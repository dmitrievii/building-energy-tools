"""Three versioned closure problems on common NASA operators and fixed p.

Strict/C2 share frozen variable-T geometry. Q-only is a smaller fixed-T
convex problem; its certificates do not exclude the larger joint domain.
"""
from __future__ import annotations
from dataclasses import asdict
import time
import warnings

import numpy as np
from scipy.optimize import minimize

from p9_3b3_c2_projection import ProjectionProblem, project_day
from p9_3b3_c2_validation import validate_projection
from p9_3b3_compare_identified_set import PressureBox, MeanInterval, identified_bounds
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_daily_feasibility import fixed_profile_feasibility
from p9_3b3_joint_solver import affine_temperature
from p9_3b3_thermodynamics import q_saturation, state_diagnostics


METHODS = ('STRICT_JOINT_T_Q_FIXED_P', 'Q_ONLY_FIXED_T_P', 'C2_BOTH_SOFT_STRICT_FIRST')


def project_q(prior, caps, target, mean_weights):
    """Unique unweighted L2 box/equality projection, including zero support.

    q=clip(q0+lambda*u,0,c). Constant shift would solve a different objective
    when u is nonuniform. Bisection brackets actual clipping breakpoints.
    """
    q0, c, u = (np.asarray(v, float) for v in (prior, caps, mean_weights))
    if (q0.ndim != 1 or not len(q0) or c.shape != q0.shape or u.shape != q0.shape
            or not np.isfinite(np.r_[q0, c, u, target]).all() or np.any(c < 0)
            or np.any(u < 0) or abs(u.sum()-1) > 1e-12):
        raise ValueError('TPA_Q_PROJECTION_DOMAIN')
    capacity = float(u@c)
    if target < -1e-12 or target > capacity+1e-9:
        return {'status': 'CERTIFIED_INFEASIBLE', 'reason': 'FIXED_T_Q_MEAN_OUTSIDE_BOX_CAPACITY',
                'scope': 'FIXED_T_P_ONLY_NOT_JOINT_T_DOMAIN', 'q_capacity': capacity, 'q_target': target}
    active = u > 0
    if target <= 0 or target >= capacity:
        q = np.clip(q0, 0, c)
        q[active] = 0 if target <= 0 else c[active]
        lam = None
    else:
        lower = float(np.min(-q0[active]/u[active]))
        upper = float(np.max((c[active]-q0[active])/u[active]))
        for _ in range(100):
            lam = (lower+upper)/2
            q = np.clip(q0+lam*u, 0, c)
            if float(u@q) < target:
                lower = lam
            else:
                upper = lam
        lam = (lower+upper)/2
        q = np.clip(q0+lam*u, 0, c)
    if abs(float(u@q)-target) > 1e-9:
        return {'status': 'UNRESOLVED', 'reason': 'Q_PROJECTION_NUMERIC_RESIDUAL'}
    return {'status': 'FEASIBLE', 'q_kgkg': q.tolist(), 'q_capacity': capacity,
            'multiplier': lam, 'mean_residual_kgkg': float(u@q)-target,
            'objective': .5*float(np.sum((q-q0)**2)),
            'optimality': 'UNIQUE_STRICTLY_CONVEX_KKT_WITHIN_NUMERICAL_TOLERANCE'}


def strict_joint(donor_T, donor_q, target, pressure):
    reference = pressure.comparison_reference()
    problem = ProjectionProblem(donor_T, donor_q, target.legacy_target(), reference,
                                target.q_weights, target.RH_weights, target.T_weights)
    tcheck = problem.temperature_feasibility()
    if tcheck['status'] in ('CERTIFIED_T_DOMAIN_INFEASIBLE', 'T_DOMAIN_NUMERICALLY_UNRESOLVED'):
        return {'status': tcheck['status'], 'certificate': tcheck, 'scope': 'THIS_DECLARED_T_PRIOR_ONLY'}
    outer = identified_bounds(problem.base.low, problem.base.high,
        PressureBox(tuple(problem.P), tuple(problem.P), reference.frame, reference.fingerprint),
        MeanInterval(target.q_mean_kgkg, target.q_mean_kgkg, 'kg/kg', target.fingerprint),
        MeanInterval(target.RH_mean_pct, target.RH_mean_pct, '%', target.fingerprint),
        target.q_weights, target.RH_weights, phase=target.rh_phase)
    if outer['status'] == 'CERTIFIED_INFEASIBLE':
        return {'status': 'CERTIFIED_INFEASIBLE', 'certificate': outer,
                'scope': 'DECLARED_T_BOX_FIXED_P_OPERATORS_NOT_ALL_ATMOSPHERIC_WEATHER'}
    starts = problem.starts()
    if hasattr(problem, '_T_lp'):
        starts[1] = problem.base.pack(problem._T_lp, np.minimum(problem.q0, q_saturation(problem._T_lp, problem.P)))
    if np.array_equal(problem.u, problem.v) and np.all(problem.u > 0):
        f = fixed_profile_feasibility(problem.T0, problem.P, target.q_mean_kgkg, target.RH_mean_pct,
                                      target.rh_phase, weights=problem.u, lower_time_limit=0)
        if 'witness_q' in f:
            # Preserve an already valid prior before using an arbitrary
            # feasible RH segment witness. Start count for local search stays 2.
            starts.append(problem.base.pack(problem.T0, np.asarray(f['witness_q'])))
    for x in starts:
        try:
            problem.validate(x, True, True)
        except ValueError:
            continue
        t, q = problem.base.unpack(x)
        return {'status': 'EXACT_DEFINED_OPERATORS', 'T_K': t.tolist(), 'q_kgkg': q.tolist(),
                'p_Pa': problem.P.tolist(), 'method': 'VALIDATED_START_OR_FIXED_PROFILE_WITNESS',
                'global_shape_optimum_certified': False}
    trials = []
    for x in starts[:2]:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            sol = minimize(problem.shape, x, jac=True, method='SLSQP', bounds=problem.base.bounds,
                constraints=problem.constraints(True, True), options={'maxiter': 180, 'ftol': 1e-11, 'disp': False})
        trials.append({'success': bool(sol.success), 'iterations': int(sol.nit), 'message': str(sol.message)})
        try:
            problem.validate(sol.x, True, True)
        except ValueError:
            continue
        t, q = problem.base.unpack(sol.x)
        return {'status': 'EXACT_DEFINED_OPERATORS', 'T_K': t.tolist(), 'q_kgkg': q.tolist(),
                'p_Pa': problem.P.tolist(), 'optimizer_trials': trials, 'global_shape_optimum_certified': False}
    return {'status': 'UNRESOLVED', 'reason': 'JOINT_LOCAL_SEARCH_DID_NOT_ESTABLISH_A_WITNESS',
            'optimizer_trials': trials, 'outer_bound': outer, 'scope': 'NO_INFEASIBILITY_CLAIM'}


def package(raw, method, target, pressure, donor_T, donor_q):
    """Revalidate actual arrays and journal every diagnostic, including failure."""
    state = 'T_K' in raw and 'q_kgkg' in raw
    hard_q = method in METHODS[:2]
    hard_rh = method == METHODS[0]
    valid, diagnostic = None, None
    if state:
        if raw['p_Pa'] != list(pressure.values_Pa):
            raise ValueError('TPA_RESULT_PRESSURE_CHANGED')
        valid = validate_projection(raw['T_K'], raw['p_Pa'], raw['q_kgkg'], target.legacy_target(),
            pressure.values_Pa, donor_T, target.q_weights, target.RH_weights, target.T_weights,
            hard_q=hard_q, hard_RH=hard_rh)
        diagnostic = state_diagnostics(raw['T_K'], raw['p_Pa'], raw['q_kgkg'], target.rh_phase)
    achieved = ({'tasmin': min(raw['T_K']), 'tasmax': max(raw['T_K']),
                 'tas': ((min(raw['T_K'])+max(raw['T_K']))/2 if target.temperature_operator == 'DERIVED_TAS_MIDRANGE'
                         else float(np.dot(target.T_weights, raw['T_K']))),
                 'huss': valid['q_mean_kgkg'], 'hurs': valid['RH_source_mean_pct']} if state else {})
    source = {'tasmin': target.Tmin_K, 'tasmax': target.Tmax_K, 'tas': target.tas_K,
              'huss': target.q_mean_kgkg, 'hurs': target.RH_mean_pct}
    journal = []
    for variable, value in source.items():
        output = achieved.get(variable)
        delta = output-value if state else None
        tol = 1e-9 if variable == 'huss' else 1e-4 if variable == 'hurs' else 5e-5
        role = ('HARD' if variable.startswith('tas') or variable == 'huss' and hard_q or variable == 'hurs' and hard_rh
                else 'DIAGNOSTIC_NOT_ENFORCED' if method == METHODS[1] else 'SOFT_RESEARCH_METRIC')
        operator = ('MIN' if variable == 'tasmin' else 'MAX' if variable == 'tasmax'
                    else target.temperature_operator if variable == 'tas' else 'DECLARED_WEIGHTED_TIME_MEAN')
        w = target.q_weights if variable == 'huss' else target.RH_weights if variable == 'hurs' else target.T_weights
        journal.append({'variable': variable, 'requested': value, 'achieved': output, 'signed_delta': delta,
            'unit': 'kg/kg' if variable == 'huss' else 'percentage_point' if variable == 'hurs' else 'K',
            'constraint_role': role, 'operator': operator, 'weights_sha256': fingerprint(w),
            'phase': target.rh_phase if variable == 'hurs' else None,
            'source_diagnostic_changed': state and abs(delta) > tol,
            'correction_budget_established': False,
            'correction_acceptance': raw.get('correction_acceptance',
                'NO_VALIDATED_STATE' if not state else 'NO_SOURCE_DIAGNOSTIC_CHANGE' if abs(delta) <= tol
                else 'NOT_ESTABLISHED_RESEARCH_ONLY'),
            'reason': raw.get('reason', raw['status']), 'pressure_trajectory_sha256': pressure.fingerprint})
    changed = state and any(j['source_diagnostic_changed'] for j in journal)
    result = {**raw, 'schema_version': 'IGE_TPA1_THERMO_CLOSURE_v1',
        'comparison_method': method, 'source_diagnostics': source, 'achieved_diagnostics': achieved,
        'source_constraints_sha256': target.fingerprint, 'pressure_trajectory_sha256': pressure.fingerprint,
        'source_input_mutated': False, 'source_diagnostics_changed': changed, 'journal_all_diagnostics': journal,
        'validation': valid, 'diagnostics': diagnostic, 'pressure': pressure.metadata(),
        'constraint_domain': 'FIXED_T_P' if method == METHODS[1] else 'FROZEN_VARIABLE_T_DOMAIN_FIXED_P',
        'semantics': {'temperature_operator': target.temperature_operator, 'rh_phase': target.rh_phase,
                      'time_support': target.time_support, 'fully_verified': False,
                      'source_identity': target.source_identity, 'source_semantics_sha256': target.semantics_sha256},
        'quality': {'code_correctness': 'SEE_SEPARATE_TEST_EVIDENCE',
                    'physical_admissibility': 'CONDITIONAL_DISCRETE_GAS_STATE_VALIDATED' if state else 'NO_VALIDATED_STATE',
                    'independent_accuracy': 'NOT_QUALIFIED', 'operational_readiness': 'NOT_QUALIFIED'},
        'pressure_unchanged': True, 'B4_qualified': False, 'production_epw_ready': False,
        'source_fidelity': 'ALL_DAILY_DIAGNOSTICS_WITHIN_TOLERANCE' if state and not changed
                           else 'SOURCE_DIAGNOSTICS_DIFFER' if state else 'NO_STATE'}
    if state:
        affine = affine_temperature(donor_T, target.legacy_target())
        result['shape_adjustments'] = {'max_T_delta_from_affine_K': float(np.max(abs(np.asarray(raw['T_K'])-affine))),
            'max_q_delta_from_common_prior_gkg': float(np.max(abs(np.asarray(raw['q_kgkg'])-donor_q))*1000),
            'T_time_mean_K': valid['T_time_mean_K'], 'T_time_mean_is_hard_tas': target.temperature_operator == 'TIME_MEAN_TAS'}
    return result


def compare(target, pressure, donor_T=None, donor_q=None):
    if pressure.target_date != target.date:
        raise ValueError('TPA_CONSTRAINT_AND_TRAJECTORY_TARGET_DATE_MISMATCH')
    donor_T = tuple(pressure.prior_T_K if donor_T is None else donor_T)
    donor_q = tuple(pressure.prior_q_kgkg if donor_q is None else donor_q)
    if len(donor_T) != 24 or len(donor_q) != 24:
        raise ValueError('TPA_COMMON_PRIOR_REQUIRES_24_NODES')
    before = fingerprint({'target': asdict(target), 'pressure': asdict(pressure), 'T': donor_T, 'q': donor_q})
    rows = []
    start = time.perf_counter()
    strict = strict_joint(donor_T, donor_q, target, pressure)
    strict_time = time.perf_counter()-start
    rows.append(package(strict, METHODS[0], target, pressure, donor_T, donor_q))
    start = time.perf_counter()
    t0 = affine_temperature(donor_T, target.legacy_target())
    if target.temperature_operator == 'TIME_MEAN_TAS' and abs(np.dot(target.T_weights, t0)-target.tas_K) > 1e-6:
        qraw = {'status': 'CERTIFIED_INFEASIBLE', 'reason': 'FIXED_T_DOES_NOT_MATCH_TIME_MEAN_TAS',
                'scope': 'FIXED_T_ONLY_NOT_JOINT_T_DOMAIN'}
    else:
        qraw = project_q(donor_q, q_saturation(t0, pressure.values_Pa), target.q_mean_kgkg, target.q_weights)
        if qraw['status'] == 'FEASIBLE':
            qraw = {**qraw, 'status': 'Q_MEAN_EXACT_RH_DIAGNOSTIC', 'T_K': t0.tolist(), 'p_Pa': list(pressure.values_Pa)}
    qtime = time.perf_counter()-start
    rows.append(package(qraw, METHODS[1], target, pressure, donor_T, donor_q))
    start = time.perf_counter()
    raw = project_day(donor_T, donor_q, target.legacy_target(), pressure.comparison_reference(),
        mode='BOTH_SOFT', donor_date=pressure.source_date,
        pressure_alignment=('TARGET_DAY_EXTERNAL_FIXED' if pressure.alignment == 'TARGET_DAY_EXTERNAL_FIXED'
                            else 'REGISTERED_DONOR_PRESSURE_SENSITIVITY'),
        q_weights=target.q_weights, RH_weights=target.RH_weights, T_weights=target.T_weights,
        strict_witness=strict if strict['status'] == 'EXACT_DEFINED_OPERATORS' else None)
    ctime = time.perf_counter()-start
    rows.append(package(raw, METHODS[2], target, pressure, donor_T, donor_q))
    for row, elapsed in zip(rows, (strict_time, qtime, ctime)):
        row['wall_seconds'] = elapsed
        row['common_prior_sha256'] = fingerprint({'T': donor_T, 'q': donor_q})
    if strict['status'] == 'EXACT_DEFINED_OPERATORS':
        assert all(rows[0][k] == rows[2][k] for k in ('T_K', 'p_Pa', 'q_kgkg')), 'TPA_C2_MODIFIED_STRICT_WITNESS'
    if fingerprint({'target': asdict(target), 'pressure': asdict(pressure), 'T': donor_T, 'q': donor_q}) != before:
        raise AssertionError('TPA_IMMUTABLE_COMPARISON_INPUT_CHANGED')
    return rows
