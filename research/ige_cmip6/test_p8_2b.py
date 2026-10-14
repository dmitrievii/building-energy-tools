"""P8.2B: disjoint foreign stations, per-hour physical closure, no mean proxy identity."""
import unittest,io,csv,math
from p8_2b_humidity import swiss_monthly,region,predict_month,evaluate_sites,bootstrap_station
from p8_2b_hourly import hourly_fields,closure,dew_point_from_vapour,one_month
from p8_2a_humidity import esat_water_hpa

class Contracts(unittest.TestCase):
 def test_swiss_monthly_observed_pressure_not_derived(self):
  raw=('station_abbr;reference_timestamp;tre200m0;ure200m0;pva200m0\n'
       'ABO;01.01.2019 00:00;4;71;7.1\n').encode()
  a,q=swiss_monthly(raw,'ABO')
  self.assertEqual(a['2019-01']['e'],7.1)
  self.assertEqual(a['2019-01']['RH'],71)
  self.assertEqual(a['2019-01']['T'],4)
 def test_swiss_monthly_missing_e_never_imputed(self):
  raw=('station_abbr;reference_timestamp;tre200m0;ure200m0;pva200m0\n'
       'ABO;01.01.2019 00:00;4;71;\n').encode()
  a,q=swiss_monthly(raw,'ABO');self.assertIsNone(a['2019-01']['e'])
 def test_swiss_monthly_duplicate_rejected(self):
  raw=('station_abbr;reference_timestamp;tre200m0;ure200m0;pva200m0\n'
       'ABO;01.01.2019 00:00;4;71;7\nABO;01.01.2019 00:00;4;71;7\n').encode()
  with self.assertRaisesRegex(ValueError,'Duplicate'):swiss_monthly(raw,'ABO')
 def test_regions_fixed_geographically(self):
  self.assertEqual(region({'lon':7.1}),'west')
  self.assertEqual(region({'lon':8.1}),'central')
  self.assertEqual(region({'lon':9.1}),'east')
 def test_target_never_enters_predictor(self):
  target={'station_id':'T','lat':47,'lon':8,'hoehe_m':900}
  stations=[{'station_id':str(i),'hoehe_m':300+30*i} for i in range(8)]
  x={str(i):{'2019-01':{'e':3+.1*i,'T':-2+i*.4,'RH':70+i}} for i in range(8)}
  ds=[(1+i,s) for i,s in enumerate(stations)]
  a,b,t=predict_month(target,ds,'2019-01',x,-.0005,-.0065)
  self.assertTrue(a['e_log_regional']>0)
  self.assertTrue(math.isfinite(b['rh_vapour_temperature_proxy']))
  with self.assertRaises(AssertionError):predict_month(target,[(1,target),*ds],'2019-01',x,-.0005,-.0065)
 def test_hourly_parse_required_fields(self):
  row=('station_abbr;reference_timestamp;tre200h0;ure200h0;pva200h0;tde200h0;prestah0\n'
       'ABO;01.01.2019 01:00;5;80;7;2;950\n')
  out,q=hourly_fields(row.encode(),'ABO',2019,{(2019,1)})
  self.assertEqual(len(out[(2019,1)]),1)
 def test_hourly_duplicate_timestamp_rejected(self):
  h='station_abbr;reference_timestamp;tre200h0;ure200h0;pva200h0;tde200h0;prestah0\n'
  r='ABO;01.01.2019 01:00;5;80;7;2;950\n'
  with self.assertRaisesRegex(ValueError,'Duplicate'):hourly_fields((h+r+r).encode(),'ABO',2019,{(2019,1)})
 def test_dewpoint_inverse(self):
  for c in (-15,-1,0,10,30):
   self.assertAlmostEqual(dew_point_from_vapour(esat_water_hpa(c)),c,places=5)
 def test_pointwise_humidity_closure_exact_ideal(self):
  t=20.;rh=50.;e=esat_water_hpa(t)*rh/100;td=dew_point_from_vapour(e)
  m,q=closure([{'T':t,'RH':rh,'e':e,'Td':td,'P':1000}])
  self.assertLess(m['e_from_T_RH_minus_e_hpa']['MAE'],1e-8)
  self.assertLess(m['Td_from_e_minus_Td_C']['MAE'],1e-8)
 def test_monthly_means_do_not_commute(self):
  rows=[]
  for t,rh in [(0,95),(30,30)]:
   e=esat_water_hpa(t)*rh/100
   rows.append({'T':t,'RH':rh,'e':e,'Td':dew_point_from_vapour(e),'P':1000})
  result=one_month(rows,{'e':8.,'RH':62.5})
  self.assertGreater(abs(result['Jensen_gap_RH_pct']),1)
 def test_predicted_rh_no_forced_clipping(self):
  target={'station_id':'X','hoehe_m':3000}
  d=[(i+1,{'station_id':str(i),'hoehe_m':100}) for i in range(8)]
  x={str(i):{'2019-01':{'e':18,'RH':91,'T':-2}} for i in range(8)}
  a,b,t=predict_month(target,d,'2019-01',x,-.0005,-.0065)
  self.assertGreater(b['rh_vapour_temperature_proxy'],100)
 def test_station_bootstrap_identical_methods_zero_gain(self):
  r=[]
  for s in range(12):
   for method in ('e_linear_idw','e_log_regional'):
    r.append({'holdout':'station_loo','buffer_km':0,'variable':'e_hpa','method':method,'site':str(s),'year':2019,'month':1,'abs_error':.2})
  v=bootstrap_station(r,'station_loo',0,'e_hpa','e_linear_idw','e_log_regional')
  self.assertEqual(v['equal_site_MAE_gain'],0)
if __name__=='__main__':unittest.main()