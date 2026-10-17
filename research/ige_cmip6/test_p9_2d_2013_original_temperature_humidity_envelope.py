import datetime as dt,math,unittest
from p9_2d_2013_original_temperature_humidity_envelope import (
    qsat_constant_pressure,convex_temperature_envelope,pressure_threshold_native_huss
)
def fake():
 return {"tas_c":10.,"tasmin_c":0.,"tasmax_c":20.,"huss":.007,"hurs":70}
class PressureDailyPhysical(unittest.TestCase):
 def test_qsat_decreases_with_pressure(self):
  self.assertGreater(qsat_constant_pressure(15,95000),qsat_constant_pressure(15,100000))
 def test_extreme_envelope_above_mean_qsat(self):
  r=fake()
  self.assertGreater(convex_temperature_envelope(r,100000),qsat_constant_pressure(10,100000))
 def test_threshold_monotone(self):
  x=pressure_threshold_native_huss(fake())
  self.assertIn("status",x)
 def test_incompatible_mean_extremes_strict_block(self):
  r=fake();r["tas_c"]=25
  with self.assertRaisesRegex(ValueError,"INVALID_NATIVE_T"):
   convex_temperature_envelope(r,100000)
 def test_no_hidden_grid_pressure_calibration(self):
  x=fake()
  a=convex_temperature_envelope(x,97000)
  b=convex_temperature_envelope(x,100000)
  self.assertNotEqual(a,b)
if __name__=="__main__":unittest.main()
