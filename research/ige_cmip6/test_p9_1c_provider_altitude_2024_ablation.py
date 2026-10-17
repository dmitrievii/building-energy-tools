"""P9.1C source locked provider-altitude pilot on independent year."""
import urllib.parse
import unittest
import p9_1c_provider_altitude_2024_ablation as c
import p9_1a_global_historical_backbone as a


class TestAltExperiment(unittest.TestCase):
    def test_altitude_provider_is_explicitly_selected(self):
        url=a.request_url(47.,15.,"2024-01-10","2024-01-16")
        v=c.altitude_url(url,2250.)
        q=urllib.parse.parse_qs(urllib.parse.urlsplit(v).query)
        self.assertEqual(q["elevation"],["2250.00"])
        self.assertEqual(q["models"],["era5"])
        self.assertEqual(q["cell_selection"],["nearest"])
        self.assertEqual(q["timezone"],["GMT"])

    def test_not_using_wrong_underlying_provider_model(self):
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_RAW_MODEL"):
            c.altitude_url(a.request_url(47.,15.,"2024-01-10","2024-01-16")
                           .replace("models=era5","models=era5_seamless"),500.)

    def test_same_observed_hours_for_both_models_and_change_of_mae(self):
        import datetime as dt
        first=dt.datetime(2024,1,10)
        times=[(first+dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
               for i in range(168)]
        actual=dict.fromkeys(times,10.)
        raw={"hourly":{"time":times,"temperature_2m":[14.]*168}}
        lowered={"hourly":{"time":times,"temperature_2m":[11.]*168}}
        r=c.score_pair(actual,raw,lowered)
        self.assertEqual(r["n_original_observed_UTC_hour_pairs"],168)
        self.assertEqual(r["raw_grid_MAE_C"],4.)
        self.assertEqual(r["provider_site_altitude_adjusted_MAE_C"],1.)
        self.assertEqual(r["MAE_change_site_adjusted_minus_grid_C"],-3.)
        self.assertTrue(r["site_altitude_correction_is_provider_black_box_not_own_physics"])

    def test_mismatched_models_must_fail_same_observation_cohort(self):
        import datetime as dt
        first=dt.datetime(2024,1,10)
        times=[(first+dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
               for i in range(168)]
        actual=dict.fromkeys(times,10.)
        raw={"hourly":{"time":times,"temperature_2m":[14.]*168}}
        adjusted={"hourly":{"time":times[:-1],"temperature_2m":[11.]*167}}
        with self.assertRaisesRegex(ValueError,"NOT_IDENTICAL_HOURLY"):
            c.score_pair(actual,raw,adjusted)

    def test_2024_independent_season_selection(self):
        self.assertEqual(c.PERIODS[0],("winter_2024","2024-01-10","2024-01-16"))
        self.assertEqual(c.PERIODS[1],("summer_2024","2024-07-10","2024-07-16"))
        self.assertEqual(len(c.PERIODS),2)


if __name__=="__main__":unittest.main()
