"""Analytic first-order oracles and frozen-path observation invariants."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import OptimizeResult

import p9_3b3_c2_projection as frozen
from p9_3b3_cd1_diagnostics import kkt_fit, finite_differences, diagnose_day, View
from p9_3b3_cd1_run import guard, load_inputs, run, write_new
from test_p9_3b3_tpa_contracts import example_pressure, example_target


def fit(grad, g=(), Ag=(), h=(), Ah=()):
    return kkt_fit(grad, g, Ag, h, Ah, 1e-6)


class FirstOrderOracles(unittest.TestCase):
    def test_interior_stationarity_does_not_certify_a_minimum(self):
        # grad(x^3)=0 at zero, but it is not a minimum.
        r = fit([0.])
        self.assertEqual(r['stationarity_Linf'], 0.)
        self.assertFalse(r['local_optimum_certified'])
        self.assertFalse(r['global_optimum_certified'])

    def test_lower_bound_multiplier_sign(self):
        r = fit([2.], [0.], [[1.]])
        self.assertLess(r['stationarity_Linf'], 1e-12)
        self.assertAlmostEqual(r['multipliers_ineq'][0], 2.)

    def test_upper_bound_multiplier_sign(self):
        r = fit([-2.], [0.], [[-1.]])
        self.assertLess(r['stationarity_Linf'], 1e-12)
        self.assertAlmostEqual(r['multipliers_ineq'][0], 2.)

    def test_inactive_bound_cannot_cancel_nonzero_gradient(self):
        r = fit([4.], [1.], [[1.]])
        self.assertEqual(r['active_inequalities'], 0)
        self.assertEqual(r['stationarity_Linf'], 4.)

    def test_equality_multiplier_is_free(self):
        r = fit([1., 1.], h=[0.], Ah=[[1., 1.]])
        self.assertLess(r['stationarity_Linf'], 1e-12)
        self.assertAlmostEqual(r['multipliers_eq'][0], -1.)

    def test_primal_failure_not_hidden_by_fitted_multipliers(self):
        r = fit([1.], [-.25], [[1.]], [.1], [[1.]])
        self.assertEqual(r['primal_violation_scaled'], .25)

    def test_dependent_active_rows_report_rank_deficiency(self):
        r = fit([1., 0.], [0., 0.], [[1., 0.], [2., 0.]])
        self.assertTrue(r['rank_deficient'])
        self.assertEqual(r['active_Jacobian_rank'], 1)


class PolynomialView:
    D = np.array([1., 1.])
    bounds = np.array([[-10., 10.], [0., 10.]])
    wrong_gradient = False
    def phase(self, x):
        return np.array([False, False])
    def objective(self, x):
        return float(np.sum((x-[1., 2.])**2)), np.zeros(2) if self.wrong_gradient else 2*(x-[1., 2.])
    def values(self, x):
        return np.array([x[0]+3]), np.array([[1., 0.]]), np.array([x.sum()-1]), np.array([[1., 1.]])


class FiniteDifferenceOracles(unittest.TestCase):
    def test_actual_water_ice_gradient_on_warm_and_cold_branches(self):
        for minimum in (258., 278.):
            p = example_pressure(T=np.linspace(minimum, minimum+2, 24))
            t = example_target(p, RH_mean_pct=20.)
            problem = frozen.ProjectionProblem(p.prior_T_K, p.prior_q_kgkg, t.legacy_target(), p.comparison_reference())
            view = View(problem, frozen.ProjectionMetric(), 'SOFT_SOURCE_PROJECTION', 'BOTH_SOFT')
            result = finite_differences(view, problem.starts()[0], 5e-6)
            self.assertLess(result['objective_max_relative_error'], 1e-5)
            self.assertLess(result['constraint_Jacobian_max_relative_error'], 1e-5)

    def test_actual_freezing_nodes_use_one_sided_water_branch(self):
        p = example_pressure(T=[272.]+[273.15]*22+[274.])
        t = example_target(p, RH_mean_pct=20.)
        problem = frozen.ProjectionProblem(p.prior_T_K, p.prior_q_kgkg, t.legacy_target(), p.comparison_reference())
        view = View(problem, frozen.ProjectionMetric(), 'SOFT_SOURCE_PROJECTION', 'BOTH_SOFT')
        result = finite_differences(view, problem.starts()[0], 5e-6)
        self.assertEqual(result['stencils']['ONE_SIDED_SAME_BRANCH'], 22)
        self.assertFalse(result['phase_crossing_stencils_used'])
        self.assertLess(result['objective_max_relative_error'], 1e-5)

    def test_correct_gradient_and_affine_constraint_jacobian(self):
        r = finite_differences(PolynomialView(), np.array([0., 1.]), 1e-5)
        self.assertLess(r['objective_max_relative_error'], 1e-8)
        self.assertLess(r['constraint_Jacobian_max_relative_error'], 1e-8)
        self.assertEqual(r['stencils'], {'CENTRAL': 2})

    def test_bound_uses_same_domain_one_sided_difference(self):
        r = finite_differences(PolynomialView(), np.array([0., 0.]), 1e-5)
        self.assertEqual(r['stencils']['ONE_SIDED_SAME_BRANCH'], 1)
        self.assertLess(r['objective_max_relative_error'], 1e-5)

    def test_wrong_gradient_is_detected(self):
        v = PolynomialView(); v.wrong_gradient = True
        self.assertGreater(finite_differences(v, np.array([0., 1.]), 1e-5)['objective_max_relative_error'], .5)

    def test_unavailable_same_branch_stencil_is_explicit(self):
        class PhaseView(PolynomialView):
            bounds = np.array([[-1., 0.], [0., 10.]])
            def phase(self, x):
                return x < 0
        r = finite_differences(PhaseView(), np.array([0., 1.]), 1e-5)
        self.assertEqual(r['unavailable_columns'], [0])
        self.assertFalse(r['phase_crossing_stencils_used'])


class FrozenObserver(unittest.TestCase):
    def test_existing_selected_fields_and_corrected_baseline_count(self):
        protocol = guard()
        self.assertEqual(len(protocol['protected_control_sha256']), 130)
        inputs, baseline = load_inputs(protocol)
        modified = [r for (_, m), r in baseline.items() if m == 'C2_BOTH_SOFT_STRICT_FIRST'
                    and r['status'] == 'LOCAL_PHYSICAL_PROJECTION_RESEARCH_ONLY']
        self.assertEqual(len(inputs), 63)
        self.assertEqual(sum(not r['selected_solver_reported_success'] for r in modified), 8)
        self.assertTrue(all('selected_optimizer_trial' in r for r in modified))

    def test_strict_witness_path_does_not_call_optimizer(self):
        p = example_pressure()
        t = example_target(p)
        witness = dict(status='EXACT_DEFINED_OPERATORS', T_K=list(p.prior_T_K), p_Pa=list(p.values_Pa), q_kgkg=list(p.prior_q_kgkg))
        with patch.object(frozen, 'minimize') as spy:
            r = diagnose_day(p.prior_T_K, p.prior_q_kgkg, t.legacy_target(), p.comparison_reference(),
                              donor_date=p.source_date, strict_witness=witness)
            spy.assert_not_called()
        self.assertEqual(r['diagnostic_category'], 'EXACT_SOURCE_WITNESS_NO_OPTIMIZATION')
        self.assertEqual(r['trials'], [])
        self.assertTrue(r['observed_unobserved_exactly_equal'])

    def test_selected_failed_trial_is_identified_despite_other_successes(self):
        p = example_pressure(T=[280.]*24)
        t = example_target(p, RH_mean_pct=20.)
        calls = []
        def fake_minimize(fun, x0, **kwargs):
            i = len(calls)%3
            x = np.asarray(x0).copy()
            if i == 0:
                x[:] = np.asarray(p.prior_q_kgkg)*1000/3
            if kwargs.get('callback'):
                kwargs['callback'](x)
            calls.append(i)
            success = i != 0
            return OptimizeResult(x=x, success=success, status=0 if success else 9,
                nit=2 if success else 180, nfev=2, njev=2,
                message='Optimization terminated successfully' if success else 'Iteration limit reached',
                fun=fun(x)[0], jac=fun(x)[1], multipliers=np.empty(0))
        with patch.object(frozen, 'minimize', side_effect=fake_minimize) as spy:
            r = diagnose_day(p.prior_T_K, p.prior_q_kgkg, t.legacy_target(), p.comparison_reference(), donor_date=p.source_date)
            self.assertIs(frozen.minimize, spy)
        self.assertEqual(len(calls), 6)
        self.assertEqual(r['selected_trial_index'], 0)
        self.assertEqual(r['diagnostic_category'], 'VALIDATED_CANDIDATE_SOLVER_NOT_SUCCESS')
        self.assertTrue(r['trials'][0]['selected'])
        self.assertEqual(r['trials'][0]['physical_admissibility'], 'VALIDATED')
        self.assertTrue(r['trials'][1]['solver_success'])
        self.assertEqual(r['trials'][0]['iteration_journal'][-1]['x_sha256'], r['trials'][0]['final']['x_sha256'])
        self.assertFalse(r['local_optimum_certified'])

    def test_real_SLSQP_observation_leaves_frozen_output_exact(self):
        p = example_pressure(T=[280.]*24)
        t = example_target(p, RH_mean_pct=20.)
        original = frozen.minimize
        r = diagnose_day(p.prior_T_K, p.prior_q_kgkg, t.legacy_target(), p.comparison_reference(), donor_date=p.source_date)
        self.assertIs(frozen.minimize, original)
        self.assertTrue(r['observed_unobserved_exactly_equal'])
        self.assertEqual(len(r['trials']), 3)
        self.assertTrue(all(len(x['iteration_journal']) > 1 for x in r['trials']))
        self.assertEqual(r['frozen_result']['correction_budget']['interpretation'], 'NOT_ESTABLISHED')

    def test_strict_search_witness_is_not_mislabeled_as_no_optimization(self):
        p = example_pressure()
        t = example_target(p)
        problem = frozen.ProjectionProblem(p.prior_T_K, p.prior_q_kgkg, t.legacy_target(), p.comparison_reference())
        witness = problem.base.pack(np.asarray(p.prior_T_K), np.asarray(p.prior_q_kgkg))
        start = problem.base.pack(np.asarray(p.prior_T_K), .5*np.asarray(p.prior_q_kgkg))
        def fake_minimize(fun, x0, **kwargs):
            if kwargs.get('callback'):
                kwargs['callback'](witness)
            return OptimizeResult(x=witness.copy(), success=False, status=9, nit=180, nfev=2, njev=2,
                message='Iteration limit reached', multipliers=np.empty(0))
        with patch.object(frozen.ProjectionProblem, 'starts', return_value=[start]*3), \
             patch.object(frozen, 'fixed_profile_feasibility', return_value={'status': 'UNRESOLVED'}), \
             patch.object(frozen, 'minimize', side_effect=fake_minimize):
            r = diagnose_day(p.prior_T_K, p.prior_q_kgkg, t.legacy_target(), p.comparison_reference(), donor_date=p.source_date)
        self.assertEqual(r['diagnostic_category'], 'EXACT_SOURCE_WITH_OPTIMIZATION')
        self.assertEqual(r['selected_trial_index'], 0)
        self.assertEqual(r['selected_trial_provenance'], 'FROZEN_STRICT_SEARCH_EARLY_RETURN')
        self.assertFalse(r['trials'][0]['solver_success'])
        self.assertTrue(r['trials'][0]['selected'])
        self.assertNotIn('selected_optimizer_trial', r['frozen_result'])
        self.assertTrue(r['observed_unobserved_exactly_equal'])

    def test_diagnostic_bounds_scales_and_jacobian_dimensions(self):
        p = example_pressure()
        t = example_target(p)
        problem = frozen.ProjectionProblem(p.prior_T_K, p.prior_q_kgkg, t.legacy_target(), p.comparison_reference())
        v = View(problem, frozen.ProjectionMetric(), 'SOFT_SOURCE_PROJECTION', 'BOTH_SOFT')
        x = problem.starts()[0]
        g, Ag, h, Ah = v.values(x)
        self.assertEqual(Ag.shape, (len(g), len(x)))
        self.assertEqual(Ah.shape, (len(h), len(x)))
        np.testing.assert_allclose(Ag[-2*len(x):-len(x)], np.eye(len(x)))
        np.testing.assert_allclose(Ag[-len(x):], -np.eye(len(x)))

    def test_outputs_never_overwrite_previous_results(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'record.json'
            write_new(p, {'original': True})
            with self.assertRaises(FileExistsError):
                write_new(p, {'original': False})
            with self.assertRaises(FileExistsError):
                run(folder)


if __name__ == '__main__':
    unittest.main()
