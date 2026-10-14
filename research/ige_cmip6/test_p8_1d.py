"""Physically constrained synthetic contracts; no commercial or station raw data."""
import unittest,math
import numpy as np
from p8_1d_regime import regime,susceptibility,season_factors,features,fit_donor_only,predict_regime,metadata_validation

def site(sid,t=-180,t5=-400,rug=150,z=500,slope=.2,temp=5):
 return {'station_id':sid,'tpi_1500_m':t,'tpi_5000_m':t5,'rugged_1500_m':rug,'slope_250m_proxy':slope,'hoehe_m':z,'station_height_m':z,'lat':45+sid*.015,'lon':12+(sid%4)*.1,'tmittel':[temp-.005*z]*12}
class Tests(unittest.TestCase):
 def test_regime_classification(self):
  self.assertEqual(regime(site(1)),'enclosed_valley')
  self.assertEqual(regime(site(2,t=555,t5=700,z=3109)),'alpine_crest')
  self.assertEqual(regime(site(3,t=150,t5=200,z=900)),'ridge')
  self.assertEqual(regime(site(4,t=-5,t5=-20,rug=9,slope=.02)),'open_lowland')
 def test_cold_pool_only_morphology_not_observation(self):
  v,r=susceptibility(site(1));self.assertGreater(v,0);self.assertEqual(r,0.)
  v,r=susceptibility(site(2,t=300,t5=600));self.assertEqual(v,0.);self.assertGreater(r,0.)
 def test_inversion_proxies_peak_in_winter(self):
  self.assertEqual(season_factors(1),(1.,0.))
  self.assertEqual(season_factors(7),(0.,1.))
  self.assertGreater(features(site(1),1)[0],features(site(1),7)[0])
 def test_train_excludes_target(self):
  target=site(99);don=[site(i,t=(i*31%280)-180,z=200+i*80) for i in range(30)]
  c=fit_donor_only(don,1);self.assertEqual(c.shape,(4,))
  self.assertTrue(np.isfinite(c).all());self.assertLessEqual(max(abs(c)),1.)
  w=np.ones(8)/8
  with self.assertRaisesRegex(AssertionError,'TARGET LEAKAGE'):
   predict_regime(5.,target,don[:7]+[target],w,c,1)
 def test_donor_permutation_invariance(self):
  s=[site(i,t=(i*17%250)-100,t5=(i*17%800)-400,z=200+i*40,temp=10+i*.2) for i in range(45)]
  self.assertTrue(np.allclose(fit_donor_only(s,1),fit_donor_only(s[::-1],1)))
 def test_identical_terrain_has_zero_delta(self):
  t=site(999);ds=[site(i) for i in range(8)];w=np.ones(8)/8
  y,delta=predict_regime(7.,t,ds,w,np.ones(4),1)
  self.assertEqual(y,7.);self.assertAlmostEqual(delta,0)
 def test_bounded_mountain_extrapolation(self):
  t=site(99,t=2200,t5=2500,z=3109);ds=[site(i) for i in range(8)]
  y,d=predict_regime(2.,t,ds,np.ones(8)/8,np.ones(4)*50.,1)
  self.assertLessEqual(abs(d),1.)
 def test_invalid_topography_rejected(self):
  with self.assertRaisesRegex(ValueError,'morphology'):susceptibility(site(1,rug=float('nan')))
  with self.assertRaises(ValueError):season_factors(13)
 def test_duplicate_stations_rejected(self):
  with self.assertRaisesRegex(ValueError,'Duplicate'):metadata_validation([site(1),site(1)])
 def test_train_vs_validation_years(self):
  from p8_1b_temporal_holdout import TRAIN_YEARS,TEST_YEARS
  self.assertEqual((min(TRAIN_YEARS),max(TRAIN_YEARS)),(1991,2010))
  self.assertEqual((min(TEST_YEARS),max(TEST_YEARS)),(2011,2020))
  self.assertFalse(set(TRAIN_YEARS)&set(TEST_YEARS))
if __name__=='__main__':unittest.main()