"""P8.1B regression against synthetic fixtures; no proprietary inputs."""
import unittest
import numpy as np
from p8_1b_terrain_holdout import global_slope,local_slope,weighted_slope,experiment
from p8_1b_temporal_holdout import calibrate_donor_normals,run_temporal,TRAIN_YEARS,TEST_YEARS,decode_response

class P8B(unittest.TestCase):
 def setUp(self):
  self.st=[]
  for i in range(24):
   z=350+25*i+180*(i%5)
   self.st.append({'station_id':i+1,'station':str(i),'lat':47+(i%6)*0.22,'lon':11+(i//6)*0.32,'hoehe_m':z,'periode':'1991–2020',
       'tmittel':[12-.005*z+2*np.sin(j/12*2*np.pi) for j in range(12)],
       'tmax':[15-.007*z+2*np.sin(j/12*2*np.pi) for j in range(12)],
       'tmin':[7-.003*z+2*np.sin(j/12*2*np.pi) for j in range(12)]})
 def test_vertical_regression(self):
  for f,g in [('tmittel',-.005),('tmin',-.003),('tmax',-.007)]:
   self.assertAlmostEqual(global_slope(self.st,1,f),g,delta=.0003)
 def test_exclude_id_and_exact_month(self):
  rows=experiment(self.st,radii=(0,),fields=('tmittel',))
  self.assertEqual(len(rows),len(self.st)*12*4)
  self.assertLess(max(abs(r['error']) for r in rows if r['method']=='idw_global_lapse'),.1)
 def test_lapse_weighting(self):
  near=[(8+i,st) for i,st in enumerate(self.st[:16])]
  est=local_slope(near,'tmittel',0,-.005)
  self.assertAlmostEqual(est,-.005,delta=.0002)
 def test_monthly_axis_rejects_shift(self):
  with self.assertRaisesRegex(ValueError,'axis'):
   decode_response({'timestamps':['2000-01'], 'features':[]},{1},None)
 def test_temporal_no_target_as_donor(self):
  series={}
  for st in self.st:
   sid=st['station_id'];z=st['hoehe_m']
   series[sid]={f'{y}-{m:02d}':11-.005*z+.2*(y-1991)+m/10 for y in range(1991,2021) for m in range(1,13)}
  res,n=run_temporal({s['station_id']:{k:s[k] for k in ('station_id','station','lat','lon','hoehe_m')} for s in self.st},series,None)
  self.assertEqual(n,24)
  self.assertTrue(res)
  self.assertLess(max(abs(r['error']) for r in res if r['method']=='idw_global_lapse'),.1)
 def test_no_train_future_leakage(self):
  series={}
  for st in self.st:
   sid=st['station_id'];z=st['hoehe_m']
   series[sid]={f'{y}-{m:02d}':11-.005*z for y in range(1991,2021) for m in range(1,13)}
  norms=calibrate_donor_normals({s['station_id']:{k:s[k] for k in ('station_id','station','lat','lon','hoehe_m')} for s in self.st},series)
  before=norms[0]['tmittel'][:]
  for sid in series:
   for y in TEST_YEARS:
    for m in range(1,13):series[sid][f'{y}-{m:02d}']+=999
  norms=calibrate_donor_normals({s['station_id']:{k:s[k] for k in ('station_id','station','lat','lon','hoehe_m')} for s in self.st},series)
  self.assertEqual(before,norms[0]['tmittel'])
 def test_exactly_360_months_and_q21(self):
  times=[f'{y}-{m:02d}-01T00:00:00Z' for y in range(1991,2021) for m in range(1,13)]
  doc={'timestamps':times,'features':[{'properties':{'station':{'id':1},'parameters':{
      'tl_mittel':{'unit':'°C','data':[10.]*360},
      'tl_mittel_flag':{'data':[21]*359+[1]}}}}]}
  out,diag=decode_response(doc,{1},'tl_mittel_flag')
  self.assertEqual(len(out[1]),359)
  self.assertEqual(diag['rejected_unqualified_hours'],1)
 def test_target_calibration_data_not_used(self):
  stations={st['station_id']:{k:st[k] for k in ('station_id','station','lat','lon','hoehe_m')} for st in self.st}
  series={st['station_id']:{f'{y}-{m:02d}':12-.004*st['hoehe_m']+m/10 for y in range(1991,2021) for m in range(1,13)} for st in self.st}
  first,_=run_temporal(stations,series,None)
  original=[x['predicted'] for x in first if x['station_id']==1]
  for y in TRAIN_YEARS:
   for m in range(1,13):series[1][f'{y}-{m:02d}']+=5
  changed,_=run_temporal(stations,series,None)
  self.assertEqual(original,[x['predicted'] for x in changed if x['station_id']==1])
if __name__=='__main__':unittest.main()