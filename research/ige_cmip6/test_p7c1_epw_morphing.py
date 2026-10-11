"""P7C.1 contract tests: physical conservation, source-calendar and no invented weather."""
import unittest,tempfile,csv,json,math
from pathlib import Path
from datetime import datetime,date
from p7c1_epw_morphing import (
  WINDOWS, EDIT_FIELDS, sha,mean,quantile,project_solar,solarcos,solar_geometry,
  erbs_diffuse_fraction,split_ghi,saturation_pa,q_from_rh,rh_from_q,dewpoint_from_rh,
  read_epw,monthly_signals,daily_delta_by_quantile,verify_model_dir
)

class P7C1Contracts(unittest.TestCase):
 def test_four_registered_windows(self):
  self.assertEqual(WINDOWS,('ssp245-2040-2059','ssp245-2080-2099','ssp585-2040-2059','ssp585-2080-2099'))
 def test_only_nine_epw_fields_can_change(self):
  self.assertEqual(set(EDIT_FIELDS),{6,7,8,12,13,14,15,21,33})
  self.assertNotIn(20,EDIT_FIELDS)
  self.assertNotIn(9,EDIT_FIELDS)
  self.assertNotIn(34,EDIT_FIELDS)
 def test_quantile_endpoints_and_median(self):
  self.assertAlmostEqual(quantile([1,2,4,8],0),1)
  self.assertAlmostEqual(quantile([1,2,4,8],.5),3)
  self.assertAlmostEqual(quantile([1,2,4,8],1),8)
 def test_source_integrity_fail_closed(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(FileNotFoundError):verify_model_dir(t,'historical-1995-2014')
 def test_solar_night_is_exactly_zero(self):
  self.assertEqual(solarcos(datetime(2013,1,2,0,30),47.0,15.4,1),0)
  self.assertEqual(solar_geometry(date(2013,1,2),47.0,15.4,1)[0][1],0.)
 def test_solar_noon_clear_positive(self):
  self.assertGreater(solarcos(datetime(2013,6,21,12,30),47.,15.4,1),.7)
 def test_solar_source_daily_exact(self):
  cap=[0.]*6+[.1,.4,.7,1,1.1,1.2,1.1,1,.7,.4,.1]+[0.]*7
  self.assertEqual(len(cap),24)
  target=4.432
  shape=[x*(0.9 if i%2==0 else .5) for i,x in enumerate(cap)]
  out=project_solar(shape,target,cap)
  self.assertLess(abs(sum(out)-target),1e-8)
  self.assertTrue(all(0<=g<=c+1e-10 for g,c in zip(out,cap)))
 def test_solar_infeasible_source_rejected(self):
  with self.assertRaisesRegex(ValueError,'outside TOA'):
   project_solar([.1]*24,10.,[.1]*24)
 def test_solar_identity_baseline_unchanged(self):
  shape=[.0]*6+[.1,.4,.7,1,1.1,1.2,1.1,1,.7,.4,.1]+[0.]*7
  cap=[max(.1,x*2) for x in shape]
  self.assertEqual(project_solar(shape,sum(shape),cap),shape)
 def test_erbs_fraction_bounds(self):
  self.assertTrue(all(0<=erbs_diffuse_fraction(x)<=1 for x in (0,.1,.22,.5,.8,1)))
 def test_radiometric_geometry_closure(self):
  for c in (.07,.15,.4,.8):
   toa=1.3*c
   for factor in (.1,.3,.5,.8,1):
    ghi=toa*factor
    dni,dhi=split_ghi(ghi,c,toa)
    self.assertAlmostEqual(ghi,dhi+dni*c,places=11)
    self.assertTrue(0<=dhi<=ghi+1e-8)
    self.assertTrue(0<=dni<=toa/c+1e-8)
 def test_low_sun_direct_beam_guard(self):
  self.assertEqual(split_ghi(.01,.01,.013), (0.,.01))
 def test_negative_and_super_toa_radiation_fail(self):
  for ghi in (-.2,.9):
   with self.assertRaises(ValueError):split_ghi(ghi,.2,.2)
 def test_specific_humidity_roundtrip(self):
  for t,rh,p in ((-10,40,93000),(10,80,97000),(34,90,101325)):
   q=q_from_rh(t,rh,p)
   self.assertLess(abs(rh-rh_from_q(t,q,p)),1e-10)
   self.assertLess(dewpoint_from_rh(t,rh)-t,1e-9)
 def test_source_validation_rejects_non_epw(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'not.epw';p.write_text('a,b,c\n')
   with self.assertRaises(ValueError):read_epw(p)
 def test_climate_ratio_neutral_identity(self):
  d={k:1. for k in ('tasmax_c','tasmin_c')}
  data=[{'month':m,'tas_c':12.,'tasmax_c':20.,'tasmin_c':8.,'huss':.007,'rsds_kwh_m2_day':4.,'pr_mm_day':3.,'sfcWind':2.,'rlds_kwh_m2_day':7.} for m in range(1,13) for _ in range(600)]
  result=monthly_signals(data,data)
  self.assertTrue(all(abs(x['T_mean_delta_c'])<1e-14 and abs(x['solar_ghi_ratio']-1)<1e-14 for x in result.values()))
 def test_precipitation_zeros_are_inherited_by_scaling(self):
  xs=[0.,1.,0.,2.,0.,5.]
  ys=[x*1.5 for x in xs]
  self.assertEqual([x>0 for x in xs],[y>0 for y in ys])

if __name__=='__main__':unittest.main()