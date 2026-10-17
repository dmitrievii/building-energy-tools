"""Original-SRTM/ARCO adapter tests: synthetic fixtures, no new station reads."""
import unittest
from p9_1h23_source_era5_dem_adapter import (
    index_from_existing_P9F1_original_srtm,predict_one_frozen_regional_hour
)

def terrain(*, center=100., ring=None):
    if ring is None:ring=[400.,450.,350.,500.,420.,300.,460.,390.]
    elevations=sorted(ring)
    p75=elevations[5]*.75+elevations[6]*.25
    return {
        "source_station_QC_temperature_was_never_used_to_derive_terrain":True,
        "terrain_inferred_valley_susceptibility_only_not_inversion_detection":True,
        "ring12km_m":list(ring),"original_srtm90m_site_m":center,
        "ring12km_p75_relief_m":p75-center,
        "ring12km_uphill_fraction":sum(z>center+50 for z in ring)/8}

def cell(z=500):
    return {"ARCO_025_original_model_height_m":z,
            "same_ERA5_grid_node_coordinate_as_OpenMeteo":True,
            "same_model_topographic_interpolation_proven":False}

def predict(weather=None, tr=None, **extra):
    return predict_one_frozen_regional_hour(
        country_code="AT",timestamp_utc="2022-01-11T01:00:00Z",
        latitude=47.0,longitude=15.0,
        source_weather_era5=weather or {
            "temperature_2m":2.,
            "cloud_cover":10.,"wind_speed_10m":1.},
        site_height_m=100.,source_arco_grid_cell=cell(),
        source_original_srtm=tr or terrain(),
        **extra)

class TestH23ExistingResearchSources(unittest.TestCase):
    def test_true_independent_valley_morphology_nonzero(self):
        t=index_from_existing_P9F1_original_srtm(terrain(),100.,500.)
        self.assertGreater(t["terrain_cold_pool_index"],0.)
        self.assertTrue(t["frozen_prior_geometric_gates_passed"])

    def test_flatland_geography_zeroes_correction(self):
        tr=terrain(center=100.,ring=[95.,100.,105.,102.,100.,99.,97.,101.])
        res=predict(tr=tr)
        self.assertEqual(res["physical_correction_C"],0.)
        self.assertEqual(res["physical_status"],"NO_DEM_COLD_POOL_SIGNAL_BACKOFF")

    def test_2022_strict_windows_no_2021(self):
        with self.assertRaisesRegex(ValueError,"WINDOW"):
            predict_one_frozen_regional_hour(
              country_code="AT",timestamp_utc="2021-01-11T01:00:00Z",
              latitude=47.,longitude=15.,
              source_weather_era5={"temperature_2m":2.},
              site_height_m=100.,source_arco_grid_cell=cell(),
              source_original_srtm=terrain())

    def test_bounded_physics_and_baseline_coherent(self):
        r=predict()
        self.assertGreater(r["original_dem_morphology"]["terrain_cold_pool_index"],0.)
        self.assertLessEqual(r["physical_correction_C"],0.)
        self.assertGreaterEqual(r["physical_correction_C"],-1.25)
        self.assertAlmostEqual(r["three_baselines"]["B1_native_grid_fixed_lapse_C"],4.6)
        self.assertTrue(r["real_observed_2m_station_MAE_unavailable"])
        self.assertEqual(r["phase"],"P9H23_AT_DE_CH_FROZEN_2022_EVALUATION")
        self.assertEqual(r["country_code"],"AT")

    def test_no_netherlands_or_finland_reuse(self):
        with self.assertRaisesRegex(ValueError,"COUNTRY"):
            predict_one_frozen_regional_hour(
                country_code="NL",timestamp_utc="2022-01-11T01:00:00Z",
                latitude=52.,longitude=5.,
                source_weather_era5={"temperature_2m":2.},
                site_height_m=100.,source_arco_grid_cell=cell(),
                source_original_srtm=terrain())

    def test_no_hidden_claim_ARCO_same_provider_regridding(self):
        x=cell();x["same_model_topographic_interpolation_proven"]=True
        with self.assertRaisesRegex(ValueError,"IMPOSSIBLE_PROVIDER_REGRID"):
            predict_one_frozen_regional_hour(
                country_code="AT",timestamp_utc="2022-01-11T01:00:00Z",
                latitude=47.,longitude=15.,
                source_weather_era5={"temperature_2m":2.},
                site_height_m=100.,source_arco_grid_cell=x,
                source_original_srtm=terrain())

    def test_srtm_provenance_hard_required(self):
        x=terrain();x["source_station_QC_temperature_was_never_used_to_derive_terrain"]=False
        with self.assertRaisesRegex(ValueError,"SRTM_NOT_INDEPENDENT"):
            index_from_existing_P9F1_original_srtm(x,100.,500.)

    def test_original_dem_summary_corruption_rejected(self):
        x=terrain();x["ring12km_p75_relief_m"]+=100
        with self.assertRaisesRegex(ValueError,"P75_INCONSISTENT"):
            index_from_existing_P9F1_original_srtm(x,100.,500.)

if __name__=="__main__":
    unittest.main()
