import datetime as dt,math,random,statistics,unittest
from p9_3b3_joint_t_p_q_physical_projection import (
 project_state,conservative_RH_bounds,_bounded_allocation,reconstruct_day)
from p9_2b_cmip6_daily_joint_regime_solver import q_of_e,e_of_q,qsat,sat_pa

class JointTPQPhysicalClosure(unittest.TestCase):
 def setUp(self):
  self.T=[15.+7*math.sin(2*math.pi*i/24) for i in range(24)]
  self.P=[96000.+300*math.sin(2*math.pi*i/24) for i in range(24)]
  self.q0=[.007+.0005*math.cos(2*math.pi*i/24) for i in range(24)]
 def test_exact_huss_mass_and_pressure_T_immutability(self):
  a=project_state(self.T,self.P,self.q0,.0075,45.)
  self.assertEqual(a["status"],"C1_HARD_T_P_HUSS_PHYSICALLY_CLOSED")
  hourly=a["hourly"]
  self.assertEqual(hourly["pressure_Pa"],self.P)
  self.assertEqual(hourly["temperature_C"],self.T)
  self.assertAlmostEqual(statistics.fmean(hourly["specific_humidity_kgkg"]),.0075,places=10)
  self.assertTrue(all(0<=r<=100 for r in hourly["relative_humidity_percent"]))
  self.assertTrue(all(d<=t for d,t in zip(hourly["dewpoint_C"],self.T)))
  self.assertAlmostEqual(a["ledger"]["native_huss_residual_kgkg"],0.,places=10)
 def test_original_source_hurs_never_silently_fitted(self):
  a=project_state(self.T,self.P,self.q0,.007,2.)
  self.assertGreater(abs(a["ledger"]["native_hurs_residual_percentage_points"]),3)
  self.assertTrue(a["ledger"]["native_daily_hurs_is_NOT_an_imposed_hard_constraint"])
  self.assertTrue(a["ledger"]["native_hurs_proven_outside_conservative_bound"])
 def test_unattainable_huss_C2_must_not_create_acceptable_hourly(self):
  a=project_state(self.T,self.P,self.q0,.030,75.)
  self.assertEqual(a["status"],"C2_FAIL_CLOSED_DIAGNOSTIC_ONLY")
  self.assertIsNone(a["hourly"])
  self.assertGreater(a["ledger"]["native_huss_unavoidable_absolute_daily_mean_correction_kgkg"],.001)
  self.assertFalse(a["ledger"]["C1_hard_native_water_mass_conserved"])
 def test_pressure_changes_qsat_not_fitted(self):
  a=project_state(self.T,self.P,self.q0,.007,60.)
  b=project_state(self.T,[p-10000 for p in self.P],self.q0,.007,60.)
  self.assertEqual(a["hourly"]["pressure_Pa"],self.P)
  self.assertEqual(b["hourly"]["pressure_Pa"],[p-10000 for p in self.P])
  self.assertNotAlmostEqual(a["ledger"]["physical_water_mass_capacity_daily_mean_kgkg"],
                            b["ledger"]["physical_water_mass_capacity_daily_mean_kgkg"],places=5)
 def test_projection_is_minimum_distance_against_two_hour_feasible_transfer(self):
  a=project_state(self.T,self.P,self.q0,.0075,50.)
  q=a["hourly"]["specific_humidity_kgkg"]
  lo=[q_of_e(sat_pa(-90.)*1.0000001,p) for p in self.P]
  hi=[qsat(t,p)*(1-2e-9) for t,p in zip(self.T,self.P)]
  cost=lambda x:sum((u-v)**2 for u,v in zip(x,self.q0))
  base=cost(q)
  checked=0
  for i in range(24):
   for j in range(24):
    if i==j:continue
    amount=min(1e-5,hi[i]-q[i],q[j]-lo[j])
    if amount<=1e-11:continue
    trial=q.copy();trial[i]+=amount;trial[j]-=amount
    self.assertGreaterEqual(cost(trial)+1e-13,base)
    checked+=1
  self.assertGreater(checked,30)
 def test_rh_conservative_interval_includes_random_feasible_q(self):
  lo=[q_of_e(sat_pa(-90)*1.0000001,p) for p in self.P]
  hi=[qsat(t,p)*(1-2e-9) for t,p in zip(self.T,self.P)]
  total=.0075*24
  low,high=conservative_RH_bounds(self.T,self.P,lo,hi,total)
  self.assertLess(low,high)
  rng=random.Random(4201)
  for _ in range(80):
   q0=[rng.uniform(l,h) for l,h in zip(lo,hi)]
   # Force exact total using the UNIQUE capped Euclidean projection through the public API.
   a=project_state(self.T,self.P,q0,.0075,60.)
   rh=statistics.fmean(a["hourly"]["relative_humidity_percent"])
   self.assertGreaterEqual(rh,low-1e-6)
   self.assertLessEqual(rh,high+1e-6)
 def test_boundary_target_cap_exact(self):
  hi=[qsat(t,p)*(1-2e-9) for t,p in zip(self.T,self.P)]
  a=project_state(self.T,self.P,self.q0,statistics.fmean(hi),99.)
  self.assertEqual(a["status"],"C1_HARD_T_P_HUSS_PHYSICALLY_CLOSED")
  self.assertAlmostEqual(statistics.fmean(a["hourly"]["specific_humidity_kgkg"]),statistics.fmean(hi),places=10)
 def test_infeasible_below_stable_floor_logs_not_hourly(self):
  a=project_state(self.T,self.P,self.q0,1.e-10,50.)
  self.assertIsNone(a["hourly"])
  self.assertIn("BELOW_FIXED_T_P",a["ledger"]["reason"])
 def test_bad_or_unacknowledged_pressure_source_rejected(self):
  with self.assertRaisesRegex(ValueError,"PROVENANCE"):
   project_state(self.T,self.P,self.q0,.007,60.,"")
  with self.assertRaisesRegex(ValueError,"DOMAIN"):
   project_state(self.T,[-10.]*24,self.q0,.007,60.)
 def test_exact_q_and_dewpoint_consistency(self):
  a=project_state(self.T,self.P,self.q0,.007,55.)
  for t,p,q,dp,rh in zip(self.T,self.P,a["hourly"]["specific_humidity_kgkg"],
     a["hourly"]["dewpoint_C"],a["hourly"]["relative_humidity_percent"]):
   self.assertAlmostEqual(q_of_e(sat_pa(dp),p),q,delta=1e-9)
   self.assertAlmostEqual(rh,100*e_of_q(q,p)/sat_pa(t),places=9)
if __name__=="__main__":unittest.main()
