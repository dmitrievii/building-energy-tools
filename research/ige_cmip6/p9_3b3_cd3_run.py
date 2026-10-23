"""CD3 immutable CI endpoint audit and preregistered multistart replay."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import lzma
from pathlib import Path
import platform
import resource
import subprocess
import time

import numpy as np
import scipy

from p9_3b3_c2_projection import ProjectionProblem, ProjectionMetric
from p9_3b3_cd1_diagnostics import View
from p9_3b3_cd1_run import write_new
from p9_3b3_cd2_run import guard as cd2_guard, load_registered_inputs, case_inputs
from p9_3b3_cd3_diagnostics import STEPS, ERROR_LIMIT
from p9_3b3_cd3_stability import run_starts, audit_endpoint, empirical_envelopes, DELTAS
from p9_3b3_compare_vertical_frame import fingerprint


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = Path(__file__).with_name('p9_3b3_cd3_protocol.json')
PROTOCOL_SHA = '3f10b653a4cc9a66cc8ef8554b9cb9ea32c2ace20c7433286f0b19cfda8b7ec4'
PREREG_COMMIT = '3a2c07fa66688a55684d118d1105392dd3f9a727'


def guard():
    p = json.loads(PROTOCOL.read_text())
    if fingerprint(p) != PROTOCOL_SHA:
        raise ValueError('CD3_REGISTERED_PROTOCOL_CHANGED')
    for path, expected in p['protected_control_sha256'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != expected:
            raise ValueError('CD3_PROTECTED_CONTROL_CHANGED_'+path)
    if (tuple(p['finite_differences']['steps']) != STEPS
            or p['finite_differences']['objective_error_limit'] != ERROR_LIMIT
            or p['finite_differences']['Jacobian_error_limit'] != ERROR_LIMIT
            or tuple(p['near_equal_profiles']['epsilon_relative_to_max_1_abs_Fmin']) != DELTAS):
        raise ValueError('CD3_DIAGNOSTIC_SETTINGS_DRIFT')
    subprocess.run(['git', 'merge-base', '--is-ancestor', PREREG_COMMIT, 'HEAD'], cwd=ROOT, check=True)
    cd2_guard()
    return p


def load_members(protocol):
    a = protocol['CI_archive']
    raw = (ROOT/a['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != a['sha256']:
        raise ValueError('CD3_ARCHIVED_CI_BYTES_CHANGED')
    wrapper = json.loads(lzma.decompress(raw))
    verified = json.loads((ROOT/'research/ige_cmip6/p9_3b3_cd2_verified_CI_39968651863.json').read_text())
    members = wrapper['members']
    if (wrapper['source_run_id'] != a['run_id'] or len(members) != 65
            or {n: hashlib.sha256(t.encode()).hexdigest() for n, t in members.items()}
                != verified['exact_archive']['member_sha256']):
        raise ValueError('CD3_CI_EXACT_MEMBER_CENSUS_OR_BYTES_CHANGED')
    return members


def fd_totals(rows):
    reports = [f for r in rows for f in r.get('finite_differences', [])]
    return {'endpoints': len(rows), 'diagnostic_errors': sum(bool(r.get('diagnostic_error')) for r in rows),
        'reports': len(reports), 'passed_reports': sum(f['pass'] for f in reports),
        'checked_columns': sum(f['checked_columns'] for f in reports),
        'unavailable_columns': sum(len(f['unavailable_columns']) for f in reports),
        'base_roundoff_reports': sum(bool(f['recorded_base_roundoff_columns']) for f in reports),
        'max_objective_relative_error': max((f['objective_max_relative_error'] for f in reports
                                             if f['objective_max_relative_error'] is not None), default=None),
        'max_Jacobian_relative_error': max((f['constraint_Jacobian_max_relative_error'] for f in reports
                                            if f['constraint_Jacobian_max_relative_error'] is not None), default=None)}


def envelope_summary(cases):
    result = {}
    for pool in ('SCALED_X_ONLY_ARCHIVED_CI_AND_NEW', 'ALL_ARCHIVED_VARIANTS_AND_NEW_X'):
        result[pool] = []
        for delta in DELTAS:
            rows = [(c['case_id'], s) for c in cases for s in c.get('envelopes', {}).get(pool, {}).get('sets', [])
                    if s['relative_delta'] == delta]
            def maximum(key):
                case_id, s = max(rows, key=lambda r: r[1][key]['max_pair_difference'])
                return {'value': s[key]['max_pair_difference'], 'case_id': case_id,
                        'endpoint_count': s['endpoint_count']}
            result[pool].append({'relative_delta': delta, 'cases': len(rows),
                'cases_with_multiple_endpoints': sum(s['endpoint_count'] > 1 for _, s in rows),
                'max_T_K': maximum('T_K'), 'max_q_gkg': maximum('q_gkg'),
                'max_RH_pp': maximum('RH_source_pp'), 'max_e_Pa': maximum('e_Pa')})
    return result


def run(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    p = guard()
    inputs, baseline, _ = load_registered_inputs(cd2_guard())
    inputs = {r['case_id']: r for r in inputs}
    members = load_members(p)
    cases, archived_rows, new_rows = [], [], []
    for name in sorted(n for n in members if n.endswith('_CD2_case.json')):
        old = json.loads(members[name])
        record = inputs[old['case_id']]
        if old['archived_input_sha256'] != fingerprint(record):
            raise ValueError('CD3_INPUT_SHA_DIFFERS_FROM_CI')
        args, kwargs, _, pressure = case_inputs(record, baseline)
        problem = ProjectionProblem(*args, q_weights=kwargs['q_weights'], RH_weights=kwargs['RH_weights'],
                                    T_weights=kwargs['T_weights'])
        view = View(problem, ProjectionMetric(), 'SOFT_SOURCE_PROJECTION', 'BOTH_SOFT')
        old_endpoints, trial_audits = [], []
        for variant in old['variants']:
            for trial in variant['trials']:
                if trial['stage'] != 'SOFT_SOURCE_PROJECTION':
                    raise ValueError('CD3_UNREGISTERED_STAGE')
                row = {'id': 'CI_'+variant['variant']['id']+'_'+str(trial['trial_index']),
                    'variant': variant['variant']['id'], 'final_x': trial['final_x'],
                    'solver_success': trial['solver_success']}
                try:
                    row.update(audit_endpoint(view, np.asarray(trial['final_x'])))
                except (ValueError, FloatingPointError) as error:
                    row['diagnostic_error'] = str(error)
                trial_audits.append(row)
                if row.get('physical_admissibility') == 'VALIDATED' and 'F_original' in row:
                    old_endpoints.append(row)
        if not trial_audits:
            for v in old['variants']:
                assert v['frozen_result']['status'] == 'EXACT_SOURCE_PRESERVED'
                assert v['frozen_result']['T_K'] == old['variants'][0]['frozen_result']['T_K']
                assert v['frozen_result']['q_kgkg'] == old['variants'][0]['frozen_result']['q_kgkg']
                assert v['frozen_result']['p_Pa'] == list(pressure.values_Pa)
            data = {'case_id': old['case_id'], 'archived_input_sha256': fingerprint(record),
                'strict_witness_preserved_without_optimization': True, 'archived_endpoint_audits': [],
                'new_trials': [], 'envelopes': {}}
        else:
            new = run_starts(problem, old['case_id'])
            endpoints = [dict(r, id='NEW_'+r['id'], variant='SLSQP_SCALED_X') for r in new
                         if r['physical_admissibility'] == 'VALIDATED' and 'F_original' in r]
            combined = old_endpoints+endpoints
            pools = {'SCALED_X_ONLY_ARCHIVED_CI_AND_NEW': [r for r in combined if r['variant'] == 'SLSQP_SCALED_X'],
                     'ALL_ARCHIVED_VARIANTS_AND_NEW_X': combined}
            data = {'case_id': old['case_id'], 'archived_input_sha256': fingerprint(record),
                'strict_witness_preserved_without_optimization': False, 'archived_endpoint_audits': trial_audits,
                'new_trials': new, 'envelopes': {k: empirical_envelopes(problem, e) for k, e in pools.items()}}
            archived_rows.extend(trial_audits)
            new_rows.extend(new)
        write_new(out/name.replace('_CD2_case', '_CD3_case'), data)
        # Keep only scalar envelope maxima in memory; full diagnostics stay in per-case files.
        cases.append({k: v for k, v in data.items() if k not in ('archived_endpoint_audits', 'new_trials')})
        print(json.dumps({'case': old['case_id'], 'archived_audits': len(trial_audits),
            'new_trials': 0 if not trial_audits else len(new)}), flush=True)
    if (len(cases), len(archived_rows), len(new_rows), sum(c['strict_witness_preserved_without_optimization'] for c in cases)) != (63, 396, 396, 30):
        raise AssertionError('CD3_PREREGISTERED_CENSUS_FAILED')
    oldfd, newfd = fd_totals(archived_rows), fd_totals(new_rows)
    summary = {'phase': p['phase'], 'protocol_sha256': PROTOCOL_SHA, 'preregistration_commit': PREREG_COMMIT,
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'code_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                       for f in sorted(Path(__file__).parent.glob('p9_3b3_cd3_*.py'))},
        'protected_files_unchanged': len(p['protected_control_sha256']), 'case_count': len(cases),
        'strict_witnesses_preserved': 30, 'archived_endpoint_FD': oldfd, 'new_endpoint_FD': newfd,
        'derivative_check_closed': all(r['reports'] == 792 and r['passed_reports'] == 792
            and r['unavailable_columns'] == 0 and r['diagnostic_errors'] == 0 for r in (oldfd, newfd)),
        'new_trial_count': len(new_rows),
        'new_physical_status_counts': dict(Counter(r['physical_admissibility'] for r in new_rows)),
        'new_solver_status_counts': dict(Counter(str(r['solver_status']) for r in new_rows)),
        'new_solver_success_count': sum(r['solver_success'] for r in new_rows),
        'new_optimizer_CPU_seconds': sum(r['optimizer_CPU_seconds'] for r in new_rows),
        'new_optimizer_wall_seconds': sum(r['optimizer_wall_seconds'] for r in new_rows),
        'new_nfev': sum(r.get('nfev', 0) for r in new_rows),
        'empirical_profile_spreads': envelope_summary(cases),
        'local_optimum_certified': False, 'global_optimum_certified': False,
        'independent_accuracy': 'NOT_QUALIFIED', 'operational_ready': False,
        'B4_qualified': False, 'production_epw_ready': False, 'C2_correction_budget': 'NOT_ESTABLISHED',
        'source_semantics_fully_verified': False, 'default_solver_changed': False, 'main_merged': False,
        'runtime': {'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__},
        'wall_seconds': time.perf_counter()-started, 'CPU_seconds': time.process_time()-cpu,
        'peak_RSS_KiB_Linux': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    guard()
    write_new(out/'CD3_summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    r = run(parser.parse_args().out)
    print(json.dumps(r, ensure_ascii=False))
