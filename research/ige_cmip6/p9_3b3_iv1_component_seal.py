"""Integrity and physical replay of IV1 method-component results.

This seal deliberately is not the full source-lineage/prediction admission
required for unblinding. The native 2022 collector and the observation scorer
remain separate work. No flag in a component bundle can authorize observations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from p9_3b3_c2_projection import ProjectionMetric, ProjectionProblem
from p9_3b3_c2_validation import validate_projection
from p9_3b3_cd1_run import write_new
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_iv1_methods import IV1PressureTrajectory, METHODS, ReferenceConstraints
from p9_3b3_iv1_preflight import PROTOCOL_SHA, cohort, guard


def replay_case(case):
    country, date = case['country'], case['date']
    identity = 'IV1|'+country+'|'+date+'|P2_NATIVE_THERMO'
    if case['case_id'] != identity or case['station_values_opened'] is not False:
        raise ValueError('IV1_COMPONENT_IDENTITY_OR_BLINDING')
    results = case['results']
    if len(results) != 5 or [r['IV1_method'] for r in results] != list(METHODS):
        raise ValueError('IV1_COMPONENT_FIVE_METHOD_CENSUS')
    if 'shared_blocker' in case:
        if not case['shared_blocker'] or any(r.get('status') != 'SOURCE_BLOCKED' or 'T_K' in r or 'q_kgkg' in r for r in results):
            raise ValueError('IV1_COMPONENT_SHARED_FAILURE_MUST_RETAIN_ALL_METHODS')
        return {'state_count': 0, 'failure_count': 5, 'shared_blocked': True}
    inputs = case['inputs']
    target = ReferenceConstraints(**inputs['target'])
    pressure = IV1PressureTrajectory(**inputs['pressure'])
    donor = inputs['donor']
    if (target.date != date or pressure.target_date != date or country not in ('AT', 'DE', 'CH')
            or donor['date'][:4] not in ('2019', '2020') or donor['date'][5:7] != date[5:7]
            or not 15 <= int(donor['date'][8:10]) <= 28
            or donor['pressure']['mode'] != 'ERA5_GRID_PROVISIONAL'
            or donor['pressure']['reference_date'] != donor['date']
            or not donor['pressure']['source_sha256']):
        raise ValueError('IV1_COMPONENT_INPUT_DATE_OR_SOURCE')
    prior = fingerprint({'T': list(donor['T_K']), 'q': list(donor['q_kgkg'])})
    if prior != case['common_prior_sha256']:
        raise ValueError('IV1_COMPONENT_COMMON_PRIOR')
    problem = ProjectionProblem(donor['T_K'], donor['q_kgkg'], target.legacy_target(),
        pressure.comparison_reference(), target.q_weights, target.RH_weights, target.T_weights)
    valid, failures = 0, 0
    for method, row in zip(METHODS, results):
        if (row['IV1_case_id'] != identity or row['common_prior_sha256'] != prior
                or row['common_donor_date'] != donor['date'] or row['source_constraints_sha256'] != target.fingerprint
                or row['pressure_trajectory_sha256'] != pressure.fingerprint):
            raise ValueError('IV1_COMPONENT_METHOD_CHANGED_COMMON_INPUT')
        if 'T_K' not in row and 'q_kgkg' not in row:
            if row.get('status') not in ('SOURCE_BLOCKED', 'UNRESOLVED', 'CERTIFIED_INFEASIBLE',
                    'CERTIFIED_T_DOMAIN_INFEASIBLE', 'T_DOMAIN_NUMERICALLY_UNRESOLVED',
                    'CERTIFIED_HARD_CONSTRAINTS_INFEASIBLE'):
                raise ValueError('IV1_COMPONENT_UNKNOWN_FAILURE_OR_SUCCESS_WITHOUT_STATE')
            failures += 1
            continue
        check = validate_projection(row['T_K'], row['p_Pa'], row['q_kgkg'], target.legacy_target(),
            pressure.values_Pa, donor['T_K'], target.q_weights, target.RH_weights, target.T_weights,
            hard_q=method in METHODS[:2], hard_RH=method == METHODS[0])
        if (not np.isfinite(row['achieved_diagnostics']['hurs'])
                or row['achieved_diagnostics']['huss'] != check['q_mean_kgkg'] or abs(
                row['achieved_diagnostics']['hurs']-check['RH_source_mean_pct']) > 1e-10):
            raise ValueError('IV1_COMPONENT_REPORTED_DAILY_MEANS_DO_NOT_REPLAY')
        expected_source = {'tasmin': target.Tmin_K, 'tasmax': target.Tmax_K, 'tas': target.tas_K,
                           'huss': target.q_mean_kgkg, 'hurs': target.RH_mean_pct}
        if row['source_diagnostics'] != expected_source:
            raise ValueError('IV1_COMPONENT_SOURCE_DIAGNOSTICS_CHANGED')
        expected_T = {'tasmin': min(row['T_K']), 'tasmax': max(row['T_K']),
                      'tas': (min(row['T_K'])+max(row['T_K']))/2}
        if any(row['achieved_diagnostics'][k] != v for k, v in expected_T.items()):
            raise ValueError('IV1_COMPONENT_REPORTED_T_OPERATORS_DO_NOT_REPLAY')
        journal = row['journal_all_diagnostics']
        if len(journal) != 5 or {j['variable'] for j in journal} != {'tasmin', 'tasmax', 'tas', 'huss', 'hurs'}:
            raise ValueError('IV1_COMPONENT_CORRECTION_LEDGER_CENSUS')
        for entry in journal:
            if not np.isfinite([entry['achieved'], entry['requested'], entry['signed_delta']]).all():
                raise ValueError('IV1_COMPONENT_NONFINITE_CORRECTION_LEDGER')
            achieved = row['achieved_diagnostics'][entry['variable']]
            requested = row['source_diagnostics'][entry['variable']]
            if entry['achieved'] != achieved or entry['requested'] != requested or abs(
                    entry['signed_delta']-(achieved-requested)) > 1e-12:
                raise ValueError('IV1_COMPONENT_CORRECTION_LEDGER_CHANGED')
        if method in METHODS[2:]:
            x = problem.base.pack(np.asarray(row['T_K']), np.asarray(row['q_kgkg']))
            value = float(problem.objective(x, ProjectionMetric())[0])
            reported = row['objective']['total']
            if not np.isfinite(reported) or abs(value-reported) > 1e-10*max(1., abs(value)):
                raise ValueError('IV1_COMPONENT_ORIGINAL_OBJECTIVE_CHANGED')
        elif method == METHODS[1]:
            # Q-only has its own unweighted L2 objective, not the C2 F.
            value = .5*float(np.sum((np.asarray(row['q_kgkg'])-donor['q_kgkg'])**2))
            if not np.isfinite(row['objective']) or abs(row['objective']-value) > 1e-14:
                raise ValueError('IV1_COMPONENT_Q_ONLY_OBJECTIVE_CHANGED')
        valid += 1
    return {'state_count': valid, 'failure_count': failures, 'shared_blocked': False}


def census(cases, protocol):
    expected = {'IV1|'+r['country']+'|'+r['date']+'|P2_NATIVE_THERMO' for r in cohort(protocol)}
    if len(cases) != len(expected) or {c['case_id'] for c in cases} != expected:
        raise ValueError('IV1_COMPONENT_FULL_84_CASE_CENSUS_REQUIRED')
    totals = [replay_case(c) for c in cases]
    return {'cases': len(cases), 'method_records': len(cases)*5,
        'physical_states_replayed': sum(r['state_count'] for r in totals),
        'explicit_failures_retained': sum(r['failure_count'] for r in totals),
        'shared_blocked_cases': sum(r['shared_blocked'] for r in totals),
        'scope': 'COMPONENT_INTEGRITY_AND_PHYSICS_ONLY_NOT_NATIVE_SOURCE_ADMISSION',
        'ready_to_open_observations': False, 'independent_accuracy': 'NOT_RUN'}


def seal_components(directory, cases):
    protocol = guard()
    report = census(cases, protocol)
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError('IV1_COMPONENT_OUTPUT_EXISTS_NO_OVERWRITE')
    directory.mkdir(parents=True)
    write_new(directory/'method_components.json', cases)
    digest = hashlib.sha256((directory/'method_components.json').read_bytes()).hexdigest()
    write_new(directory/'component_prediction_seal.json', {
        'schema_version': 'IGE_IV1_METHOD_COMPONENT_SEAL_v1', 'protocol_sha256': PROTOCOL_SHA,
        'members_sha256': {'method_components.json': digest}, 'census': report,
        'component_code_sha256': component_code(),
        'station_values_opened': False, 'native_source_lineage_verified_by_this_seal': False,
        'ready_to_open_observations': False})
    return report


def verify_components(directory):
    directory = Path(directory)
    seal = json.loads((directory/'component_prediction_seal.json').read_text())
    if (seal['schema_version'] != 'IGE_IV1_METHOD_COMPONENT_SEAL_v1'
            or seal['protocol_sha256'] != PROTOCOL_SHA or seal['station_values_opened'] is not False
            or seal['native_source_lineage_verified_by_this_seal'] is not False
            or seal['ready_to_open_observations'] is not False
            or seal['component_code_sha256'] != component_code()
            or set(seal['members_sha256']) != {'method_components.json'}):
        raise ValueError('IV1_COMPONENT_SEAL_SCOPE_OR_SCHEMA')
    raw = (directory/'method_components.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != seal['members_sha256']['method_components.json']:
        raise ValueError('IV1_COMPONENT_SEAL_MEMBER_CHANGED')
    report = census(json.loads(raw), guard())
    if report != seal['census']:
        raise ValueError('IV1_COMPONENT_SEAL_CENSUS_DOES_NOT_REPLAY')
    return report


def component_code():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in
            ('p9_3b3_iv1_methods.py', 'p9_3b3_iv1_component_seal.py', 'p9_3b3_cd3_stability.py')}
