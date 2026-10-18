import unittest
from p9_3b1_canesm5_ps_discovery import qualify_rows,MATCH
class CanESM5PressureIdentity(unittest.TestCase):
 def test_exact_all_keys(self):
  r={**MATCH,"zstore":"gs://cmip6/CMIP6/CMIP/CCCma/CanESM5/historical/r1i1p1f1/day/ps/gn/v1/"}
  exact,alt=qualify_rows([r])
  self.assertEqual(len(exact),1)
 def test_wrong_grid_blocked(self):
  r={**MATCH,"zstore":"gs://cmip6/CMIP6/CMIP/CCCma/CanESM5/historical/r1i1p1f1/day/ps/gr/v1/","grid_label":"gr"}
  self.assertEqual(qualify_rows([r])[0],[])
 def test_analog_model_not_accepted(self):
  r={**MATCH,"zstore":"gs://cmip6/CMIP6/CMIP/CCCma/CanESM5-CanOE/historical/r1i1p2f1/day/ps/gn/v1/","source_id":"CanESM5-CanOE"}
  self.assertEqual(qualify_rows([r])[0],[])
 def test_wrong_member_not_accepted(self):
  r={**MATCH,"zstore":"gs://cmip6/CMIP6/CMIP/CCCma/CanESM5/historical/r2i1p1f1/day/ps/gn/v1/","member_id":"r2i1p1f1"}
  self.assertEqual(qualify_rows([r])[0],[])
if __name__=="__main__":unittest.main()
