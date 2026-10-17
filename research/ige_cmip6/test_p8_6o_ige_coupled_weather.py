"""P8.6O original research IGE weather co-occurrence metric contracts."""
import unittest
import numpy as np
import p8_6o_ige_coupled_weather as c


class CoupledWeatherContracts(unittest.TestCase):
    def test_unchanged_P8_6N_hour_month_axis(self):
        self.assertEqual(len(c.MONTHS),8760)
        self.assertEqual(len(c.HOURS),8760)
        self.assertEqual(int(c.MONTHS[0]),1)
        self.assertEqual(int(c.MONTHS[-1]),12)
        self.assertEqual(int(c.HOURS[-1]),23)

    def test_atmospheric_solar_geometry_is_finite_and_bounded(self):
        x=c.solar_cos(47.0,15.0,1.0)
        self.assertEqual(len(x),8760)
        self.assertTrue(np.all(np.isfinite(x)))
        self.assertTrue(np.all((x>=-1)&(x<=1)))
        self.assertGreater(float(x.max()),.8)

    def test_same_month_same_hour_rain_dry_contrast(self):
        values=np.zeros(8760);wet=np.zeros(8760,dtype=bool)
        dry=np.ones(8760,dtype=bool)
        # Source hours are exactly same January 1 and January 2 local noon.
        i=12;j=24+12
        wet[i]=True;dry[i]=False
        values[i]=80.;values[j]=60.
        observed,n=c.monthly_hour_conditional(values,wet,dry,
                                             np.ones(8760,dtype=bool))
        self.assertEqual(n,1)
        self.assertEqual(observed,20.)

    def test_missing_values_do_not_count_as_clear_skies(self):
        values=np.full(8760,99.,dtype=float)
        cloud_valid=(values>=0)&(values<=10)
        self.assertEqual(int(cloud_valid.sum()),0)

    def test_no_rain_returns_no_invented_contrast(self):
        x=np.ones(8760)
        wet=np.zeros(8760,dtype=bool)
        contrast,n=c.monthly_hour_conditional(x,wet,~wet,
                                               np.ones(8760,dtype=bool))
        self.assertIsNone(contrast)
        self.assertEqual(n,0)

    def test_rain_only_uses_matched_calendar_hour_not_nighttime_mean(self):
        x=np.ones(8760)
        wet=np.zeros(8760,dtype=bool)
        i=18;wet[i]=True
        x[i]=10.
        # Artificial high mismatch other hours must not bias matched contrast.
        x[9]=10000.
        contrast,n=c.monthly_hour_conditional(x,wet,~wet,
                                              np.ones(8760,dtype=bool))
        self.assertAlmostEqual(contrast,9.)
        self.assertEqual(n,1)


if __name__=="__main__":
    unittest.main()
