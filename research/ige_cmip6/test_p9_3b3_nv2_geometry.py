"""Independent geometry, role, permutation and horizontal-support checks."""
import copy
import json
import unittest

import numpy as np

from p9_3b3_compare_vertical_frame import G0
from p9_3b3_nv2_geometry import distances_km, fixed_weights, freeze_donors, horizontal_support, radius_census
from p9_3b3_nv2_run import PROTOCOL


def protocol():
    return json.loads(PROTOCOL.read_text())


def sensors():
    return {role: {'latitude': 47.0777777778, 'longitude': 15.4488888889,
                   'height_MSL_m': height, 'role': kind, 'source_sha256': 'a'*64}
            for role, height, kind in (('pressure', 378.8, 'BAROMETER'),
                                       ('temperature', 368.7, 'THERMO_SENSOR'),
                                       ('RH_water', 368.7, 'THERMO_SENSOR'))}


def graz_catalogue():
    p = protocol()
    points = [(r['latitude'], r['longitude']) for r in p['AT_pressure_donors']]
    phi = G0*np.array([372.5592962276722, 339.8640826446401])
    return radius_census([7, 12], points, {'first': phi, 'second': phi.copy()}, sensors(), p)


class TerrainGeometry(unittest.TestCase):
    def test_graz_A_is_barometer_only_B_supports_all_lower_boundaries(self):
        a, b = graz_catalogue()
        self.assertTrue(a['roles']['pressure']['lower_boundary_admitted'])
        self.assertFalse(a['roles']['temperature']['lower_boundary_admitted'])
        self.assertFalse(a['roles']['RH_water']['lower_boundary_admitted'])
        self.assertAlmostEqual(a['roles']['temperature']['target_minus_surface_m'], -3.859296227672189)
        self.assertTrue(all(b['roles'][role]['lower_boundary_admitted'] for role in sensors()))
        self.assertEqual(freeze_donors([b, a], 'AT', protocol()), {'D1': 7, 'D2': 12})

    def test_full_census_exports_more_than_five_with_rejection_reasons(self):
        xy = [(47.0+i*.01, 15.5) for i in range(12)]
        phi = G0*np.arange(300., 420., 10.)
        rows = radius_census(range(12), xy, {'first': phi, 'second': phi}, sensors(), protocol())
        self.assertEqual(len(rows), 12)
        self.assertEqual({r['native_index'] for r in rows}, set(range(12)))
        blocked = next(r for r in rows if r['native_index'] == 11)
        self.assertIn('TARGET_BELOW_NATIVE_SURFACE', blocked['roles']['pressure']['rejection_reasons'])

    def test_complete_numpy_source_geometry_round_trips_strict_JSON(self):
        rows = graz_catalogue()
        self.assertEqual(json.loads(json.dumps(rows, allow_nan=False)), rows)

    def test_census_permutation_and_DE_CH_ties_are_deterministic(self):
        rows = graz_catalogue()
        for country in ('DE', 'CH'):
            self.assertEqual(freeze_donors(rows, country, protocol()), {'D1': 7})
            self.assertEqual(freeze_donors(rows[::-1], country, protocol()), {'D1': 7})
        a, b = copy.deepcopy(rows)
        a['roles']['pressure']['distance_km'] = b['roles']['pressure']['distance_km']
        self.assertEqual(freeze_donors([b, a], 'DE', protocol()), {'D1': 7})

    def test_control_surface_drift_fails_before_selection(self):
        with self.assertRaisesRegex(ValueError, 'NOT_STATIONARY'):
            radius_census([1], [(47., 15.5)], {'a': [300*G0], 'b': [301*G0]}, sensors(), protocol())

    def test_empty_nonfinite_and_duplicate_index_contracts(self):
        for ids, points, phi in (([1, 1], [(47, 15), (47, 16)], [300, 300]),
                                  ([1], [(float('nan'), 15)], [300]),
                                  ([1], [(47, 15)], [float('nan')])):
            with self.assertRaises(ValueError):
                radius_census(ids, points, {'a': phi}, sensors(), protocol())
        self.assertEqual(freeze_donors([], 'AT', protocol()), {'D1': None, 'D2': None})
        self.assertEqual(freeze_donors([], 'CH', protocol()), {'D1': None})

    def test_distance_matches_quarter_circumference_and_dateline(self):
        s = {'latitude': 0., 'longitude': 0.}
        d = distances_km([0, 90], [90, 0], s)
        np.testing.assert_allclose(d, np.pi*6371.0088/2, rtol=0, atol=1e-9)
        self.assertLess(distances_km([0], [359.9], s)[0], 12)

    def test_radius_is_checked_for_each_separate_instrument(self):
        s = sensors()
        s['temperature']['latitude'] = 40.
        rows = radius_census([1], [(47.0, 15.5)], {'a': [300*G0]}, s, protocol())
        self.assertTrue(rows[0]['roles']['pressure']['lower_boundary_admitted'])
        self.assertIn('OUTSIDE_FIXED_RADIUS', rows[0]['roles']['temperature']['rejection_reasons'])


class HorizontalGeometry(unittest.TestCase):
    def test_Graz_first_moment_and_hull_reproduce_crosscheck(self):
        rows = graz_catalogue()
        r = horizontal_support([(a['latitude'], a['longitude']) for a in rows], sensors()['pressure'],
                               [a['roles']['pressure']['distance_km'] for a in rows])
        np.testing.assert_allclose(r['weights'], [.603491880035562, .3965081199644379], atol=1e-10, rtol=0)
        self.assertAlmostEqual(r['first_moment_norm_km'], 30.46006342144962*6371.0088/6371, places=7)
        self.assertFalse(r['target_in_nonnegative_weight_convex_hull'])
        self.assertFalse(r['full_2D_gradient_identifiable'])
        self.assertEqual(r['affine_design_rank'], 2)

    def test_symmetric_nodes_have_zero_moment_but_only_directional_gradient(self):
        s = {'latitude': 47., 'longitude': 15.}
        r = horizontal_support([(47., 14.9), (47., 15.1)], s, [10, 10])
        np.testing.assert_allclose(r['first_moment_east_north_km'], [0, 0], atol=1e-10)
        self.assertTrue(r['target_in_nonnegative_weight_convex_hull'])
        self.assertFalse(r['full_2D_gradient_identifiable'])

    def test_barycentric_support_and_distance_weight_validation(self):
        s = {'latitude': 47., 'longitude': 15.}
        r = horizontal_support([(46.9, 14.9), (46.9, 15.1), (47.2, 15.)], s, [10, 10, 10])
        self.assertTrue(r['target_in_nonnegative_weight_convex_hull'])
        self.assertEqual(r['affine_design_rank'], 3)
        np.testing.assert_array_equal(fixed_weights([0, 10]), [1, 0])
        for d in ([], [-1, 2], [float('nan')], [0, 0]):
            with self.assertRaises(ValueError):
                fixed_weights(d)


if __name__ == '__main__':
    unittest.main()
