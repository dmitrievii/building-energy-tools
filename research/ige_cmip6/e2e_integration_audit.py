"""Offline replay of existing IGE components; not an arbitrary-point generator.

Reads two original P6 derived daily archives and the unchanged P7A historical
reference. Replays legacy morphing and its existing convex monthly-q stage,
then tests the actual Analyzer importer. No weather-provider or station I/O.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import platform
import subprocess
import sys
import time
import zipfile

import p7c1_epw_morphing as morph
from p7c1b_humidity_closure import Q_TOL, hourly_redistribution

ROOT = Path(__file__).resolve().parents[2]
BASE_COMMIT = '931a267fbe398155e9833b44d708f79c677d961a'
PACKET_SHA = '49dab390ec5d5250f79198df16e69cc3ba37a9985b66f739fde5a729db3c192d'
FUTURE = 'ssp245-2040-2059'
BASELINE_SHA = 'da8a4e08e032bebbb3105b6584c319714fc85c99fc06a59d5fa1d125bf3478fc'
MODULES = {
    'A_source': 'p9_1a_global_historical_backbone.py',
    'A_reference': 'p7a_historical_epw_reference.py',
    'A_temperature': 'p8_1_spatial_holdout.py',
    'A_humidity': 'p8_2f_station_selection.py',
    'A_wind': 'p8_3f2_physical_era5.py',
    'A_orography': 'p9_1d_native_orography_dem.py',
    'B_morph': 'p7c1_epw_morphing.py',
    'B_monthly_q': 'p7c1b_humidity_closure.py',
    'B_ensemble': 'p7c4_hourly_ensemble.py',
    'B_daily_joint': 'p9_2b_cmip6_daily_joint_regime_solver.py',
    'B_annual_joint': 'p9_2d_original_canesm5_2013_annual_source_epw_pilot.py',
    'shared_EPW': 'p9_2d_annual_cet_epw_export.py',
    'shared_pressure': 'p9_3b2d_canonical_pressure_fields.py',
    'research_C2': 'p9_3b3_c2_projection.py',
    'research_IV1': 'p9_3b3_iv1_integration.py',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, obj):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(obj, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def zip_bodies(raw, limit=32*1024**2):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        items = archive.infolist()
        if len(items) > 100 or sum(i.file_size for i in items) > limit:
            raise ValueError('E2E_ARCHIVE_BUDGET')
        names = set()
        for item in items:
            p = PurePosixPath(item.filename)
            if (p.is_absolute() or '..' in p.parts or '\\' in item.filename
                    or p.as_posix() != item.filename or item.is_dir()
                    or item.filename in names or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('E2E_UNSAFE_OR_DUPLICATED_ARCHIVE_MEMBER')
            names.add(item.filename)
        return {i.filename: archive.read(i) for i in items}


def extract_new(bodies, directory):
    directory.mkdir(parents=True)
    for name, raw in bodies.items():
        target = directory/name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)


def original_inputs(packet, out):
    raw = Path(packet).read_bytes()
    if sha(raw) != PACKET_SHA:
        raise ValueError('E2E_ORIGINAL_REPLAY_PACKET_CHANGED')
    bodies = zip_bodies(raw)
    selection = json.loads(bodies['selection_manifest.json'])
    if set(bodies) != set(selection['members']) | {'selection_manifest.json'}:
        raise ValueError('E2E_SELECTED_MEMBER_CENSUS')
    for name, proof in selection['members'].items():
        if len(bodies[name]) != proof['bytes'] or sha(bodies[name]) != proof['sha256']:
            raise ValueError('E2E_SELECTED_MEMBER_CHANGED')
    original = json.loads(bodies['original_p6_freeze_manifest.json'])
    registry = json.loads((ROOT/'research/ige_cmip6/p7c3_expected_daily_source_shas.json').read_text())['source_sha256']
    sources = {}
    for window in (morph.HIST, FUTURE):
        proof = next(r for r in original['archives'] if r.get('model') == 'CanESM5' and r.get('window') == window)
        body = bodies[proof['path']]
        assert sha(body) == proof['sha256']
        members = zip_bodies(body)
        assert {r['path'] for r in proof['zip_member_sha256']} == set(members)
        for row in proof['zip_member_sha256']:
            assert sha(members[row['path']]) == row['sha256'] and len(members[row['path']]) == row['bytes']
        assert sha(members['joint_daily_raw.csv']) == registry['CanESM5_'+window]
        folder = out/'sources'/window
        extract_new(members, folder)
        data, provenance = morph.verify_model_dir(folder, window)
        sources[window] = (data, provenance)
    portable = zip_bodies(bodies['IGE_P7A_GRAZ_2013_PORTABLE_RESEARCH_FREEZE.zip'])
    proof = json.loads(portable['MANIFEST.json'])
    original_zip = portable[proof['source_original_artifact_zip']]
    assert sha(original_zip) == proof['original_zip_sha256']
    historic = zip_bodies(original_zip)
    assert set(historic) == {r['path'] for r in proof['members']}
    for row in proof['members']:
        assert sha(historic[row['path']]) == row['sha256'] and len(historic[row['path']]) == row['size']
    folder = out/'sources'/'P7A_original'
    extract_new(historic, folder)
    baseline = folder/'Graz_2013_P7A_Historical_Reference_RESEARCH_ONLY.epw'
    assert sha(baseline.read_bytes()) == BASELINE_SHA
    return baseline, sources, selection


def monthly_q_report(baseline, candidate, ratios):
    data = defaultdict(lambda: {'target': [], 'actual': []})
    for base, row in zip(baseline, candidate):
        m = int(base[1]); p = float(row[9])
        data[m]['target'].append(morph.q_from_rh(float(base[6]), float(base[8]), p)*ratios[m])
        data[m]['actual'].append(morph.q_from_rh(float(row[6]), float(row[8]), p))
    return [{'month': m, 'target_mean_q_kgkg': math.fsum(v['target'])/len(v['target']),
             'actual_mean_q_kgkg': math.fsum(v['actual'])/len(v['actual']),
             'mean_q_error_kgkg': math.fsum(a-t for a, t in zip(v['actual'], v['target']))/len(v['target'])}
            for m, v in sorted(data.items())]


def app_import(path):
    sys.path.insert(0, str(ROOT/'tools/climate_analyzer'))
    from epw_climate_analyzer.epw_parser import parse_epw
    from epw_climate_analyzer.climate_model import canonical_from_epw
    import pandas as pd
    parsed = parse_epw(path)
    canonical = canonical_from_epw(parsed)
    assert len(canonical.data) == 8760
    return {'parser': 'EXISTING_ANALYZER_parse_epw_AND_canonical_from_epw',
        'records': len(canonical.data), 'calendar_mode': canonical.temporal.calendar_mode,
        'plotting_years': sorted(set(map(int, canonical.data.index.year))),
        'source_years': list(canonical.temporal.source_years),
        'pandas_version': pd.__version__,
        'historical_real_calendar_activation': False,
        'Streamlit_runtime_or_browser_test': False}


def audit(packet, output):
    started = time.perf_counter()
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE_COMMIT, 'HEAD'], cwd=ROOT, check=True)
    wrapper = Path(__file__).read_bytes()
    committed = subprocess.run(['git', 'show', 'HEAD:'+Path(__file__).relative_to(ROOT).as_posix()],
        cwd=ROOT, capture_output=True)
    contract = json.loads((ROOT/'research/ige_cmip6/p9_3b3_iv1_integration_contract.json').read_text())
    assert all(sha((ROOT/name).read_bytes()) == digest for name, digest in contract['protected_sha256'].items())
    out = Path(output)
    if out.exists():
        raise FileExistsError('E2E_NO_OVERWRITE_OF_PREVIOUS_RESULTS')
    out.mkdir(parents=True)
    baseline, sources, selection = original_inputs(packet, out)
    headers, rows, meta = morph.read_epw(baseline)
    baseline_copy = out/baseline.name
    with baseline_copy.open('xb') as stream:
        stream.write(baseline.read_bytes())
    signals = morph.monthly_signals(sources[morph.HIST][0], sources[FUTURE][0])
    ratios = {m: v['specific_humidity_ratio'] for m, v in signals.items()}
    headers_new, morphed, days, legacy_info = morph.morph_epw(headers, rows, signals, 'ssp245', FUTURE, meta)
    destination = out/'Graz_P7A_2013_CanESM5_SSP245_2040_2059_LEGACY_MORPH_REPLAY.epw'
    morph.write_epw(destination, headers_new, morphed)
    _, replay, _ = morph.read_epw(destination)
    assert len(replay) == 8760
    legacy = {'path': destination.name, 'sha256': sha(destination.read_bytes()), 'records': len(replay),
        'numerical': legacy_info, 'monthly_q': monthly_q_report(rows, replay, ratios),
        'app_import': app_import(destination), 'independent_accuracy': 'NOT_TESTED'}
    projection = {'status': 'NOT_RUN'}
    try:
        adjusted, months, daily, info = hourly_redistribution(rows, replay, ratios)
        path = out/'Graz_P7A_2013_CanESM5_SSP245_2040_2059_MONTHLY_Q_REPLAY.epw'
        projection_headers = [r.copy() for r in headers_new]
        projection_headers[5] = ['COMMENTS 1', 'IGE E2E archived integration replay, existing P7C1 then existing P7C1B monthly q projection; research only.']
        morph.write_epw(path, projection_headers, adjusted)
        _, adjusted_replay, _ = morph.read_epw(path)
        serialized = monthly_q_report(rows, adjusted_replay, ratios)
        if max(abs(r['mean_q_error_kgkg']) for r in serialized) > Q_TOL:
            raise ValueError('E2E_SERIALIZED_MONTHLY_Q_ORIGINAL_TOLERANCE_NOT_MET')
        projection = {'status': 'PHYSICAL_AND_MONTHLY_MASS_CONTRACTS_PASS_NOT_QUALIFIED',
            'path': path.name, 'sha256': sha(path.read_bytes()), 'records': len(adjusted_replay),
            'numerical': info, 'monthly_q': serialized,
            'app_import': app_import(path), 'independent_accuracy': 'NOT_TESTED'}
        write_json(out/'monthly_q_correction_ledger.json', {'months': months, 'days': daily, 'scope': 'EXISTING_CONVEX_MONTHLY_PROJECTION_NO_DAILY_NASA_EQUALITY_CLAIM'})
    except ValueError as error:
        projection = {'status': 'BLOCKED', 'reason': str(error), 'no_threshold_or_source_replacement': True}
    inventory = {}
    for key, name in MODULES.items():
        path = Path(__file__).parent/name
        tree = ast.parse(path.read_text())
        inventory[key] = {'path': str(path.relative_to(ROOT)), 'sha256': sha(path.read_bytes()),
            'functions': [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]}
    result = {'stage': 'IGE_E2E_INTEGRATION_AUDIT_ARCHIVED_GRAZ_REPLAY',
        'base_commit': BASE_COMMIT, 'execution_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'audit_wrapper_sha256': sha(wrapper),
        'audit_wrapper_committed_at_execution': committed.returncode == 0 and committed.stdout == wrapper,
        'python': platform.python_version(), 'source_packet_sha256': PACKET_SHA,
        'original_sources': {k: provenance for k, (_, provenance) in sources.items()},
        'selection': selection, 'historical_reference': {'sha256': BASELINE_SHA, 'records': len(rows),
            'path': baseline_copy.name, 'byte_exact_archived_readback': True,
            'regenerated_from_weather_provider_or_station_raw': False,
            'calendar_year': 2013, 'source': 'ORIGINAL_P7A_MULTISOURCE_REFERENCE_NOT_ARBITRARY_POINT_OUTPUT',
            'app_import': app_import(baseline)},
        'legacy_morph': legacy, 'monthly_q_projection': projection, 'module_inventory': inventory,
        'future_pressure': 'UNCHANGED_BASELINE_PROXY_NO_NATIVE_FUTURE_PS',
        'temperature_estimand_limit': 'LEGACY_TAS_SIGNAL_IS_APPLIED_TO_HOURLY_MEAN_BUT_NEX_TAS_IS_DERIVED_MIDRANGE_REQUIRES_EXPLICIT_MVP_POLICY',
        'observations_or_weather_provider_network_requests': 0,
        'registered_2022_IV1_station_values_opened': False,
        'historical_arbitrary_point_function_complete': False, 'future_product_function_complete': False,
        'independent_station_accuracy_newly_qualified': False, 'production_epw_ready': False,
        'protected_files_unchanged': len(contract['protected_sha256']),
        'wall_seconds': time.perf_counter()-started}
    write_json(out/'e2e_audit.json', result)
    print(json.dumps({'stage': result['stage'], 'historical_reference_hours': len(rows),
        'legacy_morph_hours': legacy['records'], 'monthly_q_stage': projection['status'],
        'runtime_seconds': result['wall_seconds'], 'production_epw_ready': False}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', default=str(Path(__file__).with_name('e2e_original_replay_inputs_20261025.zip')))
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    audit(args.inputs, args.out)
