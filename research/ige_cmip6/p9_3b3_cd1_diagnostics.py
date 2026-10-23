"""CD1 observer of frozen C2; diagnostics never change the optimizer path.

The frozen function code is reused with an isolated globals dictionary. The
only extra optimizer callback copies iterates. All numerical diagnostic work
is done afterwards. A small first-order residual is not an optimality proof.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import asdict
import types

import numpy as np
from scipy.optimize import lsq_linear

import p9_3b3_c2_projection as frozen
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_thermodynamics import saturation


ACTIVE = (1e-8, 1e-6, 1e-4)
FD_STEPS = (1e-5, 5e-6)


def kkt_fit(gradient, g, Ag, h, Ah, active_tolerance):
    """Fit grad - Ag.T lambda + Ah.T nu=0, including caller's bound rows.

    Inequalities are g>=0; lambda>=0, nu unrestricted. Minimize the L2
    residual; report its infinity norm too, without claiming L-infinity optimality.
    """
    grad, g, Ag, h, Ah = (np.asarray(a, float) for a in (gradient, g, Ag, h, Ah))
    n = len(grad)
    Ag, Ah = Ag.reshape((-1, n)), Ah.reshape((-1, n))
    active = g <= active_tolerance
    A = np.c_[Ag[active].T, -Ah.T]
    ni = int(active.sum())
    if A.shape[1]:
        solution = lsq_linear(A, grad, bounds=(np.r_[np.zeros(ni), np.full(len(h), -np.inf)], np.inf),
                              method='bvls', tol=1e-12, max_iter=1000, lsq_solver='exact')
        multipliers = solution.x
        residual = grad-A@multipliers
        success, status = bool(solution.success), int(solution.status)
    else:
        multipliers, residual, success, status = np.empty(0), grad, True, 3
    singular = np.linalg.svd(A, compute_uv=False) if A.size else np.empty(0)
    rank = int(np.linalg.matrix_rank(A)) if A.size else 0
    cond = float(singular[0]/singular[-1]) if len(singular) and singular[-1] > 0 else None
    if cond is not None and not np.isfinite(cond):
        cond = None
    return {'active_tolerance': active_tolerance, 'active_inequalities': ni, 'equalities': len(h),
        'least_squares_success': success, 'least_squares_status': status,
        'stationarity_L2': float(np.linalg.norm(residual)), 'stationarity_Linf': float(np.max(abs(residual))),
        'primal_violation_scaled': max(float(np.max(np.maximum(-g, 0), initial=0)), float(np.max(abs(h), initial=0))),
        'complementarity_Linf': float(np.max(abs(multipliers[:ni]*g[active]), initial=0)),
        'active_Jacobian_rank': rank, 'active_Jacobian_shape': list(A.T.shape), 'condition_number': cond,
        'rank_deficient': rank < min(A.shape), 'multipliers_ineq': multipliers[:ni].tolist(),
        'multipliers_eq': multipliers[ni:].tolist(), 'local_optimum_certified': False, 'global_optimum_certified': False}


class View:
    """Declared dimensionless coordinates and constraint scales for diagnosis."""
    def __init__(self, problem, metric, stage, mode):
        self.p, self.metric, self.stage = problem, metric, stage
        self.hq = stage == 'STRICT_SOURCE_SEARCH' or mode == 'HARD_Q_SOFT_RH'
        self.hr = stage == 'STRICT_SOURCE_SEARCH' or mode == 'HARD_RH_SOFT_Q'
        self.D = np.r_[np.full(problem.k, 2.), np.full(problem.n, problem.qscale*1000)]
        self.bounds = np.asarray(problem.base.bounds, float)
        self.constraints = problem.constraints(self.hq, self.hr)
        eqscales = []
        if problem.target.semantics.temperature_operator == 'TIME_MEAN_TAS' and np.any(problem.wT[problem.free] > 0):
            eqscales.append(2.)
        if self.hq:
            eqscales.append(problem.qscale*1000)
        if self.hr:
            eqscales.append(.05)
        self.scales = []
        ieq, iineq = 0, 0
        for c in self.constraints:
            if c['type'] == 'eq':
                self.scales.append(eqscales[ieq]); ieq += 1
            else:
                self.scales.append(problem.qscale*1000 if iineq == 0 else problem.base.slope); iineq += 1

    def objective(self, x):
        return self.p.shape(x) if self.stage == 'STRICT_SOURCE_SEARCH' else self.p.objective(x, self.metric)

    def values(self, x):
        """Return [native inequalities, bounds, equalities] and y-Jacobian."""
        g, Ag, h, Ah = [], [], [], []
        for c, scale in zip(self.constraints, self.scales):
            value = np.atleast_1d(c['fun'](x))/scale
            jac = np.atleast_2d(c['jac'](x))*self.D/scale
            (g if c['type'] == 'ineq' else h).extend(value)
            (Ag if c['type'] == 'ineq' else Ah).extend(jac)
        n = len(x)
        g.extend((x-self.bounds[:, 0])/self.D)
        g.extend((self.bounds[:, 1]-x)/self.D)
        Ag.extend(np.eye(n)); Ag.extend(-np.eye(n))
        return np.asarray(g), np.asarray(Ag).reshape((-1, n)), np.asarray(h), np.asarray(Ah).reshape((-1, n))

    def phase(self, x):
        t, _ = self.p.base.unpack(x)
        return t < 273.15 if self.p.base.phase == 'WATER_ICE' else np.zeros_like(t, bool)

    def point(self, x, previous=None):
        t, q = self.p.base.unpack(x)
        residual, _ = self.p.diagnostics(x)
        shape = self.p.shape(x)[0]
        data = .5*float(residual@self.metric.precision@residual)
        g, _, h, _ = self.values(x)
        result = {'x_sha256': fingerprint(x.tolist()), 'objective_total': float(self.objective(x)[0]),
            'data_metric': data, 'shape_unweighted': shape, 'shape_weighted': self.p.policy.lambda_shape*shape,
            'delta_q_mean_gkg': float(residual[0]), 'delta_RH_mean_pp': float(residual[1]),
            'primal_violation_scaled': max(float(np.max(np.maximum(-g, 0), initial=0)), float(np.max(abs(h), initial=0))),
            'min_distance_to_freezing_K': float(np.min(abs(t-273.15))),
            'ice_nodes': int(self.phase(x).sum())}
        if previous is not None:
            pt, pq = self.p.base.unpack(previous)
            result.update(max_T_step_K=float(np.max(abs(t-pt))), max_q_step_gkg=float(np.max(abs(q-pq))*1000),
                max_dimensionless_step=float(np.max(abs((x-previous)/self.D))),
                phase_crossings=int(np.sum(self.phase(x) != self.phase(previous))))
        return result


def finite_differences(view, x, step):
    """Check derivatives inside the box and phase, not on the constraint manifold."""
    F, grad = view.objective(x)
    scale = max(1., abs(F))
    grad = np.asarray(grad)*view.D/scale
    g, Ag, h, Ah = view.values(x)
    value0, jac = np.r_[g, h], np.vstack([Ag, Ah])
    errors, jac_errors, unavailable = [], [], []
    stencils = Counter()
    phase0 = view.phase(x)
    for j in range(len(x)):
        choices = {}
        for sign in (-1, 1):
            y = x.copy(); y[j] += sign*step*view.D[j]
            if (np.all(y >= view.bounds[:, 0]) and np.all(y <= view.bounds[:, 1])
                    and np.array_equal(view.phase(y), phase0)):
                choices[sign] = y
        if not choices:
            unavailable.append(j)
            continue
        def evaluate(y):
            gg, _, hh, _ = view.values(y)
            return view.objective(y)[0]/scale, np.r_[gg, hh]
        if len(choices) == 2:
            fp, cp = evaluate(choices[1]); fm, cm = evaluate(choices[-1])
            numeric, cj = (fp-fm)/(2*step), (cp-cm)/(2*step)
            stencils['CENTRAL'] += 1
        else:
            sign, y = next(iter(choices.items())); fy, cy = evaluate(y)
            numeric, cj = (fy-F/scale)/(sign*step), (cy-value0)/(sign*step)
            stencils['ONE_SIDED_SAME_BRANCH'] += 1
        errors.append(abs(numeric-grad[j])/max(1., abs(numeric), abs(grad[j])))
        jac_errors.extend(abs(cj-jac[:, j])/np.maximum(1., np.maximum(abs(cj), abs(jac[:, j]))))
    return {'dimensionless_step': step, 'objective_max_relative_error': max(errors, default=None),
        'constraint_Jacobian_max_relative_error': max(jac_errors, default=None),
        'stencils': dict(stencils), 'unavailable_columns': unavailable,
        'acceptance_threshold_established': False, 'phase_crossing_stencils_used': False}


def diagnose_day(donor_T, donor_q, target, pressure, *, donor_date, mode='BOTH_SOFT',
                 pressure_alignment='TARGET_DAY_EXTERNAL_FIXED', strict_witness=None,
                 q_weights=None, RH_weights=None, T_weights=None, metric=None, budget=None, policy=None):
    """Return unchanged frozen output plus per-start/per-iterate diagnostics."""
    kwargs = dict(donor_date=donor_date, mode=mode, pressure_alignment=pressure_alignment,
        strict_witness=strict_witness, q_weights=q_weights, RH_weights=RH_weights, T_weights=T_weights,
        metric=metric, budget=budget, policy=policy)
    before = fingerprint({'T': list(donor_T), 'q': list(donor_q), 'target': target.to_dict(), 'p': pressure.metadata()})
    baseline = frozen.project_day(donor_T, donor_q, target, pressure, **kwargs)
    captures = []
    real_minimize = frozen.minimize
    def capture_minimize(fun, x0, *args, **kw):
        record = {'initial': np.array(x0, copy=True), 'iterates': []}
        old_callback = kw.get('callback')
        def callback(x):
            record['iterates'].append(np.array(x, copy=True))
            if old_callback is not None:
                return old_callback(x)
        result = real_minimize(fun, x0, *args, **(kw | {'callback': callback}))
        record['result'] = result
        captures.append(record)
        return result
    globals_copy = dict(frozen.project_day.__globals__, minimize=capture_minimize)
    observed = types.FunctionType(frozen.project_day.__code__, globals_copy, frozen.project_day.__name__,
                                  frozen.project_day.__defaults__, frozen.project_day.__closure__)
    observed.__kwdefaults__ = dict(frozen.project_day.__kwdefaults__)
    raw = observed(donor_T, donor_q, target, pressure, **kwargs)
    if raw != baseline:
        raise AssertionError('CD1_OBSERVATION_CHANGED_FROZEN_OUTPUT')
    if frozen.minimize is not real_minimize:
        raise AssertionError('CD1_FROZEN_MODULE_GLOBALS_CHANGED')
    if len(captures) != len(raw.get('optimizer_trials', [])):
        raise AssertionError('CD1_TRIAL_CAPTURE_CENSUS_MISMATCH')
    problem = frozen.ProjectionProblem(donor_T, donor_q, target, pressure, q_weights, RH_weights, T_weights, policy)
    metric = metric or frozen.ProjectionMetric()
    selected = raw.get('selected_optimizer_trial')
    selected_provenance = 'FROZEN_SELECTED_INDEX' if selected is not None else None
    if raw.get('method') == 'STRICT_SEARCH_WITNESS_PRESERVED':
        # The frozen strict search returns the first validated trial immediately.
        # Its old schema does not export a selected index, unlike the soft stage.
        selected = len(captures)-1
        selected_provenance = 'FROZEN_STRICT_SEARCH_EARLY_RETURN'
    records = []
    for i, (capture, old) in enumerate(zip(captures, raw.get('optimizer_trials', []))):
        sol, x = capture['result'], np.asarray(capture['result'].x)
        view = View(problem, metric, old['stage'], mode)
        F, gradient = view.objective(x)
        g, Ag, h, Ah = view.values(x)
        try:
            validation = problem.validate(x, view.hq, view.hr)
            reason = None
        except ValueError as error:
            validation, reason = None, str(error)
        history = []
        previous = None
        for iteration, point in enumerate([capture['initial']]+capture['iterates']):
            history.append({'iteration': iteration, **view.point(point, previous)})
            previous = point
        record = {'trial_index': i, 'selected': i == selected, 'stage': old['stage'],
            'solver_success': bool(sol.success), 'solver_status': int(sol.status), 'message': str(sol.message),
            'iterations': int(sol.nit), 'nfev': int(sol.nfev), 'njev': int(sol.njev),
            'SLSQP_QP_multipliers_without_bounds': np.asarray(getattr(sol, 'multipliers', [])).tolist(),
            'initial_x': capture['initial'].tolist(), 'final_x': x.tolist(), 'final': view.point(x),
            'physical_admissibility': 'VALIDATED' if validation else 'REJECTED', 'rejection_reason': reason,
            'independent_validation': validation, 'iteration_journal': history,
            'finite_differences': [finite_differences(view, x, step) for step in FD_STEPS],
            'first_order': [kkt_fit(np.asarray(gradient)*view.D/max(1., abs(F)), g, Ag, h, Ah, a) for a in ACTIVE],
            'phase_scope': 'WITHIN_DECLARED_BRANCH; SMOOTH_KKT_DOES_NOT_COVER_SWITCH_JUMP',
            'diagnostic_coordinate_scales': view.D.tolist(), 'objective_normalization': max(1., abs(F))}
        records.append(record)
    state = 'T_K' in raw
    category = ('NO_VALIDATED_CANDIDATE' if not state else 'EXACT_SOURCE_WITNESS_NO_OPTIMIZATION'
                if raw['status'] == 'EXACT_SOURCE_PRESERVED' and not captures else 'EXACT_SOURCE_WITH_OPTIMIZATION'
                if raw['status'] == 'EXACT_SOURCE_PRESERVED' else 'VALIDATED_CANDIDATE_SOLVER_SUCCESS'
                if raw.get('selected_solver_reported_success') else 'VALIDATED_CANDIDATE_SOLVER_NOT_SUCCESS')
    if selected is not None:
        assert 0 <= selected < len(records) and records[selected]['physical_admissibility'] == 'VALIDATED'
        tx, tq = problem.base.unpack(np.asarray(records[selected]['final_x']))
        assert tx.tolist() == raw['T_K'] and tq.tolist() == raw['q_kgkg']
        if selected_provenance == 'FROZEN_SELECTED_INDEX':
            assert records[selected]['solver_success'] == raw['selected_solver_reported_success']
    if fingerprint({'T': list(donor_T), 'q': list(donor_q), 'target': target.to_dict(), 'p': pressure.metadata()}) != before:
        raise AssertionError('CD1_INPUT_MUTATED')
    return {'schema_version': 'IGE_CD1_CONVERGENCE_DIAGNOSTICS_v1', 'frozen_result': raw,
        'diagnostic_category': category, 'selected_trial_index': selected,
        'selected_trial_provenance': selected_provenance, 'trials': records,
        'observed_unobserved_exactly_equal': True, 'frozen_function_code_reused': True,
        'module_globals_unchanged': True, 'inputs_unchanged': True,
        'local_optimum_certified': False, 'global_optimum_certified': False,
        'phase_jump_es_Pa': {'ice_left': float(saturation(np.nextafter(273.15, -np.inf), 'WATER_ICE')),
                            'water_at_threshold': float(saturation(273.15, 'WATER_ICE'))},
        'independent_accuracy': 'NOT_QUALIFIED', 'operational_ready': False}
