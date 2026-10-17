"""P9.1F2 observed independent 2019 valley-crest pair original source contracts."""
import unittest
import p9_1f2_original_2019_observed_valley_summit_pairs as p

class ObservedPairQA(unittest.TestCase):
    def test_01_four_previous_observatory_pairs_not_selected_by_2019_temp(self):
        self.assertEqual(len(p.PAIRS),4)
        self.assertEqual(p.PAIRS[-1][:2],(39,196))

    def test_02_correct_seasonal_year_split_and_local_clock(self):
        self.assertEqual(len(p.PERIODS),3)
        self.assertTrue(all(y[1].startswith("2019") for y in p.PERIODS))
        self.assertEqual(p.daypart_utc("2019-01-10T21:00"),"night")
        self.assertEqual(p.daypart_utc("2019-07-10T12:00"),"day")

    def test_03_2019_observed_pair_warmer_upper_is_not_just_weak_lapse(self):
        times=[f"2019-01-10T{h:02d}:00" for h in range(24)]
        keys=times*5
        self.assertEqual(len(keys),120)
        # Use real unique UTC samples to mimic 2019 week, not duplicated 1-day labels.
        import datetime as dt
        base=dt.datetime(2019,1,10)
        names=[(base+dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
               for i in range(168)]
        lower=dict.fromkeys(names,0.)
        upper=dict.fromkeys(names,-2.)
        scored=p.compute_pair(lower,upper,600.)
        self.assertEqual(scored["status"],"ORIGINAL_OBSERVED_PAIR_QC_QUALIFIED")
        all_=scored["groups"]["all"]
        self.assertAlmostEqual(all_["observed_spatial_upper_warmer_fraction"],0.)
        # Upper temp -2C is warmer than a dry lapse -3.9C without inversion.
        self.assertAlmostEqual(all_["observed_upper_warmer_than_standard_lapse_fraction"],1.)
        self.assertTrue(all_["observed_Tupper_above_Tlower_is_not_proof_collocated_inversion"])

    def test_04_insufficient_original_observed_QC_blocks_pair(self):
        scored=p.compute_pair({"2019-01-10T00:00":2.},
                              {"2019-01-10T00:00":1.},500.)
        self.assertEqual(scored["status"],"INSUFFICIENT_ORIGINAL_QC_PAIRED_HOURS")

    def test_05_cannot_invert_wrong_altitude_reference(self):
        with self.assertRaisesRegex(ValueError,"UPPER_STATION_NOT_HIGHER"):
            p.compute_pair({}, {},-10.)

    def test_06_during_dst_local_night_is_timezone_aware(self):
        self.assertEqual(p.daypart_utc("2019-07-10T20:00"),"night")
        self.assertEqual(p.daypart_utc("2019-01-10T21:00"),"night")

    def test_07_no_observed_station_values_enter_other_algorithm(self):
        import inspect
        self.assertEqual(set(inspect.signature(p.compute_pair).parameters),
                         {"low","high","dz"})

if __name__=="__main__":
    unittest.main()
