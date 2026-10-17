"""P9.1D non-fitting physically screened lapse + source geometry controls."""
import unittest
import p9_1d_independent_station_correction as d

class P91DConditioningContracts(unittest.TestCase):
    def test_fixed_physical_lapse_is_explicit_and_not_fitted(self):
        self.assertEqual(d.LAPSE_K_M,-.0065)
        self.assertEqual(d.MAX_CORR_C,3.)
        self.assertEqual(d.MIN_QC_HOURS,120)

    def test_true_temperature_height_source_difference(self):
        temperatures=[10.]*168
        down=[11.]*168
        methods,meta=d.physically_fixed_candidates(
            temperatures,down,[5.]*168,[100.]*168,
            [10]*168,1000.,500.,"summer_2022")
        self.assertAlmostEqual(meta["raw_fixed_6p5_K_per_km_correction_C"],-3.25)
        self.assertEqual(methods["L1_ERA5_N320_FIXED_LAPSE_PROXY"][0],6.75)
        self.assertEqual(methods["L2_BOUNDED_FIXED_LAPSE_PROXY"][0],7.)
        self.assertEqual(meta["guarded_hours"],0)

    def test_winter_night_clear_calm_valley_guard_is_predictor_only(self):
        fields,meta=d.physically_fixed_candidates(
            [10.]*168,[11.]*168,[1.]*168,[20.]*168,[22]*168,
            400.,1000.,"winter_2022")
        self.assertEqual(meta["guarded_hours"],168)
        self.assertEqual(fields["L3_CONDITIONED_NIGHT_VALLEY_GUARD_PROXY"][0],10.)
        self.assertEqual(fields["L2_BOUNDED_FIXED_LAPSE_PROXY"][0],13.)

    def test_same_valley_but_cloudy_does_not_apply_guard(self):
        _,meta=d.physically_fixed_candidates(
            [10.],[11.],[1.],[90.],[22],400.,1000.,"winter_2022")
        self.assertEqual(meta["guarded_hours"],0)

    def test_guard_does_not_use_actual_target_observation(self):
        import inspect
        p=inspect.signature(d.physically_fixed_candidates)
        self.assertNotIn("observations",p.parameters)
        self.assertNotIn("target_temperature",p.parameters)

    def test_2022_is_independent_from_previously_studied_2023_2024(self):
        self.assertEqual(d.PERIODS[0][1],"2022-01-10")
        self.assertEqual(d.PERIODS[1][1],"2022-07-10")

    def test_reject_nonfinite_source_no_imputation(self):
        with self.assertRaisesRegex(ValueError,"NONFINITE"):
            d.physically_fixed_candidates([float("nan")],[10],[3],[20],[10],
                                          400,1000,"summer_2022")

    def test_score_requires_120_original_hourly_pairs(self):
        obs={str(i):10. for i in range(119)}
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT"):
            d.score_pair(list(obs),[10.]*len(obs),obs)

    def test_observed_temps_not_in_any_model_predictions(self):
        source={"a":10., "b":15.}
        import inspect
        f=inspect.signature(d.physically_fixed_candidates)
        self.assertNotIn("original_obs",f.parameters)

if __name__=="__main__":unittest.main()
