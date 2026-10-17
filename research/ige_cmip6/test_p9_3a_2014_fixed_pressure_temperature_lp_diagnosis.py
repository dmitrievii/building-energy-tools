"""Pure numerical LP upper-bounds, no measured station weather."""
import unittest
from test_p9_2b_cmip6_daily_joint_regimes import donor,target
from p9_3a_2014_fixed_pressure_temperature_lp_diagnosis import chord_upper_q_mean
class P93ACapacityLP(unittest.TestCase):
 def test_upper_chord_always_above_original_baseline(self):
  got=chord_upper_q_mean(donor(),target())
  self.assertEqual(got["status"],"CERTIFIED_UPPER_BOUND_UNDER_FIXED_DONOR_PRESSURE")
  self.assertGreaterEqual(got["LP_upper_mean_qsat_kgkg"],
                          got["baseline_mean_qsat_kgkg"]-1e-10)
 def test_source_q_above_even_LP_upper_is_certifiably_impossible_within_bounds(self):
  t=target();t["huss"]=.08
  got=chord_upper_q_mean(donor(),t)
  self.assertIs(type(got["huss_exceeds_proved_LP_temperature_pressure_capacity"]),bool)
  self.assertTrue(got["huss_exceeds_proved_LP_temperature_pressure_capacity"])
 def test_original_synthetic_target_q_feasible_stays_not_proved_impossible(self):
  got=chord_upper_q_mean(donor(),target())
  self.assertIs(type(got["huss_exceeds_proved_LP_temperature_pressure_capacity"]),bool)
  self.assertFalse(got["huss_exceeds_proved_LP_temperature_pressure_capacity"])
if __name__=="__main__":unittest.main()
