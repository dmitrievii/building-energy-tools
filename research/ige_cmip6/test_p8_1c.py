"""Source-independent geometry, topography, and leakage tests."""
import unittest,math,io
import numpy as np
from PIL import Image
from p8_1c_dem import tile_point,radial,decode_tile,sample_locations,TileCache
from p8_1c_validate import dem_coefficients,paired_prediction,station_cluster_bootstrap

class Tests(unittest.TestCase):
 def test_terrarium_encoding(self):
  # Elevation +3109m => 35877 => RGB(140,37,0)
  a=np.zeros((256,256,3),dtype=np.uint8);a[:,:,:]=[140,37,0]
  b=io.BytesIO();Image.fromarray(a).save(b,format='PNG')
  self.assertAlmostEqual(decode_tile(b.getvalue())[123,24],3109.)
 def test_terrarium_nodata_only_masks_unsampled_pixels(self):
  a=np.full((256,256,3),[140,37,0],dtype=np.uint8)
  a[7,9]=[0,0,0]
  b=io.BytesIO();Image.fromarray(a).save(b,format='PNG')
  h=decode_tile(b.getvalue())
  self.assertTrue(np.isnan(h[7,9]))
  self.assertAlmostEqual(h[8,9],3109.)
  cache=TileCache('/tmp/p8_1c_synthetic_only')
  tile,x,y=tile_point(47,15,11)
  cache.arrays[tile]=h.copy()
  cache.arrays[tile][y,x]=np.nan
  with self.assertRaisesRegex(ValueError,'DEM_NODATA_AT_SAMPLE'):
   cache.point(47,15)
  cache.arrays[tile][y,x]=3109.
  self.assertAlmostEqual(cache.point(47,15),3109.)
 def test_all_nodata_rejected(self):
  a=np.zeros((256,256,3),dtype=np.uint8)
  b=io.BytesIO();Image.fromarray(a).save(b,format='PNG')
  with self.assertRaisesRegex(ValueError,'no valid elevation'):
   decode_tile(b.getvalue())
 def test_tile_geolocation(self):
  k,x,y=tile_point(0,0,11)
  self.assertEqual(k,(11,1024,1024));self.assertEqual((x,y),(0,0))
 def test_topographic_radial(self):
  lat,lon=radial(47.,15.,5000,0)
  self.assertTrue(47.043<lat<47.046)
  self.assertAlmostEqual(lon,15.,places=3)
  self.assertEqual(len(sample_locations({'lat':47,'lon':15})),49)
 def test_dem_fit_excludes_target(self):
  # Fit must depend on donor data only and not require target station.
  donors=[]
  for i in range(25):
   z=200+80*i; tpi=(i*83%190)-95
   donors.append({'station_id':i,'lat':46.+i*.07,'lon':13.+(i%4)*.3,'hoehe_m':z,
    'tpi_1500_m':tpi,'tpi_5000_m':(i*59%180)-90,
    'tmittel':[-.004*z+0.002*tpi+12]*12})
  a=dem_coefficients(donors,0)
  self.assertEqual(a.shape,(2,))
  self.assertTrue(np.all(np.abs(a)<=.008))
  self.assertTrue(np.all(np.isfinite(a)))
 def test_demo_never_in_prediction_donors(self):
  target={'station_id':123,'hoehe_m':2500,'tpi_1500_m':100,'tpi_5000_m':200}
  donors=[(10+i,{'station_id':i,'hoehe_m':200+i*30,'tpi_1500_m':i*6,'tpi_5000_m':i*8}) for i in range(8)]
  obs={i:10+i for i in range(8)}
  d=paired_prediction(target,donors,obs,(-.006,-.004),np.array([.001,.002]),0)
  self.assertEqual(len(d),6)
  self.assertNotAlmostEqual(d['idw_regional'],d['dem_tpi_multiscale'])
  with self.assertRaises(AssertionError):paired_prediction(target,[(1,target),*donors],obs,(-.006,-.004),np.array([0,0]),0)
 def test_zero_dem_coeff_matches_baseline(self):
  target={'station_id':100,'hoehe_m':1500,'tpi_1500_m':300,'tpi_5000_m':0}
  donors=[(50+i,{'station_id':i,'hoehe_m':300+i*10,'tpi_1500_m':0,'tpi_5000_m':0}) for i in range(8)]
  d=paired_prediction(target,donors,{i:10 for i in range(8)},(-.006,-.004),np.array([0.,0.]),0)
  self.assertAlmostEqual(d['idw_regional'],d['dem_tpi_1500'])
  self.assertAlmostEqual(d['idw_regional'],d['dem_tpi_multiscale'])
 def test_cluster_bootstrap_matched(self):
  rows=[]
  for i in range(15):
   for m in range(12):
    for name,error in [('idw_regional',2.),('dem_tpi_multiscale',1.)]:
     rows.append({'station_id':i,'year':2018,'month':m,'buffer_km':0,'method':name,'abs_error':error})
  d=station_cluster_bootstrap(rows,reps=100)
  self.assertEqual(d['station_count'],15)
  self.assertAlmostEqual(d['gain_mae_C'],1.)
  self.assertTrue(d['station_bootstrap_95_C'][0]>.9)
 def test_causal_period_protocol(self):
  from p8_1b_temporal_holdout import TRAIN_YEARS,TEST_YEARS
  self.assertEqual((min(TRAIN_YEARS),max(TRAIN_YEARS)),(1991,2010))
  self.assertEqual((min(TEST_YEARS),max(TEST_YEARS)),(2011,2020))
  self.assertFalse(set(TRAIN_YEARS)&set(TEST_YEARS))

if __name__=='__main__':unittest.main()