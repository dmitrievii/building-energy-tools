import unittest, numpy as np
from p8_1d_validate import run_fold,aggregate,station_bootstrap
class Integration(unittest.TestCase):
 def test_end_to_end_pairing_and_heldout_years(self):
  obs={};sites={};geo=[]
  for i in range(38):
   sid=i+1;lat=46+i*.02;lon=13+(i%6)*.11;alt=350+i*40
   sites[sid]={'station_id':sid,'lat':lat,'lon':lon,'hoehe_m':alt,'station':'fixture_'+str(i)}
   geo.append({'station_id':sid,'dem_height_m':alt,'tpi_1500_m':-120+(i%8)*35,
               'tpi_5000_m':-200+(i%7)*70,'rugged_1500_m':30+(i%9)*21,'slope_250m_proxy':.08})
   obs[sid]={f'{year}-{month:02d}':(12-0.004*alt+(month-1)*0.2+0.1*(year-1991))
                 for year in range(1991,2021) for month in range(1,13)}
  rows,diag,coeff=run_fold(sites,obs,{'stations':geo},0)
  self.assertGreater(diag['scored_station_months'],4000)
  self.assertEqual(len(rows),diag['scored_station_months']*5)
  self.assertEqual(set(x['method'] for x in rows),{'idw_regional','idw_local','dem_tpi_multiscale','orographic_winter','orographic_seasonal'})
  self.assertEqual(set(x['year'] for x in rows),set(range(2011,2021)))
  self.assertTrue(all(np.isfinite(x['error_C']) for x in rows))
  self.assertEqual(len(aggregate(rows,['method'])),5)
  self.assertEqual(station_bootstrap(rows,'idw_regional','orographic_seasonal',0,reps=50)['n_stations'],38)
if __name__=='__main__':unittest.main()