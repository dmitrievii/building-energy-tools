"""P6.2D calendar-month heldout and quantile delta science tests."""
from __future__ import annotations
import unittest
from p6_2d_solar_methods_benchmark import (
    CAL,TEST,METHODS,fit_months,apply_heldout_month,qdm_target,
    discrepancy,interp_percentile,ensure_complete,
)

def fixture():
    station={}
    model={}
    for y in range(1995,2015):
        for m in range(1,13):
            value=30+10*m+1.1*(y-1995)+(m%3)*2.
            station[y,m]=value
            model[y,m]=value*1.3
    return station,model

class SolarHoldoutScienceTests(unittest.TestCase):
    def test_splits_are_temporally_disjoint(self):
        self.assertEqual((min(CAL),max(CAL),min(TEST),max(TEST)),(1995,2004,2005,2014))
        self.assertEqual(set(CAL)&set(TEST),set())

    def test_m0_equals_unmodified_nasa(self):
        obs,model=fixture()
        rules=fit_months(obs,model)
        target=apply_heldout_month(model,rules)
        self.assertEqual(len(target),120)
        for year in TEST:
            for month in range(1,13):
                self.assertAlmostEqual(target[year,month][METHODS[0]],model[year,month])

    def test_m1_reverses_synthetic_30pct_calibration_bias(self):
        obs,model=fixture()
        fitted=fit_months(obs,model)
        for month in range(1,13):
            self.assertAlmostEqual(fitted[month]["monthly_factor"],1/1.3,places=12)
        target=apply_heldout_month(model,fitted)
        for year in TEST:
            for month in range(1,13):
                self.assertAlmostEqual(target[year,month][METHODS[1]],obs[year,month],places=10)

    def test_qdm_multiplicative_shift_and_trend_preservation(self):
        rule={
            "model_calibration_sorted":tuple(110+10*i for i in range(10)),
            "observed_calibration_sorted":tuple(80+8*i for i in range(10)),
        }
        baseline=[110+10*i for i in range(10)]
        future=[1.25*x for x in baseline]
        q0=qdm_target(baseline,rule)
        qfuture=qdm_target(future,rule)
        for a,b in zip(q0,qfuture):
            self.assertAlmostEqual(b/a,1.25,places=10)

    def test_qdm_does_not_consume_station_holdout(self):
        obs,model=fixture()
        fitted=fit_months(obs,model)
        expected=apply_heldout_month(model,fitted)
        for y in TEST:
            for m in range(1,13):
                obs[y,m]=9999
        test_after=apply_heldout_month(model,fit_months(obs,model))
        self.assertEqual(expected,test_after)

    def test_qdm_rejects_zero_negative_and_nan_solar(self):
        rule={"model_calibration_sorted":(30,40),"observed_calibration_sorted":(25,35)}
        for vals in ([0,30],[-1,30],[float("nan"),30]):
            with self.assertRaisesRegex(ValueError,"positive finite"):
                qdm_target(vals,rule)

    def test_no_per_year_paired_metric(self):
        obs,model=fixture()
        target=apply_heldout_month(model,fit_months(obs,model))
        monthly,scores=discrepancy(target,obs,METHODS[0])
        self.assertEqual(len(monthly),12)
        self.assertTrue(scores["not_paired_model_year_rmse"])
        self.assertGreater(scores["annual_climatological_bias_percent"],25)
        self.assertNotIn("RMSE",scores)

    def test_complete_calendar_contract_rejects_missing_month(self):
        station,model=fixture()
        del station[(2003,2)]
        with self.assertRaisesRegex(ValueError,"Missing/duplicated"):
            fit_months(station,model)

    def test_distribution_quantile_is_bounded(self):
        self.assertAlmostEqual(interp_percentile((2,4,6),.5),4)
        with self.assertRaisesRegex(ValueError,"Invalid percentile"):
            interp_percentile((2,4),1.1)

    def test_distinct_observed_bias_does_not_forge_model_year_matching(self):
        obs,model=fixture()
        target=apply_heldout_month(model,fit_months(obs,model))
        orig_score=discrepancy(target,obs,METHODS[1])[1]
        # Permuting observations among heldout years (within each calendar
        # month) must not change any unpaired distribution/climatology metric.
        new_obs=dict(obs)
        for m in range(1,13):
            for i,y in enumerate(TEST):
                new_obs[y,m]=obs[list(TEST)[len(TEST)-i-1],m]
        reorder_score=discrepancy(target,new_obs,METHODS[1])[1]
        self.assertEqual(orig_score,reorder_score)

if __name__=="__main__":unittest.main()
