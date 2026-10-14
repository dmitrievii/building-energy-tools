import unittest
import numpy as np
from p8_2e_rh_attribution import esat,psychrometric_states,indicators,analyze,grouped

class RHComponents(unittest.TestCase):
 def inputs(self):
  return dict(mt=np.array([9.,13.,0.,12.]),me=np.array([10.,13.,5.,7.]),
              ot=np.array([10.,11.,2.,10.]),oe=np.array([11.,12.,6.,8.]),
              mp=np.full(4,990.),op=np.full(4,995.),
              rh=np.array([100*11/esat(10.),100*12/esat(11.),100*6/esat(2.),100*8/esat(10.)]))
 def test_observed_reconstruction_exact_ideal(self):
  z=psychrometric_states(**self.inputs())
  np.testing.assert_allclose(z['observed_T_observed_e'],self.inputs()['rh'])
 def test_model_equivalence_frozen_rh(self):
  a=self.inputs();z=psychrometric_states(**a)
  psychrometric_states(**a,model_rh=z['model_T_model_e'])
  with self.assertRaises(AssertionError):psychrometric_states(**a,model_rh=z['model_T_model_e']+1)
 def test_no_pressure_direct_effect(self):
  a=self.inputs();x=psychrometric_states(**a);a['mp']*=.95;a['op']*=1.02
  y=psychrometric_states(**a)
  for k in x:np.testing.assert_array_equal(x[k],y[k])
 def test_fix_temperature_when_only_temperature_wrong(self):
  a=self.inputs();a['me']=a['oe'].copy();a['rh']=100*a['oe']/esat(a['ot'])
  v,c=analyze(**a)
  self.assertAlmostEqual(v['observed_T_model_e']['MAE_pp'],0)
  self.assertAlmostEqual(v['model_T_observed_e']['MAE_pp'],v['model_T_model_e']['MAE_pp'])
 def test_fix_e_when_only_e_wrong(self):
  a=self.inputs();a['mt']=a['ot'].copy();a['rh']=100*a['oe']/esat(a['ot'])
  v,c=analyze(**a)
  self.assertAlmostEqual(v['model_T_observed_e']['MAE_pp'],0)
 def test_symmetric_MAE_decomposition_exact(self):
  v,c=analyze(**self.inputs())
  self.assertAlmostEqual(c['symmetric_T_MAE_contribution_pp']+c['symmetric_e_MAE_contribution_pp'],c['model_rh_mae_pp']-c['measured_eT_vs_published_RH_mae_pp'])
 def test_counterfactual_not_clipped(self):
  a=self.inputs();a['me'][:]=40.;a['mp'][:]=1000.
  v,c=analyze(**a)
  self.assertGreater(v['model_T_model_e']['n_supersaturated_counterfactual'],0)
 def test_events_confusion(self):
  a=indicators(np.array([91,91,80,80]),np.array([91,80,91,80]))
  self.assertEqual((a['tp'],a['fp'],a['fn']),(1,1,1))
  self.assertAlmostEqual(a['recall'],.5)
 def test_grouped_counts_weighted_and_aggregated(self):
  z=[]
  for sid,nn in [('A',2),('B',3)]:
   z.append(dict(year=2019,method='X',variant='model_T_model_e',site=sid,n_hours=nn,
      tp=nn,fp=0,fn=0,obs_count=nn,pred_count=nn,
      sum_absolute_error=nn,sum_square_error=nn,sum_signed_error=nn,n_supersaturated_counterfactual=0))
  r=grouped(z)[0]
  self.assertEqual(r['n_hours'],5);self.assertEqual(r['n_sites'],2)
  self.assertEqual(r['f1'],1)
 def test_pairing_rejected(self):
  a=self.inputs();a['mt']=np.ones(5)
  with self.assertRaises(ValueError):psychrometric_states(**a)

if __name__=='__main__':unittest.main()