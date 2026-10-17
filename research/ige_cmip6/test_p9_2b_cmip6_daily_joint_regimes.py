"""P9.2B strict local science contracts, no external source needed."""
import datetime as dt
import math
import unittest
from p9_2a_joint_weather_regimes import Day,check_vector
from p9_2b_cmip6_daily_joint_regime_solver import (
    InfeasibleDailyClimate,source_hourly_mean_temperature,distribute_exact,
    new_day,generate,native_target,select_donor,summarize,qsat,q_of_e,sat_pa,
    geometry
)
SHA="a"*64
def donor(wet=True,year=2019,month=1,day=10):
    winds=[];x=[]
    for hour in range(24):
        t=4+4*math.sin(2*math.pi*(hour-6)/24)
        rh=73.
        sun=max(0,math.sin(math.pi*(hour-7)/11))
        ghi=200.*sun
        wet_hour=wet and 10<=hour<=13
        x.append({"temperature_2m":t,"dew_point_2m":t-3.2,
          "relative_humidity_2m":rh,"surface_pressure":1000.,
          "precipitation":.3 if wet_hour else 0.,
          "cloud_cover":85. if wet else 30.,
          "shortwave_radiation":ghi,"direct_radiation":ghi*.35,
          "diffuse_radiation":ghi*.65,
          "direct_normal_irradiance":500. if sun>0 else 0.,
          "wind_speed_10m":2.+hour*.02,"wind_direction_10m":180.})
    return Day(dt.date(year,month,day),tuple(x),SHA)

def target(wet=True,year=2013,month=1,day=10):
    return {"date":dt.date(year,month,day),
        "tas_c":4.,"tasmin_c":0.,"tasmax_c":8.,
        "pr_mm_day":2. if wet else 0.,
        "rsds_kwh_m2_day":1.20,"rlds_kwh_m2_day":7.00,
        "sfcWind":2.4,"hurs":78.,"huss":.0042}

class P92BDailyContracts(unittest.TestCase):
    def test_real_joint_donor_wet_all_hard_constraints(self):
        generated,lw,meta=new_day(target(),donor(),47.0707,15.4395)
        self.assertEqual(len(generated.vectors),24)
        for vec in generated.vectors:check_vector(vec)
        residual=meta["daily_native_source_residuals"]
        for k in ("tas_c","tasmin_c","tasmax_c","pr_mm_day",
                  "rsds_kwh_m2_day","rlds_kwh_m2_day","huss","sfcWind"):
            self.assertLess(abs(residual[k]),1e-6,k)
        self.assertTrue(meta["native_daily_q_hard_constraint_closed"])
        self.assertGreater(meta["rainy_hours"],0)
        self.assertEqual(sum(v["precipitation"]>0 for v in generated.vectors),4)
        self.assertEqual(len(lw),24)

    def test_dry_target_dry_donor_no_fake_rain(self):
        generated,lw,meta=new_day(target(wet=False),donor(wet=False),47.0707,15.4395)
        self.assertEqual(meta["rainy_hours"],0)
        self.assertEqual(sum(x["precipitation"] for x in generated.vectors),0)

    def test_original_cloud_fraction_donor_not_independently_randomized(self):
        generated,_,_=new_day(target(),donor(),47.0707,15.4395)
        self.assertTrue(all(v["cloud_cover"]==85. for v in generated.vectors))

    def test_absolute_humidity_physical_from_dewpoint(self):
        generated,_,_=new_day(target(),donor(),47.0707,15.4395)
        for v in generated.vectors:
            self.assertLessEqual(v["dew_point_2m"],v["temperature_2m"]+1e-6)
            self.assertTrue(0<=v["relative_humidity_2m"]<=100)
            self.assertGreater(v["dew_point_2m"],-100)

    def test_exact_temperature_full_mean_min_max_not_sine_substitute(self):
        t=source_hourly_mean_temperature(donor(),native_target(target()))
        self.assertAlmostEqual(min(t),0.,places=7)
        self.assertAlmostEqual(max(t),8.,places=7)
        self.assertAlmostEqual(sum(t)/24,4.,places=7)

    def test_target_year_leakage_fails(self):
        with self.assertRaisesRegex(InfeasibleDailyClimate,"DONOR_LEAK"):
            select_donor([donor(year=2013)],target(),None,7313)

    def test_missing_genuine_gcm_huss_blocks(self):
        t=target();t["huss"]=None
        with self.assertRaises(InfeasibleDailyClimate):
            new_day(t,donor(),47.0707,15.4395)

    def test_infeasible_temperature_mean_min_max_is_rejected(self):
        t=target();t["tas_c"]=0.
        with self.assertRaisesRegex(InfeasibleDailyClimate,"SHAPE_NOT_FEASIBLE"):
            new_day(t,donor(),47.0707,15.4395)

    def test_no_donor_for_required_gcm_wet_day(self):
        with self.assertRaisesRegex(InfeasibleDailyClimate,"NO_ORIGINAL_DONOR"):
            select_donor([donor(wet=False)],target(),None,7313)

    def test_impossible_solar_cap_blocks(self):
        t=target();t["rsds_kwh_m2_day"]=15.
        with self.assertRaisesRegex(InfeasibleDailyClimate,"EXCEEDS_PHYSICAL"):
            new_day(t,donor(),47.0707,15.4395)

    def test_supersaturation_q_blocks_without_clipping_source_q(self):
        t=target();t["huss"]=.06
        with self.assertRaisesRegex(InfeasibleDailyClimate,"EXCEEDS_PHYSICAL"):
            new_day(t,donor(),47.0707,15.4395)

    def test_zero_donor_rain_is_not_morphed_to_future_wet(self):
        with self.assertRaisesRegex(InfeasibleDailyClimate,"NO_WET_DONOR"):
            new_day(target(),donor(wet=False),47.0707,15.4395)

    def test_wind_mean_native_exact_preserves_direction(self):
        generated,_,_=new_day(target(),donor(),47.0707,15.4395)
        self.assertAlmostEqual(sum(v["wind_speed_10m"] for v in generated.vectors)/24,2.4,places=8)
        self.assertTrue(all(v["wind_direction_10m"]==180. for v in generated.vectors))

    def test_ghi_derived_partition_day_night_and_daily_total(self):
        generated,_,_=new_day(target(),donor(),47.0707,15.4395)
        cos=geometry(target()["date"],47.0707,15.4395)
        self.assertAlmostEqual(sum(v["shortwave_radiation"] for v in generated.vectors)/1000,1.2,places=8)
        for v,z in zip(generated.vectors,cos):
            self.assertLessEqual(v["shortwave_radiation"],1450*z+1e-5)
            self.assertLessEqual(v["direct_normal_irradiance"],1400+1e-5)
            self.assertAlmostEqual(v["shortwave_radiation"],v["direct_radiation"]+v["diffuse_radiation"],places=7)

    def test_seed_is_deterministic_full_generated_weather(self):
        pool=[donor(wet=bool(i%2),year=2019+(i%2),day=10+i) for i in range(4)]
        dates=[target(wet=bool(i%2),day=10+i) for i in range(4)]
        a,b=generate(dates,pool,47.0707,15.4395,7313)
        c,d=generate(dates,pool,47.0707,15.4395,7313)
        self.assertEqual(b,d)
        self.assertEqual([(x[0].vectors,x[2]) for x in a],[(x[0].vectors,x[2]) for x in c])

    def test_incomplete_cohort_report_has_blocked_reasons(self):
        pool=[donor(wet=False)]
        dates=[target(wet=True)]
        good,blocked=generate(dates,pool,47.0707,15.4395)
        report=summarize(good,blocked,len(dates))
        self.assertEqual(report["n_physically_blocked"],1)
        self.assertEqual(report["n_conserved"],0)
        self.assertFalse(report["not_EPW_production_qualified"] is False)
if __name__=="__main__":
    unittest.main()
