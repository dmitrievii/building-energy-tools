"""P8.2E temperature-bias posthoc contracts; synthetic only, no network."""
import unittest,datetime as dt
import numpy as np
from p8_2e_temperature_bias_audit import masks,summer_winter,cet_daypart,summarize,score_site,combined

class TemperatureBiasAuditContracts(unittest.TestCase):
 def test_sign_positive_means_too_warm(self):
  s=summarize(np.array([True,True]),np.array([1,3]),np.array([-.2,.4]),np.array([5,5]),np.array([6,8]))
  self.assertAlmostEqual(s['T_bias_C'],2)
  self.assertAlmostEqual(s['T_MAE_C'],2)
 def test_wet_vs_missed_condition(self):
  m=masks([95,92,70,85],[88,91,97,79]);self.assertEqual(list(np.flatnonzero(m['missed_wet_ge90'])),[0]);self.assertEqual(m['detected_wet_ge90'].sum(),1)
 def test_threshold_exactly90(self):
  m=masks([90,89.999,95],[90,91,89]);self.assertEqual(m['observed_wet_ge90'].sum(),2);self.assertEqual(m['missed_wet_ge90'].sum(),1)
 def test_seasons(self):
  self.assertEqual([summer_winter(x) for x in (1,4,7,10)],['DJF','MAM','JJA','SON'])
 def test_utc_fixed_cet_not_daylight_savings(self):
  self.assertEqual(cet_daypart(23),'CET_00_05')
  self.assertEqual(cet_daypart(0),'CET_00_05')
  self.assertEqual(cet_daypart(11),'CET_12_17')
  self.assertEqual(cet_daypart(22),'CET_18_23')
 def test_reject_bad_timestamp(self):
  with self.assertRaises(ValueError):cet_daypart(24)
 def test_empty_selection_returns_none(self):
  self.assertIsNone(summarize(np.array([False,False]),np.array([1.,2.]),np.array([1.,1.]),np.array([1.,1.]),np.array([2.,3.])))
 def test_weighted_group_bias(self):
  rows=[dict(group_type='condition',group='all',n_hours=1,T_bias_C=2,T_MAE_C=2,T_RMSE_C=2,T_warm_error_fraction=1,e_bias_hpa=.5,e_MAE_hpa=.5),dict(group_type='condition',group='all',n_hours=3,T_bias_C=-2,T_MAE_C=2,T_RMSE_C=2,T_warm_error_fraction=0,e_bias_hpa=-.5,e_MAE_hpa=.5)]
  g=combined(rows)[0];self.assertAlmostEqual(g['T_bias_C'],-1);self.assertEqual(g['n_hours'],4)
 def test_score_station_coverage_without_pred_use_target(self):
  hours=[dt.datetime(2019,1,1)+dt.timedelta(hours=i) for i in range(48)]
  pred=dict(T=np.full(48,5.),e=np.full(48,6.),RH=np.full(48,85.))
  obs={h:dict(T=4.,e=6.2,RH=94.,P=980.) for h in hours}
  rows,cov=score_site('XYZ',2019,hours,pred,obs,300)
  wet=[r for r in rows if r['group_type']=='condition' and r['group']=='missed_wet_ge90'][0]
  self.assertEqual(wet['n_hours'],48);self.assertAlmostEqual(wet['T_bias_C'],1)
  self.assertEqual(cov['missed_count'],48)
 def test_observed_and_predicted_wet_groups_different(self):
  m=masks([91,91,50],[95,20,90]);self.assertEqual(m['predicted_wet_ge90'].sum(),2)
  self.assertEqual(m['observed_wet_ge90'].sum(),2)
  self.assertEqual(m['missed_wet_ge90'].sum(),1)
 def test_finite_validation(self):
  with self.assertRaises(ValueError):summarize(np.array([True]),np.array([float('nan')]),np.array([0.]),np.array([1.]),np.array([1.]))

if __name__=='__main__':unittest.main()