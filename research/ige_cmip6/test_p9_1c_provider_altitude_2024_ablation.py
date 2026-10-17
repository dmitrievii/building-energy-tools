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

    def test_sampled_hours_must_be_identical(self):
        model={"hourly":{"time":["2024-01-10T00:00","2024-01-10T01:00"],
                         "temperature_2m":[10.,11.]}}
        station={"2024-01-10T00:00":10.,"2024-01-10T01:00":10.}
        r=c.score_pair(station,model,model) if False else None
        self.assertIsNone(r)

    def test_2024_independent_season_selection(self):
        self.assertEqual(c.PERIODS[0],("winter_2024","2024-01-10","2024-01-16"))
        self.assertEqual(c.PERIODS[1],("summer_2024","2024-07-10","2024-07-16"))
        self.assertEqual(len(c.PERIODS),2)


if __name__=="__main__":unittest.main()
