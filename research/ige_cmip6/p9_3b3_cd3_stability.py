"""Registered multistart and finite empirical sublevel endpoint sets.

These are research diagnostics of the unchanged problem. No confidence
interval, global sublevel enclosure or meteorological error budget is implied.
"""
from __future__ import annotations

import hashlib
import time
import warnings
import numpy as np

from p9_3b3_c2_projection import ProjectionMetric
from p9_3b3_cd1_diagnostics import View, ACTIVE, kkt_fit
from p9_3b3_cd2_solvers import Coordinates, solve_equivalent
from p9_3b3_cd3_diagnostics import second_order_fd, STEPS
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_thermodynamics import q_saturation, relative_humidity, e_from_q, MK, epsilon_for


DELTAS = (1e-10, 1e-8, 1e-6, 1e-4)


def registered_starts(problem, case_id):
    if problem.target.semantics.temperature_operator != 'DERIVED_TAS_MIDRANGE':
        raise ValueError('CD3_START_DESIGN_REQUIRES_REGISTERED_MIDRANGE_COHORT')
    rows = [{'id': 'ORIGINAL_'+str(i), 'x': np.array(x, copy=True)}
            for i, x in enumerate(problem.starts())]
    seed = int.from_bytes(hashlib.sha256(('20261023|'+case_id).encode()).digest()[:16], 'little')
    rng = np.random.Generator(np.random.PCG64(seed))
    angles = 2*np.pi*np.arange(problem.n)/problem.n
    patterns = (np.sin(angles), np.cos(angles), rng.uniform(-1, 1, problem.n))
    for index, pattern in enumerate(patterns):
        d = .5*np.where(pattern >= 0, problem.base.high-problem.T0, problem.T0-problem.base.low)*pattern
        slopes = np.diff(problem.T0)*problem.n/24
        ds = np.diff(d)*problem.n/24
        ratios = [1.]
        for value, change in zip(slopes, ds):
            if change > 0:
                ratios.append(max(0., (problem.base.slope-value)/change))
            elif change < 0:
                ratios.append(max(0., (-problem.base.slope-value)/change))
        alpha = min(1., .9*min(ratios))
        T = problem.T0+alpha*d
        caps = q_saturation(T, problem.P)
        for fraction in (.1, .5, .9):
            x = problem.base.pack(T, fraction*caps)
            validation = problem.validate(x, False, False)
            rows.append({'id': 'PATTERN_'+str(index)+'_Q_'+str(fraction), 'x': x,
                'seed_integer': str(seed), 'T_segment_fraction': alpha,
                'initial_validation': validation})
    if len(rows) != 12:
        raise AssertionError('CD3_START_CENSUS')
    return rows


def audit_endpoint(view, x):
    original = np.array(x, copy=True)
    validation = view.p.validate(x, view.hq, view.hr)
    F, gradient = view.objective(x)
    g, Ag, h, Ah = view.values(x)
    fd, errors = [], []
    for step in STEPS:
        try:
            fd.append(second_order_fd(view, x, step))
        except (ValueError, FloatingPointError) as error:
            errors.append(str(error))
            fd.append({'dimensionless_step': step, 'pass': False, 'column_count': len(x),
                'checked_columns': 0, 'unavailable_columns': [{'column': j, 'reason': str(error)} for j in range(len(x))],
                'recorded_base_roundoff_columns': [], 'objective_max_relative_error': None,
                'constraint_Jacobian_max_relative_error': None})
    data = {'physical_admissibility': 'VALIDATED', 'validation': validation,
        'F_original': float(F), 'finite_differences': fd, 'diagnostic_error': '; '.join(errors) or None,
        'first_order': [kkt_fit(np.asarray(gradient)*view.D/max(1., abs(F)), g, Ag, h, Ah, a) for a in ACTIVE]}
    if not np.array_equal(x, original):
        raise AssertionError('CD3_AUDIT_MUTATED_ENDPOINT')
    return data


def run_starts(problem, case_id):
    metric = ProjectionMetric()
    view = View(problem, metric, 'SOFT_SOURCE_PROJECTION', 'BOTH_SOFT')
    coordinates = Coordinates(np.r_[problem.T0[problem.free], np.zeros(problem.n)], view.D, view.bounds)
    results = []
    for start in registered_starts(problem, case_id):
        x0 = start['x'].copy()
        phases = [view.phase(x0)]
        def callback(x):
            phases.append(view.phase(x))
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            with warnings.catch_warnings(record=True) as logged:
                warnings.simplefilter('always')
                sol, counts = solve_equivalent(lambda x: problem.objective(x, metric), x0,
                    view.bounds, view.constraints, coordinates, np.ones(len(view.constraints)), 'SLSQP', callback)
            row = {k: v for k, v in start.items() if k != 'x'}
            row.update(initial_x=x0.tolist(), initial_x_sha256=fingerprint(x0.tolist()),
                final_x=np.asarray(sol.x).tolist(), solver_success=bool(sol.success),
                solver_status=int(sol.status), message=str(sol.message), iterations=int(sol.nit),
                nfev=int(sol.nfev), njev=int(sol.njev), call_counts=counts,
                warnings=[str(w.message) for w in logged],
                phase_crossings=sum(int(np.sum(a != b)) for a, b in zip(phases, phases[1:])),
                optimizer_wall_seconds=time.perf_counter()-wall, optimizer_CPU_seconds=time.process_time()-cpu)
            try:
                row['validation'] = problem.validate(np.asarray(sol.x), False, False)
                row['physical_admissibility'] = 'VALIDATED'
            except (ValueError, FloatingPointError) as error:
                row.update(physical_admissibility='REJECTED', rejection_reason=str(error))
            try:
                if row['physical_admissibility'] != 'VALIDATED':
                    raise ValueError('CD3_REJECTED_ENDPOINT_NOT_AUDITED')
                row.update(audit_endpoint(view, np.asarray(sol.x)))
            except (ValueError, FloatingPointError) as error:
                row['diagnostic_error'] = str(error)
        except Exception as error:
            row = {'id': start['id'], 'initial_x': x0.tolist(), 'initial_x_sha256': fingerprint(x0.tolist()),
                'final_x': None, 'solver_success': False, 'solver_status': -100,
                'physical_admissibility': 'ALGORITHM_ERROR', 'algorithm_error': type(error).__name__+': '+str(error),
                'optimizer_wall_seconds': time.perf_counter()-wall, 'optimizer_CPU_seconds': time.process_time()-cpu}
        results.append(row)
    return results


def empirical_envelopes(problem, endpoints, deltas=DELTAS):
    """Input states must already have been checked against the original problem."""
    if not endpoints:
        return {'endpoint_count': 0, 'sets': [], 'scope': 'NO_VALIDATED_ENDPOINTS'}
    F = np.array([r['F_original'] for r in endpoints])
    Fmin = float(np.min(F))
    T, q = zip(*(problem.base.unpack(np.asarray(r['final_x'])) for r in endpoints))
    T, q = np.asarray(T), np.asarray(q)
    RH = relative_humidity(T, problem.P, q, problem.base.phase, MK)
    e = e_from_q(q, problem.P, epsilon_for(MK))
    sets = []
    for delta in deltas:
        tolerance = delta*max(1., abs(Fmin))
        ids = np.flatnonzero(F-Fmin <= tolerance)
        tt, qq, rr, ee = T[ids], q[ids]*1000, RH[ids], e[ids]
        def spread(a):
            return {'min': a.min(axis=0).tolist(), 'max': a.max(axis=0).tolist(),
                'max_pair_difference': float(np.max(np.ptp(a, axis=0))),
                'max_pair_RMS': max(float(np.sqrt(np.mean((u-v)**2))) for u in a for v in a)}
        sets.append({'relative_delta': delta, 'absolute_F_tolerance': tolerance, 'endpoint_count': len(ids),
            'endpoint_ids': [endpoints[i]['id'] for i in ids], 'T_K': spread(tt), 'q_gkg': spread(qq),
            'RH_source_pp': spread(rr), 'e_Pa': spread(ee),
            'daily_q_mean_spread_gkg': float(np.ptp(qq@problem.u)),
            'daily_RH_mean_spread_pp': float(np.ptp(rr@problem.v)),
            'distinct_ice_node_patterns': len({tuple(t < 273.15) for t in tt}) if problem.base.phase == 'WATER_ICE' else 1})
    return {'endpoint_count': len(endpoints), 'minimum_F': Fmin,
        'all_endpoint_F_gaps': [{'id': r['id'], 'gap': float(f-Fmin), 'solver_success': r['solver_success']}
                                for r, f in zip(endpoints, F)], 'sets': sets,
        'scope': 'FINITE_EMPIRICAL_ENDPOINT_SET_NOT_GLOBAL_SUBLEVEL_OR_CONFIDENCE_INTERVAL',
        'local_optimum_certified': False, 'global_optimum_certified': False,
        'independent_accuracy': 'NOT_QUALIFIED'}
