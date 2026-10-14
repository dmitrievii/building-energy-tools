"""Unit physics/nonleakage regression for P8.2C; no network required."""
import unittest,datetime,math
import numpy as np
from p8_2c_hourly import (reconcile_monthly,synthesize,score,capacity,parse_hourly,metric_rows)
from p8_2a_humidity import esat_water_hpa

class Contracts(unittest.TestCase):
 def test_exact_monthly_mean_all_models(self):
  t=np.array([5,0,25,15.,-8,10]*120);p=np.full(len(t),1000.)
  donor=np.linspace(3,18,len(t));m=synthesize(t,p,4.,donor)
  for a in m.values():
   self.assertAlmostEqual(a['e'].mean(),4.,places=8)
   self.assertTrue(np.all(a['e']<=capacity(t,p)+1e-10))
   self.assertTrue(np.all(a['RH']<=100+1e-10))
   self.assertTrue(np.all(a['w']>0))
   self.assertTrue(np.all(a['rho_v']>0))
   self.assertTrue(np.all(a['Td']<=t+1e-7))
 def test_infeasible_mean_does_not_clip_silently(self):
  with self.assertRaisesRegex(ValueError,'INFEASIBLE'):reconcile_monthly(20,np.ones(25),np.zeros(25),np.full(25,970.))
 def test_pressure_saturation_enforced(self):
  t=np.full(20,50.);p=np.full(20,500.)
  a=reconcile_monthly(25.,np.ones(20),t,p)
  self.assertLess(a.max(),500.)
 def test_target_hourly_humidity_not_an_input(self):
  x=np.array([2,4,8.,15]);p=np.full(4,990.);d=np.array([3.,4,6,8]);a=synthesize(x,p,4,d)
  self.assertTrue(set(a)=={'constant_e','donor_shape_half','donor_shape_full'})
 def test_donor_alignment_mandatory(self):
  x=[10.,10.];p=[1000.,1000.]
  with self.assertRaisesRegex(ValueError,'unaligned'):synthesize(x,p,3,[2,4],[1,2],[2,1])
 def test_invalid_shape(self):
  with self.assertRaisesRegex(ValueError,'Nonpositive'):synthesize([20,10],[1000,1000],3,[1,0])
 def test_same_month_zero_donor_shape_equals_constant(self):
  t=np.array([1.,10,20,-5]);p=np.full(4,1000.)
  v=synthesize(t,p,3.,[5]*4)
  np.testing.assert_allclose(v['constant_e']['e'],v['donor_shape_full']['e'])
 def test_source_duplicate_timestamp_fail_closed(self):
  h='station_abbr;reference_timestamp;tre200h0;prestah0;pva200h0;ure200h0;tde200h0\n'
  s='ABO;01.01.2019 00:00;5;950;6;60;1\n'
  with self.assertRaisesRegex(ValueError,'Duplicate'):parse_hourly((h+s+s).encode(),'ABO',2019,{(2019,1)})
 def test_score_no_unpaired_values(self):
  with self.assertRaisesRegex(ValueError,'Unpaired'):score([1,2],[1])
 def test_fixed_matched_counts_across_all_methods(self):
  idx=[datetime.datetime(2019,1,1,i) for i in range(4)]
  obs={d:{'site':'ABO','e':3.,'RH':65.,'Td':-3.} for d in idx}
  T=np.full(4,4.);P=np.full(4,1000.)
  m=synthesize(T,P,3.,[3.,4.,5.,6.],idx,idx)
  rows,clos=metric_rows("ABO",obs,2019,1,idx,m,T,P,3.)
  self.assertEqual(len(rows),9);self.assertEqual(len(clos),3)
  self.assertEqual({r['n_hours'] for r in rows},{4})
 def test_no_rh_clip_from_independent_prediction(self):
  t=np.array([-5.,0.,5]);p=np.full(3,900.)
  e=reconcile_monthly(4,np.array([3.,1.,1.]),t,p)
  self.assertTrue(np.all(100*e/np.array([esat_water_hpa(x) for x in t])<=100.00000001))

if __name__=='__main__':unittest.main()