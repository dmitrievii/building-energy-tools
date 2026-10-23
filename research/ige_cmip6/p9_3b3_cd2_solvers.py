"""CD2: equivalent coordinates and an independent optimizer of frozen C2.

The scalar objective is never rescaled. Positive constraint scales preserve
the exact feasible set, not necessarily a solver's numerical stopping test.
The exact WATER_ICE switch remains in all objective evaluations.
"""
from __future__ import annotations

import time
import types
import warnings

import numpy as np
from scipy.optimize import NonlinearConstraint, OptimizeResult, minimize

import p9_3b3_c2_projection as frozen
from p9_3b3_cd1_diagnostics import View, ACTIVE, FD_STEPS, finite_differences, kkt_fit
from p9_3b3_compare_vertical_frame import fingerprint


VARIANTS = (
    {'id': 'FROZEN_C2', 'algorithm': 'SLSQP', 'scaled_variables': False, 'scaled_constraints': False},
    {'id': 'SLSQP_SCALED_X', 'algorithm': 'SLSQP', 'scaled_variables': True, 'scaled_constraints': False},
    {'id': 'SLSQP_SCALED_XC', 'algorithm': 'SLSQP', 'scaled_variables': True, 'scaled_constraints': True},
    {'id': 'COBYQA_SCALED_XC', 'algorithm': 'COBYQA', 'scaled_variables': True, 'scaled_constraints': True},
)
SLSQP_OPTIONS = {'maxiter': 180, 'ftol': 1e-11, 'disp': False}
COBYQA_OPTIONS = {'maxiter': 180, 'maxfev': 2000, 'initial_tr_radius': 1.,
    'final_tr_radius': 1e-6, 'feasibility_tol': 1e-9, 'scale': False, 'disp': False}


class Coordinates:
    def __init__(self, center, scale, bounds):
        self.c, self.D, self.bounds = (np.asarray(v, float) for v in (center, scale, bounds))
        if (self.c.ndim != 1 or self.D.shape != self.c.shape or
                self.bounds.shape != (len(self.c), 2) or np.any(self.D <= 0) or
                not all(np.all(np.isfinite(v)) for v in (self.c, self.D, self.bounds)) or
                np.any(self.bounds[:, 0] > self.bounds[:, 1])):
            raise ValueError('CD2_INVALID_INVERTIBLE_COORDINATES')
        self.scaled_bounds = (self.bounds-self.c[:, None])/self.D[:, None]

    def x(self, y):
        return self.c+self.D*np.asarray(y)

    def y(self, x):
        return (np.asarray(x)-self.c)/self.D

    def objective(self, fun):
        def transformed(y):
            value, gradient = fun(self.x(y))
            return value, np.asarray(gradient)*self.D
        return transformed

    def constraints(self, constraints, scales):
        if len(constraints) != len(scales) or any(not np.isfinite(s) or s <= 0 for s in scales):
            raise ValueError('CD2_NONPOSITIVE_CONSTRAINT_SCALE')
        return [{'type': c['type'],
            'fun': lambda y, c=c, s=s: c['fun'](self.x(y))/s,
            'jac': lambda y, c=c, s=s: np.asarray(c['jac'](self.x(y)))*self.D/s}
            for c, s in zip(constraints, scales)]


def solve_equivalent(fun, x0, bounds, constraints, coordinates, scales, algorithm, callback=None):
    """Run a real optimizer; return its physical-coordinate endpoint and counts.

    No clipping, smoothing, added phase bounds, objective normalization, or
    warm start is allowed here. COBYQA receives no analytic derivatives.
    """
    counts = {'objective_calls': 0, 'constraint_calls': 0, 'constraint_Jacobian_calls': 0}
    transformed = coordinates.objective(fun)
    def objective(y):
        counts['objective_calls'] += 1
        value, gradient = transformed(y)
        return (value, gradient) if algorithm == 'SLSQP' else value
    mapped = coordinates.constraints(constraints, scales)
    counted = []
    for c in mapped:
        def value(y, c=c):
            counts['constraint_calls'] += 1
            return c['fun'](y)
        def jac(y, c=c):
            counts['constraint_Jacobian_calls'] += 1
            return c['jac'](y)
        counted.append(dict(type=c['type'], fun=value, jac=jac))
    cb = None if callback is None else lambda y: callback(coordinates.x(y))
    common = dict(bounds=coordinates.scaled_bounds, callback=cb)
    if algorithm == 'SLSQP':
        result = minimize(objective, coordinates.y(x0), method='SLSQP', jac=True,
            constraints=counted, options=SLSQP_OPTIONS.copy(), **common)
    elif algorithm == 'COBYQA':
        nonlinear = [NonlinearConstraint(c['fun'], 0., 0. if c['type'] == 'eq' else np.inf) for c in counted]
        result = minimize(objective, coordinates.y(x0), method='COBYQA',
            constraints=nonlinear, options=COBYQA_OPTIONS.copy(), **common)
    else:
        raise ValueError('CD2_UNREGISTERED_ALGORITHM')
    result = OptimizeResult(result)
    result['solver_coordinate_x'] = np.asarray(result.x).copy()
    result.x = coordinates.x(result.x)
    return result, counts


def _point(view, x, previous=None):
    try:
        return view.point(x, previous)
    except (ValueError, FloatingPointError) as error:
        return {'diagnostics_unavailable': str(error)}


def endpoint(view, x):
    try:
        validation = view.p.validate(x, view.hq, view.hr)
        reason = None
    except ValueError as error:
        validation, reason = None, str(error)
    out = {'physical_admissibility': 'VALIDATED' if validation else 'REJECTED',
           'independent_validation': validation, 'rejection_reason': reason}
    try:
        F, gradient = view.objective(x)
        g, Ag, h, Ah = view.values(x)
        if not np.isfinite(F) or not np.all(np.isfinite(gradient)):
            raise ValueError('CD2_NONFINITE_ENDPOINT_OBJECTIVE')
        out.update(final=view.point(x),
            first_order=[kkt_fit(np.asarray(gradient)*view.D/max(1., abs(F)), g, Ag, h, Ah, t) for t in ACTIVE],
            finite_differences=[finite_differences(view, x, h) for h in FD_STEPS],
            original_F_recomputed=float(F))
    except (ValueError, FloatingPointError) as error:
        out['diagnostics_unavailable'] = str(error)
    return out


def solve_variant(donor_T, donor_q, target, pressure, variant_id, *, donor_date,
                  pressure_alignment='TARGET_DAY_EXTERNAL_FIXED', strict_witness=None,
                  q_weights=None, RH_weights=None, T_weights=None):
    """Keep frozen strict-first and selection; replace only its minimizer call."""
    variants = {v['id']: v for v in VARIANTS}
    if variant_id not in variants:
        raise ValueError('CD2_UNREGISTERED_VARIANT')
    variant = variants[variant_id]
    kwargs = dict(donor_date=donor_date, pressure_alignment=pressure_alignment,
        strict_witness=strict_witness, mode='BOTH_SOFT', q_weights=q_weights,
        RH_weights=RH_weights, T_weights=T_weights)
    before = fingerprint({'T': list(donor_T), 'q': list(donor_q), 'target': target.to_dict(), 'p': pressure.metadata()})
    problem = frozen.ProjectionProblem(donor_T, donor_q, target, pressure, q_weights, RH_weights, T_weights)
    metric = frozen.ProjectionMetric()
    view = View(problem, metric, 'SOFT_SOURCE_PROJECTION', 'BOTH_SOFT')
    coordinates = Coordinates(np.r_[problem.T0[problem.free], np.zeros(problem.n)], view.D, view.bounds)
    real_minimize, captures = frozen.minimize, []
    baseline = frozen.project_day(donor_T, donor_q, target, pressure, **kwargs) if variant_id == 'FROZEN_C2' else None

    def replacement(fun, x0, *args, **kw):
        if args or kw.get('jac') is not True or kw['options'] != SLSQP_OPTIONS:
            raise ValueError('CD2_FROZEN_MINIMIZER_CONTRACT_CHANGED')
        record = {'initial': np.array(x0, copy=True), 'iterates': []}
        def callback(x):
            record['iterates'].append(np.array(x, copy=True))
        wall, cpu = time.perf_counter(), time.process_time()
        counts, error = None, None
        if variant_id == 'FROZEN_C2':
            result = real_minimize(fun, x0, **(kw | {'callback': callback}))
        else:
            scales = view.scales if variant['scaled_constraints'] else np.ones(len(kw['constraints']))
            try:
                with warnings.catch_warnings(record=True) as logged:
                    warnings.simplefilter('always')
                    result, counts = solve_equivalent(fun, x0, kw['bounds'], kw['constraints'],
                        coordinates, scales, variant['algorithm'], callback)
                record['warnings'] = [str(w.message) for w in logged]
            except Exception as exc:
                # Explicit failed trial, never a substituted initial/last state.
                error = type(exc).__name__+': '+str(exc)
                result = OptimizeResult(x=np.full_like(x0, np.nan), success=False, status=-100,
                    nit=0, nfev=0, njev=0, message='CD2_ALGORITHM_EXCEPTION: '+error)
        record.update(result=result, wall_seconds=time.perf_counter()-wall,
            CPU_seconds=time.process_time()-cpu, call_counts=counts, algorithm_error=error)
        captures.append(record)
        return result

    globals_copy = dict(frozen.project_day.__globals__, minimize=replacement)
    observed = types.FunctionType(frozen.project_day.__code__, globals_copy,
        frozen.project_day.__name__, frozen.project_day.__defaults__, frozen.project_day.__closure__)
    observed.__kwdefaults__ = dict(frozen.project_day.__kwdefaults__)
    raw = observed(donor_T, donor_q, target, pressure, **kwargs)
    if baseline is not None and baseline != raw:
        raise AssertionError('CD2_CONTROL_OBSERVER_CHANGED_FROZEN_OUTPUT')
    if frozen.minimize is not real_minimize:
        raise AssertionError('CD2_FROZEN_MODULE_GLOBALS_CHANGED')
    if len(captures) != len(raw.get('optimizer_trials', [])):
        raise AssertionError('CD2_TRIAL_CAPTURE_CENSUS')
    selected = raw.get('selected_optimizer_trial')
    if raw.get('method') == 'STRICT_SEARCH_WITNESS_PRESERVED':
        selected = len(captures)-1
    records = []
    for i, (c, old) in enumerate(zip(captures, raw.get('optimizer_trials', []))):
        sol = c['result']; x = np.asarray(sol.x)
        trial_view = View(problem, metric, old['stage'], 'BOTH_SOFT')
        history, previous = [], None
        for iteration, point in enumerate([c['initial']]+c['iterates']):
            history.append({'iteration': iteration, **_point(trial_view, point, previous)})
            previous = point
        records.append({'trial_index': i, 'selected': i == selected, 'stage': old['stage'],
            'solver_success': bool(sol.success), 'solver_status': int(sol.status), 'message': str(sol.message),
            'iterations': int(sol.nit), 'nfev': int(sol.nfev), 'njev': int(sol.get('njev', 0)),
            'initial_x': c['initial'].tolist(), 'initial_x_sha256': fingerprint(c['initial'].tolist()),
            'final_x': x.tolist() if np.all(np.isfinite(x)) else None,
            'algorithm_error': c['algorithm_error'], 'warnings': c.get('warnings', []),
            'wall_seconds': c['wall_seconds'], 'CPU_seconds': c['CPU_seconds'], 'call_counts': c['call_counts'],
            'iteration_journal': history, **endpoint(trial_view, x),
            'phase_scope': 'EXACT_SOURCE_SWITCH_NO_SMOOTHING; FIRST_ORDER_WITHIN_BRANCH_ONLY',
            'local_optimum_certified': False, 'global_optimum_certified': False})
    if selected is not None:
        s = records[selected]
        if s['physical_admissibility'] != 'VALIDATED':
            raise AssertionError('CD2_SELECTED_CANDIDATE_REJECTED')
        T, q = problem.base.unpack(np.asarray(s['final_x']))
        assert T.tolist() == raw['T_K'] and q.tolist() == raw['q_kgkg']
        assert s['original_F_recomputed'] == raw['objective']['total']
    if 'T_K' in raw and raw['p_Pa'] != list(pressure.values_Pa):
        raise AssertionError('CD2_PRESSURE_CHANGED')
    after = fingerprint({'T': list(donor_T), 'q': list(donor_q), 'target': target.to_dict(), 'p': pressure.metadata()})
    if before != after:
        raise AssertionError('CD2_INPUT_MUTATED')
    return {'schema_version': 'IGE_CD2_EQUIVALENT_SOLVER_v1', 'variant': dict(variant),
        'frozen_result': raw, 'selected_trial_index': selected, 'trials': records,
        'same_runtime_control_exactly_equal': baseline == raw if baseline is not None else None,
        'inputs_unchanged': True, 'module_globals_unchanged': True,
        'objective_unmodified': True, 'coordinate_center': coordinates.c.tolist(), 'coordinate_scale': coordinates.D.tolist(),
        'local_optimum_certified': False, 'global_optimum_certified': False,
        'independent_accuracy': 'NOT_QUALIFIED', 'operational_ready': False}
