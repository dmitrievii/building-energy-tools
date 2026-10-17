"""P9.1D physical geometry and no-false-native-grid claims."""
import unittest
import numpy as np
import p9_1d_native_orography_dem as p

class NativeOroContract(unittest.TestCase):
    def test_geopotential_m2_s2_contract(self):
        self.assertTrue(p.is_geopotential_unit("m**2 s**-2"))
        self.assertFalse(p.is_geopotential_unit("m"))
        self.assertFalse(p.is_geopotential_unit("K"))

    def test_N320_not_regular_0p25_grid(self):
        self.assertIn("/co/single-level-reanalysis.zarr-v2",p.NATIVE)
        self.assertNotIn("/ar/",p.NATIVE)

    def test_true_haversine_nearest_wraparound(self):
        n=542080
        lats=np.full(n,10.,dtype=float)
        lons=np.full(n,10.,dtype=float)
        lats[10]=47.0;lons[10]=359.8
        i,lat,lon,km=p.nearest_n320(lats,lons,47.0,-.2)
        self.assertEqual(i,10)
        self.assertAlmostEqual(lon,-.2)
        self.assertAlmostEqual(km,0,places=5)

    def test_not_grid_if_3_coordinate_values(self):
        with self.assertRaisesRegex(ValueError,"NOT_NATIVE_N320"):
            p.nearest_n320([47,48,49],[15,16,17],47,15)

    def test_native_no_latitude_out_of_bounds(self):
        n=542080
        a=np.zeros(n);b=np.zeros(n);a[30]=100.
        with self.assertRaisesRegex(ValueError,"INVALID_NATIVE_COORDS"):
            p.nearest_n320(a,b,47,15)

    def test_geoaltitude_geopotential_constant_not_gravity_profile(self):
        self.assertAlmostEqual(9806.65/p.G0,1000.,places=5)

if __name__=="__main__":unittest.main()
