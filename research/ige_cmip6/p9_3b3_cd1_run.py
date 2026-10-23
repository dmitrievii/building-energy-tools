"""Replay registered CD1 inputs and publish complete C2 diagnostic journals."""
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

from p9_3b3_cd1_diagnostics import diagnose_day
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_tpa_contracts import DailyClimateConstraints, PressureTrajectory
from p9_3b3_tpa_compare import package, METHODS


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = Path(__file__).with_name('p9_3b3_cd1_protocol.json')
PROTOCOL_SHA = 'f01169b07e5d263b303c84c06592c778506a1c33f30d23325a5607d7537f59b4'


def guard():
    p = json.loads(PROTOCOL.read_text())
    if fingerprint(p) != PROTOCOL_SHA:
        raise ValueError('CD1_REGISTERED_PROTOCOL_CHANGED')
    for name, sha in p['protected_control_sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != sha:
            raise ValueError('CD1_FROZEN_CONTROL_CHANGED_'+name)
    return p


def load_inputs(protocol):
    path = ROOT/protocol['archive']
    if hashlib.sha256(path.read_bytes()).hexdigest() != protocol['archive_sha256']:
        raise ValueError('CD1_ARCHIVED_INPUTS_CHANGED')
    with zipfile.ZipFile(path) as z:
        inputs = json.loads(z.read('comparison_inputs.json'))
        results = json.loads(z.read('comparison_results.json'))
    if len(inputs) != 63 or len(results) != 189:
        raise ValueError('CD1_SOURCE_CASE_CENSUS')
    c2 = [r for r in results if r['comparison_method'] == METHODS[2] and r['status'] == 'LOCAL_PHYSICAL_PROJECTION_RESEARCH_ONLY']
    if sum(r['selected_solver_reported_success'] is False for r in c2) != 8:
        raise ValueError('CD1_CORRIGENDUM_BASELINE_CENSUS')
    return inputs, {(r['case_id'], r['comparison_method']): r for r in results}


def write_new(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def run(out):
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    protocol = guard()
    inputs, baseline = load_inputs(protocol)
    start, cpu = time.perf_counter(), time.process_time()
    cases, trial_counts, selections = [], Counter(), Counter()
    for index, record in enumerate(inputs):
        b = record['base_case']
        target = DailyClimateConstraints(**b['target'])
        pressure = PressureTrajectory(**record['pressure_trajectory'])
        strict = baseline[record['case_id'], METHODS[0]]
        strict = strict if strict['status'] == 'EXACT_DEFINED_OPERATORS' else None
        result = diagnose_day(b['donor_T'], b['donor_q'], target.legacy_target(), pressure.comparison_reference(),
            donor_date=pressure.source_date, mode='BOTH_SOFT',
            pressure_alignment='TARGET_DAY_EXTERNAL_FIXED' if pressure.alignment == 'TARGET_DAY_EXTERNAL_FIXED'
                else 'REGISTERED_DONOR_PRESSURE_SENSITIVITY',
            strict_witness=strict, q_weights=target.q_weights, RH_weights=target.RH_weights, T_weights=target.T_weights)
        result['five_diagnostic_result'] = package(result['frozen_result'], METHODS[2], target, pressure, b['donor_T'], b['donor_q'])
        result['case_id'] = record['case_id']
        result['archived_input_sha256'] = fingerprint(record)
        result['family'] = b['family']
        result['archived_status'] = baseline[record['case_id'], METHODS[2]]['status']
        selected = result['selected_trial_index']
        row = {'case_id': record['case_id'], 'family': b['family'], 'category': result['diagnostic_category'],
            'status': result['frozen_result']['status'], 'archived_status': result['archived_status'],
            'observed_unobserved_exactly_equal': result['observed_unobserved_exactly_equal'],
            'trial_count': len(result['trials']), 'selected_trial_index': selected}
        selections[result['diagnostic_category']] += 1
        if selected is not None:
            s = result['trials'][selected]
            row.update(selected_solver_success=s['solver_success'], selected_iterations=s['iterations'],
                selected_first_order=s['first_order'], selected_finite_differences=s['finite_differences'],
                selected_phase_distance_K=s['final']['min_distance_to_freezing_K'],
                any_successful_trial=any(t['solver_success'] for t in result['trials']))
        for t in result['trials']:
            trial_counts['total'] += 1
            trial_counts['solver_success'] += t['solver_success']
            trial_counts['iteration_limit'] += t['solver_status'] == 9
            trial_counts['physically_valid'] += t['physical_admissibility'] == 'VALIDATED'
        cases.append(row)
        write_new(out/(str(index).zfill(2)+'_trial_journal.json'), result)
        print(json.dumps({'index': index, 'case_id': row['case_id'], 'category': row['category'],
                          'selected_trial': selected, 'trials': row['trial_count']}), flush=True)
    if len(cases) != 63 or trial_counts['total'] != 99 or selections['EXACT_SOURCE_WITNESS_NO_OPTIMIZATION'] != 30:
        raise AssertionError('CD1_REGISTERED_CENSUS_NOT_REPRODUCED')
    summary = {'phase': protocol['phase'], 'protocol_sha256': PROTOCOL_SHA,
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'code_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                       for f in sorted(Path(__file__).parent.glob('p9_3b3_cd1_*.py'))},
        'protected_controls_unchanged': len(protocol['protected_control_sha256']), 'cases': cases,
        'case_count': len(cases), 'trial_counts': dict(trial_counts), 'category_counts': dict(selections),
        'archived_status_differences': [r['case_id'] for r in cases if r['status'] != r['archived_status']],
        'corrigendum': protocol['corrigendum'],
        'all_observed_unobserved_outputs_exactly_equal': all(c['observed_unobserved_exactly_equal'] for c in cases),
        'local_optimum_certified': False, 'global_optimum_certified': False,
        'new_acceptance_thresholds_established': False, 'C2_correction_budget': 'NOT_ESTABLISHED',
        'source_semantics_fully_verified': False, 'independent_accuracy': 'NOT_QUALIFIED',
        'operational_ready': False, 'B4_qualified': False, 'production_epw_ready': False,
        'native_future_GCM_pressure_recovered': False, 'main_merged': False,
        'runtime': {'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__},
        'wall_seconds': time.perf_counter()-start, 'CPU_seconds': time.process_time()-cpu,
        'peak_RSS_KiB_Linux': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write_new(out/'CD1_summary.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True)
    args = p.parse_args()
    r = run(args.out)
    print(json.dumps({k: r[k] for k in ('case_count', 'trial_counts', 'category_counts', 'wall_seconds')}))
