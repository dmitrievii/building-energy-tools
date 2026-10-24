"""Read-only CD3/IV1 verification: endpoint math, start wording and raw WMDR.

No optimizer or new meteorological source is called. Numerical reproduction
does not certify minimum uniqueness, station accuracy or an executable IV1.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import lzma
from pathlib import Path
import time
import zipfile

import numpy as np

from audit_p9_3b3_CD2 import scalar_objective
from p9_3b3_c2_projection import ProjectionProblem, ProjectionMetric
from p9_3b3_cd1_diagnostics import View
from p9_3b3_cd1_run import write_new
from p9_3b3_cd2_run import guard as cd2_guard, load_registered_inputs, case_inputs
from p9_3b3_cd3_run import guard as cd3_guard
from p9_3b3_cd3_diagnostics import second_order_fd, STEPS
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_iv1_preflight import guard as iv1_guard, load_metadata, cohort, preflight
from p9_3b3_native_heights import sensor_records, includes
from p9_3b3_state_validation import _es


ROOT = Path(__file__).resolve().parents[2]


def require_close(actual, expected):
    if not np.allclose(actual, expected, rtol=1e-12, atol=1e-9):
        raise AssertionError('RECHECK_NUMERIC_SUMMARY_MISMATCH')


def verify_envelopes(problem, points, reports):
    """Pairwise calculation independent of the original ptp/max-RMS routine."""
    count = 0
    minimum = min(p['F_original'] for p in points)
    eps = 287.05/461.5
    for report in reports['sets']:
        chosen = [p for p in points if p['F_original']-minimum <= report['relative_delta']*max(1., abs(minimum))]
        if [p['id'] for p in chosen] != report['endpoint_ids']:
            raise AssertionError('RECHECK_NEAR_EQUAL_MEMBERSHIP')
        T, q = zip(*(problem.base.unpack(np.asarray(p['final_x'])) for p in chosen))
        T, q = np.asarray(T), np.asarray(q)
        e = q*problem.P/(eps+(1-eps)*q)
        RH = np.array([[100*ee/_es(tt, 'WATER_ICE', 'MURPHY_KOOP_2005') for tt, ee in zip(t, ev)]
                       for t, ev in zip(T, e)])
        for key, values in [('T_K', T), ('q_gkg', q*1000), ('RH_source_pp', RH), ('e_Pa', e)]:
            delta = abs(values[:, None, :]-values[None, :, :])
            require_close(float(delta.max()), report[key]['max_pair_difference'])
            require_close(float(np.sqrt(np.mean(delta*delta, axis=2)).max()), report[key]['max_pair_RMS'])
            require_close(values.min(axis=0), report[key]['min'])
            require_close(values.max(axis=0), report[key]['max'])
        require_close(float(np.ptp(q@problem.u)*1000), report['daily_q_mean_spread_gkg'])
        require_close(float(np.ptp(RH@problem.v)), report['daily_RH_mean_spread_pp'])
        count += 1
    return count


def start_wording(problem, identity, new_trials):
    """Record both readings; never change the frozen actual starts."""
    seed = int.from_bytes(hashlib.sha256(('20261023|'+identity).encode()).digest()[:16], 'little')
    rng = np.random.Generator(np.random.PCG64(seed))
    angles = 2*np.pi*np.arange(problem.n)/problem.n
    patterns = (np.sin(angles), np.cos(angles), rng.uniform(-1, 1, problem.n))
    rows = []
    for i, pattern in enumerate(patterns):
        d = .5*np.where(pattern >= 0, problem.base.high-problem.T0, problem.T0-problem.base.low)*pattern
        s, ds = np.diff(problem.T0)*problem.n/24, np.diff(d)*problem.n/24
        ratios = [max(0., (problem.base.slope-v)/dv) if dv > 0
                  else max(0., (-problem.base.slope-v)/dv) for v, dv in zip(s, ds) if dv != 0]
        r = min(ratios, default=float('inf'))
        literal = min(1., .9*r)
        actual = .9*min(1., r)
        trials = [p for p in new_trials if p['id'].startswith('PATTERN_'+str(i)+'_')]
        if len(trials) != 3 or any(p['T_segment_fraction'] != actual for p in trials):
            raise AssertionError('RECHECK_ACTUAL_START_ALPHA')
        rows.append({'case_id': identity, 'pattern': i, 'slope_only_limit': r if np.isfinite(r) else None,
            'literal_slope_only_alpha': literal, 'actual_code_alpha': actual,
            'wording_difference': abs(actual-literal) > 1e-12})
    return rows


def raw_metadata_replay():
    p = iv1_guard()
    bodies = load_metadata(p)
    saved = json.loads(bodies['dated_2022_sensor_admission.json'])
    days = cohort(p)
    rows = []
    for country in p['countries']:
        stamps = [h for r in days if r['country'] == country for h in r['hours_UTC']]
        for key, code, role in [('pressure', 216, 'BAROMETER'), ('temperature', 224, 'THERMO_SENSOR'),
                                 ('RH_water', 12249, 'THERMO_SENSOR')]:
            parsed = sensor_records(bodies[country+'_WMDR.xml'], p['stations'][country]['WSI'], code, stamps, role)
            if parsed != saved[country]['sensors'][key]:
                raise AssertionError('RECHECK_WMDR_DERIVED_RECORD_MISMATCH')
            rows.append({'country': country, 'sensor': key, 'height_MSL_m': parsed['height_MSL_m'],
                'timestamps_checked': len(stamps), 'raw_XML_matches_derived_record': True})
    metadata = json.loads(bodies['AT_metadata.json'])
    stamps = [h for r in days if r['country'] == 'AT' for h in r['hours_UTC']]
    eligible = [s for s in metadata['stations'] if s.get('type') == 'INDIVIDUAL'
                and s.get('group_id') == 30 and includes((s['valid_from'], s['valid_to']), stamps)]
    if len(eligible) != 1 or eligible[0]['id'] != 16412:
        raise AssertionError('RECHECK_AT_DATED_PROVIDER_IDENTITY')
    result = preflight()
    if result['ready_to_open_observations'] or result['station_values_opened']:
        raise AssertionError('RECHECK_IV1_UNBLINDING')
    return {'sensor_records_reparsed': rows, 'AT_unique_historical_individual': 16412,
        'preflight_blockers': result['source_blockers'], 'preflight_is': 'SOURCE_REGISTRATION_NOT_GENERATOR_OR_SCORER',
        'old_preflight_height_check': 'TRUSTED_HASHED_DERIVED_JSON; THIS_AUDIT_ADDS_RAW_XML_REPARSE',
        'station_values_opened': False, 'station_accuracy': 'NOT_RUN'}


def audit(original_zip=None):
    started = time.perf_counter()
    p3 = cd3_guard()
    inputs, baseline, _ = load_registered_inputs(cd2_guard())
    inputs = {r['case_id']: r for r in inputs}
    verified = json.loads((ROOT/'research/ige_cmip6/p9_3b3_cd3_verified_CI_40009910484.json').read_text())
    archive = ROOT/verified['exact_archive']['path']
    if hashlib.sha256(archive.read_bytes()).hexdigest() != verified['exact_archive']['sha256']:
        raise AssertionError('RECHECK_ARCHIVE_SHA')
    wrapper = json.loads(lzma.decompress(archive.read_bytes()))
    members = wrapper['members']
    if len(members) != 65 or {k: hashlib.sha256(v.encode()).hexdigest() for k, v in members.items()} != verified['exact_archive']['member_sha256']:
        raise AssertionError('RECHECK_EXACT_MEMBER_SHA')
    original_verified = None
    if original_zip:
        source = Path(original_zip)
        if hashlib.sha256(source.read_bytes()).hexdigest() != verified['source_zip_sha256']:
            raise AssertionError('RECHECK_ORIGINAL_CI_ZIP_SHA')
        with zipfile.ZipFile(source) as z:
            if set(z.namelist()) != set(members) or any(z.read(n) != members[n].encode() for n in z.namelist()):
                raise AssertionError('RECHECK_ORIGINAL_CI_MEMBERS_NOT_EXACT')
        original_verified = True
    source_summary = json.loads(members['CD3_summary.json'])
    for name, sha in source_summary['code_sha256'].items():
        if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != sha:
            raise AssertionError('RECHECK_NUMERICAL_CODE_CHANGED')
    counts, seen, maximum, alpha_rows, improvements = Counter(), set(), 0., [], []
    fd_max_F, fd_max_J = 0., 0.
    for name in sorted(n for n in members if n.endswith('_CD3_case.json')):
        case = json.loads(members[name]); identity = case['case_id']
        if identity in seen or fingerprint(inputs[identity]) != case['archived_input_sha256']:
            raise AssertionError('RECHECK_CASE_CENSUS_OR_SOURCE_SHA')
        seen.add(identity); record = inputs[identity]
        if case['strict_witness_preserved_without_optimization']:
            if case['new_trials'] or case['archived_endpoint_audits']:
                raise AssertionError('RECHECK_STRICT_WITNESS_OPTIMIZED')
            counts['strict_witnesses'] += 1
            continue
        args, kwargs, _, _ = case_inputs(record, baseline)
        problem = ProjectionProblem(*args, q_weights=kwargs['q_weights'], RH_weights=kwargs['RH_weights'], T_weights=kwargs['T_weights'])
        view = View(problem, ProjectionMetric(), 'SOFT_SOURCE_PROJECTION', 'BOTH_SOFT')
        for r in case['archived_endpoint_audits']+case['new_trials']:
            x = np.asarray(r['final_x']); before = x.copy()
            problem.validate(x)
            T, q = problem.base.unpack(x)
            value = scalar_objective(T, problem.P, q, record)['total']
            error = abs(value-r['F_original'])/max(1., abs(r['F_original']))
            if not np.isfinite(error) or error > 1e-12:
                raise AssertionError('RECHECK_SCALAR_F')
            maximum = max(maximum, error)
            for step in STEPS:
                fd = second_order_fd(view, x, step)
                if not fd['pass'] or fd['unavailable_columns']:
                    raise AssertionError('RECHECK_FD_FAILED')
                counts['FD_reports'] += 1; counts['FD_columns'] += fd['checked_columns']
                fd_max_F = max(fd_max_F, fd['objective_max_relative_error'])
                fd_max_J = max(fd_max_J, fd['constraint_Jacobian_max_relative_error'])
            if not np.array_equal(x, before):
                raise AssertionError('RECHECK_STATE_MUTATED')
            counts['validated_endpoints'] += 1
        old = case['archived_endpoint_audits']
        new = [dict(r, id='NEW_'+r['id'], variant='SLSQP_SCALED_X') for r in case['new_trials']]
        all_points = old+new
        for pool, points in [('SCALED_X_ONLY_ARCHIVED_CI_AND_NEW', [r for r in all_points if r['variant'] == 'SLSQP_SCALED_X']),
                              ('ALL_ARCHIVED_VARIANTS_AND_NEW_X', all_points)]:
            counts['envelope_sets_checked'] += verify_envelopes(problem, points, case['envelopes'][pool])
        alpha_rows.extend(start_wording(problem, identity, case['new_trials']))
        a = min(case['new_trials'][:3], key=lambda r: r['F_original'])
        b = min(case['new_trials'], key=lambda r: r['F_original'])
        if a['F_original']-b['F_original'] > 1e-8*max(1., abs(b['F_original'])):
            improvements.append(identity)
        counts['new_successful_trials'] += sum(r['solver_success'] for r in case['new_trials'])
        print(json.dumps({'case_id': identity, 'endpoints_checked': counts['validated_endpoints']}), flush=True)
    if seen != set(inputs) or (counts['strict_witnesses'], counts['validated_endpoints'], counts['FD_columns'], counts['new_successful_trials']) != (30, 792, 72864, 396):
        raise AssertionError('RECHECK_FINAL_CENSUS')
    meta = raw_metadata_replay()
    return {'phase': 'CD3_IV1_READ_ONLY_VERIFICATION_20261024', 'checked_commit': '63e4eeaa969831556c4fda5d0e8700d51d79c9c9',
        'numerical_status': 'PASS', 'frozen_CD3_controls': len(p3['protected_control_sha256']),
        'frozen_IV1_controls': len(iv1_guard()['protected_control_sha256']), 'counts': dict(counts),
        'CI_exact_members': 65, 'original_CI_zip_verified': original_verified,
        'max_scalar_F_error': maximum, 'max_FD_objective_error': fd_max_F, 'max_FD_Jacobian_error': fd_max_J,
        'improved_pressure_cases': improvements, 'improved_underlying_cases': sorted({s.rsplit('|', 1)[0] for s in improvements}),
        'start_contract_review': {'status': 'WORDING_AMBIGUITY_REQUIRES_EXPLICIT_SEGMENT_LIMIT', 'patterns_checked': len(alpha_rows),
            'different_from_slope_only_reading': sum(r['wording_difference'] for r in alpha_rows),
            'actual_alphas': sorted({r['actual_code_alpha'] for r in alpha_rows}),
            'literal_slope_only_alphas': sorted({r['literal_slope_only_alpha'] for r in alpha_rows}),
            'actual_formula': '0.9*min(1,r_slope)', 'slope_only_reading_of_protocol': 'min(1,0.9*r_slope)',
            'no_retroactive_perfect_preregistration_claim': True},
        'IV1_raw_source_replay': meta, 'optimizer_calls': 0, 'station_values_opened': False,
        'independent_accuracy': 'NOT_QUALIFIED', 'operational_ready': False, 'main_merged': False,
        'audit_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'wall_seconds': time.perf_counter()-started}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--original-zip')
    args = parser.parse_args()
    r = audit(args.original_zip)
    write_new(args.out, r)
    print(json.dumps(r, ensure_ascii=False))
