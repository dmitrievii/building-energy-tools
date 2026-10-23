"""Hydrostatic analytic oracles and fixed-slot behavior at instrument heights."""
import dataclasses
import math
import unittest

import numpy as np
from scipy.integrate import quad

from p9_3b3_compare_vertical_frame import G0
from p9_3b3_nv2_columns import admission, predict_role, single_donor
from p9_3b3_reference_column import GASES
from test_p9_3b3_nv2_geometry import protocol, sensors
from test_p9_3b3_reference_column import TIME, column


def graz_columns():
    result = {}
    for i, (T, q, ps, ground) in enumerate(((270, .003, 97000, 372.5592962276722),
                                          (290, .009, 97300, 339.8640826446401))):
        c = column(T=T, q=q, ps=ps, ground=ground)
        donor = protocol()['AT_pressure_donors'][i]
        result[i+1] = dataclasses.replace(c, latitude=donor['latitude'], longitude=donor['longitude'])
    return result


class PressurePhysics(unittest.TestCase):
    def test_isothermal_independent_analytic_oracle_same_surface_anchor(self):
        c = column(T=280, q=.005, ground=100)
        s = sensors()['pressure']
        s.update(latitude=c.latitude, longitude=c.longitude)
        rd, coef = GASES[c.gas]
        for h in (100, 100.01, 150, 500, 1500):
            s['height_MSL_m'] = h
            r = single_donor(c, s, TIME)
            expected = 100000*math.exp(-G0*(h-100)/(rd*280*(1+coef*.005)))
            for m in ('P1_ISOTHERMAL', 'P2_NATIVE'):
                self.assertAlmostEqual(r[m]['pressure_Pa'], expected, delta=3e-8)
            self.assertEqual(len({v['anchor_phi_m2s2'] for v in r.values()}), 1)
            self.assertEqual(len({v['anchor_log_pressure'] for v in r.values()}), 1)

    def test_fixed_lapse_matches_independent_numerical_quadrature(self):
        c = column(T=280, q=.005, ground=100)
        s = {**sensors()['pressure'], 'height_MSL_m': 850}
        r = single_donor(c, s, TIME)['P1_LAPSE_0065']
        rd, coef = GASES[c.gas]
        integral = quad(lambda h: G0/(rd*(1+coef*.005)*(280+.0065*(850-h))), 100, 850,
                        epsabs=1e-13, epsrel=1e-13)[0]
        self.assertAlmostEqual(r['pressure_Pa'], 100000*math.exp(-integral), delta=3e-8)

    def test_stratified_native_profile_matches_independent_pressure_product(self):
        rng = np.random.default_rng(46021)
        for _ in range(12):
            T, q = rng.uniform(250, 300, 29), rng.uniform(.0001, .009, 29)
            c = column(T=T, q=q)
            h = rng.uniform(10, 900)
            s = {**sensors()['pressure'], 'height_MSL_m': h}
            r = single_donor(c, s, TIME)['P2_NATIVE']
            rd, coef = GASES[c.gas]
            p = 100000.
            phi = h*G0
            for j in reversed(range(29)):
                bottom, top = c.half_geopotential_m2s2[j+1], c.half_geopotential_m2s2[j]
                length = max(0., min(top, phi)-bottom)
                p *= math.exp(-length/(rd*T[j]*(1+coef*q[j])))
            self.assertAlmostEqual(r['pressure_Pa'], p, delta=4e-8)

    def test_graz_temperature_slot_D1_blocks_without_relabeling_D2(self):
        cs = graz_columns()
        r = predict_role(cs, {'D1': 1, 'D2': 2}, sensors()['temperature'], 'AT', TIME, protocol())
        self.assertFalse(r['admissions']['D1']['admitted'])
        self.assertTrue(r['admissions']['D2']['admitted'])
        self.assertNotIn('pressure_Pa', r['methods']['P2_NATIVE_D1'])
        self.assertIn('pressure_Pa', r['methods']['P2_NATIVE_D2'])
        self.assertEqual(r['methods']['P2_FIXED_D1_D2_BLEND']['status'], 'SOURCE_BLOCKED')
        self.assertFalse(r['direct_barometer_truth_at_this_role'])

    def test_missing_D2_never_turns_blend_into_single_or_changes_D1(self):
        cs = graz_columns()
        full = predict_role(cs, {'D1': 1, 'D2': 2}, sensors()['pressure'], 'AT', TIME, protocol())
        one = predict_role({1: cs[1]}, {'D1': 1, 'D2': 2}, sensors()['pressure'], 'AT', TIME, protocol())
        self.assertEqual(full['methods']['P2_NATIVE_D1'], one['methods']['P2_NATIVE_D1'])
        self.assertNotIn('pressure_Pa', one['methods']['P2_NATIVE_D2'])
        self.assertNotIn('pressure_Pa', one['methods']['P2_FIXED_D1_D2_BLEND'])

    def test_two_column_isothermal_blend_common_top_analytic_solution(self):
        cs = graz_columns()
        r = predict_role(cs, {'D1': 1, 'D2': 2}, sensors()['pressure'], 'AT', TIME, protocol())
        blend = r['methods']['P2_FIXED_D1_D2_BLEND']
        w = r['horizontal_support']['weights']
        top = min(c.domain[1] for c in cs.values())
        rd, coef = GASES[cs[1].gas]
        anchor = 0.
        for weight, c in zip(w, cs.values()):
            tv = c.temperature_K[0]*(1+coef*c.specific_humidity_kgkg[0])
            anchor += weight*(math.log(c.half_pressure_Pa[-1])-(top-c.domain[0])/(rd*tv))
        t = sum(weight*c.temperature_K[0] for weight, c in zip(w, cs.values()))
        q = sum(weight*c.specific_humidity_kgkg[0] for weight, c in zip(w, cs.values()))
        expected = math.exp(anchor+(top-G0*378.8)/(rd*t*(1+coef*q)))
        self.assertAlmostEqual(blend['pressure_Pa'], expected, delta=3e-8)
        self.assertEqual(len(blend['active_columns']), 2)
        self.assertFalse(blend['donor_spread_is_confidence_interval'])

    def test_profile_time_gas_top_and_radius_are_independent_blockers(self):
        c = graz_columns()[1]
        s = sensors()['pressure']
        for altered, sensor, reason in (
                (dataclasses.replace(c, timestamp_UTC='2021-02-01T01:00'), s, 'PROFILE_TIME_MISMATCH'),
                (dataclasses.replace(c, gas='ECMWF_PUBLISHED_APPROXIMATION'), s, 'GAS_FORMULATION_MISMATCH'),
                (c, {**s, 'height_MSL_m': c.domain[1]/G0+1}, 'TARGET_ABOVE_AVAILABLE_PROFILE_TOP'),
                (c, {**s, 'latitude': 40}, 'OUTSIDE_FIXED_RADIUS')):
            a = admission(altered, sensor, TIME, protocol())
            self.assertFalse(a['admitted'])
            self.assertIn(reason, a['reasons'])

    def test_lower_and_upper_boundaries_are_inclusive_no_extrapolation(self):
        c = graz_columns()[1]
        s = sensors()['pressure']
        for h in (c.domain[0]/G0, c.domain[1]/G0):
            a = admission(c, {**s, 'height_MSL_m': h}, TIME, protocol())
            self.assertTrue(a['admitted'])
        self.assertFalse(admission(c, {**s, 'height_MSL_m': c.domain[0]/G0-.01}, TIME, protocol())['admitted'])


if __name__ == '__main__':
    unittest.main()
