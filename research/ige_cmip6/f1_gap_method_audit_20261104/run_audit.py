"""Audit frozen PR126 equations on disclosed development packets, no fitting."""
import ast
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
PACKETS = ROOT if (ROOT/'stations_2015.zip').exists() else ROOT.parent/'f1_gap_recovery_20261104'
SOURCE_DIR = ROOT if (ROOT/'station_gap_recovery.py').exists() else ROOT.parents[2]/'tools/climate_analyzer/epw_climate_analyzer'
SOURCE_GIT_SHA = {'station_gap_recovery.py': '2b155d48a8a63efc776c2b8999ded16970e3b983',
    'engine/point_interpolation.py': '688893f7aeaa23536bc25ffa18059cdfdb402080'}
PACKET_SHA256 = {2014: 'aee65a4f4d926c4fc78728205295415f0048f6ee17b31722f455e1cfa9bd92e1',
    2015: '3e7b0642b8b8078a2a843f28bb177270f2c3abfbbccc3efe726d78da0351a3f2',
    2016: '4ade92fc539d80c9af84410dc2ec7becf07307433e5b4b6ce8f000d820df222d'}
T = 'dry_bulb_temperature_c'
RH = 'relative_humidity_pct'
P = 'atmospheric_station_pressure_pa'
E = 'vapor_pressure_hpa'
FIELDS = (T, RH, P)


def load_equations():
    env = dict(T=T, RH=RH, P=P, E=E, np=np, pd=pd, math=math)
    sources = {}
    for key, expected in SOURCE_GIT_SHA.items():
        path = ROOT/'point_interpolation_original.py' if key.startswith('engine/') and SOURCE_DIR == ROOT else SOURCE_DIR/key
        body = path.read_bytes()
        assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest() == expected, 'FROZEN_SOURCE_CHANGED '+key
        sources[key] = body.decode()
    tree = ast.parse(sources['engine/point_interpolation.py'])
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ('distance_km', 'saturation_buck_hpa'):
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'frozen_geometry_and_buck', 'exec'), env)
    tree = ast.parse(sources['station_gap_recovery.py'])
    tree.body = [node for node in tree.body if not isinstance(node, ast.ImportFrom) or node.module != 'engine.point_interpolation']
    exec(compile(tree, 'frozen_station_gap_recovery', 'exec'), env)
    return env


EQ = load_equations()
SAT = EQ['saturation_buck_hpa']
EPISODE = EQ['_episode']
VALIDATE = EQ['_validate']


def read_packet(year):
    assert hashlib.sha256((PACKETS/f'stations_{year}.zip').read_bytes()).hexdigest() == PACKET_SHA256[year]
    with zipfile.ZipFile(PACKETS/f'stations_{year}.zip') as archive:
        manifest = json.loads(archive.read('manifest.json'))
        metadata = json.loads(archive.read('catalog.original.json'))
        locations = {str(v['id']): v for v in metadata['stations']}
        results = {}
        for entry in manifest['entries']:
            raw = archive.read(entry['file'])
            assert hashlib.sha256(raw).hexdigest() == manifest['members'][entry['file']]['sha256']
            frames = []
            with zipfile.ZipFile(io.BytesIO(raw)) as inner:
                source = json.loads(inner.read('manifest.json'))
                assert source['transport_error'] is None
                for record in source['responses']:
                    body = inner.read(record['path'])
                    assert hashlib.sha256(body).hexdigest() == record['sha256']
                    payload = json.loads(body)
                    if not record['query']:
                        continue
                    feature, = payload['features']
                    assert str(feature['properties']['station']) == entry['station_id']
                    native = feature['properties']['parameters']
                    f = pd.DataFrame({key: pd.to_numeric(native[key]['data'])
                        for key in ('tl', 'rf', 'p', 'tl_flag', 'rf_flag', 'p_flag')},
                        index=pd.to_datetime(payload['timestamps'], utc=True))
                    for key in ('tl', 'rf', 'p'):
                        assert (f.loc[f[key].notna(), key+'_flag'] == 10).all()
                    frames.append(f)
            frame = pd.concat(frames)
            assert not frame.index.has_duplicates
            clock = pd.date_range(f'{year}-01-01', f'{year+1}-01-01', inclusive='left', freq='h', tz='Etc/GMT-1')
            expected = clock.tz_convert('UTC') + pd.Timedelta(hours=1)
            assert frame.index.equals(expected)
            values = {T: frame['tl'].to_numpy(float), RH: frame['rf'].to_numpy(float), P: 100*frame['p'].to_numpy(float)}
            values[E] = values[RH]/100*SAT(np.where(np.isfinite(values[T]), values[T], 0))
            values[E][~np.isfinite(values[T])] = np.nan
            results[entry['station_id']] = {'values': values, 'metadata': locations[entry['station_id']],
                'clock': expected-pd.Timedelta(hours=1)}
    return results


def peer_series(rows, target):
    a = rows[target]['metadata']
    peers = [v for key, v in rows.items() if key != target]
    weights = np.array([1/max(1., EQ['distance_km'](a['lat'], a['lon'], v['metadata']['lat'], v['metadata']['lon']))**2 for v in peers])
    weights /= weights.sum()
    return {k: np.sum(weights[:, None]*np.stack([v['values'][k] for v in peers]), axis=0) for k in (*FIELDS, E)}


def linear(values, mask, i, n, vapour):
    f = {k: values[k][i:i+n].copy() for k in FIELDS}
    fraction = np.arange(1, n+1)/(n+1)
    lerp = lambda key: values[key][i-1]*(1-fraction) + values[key][i+n]*fraction
    for k in (T, P):
        f[k][mask[k]] = lerp(k)[mask[k]]
    rh = 100*lerp(E)/SAT(f[T]) if vapour else lerp(RH)
    f[RH][mask[RH]] = rh[mask[RH]]
    return f


def metrics(errors):
    return {k: {'MAE': float(np.mean(v)), 'max_abs': float(np.max(v)), 'hours': len(v)} for k, v in errors.items()}


def compare_windows(values, peer, mask, windows, n):
    errors = {name: {k: [] for k in FIELDS if mask[k].any()} for name in ('peer_anomaly', 'linear_vapour', 'linear_RH')}
    for i in windows:
        trial = {'peer_anomaly': EPISODE(values, peer, mask, i, n),
            'linear_vapour': linear(values, mask, i, n, True), 'linear_RH': linear(values, mask, i, n, False)}
        for name, fields in errors.items():
            for k, arr in fields.items():
                arr.extend(np.abs(trial[name][k][mask[k]] - values[k][i:i+n][mask[k]]))
    return {name: metrics(fields) for name, fields in errors.items()}


def main():
    controls = []
    t = np.arange(200)
    peer = {T: 10+np.sin(t/12), P: 98000+30*np.sin(t/8), E: 8+.1*np.sin(t/9)}
    values = {T: peer[T]+.2+.001*t, P: peer[P]+5+.01*t, E: peer[E]+.2+.001*t}
    values[RH] = 100*values[E]/SAT(values[T])
    peer[RH] = 100*peer[E]/SAT(peer[T])
    for n in (2, 6, 24, 61):
        mask = {k: np.ones(n, bool) for k in FIELDS}
        hidden = {k: v.copy() for k, v in values.items()}
        for k in (*FIELDS, E): hidden[k][50:50+n] = np.nan
        predicted = EPISODE(hidden, peer, mask, 50, n)
        residual = {k: float(np.max(np.abs(predicted[k]-values[k][50:50+n]))) for k in FIELDS}
        assert max(residual.values()) < 1e-9
        controls.append({'hours': n, 'affine_residual_exact_recovery': residual})
    results = {'source_commit': '56c019b63acc328c5b421bf014300f38b3e79372',
        'source_files_git_sha': SOURCE_GIT_SHA,
        'source_packets_sha256': {str(y): hashlib.sha256((PACKETS/f'stations_{y}.zip').read_bytes()).hexdigest() for y in (2014, 2015, 2016)},
        'qualification': 'DISCLOSED_DEVELOPMENT_AUDIT_NOT_INDEPENDENT_VALIDATION',
        'analytic_controls': controls, 'local_controls': [], 'matrix': {}}
    packets = {y: read_packet(y) for y in (2014, 2015, 2016)}
    for year, station in ((2015, '16412'), (2016, '16412')):
        rows = packets[year]
        values = rows[station]['values']
        peer = peer_series(rows, station)
        positions = np.flatnonzero(np.logical_or.reduce([~np.isfinite(values[k]) for k in FIELDS]))
        assert len(positions) == 2 and positions[1] == positions[0]+1
        start, n = int(positions[0]), len(positions)
        mask = {k: ~np.isfinite(values[k][start:start+n]) for k in FIELDS}
        accepted, original, windows = VALIDATE(values, peer, mask, start, n)
        assert accepted and len(windows) == 12
        comparison = compare_windows(values, peer, mask, windows, n)
        for k in original:
            assert abs(original[k]['MAE'] - comparison['peer_anomaly'][k]['MAE']) < 1e-12
        results['local_controls'].append({'year': year, 'station': station,
            'windows': [rows[station]['clock'][i].isoformat() for i in windows], 'comparison': comparison})

    # Fixed exploratory design, chosen before computing these results: all 4
    # source stations; 15th day of each month at 06:00 UTC; 2/6/24/61-hour gaps.
    # Includes disclosed 2014 regression cases; cannot qualify independent skill.
    for n in (2, 6, 24, 61):
        errors = {name: {k: [] for k in FIELDS} for name in ('peer_anomaly', 'linear_vapour', 'linear_RH')}
        physical_failures = dict.fromkeys(errors, 0)
        counts = {'planned': 144, 'complete': 0, 'paired_physical': 0, 'admitted_by_full_gate': 0}
        gate_rejections = {}
        admitted_errors = {name: {k: [] for k in FIELDS} for name in errors}
        failures = []
        for year, rows in packets.items():
            for station, row in rows.items():
                values, peer = row['values'], peer_series(rows, station)
                mask = {k: np.ones(n, bool) for k in FIELDS}
                for month in range(1, 13):
                    stamp = pd.Timestamp(f'{year}-{month:02d}-15T06:00:00Z')
                    i = row['clock'].get_loc(stamp)
                    if not all(np.isfinite(values[k][i-1:i+n+1]).all() and np.isfinite(peer[k][i-1:i+n+1]).all() for k in (*FIELDS, E)):
                        continue
                    counts['complete'] += 1
                    predictions = {'linear_vapour': linear(values, mask, i, n, True), 'linear_RH': linear(values, mask, i, n, False)}
                    try:
                        predictions['peer_anomaly'] = EPISODE(values, peer, mask, i, n)
                    except ValueError as exc:
                        physical_failures['peer_anomaly'] += 1
                        failures.append({'year': year, 'station': station, 'first_utc': stamp.isoformat(), 'reason': str(exc)})
                    for name in ('linear_vapour', 'linear_RH'):
                        valid = all(np.isfinite(predictions[name][k]).all() and
                            ((predictions[name][k] >= EQ['BOUNDS'][k][0]) & (predictions[name][k] <= EQ['BOUNDS'][k][1])).all() for k in FIELDS)
                        if not valid:
                            physical_failures[name] += 1
                            del predictions[name]
                    if len(predictions) != 3:
                        continue
                    counts['paired_physical'] += 1
                    for name in errors:
                        for k in FIELDS:
                            errors[name][k].extend(np.abs(predictions[name][k]-values[k][i:i+n]))
                    hidden = {k: v.copy() for k, v in values.items()}
                    for k in (*FIELDS, E):
                        hidden[k][i:i+n] = np.nan
                    blinded = EPISODE(hidden, peer, mask, i, n)
                    assert all(np.array_equal(blinded[k], predictions['peer_anomaly'][k]) for k in FIELDS)
                    try:
                        admitted, _, _ = VALIDATE(hidden, peer, mask, i, n)
                        reason = 'MASKED_WINDOW_ACCURACY_OR_COUNT_GATE'
                    except ValueError as exc:
                        admitted, reason = False, str(exc).split(':')[0]
                    if admitted:
                        counts['admitted_by_full_gate'] += 1
                        for name in errors:
                            for k in FIELDS:
                                admitted_errors[name][k].extend(np.abs(predictions[name][k]-values[k][i:i+n]))
                    else:
                        gate_rejections[reason] = gate_rejections.get(reason, 0)+1
        results['matrix'][str(n)] = {'counts': counts, 'physical_failures': physical_failures,
            'physical_failure_details': failures, 'gate_rejections_after_physical_pass': gate_rejections,
            'comparison_on_same_physical_windows_only': {name: metrics(fields) for name, fields in errors.items()},
            'comparison_on_same_fully_admitted_windows_only': {name: metrics(fields) for name, fields in admitted_errors.items() if all(len(v) for v in fields.values())}}
    (ROOT/'audit_results.json').write_text(json.dumps(results, indent=2)+'\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
