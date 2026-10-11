"""P7B.3E source-science, cap disagreement, Erbs and frozen 8-GCM contracts."""
import csv,json,tempfile,unittest,math
from datetime import date
from pathlib import Path
from p7b3e_multigcm_radiometric_closure import (
 MODELS,WINDOW,FLOORS,source_dirs,original_source,erbs_fraction,
 reconstruct_components,cap_profile,solar_vectors,compute_model
)
from p7b3e_distant_sites import SITES,check_original_metadata

class OriginalPhysics(unittest.TestCase):
 def test_all_eight_model_names_are_unique(self):
  self.assertEqual(len(MODELS),8)
  self.assertEqual(len(set(MODELS)),8)
 def test_predeclared_solar_cap_sensitivity(self):
  self.assertEqual(FLOORS,(.45,.65,.85))
  day=solar_vectors(date(2013,6,1),46.875,15.375)
  self.assertEqual(len(day),24)
  for floor in FLOORS:
   caps=cap_profile(day,floor)
   self.assertTrue(all(0<=x<=t+1e-12 for x,(_,t,_) in zip(caps,day)))
   self.assertTrue(sum(caps)>0)
  self.assertTrue(all(a<=b+1e-12 for a,b in zip(cap_profile(day,.45),cap_profile(day,.85))))
 def test_bad_cap_is_rejected(self):
  with self.assertRaises(ValueError): cap_profile(solar_vectors(date(2013,6,1),47,15),.61)
 def test_hourly_physics_solar_at_night(self):
  self.assertEqual(reconstruct_components(0,0,0),(0.,0.,0.))
 def test_negative_or_more_than_toa_fail(self):
  for vals in ((-0.01,.1,.5),(.2,.1,.5),(.1,.2,1.1)):
   with self.subTest(vals=vals):
    with self.assertRaises(ValueError): reconstruct_components(*vals)
 def test_low_sun_dni_guard(self):
  self.assertEqual(reconstruct_components(.01,.1,.05),(.01,0.,0.))
 def test_erbs_fraction_is_bounded(self):
  for v in [-1,0,.05,.22,.22001,.4,.8,.8001,1,2]:
   self.assertGreaterEqual(erbs_fraction(v),0)
   self.assertLessEqual(erbs_fraction(v),1)
 def test_all_radiometric_component_identities(self):
  for cos in (.065,.1,.25,.5,.85):
   for kt in (.01,.15,.22,.4,.6,.8,.95,1):
    toa=1.3*cos
    ghi=toa*kt
    dhi,dni,err=reconstruct_components(ghi,toa,cos)
    self.assertAlmostEqual(ghi,dhi+dni*cos,places=12)
    self.assertLessEqual(dni,1.3+1e-9)
    self.assertTrue(0<=dhi<=ghi+1e-12)
    self.assertLess(err,1e-10)
 def test_source_folder_names_no_false_access_reuse(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   p=root/f'ige-p6-access-{WINDOW}'
   p.mkdir();(p/'quality_report.json').write_text('{}')
   with self.assertRaisesRegex(ValueError,'missing or ambiguous'): source_dirs(root)
 def test_invalid_original_provenance_blocks(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)
   (p/'quality_report.json').write_text(json.dumps({'status':'FAIL','model':'CanESM5'}))
   (p/'source_provenance.json').write_text(json.dumps({'status':'PASS','model':'CanESM5'}))
   with self.assertRaisesRegex(ValueError,'QA/provenance'):original_source(p,'CanESM5')
 def test_recorded_new_geographies_are_not_graz_aliases(self):
  self.assertNotIn(30,SITES)
  self.assertNotIn(16412,SITES)
  self.assertGreaterEqual(len(SITES),4)
  self.assertGreater(max(v[3] for v in SITES.values())-min(v[3] for v in SITES.values()),1000)
 def test_distant_site_source_metadata_fail_closed(self):
  with self.assertRaisesRegex(ValueError,'metadata incompatible'):
   check_original_metadata({'parameters':[],'stations':[]})
 def test_provider_null_key_legend_entry_must_not_raise_typeerror(self):
  from p7b3e_distant_sites import QUALITY
  metadata={'parameters':[{'name':'cglo','unit':'W/m²'},{'name':'cglo_flag'}],
            'code_lists':{'q21':[{'key':None,'value':'header'}]+
                          [{'key':k,'value':str(k)} for k in sorted(set(QUALITY)|{0})]},
            'stations':[]}
  # The source is still invalid (stations absent), but must reach the
  # fail-closed site-coverage contract, not fail on int(None).
  with self.assertRaisesRegex(ValueError,'missing original provider site'):
   check_original_metadata(metadata)

if __name__=='__main__':unittest.main()