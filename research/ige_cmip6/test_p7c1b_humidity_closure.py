import json,math,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from p7c1b_humidity_closure import minimum_adjustment_projection,load_monthly_ratios,check_baseline_provenance

class P7C1BContracts(unittest.TestCase):
 def test_no_saturation_preserves_old_series(self):
  q=[.003,.005,.006];self.assertEqual([round(x,12) for x in minimum_adjustment_projection(q,[.001]*3,[.02]*3)],q)
 def test_one_hour_over_cap_reallocates_without_loss(self):
  q=[.009,.004,.004];v=minimum_adjustment_projection(q,[.001]*3,[.006,.02,.02]);
  self.assertAlmostEqual(sum(q),sum(v),places=12);self.assertLessEqual(v[0],.006+1e-12)
  self.assertAlmostEqual(v[1],v[2],places=12)
 def test_lower_bound_violation_redistributes(self):
  q=[.00001,.004,.004];v=minimum_adjustment_projection(q,[.001]*3,[.02]*3)
  self.assertAlmostEqual(v[0],.001,places=9);self.assertAlmostEqual(sum(q),sum(v),places=12)
 def test_capacity_insufficient_fails_closed(self):
  with self.assertRaisesRegex(ValueError,'outside physically attainable'):
   minimum_adjustment_projection([.01,.01],[.001]*2,[.009]*2)
 def test_insufficient_very_dry_target_fails_closed(self):
  with self.assertRaisesRegex(ValueError,'outside physically attainable'):
   minimum_adjustment_projection([.0001,.0001],[.001]*2,[.02]*2)
 def test_bad_or_nan_values_fail(self):
  for q in [[math.nan,.004],[.004,-.1]]:
   with self.assertRaises(ValueError):minimum_adjustment_projection(q,[.001]*2,[.02]*2)
 def test_mismatched_dimensions_fail(self):
  with self.assertRaises(ValueError):minimum_adjustment_projection([.003,.004],[.001],[.02]*2)
 def test_no_provenance_cannot_claim_real_contemporary(self):
  with self.assertRaisesRegex(ValueError,'Original contemporary EPW provenance is required'):
   from p7c1b_humidity_closure import check_baseline_provenance
   from unittest.mock import patch
   with patch('p7c1b_humidity_closure.read_epw',return_value=([],[],{'baseline_epw_sha256':'abc'})):
    check_baseline_provenance('/tmp/example.epw',None,True)
 def test_sha_provenance_mismatch_fails(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as p:
   f=Path(p)/'provenance.json';f.write_text(json.dumps({'original_filename':'orig.epw','provider':'Meteonorm 8','source_description':'user supplied','sha256':'wrong','user_authorized_research_use':True}))
   with patch('p7c1b_humidity_closure.read_epw',return_value=([],[],{'baseline_epw_sha256':'abc'})):
    with self.assertRaisesRegex(ValueError,'SHA/name provenance mismatch'):
     check_baseline_provenance('/tmp/orig.epw',f,True)
 def test_invalid_month_ratios_fail(self):
  with tempfile.TemporaryDirectory() as p:
   f=Path(p)/'month.csv';f.write_text('month,specific_humidity_ratio\n1,1.4\n')
   with self.assertRaisesRegex(ValueError,'twelve'):load_monthly_ratios(f)
 def test_permuted_month_signal_is_supported(self):
  with tempfile.TemporaryDirectory() as p:
   f=Path(p)/'month.csv';f.write_text('month,specific_humidity_ratio\n'+''.join(f'{m},1.2\n' for m in reversed(range(1,13))))
   self.assertEqual(len(load_monthly_ratios(f)),12)
 def test_negative_q_rejected(self):
  with self.assertRaises(ValueError):minimum_adjustment_projection([-.01],[.001],[.02])
if __name__=='__main__':unittest.main()