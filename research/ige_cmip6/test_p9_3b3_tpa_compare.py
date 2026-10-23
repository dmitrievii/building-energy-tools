"""Analytic convex oracles and independent closure/ledger checks."""
from dataclasses import asdict, replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from p9_3b3_thermodynamics import saturation, q_from_e, q_saturation, relative_humidity
from p9_3b3_tpa_compare import project_q, compare, strict_joint, package, METHODS
from test_p9_3b3_tpa_contracts import example_pressure, example_target


class ConvexProjectionOracles(unittest.TestCase):
    def test_unequal_weights_use_lambda_times_weight(self):
        r = project_q([0., 0.], [1., 1.], .5, [.25, .75])
        np.testing.assert_allclose(r['q_kgkg'], [.2, .6], atol=1e-13)
        self.assertAlmostEqual(r['multiplier'], .8)
        # Constant shift [.5,.5] satisfies the mean but has larger distance.
        self.assertLess(r['objective'], .25)

    def test_active_cap_has_exact_analytic_solution(self):
        r = project_q([0., 0.], [.1, 1.], .5, [.5, .5])
        np.testing.assert_allclose(r['q_kgkg'], [.1, .9], atol=1e-13)
        self.assertAlmostEqual(r['mean_residual_kgkg'], 0.)

    def test_zero_support_retains_clipped_nearest_prior(self):
        r = project_q([.7, -.2, .3], [.5, 1., 1.], .6, [0., 0., 1.])
        np.testing.assert_allclose(r['q_kgkg'], [.5, 0., .6], atol=1e-13)

    def test_capacity_endpoints_and_scoped_certificate(self):
        for target, expected in ((0., [0., .4]), (.25, [.25, .4])):
            r = project_q([.2, .4], [.25, .5], target, [1., 0.])
            self.assertEqual(r['status'], 'FEASIBLE')
            np.testing.assert_allclose(r['q_kgkg'], expected)
        r = project_q([.2, .4], [.25, .5], .3, [1., 0.])
        self.assertEqual(r['status'], 'CERTIFIED_INFEASIBLE')
        self.assertIn('NOT_JOINT_T_DOMAIN', r['scope'])

    def test_projection_satisfies_variational_optimality_on_feasible_line(self):
        prior = np.array([-.1, .4])
        r = project_q(prior, [1., 1.], .5, [.2, .8])
        q = np.asarray(r['q_kgkg'])
        for a in np.linspace(0, 1, 31):
            other = np.array([a, (.5-.2*a)/.8])
            self.assertGreaterEqual(float((q-prior)@(other-q)), -1e-12)
        second = project_q(q, [1., 1.], .5, [.2, .8])
        np.testing.assert_allclose(second['q_kgkg'], q, atol=1e-13)

    def test_invalid_quadrature_or_nan_rejected(self):
        for prior, caps, weights in (([0.], [1.], [0.]), ([0.], [-1.], [1.]),
                                     ([float('nan')], [1.], [1.]), ([0., 0.], [1.], [.5, .5])):
            with self.assertRaises(ValueError):
                project_q(prior, caps, .1, weights)


class CommonClosureAndLedger(unittest.TestCase):
    def test_three_methods_share_inputs_fixed_p_and_strict_witness(self):
        p, t = example_pressure(), example_target()
        original = asdict(p), asdict(t)
        rows = compare(t, p)
        self.assertEqual([r['status'] for r in rows],
            ['EXACT_DEFINED_OPERATORS', 'Q_MEAN_EXACT_RH_DIAGNOSTIC', 'EXACT_SOURCE_PRESERVED'])
        self.assertEqual(len({r['source_constraints_sha256'] for r in rows}), 1)
        self.assertEqual(len({r['common_prior_sha256'] for r in rows}), 1)
        for r in rows:
            self.assertEqual(r['p_Pa'], list(p.values_Pa))
            self.assertEqual(len(r['journal_all_diagnostics']), 5)
            self.assertFalse(r['source_input_mutated'])
            self.assertEqual(r['quality']['independent_accuracy'], 'NOT_QUALIFIED')
            self.assertFalse(r['semantics']['fully_verified'])
        for field in ('T_K', 'p_Pa', 'q_kgkg'):
            self.assertEqual(rows[0][field], rows[2][field])
        np.testing.assert_allclose(rows[0]['q_kgkg'], p.prior_q_kgkg, atol=0, rtol=0)
        self.assertEqual(original, (asdict(p), asdict(t)))

    def test_derived_tas_does_not_impose_hourly_temperature_mean(self):
        p = example_pressure(T=[270.]+[271.]*22+[280.])
        t = example_target(p)
        rows = compare(t, p)
        for r in rows:
            self.assertNotAlmostEqual(r['shape_adjustments']['T_time_mean_K'], t.tas_K, places=1)
            self.assertFalse(r['shape_adjustments']['T_time_mean_is_hard_tas'])
            self.assertEqual(r['achieved_diagnostics']['tas'], 275.)

    def test_q_only_cert_does_not_exclude_a_joint_temperature_witness(self):
        # Same extrema, slightly warmer interior increases q capacity. This is
        # a constructed existence witness, not an inference from local failure.
        donor = np.array([270.]+[271.]*22+[280.])
        witness_T = donor.copy(); witness_T[1:23] += 1.5
        p = example_pressure(T=donor)
        cap0 = q_saturation(donor, p.values_Pa)
        q = .99*q_saturation(witness_T, p.values_Pa)
        Q = float(np.mean(q))
        R = float(np.mean(relative_humidity(witness_T, p.values_Pa, q, 'WATER_ICE')))
        t = example_target(p, q_mean_kgkg=Q, RH_mean_pct=R)
        self.assertGreater(Q, float(np.mean(cap0)))
        result = project_q(p.prior_q_kgkg, cap0, Q, t.q_weights)
        self.assertEqual(result['status'], 'CERTIFIED_INFEASIBLE')
        raw = {'status': 'EXACT_DEFINED_OPERATORS', 'T_K': witness_T.tolist(), 'q_kgkg': q.tolist(), 'p_Pa': list(p.values_Pa)}
        verified = package(raw, METHODS[0], t, p, p.prior_T_K, p.prior_q_kgkg)
        self.assertEqual(verified['quality']['physical_admissibility'], 'CONDITIONAL_DISCRETE_GAS_STATE_VALIDATED')

    def test_q_only_RH_diagnostic_and_C2_correction_are_explicit(self):
        p = example_pressure(T=[280.]*24)
        t = example_target(p, RH_mean_pct=20.)
        strict, qonly, c2 = compare(t, p)
        self.assertEqual(strict['status'], 'CERTIFIED_INFEASIBLE')
        self.assertTrue(qonly['source_diagnostics_changed'])
        j = next(j for j in qonly['journal_all_diagnostics'] if j['variable'] == 'hurs')
        self.assertEqual(j['constraint_role'], 'DIAGNOSTIC_NOT_ENFORCED')
        self.assertAlmostEqual(j['signed_delta'], 40., places=7)
        self.assertTrue(c2['source_diagnostics_changed'])
        self.assertEqual(c2['status'], 'LOCAL_PHYSICAL_PROJECTION_RESEARCH_ONLY')
        self.assertFalse(c2['global_optimality_certified'])
        self.assertEqual(c2['correction_budget']['interpretation'], 'NOT_ESTABLISHED')
        self.assertFalse(c2['production_eligible'])
        self.assertFalse(strict['source_diagnostics_changed'])
        self.assertTrue(all(j['achieved'] is None for j in strict['journal_all_diagnostics']))

    def test_cold_ice_RH_above_100_is_not_water_supersaturation(self):
        T, P = np.full(24, 260.), np.full(24, 95000.)
        q = q_from_e(1.05*saturation(T, 'WATER_ICE'), P, 287.05/461.5)
        p = example_pressure(T, P, q)
        t = example_target(p, RH_mean_pct=105.)
        rows = compare(t, p)
        self.assertEqual(rows[0]['status'], 'EXACT_DEFINED_OPERATORS')
        self.assertAlmostEqual(rows[0]['achieved_diagnostics']['hurs'], 105., places=7)
        self.assertLess(rows[0]['validation']['RH_water_max_pct'], 100.)

    def test_warm_daily_RH_101_is_not_a_physical_hourly_water_cap(self):
        T, P = np.full(24, 280.), np.full(24, 95000.)
        q = q_from_e(1.01*saturation(T, 'WATER_ICE'), P, 287.05/461.5)
        p = example_pressure(T, P, q)
        t = example_target(p, RH_mean_pct=101.)
        strict, qonly, c2 = compare(t, p)
        self.assertEqual(strict['status'], 'CERTIFIED_INFEASIBLE')
        self.assertEqual(qonly['status'], 'CERTIFIED_INFEASIBLE')
        self.assertLessEqual(c2['validation']['RH_water_max_pct'], 100.+1e-6)
        self.assertTrue(c2['source_diagnostics_changed'])

    def test_exact_freezing_branch_and_mean_of_RH_not_RH_of_means(self):
        T = np.array([263.15]*8+[273.15]*8+[283.15]*8)
        p = example_pressure(T=T)
        np.testing.assert_allclose(saturation([273.15], 'WATER_ICE'), saturation([273.15], 'WATER'), atol=0)
        source_mean = float(np.mean(relative_humidity(T, p.values_Pa, p.prior_q_kgkg, 'WATER_ICE')))
        rh_of_means = float(relative_humidity(np.mean(T), np.mean(p.values_Pa), np.mean(p.prior_q_kgkg), 'WATER_ICE'))
        self.assertAlmostEqual(source_mean, 60.)
        self.assertGreater(abs(rh_of_means-source_mean), 2.)

    def test_local_failure_has_no_infeasibility_claim(self):
        p = example_pressure()
        t = example_target(p, RH_mean_pct=61.)
        bad = SimpleNamespace(success=False, nit=1, message='FORCED_LOCAL_FAILURE', x=np.full(70, np.nan))
        # No supporting global bound and no validated start. Failed numerical
        # search remains UNRESOLVED instead of being recast as a certificate.
        with patch('p9_3b3_tpa_compare.fixed_profile_feasibility', return_value={'status': 'UNRESOLVED'}), \
             patch('p9_3b3_tpa_compare.identified_bounds', return_value={'status': 'BOUNDS_OVERLAP'}), \
             patch('p9_3b3_tpa_compare.minimize', return_value=bad):
            r = strict_joint(p.prior_T_K, p.prior_q_kgkg, t, p)
        self.assertEqual(r['status'], 'UNRESOLVED')
        self.assertEqual(r['scope'], 'NO_INFEASIBILITY_CLAIM')

    def test_source_day_sensitivity_cannot_be_hidden_by_target_date(self):
        p = example_pressure()
        with self.assertRaisesRegex(ValueError, 'TARGET_DATE_MISMATCH'):
            compare(replace(example_target(p), date='2013-01-08'), p)


if __name__ == '__main__':
    unittest.main()
