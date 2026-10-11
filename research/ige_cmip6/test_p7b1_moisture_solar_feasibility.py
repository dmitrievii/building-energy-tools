"""P7B.1 contract: source hurs/huss source feasibility and UNPAIRED solar distribution."""
from __future__ import annotations
import math,unittest
from datetime import date,datetime,timedelta
from statistics import fmean
from p7b1_moisture_solar_feasibility import (
 moisture_daily_candidate,annual_solar_distribution,stationary_observed_solar_climatology,
 P_PROXY,MODEL_YEARS,RH_SHAPE_CAP_PP)
from p7b_daily_to_hourly_cmip6_pilot import q_from_t_rh

class P7B1MoistureAndSolarContracts(unittest.TestCase):
    def temps(self):
        return [12+6*math.cos(2*math.pi*(h-15)/24) for h in range(24)]

    def test_native_hurs_and_huss_jointly_closed_where_reachable(self):
        temps=self.temps()
        original=fmean(q_from_t_rh(t,60,P_PROXY) for t in temps)
        rh,dew,report=moisture_daily_candidate(temps,60,original)
        self.assertEqual(report["status"],"JOINT_CLOSED_WITHIN_25PP_RH_FAMILY")
        self.assertAlmostEqual(fmean(rh),60,places=9)
        self.assertAlmostEqual(report["candidate_minus_original_huss_kg_kg"],0,places=9)
        self.assertTrue(all(0<=v<=100 for v in rh))
        self.assertTrue(all(v<=t+1e-7 for v,t in zip(dew,temps)))

    def test_nonzero_night_day_profile_can_match_another_source_huss(self):
        temps=self.temps()
        weights=[(fmean(temps)-t)/6 for t in temps]
        native=fmean(q_from_t_rh(t,60+12*w,P_PROXY)
                     for t,w in zip(temps,weights))
        rh,dew,report=moisture_daily_candidate(temps,60,native)
        self.assertEqual(report["status"],"JOINT_CLOSED_WITHIN_25PP_RH_FAMILY")
        self.assertAlmostEqual(fmean(q_from_t_rh(t,v,P_PROXY)
                          for t,v in zip(temps,rh)),native,places=9)
        self.assertTrue(all(v<=t for v,t in zip(dew,temps)))
        self.assertLessEqual(abs(report["rh_shape_coefficient_pp"]),25)

    def test_incompatible_family_not_pretended_closed(self):
        temps=self.temps()
        rh,dew,report=moisture_daily_candidate(temps,50,.00005)
        self.assertEqual(report["status"],"NOT_CLOSED_WITHIN_25PP_RH_FAMILY")
        self.assertGreater(abs(report["candidate_minus_original_huss_kg_kg"]),1e-6)
        self.assertAlmostEqual(fmean(rh),50,places=9)
        self.assertTrue(all(0<=v<=100 for v in rh))
        self.assertEqual(len(dew),24)

    def test_reject_physically_unbounded_humidity_and_source_gaps(self):
        t=self.temps()
        for rh,q in ((-1,.003),(101,.005),(50,-.003)):
            with self.subTest(rh=rh,q=q),self.assertRaises(ValueError):
                moisture_daily_candidate(t,rh,q)
        with self.assertRaisesRegex(ValueError,"24-hour"):
            moisture_daily_candidate(t[:23],60,.007)
        self.assertEqual(RH_SHAPE_CAP_PP,25.)

    def test_true_station_observed_solar_climatology_is_distinct_from_nasa_grid(self):
        original=[];station={}
        for y in MODEL_YEARS:
            days=366 if y in (2008,2012) else 365
            start=date(y,1,1)
            station[y]=[((start+timedelta(days=i)).month,2.5) for i in range(days)]
            for i in range(365):
                day=start+timedelta(days=i)
                original.append({"year":str(y),"month":str(day.month),
                                 "rsds_kwh_m2_day":"3.0"})
        annual,month,clim=stationary_observed_solar_climatology(original,station)
        self.assertEqual(len(annual),10)
        self.assertEqual(len(month),12)
        self.assertAlmostEqual(clim["model_10y_mean_annual_kwh_m2"],1095.)
        self.assertAlmostEqual(clim["station_observed_10y_mean_365day_normalized_kwh_m2"],912.5)
        self.assertAlmostEqual(clim["model_minus_station_pct"],20.)
        self.assertEqual(annual[3]["observed_station_days"],366)

    def test_multiyear_unpaired_monthly_solar_and_leap_normalization(self):
        model=[];nasa={}
        for year in MODEL_YEARS:
            records=[]
            start=date(year,1,1)
            for i in range(365):
                day=start+timedelta(days=i)
                # GCM source has 365 noleap solar days; test MONTH is genuine,
                # not all January (missing-month synthetic fixture is invalid).
                model.append({"year":str(year),"month":str(day.month),
                              "rsds_kwh_m2_day":"4"})
            length=(366 if year in (2008,2012) else 365)*24
            nasa[year]=[((datetime(year,1,1)+timedelta(hours=i)).month,.125)
                        for i in range(length)]
        annual,monthly,clim=annual_solar_distribution(model,nasa)
        self.assertEqual(len(annual),10)
        self.assertEqual(len(monthly),12)
        self.assertEqual(annual[3]["nasa_original_hours"],8784)
        self.assertAlmostEqual(annual[3]["nasa_annual_365day_normalized_kwh_m2"],1095)
        self.assertAlmostEqual(clim["model_10y_mean_annual_kwh_m2"],1460)
        self.assertAlmostEqual(clim["nasa_10y_mean_annual_365day_normalized_kwh_m2"],1095)
        self.assertTrue(all(r["comparison"].startswith("UNPAIRED") for r in monthly))
        self.assertAlmostEqual(clim["model_minus_nasa_10y_climatological_pct"],100*(4/3-1))

if __name__=="__main__":
    unittest.main()
