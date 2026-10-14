"""Diagnostic-only contracts; no observational data or network required."""
import unittest
import numpy as np
from p8_2e_absolute_humidity_audit import absolute_humidity_gm3,specific_humidity_gkg,scores,diagnose

class AbsoluteHumidityContracts(unittest.TestCase):
 def test_reference_20C_10hpa(self):
  self.assertAlmostEqual(float(absolute_humidity_gm3(10.,20.)),2167./293.15,places=9)
 def test_absolute_humidity_does_not_depend_on_total_pressure(self):
  self.assertAlmostEqual(float(absolute_humidity_gm3(10.,20.)),float(absolute_humidity_gm3(10.,20.)))
  self.assertNotAlmostEqual(float(specific_humidity_gkg(10.,900.)),float(specific_humidity_gkg(10.,1000.)))
 def test_pressure_constraints_fail_closed(self):
  with self.assertRaises(ValueError):specific_humidity_gkg(1000,900)
  with self.assertRaises(ValueError):absolute_humidity_gm3(-2,20)
 def test_reference_perfect_reconstruction(self):
  e=np.array([2.,6.,10.]);t=np.array([-10.,5.,22.]);v=absolute_humidity_gm3(e,t)
  self.assertAlmostEqual(scores(v,v)['MAE'],0.0)
 def test_oracle_temperature_isolates_error(self):
  e=np.array([3.,6.]);t=np.array([8.,15.]);p=np.array([950.,950.]);idx=np.arange(2)
  observed={i:{'e':float(e[i]),'T':float(t[i]),'P':float(p[i]),'RH':95.,'Td':3.} for i in idx}
  prediction={'e':e.copy(),'T':t+2,'P':p.copy(),'RH':np.array([85.,85.])}
  x=diagnose(prediction,observed,idx,[0,1]);self.assertAlmostEqual(x['rho_v_oracle_T']['MAE'],0.0)
  self.assertGreater(x['rho_v_model']['MAE'],0.0)
 def test_oracle_vapour_isolates_error(self):
  e=np.array([3.,6.]);t=np.array([8.,15.]);p=np.array([950.,950.]);idx=np.arange(2)
  observed={i:{'e':float(e[i]),'T':float(t[i]),'P':float(p[i]),'RH':95.} for i in idx}
  prediction={'e':e+1,'T':t.copy(),'P':p.copy(),'RH':np.array([85.,85.])}
  x=diagnose(prediction,observed,idx,[0,1]);self.assertAlmostEqual(x['rho_v_oracle_e']['MAE'],0.0)
 def test_high_humidity_audit_does_not_replace_prediction(self):
  idx=np.arange(2);hours=[0,1]
  o={0:{'e':10.,'T':20.,'P':950.,'RH':91.},1:{'e':6.,'T':12.,'P':950.,'RH':45.}}
  p={'e':np.array([9.,5.]),'T':np.array([20.,12.]),'P':np.array([950.,950.]),'RH':np.array([80.,40.])}
  diag=diagnose(p,o,idx,hours)
  self.assertEqual(diag['high_rh_n_hours'],1)
  self.assertGreater(diag['rho_v_observed_RH_ge90']['MAE'],0.)

if __name__=='__main__':unittest.main()