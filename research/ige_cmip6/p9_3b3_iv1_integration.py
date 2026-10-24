"""IV1 sources -> all common priors -> five methods -> full seal -> scoring.

Real collection and observations are blocked by the pinned unresolved AT
operator. There is no CLI switch to bypass scientific source admission.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import datetime as dt
import json
from pathlib import Path
import shutil

from p9_2a_joint_weather_regimes import Day
from p9_3b3_compare_vertical_frame import fingerprint, SourceBlocked
from p9_3b3_generator import from_legacy_day
from p9_3b3_iv1_component_seal import seal_components, verify_components
from p9_3b3_iv1_integration_common import (CONTRACT_SHA, code_pins, execution_plan,
    fresh_directory, integration_guard, member_path, read_members, require_time_admission, sha, write_new)
from p9_3b3_iv1_integration_sources import collect_sources, verify_sources
from p9_3b3_iv1_methods import (IV1PressureTrajectory, METHODS, choose_common_prior,
                               compare_five, reference_constraints)
from p9_3b3_iv1_preflight import cohort
from p9_3b3_nv2_columns import admission, single_donor


def native_day(data, columns, country, date):
    sensors = data['sensors'][country]
    if any(sensors['temperature'][k] != sensors['RH_water'][k] for k in ('latitude', 'longitude', 'height_MSL_m')):
        raise SourceBlocked('IV1_T_AND_RH_NOT_COLOCATED')
    pressures, T, q, anchors, pbar = [], [], [], [], {}
    for hour in range(24):
        stamp = date+f'T{hour:02d}:00'
        column = columns.get(stamp, {}).get(country)
        for role in ('temperature', 'RH_water', 'pressure'):
            gate = admission(column, sensors[role], stamp,
                {'earth_radius_km': 6371.0088, 'radius_km': 50., 'gas': 'B3_GAS_CONSISTENT'})
            if not gate['admitted']:
                raise SourceBlocked('IV1_FIXED_NATIVE_COLUMN_AIR_DOMAIN_'+role+'|'+'|'.join(gate['reasons']))
        state = single_donor(column, sensors['temperature'], stamp)['P2_NATIVE']
        bar = single_donor(column, sensors['pressure'], stamp)['P2_NATIVE']
        pressures.append(state['pressure_Pa']); T.append(state['target_layer_T_K']); q.append(state['target_layer_q_kgkg'])
        anchors.append({k: state[k] for k in ('anchor_phi_m2s2', 'anchor_log_pressure', 'source_column_fingerprint')})
        pbar[stamp] = bar['pressure_Pa']
    sensor = sensors['temperature']
    provenance = {'country': country, 'source_kind': 'NATIVE_ERA5_2022_FIXED_GEOMETRY_SAME_CHAIN',
        'anchors': anchors, 'sensor': sensor, 'datum': 'MSL_TIMES_CONSTANT_G0_APPROXIMATION',
        'fixed_native_index': data['plan']['fixed_native_grid_indices'][country],
        'source_data_fingerprint': fingerprint({'lineage': data['lineage'], 'plan': data['plan']})}
    pressure = IV1PressureTrajectory(date, date, tuple(date+f'T{h:02d}:00' for h in range(24)),
        tuple(pressures), tuple(T), tuple(q), sensor['latitude'], sensor['longitude'], sensor['height_MSL_m'],
        'THERMO_SENSOR', 'P2_NATIVE', 'D2' if country == 'AT' else 'D1',
        fingerprint(data), json.dumps(provenance, sort_keys=True, allow_nan=False))
    return pressure, pbar


def reference_days(data, references):
    result, failures = {}, {}
    for entry in data['reference_requests']:
        r = entry['request']
        if (r['country'], r['start']) not in references:
            continue
        obj, arrays, meta = references[(r['country'], r['start'])]
        times = obj['hourly']['time']
        for offset in range(0, len(times), 24):
            date = times[offset][:10]
            vectors = tuple({k: v[i] for k, v in arrays.items()} for i in range(offset, offset+24))
            try:
                result[r['country'], date] = Day(dt.date.fromisoformat(date), vectors,
                                                meta['raw_original_response_sha256'])
            except ValueError as error:
                failures[r['country'], date] = str(error)
    return result, failures


def prepare_inputs(data, columns, references, protocol):
    days, failures = reference_days(data, references)
    donors = {co: [] for co in protocol['countries']}
    for (country, date), day in sorted(days.items()):
        if date[:4] not in ('2019', '2020'):
            continue
        try:
            donors[country].append(from_legacy_day(day, frame='IV1_OPEN_METEO_ERA5_GRID'))
        except ValueError as error:
            failures[country, date] = str(error)
    prepared, barometer = [], {co: {} for co in protocol['countries']}
    for row in cohort(protocol):
        country, date = row['country'], row['date']
        record = {'country': country, 'date': date,
                  'case_id': 'IV1|'+country+'|'+date+'|P2_NATIVE_THERMO',
                  'donor_source_rejections': [{'date': d, 'reason': reason} for (co, d), reason in sorted(failures.items())
                    if co == country and d[:4] in ('2019', '2020') and d[5:7] == date[5:7]]}
        try:
            pressure, pbar = native_day(data, columns, country, date)
            # Pressure validation is independent of daily reference/donor
            # availability and of every T/q method's numerical disposition.
            barometer[country].update(pbar)
            if (country, date) not in days:
                raise SourceBlocked('IV1_REFERENCE_DAY_UNAVAILABLE_OR_INVALID:'+failures.get((country, date), 'SOURCE_MISSING'))
            day = days[country, date]
            T = [v['temperature_2m']+273.15 for v in day.vectors]
            Td = [v['dew_point_2m']+273.15 for v in day.vectors]
            target = reference_constraints(date, T, Td, pressure, day.original_sha256)
            wet = any(v['precipitation'] > 0 for v in day.vectors)
            donor = choose_common_prior(target, donors[country], wet)
            record.update(target=target, pressure=pressure, donor=donor,
                input_sha256=fingerprint({'target': asdict(target), 'pressure': asdict(pressure), 'donor': asdict(donor)}))
        except (ValueError, KeyError) as error:
            record['shared_blocker'] = type(error).__name__+':'+str(error)
        prepared.append(record)
    return prepared, barometer


def input_records(prepared):
    values = [{k: asdict(v) if k in ('target', 'pressure', 'donor') else v for k, v in row.items()}
              for row in prepared]
    return json.loads(json.dumps(values, allow_nan=False))


def blocked_case(row, reason):
    return {'country': row['country'], 'date': row['date'], 'case_id': row['case_id'],
        'shared_blocker': reason, 'station_values_opened': False,
        'results': [{'IV1_method': method, 'status': 'SOURCE_BLOCKED'} for method in METHODS]}


def generate_predictions(source_directory, directory):
    protocol, contract = integration_guard()
    require_time_admission()
    data, columns, references = verify_sources(source_directory)
    prepared, barometer = prepare_inputs(data, columns, references, protocol)
    out = fresh_directory(directory)
    # Freeze ALL common priors before the first feasibility/optimizer call.
    write_new(out/'common_inputs_before_methods.json', input_records(prepared))
    write_new(out/'pressure_barometer_predictions.json', barometer)
    cases, errors = [], []
    for row in prepared:
        if 'shared_blocker' in row:
            case = blocked_case(row, row['shared_blocker'])
        else:
            try:
                case = compare_five(row['country'], row['target'], row['pressure'], row['donor'])
            except Exception as error:
                reason = 'ALGORITHM_ERROR:'+type(error).__name__+':'+str(error)
                errors.append({'case_id': row['case_id'], 'reason': reason})
                case = blocked_case(row, reason)
        cases.append(case)
        print('IV1_METHOD_CASE '+row['case_id'], flush=True)
    seal_components(out/'components', cases)
    source_seal = json.loads((Path(source_directory)/'source_seal.json').read_text())
    source_names = [*source_seal['members_sha256'], 'source_seal.json']
    (out/'sources').mkdir()
    for name in source_names:
        shutil.copyfile(member_path(source_directory, name), member_path(out/'sources', name))
    members = {f'sources/{name}': sha(out/'sources'/name) for name in source_names}
    names = ['common_inputs_before_methods.json', 'pressure_barometer_predictions.json',
             'components/method_components.json', 'components/component_prediction_seal.json']
    members.update({name: sha(out/name) for name in names})
    write_new(out/'prediction_seal.json', {'schema': 'IGE_IV1_FULL_PREDICTION_SEAL_v1',
        'contract_sha256': CONTRACT_SHA, 'code_sha256': code_pins(), 'members_sha256': members,
        'source_complete': data['complete'], 'case_count': len(cases), 'method_records': len(cases)*5,
        'algorithm_errors': errors, 'station_values_opened': False,
        'seal_scope': 'FULL_MODEL_SOURCES_COMMON_PRIORS_ALL_METHODS_BEFORE_OBSERVATIONS',
        'independent_accuracy': 'NOT_RUN', 'production_epw_ready': False})
    return {'prediction_seal_sha256': sha(out/'prediction_seal.json'), 'case_count': len(cases),
        'method_records': len(cases)*5, 'source_complete': data['complete'], 'algorithm_errors': errors,
        'ready_for_scoring_admission': data['complete'] and not errors, 'station_values_opened': False}


def verify_predictions(directory, expected_seal_sha256):
    protocol, contract = integration_guard()
    directory = Path(directory)
    if len(expected_seal_sha256) != 64 or sha(directory/'prediction_seal.json') != expected_seal_sha256:
        raise ValueError('IV1_EXTERNALLY_PINNED_PREDICTION_SEAL_CHANGED')
    seal = json.loads((directory/'prediction_seal.json').read_text())
    if (seal['schema'] != 'IGE_IV1_FULL_PREDICTION_SEAL_v1' or seal['contract_sha256'] != CONTRACT_SHA
            or seal['code_sha256'] != code_pins() or seal['station_values_opened'] is not False
            or seal['algorithm_errors'] or seal['case_count'] != 84 or seal['method_records'] != 420):
        raise ValueError('IV1_FULL_SEAL_SCOPE_CODE_OR_ALGORITHM_ERROR')
    paths = read_members(directory, seal['members_sha256'])
    data, columns, references = verify_sources(directory/'sources')
    if not data['complete'] or seal['source_complete'] is not True:
        raise SourceBlocked('IV1_INCOMPLETE_SOURCES_NO_OBSERVATION_UNBLINDING')
    verify_components(directory/'components')
    cases = json.loads(paths['components/method_components.json'].read_text())
    prepared, barometer = prepare_inputs(data, columns, references, protocol)
    if input_records(prepared) != json.loads(paths['common_inputs_before_methods.json'].read_text()):
        raise ValueError('IV1_COMMON_PRIOR_OR_DAILY_INPUTS_DO_NOT_REPLAY_FROM_SOURCES')
    if barometer != json.loads(paths['pressure_barometer_predictions.json'].read_text()):
        raise ValueError('IV1_BAROMETER_HEIGHT_PRESSURE_DOES_NOT_REPLAY')
    for row, case in zip(prepared, cases):
        if row['case_id'] != case['case_id']:
            raise ValueError('IV1_CASE_ORDER_CHANGED')
        if 'shared_blocker' in row:
            if case.get('shared_blocker') != row['shared_blocker']:
                raise ValueError('IV1_SHARED_FAILURE_DISPOSITION_CHANGED')
        else:
            expected = {key: asdict(row[key]) for key in ('target', 'pressure', 'donor')}
            if fingerprint(case.get('inputs')) != fingerprint(expected):
                raise ValueError('IV1_METHOD_INPUTS_DIFFER_FROM_FROZEN_COMMON_PRIOR')
    source_seal = json.loads((directory/'sources'/'source_seal.json').read_text())
    expected_members = {f'sources/{name}' for name in [*source_seal['members_sha256'], 'source_seal.json']} | {
        'common_inputs_before_methods.json', 'pressure_barometer_predictions.json',
        'components/method_components.json', 'components/component_prediction_seal.json'}
    if set(paths) != expected_members:
        raise ValueError('IV1_FULL_SEAL_MEMBER_CENSUS_CHANGED')
    return cases, barometer, protocol


def score_predictions(directory, expected_seal_sha256, output, private_cache):
    # Both gates precede cache construction, callback resolution and downloads.
    require_time_admission()
    cases, barometer, protocol = verify_predictions(directory, expected_seal_sha256)
    from p9_3b3_iv1_integration_observations import open_observations
    from p9_3b3_iv1_integration_statistics import score_arrays
    if Path(output).exists():
        raise FileExistsError('IV1_SCORE_OUTPUT_EXISTS_NO_OVERWRITE')
    private = Path(private_cache).resolve()
    if any(private == root or root in private.parents for root in
           (Path(directory).resolve(), Path(output).resolve().parent)):
        raise ValueError('IV1_STATION_PRIVATE_CACHE_MUST_BE_OUTSIDE_ARTIFACT_DIRECTORIES')
    observations, provenance = open_observations(protocol, private_cache, directory, expected_seal_sha256)
    # Recheck all model sources and predictions after external observation I/O.
    verify_predictions(directory, expected_seal_sha256)
    result = score_arrays(cases, barometer, observations, protocol)
    result.update(prediction_seal_sha256=expected_seal_sha256, observation_provenance=provenance,
                  station_values_opened=True, comparison_protocol_unchanged=True,
                  parameter_time_admission='ALL_NINE_EXPLICIT_CURRENT_NODE_OPERATORS')
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    write_new(output, result)
    return result


def preflight():
    from p9_3b3_iv1_admission import admission_report
    protocol, contract = integration_guard()
    plan = execution_plan(protocol, contract)
    try:
        require_time_admission()
        blocked = None
    except SourceBlocked as error:
        blocked = str(error)
    return {'stage': 'IV1_INTEGRATION_IMPLEMENTED_SOURCE_PREFLIGHT', 'contract_sha256': CONTRACT_SHA,
        'protected_files_unchanged': len(contract['protected_sha256']), 'execution_plan': plan,
        'source_collection_status': 'SOURCE_BLOCKED' if blocked else 'ADMITTED_NOT_RUN',
        'source_blocker': blocked, 'end_to_end_code_implemented': True,
        'time_admission': admission_report()['time_admission'],
        'physical_admissibility': 'VALIDATORS_IMPLEMENTED_REAL_COHORT_NOT_RUN',
        'real_2022_profiles_collected': 0, 'real_heldout_predictions_sealed': False,
        'real_station_scoring': 'NOT_RUN', 'station_values_opened': False,
        'independent_accuracy': 'NOT_RUN', 'B4_qualified': False,
        'P2_superiority_established': False, 'operational_ready': False, 'production_epw_ready': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('preflight'); p.add_argument('--out', required=True)
    p = sub.add_parser('collect'); p.add_argument('--out', required=True); p.add_argument('--private-cache', required=True)
    p = sub.add_parser('generate'); p.add_argument('--sources', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('score'); p.add_argument('--predictions', required=True); p.add_argument('--expected-seal-sha256', required=True)
    p.add_argument('--out', required=True); p.add_argument('--private-cache', required=True)
    args = parser.parse_args()
    if args.command == 'preflight':
        result = preflight(); write_new(args.out, result)
    elif args.command == 'collect': result = collect_sources(args.out, args.private_cache)
    elif args.command == 'generate': result = generate_predictions(args.sources, args.out)
    else: result = score_predictions(args.predictions, args.expected_seal_sha256, args.out, args.private_cache)
    print(json.dumps(result if args.command != 'preflight' else {k: result[k] for k in
        ('stage', 'source_collection_status', 'source_blocker', 'station_values_opened')}))


if __name__ == '__main__':
    main()
