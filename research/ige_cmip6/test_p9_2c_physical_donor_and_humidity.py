import datetime as dt,math,unittest
from p9_2c_physical_donor_and_humidity import (
    candidates_for_target,generate,humidity_reconcile,InfeasibleDailyClimate
)
from test_p9_2b_cmip6_daily_joint_regimes import donor,target
from p9_2b_cmip6_daily_joint_regime_solver import new_day,q_of_e,sat_pa
class P92CPhysics(unittest.TestCase):
    def test_frozen_ordinary_hard_conservation(self):
        t=target();d=donor()
        day,lw,meta=new_day(t,d,47.0707,15.4395)
        updated,longwave,diag=humidity_reconcile(day,lw,t)
        self.assertAlmostEqual(sum(longwave)/1000,t["rlds_kwh_m2_day"],places=6)
        q=[q_of_e(sat_pa(v["dew_point_2m"]),v["surface_pressure"]*100) for v in updated.vectors]
        self.assertAlmostEqual(sum(q)/24,t["huss"],places=6)
        self.assertTrue(all(v["dew_point_2m"]<=v["temperature_2m"]+.00001 for v in updated.vectors))
    def test_station_outcome_absent_from_donor_selection(self):
        a=[donor(year=2019,day=10),donor(year=2020,day=11)]
        v,b=generate([target()],a,47.0707,15.4395)
        self.assertEqual(len(v),1)
        self.assertEqual(len(b),0)
        self.assertTrue(v[0][2]["no_observed_station_measurements_used_in_selection"])
    def test_missing_wet_regime_blocks(self):
        vals,blocked=generate([target(wet=True)],[donor(wet=False)],47.0707,15.4395)
        self.assertEqual(len(vals),0)
        self.assertEqual(len(blocked),1)
    def test_no_mixed_target_year_leakage(self):
        with self.assertRaisesRegex(ValueError,"LEAK"):
            generate([target()],[donor(year=2013)],47.0707,15.4395)
    def test_solar_strict_blocks_without_silent_rescaling(self):
        t=target();t["rsds_kwh_m2_day"]=15.
        pool,b=candidates_for_target([donor()],t,47.0707,15.4395)
        self.assertEqual(len(pool),0)
        self.assertTrue(b)
    def test_high_huss_blocks_not_clip(self):
        t=target();t["huss"]=.06
        pool,b=candidates_for_target([donor()],t,47.0707,15.4395)
        self.assertEqual(len(pool),0)
        self.assertTrue(any("HUSS" in x for x in b))
    def test_no_new_observed_source_input(self):
        t=target();t["observed_station_temperature"]=2000
        a=generate([t],[donor()],47.0707,15.4395)
        b=generate([target()],[donor()],47.0707,15.4395)
        self.assertEqual(a[0][0][0].vectors,b[0][0][0].vectors)
    def test_native_rh_unattainable_explicit(self):
        t=target();t["hurs"]=100.
        good,blocked=generate([t],[donor()],47.0707,15.4395)
        if good:
            self.assertGreaterEqual(abs(good[0][2]["P92C_hurs_residual_pp"]),0)
            self.assertIn("hurs_joint_status",good[0][2])
    def test_multiple_source_candidates_stable_seed(self):
        donors=[donor(year=2019,day=10),donor(year=2020,day=11)]
        a,b=generate([target()],donors,47.0707,15.4395,7313)
        c,d=generate([target()],donors,47.0707,15.4395,7313)
        self.assertEqual(b,d)
        self.assertEqual([(x[0].vectors,x[2]["selected_donor_date"]) for x in a],
                         [(x[0].vectors,x[2]["selected_donor_date"]) for x in c])
if __name__=="__main__":unittest.main()
