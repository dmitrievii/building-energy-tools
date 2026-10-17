"""IGE P9.1F1 physically preregistered cold-pool susceptibility controls."""
import datetime as dt
import math
import unittest

import p9_1f1_terrain_inversion_2019_holdout as f


class P91FColdPoolContracts(unittest.TestCase):
    def test_01_geographic_source_cohort_is_frozen_before_2019(self):
        self.assertEqual(f.IDS,(105,56,145,48,15,22,39,196,14305))
        self.assertEqual(len(f.PERIODS),3)
        self.assertTrue(all(p[1].startswith("2019") for p in f.PERIODS))
        self.assertEqual(f.MIN_QC,120)

    def test_02_srtm_two_independent_radius_ring_geometry(self):
        points,keys=f.terrain_source_points([{
            "id":48,"name":"Klagenfurt","lat":46.62,"lon":14.3,"altitude_m":448}])
        self.assertEqual(len(points),17)
        self.assertEqual(len(keys[48]),17)
        self.assertEqual(len({p["id"] for p in points}),17)
        self.assertEqual(len([p for p in points if "12km" in p["id"]]),8)

    def test_03_geodesic_radius_not_fixed_lat_degree(self):
        lat,lon=f.ring_coordinates(47.,15.,12.,90.)
        dist=f.era.haversine(47.,15.,lat,lon)
        self.assertAlmostEqual(dist,12.,places=4)

    def test_04_cold_valley_high_grid_height_clear_winter_night_suppresses_warming(self):
        base=["2019-01-11T01:00"]*168
        preds,flags,m=f.make_fixed_predictions(
            [0.]*168,[2.]*168,[1.]*168,[10.]*168,[0.]*168,base,
            450.,850.,320.)
        self.assertEqual(sum(flags),168)
        self.assertTrue(m["predeclared_valley_geometry_susceptible"])
        self.assertAlmostEqual(preds["L1_REGULAR_LAPSE"][0],2.6)
        self.assertEqual(preds["L2_TERRAIN_NIGHT_GUARD"][0],0.)
        self.assertEqual(preds["L3_TERRAIN_NIGHT_COLDPOOL"][0],-1.)

    def test_05_windy_weather_disables_guard(self):
        d,flags,m=f.make_fixed_predictions(
            [0.],[1.],[3.],[5.],[0.],["2019-01-11T01:00"],450.,850.,320.)
        self.assertFalse(flags[0])
        self.assertEqual(d["L2_TERRAIN_NIGHT_GUARD"][0],d["L1_REGULAR_LAPSE"][0])

    def test_06_cloud_cover_disables_guard(self):
        _,flags,_=f.make_fixed_predictions(
            [0.],[1.],[1.],[85.],[0.],["2019-01-11T01:00"],450.,850.,320.)
        self.assertFalse(flags[0])

    def test_07_daytime_solar_disables_guard(self):
        _,flags,_=f.make_fixed_predictions(
            [0.],[1.],[1.],[10.],[50.],["2019-01-11T12:00"],450.,850.,320.)
        self.assertFalse(flags[0])

    def test_08_summer_calm_night_not_designated_cold_season(self):
        _,flags,_=f.make_fixed_predictions(
            [0.],[1.],[1.],[10.],[0.],["2019-07-11T01:00"],450.,850.,320.)
        self.assertFalse(flags[0])

    def test_09_no_valley_relief_disables_guard(self):
        _,flags,_=f.make_fixed_predictions(
            [0.],[1.],[1.],[10.],[0.],["2019-01-11T01:00"],450.,850.,10.)
        self.assertFalse(flags[0])

    def test_10_grid_below_station_disables_valley_susceptibility(self):
        _,flags,m=f.make_fixed_predictions(
            [0.],[1.],[1.],[10.],[0.],["2019-01-11T01:00"],1550.,850.,400.)
        self.assertFalse(flags[0])
        self.assertFalse(m["predeclared_valley_geometry_susceptible"])

    def test_11_boundary_conditions_wind_cloud_GHI_are_strict(self):
        _,flags,_=f.make_fixed_predictions(
            [0.],[1.],[2.5],[60.],[10.],["2019-01-11T01:00"],450.,850.,320.)
        self.assertFalse(flags[0])

    def test_12_NaN_source_weather_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"NONFINITE_SOURCE_WEATHER"):
            f.make_fixed_predictions([0.],[1.],[float("nan")],[10.],[0.],
                                     ["2019-01-11T01:00"],450.,850.,320.)

    def test_13_unequal_source_lengths_rejected(self):
        with self.assertRaisesRegex(ValueError,"TIMELINES_NOT_ALIGNED"):
            f.make_fixed_predictions([0.,1.],[1.],[1.],[10.],[0.],
                                     ["2019-01-11T01:00"],450.,850.,320.)

    def test_14_outcome_scoring_is_observation_only_not_predictor(self):
        # Source guard remains independent of observed target temperature.
        import inspect
        self.assertNotIn("observations",inspect.signature(
            f.make_fixed_predictions).parameters)
        t=[(dt.datetime(2019,1,10)+dt.timedelta(hours=i)).strftime(
            "%Y-%m-%dT%H:%M") for i in range(168)]
        obs=dict.fromkeys(t,0.)
        r=f.score_qualified(obs,t,[1.]*168,[True]*20+[False]*148)
        self.assertEqual(r["n_original_QC_observation_matched"],168)
        self.assertEqual(r["n_original_QC_guarded_hours"],20)
        self.assertEqual(r["MAE_C"],1.)
        self.assertEqual(r["guarded_MAE_C"],1.)

    def test_15_original_QC_minimum_is_enforced(self):
        with self.assertRaisesRegex(ValueError,"TOO_FEW_QUALIFIED_OBS"):
            f.score_qualified({},["2019-01-11T01:00"],[1.],[False])

    def test_16_candidate_parameters_fixed_to_physical_research_controls(self):
        self.assertEqual(f.LAPSE_COEFF,-.0065)
        self.assertEqual(f.MIN_12KM_TERRAIN_P75_RELIEF_M,120.)
        self.assertEqual(f.MIN_GRID_STATION_DZ_M,150.)
        self.assertEqual(f.MAX_WIND_MS,2.5)
        self.assertEqual(f.MAX_CLOUD_PERCENT,60.)
        self.assertEqual(f.FIXED_COLDPOOL_PERTURBATION_C,-1.)

    def test_17_method_separation_even_when_guard_never_triggers(self):
        p,flags,_=f.make_fixed_predictions(
            [1.],[2.],[5.],[80.],[100.],["2019-10-11T10:00"],400.,800.,200.)
        self.assertEqual(p["L1_REGULAR_LAPSE"],p["L2_TERRAIN_NIGHT_GUARD"])
        self.assertEqual(p["L2_TERRAIN_NIGHT_GUARD"],p["L3_TERRAIN_NIGHT_COLDPOOL"])
        self.assertEqual(flags,[False])

    def test_18_source_time_of_day_uses_hourly_GHI_not_civil_night_guess(self):
        p,flags,_=f.make_fixed_predictions(
            [1.],[2.],[1.],[10.],[0.],["2019-10-11T10:00"],400.,800.,200.)
        self.assertEqual(flags,[True])

if __name__=="__main__":
    unittest.main()
