"""Synthetic-only scientific invariants for donor humidity and frozen T-bias."""
import datetime as dt,unittest
import numpy as np
from unittest.mock import patch
from p8_2e_donor_rh_bias_audit import donor_humidity_at_hour,bin_index,BIN_LABELS,cet_daypart,aggregate,build_audit_rows

class ScientificContracts(unittest.TestCase):
 def setUp(self):
  self.hour=dt.datetime(2019,1,1,1)
  self.donors=[(10,{'station_id':'A'}),(20,{'station_id':'B'})]
  self.weather={'A':{self.hour:{'T':5.,'P':1010.,'e':5.,'RH':100.}},
                'B':{self.hour:{'T':6.,'P':1011.,'e':6.,'RH':50.}}}
  self.monthly={'A':{'2019-01':{'e':5.}},'B':{'2019-01':{'e':6.}}}
 def test_same_weighting_as_frozen_prediction(self):
  out=donor_humidity_at_hour(self.hour,self.donors,self.weather,self.monthly,2019)
  self.assertAlmostEqual(out['donor_RH_weighted_pct'],90.)
  self.assertAlmostEqual(out['donor_wet_fraction_weighted'],.8)
  self.assertEqual(out['donor_wet_count'],1)
 def test_fail_closed_missing_donor_rh(self):
  self.weather['B'][self.hour]['RH']=None
  self.assertIsNone(donor_humidity_at_hour(self.hour,self.donors,self.weather,self.monthly,2019))
 def test_only_temperature_eligible_donors(self):
  self.weather['B'][self.hour]['P']=None
  self.assertIsNone(donor_humidity_at_hour(self.hour,self.donors,self.weather,self.monthly,2019))
 def test_donor_bins_boundary(self):
  self.assertEqual([BIN_LABELS[bin_index(x)] for x in [0.,59.99,60,69.99,70,79.9,80,89.9,90,94.9,95,105]],
    ['0-<60','0-<60','60-<70','60-<70','70-<80','70-<80','80-<90','80-<90','90-<95','90-<95','95-105','95-105'])
 def test_invalid_rh_rejected(self):
  with self.assertRaises(ValueError):bin_index(106.)
 def test_cet_without_dst(self):
  self.assertEqual(cet_daypart(0),'00-05')
  self.assertEqual(cet_daypart(11),'12-17')
  self.assertEqual(cet_daypart(23),'00-05')
 def test_no_target_in_donors(self):
  with self.assertRaises(AssertionError):
   build_audit_rows('A',2019,[self.hour],self.donors,self.weather,self.monthly,{'T':np.array([5.]),'e':np.array([5.]),'RH':np.array([90.])},{self.hour:{'T':4,'RH':90,'e':5}},0.)
 def test_scoring_target_only_after_predicting(self):
  ds,cover=build_audit_rows('TARGET',2019,[self.hour],self.donors,self.weather,self.monthly,
       {'T':np.array([7.]),'e':np.array([5.]),'RH':np.array([85.])},
       {self.hour:{'T':5.,'e':5.5,'RH':95.}})
  self.assertEqual(ds[0]['missed_wet_hours'],1)
  self.assertAlmostEqual(ds[0]['sum_temperature_error_C'],2)
  self.assertEqual(ds[0]['donor_RH_bin'],'90-<95')
  self.assertFalse(cover['target_meteorology_used_as_feature'])
 def test_weighted_aggregation_and_recall(self):
  rows=[{'donor_RH_bin':'80-<90','n_hours':1,'sum_temperature_error_C':2,'sum_abs_temperature_error_C':2,'sum_e_error_hpa':.5,'sum_model_T_C':10,'sum_observed_T_C':8,'sum_donor_RH_pct':80,'observed_wet_hours':1,'model_wet_hours':0,'missed_wet_hours':1,'correct_wet_hours':0,'positive_temperature_error_hours':1,'donor_some_wet_hours':0,'donor_all_wet_hours':0},
        {'donor_RH_bin':'80-<90','n_hours':1,'sum_temperature_error_C':0,'sum_abs_temperature_error_C':0,'sum_e_error_hpa':0,'sum_model_T_C':10,'sum_observed_T_C':10,'sum_donor_RH_pct':83,'observed_wet_hours':1,'model_wet_hours':1,'missed_wet_hours':0,'correct_wet_hours':1,'positive_temperature_error_hours':0,'donor_some_wet_hours':0,'donor_all_wet_hours':0}]
  o=aggregate(rows,['donor_RH_bin'])[0]
  self.assertEqual(o['n_hours'],2);self.assertAlmostEqual(o['T_bias_C'],1)
  self.assertAlmostEqual(o['wet_recall'],.5)
  self.assertAlmostEqual(o['missed_wet_rate_pct_of_all_hours'],50.)
 def test_missing_target_hour_fail_closed(self):
  with self.assertRaises(RuntimeError):build_audit_rows('TARGET',2019,[self.hour],self.donors,self.weather,self.monthly,
         {'T':np.array([1.]),'e':np.array([1.]),'RH':np.array([70.])},{})

if __name__=='__main__':unittest.main()