"""P9.1E original regular-grid model-cell identity and independent holdout contracts."""
import unittest
import numpy as np
import p9_1e_regular_grid_orography as a
import p9_1e_2021_new_lowland_station_holdout as b

class TestRegularGridOrography(unittest.TestCase):
    def test_01_exact_regular_025_lat_center(self):
        lat=np.linspace(90,-90,721)
        self.assertEqual(a.regular_coordinate_index(lat,47.),172)

    def test_02_wrap_longitude_with_WGS84_negative(self):
        lon=np.arange(0,360,.25)
        self.assertEqual(a.regular_coordinate_index(lon,-.25,wrap=True),1439)

    def test_03_far_from_exact_grid_node_fails(self):
        lon=np.arange(0,360,.25)
        with self.assertRaisesRegex(ValueError,"NOT_EXACT_ARCO"):
            a.regular_coordinate_index(lon,15.13,wrap=True)

    def test_04_invalid_grid_step_fails(self):
        malformed=np.arange(721)*.20
        with self.assertRaisesRegex(ValueError,"NOT_NATIVE_025"):
            a.regular_coordinate_index(malformed,15.0)

    def test_05_preregistered_six_sites_not_previous_alpine(self):
        self.assertEqual(set(a.LOWLAND_TARGETS),{
            "Vienna","Linz","Salzburg","Klagenfurt","Bregenz","Eisenstadt"})
        self.assertEqual(len(a.GLOBAL_PROBES),5)
        self.assertNotIn(30,a.EXCLUDED_PREVIOUS_SITE_IDS ^ {30})

    def test_06_deterministic_metadata_only_site_selection_not_hourly_weather(self):
        stations=[
            {"id":50,"name":"Vienna A","lat":48.25,"lon":16.35,"altitude":200},
            {"id":52,"name":"Vienna B","lat":48.29,"lon":16.36,"altitude":210},
            {"id":30,"name":"Excluded","lat":48.249,"lon":16.356,"altitude":200}]
        result=a.select_new_stations({"stations":stations})
        self.assertEqual(result["Vienna"]["station_id"],50)
        self.assertEqual(result["Linz"]["status"],"NO_AUTHENTIC_NEARBY_STATION_25KM")

    def test_07_altitude_classification_is_not_station_qc_prediction(self):
        from inspect import signature
        self.assertEqual(set(signature(a.select_new_stations).parameters),{"meta"})

    def test_08_regular_lapse_and_native_lapse_have_correct_independent_sign(self):
        model,diag=b.fixed_predictions(
            [10.,20.],[12.,22.],600.,300.,500.)
        self.assertAlmostEqual(model["L1_NATIVE_N320_FIXED_LAPSE"][0],8.05)
        self.assertAlmostEqual(model["L2_REGULAR_025_FIXED_LAPSE"][0],9.35)
        self.assertEqual(model["L3_REGULAR_025_BOUNDED_3C"][0],
                         model["L2_REGULAR_025_FIXED_LAPSE"][0])
        self.assertFalse(diag["correction_parameters_chosen_after_target_observation"])

    def test_09_regular_correction_bounded_exactly_three(self):
        model,d=b.fixed_predictions([10],[11],3000.,500.,600.)
        self.assertAlmostEqual(d["bounded_regular_correction_C"],-3.)
        self.assertAlmostEqual(model["L3_REGULAR_025_BOUNDED_3C"][0],7.)

    def test_10_fails_on_nonfinite_geopotential(self):
        with self.assertRaisesRegex(ValueError,"NONFINITE_SITE"):
            b.fixed_predictions([10],[11],300.,float("nan"),350.)

    def test_11_rejects_different_weather_hour_count(self):
        with self.assertRaisesRegex(ValueError,"DIVERGENT_WEATHER"):
            b.fixed_predictions([10,11],[10],300,400,500)

    def test_12_temporal_new_year_is_distinct_from_2022_2023_2024(self):
        self.assertEqual(b.PERIODS[0][1],"2021-01-10")
        self.assertEqual(b.PERIODS[1][1],"2021-07-10")
        self.assertEqual(b.MIN_QC,120)

    def test_13_name_declares_regridding_equivalence_unproven(self):
        self.assertIn("ar/full_37-1h-0p25deg-chunk-1.zarr-v3",a.ARCO_REGULAR)
        self.assertEqual(a.PARAM_NAME,"geopotential_at_surface")
        self.assertFalse(b.fixed_predictions([0],[0],0,0,0)[1][
            "OpenMeteo_arco_regridding_equivalence_proven"])

    def test_14_native_and_regular_ERA5_heights_not_conflated(self):
        self.assertNotEqual(a.ARCO_REGULAR,"gs://gcp-public-data-arco-era5/co/single-level-reanalysis.zarr-v2")

if __name__=="__main__":
    unittest.main()
