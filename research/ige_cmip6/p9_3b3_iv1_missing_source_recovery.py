"""Append-only completion of the two registered TLS failures in IV1.

The predecessor archive, 675 native inputs, 17 original reference bodies and
frozen integration/physics are retained. This helper cannot fetch station
observations, select another date/column, or admit an incomplete source seal.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import time

import p9_1a_global_historical_backbone as era
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_iv1_integration_common import (OBSERVATION_BUDGET, code_pins, execution_plan, fresh_directory,
    integration_guard, member_path, read_members, require_time_admission, sha, write_new)
from p9_3b3_iv1_integration_sources import IV1Columns, ModelCache, fetch_reference, native_config, verify_sources
from p9_3b3_iv1_preflight import ROOT


REQUEST = Path(__file__).with_name('p9_3b3_iv1_missing_source_recovery_request_20261024.json')
REQUEST_SHA = 'd640b1a78dca75139a510b79ee10cb356359485509d3cb82098cacb2610fd71a'


def require_committed_recovery(request):
    subprocess.run(['git', 'merge-base', '--is-ancestor', request['parent_commit'], 'HEAD'],
                   cwd=ROOT, check=True, capture_output=True)
    for path in (Path(__file__), REQUEST):
        raw = subprocess.check_output(['git', 'show', 'HEAD:'+path.relative_to(ROOT).as_posix()], cwd=ROOT)
        if raw != path.read_bytes():
            raise ValueError('IV1_RECOVERY_EXECUTION_CODE_AND_REQUEST_MUST_ALREADY_BE_COMMITTED')


def recover_sources(source_directory, predecessor_archive, directory, private_cache):
    protocol, contract = integration_guard()
    require_time_admission()
    if sha(REQUEST) != REQUEST_SHA:
        raise ValueError('IV1_RECOVERY_REQUEST_CHANGED')
    request = json.loads(REQUEST.read_text())
    require_committed_recovery(request)
    if (request['stage'] != 'RESTORE_ONLY_REGISTERED_MISSING_MODEL_INPUTS_BEFORE_OBSERVATIONS'
            or request['heldout_2022_station_values_opened'] is not False
            or sha(predecessor_archive) != request['original_artifact_sha256']):
        raise ValueError('IV1_RECOVERY_PREDECESSOR_ARCHIVE_OR_SCOPE_CHANGED')
    source_directory = Path(source_directory)
    if (sha(source_directory/'source_seal.json') != request['original_source_seal_sha256']
            or sha(source_directory/'source_data.json') != request['original_source_data_sha256']):
        raise ValueError('IV1_RECOVERY_PREDECESSOR_SOURCE_SEAL_CHANGED')
    original, _, _ = verify_sources(source_directory)
    if original['complete'] or original['station_values_opened'] is not False:
        raise ValueError('IV1_RECOVERY_REQUIRES_INCOMPLETE_BLIND_SOURCE')
    missing = [stamp for stamp, row in original['native_hours'].items() if row.get('status') == 'SOURCE_BLOCKED']
    missing_refs = [i for i, row in enumerate(original['reference_requests']) if row['status'] != 'SOURCE_READ']
    if missing != request['missing_native_hours'] or missing_refs != request['missing_reference_indices']:
        raise ValueError('IV1_RECOVERY_MUST_MATCH_EXACT_ORIGINAL_MISSING_INPUTS')
    identity = request['missing_reference_identity']
    if any(any(original['reference_requests'][i]['request'][key] != value for key, value in identity.items())
           for i in missing_refs):
        raise ValueError('IV1_RECOVERY_REFERENCE_IDENTITY_CHANGED')
    byte_cap, request_cap = request['additional_native_byte_ceiling'], request['additional_native_request_ceiling']
    if (byte_cap != 512*1024**2 or request_cap != 1000
            or original['network_bytes_conservative_upper_bound']+byte_cap+len(missing_refs)*era.LIMIT_BYTES
                +OBSERVATION_BUDGET > protocol['compute_estimate']['max_network_bytes']
            or original['network_requests_conservative_upper_bound']+request_cap+len(missing_refs)
                > protocol['compute_estimate']['max_requests']):
        raise ValueError('IV1_RECOVERY_CUMULATIVE_OR_ADDITIONAL_BUDGET')
    out, private = Path(directory), Path(private_cache)
    if out.exists():
        raise FileExistsError('IV1_RECOVERY_OUTPUT_EXISTS_NO_OVERWRITE')
    if out.resolve() == private.resolve() or out.resolve() in private.resolve().parents:
        raise ValueError('IV1_RECOVERY_PRIVATE_CACHE_MUST_BE_OUTSIDE_OUTPUT')
    plan = execution_plan(protocol, contract)
    config = native_config(protocol, plan)
    config.update(max_download_bytes=byte_cap, max_requests=request_cap)
    started = time.perf_counter()
    cache = ModelCache(private/'native', config)
    reader = IV1Columns(cache, config, original['sensors'], contract)
    new_lineage = reader.controls()
    if (reader.A+reader.B != original['hybrid_pv'] or reader.field_attributes != original['field_attributes']
            or new_lineage['sources'] != original['lineage']['sources']
            or fingerprint(new_lineage['original_GRIB_controls']) != fingerprint(original['lineage']['original_GRIB_controls'])):
        raise ValueError('IV1_RECOVERY_SOURCE_METADATA_HYBRID_OR_RAW_GRIB_CHAIN_CHANGED')
    data = deepcopy(original)
    retained = {k: v for k, v in original['native_hours'].items() if k not in missing}
    native_before = fingerprint(retained)
    for stamp in missing:
        data['native_hours'][stamp] = reader.raw_hour(stamp)
    # Do not create a new source product until the replacement profile has
    # actually been obtained from the unchanged registered native chain.
    fresh_directory(out)
    old_seal = json.loads((source_directory/'source_seal.json').read_text())
    old_paths = read_members(source_directory, old_seal['members_sha256'])
    preserved = {}
    for name, path in old_paths.items():
        if name == 'source_data.json':
            continue
        target = member_path(out, name)
        shutil.copyfile(path, target); preserved[name] = sha(target)
        if preserved[name] != old_seal['members_sha256'][name]:
            raise ValueError('IV1_RECOVERY_ORIGINAL_REFERENCE_BODY_CHANGED')
    ref_bytes, ref_requests = 0, 0
    for i in missing_refs:
        entry = data['reference_requests'][i]; r = entry['request']
        sensor = data['sensors'][r['country']]['temperature']
        url = era.request_url(sensor['latitude'], sensor['longitude'], r['start'], r['end'])
        if url != entry['url']:
            raise ValueError('IV1_RECOVERY_REFERENCE_URL_CHANGED')
        raw, network = fetch_reference(url, private/'reference')
        era.parse_source(raw, sensor['latitude'], sensor['longitude'], r['start'], r['end'])
        name = f'reference_{i:02d}.json'
        with (out/name).open('xb') as stream:
            stream.write(raw)
        entry.pop('reason', None)
        entry.update(status='SOURCE_READ', member=name, sha256=sha(out/name))
        ref_bytes += network['bytes_downloaded']; ref_requests += network['requests']
    native_after = fingerprint({k: v for k, v in data['native_hours'].items() if k not in missing})
    if native_after != native_before:
        raise ValueError('IV1_RECOVERY_PREVIOUS_NATIVE_INPUTS_CHANGED')
    elapsed = time.perf_counter()-started
    data['source_recovery'] = {'request_sha256': REQUEST_SHA, 'helper_sha256': sha(__file__),
        'original_artifact_sha256': request['original_artifact_sha256'],
        'original_source_seal_sha256': request['original_source_seal_sha256'],
        'original_source_data_sha256': request['original_source_data_sha256'],
        'original_source_failures': original['source_failures'],
        'restored_native_hours': missing, 'restored_reference_indices': missing_refs,
        'preserved_native_hour_count': len(retained), 'preserved_native_inputs_canonical_sha256': native_before,
        'preserved_reference_body_sha256': preserved, 'rechecked_native_lineage': new_lineage,
        'additional_network_bytes': cache.downloaded+ref_bytes, 'additional_requests': cache.requests+ref_requests,
        'wall_seconds': elapsed, 'heldout_2022_station_values_opened': False,
        'all_forecasts_must_be_regenerated_before_final_seal': True}
    data.update(source_failures=[], complete=True,
        network_bytes=original['network_bytes']+cache.downloaded+ref_bytes,
        network_bytes_conservative_upper_bound=original['network_bytes_conservative_upper_bound']+cache.downloaded+ref_bytes,
        network_requests=original['network_requests_conservative_upper_bound']+cache.requests+ref_requests,
        network_requests_conservative_upper_bound=original['network_requests_conservative_upper_bound']+cache.requests+ref_requests,
        request_accounting='CUMULATIVE_INCLUDING_ALL_ORIGINAL_REFERENCE_ATTEMPTS',
        wall_seconds=original['wall_seconds']+elapsed,
        wall_seconds_scope='SUM_OF_ORIGINAL_AND_RECOVERY_SOURCE_PROCESSING_EXCLUDES_IDLE_TIME')
    if (data['network_bytes_conservative_upper_bound']+OBSERVATION_BUDGET > protocol['compute_estimate']['max_network_bytes']
            or data['network_requests_conservative_upper_bound'] > protocol['compute_estimate']['max_requests']):
        raise ValueError('IV1_RECOVERY_TOTAL_BUDGET_EXCEEDED')
    write_new(out/'source_data.json', data)
    members = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    write_new(out/'source_seal.json', {'schema': 'IGE_IV1_SOURCE_SEAL_v1', 'members_sha256': members,
        'contract_sha256': old_seal['contract_sha256'], 'code_sha256': code_pins(), 'station_values_opened': False})
    completed, columns, references = verify_sources(out)
    if not completed['complete'] or len(columns) != 676 or len(references) != 18:
        raise ValueError('IV1_RECOVERY_COMPLETENESS_NOT_REPLAYED')
    return {'stage': 'REGISTERED_MISSING_SOURCE_RECOVERY_COMPLETE', 'native_hours': len(columns),
        'reference_requests': len(references), 'source_seal_sha256': sha(out/'source_seal.json'),
        'preserved_native_hours': len(retained), 'preserved_reference_bodies': len(preserved),
        'additional_network_bytes': cache.downloaded+ref_bytes,
        'cumulative_network_bytes_conservative_upper_bound': data['network_bytes_conservative_upper_bound'],
        'cumulative_requests': data['network_requests'], 'station_values_opened': False,
        'independent_accuracy': 'NOT_RUN', 'ready_to_open_observations': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True); parser.add_argument('--predecessor-archive', required=True)
    parser.add_argument('--out', required=True); parser.add_argument('--private-cache', required=True)
    args = parser.parse_args()
    print(json.dumps(recover_sources(args.sources, args.predecessor_archive, args.out, args.private_cache)))
