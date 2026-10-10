"""IGE P6.2D-B scientific contracts: FAO56 solar geometry, no QC leakage,
independent calendar rules, physical solar cap and QDM climate-signal behavior.
"""
from __future__ import annotations
import unittest
from datetime import date,timedelta

from p6_2d_b_daily_clearsky_benchmark import (
    MAX_CLEARSKY_INDEX,STATION_LAT,STATION_ALT_M,NASA_LAT,
    solar_geometry,safe_ratio,fit_daily_clear_index,
    corrected_daily_indices,aggregate_months,TRAIN_YEARS,TEST_YEARS,
)

def samples(noleap=False):
    observed=[];gcm=[]
    day=date(1995,1,1)
    while day<=date(2014,12,31):
        if noleap and day.month==2 and day.day==29:
            day+=timedelta(days=1);continue
        _,clear_obs=solar_geometry(day.month,day.day,day.year,
                                   STATION_LAT,STATION_ALT_M)
        ra,clear_model=solar_geometry(day.month,day.day,day.year,
                                      NASA_LAT,STATION_ALT_M,noleap)
        # Synthetic: no synchronization assumptions. Calibration source is
        # deliberately separated by artificial station-model index bias.
        observed.append({"year":day.year,"month":day.month,"day":day.day,
            "index":.38+(day.day%11)*.004,"rso":clear_obs})
        k=.58+(day.day%11)*.004
        gcm.append({"year":day.year,"month":day.month,"day":day.day,
             "date":day.isoformat(),"rso":clear_model,"ra":ra,
             "index":k,"ghi_kwh_m2_day":k*clear_model})
        day+=timedelta(days=1)
    return observed,gcm

class FAO56ClearSkyContracts(unittest.TestCase):
    def test_sun_geometry_seasonal_and_elevation(self):
        winter_toa,winter_clear=solar_geometry(12,21,2005,47.08,366.)
        summer_toa,summer_clear=solar_geometry(6,21,2005,47.08,366.)
        self.assertGreater(summer_toa,winter_toa)
        self.assertGreater(summer_clear,winter_clear)
        self.assertLess(winter_clear,winter_toa)
        self.assertAlmostEqual(winter_clear/winter_toa,.75+2e-5*366.,places=12)
        self.assertGreater(solar_geometry(6,21,2005,47.08,900.)[1],summer_clear)

    def test_noleap_february_29_rejected(self):
        with self.assertRaisesRegex(ValueError,"Noleap"):
            solar_geometry(2,29,2008,NASA_LAT,366.,noleap=True)
        self.assertGreater(solar_geometry(3,1,2008,NASA_LAT,366.,noleap=True)[1],0)
        self.assertGreater(solar_geometry(2,29,2008,NASA_LAT,366.,noleap=False)[1],0)

    def test_ground_radiation_vs_TOA_not_conflated(self):
        ra,rs=solar_geometry(7,1,2005,47.08,366.)
        self.assertGreater(ra,rs)
        self.assertLess(MAX_CLEARSKY_INDEX*rs,ra)

    def test_observed_small_cloud_enhancement_remains_unclipped(self):
        ra,rs=solar_geometry(6,20,2005,47.08,366.)
        k,excess,toa=safe_ratio(1.035*rs,rs,ra)
        self.assertAlmostEqual(k,1.035,places=9)
        self.assertFalse(excess)
        self.assertFalse(toa)

    def test_extreme_solar_clips_index_and_reports_raw_exceedance(self):
        ra,rs=solar_geometry(6,20,2005,47.08,366.)
        k,excess,toa=safe_ratio(1.5*ra,rs,ra)
        self.assertEqual(k,MAX_CLEARSKY_INDEX)
        self.assertTrue(excess);self.assertTrue(toa)

    def test_calibration_and_holdout_years_disjoint(self):
        self.assertFalse(set(TRAIN_YEARS)&set(TEST_YEARS))
        self.assertEqual((min(TRAIN_YEARS),max(TRAIN_YEARS)),(1995,2004))
        self.assertEqual((min(TEST_YEARS),max(TEST_YEARS)),(2005,2014))

    def test_training_only_and_never_uses_heldout_station_observations(self):
        obs,gcm=samples()
        fitted=fit_daily_clear_index(obs,gcm)
        target=[x for x in gcm if x["year"] in TEST_YEARS]
        base=corrected_daily_indices(target,fitted)
        # Scramble the station observations of all heldout years.
        for r in obs:
            if r["year"] in TEST_YEARS:r["index"]=.999
        fitted2=fit_daily_clear_index(obs,gcm)
        again=corrected_daily_indices(target,fitted2)
        self.assertEqual(base,again)

    def test_m3_corrects_synthetic_index_bias_and_keeps_physical_bounds(self):
        obs,gcm=samples()
        fitted=fit_daily_clear_index(obs,gcm)
        corrected=corrected_daily_indices([x for x in gcm if x["year"] in TEST_YEARS],fitted)
        self.assertEqual(len(corrected),3652)
        self.assertTrue(all(0<=r["m3_kwh_m2_day"]<=
                            r["physical_cap_kwh_m2_day"]+1.e-12 for r in corrected))
        self.assertTrue(all(abs(r["corrected_k"]-(
           r["raw_k"]-.20))<1e-9 for r in corrected))
        months=aggregate_months(corrected)
        self.assertEqual(len(months),120)

    def test_noleap_gcm_calendar_keeps_monthly_coverage(self):
        obs,gcm=samples(noleap=True)
        target=[x for x in gcm if x["year"] in TEST_YEARS]
        result=corrected_daily_indices(target,fit_daily_clear_index(obs,gcm))
        self.assertEqual(len(result),3650)
        self.assertEqual(len(aggregate_months(result)),120)

    def test_target_distribution_relative_index_change_survives_if_unbounded(self):
        obs,gcm=samples()
        rules=fit_daily_clear_index(obs,gcm)
        target=[dict(x) for x in gcm if x["year"] in TEST_YEARS]
        base=corrected_daily_indices(target,rules)
        shifted=[dict(x,index=x["index"]+.07,
                      ghi_kwh_m2_day=(x["index"]+.07)*x["rso"]) for x in target]
        future=corrected_daily_indices(shifted,rules)
        for a,b in zip(base,future):
            self.assertAlmostEqual(b["corrected_k"]-a["corrected_k"],.07,places=9)

    def test_target_must_only_contain_heldout_years(self):
        obs,gcm=samples()
        with self.assertRaisesRegex(ValueError,"training/non-holdout"):
            corrected_daily_indices([x for x in gcm if x["year"]==2000],
                                    fit_daily_clear_index(obs,gcm))

if __name__=="__main__":
    unittest.main()
