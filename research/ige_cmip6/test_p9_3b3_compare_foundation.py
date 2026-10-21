"""Independent forward states, analytic columns and adversarial source contracts."""
import dataclasses
import math
import unittest

import numpy as np
from scipy.integrate import quad

from p9_3b3_compare_identified_set import (MeanInterval, PressureBox, identified_bounds,
                                         saturation_envelope, summarize_scenarios)
from p9_3b3_compare_operators import DiscreteOperator, IntervalSupport, humidity_means
from p9_3b3_compare_pressure import hydrostatic_pressure, to_legacy_reference
from p9_3b3_compare_vertical_frame import (G0, PressureSeries, SourceBlocked,
                                         VerticalCoordinate, height_difference)
from p9_3b3_joint_bounds import joint_domain_bounds
from p9_3b3_thermodynamics import (MK, RD, RV, q_saturation, relative_humidity,
                                  saturation)


def coordinate(value=0., role="MSL_REFERENCE", **kwargs):
    return VerticalCoordinate(value, kwargs.pop("kind", "GEOMETRIC_M"),
        kwargs.pop("datum", "MSL_GEOID"), role, "INDEPENDENT_SYNTHETIC_FIXTURE", **kwargs)


def pressure(values=(101325.,), **kwargs):
    return PressureSeries(values, coordinate(verified=True), "2021-02-01",
                          "SYNTHETIC_NOT_OBSERVATIONS", "DECLARED_HOURLY_NODES", **kwargs)


def operators(n, q_weights=None, rh_weights=None, phase="WATER"):
    w = tuple([1/n]*n)
    common = dict(spatial_support="SYNTHETIC_POINT", evidence="FORWARD_ORACLE",
                  hypothesis="DECLARED_DISCRETE_EXPERIMENT_NOT_NASA_BOUNDS")
    return (DiscreteOperator("huss", "MEAN", tuple(q_weights) if q_weights is not None else w,
                             "kg/kg", **common),
            DiscreteOperator("hurs", "MEAN", tuple(rh_weights) if rh_weights is not None else w,
                             "%", phase=phase, **common))


def bounds(lo, hi, p, Q, R, *, upper_p=None, u=None, v=None, phase="WATER",
           q_interval=None, r_interval=None):
    n = len(lo)
    pbox = PressureBox(tuple(p), tuple(p if upper_p is None else upper_p),
        "DECLARED_SYNTHETIC_LEVEL", "FORWARD_ORACLE",
        "FIXED_CONDITIONAL_REFERENCE" if upper_p is None else "SENSITIVITY_BOX_NOT_CI")
    return identified_bounds(lo, hi, pbox,
        q_interval or MeanInterval(Q, Q, "kg/kg", "FORWARD_ORACLE"),
        r_interval or MeanInterval(R, R, "%", "FORWARD_ORACLE"),
        np.ones(n)/n if u is None else u, np.ones(n)/n if v is None else v,
        phase=phase)


class VerticalAndP1(unittest.TestCase):
    def test_isa_tabulation_and_zero_height(self):
        r = hydrostatic_pressure(pressure(), coordinate(1000, "BAROMETER", verified=True),
            [281.65], [0.], proxy_source="ISA_DRY_COLUMN", proxy_date="2021-02-01")
        self.assertAlmostEqual(r.pressure.values_Pa[0], 89874.56, delta=.2)
        z = hydrostatic_pressure(pressure(), coordinate(0, "BAROMETER", verified=True),
            [280.], [.005], proxy_source="SYNTHETIC", proxy_date="2021-02-01")
        self.assertEqual(z.pressure.values_Pa, pressure().values_Pa)

    def test_lapse_against_independently_integrated_column(self):
        # Integrate 1/Tv(z) directly, independently of the closed-form routine.
        for dz in (-120., 366., 1594.):
            for q in (0., .008):
                Tsite, lapse = 280., .0065
                integral = quad(lambda z: G0/(RD * (Tsite + lapse*(dz-z)) *
                                             (1+(RV/RD-1)*q)), 0, dz,
                                epsabs=1e-13)[0]
                r = hydrostatic_pressure(pressure(), coordinate(dz, "BAROMETER", verified=True),
                    [Tsite], [q], proxy_source="KNOWN_LINEAR_COLUMN", proxy_date="2021-02-01")
                self.assertAlmostEqual(r.pressure.values_Pa[0], 101325*math.exp(-integral), places=7)

    def test_isothermal_limit_and_humidity_sign(self):
        args = (pressure(), coordinate(1594, "BAROMETER", verified=True), [280.], [.01])
        kwargs = dict(proxy_source="SYNTHETIC", proxy_date="2021-02-01")
        iso = hydrostatic_pressure(*args, **kwargs, lapse_K_per_m=0)
        nearly = hydrostatic_pressure(*args, **kwargs, lapse_K_per_m=1e-10)
        self.assertAlmostEqual(iso.pressure.values_Pa[0], nearly.pressure.values_Pa[0], delta=1e-5)
        dry = hydrostatic_pressure(pressure(), args[1], [280.], [0.], **kwargs, lapse_K_per_m=0)
        self.assertGreater(iso.pressure.values_Pa[0], dry.pressure.values_Pa[0])
        self.assertFalse(iso.metadata()["pressure_model_qualified"])

    def test_ground_is_never_accepted_as_barometer(self):
        for role, verified in (("STATION_GROUND", True), ("BAROMETER", False)):
            with self.assertRaises(SourceBlocked):
                hydrostatic_pressure(pressure(), coordinate(36, role, verified=verified),
                    [280.], [.005], proxy_source="SYNTHETIC", proxy_date="2021-02-01")

    def test_unknown_datum_and_mixed_height_system_are_blocked(self):
        for target in (coordinate(36, "BAROMETER", datum="WGS84_ELLIPSOID", verified=True),
                       coordinate(36, "BAROMETER", kind="GEOPOTENTIAL_HEIGHT_M", verified=True)):
            with self.assertRaises(SourceBlocked):
                height_difference(pressure().coordinate, target)

    def test_geopotential_difference_has_explicit_units(self):
        a = coordinate(0, kind="GEOPOTENTIAL_M2_S2", verified=True)
        b = coordinate(1000*G0, "THERMO_SENSOR", kind="GEOPOTENTIAL_M2_S2", verified=True)
        self.assertAlmostEqual(height_difference(a, b), 1000.)

    def test_observed_anchor_wrong_date_and_hpa_are_rejected(self):
        target = coordinate(100, "BAROMETER", verified=True)
        with self.assertRaisesRegex(ValueError, "OBSERVED"):
            hydrostatic_pressure(pressure(usage="OBSERVED_VALIDATION_ONLY"), target,
                [280.], [.005], proxy_source="SYNTHETIC", proxy_date="2021-02-01")
        with self.assertRaisesRegex(ValueError, "DATE"):
            hydrostatic_pressure(pressure(), target, [280.], [.005],
                proxy_source="SYNTHETIC", proxy_date="2019-02-01")
        with self.assertRaisesRegex(ValueError, "UNITS"):
            pressure((1013.25,))

    def test_sensor_adapter_is_immutable_and_barometer_is_not_thermo_level(self):
        p = pressure()
        args = dict(proxy_source="SYNTHETIC", proxy_date="2021-02-01")
        r = hydrostatic_pressure(p, coordinate(368, "THERMO_SENSOR", verified=True), [280.], [.005], **args)
        legacy = to_legacy_reference(r)
        self.assertEqual(legacy.values_Pa, r.pressure.values_Pa)
        self.assertEqual(legacy.reference_date, p.reference_date)
        self.assertEqual(p.values_Pa, (101325.,))
        bar = hydrostatic_pressure(p, coordinate(366, "BAROMETER", verified=True), [280.], [.005], **args)
        with self.assertRaisesRegex(ValueError, "THERMODYNAMIC_SENSOR"):
            to_legacy_reference(bar)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.pressure.source = "CHANGED"


class ObservationOperators(unittest.TestCase):
    def test_midrange_never_imposes_time_mean(self):
        op = DiscreteOperator("tas", "MIDRANGE", (.25,)*4, "K", "POINT", "SOURCE_COMMENT",
            hypothesis="KNOWN_SYNTHETIC_WINDOW", independent_observation=False)
        self.assertEqual(op.evaluate([270., 270., 270., 290.]), 280.)
        self.assertNotEqual(op.evaluate([270., 270., 270., 290.]), 275.)
        with self.assertRaisesRegex(ValueError, "INDEPENDENT"):
            dataclasses.replace(op, independent_observation=True)

    def test_unknown_window_does_not_become_verified_from_weights(self):
        q, _ = operators(4)
        self.assertFalse(q.metadata()["interval_verified"])
        with self.assertRaisesRegex(ValueError, "HYPOTHESIS"):
            dataclasses.replace(q, hypothesis="")
        support = IntervalSupport(-3600, 0, "gregorian", "PROVIDER_PRECEDING_HOUR", "VERIFIED")
        verified = dataclasses.replace(q, interval=support, hypothesis="")
        self.assertTrue(verified.metadata()["interval_verified"])
        self.assertFalse(verified.metadata()["spatial_operator_identified"])

    def test_nonlinear_mean_and_different_windows(self):
        t, p, q = np.array([270., 290.]), np.array([97000., 98000.]), np.array([.001, .006])
        qo, ro = operators(2, [.25, .75], [.75, .25])
        out = humidity_means(t, p, q, qo, ro)
        r = relative_humidity(t, p, q)
        self.assertAlmostEqual(out["RH_mean_pp"], .75*r[0]+.25*r[1])
        collapsed = float(relative_humidity(t.mean(), p.mean(), q.mean()))
        self.assertGreater(abs(out["RH_mean_pp"]-collapsed), 1)
        self.assertTrue(out["mean_q_is_not_a_column_water_mass_balance"])

    def test_invalid_weights_phase_and_shapes_are_rejected(self):
        q, r = operators(2)
        for weights in ((-.1, 1.1), (.2, .2), (math.nan, 1)):
            with self.assertRaises(ValueError):
                dataclasses.replace(q, weights=weights)
        with self.assertRaises(ValueError):
            dataclasses.replace(r, phase="UNKNOWN")
        with self.assertRaisesRegex(ValueError, "UNITS"):
            dataclasses.replace(r, unit="K")
        with self.assertRaises(ValueError):
            humidity_means([280], [97000, 97000], [.005], q, r)


class IdentifiedSetBounds(unittest.TestCase):
    def test_240_forward_states_with_pressure_boxes_and_distinct_weights(self):
        rng = np.random.default_rng(20261021)
        for phase in ("WATER", "WATER_ICE"):
            for _ in range(120):
                n = 7
                lo = rng.uniform(250, 290, n)
                hi = lo + rng.uniform(0, 12, n)
                t = rng.uniform(lo, hi)
                pl = rng.uniform(79000, 101000, n)
                pu = pl + rng.uniform(0, 1000, n)
                p = rng.uniform(pl, pu)
                q = q_saturation(t, p) * rng.uniform(0, 1, n)
                u, v = rng.uniform(.1, 1, (2, n))
                u[0] = 0.; v[1] = 0.
                u /= u.sum(); v /= v.sum()
                # Existing independently tested thermodynamic primitives supply
                # the forward state; this never calls the inverse bound solver.
                Q, R = float(u @ q), float(v @ relative_humidity(t, p, q, phase))
                out = bounds(lo, hi, pl, Q, R, upper_p=pu, u=u, v=v, phase=phase)
                self.assertNotEqual(out["status"], "CERTIFIED_INFEASIBLE", out)
                self.assertLessEqual(out["RH_mean_lower_pp"], R+1e-7)
                self.assertGreaterEqual(out["RH_mean_upper_pp"], R-1e-7)
                self.assertFalse(out["source_feasibility_established"])

    def test_homogeneous_upper_has_independent_jensen_solution(self):
        T, P, Q = 280., 97000., .003
        out = bounds([T]*4, [T]*4, [P]*4, Q, 50)
        # For identical nodes Jensen gives max mean RH = RH(mean q).
        expected = float(relative_humidity(T, P, Q+1e-9))
        self.assertAlmostEqual(out["RH_mean_upper_pp"], expected, delta=2e-7)

    def test_two_node_exact_curve_is_contained(self):
        T, P = np.array([274., 287.]), np.array([96000., 99000.])
        Q = .003
        caps = q_saturation(T, P)
        q0 = np.linspace(max(0, 2*Q-caps[1]), min(caps[0], 2*Q), 2001)
        q1 = 2*Q-q0
        curve = (relative_humidity(T[0], P[0], q0)+relative_humidity(T[1], P[1], q1))/2
        out = bounds(T, T, P, Q, float(curve.mean()))
        self.assertLessEqual(out["RH_mean_lower_pp"], float(curve.min()))
        self.assertGreaterEqual(out["RH_mean_upper_pp"], float(curve.max()))

    def test_nominal_bounds_match_frozen_relaxation(self):
        for lo, hi, Q, R, phase in ((270., 280., .0015, 80., "WATER_ICE"),
                                   (278., 283., .0075, 50., "WATER")):
            old = joint_domain_bounds([lo]*24, [hi]*24, [97000.]*24, Q, R, phase)
            new = bounds([lo]*24, [hi]*24, [97000.]*24, Q, R, phase=phase)
            self.assertEqual(new["status"], old["status"])
            self.assertAlmostEqual(new["RH_mean_lower_pp"], old["RH_mean_lower_pp"], places=6)
            self.assertAlmostEqual(new["RH_mean_upper_pp"], old["RH_mean_upper_pp"], places=6)

    def test_interval_expansion_never_tightens_outer_bound(self):
        fixed = bounds([270.]*4, [280.]*4, [97000.]*4, .0015, 80., phase="WATER_ICE")
        wide = bounds([270.]*4, [280.]*4, [96500.]*4, .0015, 80., upper_p=[97500.]*4,
                      phase="WATER_ICE")
        self.assertLessEqual(wide["RH_mean_lower_pp"], fixed["RH_mean_lower_pp"])
        self.assertGreaterEqual(wide["RH_mean_upper_pp"], fixed["RH_mean_upper_pp"])
        qband = MeanInterval(.001, .002, "kg/kg", "DECLARED_SENSITIVITY", "SENSITIVITY_ONLY")
        wider = bounds([270.]*4, [280.]*4, [96500.]*4, .0015, 80., upper_p=[97500.]*4,
                       phase="WATER_ICE", q_interval=qband)
        self.assertLessEqual(wider["RH_mean_lower_pp"], wide["RH_mean_lower_pp"])
        self.assertGreaterEqual(wider["RH_mean_upper_pp"], wide["RH_mean_upper_pp"])

    def test_different_windows_include_unconstrained_q_nodes(self):
        T, P = [280., 280.], [97000., 97000.]
        cap = q_saturation(T, P)
        # q is measured on node 0, RH on node 1. Zero mean q does not imply
        # zero RH on an entirely different averaging window.
        out = bounds(T, T, P, 0., 100., u=[1., 0.], v=[0., 1.])
        self.assertNotEqual(out["status"], "CERTIFIED_INFEASIBLE")
        self.assertGreaterEqual(out["RH_mean_upper_pp"], 100.)
        self.assertEqual(out["RH_mean_lower_pp"], 0.)
        self.assertGreater(float(cap[1]), 0.)

    def test_freezing_envelope_contains_both_one_sided_values(self):
        lo, hi = np.array([273.149]), np.array([273.151])
        a, b = saturation_envelope(lo, hi, "WATER_ICE")
        vals = saturation(np.r_[np.linspace(lo[0], hi[0], 1001),
                                np.nextafter(273.15, -np.inf), 273.15], "WATER_ICE")
        self.assertLessEqual(a[0], vals.min())
        self.assertGreaterEqual(b[0], vals.max())

    def test_mass_capacity_and_interval_overlap_have_distinct_statuses(self):
        impossible = bounds([270.]*4, [275.]*4, [97000.]*4, .02, 80.)
        self.assertEqual(impossible["reason"], "Q_INTERVAL_ABOVE_DOMAIN_CAPACITY")
        rband = MeanInterval(0., 100., "%", "SENSITIVITY", "SENSITIVITY_ONLY")
        inconclusive = bounds([270.]*4, [280.]*4, [97000.]*4, .0015, 80., r_interval=rband)
        self.assertEqual(inconclusive["status"], "BOUND_INCONCLUSIVE")
        self.assertFalse(inconclusive["probability_or_confidence_interval"])
        summary = summarize_scenarios([impossible, inconclusive])
        self.assertEqual(summary["status"], "SOME_DECLARED_SCENARIOS_NOT_EXCLUDED")
        self.assertFalse(summary["source_feasibility_established"])

    def test_invalid_intervals_weights_and_pressure_units_are_rejected(self):
        for lo, hi in ((.01, .001), (math.nan, .01), (-.01, .01)):
            with self.assertRaises(ValueError):
                MeanInterval(lo, hi, "kg/kg", "INPUT", "SENSITIVITY_ONLY")
        with self.assertRaises(ValueError):
            MeanInterval(.001, .002, "kg/kg", "NOT_EXACT")
        with self.assertRaises(ValueError):
            PressureBox((970.,), (980.,), "LEVEL", "WRONG_UNITS", "SENSITIVITY_BOX_NOT_CI")
        with self.assertRaises(ValueError):
            bounds([270.]*2, [280.]*2, [97000.]*2, .0015, 80., u=[-.1, 1.1])


if __name__ == "__main__":
    unittest.main()
