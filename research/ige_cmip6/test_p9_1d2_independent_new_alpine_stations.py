"""P9.1D2 genuine new-site holdout immutability and frozen candidate controls."""
import unittest
import p9_1d2_independent_new_alpine_stations as p
import p9_1d_independent_station_correction as model

class NewSiteContracts(unittest.TestCase):
    def test_six_new_sites_have_no_leakage_of_old_three(self):
        self.assertEqual(len(set(p.IDS)),6)
        self.assertFalse(set(p.IDS)&{30,39,196})

    def test_2022_seasons_frozen_and_new_site_sample_floor(self):
        self.assertEqual(model.PERIODS[0][1],"2022-01-10")
        self.assertEqual(p.MINIMUM,96)

    def test_native_grid_heights_remain_source_proxy(self):
        self.assertIn("N320",model.METHODS[2])
        self.assertEqual(model.MAX_CORR_C,3.)

    def test_missing_real_registered_original_station_is_fatal(self):
        with self.assertRaisesRegex(ValueError,"STATION_ID_MISSING"):
            p.full_station_metadata({"stations":[]})

if __name__=="__main__":unittest.main()
