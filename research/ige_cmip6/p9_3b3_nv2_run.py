"""NV2: frozen geometry -> native profiles -> sealed predictions -> scores.

Technical completeness is distinct from geometry and independent skill.
Output directories are never reused. Station pressure products open only
after the source-only products have been written and hashed.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import datetime as dt
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import subprocess
import time
from xml.etree import ElementTree as ET

from p9_3b3_compare_vertical_frame import SourceBlocked, fingerprint
from p9_3b3_native_heights import sensor_records
from p9_3b3_native_run import protocol_guard as source_protocol_guard, write_json
from p9_3b3_native_sources import NativeCache
from p9_3b3_native_validation import score_pressure, target_hours
from p9_3b3_nv2_columns import NV2Columns
from p9_3b3_nv2_validation import score_after_seal, score_nv2
from p9_3b3_reference_run import protected_controls


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = Path(__file__).with_name('p9_3b3_nv2_protocol.json')
PROTOCOL_CANONICAL_SHA256 = '4e00ddbb585ceeb1f93feaa7d033081b1c2ff22427a2e82cc98302f77df9b004'


def protocol_guard(protocol):
    if fingerprint(protocol) != PROTOCOL_CANONICAL_SHA256:
        raise ValueError('NV2_FROZEN_DESIGN_DRIFT_REQUIRES_NEW_PROTOCOL_VERSION')
    return protocol


def source_hours(protocol):
    return sorted(set(target_hours(protocol)+[
        (dt.datetime.fromisoformat(day)-dt.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
        for day in protocol['development_days']]))


def refresh_sensor_references(cache, protocol, source_protocol):
    """Refresh ONLY WMDR; do not fetch a DWD pressure archive for metadata."""
    path = ROOT/protocol['dated_sensor_reference_file']
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != protocol['dated_sensor_reference_sha256']:
        raise ValueError('NV2_FROZEN_SENSOR_REFERENCE_CHANGED')
    frozen = json.loads(raw)
    result = copy.deepcopy(frozen['countries'])
    stamps = source_hours(protocol)
    for country in protocol['countries']:
        old = result[country]
        try:
            wsi = source_protocol['station_WSI'][country]
            url = 'https://oscar.wmo.int/surface/rest/api/wmd/download/'+wsi
            xml = cache.fetch(url, limit=3_000_000)
            sensors = {key: sensor_records(xml, wsi, code, stamps, role)
                       for key, code, role in (('pressure', 216, 'BAROMETER'),
                                               ('temperature', 224, 'THERMO_SENSOR'),
                                               ('RH_water', 12249, 'THERMO_SENSOR'))}
            for key, value in sensors.items():
                a = {k: v for k, v in value.items() if k != 'source_sha256'}
                b = {k: v for k, v in old['sensors'][key].items() if k != 'source_sha256'}
                if a != b:
                    raise SourceBlocked('NV2_DATED_SENSOR_SEMANTICS_CHANGED_NEW_DESIGN_REQUIRED:'+key)
            old.update(sensors=sensors, source_WMDR=url, source_WMDR_sha256=hashlib.sha256(xml).hexdigest(),
                       provider_identity_policy='FROZEN_PREVIOUSLY_AUDITED_METADATA_NO_OBSERVATION_PRODUCT_READ',
                       reference_refresh='WMDR_SEMANTIC_IDENTITY_CONFIRMED',
                       prior_WMDR_sha256=frozen['countries'][country]['source_WMDR_sha256'])
        except (SourceBlocked, OSError, ValueError, KeyError, ET.ParseError) as exc:
            result[country] = {'status': 'SOURCE_BLOCKED', 'reason': type(exc).__name__+':'+str(exc)}
    return result


def blocked_prediction(protocol, reason):
    return {co: {'methods': {m: {'status': 'SOURCE_BLOCKED', 'reason': reason}
                             for m in protocol['methods_by_country'][co]}, 'roles': {},
                 'G0': {'methods': {m: {'status': 'SOURCE_BLOCKED', 'reason': reason}
                                    for m in protocol['G0_regression_methods']}}}
            for co in protocol['countries']}


def execution_summary(protocol, profiles, source, heights, score, *, stations):
    hours = source_hours(protocol)
    complete = sum(stamp in profiles for stamp in hours)
    lineage = source.get('paired_surface_lineage_status') == 'ORIGINAL_GRIB_TO_CO_CAST_IDENTITY_CONFIRMED_AT_BOTH_CONTROL_HOURS'
    dated = all(heights.get(co, {}).get('reference_refresh') == 'WMDR_SEMANTIC_IDENTITY_CONFIRMED'
                for co in protocol['countries'])
    observations = not stations or (score is not None and all(
        score.get('observation_provenance', {}).get(co, {}).get('status') == 'SOURCE_READ'
        for co in protocol['countries']))
    cells = not stations or (score is not None and len(score['cells']) == protocol['expected_pressure_score_cells'])
    success = complete == len(hours) and lineage and dated and observations and cells
    return {'engineering_execution_status': 'COMPLETE_SOURCE_EXECUTION' if success else 'INCOMPLETE_SOURCE_EXECUTION',
            'source_profile_hours_expected': len(hours), 'source_profile_hours_complete': complete,
            'historical_sensor_countries_confirmed': sum(h.get('reference_refresh') == 'WMDR_SEMANTIC_IDENTITY_CONFIRMED'
                                                        for h in heights.values()),
            'observation_sources_complete': observations, 'score_cell_census_complete': cells,
            'code_correctness': 'REQUIRES_SEPARATE_TEST_JOB_EVIDENCE',
            'physical_admissibility': 'CONDITIONAL_GAS_HYDROSTATIC_AIR_DOMAIN_ONLY',
            'independent_accuracy': 'NOT_QUALIFIED_REVEALED_TWO_DAY_PILOT',
            'operational_readiness': 'NOT_QUALIFIED',
            'B4_qualified': False, 'production_epw_ready': False,
            'native_future_CanESM5_pressure_recovered': False}


def run(out, private_cache, *, stations=False, cache_only=False, protocol_path=PROTOCOL):
    out, cache_path = Path(out), Path(private_cache)
    if out.exists():
        raise ValueError('NV2_OUTPUT_EXISTS_NO_OVERWRITE')
    if out.resolve() in (cache_path.resolve(), *cache_path.resolve().parents):
        raise ValueError('NV2_PRIVATE_CACHE_INSIDE_OUTPUT')
    started = time.perf_counter()
    raw = Path(protocol_path).read_bytes()
    p = protocol_guard(json.loads(raw))
    source_raw = (ROOT/p['source_protocol_file']).read_bytes()
    if hashlib.sha256(source_raw).hexdigest() != p['source_protocol_sha256']:
        raise ValueError('NV2_FROZEN_NATIVE_SOURCE_PROTOCOL_CHANGED')
    base = source_protocol_guard(json.loads(source_raw))
    protected = protected_controls(p)
    out.mkdir(parents=True)
    cache = NativeCache(cache_path, base, cache_only=cache_only)
    heights = refresh_sensor_references(cache, p, base)
    write_json(out/'historical_sensor_references.json', heights)
    manifest = {'phase': p['phase'], 'protocol_sha256': hashlib.sha256(raw).hexdigest(),
                'protocol_canonical_sha256': fingerprint(p),
                'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'code_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                                for f in sorted(Path(__file__).parent.glob('p9_3b3_nv2_*.py'))},
                'python': platform.python_version(), 'packages': {n: importlib.metadata.version(n)
                    for n in ('numpy', 'scipy', 'numcodecs', 'pyshtools', 'eccodes', 'eccodeslib')},
                'protected_control_count': protected['verified_count'], 'protected_changed_count': 0,
                'started_UTC': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'cache_only_mode': cache_only, 'stations_requested': stations,
                'old_results_rewritten': False, 'main_modified': False, 'merge_performed': False}
    source, geometry, predictions, profiles, deep, blockers = {}, {}, {}, {}, {}, []
    hours = source_hours(p)
    try:
        reader = NV2Columns(cache, base, heights, p)
        # Written before T/q profiles or pressure observations are read.
        geometry = reader.geometry_report()
        write_json(out/'source_geometry_and_fixed_donors.json', geometry)
        source = reader.controls()
        write_json(out/'native_source_lineage.json', source)
        for stamp in hours:
            print('NV2_NATIVE_PROFILE '+stamp, flush=True)
            try:
                columns = reader.read(stamp, base['primary_first_model_level'])
                predictions[stamp] = reader.predict(columns, stamp)
                profiles[stamp] = {str(index): asdict(c) for index, c in columns.items()}
            except (OSError, ValueError) as exc:
                reason = type(exc).__name__+':'+str(exc)
                predictions[stamp] = blocked_prediction(p, reason)
                blockers.append({'scope': 'PRIMARY_PROFILE', 'timestamp_UTC': stamp, 'reason': reason})
            if stamp in base['source_control_hours']:
                try:
                    full = reader.read(stamp, base['deep_diagnostic_first_model_level'])
                    deep[stamp] = {'predictions': reader.predict(full, stamp),
                                   'columns': {str(index): asdict(c) for index, c in full.items()}}
                except (OSError, ValueError) as exc:
                    deep[stamp] = {'status': 'SOURCE_BLOCKED', 'reason': type(exc).__name__+':'+str(exc)}
                    blockers.append({'scope': 'DEEP_SENSITIVITY_ONLY', 'timestamp_UTC': stamp,
                                     'reason': deep[stamp]['reason']})
    except (OSError, ValueError) as exc:
        reason = type(exc).__name__+':'+str(exc)
        blockers.append({'scope': 'SOURCE_INITIALIZATION', 'reason': reason})
        source = {'status': 'SOURCE_BLOCKED', 'reason': reason}
    # A complete prediction census remains visible even after an init failure.
    for stamp in hours:
        predictions.setdefault(stamp, blocked_prediction(p, 'SOURCE_INITIALIZATION_BLOCKED'))
    products = {'source_geometry_and_fixed_donors.json': geometry,
                'historical_sensor_references.json': heights, 'native_source_lineage.json': source,
                'native_primary_profiles.json': profiles, 'deep_column_sensitivity.json': deep,
                'sealed_pressure_predictions.json': {'phase': p['phase'], 'hourly': predictions,
                    'protocol_sha256': manifest['protocol_sha256'],
                    'scope': 'SOURCE_ONLY_PREDICTIONS_BEFORE_PRESSURE_OBSERVATIONS'}}
    seals = {}
    for name, value in products.items():
        write_json(out/name, value)
        seals[name] = hashlib.sha256((out/name).read_bytes()).hexdigest()
    write_json(out/'prediction_seal.json', {'source_products_sha256': seals,
                                           'station_pressure_products_opened': False})
    score, g0 = None, None
    if stations:
        eligible = [co for co, h in heights.items() if h.get('reference_refresh') == 'WMDR_SEMANTIC_IDENTITY_CONFIRMED']
        if source.get('paired_surface_lineage_status', '').startswith('ORIGINAL_GRIB_TO_CO_CAST_IDENTITY_CONFIRMED'):
            print('NV2_SOURCE_PRODUCTS_SEALED_OPEN_REVEALED_PRESSURE_OBSERVATIONS', flush=True)
            score, g0 = score_after_seal(out, seals, cache, p, base, eligible)
        else:
            score = {**score_nv2(predictions, {}, p), 'observation_provenance': {}}
            old = {t: {co: v['G0'] for co, v in row.items()} for t, row in predictions.items()}
            g0 = score_pressure(old, {}, base)
        write_json(out/'revealed_pressure_scores_NV2.json', score)
        write_json(out/'G0_regression_pressure_scores.json', g0)
    protected_controls(p)  # No generation/scoring code may rewrite a frozen file.
    manifest.update(execution_summary(p, profiles, source, heights, score, stations=stations))
    objects = {r['url']+'|'+str(r['range']): r for r in cache.records}
    manifest.update(source_lineage_status=source.get('paired_surface_lineage_status', source.get('status', 'UNKNOWN')),
                    score_cells_expected=p['expected_pressure_score_cells'], score_cells_retained=len(score['cells']) if score else 0,
                    G0_score_cells_retained=len(g0['cells']) if g0 else 0, source_blockers=blockers,
                    sealed_products_sha256=seals, network_downloaded_bytes=cache.downloaded,
                    network_requests=cache.requests, source_objects=list(objects.values()),
                    unique_source_bytes_including_cache=sum(r['bytes'] for r in objects.values()),
                    wall_seconds=time.perf_counter()-started,
                    peak_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    write_json(out/'run_manifest.json', manifest)
    print(json.dumps({k: manifest[k] for k in ('engineering_execution_status', 'source_profile_hours_complete',
          'historical_sensor_countries_confirmed', 'score_cells_retained', 'network_downloaded_bytes',
          'network_requests', 'wall_seconds', 'independent_accuracy')}), flush=True)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--private-cache', required=True)
    parser.add_argument('--protocol', default=str(PROTOCOL))
    parser.add_argument('--stations', action='store_true')
    parser.add_argument('--cache-only', action='store_true')
    args = parser.parse_args(argv)
    manifest = run(args.out, args.private_cache, stations=args.stations,
                   cache_only=args.cache_only, protocol_path=args.protocol)
    return 0 if manifest['engineering_execution_status'] == 'COMPLETE_SOURCE_EXECUTION' else 1


if __name__ == '__main__':
    raise SystemExit(main())
