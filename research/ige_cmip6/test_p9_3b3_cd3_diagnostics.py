"""Independent stencil oracles, error detection and profile set semantics."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from p9_3b3_c2_projection import ProjectionProblem, ProjectionMetric
from p9_3b3_cd1_diagnostics import View, finite_differences
from p9_3b3_cd3_diagnostics import three_point_weights, second_order_fd
from p9_3b3_cd3_stability import registered_starts, empirical_envelopes, audit_endpoint
from p9_3b3_cd3_run import guard, run
from test_p9_3b3_c2_projection import fixture


class PolynomialView:
    def __init__(self, bounds, D=None, phase=False, wrong_gradient=False, wrong_jacobian=False):
        self.bounds = np.array(bounds, float)
        self.D = np.ones(len(bounds)) if D is None else np.array(D, float)
        self.switch = phase
        self.wrong_gradient, self.wrong_jacobian = wrong_gradient, wrong_jacobian

    def objective(self, x):
        z = x-273.15 if self.switch else x
        F = float(np.sum(z*z+2*z))
        if self.switch and x[0] < 273.15:
            F += .01
        return F, (2*z+2)*(2 if self.wrong_gradient else 1)

    def values(self, x):
        g = np.r_[x-self.bounds[:, 0], self.bounds[:, 1]-x, np.sum(x*x)]
        J = np.vstack([np.eye(len(x)), -np.eye(len(x)), 2*x])*self.D
        if self.wrong_jacobian:
            J *= 2
        return g, J, np.empty(0), np.empty((0, len(x)))

    def phase(self, x):
        return x < 273.15 if self.switch else np.zeros(len(x), bool)


class StencilOracles(unittest.TestCase):
    def test_nonuniform_three_point_formula_exact_for_quadratics(self):
        for a, b in [(-.3, .8), (.2, .5), (-.3, -.7)]:
            wa, wb = three_point_weights(a, b)
            self.assertAlmostEqual(wa*a+wb*b, 1.)
            self.assertAlmostEqual(wa*a*a+wb*b*b, 0.)
            f = lambda t: 17+3*t+7*t*t
            self.assertAlmostEqual(wa*(f(a)-f(0))+wb*(f(b)-f(0)), 3.)

    def test_degenerate_stencils_are_rejected(self):
        for a, b in [(0, 1), (1, 0), (1, 1), (np.inf, 1)]:
            with self.assertRaises(ValueError):
                three_point_weights(a, b)

    def test_central_and_one_sided_scaled_derivatives(self):
        view = PolynomialView([[0, 1], [0, 4], [-1, 1]], [2, 8, .5])
        x = np.array([0., 4., .3])
        for h in (1e-5, 5e-6):
            r = second_order_fd(view, x, h)
            self.assertTrue(r['pass'])
            self.assertEqual(r['checked_columns'], 3)
            self.assertEqual(r['stencils']['ONE_SIDED_SECOND_ORDER_SAME_BRANCH'], 2)
            self.assertEqual(r['stencils']['CENTRAL_SECOND_ORDER'], 1)

    def test_one_sided_cubic_error_is_second_order(self):
        view = PolynomialView([[0, 1]])
        view.objective = lambda x: (float(x[0]**3+2*x[0]), np.array([3*x[0]**2+2]))
        a = second_order_fd(view, np.array([0.]), .001)['objective_max_relative_error']
        b = second_order_fd(view, np.array([0.]), .0005)['objective_max_relative_error']
        self.assertAlmostEqual(a/b, 4., delta=1e-5)

    def test_roundoff_in_unchanged_column_does_not_disable_all_columns(self):
        view = PolynomialView([[0, 1], [0, 1]])
        x = np.array([.3, np.nextafter(1., np.inf)])
        copy = x.copy()
        # Reproduce the old all-vector predicate failure independently.
        self.assertFalse(np.all(x <= view.bounds[:, 1]))
        for h in (1e-5, 5e-6):
            r = second_order_fd(view, x, h)
            self.assertTrue(r['pass'])
            self.assertEqual(r['recorded_base_roundoff_columns'], [1])
            self.assertEqual(r['unavailable_columns'], [])
        np.testing.assert_array_equal(x, copy)

    def test_material_bound_violation_is_not_excused_as_roundoff(self):
        view = PolynomialView([[0, 1], [0, 1]])
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_ROUNDOFF'):
            second_order_fd(view, np.array([.3, 1+1e-9]), 1e-5)

    def test_incorrect_objective_derivative_fails(self):
        r = second_order_fd(PolynomialView([[0, 1]], wrong_gradient=True), np.array([.2]), 1e-5)
        self.assertFalse(r['pass'])
        self.assertGreater(r['objective_max_relative_error'], .1)

    def test_incorrect_constraint_derivative_fails(self):
        r = second_order_fd(PolynomialView([[0, 1]], wrong_jacobian=True), np.array([.2]), 1e-5)
        self.assertFalse(r['pass'])
        self.assertGreater(r['constraint_Jacobian_max_relative_error'], .1)

    def test_switch_and_adjacent_floats_never_cross_branch(self):
        view = PolynomialView([[270, 276]], phase=True)
        for T in (np.nextafter(273.15, -np.inf), 273.15, np.nextafter(273.15, np.inf)):
            r = second_order_fd(view, np.array([T]), 1e-5)
            self.assertTrue(r['pass'])
            self.assertFalse(r['phase_crossing_stencils_used'])
            self.assertEqual(r['stencils']['ONE_SIDED_SECOND_ORDER_SAME_BRANCH'], 1)

    def test_unavailable_singleton_is_explicit_failure(self):
        r = second_order_fd(PolynomialView([[.2, .2]]), np.array([.2]), 1e-5)
        self.assertFalse(r['pass'])
        self.assertEqual(len(r['unavailable_columns']), 1)


class PhysicalAndProfileOracles(unittest.TestCase):
    def problem(self):
        T, q, target, p = fixture(24, phase='WATER_ICE')
        return ProjectionProblem(T, q, target, p)

    def test_original_physical_derivatives_all_columns(self):
        p = self.problem()
        view = View(p, ProjectionMetric(), 'SOFT_SOURCE_PROJECTION', 'BOTH_SOFT')
        for x in p.starts():
            for h in (1e-5, 5e-6):
                r = second_order_fd(view, x, h)
                self.assertTrue(r['pass'])
                self.assertEqual(r['checked_columns'], p.k+p.n)

    def test_new_starts_reproducible_and_physically_admissible(self):
        p = self.problem()
        a, b = registered_starts(p, 'case-a'), registered_starts(p, 'case-a')
        self.assertEqual(len(a), 12)
        for r, s in zip(a, b):
            np.testing.assert_array_equal(r['x'], s['x'])
            p.validate(r['x'])
        c = registered_starts(p, 'case-b')
        self.assertFalse(np.array_equal(a[9]['x'], c[9]['x']))
        for i, original in enumerate(p.starts()):
            np.testing.assert_array_equal(a[i]['x'], original)

    def test_mean_temperature_cohort_requires_separate_start_design(self):
        T, q, target, pressure = fixture(4, mean=True)
        with self.assertRaisesRegex(ValueError, 'MIDRANGE'):
            registered_starts(ProjectionProblem(T, q, target, pressure), 'not-registered')

    def test_empirical_sets_use_F_gaps_and_keep_unsuccessful_validated_states(self):
        p = self.problem()
        x = p.starts()[0]
        T, q = p.base.unpack(x)
        q2 = q.copy(); q2[0] *= .9
        y = p.base.pack(T, q2)
        points = [{'id': 'a', 'final_x': x, 'F_original': 2., 'solver_success': True},
                  {'id': 'b', 'final_x': y, 'F_original': 2.+1e-9, 'solver_success': False}]
        r = empirical_envelopes(p, points, (1e-10, 1e-8))
        self.assertEqual([s['endpoint_count'] for s in r['sets']], [1, 2])
        self.assertAlmostEqual(r['sets'][1]['q_gkg']['max_pair_difference'], q[0]*100)
        self.assertEqual(r['sets'][1]['T_K']['max_pair_difference'], 0.)
        self.assertAlmostEqual(r['sets'][1]['q_gkg']['max_pair_RMS'], r['sets'][1]['q_gkg']['max_pair_difference']/np.sqrt(24), places=14)
        self.assertFalse(r['global_optimum_certified'])
        self.assertEqual(r['independent_accuracy'], 'NOT_QUALIFIED')

    def test_diagnostic_failure_does_not_change_physical_admissibility(self):
        p = self.problem()
        view = View(p, ProjectionMetric(), 'SOFT_SOURCE_PROJECTION', 'BOTH_SOFT')
        with patch('p9_3b3_cd3_stability.second_order_fd', side_effect=ValueError('synthetic FD failure')):
            r = audit_endpoint(view, p.starts()[0])
        self.assertEqual(r['physical_admissibility'], 'VALIDATED')
        self.assertIn('synthetic FD failure', r['diagnostic_error'])
        self.assertTrue(all(not f['pass'] for f in r['finite_differences']))

    def test_registered_controls_and_settings(self):
        self.assertEqual(len(guard()['protected_control_sha256']), 154)

    def test_existing_output_directory_is_never_reused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileExistsError):
                run(d)


if __name__ == '__main__':
    unittest.main()
