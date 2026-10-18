import unittest
from p9_3b1_esgf_native_monthly_pressure_audit import EXACT
class NativePSSemantics(unittest.TestCase):
 def test_daily_ps_has_explicit_CMIP_table_day(self):
  self.assertEqual(EXACT["table_id"],"day")
 def test_orig_member(self):
  self.assertEqual(EXACT["member_id"],"r1i1p1f1")
 def test_not_model_variant_or_future(self):
  self.assertEqual(EXACT["source_id"],"CanESM5")
  self.assertEqual(EXACT["experiment_id"],"historical")
if __name__=="__main__":unittest.main()
