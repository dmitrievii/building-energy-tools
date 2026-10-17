"""P9.1H23 fast scientific contract checks on SYNTHETIC inputs only."""
import datetime as dt
import math
import unittest
from p9_1h23_physical_inversion_candidate import (
    State,evaluate,baselines,solar_altitude_degrees,MAX_COLD_POOL_CORRECTION_C,
    MODEL_ID,single_site_scores,
)
UTC=dt.timezone.utc

def template(**override):
    spec={"timestamp_utc":dt.datetime(2018,1,11,0,tzinfo=UTC),
          "latitude_deg":51.97,"longitude_deg":4.926,
          "cloud_cover_percent":0.,"wind_speed_10m_ms":0.,
          "terrain_cold_pool_index":1.,
          "independently_verified_snow_cover":None}
    spec.update(override)
    return State(**spec)

class P9H23MinimalPhysicalContract(unittest.TestCase):
    def test_solar_sanity_noon_midnight(self):
        noon=dt.datetime(2018,6,21,12,tzinfo=UTC)
        midnight=dt.datetime(2018,6,21,0,tzinfo=UTC)
        self.assertGreater(solar_altitude_degrees(noon,51.97,4.926),40)
        self.assertLess(solar_altitude_degrees(midnight,51.97,4.926),-3)

    def test_daytime_no_spurious_thermal_correction(self):
        x=evaluate(template(timestamp_utc=dt.datetime(2018,6,21,12,tzinfo=UTC)),5.)
        self.assertEqual(x.correction_c,0.)
        self.assertEqual(x.status,"DAYLIGHT_BACKOFF")

    def test_physical_sign_and_bound_even_with_snow(self):
        x=evaluate(template(independently_verified_snow_cover=True),0.)
        self.assertLessEqual(x.correction_c,0.)
        self.assertGreaterEqual(x.correction_c,-MAX_COLD_POOL_CORRECTION_C)
        self.assertEqual(x.id,MODEL_ID)

    def test_calmer_clearer_more_cooling(self):
        dry=evaluate(template(),1.)
        windy=evaluate(template(wind_speed_10m_ms=12.),1.)
        cloudy=evaluate(template(cloud_cover_percent=100.),1.)
        self.assertLess(dry.correction_c,windy.correction_c)
        self.assertLess(windy.correction_c,0.)
        self.assertEqual(cloudy.correction_c,0.)

    def test_flat_and_missing_dem_are_safely_unmodified(self):
        flat=evaluate(template(terrain_cold_pool_index=0.),10.)
        missing=evaluate(template(terrain_cold_pool_index=None),10.)
        self.assertEqual(flat.corrected_temperature_c,10.)
        self.assertEqual(missing.corrected_temperature_c,10.)
        self.assertEqual(missing.status,"MISSING_SOURCE_BACKOFF")

    def test_missing_era5_wind_or_cloud_backoff(self):
        for k in ("wind_speed_10m_ms","cloud_cover_percent"):
            self.assertEqual(evaluate(template(**{k:None}),3.).correction_c,0.)

    def test_terrain_monotonic_no_site_labelling(self):
        a=evaluate(template(terrain_cold_pool_index=.3),2.)
        b=evaluate(template(terrain_cold_pool_index=.6),2.)
        self.assertGreater(a.correction_c,b.correction_c)

    def test_source_units_fail_closed(self):
        for kw in ({"cloud_cover_percent":-1.},{"cloud_cover_percent":101.},
                   {"wind_speed_10m_ms":-1.},{"terrain_cold_pool_index":1.1},
                   {"wind_speed_10m_ms":float("nan")}):
            with self.assertRaisesRegex(ValueError,"FEATURE_UNITS"):
                evaluate(template(**kw),8.)

    def test_grid_lapse_sign_and_provider_separated(self):
        x=baselines(5.,550.,250.,9.)
        self.assertAlmostEqual(x["B1_native_grid_fixed_lapse_C"],6.95)
        self.assertEqual(x["B0_raw_ERA5_C"],5.)
        self.assertEqual(x["B2_provider_altitude_C"],9.)

    def test_utc_only_and_no_unqualified_2m_proxy(self):
        with self.assertRaisesRegex(ValueError,"UTC"):
            evaluate(template(timestamp_utc=dt.datetime(2018,1,11,0)),4.)
        # No actual 2 m observation series available here = no skill claim.
        self.assertEqual(single_site_scores({},{"H":{}})["H"]["reason"],"NO_PAIR")

if __name__=="__main__":
    unittest.main()
