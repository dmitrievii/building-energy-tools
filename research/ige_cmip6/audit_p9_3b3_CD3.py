"""Independent scalar F replay and original-three versus registered-twelve audit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

from audit_p9_3b3_CD2 import scalar_objective
from p9_3b3_c2_projection import ProjectionProblem
from p9_3b3_cd1_run import write_new
from p9_3b3_cd2_run import guard, load_registered_inputs, case_inputs


def audit(directory):
    directory = Path(directory)
    inputs, baseline, _ = load_registered_inputs(guard())
    inputs = {r['case_id']: r for r in inputs}
    rows, maximum, n, case_ids = [], 0., 0, set()
    for f in sorted(directory.glob('*_CD3_case.json')):
        case = json.loads(f.read_text())
        identity = case['case_id']
        if identity in case_ids or identity not in inputs:
            raise ValueError('CD3_AUDIT_CASE_CENSUS')
        case_ids.add(identity)
        if not case['new_trials']:
            if not case['strict_witness_preserved_without_optimization']:
                raise ValueError('CD3_AUDIT_MISSING_TRIALS')
            continue
        record = inputs[identity]
        args, kwargs, _, _ = case_inputs(record, baseline)
        p = ProjectionProblem(*args, q_weights=kwargs['q_weights'], RH_weights=kwargs['RH_weights'],
                              T_weights=kwargs['T_weights'])
        for r in case['archived_endpoint_audits']+case['new_trials']:
            T, q = p.base.unpack(np.array(r['final_x']))
            p.validate(np.asarray(r['final_x']))
            value = scalar_objective(T.tolist(), p.P.tolist(), q.tolist(), record)['total']
            error = abs(value-r['F_original'])/max(1., abs(r['F_original']))
            maximum = max(maximum, error)
            n += 1
            if not np.isfinite(error) or error > 1e-12:
                raise ValueError('CD3_ORIGINAL_F_SCALAR_MISMATCH')
        original = min(case['new_trials'][:3], key=lambda r: r['F_original'])
        all_starts = min(case['new_trials'], key=lambda r: r['F_original'])
        T0, q0 = p.base.unpack(np.asarray(original['final_x']))
        T1, q1 = p.base.unpack(np.asarray(all_starts['final_x']))
        rows.append({'case_id': identity, 'original_3_min_F': original['F_original'],
            'all_12_min_F': all_starts['F_original'], 'improvement': original['F_original']-all_starts['F_original'],
            'relative_to_max1F': (original['F_original']-all_starts['F_original'])/max(1., abs(all_starts['F_original'])),
            'max_T_difference_K': float(np.max(abs(T0-T1))), 'max_q_difference_gkg': float(np.max(abs(q0-q1))*1000),
            'original_ice_nodes': int(np.sum(T0 < 273.15)), 'all_12_ice_nodes': int(np.sum(T1 < 273.15)),
            'changed_phase_nodes': int(np.sum((T0 < 273.15) != (T1 < 273.15))),
            'best_original_start': original['id'], 'best_all_start': all_starts['id']})
    if case_ids != set(inputs) or n != 792 or len(rows) != 33:
        raise ValueError('CD3_AUDIT_INCOMPLETE_63_CASE_792_ENDPOINT_CENSUS')
    return {'audited_cases': len(case_ids), 'audited_endpoints': n,
        'max_relative_original_F_scalar_error': maximum,
        'original_3_vs_all_12': rows,
        'cases_improved_above_1e_8_max1F': sum(r['relative_to_max1F'] > 1e-8 for r in rows),
        'max_3_vs_12_T_difference_K': max(r['max_T_difference_K'] for r in rows),
        'no_global_minimum_or_accuracy_certificate': True,
        'audit_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    r = audit(args.input)
    write_new(args.out, r)
    print(json.dumps({k: v for k, v in r.items() if k != 'original_3_vs_all_12'}))
