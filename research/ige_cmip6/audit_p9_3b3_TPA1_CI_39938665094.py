"""Read-only TPA1 CI audit, including termination and same-input sensitivity.

No solver, source definition, metric, case selection or historical result is
changed here. The optional same-input repeat is a post-hoc numerical diagnostic,
not another independent accuracy experiment or a newly chosen tolerance.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import zipfile

from p9_3b3_compare_vertical_frame import SourceBlocked, fingerprint
from p9_3b3_tpa_audit import audit_comparison
from p9_3b3_tpa_pressure import load_sealed_nv2, pressure_at_thermo
from p9_3b3_tpa_run import ROOT, load_protocol, protected_controls, summarize


HEAD = 'd09b1dcef046e21ba7dbd174c275646132ce6409'
ARCHIVES = {'comparison.zip': '4cc3d680d4608483ee06a5d03a162a376ebbb6365ee158212f9edf4734393276',
            'regression.zip': 'fd0f1aa0038dfc81d5a15c4bd3311044a4829127c4242704c506142ea40b8392'}


def read_zip(path, expected):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('TPA_CI_ARCHIVE_DIGEST_MISMATCH_'+path.name)
    with zipfile.ZipFile(path) as z:
        return {n: json.loads(z.read(n)) for n in z.namelist()}, {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}


def state_differences(first, second):
    lookup = {(r['case_id'], r['comparison_method']): r for r in first}
    out = defaultdict(lambda: {'states': 0, 'different_arrays': 0, 'max_T_K': 0., 'max_p_Pa': 0.,
                               'max_q_gkg': 0., 'max_achieved_q_mean_gkg': 0., 'max_achieved_RH_mean_pp': 0.})
    status_differences = []
    for row in second:
        prior = lookup[row['case_id'], row['comparison_method']]
        if row['status'] != prior['status']:
            status_differences.append((row['case_id'], row['comparison_method'], prior['status'], row['status']))
        if 'T_K' not in row:
            continue
        dT, dp, dq = (max(abs(x-y) for x, y in zip(row[k], prior[k])) for k in ('T_K', 'p_Pa', 'q_kgkg'))
        g = out[row['comparison_method']]
        g['states'] += 1
        g['different_arrays'] += any(x != 0 for x in (dT, dp, dq))
        for key, value in (('max_T_K', dT), ('max_p_Pa', dp), ('max_q_gkg', 1000*dq),
                           ('max_achieved_q_mean_gkg', 1000*abs(row['achieved_diagnostics']['huss']-prior['achieved_diagnostics']['huss'])),
                           ('max_achieved_RH_mean_pp', abs(row['achieved_diagnostics']['hurs']-prior['achieved_diagnostics']['hurs']))):
            g[key] = max(g[key], value)
    return {'status_differences': status_differences, 'by_method': dict(out)}


def run(evidence, nv2_zip, repair_baseline, out):
    evidence, out = Path(evidence), Path(out)
    metadata = json.loads((evidence/'github_metadata.json').read_text())
    runmeta = metadata['run']
    assert runmeta['id'] == 39938665094 and runmeta['head_sha'] == HEAD and runmeta['conclusion'] == 'success'
    assert len(metadata['jobs']) == 3 and all(j['conclusion'] == 'success' for j in metadata['jobs'])
    comparison, digests = read_zip(evidence/'comparison.zip', ARCHIVES['comparison.zip'])
    regression, reg_digests = read_zip(evidence/'regression.zip', ARCHIVES['regression.zip'])
    inputs, results, summary = (comparison[n] for n in ('comparison_inputs.json', 'comparison_results.json', 'comparison_summary.json'))
    assert len(inputs) == 63 and len(results) == 189 and len({r['case_id'] for r in inputs}) == 63
    assert summary['git_head'] == HEAD and summary['comparison_results'] == 189
    assert all(digests[name] == sha for name, sha in summary['output_sha256'].items())
    for name, sha in summary['code_sha256'].items():
        assert hashlib.sha256((ROOT/'research/ige_cmip6'/name).read_bytes()).hexdigest() == sha, name
    numeric = audit_comparison(inputs, results)
    assert numeric == comparison['independent_numeric_audit.json'] == summary['independent_numeric_audit']
    assert summarize(results)['groups'] == summary['groups']
    assert summarize(results)['status_counts'] == summary['status_counts']
    controls = protected_controls(load_protocol())
    models = load_sealed_nv2(Path(nv2_zip))
    for record in inputs:
        b = record['base_case']
        p = pressure_at_thermo(models, b['country'], b['source_day'], record['pressure_trajectory']['method'],
                               b['slot'], target_date=b['target']['date'])
        assert fingerprint(asdict(p)) == fingerprint(record['pressure_trajectory'])
    try:
        pressure_at_thermo(models, 'AT', '2021-02-01', 'P2_NATIVE', 'D1')
    except SourceBlocked:
        pass
    else:
        raise AssertionError('AT_D1_THERMO_REJECTION_NOT_PRESERVED')
    tests = [int(v) for v in re.findall(r'Ran (\d+) tests in ', (evidence/'contracts.log').read_text())]
    assert tests == [288, 14, 50, 8] and sum(tests) == 360
    assert 'Unchanged controls: 109' in (evidence/'contracts.log').read_text()

    old = regression['c2_comparison.json']
    assert old['algorithm_commit'] == HEAD
    for name, sha in old['implementation_file_sha256'].items():
        assert hashlib.sha256((ROOT/'research/ige_cmip6'/name).read_bytes()).hexdigest() == sha, name
    raw = Path(repair_baseline).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == load_protocol()['frozen_regression_baseline_sha256']
    baseline = json.loads(raw)
    old_counts, strict_state_reuse, all_ledgers, blocked = Counter(), 0, 0, []
    for year in old['years']:
        prior = next(m for m in baseline['members'] if m['year'] == year['year'] and m['variant'] == 'L3_JOINT_SOURCE_PHASE')
        previous = {d['date']: d for d in prior['days']}
        members = {m['mode']: {d['date']: d for d in m['days']} for m in year['members']}
        assert all(set(days) == set(previous) and len(days) == 366 for days in members.values())
        for date, control in previous.items():
            old_counts[control['status']] += 1
            cohort = [m[date] for m in members.values()]
            assert all(r['baseline_strict_status'] == control['status'] for r in cohort)
            if control['status'] == 'EXACT_DEFINED_OPERATORS':
                assert all(r['status'] == 'EXACT_SOURCE_PRESERVED' and r['donor_date'] == control['donor_date'] for r in cohort)
                assert len({r['state_sha256'] for r in cohort}) == 1
                strict_state_reuse += 1
            else:
                blocked.append(date)
            for row in cohort:
                assert row['source_inputs_mutated'] is False and row['production_eligible'] is False
                for journal in row['journal']:
                    if journal['achieved_value'] is not None:
                        assert abs(journal['delta']-(journal['achieved_value']-journal['source_value'])) <= 1e-12
                all_ledgers += 1
    assert dict(old_counts) == old['strict_rerun_counts'] == {'EXACT_DEFINED_OPERATORS': 727, 'CERTIFIED_INFEASIBLE': 5}
    assert strict_state_reuse == 727 and all_ledgers == 2196
    assert old['total_records_per_mode_including_boundaries'] == 732 and old['unique_dates'] == 731 and old['core_year_days'] == 730

    trials, no_success = Counter(), []
    for row in results:
        if row['comparison_method'] != 'C2_BOTH_SOFT_STRICT_FIRST' or row['status'] != 'LOCAL_PHYSICAL_PROJECTION_RESEARCH_ONLY':
            continue
        soft = [t for t in row.get('optimizer_trials', []) if t['stage'] == 'SOFT_SOURCE_PROJECTION']
        successes = sum(t['solver_success'] for t in soft)
        trials.update({'modified_cases': 1, 'trials': len(soft), 'successful_trials': successes,
                       'iteration_limit_trials': sum(t['message'] == 'Iteration limit reached' for t in soft)})
        if successes == 0:
            no_success.append({'case_id': row['case_id'], 'trials': soft, 'objective': row['objective']})

    with gzip.open(ROOT/'research/ige_cmip6/p9_3b3_tpa1_verified_local_replay_20261023.json.gz', 'rt') as stream:
        bundle = json.load(stream)
    local = {n: json.loads(v['utf8']) for n, v in bundle['files'].items()}
    prior_inputs = {r['case_id']: r for r in local['comparison_inputs.json']}
    input_diffs, max_prior_q = Counter(), 0.
    for record in inputs:
        before = prior_inputs[record['case_id']]
        assert record['pressure_trajectory'] == before['pressure_trajectory']
        a, b = record['base_case'], before['base_case']
        assert a['donor_T'] == b['donor_T']
        assert all(a['target'][k] == b['target'][k] for k in ('Tmin_K', 'Tmax_K', 'tas_K', 'q_mean_kgkg', 'RH_mean_pct'))
        input_diffs['q_prior_different'] += a['donor_q'] != b['donor_q']
        max_prior_q = max(max_prior_q, max(abs(x-y) for x, y in zip(a['donor_q'], b['donor_q'])))
    repeat = json.loads((evidence/'same_CI_input_local_replay_summary.json').read_text())
    assert repeat['status_differences'] == [] and repeat['all_189_results'] == 189
    report = {'phase': 'P9.3B3_TPA1_CI_39938665094_AUDIT', 'tested_commit': HEAD,
        'CI': {'id': runmeta['id'], 'conclusion': runmeta['conclusion'], 'updated_at_UTC': runmeta['updated_at'],
               'jobs_successful': 3, 'tests': tests, 'test_count': sum(tests)},
        'archive_sha256': ARCHIVES, 'comparison_file_sha256': digests, 'regression_file_sha256': reg_digests,
        'engine_code_hashes_match_tested_sources': True, 'protected_scientific_files_unchanged': len(controls),
        'comparison': {'pressure_cases': len(inputs), 'method_results': len(results), 'status_counts': summary['status_counts'],
            'groups': summary['groups'], 'all_63_pressure_trajectories_rederived_from_sealed_NV2': True,
            'Graz_D1_thermo_block_retained': True, 'independent_scalar_replay': numeric,
            'wall_seconds': summary['wall_seconds'], 'CPU_seconds': summary['CPU_seconds'], 'peak_RSS_KiB': summary['peak_RSS_KiB_Linux']},
        'frozen_regressions': {'counts': dict(old_counts), 'strict_states_reused_in_all_three_C2_modes': strict_state_reuse,
            'day_mode_ledgers_checked': all_ledgers, 'blocked_dates': sorted(blocked),
            'records_per_mode_with_boundaries': 732, 'unique_dates': 731, 'core_year_days': 730,
            'mode_summaries': old['comparison_summary'], 'working_tree_dirty_metadata': old['working_tree_dirty'],
            'code_hashes_match': True, 'raw_T_p_q_omitted_in_compact_regression_artifact': True,
            'validation_scope': 'CI_REGENERATED_AND_VALIDATED_STATES; AUDIT_CHECKS_LEDGERS_HASHES_DATES_DONORS_NOT_RAW_727_ARRAYS',
            'wall_seconds': old['elapsed_run_wall_seconds'], 'CPU_seconds': old['elapsed_run_process_CPU_seconds'],
            'peak_RSS_KiB': old['peak_process_RSS_KiB']},
        'C2_optimizer_termination': {'counts': dict(trials), 'cases_with_no_successful_soft_trial': no_success,
            'physical_feasibility_does_not_establish_local_optimality': True,
            'selected_trial_identity_not_recorded_in_frozen_C2': True},
        'original_local_vs_CI': {'input_differences': dict(input_diffs), 'max_prior_q_difference_kgkg': max_prior_q,
            'daily_targets_and_pressure_trajectories_numerically_identical': True,
            **state_differences(local['comparison_results.json'], results)},
        'identical_CI_input_repeat': repeat,
        'quality': {'code_correctness': 'PASS_IN_TESTED_SCOPE', 'physical_admissibility': 'CONDITIONAL_DISCRETE_STATES_VALIDATED',
            'C2_local_optimality': 'NOT_ESTABLISHED_FOR_ALL_RETURNED_CANDIDATES',
            'independent_accuracy': 'NOT_QUALIFIED_NO_NEW_HOLDOUT', 'operational_readiness': 'NOT_QUALIFIED'},
        'source_semantics_fully_verified': False, 'C2_correction_budget': 'NOT_ESTABLISHED',
        'hydrostatic_reintegration_after_T_q_changes': False, 'B4_qualified': False,
        'native_future_CanESM5_pressure_recovered': False, 'new_station_observations_opened': False,
        'engine_or_scientific_parameters_modified': False, 'production_epw_ready': False, 'merge_main': False}
    with out.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--nv2-zip', required=True)
    parser.add_argument('--repair-baseline', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    report = run(args.evidence, args.nv2_zip, args.repair_baseline, args.out)
    print(json.dumps({'CI': report['CI'], 'C2_optimizer_termination_counts': report['C2_optimizer_termination']['counts'],
                      'no_successful_C2_soft_trial_cases': len(report['C2_optimizer_termination']['cases_with_no_successful_soft_trial'])}, indent=2))
