"""P9.1G original regional DWD + direct ERA5 vertical stability physical contracts."""
import datetime as dt
import io
import math
import unittest
import zipfile

import p9_1g_dwd_original_2019_observations as d
import p9_1g_era5_pressure_stability as p
import p9_1g_germany_dwd_stability_holdout as h


class P9GPhysicalAndSourceTests(unittest.TestCase):
    def test_01_new_4_independent_Germany_DWD_stations_fixed(self):
        self.assertEqual(d.STATION_IDS,(3987,4271,3730,2290))
        self.assertEqual(len(d.SEASONS),2)
        self.assertTrue(all(x[1].startswith("2019-") for x in d.SEASONS))

    def test_02_independent_DWD_QN_only_fully_checked(self):
        self.assertEqual(d.QC_FINAL,frozenset((10,)))
        self.assertNotIn(3,d.QC_FINAL)
        self.assertNotIn(0,d.QC_FINAL)

    def test_03_original_DWD_archive_filename_covering_2019(self):
        source=b'abc stundenwerte_TU_03987_18930101_20251231_hist.zip abc'
        for sid in d.STATION_IDS[1:]:
            source+=f' stundenwerte_TU_{sid:05d}_19510101_20251231_hist.zip'.encode()
        result=d.fixed_zip_filenames(source)
        self.assertEqual(len(result),4)
        self.assertTrue(result[3987].endswith("_hist.zip"))

    def test_04_archive_not_covering_2019_is_fatal(self):
        source=b' '.join(f'stundenwerte_TU_{sid:05d}_20200101_20251231_hist.zip'.encode()
                         for sid in d.STATION_IDS)
        with self.assertRaisesRegex(ValueError,"ARCHIVE_MISSING"):
            d.fixed_zip_filenames(source)

    def test_05_DWD_source_host_pinned_to_original_historical(self):
        with self.assertRaisesRegex(ValueError,"ONLY_ALLOWLISTED"):
            d.get_original("https://evil.example/temperatures.zip")

    def test_06_DWD_original_metadata_includes_real_station_altitude(self):
        meta=b'\n'.join(
            f'{sid:05d} 19500101 20251231 {200+sid%200} 48.1250 13.5000 '
            f'{d.LABELS[sid]} Bundesland'.encode()
            for sid in d.STATION_IDS)
        sites=d.parse_original_metadata(meta)
        self.assertEqual(len(sites),4)
        self.assertGreater(sites[3987]["altitude_m"],200)

    def test_07_true_original_DWD_CSV_QC10_and_missing_not_fabricated(self):
        txt="STATIONS_ID;MESS_DATUM;QN_9;TT_TU;RF_TU;eor\n"
        txt+="3987;2019011000;10;2.2;70;eor\n"
        txt+="3987;2019011001;3;3.1;70;eor\n"
        txt+="3987;2019011002;10;-999;70;eor\n"
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
            z.writestr("produkt_tu_stunde_03987_1950_2025.txt",txt)
        out=d.parse_original_zip(buf.getvalue(),3987)
        self.assertEqual(out["QC_accepted_original_source_hours"]["winter_2019"],1)
        self.assertEqual(out["original_QC_histograms"]["winter_2019"],{3:1,10:2})
        self.assertEqual(len(out["hourly_QC_accepted_TT_TU_for_scoring_PRIVATE"]["winter_2019"]),1)

    def test_08_pressure_K_and_m2s2_not_Celsius_no_passthrough(self):
        levels=[1000,975,950,925,900,875,850]
        t=[282,281,279,276,274,272,270]
        z=[0,200*9.80665,400*9.80665,600*9.80665,
           800*9.80665,1000*9.80665,1400*9.80665]
        out=p.pair_above_ground(levels,t,z,0.)
        self.assertEqual(out["status"],"TWO_VALID_ABOVE_REGULAR_ERA5_SURFACE_LEVELS")
        self.assertGreater(out["lower_height_above_model_ground_m"],50)
        self.assertEqual(out["lower_pressure_hpa"],975.)
        self.assertEqual(out["upper_pressure_hpa"],950.)
        self.assertTrue(out["below_surface_pressure_level_was_never_used"])

    def test_09_below_ground_levels_EXCLUDED_not_interpolated(self):
        levels=[1000,975,950,925,900,875,850]
        t=[282,281,279,276,274,272,270]
        z=[0,200*9.80665,400*9.80665,600*9.80665,
           800*9.80665,1000*9.80665,1400*9.80665]
        out=p.pair_above_ground(levels,t,z,750.)
        self.assertEqual(out["lower_pressure_hpa"],900.)
        self.assertEqual(out["upper_pressure_hpa"],875.)
        self.assertGreater(out["lower_height_above_model_ground_m"],49)

    def test_10_pressure_Kelvin_unit_Celsius_detected(self):
        with self.assertRaisesRegex(ValueError,"UNITS_OR_DOMAIN"):
            p.pair_above_ground([1000,950,900,850],[-5,-10,-12,-14],
                                [0,2000,3000,5000],0.)

    def test_11_only_surface_near_1_valid_above_ground_is_not_inversion(self):
        out=p.pair_above_ground(
            [1000,975,950,925],[280]*4,
            [0,1000,2000,3000],200.)
        self.assertNotEqual(out["status"],"TWO_VALID_ABOVE_REGULAR_ERA5_SURFACE_LEVELS")

    def test_12_physical_theta_gradient_K_per_km_in_ERA5_source(self):
        out=p.pair_above_ground([1000,975,950,925,900],
                                [282,280,278,276,274],
                                [0,1000,2500,4500,6000],0.)
        self.assertIn("theta_gradient_K_per_km",out)
        self.assertTrue(math.isfinite(out["theta_gradient_K_per_km"]))

    def test_13_guard_true_pressure_T_inversion_only_plus_weather_and_valley(self):
        prof={"status":"TWO_VALID_ABOVE_REGULAR_ERA5_SURFACE_LEVELS",
              "temperature_gradient_K_per_km":1.2,
              "theta_gradient_K_per_km":7.0}
        self.assertTrue(p.fixed_potential_temperature_stability_guard(
            True,0.,1.,30.,prof,"T_UPPER_WARM"))
        self.assertTrue(p.fixed_potential_temperature_stability_guard(
            True,0.,1.,30.,prof,"THETA_STABLE"))
        self.assertFalse(p.fixed_potential_temperature_stability_guard(
            False,0.,1.,30.,prof,"THETA_STABLE"))

    def test_14_stability_not_equal_real_inversion(self):
        prof={"status":"TWO_VALID_ABOVE_REGULAR_ERA5_SURFACE_LEVELS",
              "temperature_gradient_K_per_km":-2.,
              "theta_gradient_K_per_km":7.0}
        self.assertFalse(p.fixed_potential_temperature_stability_guard(
            True,0.,1.,20.,prof,"T_UPPER_WARM"))
        self.assertTrue(p.fixed_potential_temperature_stability_guard(
            True,0.,1.,20.,prof,"THETA_STABLE"))

    def test_15_pressure_pair_missing_never_triggers_guard(self):
        prof={"status":"INSUFFICIENT_ABOVE_GROUND_ERA5_PRESSURE_LEVELS"}
        self.assertFalse(p.fixed_potential_temperature_stability_guard(
            True,0.,1.,20.,prof,"THETA_STABLE"))

    def test_16_two_hourly_subsample_UTC_is_explicit_not_8760(self):
        self.assertEqual(p.PILOT_HOURS_UTC,(0,12))
        times=p.hours_for_season("2019-01-10","2019-01-16")
        self.assertEqual(len(times),14)
        self.assertEqual(times[0],"2019-01-10T00:00")
        self.assertEqual(times[-1],"2019-01-16T12:00")

    def test_17_same_original_DWD_observation_source_for_all_candidates(self):
        real={"2019-01-10T00:00":10.,"2019-01-10T12:00":12.}
        out=h.scores(real,{"2019-01-10T00:00":11.,
                           "2019-01-10T12:00":13.},list(real))
        self.assertEqual(out["n_qualified_original_DWD_QC10_hours"],2)
        self.assertAlmostEqual(out["MAE_C"],1.)

    def test_18_no_false_more_observations_than_original(self):
        self.assertIsNone(h.scores({},{"2019-01-10T00:00":11.},
                                   ["2019-01-10T00:00"],minimum=1))

    def test_19_German_DWD_long_archive_expected_original_product(self):
        self.assertTrue(d.ROOT.startswith("https://opendata.dwd.de/"))
        self.assertIn("/historical/",d.ROOT)
        self.assertNotIn("recent",d.ROOT)

if __name__=="__main__":
    unittest.main()
