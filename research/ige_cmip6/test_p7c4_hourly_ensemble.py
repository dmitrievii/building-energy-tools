"""P7C.4 public synthetic/fail-closed unit contracts; no licensed Meteonorm records."""
import csv,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import p7c4_hourly_ensemble as m

class Contract(unittest.TestCase):
 def valid_reg(self,model='CanESM5',win='ssp245-2040-2059'):
  return {(model,win,i):{'model':model,'window':win,'month':str(i),'tas_delta_C':'2', 'dtr_ratio':'1.05','huss_ratio':'1.1','pr_ratio':'1','ghi_ratio':'1.02','rlds_ratio':'1','wind_ratio':'1'} for i in range(1,13)}
 def source(self,model='CanESM5',win='ssp245-2040-2059',missing_huss=False):
  h=[{'month':m,'tas_c':10.,'huss':None if missing_huss else .005} for m in range(1,13)]
  return {model+'_'+m.HIST:(h,{}),model+'_'+win:(h,{})}
 def test_model_registry_count(self):
  self.assertEqual(len(m.MODELS),8);self.assertEqual(len(m.WINDOWS),4)
 def test_model_member_not_ensemble_blend(self):
  self.assertEqual(len(set(m.MODELS)),8);self.assertIn('CanESM5',m.MODELS)
 def test_humidity_source_mandatory(self):
  self.assertFalse(m.can_morph_moisture(self.source(missing_huss=True),'CanESM5','ssp245-2040-2059'))
 def test_humidity_source_accepted(self):
  self.assertTrue(m.can_morph_moisture(self.source(),'CanESM5','ssp245-2040-2059'))
 def test_cannot_replace_missing_huss_with_neutral(self):
  reg=self.valid_reg();reg[('CanESM5','ssp245-2040-2059',4)]['huss_ratio']=''
  with self.assertRaisesRegex(ValueError,'without native GCM huss'):
   m.build_signal('CanESM5','ssp245-2040-2059',self.source(),reg)
 def test_climate_monthly_temporal_quantile_sources(self):
  sig=m.build_signal('CanESM5','ssp245-2040-2059',self.source(),self.valid_reg())
  self.assertEqual(set(sig),set(range(1,13)));self.assertEqual(sig[2]['T_mean_delta_c'],2.)
  self.assertEqual(sig[7]['future_daily_tas_sorted'],[10.])
 def test_monthly_q_ratio_identical_to_source(self):
  s=m.build_signal('CanESM5','ssp245-2040-2059',self.source(),self.valid_reg())
  self.assertEqual(m.climate_ratio(s),{i:1.1 for i in range(1,13)})
 def test_excess_solar_multiplier_rejected(self):
  r=self.valid_reg();r[('CanESM5','ssp245-2040-2059',1)]['ghi_ratio']='1.81'
  with self.assertRaisesRegex(ValueError,'range'):
   m.build_signal('CanESM5','ssp245-2040-2059',self.source(),r)
 def test_excess_humidity_multiplier_rejected(self):
  r=self.valid_reg();r[('CanESM5','ssp245-2040-2059',1)]['huss_ratio']='4'
  with self.assertRaisesRegex(ValueError,'range'):
   m.build_signal('CanESM5','ssp245-2040-2059',self.source(),r)
 def test_source_month_absent_rejected(self):
  r=self.valid_reg();del r[('CanESM5','ssp245-2040-2059',10)]
  with self.assertRaises(KeyError):m.build_signal('CanESM5','ssp245-2040-2059',self.source(),r)
 def test_source_sha_manifest_present(self):
  j=json.loads((Path(__file__).parent/'p7c3_expected_daily_source_shas.json').read_text())
  self.assertEqual(len(j['source_sha256']),40)
  self.assertTrue(all(len(h)==64 for h in j['source_sha256'].values()))
 def test_missing_original_archive_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):m.verify_daily_sources(d,Path(__file__).parent/'p7c3_expected_daily_source_shas.json','/this/not-a-monthly.csv')
 def test_baseline_provenance_is_required(self):
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/'sample.epw';f.write_text('invalid')
   p=Path(d)/'prov.json';p.write_text(json.dumps({'provider':'Meteonorm','original_filename':'sample.epw','sha256':'incorrect','user_authorized_research_use':True}))
   with self.assertRaisesRegex(ValueError,'provenance mismatch'):m.validate_baseline(f,p)
 def test_output_fields_preserve_source_identities(self):
  self.assertEqual(set(m.P7C4_FIELDS),{6,7,8,12,13,14,15,21,33})
  self.assertNotIn(20,m.P7C4_FIELDS)
 def test_reject_incomplete_hourly_data(self):
  with self.assertRaisesRegex(ValueError,'Incomplete EPW'):
   m.verify_hourly([],[],[],[],{}, {},'CanESM5','ssp245-2040-2059')

if __name__=='__main__':unittest.main()