"""P9.3A source-pressure immutable and joint T/huss physical contracts.

These are wholly synthetic fixtures, not independent original-year skill.
"""
import datetime as dt,math,statistics,unittest
from test_p9_2b_cmip6_daily_joint_regimes import donor,target
from p9_2b_cmip6_daily_joint_regime_solver import (
    qsat,native_target,InfeasibleDailyClimate,source_hourly_mean_temperature,new_day)
from p9_3a_pressure_temperature_q_joint import (
    PRESSURE_MODE,MAX_ADJUST_C,_profile,saturation_deficit,
    repair_temperature_profile,repair_candidate,generate)

class P93APhysicalContracts(unittest.TestCase):
    def test_original_P_is_fixed_ERA5_not_native_ps(self):
        d=donor();t=target()
        original=[v["surface_pressure"] for v in d.vectors]
        day,lw,meta=repair_candidate(d,t,47.0707,15.4395)
        self.assertEqual([v["surface_pressure"] for v in day.vectors],original)
        self.assertFalse(meta["native_GCM_pressure_ps_available"])
        self.assertIn("NOT_NATIVE",meta["donor_pressure_source"])
    def test_no_temperature_perturbation_when_original_q_feasible(self):
        d=donor();t=target()
        vals,diag=repair_temperature_profile(d,t)
        self.assertFalse(diag["temperature_repaired"])
        self.assertAlmostEqual(statistics.fmean(vals),t["tas_c"])
        self.assertAlmostEqual(max(vals),t["tasmax_c"])
        self.assertAlmostEqual(min(vals),t["tasmin_c"])
    def test_original_huss_and_all_native_hard_fields(self):
        d=donor();t=target()
        day,lw,meta=repair_candidate(d,t,47.0707,15.4395)
        self.assertTrue(meta["huss_native_hard_closed"])
        self.assertTrue(all(v["dew_point_2m"]<=v["temperature_2m"]+1e-6 for v in day.vectors))
    def test_original_huss_too_high_fails_closed_at_fixed_p(self):
        d=donor();t=target();t["huss"]=.08
        with self.assertRaisesRegex(InfeasibleDailyClimate,"P93A_FIXED_PRESSURE"):
            repair_temperature_profile(d,t)
    def test_joint_temperature_optimization_attempt_one_numerical_gate(self):
        d=donor();t=target()
        n,base,p=_profile(d,t)
        capacity=statistics.fmean(qsat(x,y)*.999999999 for x,y in zip(base,p))
        t["huss"]=capacity+5e-8
        try:
            new_t,meta=repair_temperature_profile(d,t)
        except InfeasibleDailyClimate as ex:
            self.assertTrue(str(ex).startswith("P93A_"))
            return
        self.assertTrue(meta["temperature_repaired"])
        self.assertLessEqual(max(abs(x-y) for x,y in zip(new_t,base)),MAX_ADJUST_C+1e-5)
        self.assertAlmostEqual(statistics.fmean(new_t),t["tas_c"],places=6)
        self.assertAlmostEqual(min(new_t),t["tasmin_c"],places=6)
        self.assertAlmostEqual(max(new_t),t["tasmax_c"],places=6)
        self.assertGreaterEqual(statistics.fmean(qsat(x,y)*.999999999 for x,y in zip(new_t,p)),t["huss"]-1e-9)
    def test_no_target_year_donor_leakage(self):
        with self.assertRaisesRegex(ValueError,"LEAK"):
            generate([target()],[donor(year=2013)],47.0707,15.4395)
    def test_weather_regime_no_fabrication(self):
        t=target(wet=True)
        good,bad=generate([t],[donor(wet=False)],47.0707,15.4395)
        self.assertFalse(good);self.assertEqual(len(bad),1)
    def test_temperature_override_rejects_wrong_daily_mean(self):
        d=donor();t=target()
        base=source_hourly_mean_temperature(d,native_target(t))
        base[0]+=1
        with self.assertRaisesRegex(InfeasibleDailyClimate,"OVERRIDE"):
            new_day(t,d,47.0707,15.4395,temperature_override=base)
    def test_no_source_station_observation_influences_generation(self):
        t=target();d=donor()
        a,b=generate([t],[d],47.0707,15.4395,7313)
        tt=target();tt["2025_original_station_mae_temperature_C"]=10000
        c,e=generate([tt],[d],47.0707,15.4395,7313)
        self.assertEqual(a[0][0].vectors,c[0][0].vectors)
        self.assertEqual(b,e)
    def test_source_seed_determinism(self):
        d=[donor(wet=True,year=2019,day=10),
           donor(wet=True,year=2020,day=11)]
        a,b=generate([target()],d,47.0707,15.4395,7313)
        c,e=generate([target()],d,47.0707,15.4395,7313)
        self.assertEqual(b,e)
        self.assertEqual(a[0][0].vectors,c[0][0].vectors)
    def test_can_use_2014_CET_data_period_header(self):
        from p9_2d_annual_cet_epw_export import epw_header
        hd=epw_header(2014)
        self.assertIn("Wednesday",hd[7])
if __name__=="__main__":unittest.main()
