"""Offline NV2 audit; no production predictor, admission or scorer imported.

Inputs: exact CI ZIP/API/logs, six SHA-named private pressure products, previous
Work ZIP, and the small native metadata/coordinate cache from source geometry.
Raw observations and cache bytes are never included in the public audit JSON.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import re
import subprocess
import urllib.parse
import zipfile

import numpy as np
from numcodecs import get_codec


ROOT = Path(__file__).resolve().parents[2]
HEAD = 'f65d3ebdcfeaa9fef2605c42d9ee9104674d7861'
PREREG = 'cdc25a87ae237ccdfc584e694c06358e1a40efe4'
ZIP_SHA = 'dd4bb285c22cc081deba891c33ec2aafff549e53028103cfd09c2736ca0727ea'
WORK_ZIP_SHA = '2545012a7ace42d851ee2b418f50e2c3c30452202097fde4d9b2d6ae4bed3027'
RD, RV, G0, EARTH_R = 287.05, 461.5, 9.80665, 6371.0088
COEF = RV/RD-1


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    return sha(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode())


def blob(head, path):
    return subprocess.check_output(['git', 'show', head+':'+path], cwd=ROOT)


def read(root, name):
    return json.loads((root/'artifact'/name).read_bytes())


def archive(root, digest):
    raw = (root/'artifact.zip').read_bytes()
    assert sha(raw) == digest
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert set(z.namelist()) == {p.name for p in (root/'artifact').glob('*.json')}
        for name in z.namelist():
            assert z.read(name) == (root/'artifact'/name).read_bytes(), name


def distance(a, b):
    x, y, u, v = map(math.radians, (a['latitude'], a['longitude'], b['latitude'], b['longitude']))
    k = math.sin((x-u)/2)**2+math.cos(x)*math.cos(u)*math.sin((y-v)/2)**2
    return 2*EARTH_R*math.asin(math.sqrt(min(1., k)))


def state(c, phi):
    z = c['half_geopotential_m2s2']
    assert z[-1] <= phi <= z[0]
    # Match the declared air-side convention at an exact interface.
    j = next((j for j in range(len(z)-1) if z[j] >= phi > z[j+1]), len(z)-2)
    return c['temperature_K'][j], c['specific_humidity_kgkg'][j]


def logp(c, phi):
    z = c['half_geopotential_m2s2']
    assert z[-1] <= phi <= z[0]
    increments = []
    for j, (t, q) in enumerate(zip(c['temperature_K'], c['specific_humidity_kgkg'])):
        length = max(0., min(phi, z[j])-z[j+1])
        increments.append(-length/(RD*t*(1+COEF*q)))
    return math.log(c['half_pressure_Pa'][-1])+math.fsum(increments)


def native_blend(cs, sensor):
    ds = [distance(sensor, c) for c in cs]
    w = [1/d**2 for d in ds]
    total = math.fsum(w)
    w = [v/total for v in w]
    phi = G0*sensor['height_MSL_m']
    top = min(c['half_geopotential_m2s2'][0] for c in cs)
    anchor = math.fsum(ww*logp(c, top) for ww, c in zip(w, cs))
    boundaries = sorted({phi, top, *[v for c in cs for v in c['half_geopotential_m2s2'] if phi < v < top]})
    integral = []
    for lower, upper in zip(boundaries, boundaries[1:]):
        tq = [state(c, (lower+upper)/2) for c in cs]
        t = math.fsum(ww*v[0] for ww, v in zip(w, tq))
        q = math.fsum(ww*v[1] for ww, v in zip(w, tq))
        integral.append((upper-lower)/(RD*t*(1+COEF*q)))
    return math.exp(anchor+math.fsum(integral)), w, top


def raw_observations(private, provenance, days):
    wanted = {day+'T'+str(h).zfill(2)+':00' for day in days for h in range(24)}
    observed = {co: {} for co in ('AT', 'DE', 'CH')}
    products, series = [], {}
    def source(record):
        raw = (private/(record['sha256']+'.bin')).read_bytes()
        assert sha(raw) == record['sha256']
        products.append({**record, 'bytes': len(raw)})
        return raw
    for record in provenance['AT']['sources']:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(record['url']).query)
        if 'station_ids' not in query:
            continue
        day, station = query['start'][0][:10], int(query['station_ids'][0])
        obj = json.loads(source(record))
        assert len(obj['features']) == 1
        fields = obj['features'][0]['properties']['parameters']
        assert fields['p']['unit'] == 'hPa'
        times = [dt.datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M')
                 for t in obj['timestamps']]
        assert times == [day+'T'+str(h).zfill(2)+':00' for h in range(24)]
        series[day, station] = times, fields['p']['data'], fields['p_flag']['data']
    for day in days:
        assert series[day, 30] == series[day, 16412]
        times, values, flags = series[day, 30]
        for t, v, flag in zip(times, values, flags):
            assert flag == 10 and 450 < float(v) < 1100
            observed['AT'][t] = float(v)*100
    records = provenance['DE']['sources']
    assert len(records) == 1
    with zipfile.ZipFile(io.BytesIO(source(records[0]))) as z:
        names = [n for n in z.namelist() if n.startswith('produkt') and n.endswith('.txt')]
        assert len(names) == 1
        description = z.read('Metadaten_Parameter_zehn_st_min_p0_00399.txt').decode('latin1')
        assert 'P0_ST_10;momentaner Luftdruck Stationshoehe;' in description
        assert 'PP_ST_10;momentaner Luftdruck Normal Null;' in description
        for raw in csv.DictReader(io.StringIO(z.read(names[0]).decode('latin1')), delimiter=';'):
            row = {k.strip(): v.strip() for k, v in raw.items() if k is not None}
            date = row['MESS_DATUM']
            if len(date) != 12 or not date.endswith('00'):
                continue
            t = dt.datetime.strptime(date, '%Y%m%d%H%M').strftime('%Y-%m-%dT%H:%M')
            if t not in wanted:
                continue
            assert int(row['STATIONS_ID']) == 399 and row['QN'] == '3' and t not in observed['DE']
            value = float(row['P0_ST_10'])
            assert 450 < value < 1100
            observed['DE'][t] = value*100
    records = provenance['CH']['sources']
    assert len(records) == 1
    for row in csv.DictReader(io.StringIO(source(records[0]).decode('utf-8-sig')), delimiter=';'):
        t = dt.datetime.strptime(row['reference_timestamp'], '%d.%m.%Y %H:%M').strftime('%Y-%m-%dT%H:%M')
        if t not in wanted:
            continue
        assert row['station_abbr'].strip().upper() == 'DAV' and t not in observed['CH']
        value = float(row['prestah0'])
        assert 450 < value < 1100
        observed['CH'][t] = value*100
    assert len(products) == 6 and all(set(v) == wanted for v in observed.values())
    return observed, products


def predicted(p, stamp, country, method, *, g0=False):
    def node(t):
        value = p[t][country]
        if g0:
            value = value['G0']
        return value['methods'][method].get('pressure_Pa')
    value = node(stamp)
    if country == 'CH' and value is not None:
        previous = (dt.datetime.fromisoformat(stamp)-dt.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
        earlier = node(previous)
        value = None if earlier is None else (value+earlier)/2
    return value


def metrics(errors):
    return {'MAE_hPa': math.fsum(abs(v) for v in errors)/len(errors),
            'bias_hPa': math.fsum(errors)/len(errors),
            'RMSE_hPa': math.sqrt(math.fsum(v*v for v in errors)/len(errors)),
            'max_abs_error_hPa': max(abs(v) for v in errors)}


def audit_scores(score, p, observed, *, g0=False):
    maximum, cells, pairs = 0., 0, 0
    for row in score['cells']:
        co, day, method = row['country'], row['day'], row['method']
        errors = []
        for hour in range(24):
            stamp = day+'T'+str(hour).zfill(2)+':00'
            value = predicted(p, stamp, co, method, g0=g0)
            if value is not None:
                errors.append((value-observed[co][stamp])/100)
        assert row['matched_hours'] == len(errors) and row['coverage'] == len(errors)/24
        gate = 'INCONCLUSIVE_COVERAGE'
        if errors:
            for key, value in metrics(errors).items():
                maximum = max(maximum, abs(value-row[key]))
            if len(errors) >= 24*.9:
                gate = 'PASS_THIS_REVEALED_CELL' if metrics(errors)['MAE_hPa'] <= 2 else 'FAIL_THIS_REVEALED_CELL'
        assert row['accuracy_gate'] == gate and row['independently_qualified'] is False
        cells += 1
    for pair in score['paired_comparisons']:
        a, b, matched = [], [], []
        co, day = pair['country'], pair['day']
        for hour in range(24):
            stamp = day+'T'+str(hour).zfill(2)+':00'
            pa = predicted(p, stamp, co, pair['method'], g0=g0)
            pb = predicted(p, stamp, co, pair['baseline'], g0=g0)
            if pa is not None and pb is not None:
                a.append((pa-observed[co][stamp])/100)
                b.append((pb-observed[co][stamp])/100)
                matched.append(stamp)
        assert pair['paired_hours'] == len(matched)
        if not g0:
            assert pair['matched_timestamps_UTC'] == matched
        if matched:
            ma, mb = metrics(a), metrics(b)
            for key in ('MAE_hPa', 'RMSE_hPa'):
                maximum = max(maximum, abs(ma[key]-mb[key]-pair['delta_'+key]))
            if not g0:
                for key in ma:
                    maximum = max(maximum, abs(ma[key]-pair['method_metrics'][key]), abs(mb[key]-pair['baseline_metrics'][key]))
        pairs += 1
    assert maximum < 1e-10
    return {'cells': cells, 'paired_comparisons': pairs, 'max_metric_delta_hPa': maximum}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--evidence-dir', type=Path, required=True)
    ap.add_argument('--work-evidence-dir', type=Path, required=True)
    ap.add_argument('--private-observation-dir', type=Path, required=True)
    ap.add_argument('--private-native-cache', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    assert not args.out.exists(), 'AUDIT_OUTPUT_EXISTS_NO_OVERWRITE'
    root, oldroot = args.evidence_dir, args.work_evidence_dir
    archive(root, ZIP_SHA)
    archive(oldroot, WORK_ZIP_SHA)
    api = json.loads((root/'api_evidence.json').read_bytes())
    run = api['run']
    assert run['id'] == 39925504607 and run['head_sha'] == HEAD
    assert run['status'] == 'completed' and run['conclusion'] == 'success'
    assert len(api['jobs']['jobs']) == 2 and all(j['conclusion'] == 'success' for j in api['jobs']['jobs'])
    artifact = api['artifacts']['artifacts'][0]
    assert artifact['id'] == 12489671619 and artifact['digest'] == 'sha256:'+ZIP_SHA
    m = read(root, 'run_manifest.json')
    s = read(root, 'revealed_pressure_scores_NV2.json')
    g0scores = read(root, 'G0_regression_pressure_scores.json')
    geometry = read(root, 'source_geometry_and_fixed_donors.json')
    heights = read(root, 'historical_sensor_references.json')
    lineage = read(root, 'native_source_lineage.json')
    seal = read(root, 'prediction_seal.json')
    pred = read(root, 'sealed_pressure_predictions.json')
    p = pred['hourly']
    primary = read(root, 'native_primary_profiles.json')
    deep = read(root, 'deep_column_sensitivity.json')
    oldp = read(oldroot, 'sealed_pressure_predictions.json')['hourly']
    oldm = read(oldroot, 'run_manifest.json')
    oldheights = read(oldroot, 'historical_sensor_references.json')
    raw = blob(HEAD, 'research/ige_cmip6/p9_3b3_nv2_protocol.json')
    protocol = json.loads(raw)
    assert raw == blob(PREREG, 'research/ige_cmip6/p9_3b3_nv2_protocol.json')
    assert sha(raw) == m['protocol_sha256'] == pred['protocol_sha256']
    assert fingerprint(protocol) == m['protocol_canonical_sha256']
    assert m['git_head'] == HEAD and m['protected_control_count'] == len(protocol['protected_control_sha256']) == 80
    for path, digest in protocol['protected_control_sha256'].items():
        assert sha(blob(HEAD, path)) == sha(blob(PREREG, path)) == sha((ROOT/path).read_bytes()) == digest, path
    for name, digest in m['code_sha256'].items():
        assert sha(blob(HEAD, 'research/ige_cmip6/'+name)) == digest
    assert m['sealed_products_sha256'] == seal['source_products_sha256'] == s['sealed_inputs_sha256'] == g0scores['sealed_inputs_sha256']
    assert seal['station_pressure_products_opened'] is False
    for name, digest in seal['source_products_sha256'].items():
        assert sha((root/'artifact'/name).read_bytes()) == digest
    assert len(seal['source_products_sha256']) == 6
    logs = {key: (root/(key+'.log')).read_bytes() for key in ('contracts', 'pilot')}
    counts = list(map(int, re.findall(r'Ran (\d+) tests', logs['contracts'].decode())))
    assert counts == [251, 14, 50, 8]
    assert 'Protected files: 80 changed: 0' in logs['contracts'].decode()
    assert 'P93B2D_ORIGINAL_PRESSURE_FIELD_SEMANTICS_CONTRACTS_PASS' in logs['contracts'].decode()
    text = logs['pilot'].decode()
    assert text.index('NV2_SOURCE_PRODUCTS_SEALED_OPEN_REVEALED_PRESSURE_OBSERVATIONS') < text.index('"engineering_execution_status": "COMPLETE_SOURCE_EXECUTION"')
    hours = {day+'T'+str(h).zfill(2)+':00' for day in protocol['development_days'] for h in range(24)}
    hours |= {'2021-01-31T23:00', '2021-07-31T23:00'}
    assert set(primary) == set(p) == hours and len(hours) == 50
    assert m['source_profile_hours_complete'] == m['source_profile_hours_expected'] == 50
    assert m['source_blockers'] == [] and m['historical_sensor_countries_confirmed'] == 3
    assert len(s['cells']) == 26 and len(s['paired_comparisons']) == 54 and len(g0scores['cells']) == 24
    assert all(c['matched_hours'] == 24 and c['accuracy_gate'] == 'PASS_THIS_REVEALED_CELL' for c in s['cells'])
    assert len({(c['country'], c['day'], c['method']) for c in s['cells']}) == 26
    assert {(c['country'], c['day'], c['method']) for c in s['cells']} == {
        (co, day, method) for co in protocol['countries'] for day in protocol['development_days']
        for method in protocol['methods_by_country'][co]}
    assert set(deep) == {'2021-02-01T00:00', '2021-08-01T00:00'}
    assert all(heights[co]['reference_refresh'] == 'WMDR_SEMANTIC_IDENTITY_CONFIRMED' for co in protocol['countries'])
    for co in protocol['countries']:
        for role in protocol['roles']:
            a, b = heights[co]['sensors'][role], oldheights[co]['sensors'][role]
            assert {k: v for k, v in a.items() if k != 'source_sha256'} == {k: v for k, v in b.items() if k != 'source_sha256'}
    assert s['observation_provenance'] == g0scores['observation_provenance']
    previous_provenance = read(oldroot, 'revealed_pressure_scores.json')['observation_provenance']
    for co, current in s['observation_provenance'].items():
        previous = previous_provenance[co]
        assert {k: v for k, v in current.items() if k != 'sources'} == {k: v for k, v in previous.items() if k != 'sources'}
        assert [r for r in current['sources'] if '/metadata' not in r['url']] == [
            r for r in previous['sources'] if '/metadata' not in r['url']]
    observed, products = raw_observations(args.private_observation_dir, s['observation_provenance'], protocol['development_days'])
    nv2_replay = audit_scores(s, p, observed)
    g0_replay = audit_scores(g0scores, p, observed, g0=True)
    assert (nv2_replay['cells'], nv2_replay['paired_comparisons']) == (26, 54)
    assert (g0_replay['cells'], g0_replay['paired_comparisons']) == (24, 16)

    # Decode only the small native coordinates and metadata, by their CI hashes.
    objects = {o['url']+'|'+str(o['range']): o for o in m['source_objects']}
    positions = {o['url']: j for j, o in enumerate(m['source_objects'])}
    last_model_object = max(j for j, o in enumerate(m['source_objects']) if 'storage.googleapis.com' in o['url'])
    assert all(positions[record['url']] > last_model_object for record in products)
    def cached(url):
        raw = (args.private_native_cache/(sha(url.encode())+'.bin')).read_bytes()
        assert sha(raw) == objects[url+'|None']['sha256'], url
        return raw
    moisture = 'https://storage.googleapis.com/gcp-public-data-arco-era5/co/model-level-moisture.zarr-v2'
    metadata = json.loads(cached(moisture+'/.zmetadata'))['metadata']
    def coordinate(name):
        encoding = metadata[name+'/.zarray']
        assert encoding['shape'] == [542080] and encoding['chunks'] == [542080]
        decoded = get_codec(encoding['compressor']).decode(cached(moisture+'/'+name+'/0'))
        return np.frombuffer(decoded, dtype=np.dtype(encoding['dtype']))
    lat, lon = coordinate('latitude'), coordinate('longitude')
    assert len(np.unique(lat)) == 640
    xyz = np.column_stack((np.cos(np.deg2rad(lat))*np.cos(np.deg2rad(lon)),
                           np.cos(np.deg2rad(lat))*np.sin(np.deg2rad(lon)), np.sin(np.deg2rad(lat))))
    def all_distances(sensor):
        la, lo = math.radians(sensor['latitude']), math.radians(sensor['longitude'])
        u = np.array([math.cos(la)*math.cos(lo), math.cos(la)*math.sin(lo), math.sin(la)])
        return EARTH_R*np.arctan2(np.linalg.norm(np.cross(xyz, u), axis=1), xyz@u)
    census = {}
    for co in protocol['countries']:
        rows = geometry['full_radius_catalogue'][co]
        ds = {role: all_distances(heights[co]['sensors'][role]) for role in protocol['roles']}
        expected = set(np.flatnonzero(np.min(list(ds.values()), axis=0) <= 50).tolist())
        assert expected == {row['native_index'] for row in rows}
        for row in rows:
            index = row['native_index']
            assert row['latitude'] == lat[index] and row['longitude'] == lon[index]
            surface_values = list(row['surface_phi_m2s2_by_control'].values())
            assert max(surface_values)-min(surface_values) <= G0*.25
            assert abs(row['surface_H_m']-surface_values[0]/G0) < 1e-12
            for role, admission in row['roles'].items():
                assert abs(admission['distance_km']-ds[role][index]) < 1e-7
                margin = heights[co]['sensors'][role]['height_MSL_m']-row['surface_H_m']
                assert abs(margin-admission['target_minus_surface_m']) < 1e-12
                assert admission['lower_boundary_admitted'] == (ds[role][index] <= 50 and margin >= 0)
                assert admission['buffer_2m_sensitivity_admitted'] == (ds[role][index] <= 50 and margin >= 2)
        valid = [r for r in rows if r['roles']['pressure']['lower_boundary_admitted']]
        if co != 'AT':
            closest = min(valid, key=lambda r: (r['roles']['pressure']['distance_km'], r['latitude'], r['longitude']))
            assert geometry['fixed_pressure_donor_slots'][co] == {'D1': closest['native_index']}
        else:
            for fixed in protocol['AT_pressure_donors']:
                row = next(r for r in valid if r['latitude'] == fixed['latitude'] and r['longitude'] == fixed['longitude'])
                assert geometry['fixed_pressure_donor_slots'][co][fixed['slot']] == row['native_index']
        census[co] = {'points': len(rows), 'all_native_coordinates_checked': len(lat),
                      'minimum_distance_to_radius_boundary_km': float(np.min(abs(np.r_[*ds.values()]-50)))}

    pv = metadata['q/.zattrs']['GRIB_pv']
    assert len(pv) == 276 and fingerprint(pv) == lineage['GRIB_pv_sha256']
    assert len(lineage['original_GRIB_controls']) == 4
    assert all(c['status'] == 'ORIGINAL_GRIB_TO_CO_FLOAT32_EXACT' and c['coefficient_count'] == 410240
               for c in lineage['original_GRIB_controls'])
    assert lineage['original_GRIB_controls'] == read(oldroot, 'native_source_lineage.json')['original_GRIB_controls']
    layer_checks, pressure_checks, admission_checks = 0, 0, 0
    hydro_max, pressure_max, hybrid_max, alpha_max = 0., 0., 0., 0.
    role_counts = collections.Counter()
    single_layer_AT_D1, single_layer_AT_D1_max_delta = 0, 0.
    depth, geometry_margins, blend_support = {}, {}, {}
    def check_columns(cols, stamp):
        nonlocal layer_checks, hydro_max, hybrid_max, alpha_max
        for c in cols.values():
            z, pr = c['half_geopotential_m2s2'], c['half_pressure_Pa']
            t, q, first = c['temperature_K'], c['specific_humidity_kgkg'], c['first_level']
            assert c['timestamp_UTC'] == stamp and c['gas'] == 'B3_GAS_CONSISTENT'
            assert len(t) == 138-first and len(z) == len(pr) == len(t)+1
            assert all(100 < v < 360 for v in t) and all(0 <= v < .1 for v in q)
            assert all(a < b for a, b in zip(pr, pr[1:])) and all(a > b for a, b in zip(z, z[1:]))
            for j, (tt, qq) in enumerate(zip(t, q)):
                residual = z[j]-z[j+1]-RD*tt*(1+COEF*qq)*math.log(pr[j+1]/pr[j])
                hydro_max = max(hydro_max, abs(residual))
                alpha = 1-pr[j]/(pr[j+1]-pr[j])*math.log(pr[j+1]/pr[j])
                alpha_phi = z[j+1]+RD*tt*(1+COEF*qq)*alpha
                alpha_max = max(alpha_max, abs(alpha_phi-c['full_geopotential_ECMWF_alpha_m2s2'][j]))
                assert abs((pr[j]+pr[j+1])/2-c['full_pressure_Pa'][j]) < 1e-8
                layer_checks += 1
            for j, value in enumerate(pr):
                k = first-1+j
                hybrid_max = max(hybrid_max, abs(value-pv[k]-pv[138+k]*pr[-1]))
    def check_prediction(prediction, cols, stamp, scope):
        nonlocal pressure_checks, admission_checks, pressure_max, single_layer_AT_D1, single_layer_AT_D1_max_delta
        for co, result in prediction.items():
            slots = geometry['fixed_pressure_donor_slots'][co]
            assert result['methods'] == result['roles']['pressure']['methods']
            for role, role_result in result['roles'].items():
                sensor = heights[co]['sensors'][role]
                phi = G0*sensor['height_MSL_m']
                assert role_result['target_sensor'] == sensor
                assert set(role_result['methods']) == set(protocol['methods_by_country'][co])
                assert role_result['direct_barometer_truth_at_this_role'] == (role == 'pressure')
                eligible = {}
                for slot, index in slots.items():
                    c = cols[str(index)]
                    valid = distance(sensor, c) <= 50 and c['half_geopotential_m2s2'][-1] <= phi <= c['half_geopotential_m2s2'][0]
                    a = role_result['admissions'][slot]
                    assert a['admitted'] == valid and a['profile_fingerprint'] == fingerprint(c)
                    admission_checks += 1
                    if valid:
                        eligible[slot] = c
                    if scope == 'PRIMARY':
                        role_counts[co+'|'+role+'|'+slot+'|'+('ADMITTED' if valid else 'BLOCKED')] += 1
                        geometry_margins[co+'|'+role+'|'+slot] = {
                            'surface_H_m': a['surface_H_m'], 'target_minus_surface_m': a['target_minus_surface_m'],
                            'buffer_2m_pass': a['buffer_2m_lower_boundary_sensitivity_pass']}
                for method, v in role_result['methods'].items():
                    if method == 'P2_FIXED_D1_D2_BLEND':
                        valid = len(eligible) == 2
                        if valid:
                            cs = [eligible[k] for k in ('D1', 'D2')]
                            expected, weights, top = native_blend(cs, sensor)
                            assert abs(top-v['anchor_phi_m2s2']) < 1e-8
                            assert all(abs(a['weight']-w) < 1e-12 for a, w in zip(v['active_columns'], weights))
                            support = role_result['horizontal_support']
                            assert not support['target_in_nonnegative_weight_convex_hull']
                            assert not support['full_2D_gradient_identifiable']
                            offsets = [[EARTH_R*math.cos(math.radians(sensor['latitude']))*math.radians(c['longitude']-sensor['longitude']),
                                        EARTH_R*math.radians(c['latitude']-sensor['latitude'])] for c in cs]
                            moment = [math.fsum(w*offset[j] for w, offset in zip(weights, offsets)) for j in (0, 1)]
                            assert max(abs(a-b) for a, b in zip(moment, support['first_moment_east_north_km'])) < 1e-8
                            assert abs((logp(cs[1], phi)-logp(cs[0], phi))-support['same_target_phi_native_log_pressure_D2_minus_D1']) < 1e-12
                            if scope == 'PRIMARY':
                                blend_support[co+'|'+role] = {'weights': weights, 'first_moment_east_north_km': moment,
                                                              'first_moment_norm_km': math.hypot(*moment), 'full_2D_gradient_identifiable': False}
                    else:
                        slot = method.rsplit('_', 1)[-1]
                        valid = slot in eligible
                        if valid:
                            c = eligible[slot]
                            assert v['source_column_fingerprint'] == fingerprint(c)
                            assert v['anchor_phi_m2s2'] == c['half_geopotential_m2s2'][-1]
                            assert abs(v['anchor_log_pressure']-math.log(c['half_pressure_Pa'][-1])) < 1e-13
                            t, q = state(c, phi)
                            assert (t, q) == (v['target_layer_T_K'], v['target_layer_q_kgkg'])
                            dz = (phi-c['half_geopotential_m2s2'][-1])/G0
                            if method.startswith('P2'):
                                expected = math.exp(logp(c, phi))
                            elif method.startswith('P1_ISO'):
                                expected = c['half_pressure_Pa'][-1]*math.exp(-G0*dz/(RD*t*(1+COEF*q)))
                            else:
                                expected = c['half_pressure_Pa'][-1]*(t/(t+.0065*dz))**(G0/(RD*(1+COEF*q)*.0065))
                    assert ('pressure_Pa' in v) == valid, (scope, stamp, co, role, method)
                    if valid:
                        pressure_max = max(pressure_max, abs(v['pressure_Pa']-expected))
                        pressure_checks += 1
                        if scope == 'DEEP':
                            original = p[stamp][co]['roles'][role]['methods'][method]['pressure_Pa']
                            key = co+'|'+role+'|'+method
                            depth[key] = max(depth.get(key, 0), abs(v['pressure_Pa']-original)/100)
                if scope == 'PRIMARY' and co == 'AT' and role == 'pressure':
                    a = cols[str(slots['D1'])]
                    assert phi <= a['half_geopotential_m2s2'][-2]
                    methods = role_result['methods']
                    single_layer_AT_D1 += 1
                    single_layer_AT_D1_max_delta = max(single_layer_AT_D1_max_delta,
                        abs(methods['P1_ISOTHERMAL_D1']['pressure_Pa']-methods['P2_NATIVE_D1']['pressure_Pa']))
    for stamp, cols in primary.items():
        assert len(cols) == 14 and all(c['first_level'] == 124 for c in cols.values())
        check_columns(cols, stamp)
        check_prediction(p[stamp], cols, stamp, 'PRIMARY')
    for stamp, value in deep.items():
        cols = value['columns']
        assert len(cols) == 14 and all(c['first_level'] == 109 for c in cols.values())
        check_columns(cols, stamp)
        check_prediction(value['predictions'], cols, stamp, 'DEEP')
    assert hydro_max < 1e-8 and hybrid_max < 1e-8 and alpha_max < 1e-8 and pressure_max < 1e-6
    assert (layer_checks, admission_checks, pressure_checks) == (10612, 624, 1612)

    g0_deltas, g0_count, g0_bit_changes = [], 0, 0
    for stamp in hours:
        for co in protocol['countries']:
            old = oldp[stamp][co]['methods']
            new = p[stamp][co]['G0']['methods']
            for method, a in old.items():
                b = new[method]
                assert ('pressure_Pa' in a) == ('pressure_Pa' in b)
                if 'pressure_Pa' in a:
                    delta = abs(a['pressure_Pa']-b['pressure_Pa'])
                    g0_deltas.append(delta)
                    g0_count += 1
                    g0_bit_changes += delta > 0
    assert max(g0_deltas) < 1e-6 and g0_count == 400
    oldobjects = {o['url']+'|'+str(o['range']): o for o in oldm['source_objects']}
    shared = set(objects)&set(oldobjects)
    changed = [{'url': objects[k]['url'], 'before': oldobjects[k]['sha256'], 'after': objects[k]['sha256']}
               for k in sorted(shared) if objects[k]['sha256'] != oldobjects[k]['sha256']]
    # Metadata byte drift must remain visible; it is not field-value drift.
    # Previous complete .zmetadata/XML bodies were not exported by Work, so
    # do not invent a cause for their SHA changes or assert full identity.
    assert {o['url'] for o in changed} == {
        'https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h/metadata',
        'https://oscar.wmo.int/surface/rest/api/wmd/download/0-20000-0-11290',
        'https://oscar.wmo.int/surface/rest/api/wmd/download/0-276-6-399',
        'https://storage.googleapis.com/gcp-public-data-arco-era5/co/model-level-moisture.zarr-v2/.zmetadata',
        'https://storage.googleapis.com/gcp-public-data-arco-era5/co/model-level-wind.zarr-v2/.zmetadata'}
    assert len(objects) == m['network_requests'] == 1660
    assert sum(o['bytes'] for o in objects.values()) == m['network_downloaded_bytes'] == 2194021975
    chunks = {name: sum('/'+name+'/' in o['url'] for o in objects.values()) for name in ('t', 'q')}
    assert chunks == {'t': 730, 'q': 730}
    report = {
        'phase': 'P9.3B3_NV2_CI_INDEPENDENT_RESULT_REPLAY', 'run_id': 39925504607,
        'audit_code_sha256': sha(Path(__file__).read_bytes()),
        'gas_constants': {'Rd_J_kg_K': RD, 'Rv_J_kg_K': RV, 'g0_m_s2': G0},
        'html_url': run['html_url'], 'head_sha': HEAD, 'preregistered_parent_sha': PREREG,
        'conclusion': run['conclusion'], 'updated_at_UTC': run['updated_at'], 'tests_passed': sum(counts),
        'job_log_sha256': {k: sha(v) for k, v in logs.items()}, 'artifact_id': artifact['id'],
        'artifact_zip_sha256': ZIP_SHA, 'artifact_file_sha256': {f.name: sha(f.read_bytes()) for f in sorted((root/'artifact').glob('*.json'))},
        'protocol_sha256': m['protocol_sha256'], 'protected_scientific_files': 80, 'protected_changed': 0,
        'engineering': {'complete_source_hours': 50, 'dated_sensor_countries': 3, 'source_blockers': [],
                        'NV2_score_cells': 26, 'NV2_cells_full_24h_and_dev_gate_pass': 26, 'G0_score_cells': 24,
                        'unique_matched_station_hours': 144, 'new_independent_holdout': False},
        'geometry_census': census, 'fixed_donors': geometry['fixed_pressure_donor_slots'],
        'instrument_lower_margins': geometry_margins, 'hourly_admission_counts': dict(role_counts),
        'horizontal_blend_support': blend_support,
        'independent_equation_replay': {'source_column_records': 728, 'hydrostatic_layer_equations': layer_checks,
             'max_hydrostatic_residual_m2s2': hydro_max, 'max_hybrid_pressure_residual_Pa': hybrid_max,
             'max_ECMWF_alpha_phi_residual_m2s2': alpha_max, 'role_donor_admissions_checked': admission_checks,
             'NV2_role_pressure_results_recomputed': pressure_checks, 'max_pressure_delta_Pa': pressure_max,
             'production_model_helpers_imported': False},
        'raw_score_replay': {'products': products, 'valid_station_hours': {k: len(v) for k, v in observed.items()},
                             'NV2': nv2_replay, 'G0': g0_replay, 'raw_observations_in_public_output': False,
                             'AT_individual_combined_exact': True, 'DWD_absolute_field': 'P0_ST_10',
                             'DWD_QN': 3, 'CH_boundary_mean_operator_replayed': True},
        'G0_regression_to_Work': {'source_node_pressures_compared': g0_count, 'nonbitexact_values': int(g0_bit_changes),
                                 'max_pressure_delta_Pa': max(g0_deltas), 'common_source_objects': len(shared),
                                 'changed_common_source_objects': changed,
                                 'all_common_T_q_z_lnsp_data_chunk_hashes_identical': True,
                                 'all_six_station_pressure_product_hashes_identical': True,
                                 'metadata_byte_change_cause': 'NOT_IDENTIFIED_PREVIOUS_FULL_METADATA_BODIES_NOT_EXPORTED'},
        'AT_D1_P1_P2_equivalence': {'hours_target_inside_lowest_constant_Tv_layer': single_layer_AT_D1,
                                   'max_abs_P1iso_minus_P2_Pa': single_layer_AT_D1_max_delta,
                                   'interpretation': 'MATHEMATICAL_SAME_LAYER_EQUIVALENCE_NOT_EXTRA_P2_SKILL'},
        'deep_vs_primary_max_pressure_delta_hPa': depth,
        'cells': s['cells'], 'paired_comparisons': s['paired_comparisons'],
        'resources': {k: m[k] for k in ('network_downloaded_bytes', 'network_requests', 'wall_seconds', 'peak_RSS_KiB')},
        'chunks': chunks, 'science': {'code_contracts': '323_TESTS_PASS_AT_TESTED_COMMIT',
             'physical_scope': 'CONDITIONAL_AIR_COLUMN_GAS_HYDROSTATICS_NOT_DATUM_SURFACE_LAYER_OR_SATURATION_QUALIFICATION',
             'independent_accuracy': 'NOT_QUALIFIED_REVEALED_TWO_DAY_PILOT', 'P2_general_advantage_established': False,
             'operational_readiness': 'NOT_QUALIFIED', 'B4_qualified': False, 'production_epw_ready': False,
             'native_future_CanESM5_pressure_recovered': False, 'main_modified': False, 'merge_performed': False}}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: report[k] for k in ('tests_passed', 'engineering', 'independent_equation_replay',
                                            'AT_D1_P1_P2_equivalence', 'G0_regression_to_Work')}))
    print('RAW_SCORE_REPLAY', json.dumps({'NV2': nv2_replay, 'G0': g0_replay}))


if __name__ == '__main__':
    main()
