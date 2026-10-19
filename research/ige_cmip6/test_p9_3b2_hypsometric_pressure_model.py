import unittest,math
from p9_3b2_hypsometric_pressure_model import correct_pressure,virtual_T_kelvin,evaluate_methods
class PressurePhysical(unittest.TestCase):
 def test_zero_height_identity_both_methods(self):
  for m in ("ISOTHERMAL_VIRTUAL_T","FIXED_LAPSE_0065_SENSITIVITY"):
   self.assertAlmostEqual(correct_pressure(955.,10.,4.,700.,700.,m),955.,places=9)
 def test_higher_station_has_lower_pressure(self):
  got=evaluate_methods(950,10,3,1500,800)
  self.assertLess(got["B1_FIXED_HYPSOMETRIC_ISOTHERMAL_hPa"],950)
  self.assertLess(got["B2_FIXED_LAPSE_SENSITIVITY_hPa"],950)
 def test_lower_station_has_higher_pressure(self):
  self.assertGreater(correct_pressure(920,10,3,500,1500,"ISOTHERMAL_VIRTUAL_T"),920)
 def test_humidity_increases_virtual_temperature(self):
  self.assertGreater(virtual_T_kelvin(20,15,990),virtual_T_kelvin(20,-10,990))
 def test_both_models_agree_near_zero_height(self):
  a=correct_pressure(930,5,0,905,900,"ISOTHERMAL_VIRTUAL_T")
  b=correct_pressure(930,5,0,905,900,"FIXED_LAPSE_0065_SENSITIVITY")
  self.assertLess(abs(a-b),.001)
 def test_very_large_delta_height_blocks(self):
  with self.assertRaisesRegex(ValueError,"VERTICAL_EXTRAPOLATION"):
   correct_pressure(900,5,-2,4500,100,"ISOTHERMAL_VIRTUAL_T")
 def test_sea_level_pressure_cannot_replace_station_pressure(self):
  with self.assertRaisesRegex(ValueError,"UNREGISTERED"):
   correct_pressure(990,5,0,750,900,"QFF_SEA_LEVEL")
 def test_pressure_gross_physics(self):
  with self.assertRaisesRegex(ValueError,"OUT_OF_RANGE"):
   correct_pressure(1600,5,-2,600,900,"ISOTHERMAL_VIRTUAL_T")
if __name__=="__main__":unittest.main()
