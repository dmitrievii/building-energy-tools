"""Run preregistered CD2 variants on identical archived TPA1 inputs."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import time
import zipfile

import numpy as np
import scipy

from p9_3b3_cd1_run import load_inputs, write_new
from p9_3b3_cd2_solvers import VARIANTS, SLSQP_OPTIONS, COBYQA_OPTIONS, solve_variant
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_tpa_contracts import DailyClimateConstraints, PressureTrajectory
from p9_3b3_tpa_compare import package, METHODS


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = Path(__file__).with_name('p9_3b3_cd2_protocol.json')
PROTOCOL_SHA = '0ef3801ca9dc181d11b47f9d0386eb73e248b1c68e60a3faf0ff851f8a436f37'


def guard():
    p = json.loads(PROTOCOL.read_text())
    if fingerprint(p) != PROTOCOL_SHA:
        raise ValueError('CD2_REGISTERED_PROTOCOL_CHANGED')
    for path, sha in p['protected_control_sha256'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != sha:
            raise ValueError('CD2_FROZEN_CONTROL_CHANGED_'+path)
    if list(VARIANTS) != p['variants'] or SLSQP_OPTIONS != p['SLSQP_options'] or COBYQA_OPTIONS != p['COBYQA_options']:
        raise ValueError('CD2_IMPLEMENTATION_DIFFERS_FROM_REGISTERED_VARIANTS_OR_OPTIONS')
    archive = ROOT/p['CD1_CI']['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest() != p['CD1_CI']['archive_sha256']:
        raise ValueError('CD2_ORIGINAL_CD1_CI_ARCHIVE_CHANGED')
    with zipfile.ZipFile(archive) as z:
        summary = json.loads(z.read('CD1_summary.json'))
        if summary['case_count'] != 63 or summary['trial_counts']['total'] != 99:
            raise ValueError('CD2_CD1_CI_INCOMPLETE')
        if not summary['all_observed_unobserved_outputs_exactly_equal']:
            raise ValueError('CD2_CD1_CI_CONTROL_NOT_EQUAL')
    return p


def load_registered_inputs(protocol):
    cd1 = json.loads(Path(__file__).with_name('p9_3b3_cd1_protocol.json').read_text())
    if cd1['archive'] != protocol['comparison_archive'] or cd1['archive_sha256'] != protocol['comparison_archive_sha256']:
        raise ValueError('CD2_INPUT_LINEAGE_CHANGED')
    inputs, baseline = load_inputs(cd1)
    with zipfile.ZipFile(ROOT/protocol['CD1_CI']['archive']) as z:
        ci = {r['case_id']: r for n in z.namelist() if n.endswith('_trial_journal.json')
              for r in [json.loads(z.read(n))]}
    if set(ci) != {r['case_id'] for r in inputs}:
        raise ValueError('CD2_CD1_CI_CASE_CENSUS')
    for record in inputs:
        if ci[record['case_id']]['archived_input_sha256'] != fingerprint(record):
            raise ValueError('CD2_CD1_CI_INPUT_FINGERPRINT')
    return inputs, baseline, ci


def case_inputs(record, baseline):
    base = record['base_case']
    target = DailyClimateConstraints(**base['target'])
    pressure = PressureTrajectory(**record['pressure_trajectory'])
    strict = baseline[record['case_id'], METHODS[0]]
    strict = strict if strict['status'] == 'EXACT_DEFINED_OPERATORS' else None
    kwargs = dict(donor_date=pressure.source_date,
        pressure_alignment='TARGET_DAY_EXTERNAL_FIXED' if pressure.alignment == 'TARGET_DAY_EXTERNAL_FIXED'
            else 'REGISTERED_DONOR_PRESSURE_SENSITIVITY', strict_witness=strict,
        q_weights=target.q_weights, RH_weights=target.RH_weights, T_weights=target.T_weights)
    args = (base['donor_T'], base['donor_q'], target.legacy_target(), pressure.comparison_reference())
    return args, kwargs, target, pressure


def compare_to_control(result, control):
    raw, ref = result['frozen_result'], control['frozen_result']
    if 'T_K' not in raw or 'T_K' not in ref:
        return {'classification': 'NO_COMMON_VALIDATED_STATE', 'objective_delta': None}
    F, F0 = raw['objective']['total'], ref['objective']['total']
    delta, tolerance = F-F0, 1e-10*max(1., abs(F0))
    return {'classification': 'NUMERICAL_TIE' if abs(delta) <= tolerance else 'LOWER_F' if delta < 0 else 'HIGHER_F',
        'objective_delta': delta, 'numerical_tie_tolerance': tolerance,
        'max_T_difference_K': float(np.max(abs(np.asarray(raw['T_K'])-ref['T_K']))),
        'max_q_difference_gkg': float(np.max(abs(np.asarray(raw['q_kgkg'])-ref['q_kgkg']))*1000),
        'scientific_accuracy_interpretation': 'NONE'}


def compact_result(result):
    raw = result['frozen_result']; selected = result['selected_trial_index']
    row = {'variant': result['variant']['id'], 'status': raw['status'],
        'selected_trial_index': selected, 'trial_count': len(result['trials']),
        'solver_success_count': sum(t['solver_success'] for t in result['trials']),
        'physically_valid_trial_count': sum(t['physical_admissibility'] == 'VALIDATED' for t in result['trials']),
        'algorithm_errors': sum(t['algorithm_error'] is not None for t in result['trials']),
        'optimizer_CPU_seconds': sum(t['CPU_seconds'] for t in result['trials']),
        'optimizer_wall_seconds': sum(t['wall_seconds'] for t in result['trials']),
        'nfev': sum(t['nfev'] for t in result['trials']), 'njev': sum(t['njev'] for t in result['trials'])}
    if 'T_K' in raw:
        row.update(objective=raw['objective'], correction_journal=raw['journal'])
    if selected is not None:
        s = result['trials'][selected]
        row.update(selected_solver_success=s['solver_success'], selected_first_order=s.get('first_order'),
            selected_finite_differences=s.get('finite_differences'), selected_iterations=s['iterations'])
    return row


def run(out):
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    protocol = guard()
    inputs, baseline, ci = load_registered_inputs(protocol)
    wall, cpu = time.perf_counter(), time.process_time()
    cases, totals = [], {v['id']: Counter() for v in VARIANTS}
    for index, record in enumerate(inputs):
        args, kwargs, target, pressure = case_inputs(record, baseline)
        variants, common_starts = [], None
        for v in VARIANTS:
            result = solve_variant(*args, v['id'], **kwargs)
            result['five_diagnostic_result'] = package(result['frozen_result'], METHODS[2], target, pressure, args[0], args[1])
            starts = [t['initial_x_sha256'] for t in result['trials']]
            if common_starts is not None and starts != common_starts:
                raise AssertionError('CD2_VARIANTS_DID_NOT_RECEIVE_IDENTICAL_PHYSICAL_STARTS')
            common_starts = starts
            if variants and not result['trials'] and result['frozen_result'] != variants[0]['frozen_result']:
                raise AssertionError('CD2_STRICT_WITNESS_CHANGED')
            variants.append(result)
        rows = []
        for result in variants:
            row = compact_result(result)
            row['comparison_with_control'] = compare_to_control(result, variants[0])
            tally = totals[row['variant']]
            tally['cases'] += 1; tally['trials'] += row['trial_count']
            tally['physically_valid_trials'] += row['physically_valid_trial_count']
            tally['solver_success_trials'] += row['solver_success_count']
            tally['selected_solver_failure'] += row.get('selected_solver_success') is False
            tally['selected_solver_success'] += row.get('selected_solver_success') is True
            tally['algorithm_errors'] += row['algorithm_errors']
            tally['returned_states'] += 'objective' in row
            tally['strict_witnesses_without_optimization'] += row['trial_count'] == 0
            tally['optimizer_CPU_seconds'] += row['optimizer_CPU_seconds']
            tally['optimizer_wall_seconds'] += row['optimizer_wall_seconds']
            tally['nfev'] += row['nfev']; tally['njev'] += row['njev']
            tally[row['comparison_with_control']['classification']] += 1
            rows.append(row)
        data = {'case_id': record['case_id'], 'family': record['base_case']['family'],
            'archived_input_sha256': fingerprint(record), 'identical_physical_starts': True,
            'CD1_CI_baseline_status': ci[record['case_id']]['frozen_result']['status'],
            'variants': variants}
        write_new(out/(str(index).zfill(2)+'_CD2_case.json'), data)
        cases.append({'case_id': record['case_id'], 'family': data['family'], 'results': rows})
        print(json.dumps({'index': index, 'case_id': record['case_id'],
            'variants': [{'id': r['variant'], 'status': r['status'], 'comparison': r['comparison_with_control']['classification']} for r in rows]}), flush=True)
    for v in totals.values():
        if v['cases'] != 63 or v['trials'] != 99 or v['strict_witnesses_without_optimization'] != 30:
            raise AssertionError('CD2_REGISTERED_CENSUS_NOT_REPRODUCED')
    guard()
    summary = {'phase': protocol['phase'], 'protocol_sha256': PROTOCOL_SHA,
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'code_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('p9_3b3_cd2_*.py'))},
        'protected_controls_unchanged': len(protocol['protected_control_sha256']),
        'case_count': len(cases), 'method_results': sum(v['cases'] for v in totals.values()),
        'optimizer_trials': sum(v['trials'] for v in totals.values()), 'variants': {k: dict(v) for k,v in totals.items()},
        'all_control_observed_unobserved_exactly_equal': True, 'all_variants_identical_physical_starts': True,
        'cases': cases, 'local_optimum_certified': False, 'global_optimum_certified': False,
        'independent_accuracy': 'NOT_QUALIFIED', 'operational_ready': False, 'C2_correction_budget': 'NOT_ESTABLISHED',
        'B4_qualified': False, 'production_epw_ready': False, 'native_future_GCM_pressure_recovered': False,
        'source_semantics_fully_verified': False, 'main_merged': False,
        'runtime': {'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__},
        'wall_seconds': time.perf_counter()-wall, 'CPU_seconds': time.process_time()-cpu,
        'peak_RSS_KiB_Linux': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write_new(out/'CD2_summary.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True)
    args = p.parse_args()
    r = run(args.out)
    print(json.dumps({k: r[k] for k in ('case_count', 'method_results', 'optimizer_trials', 'variants', 'wall_seconds')}))
