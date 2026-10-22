import math,unittest,numpy as np
from p9_3b3_native_at_valley_source_only import frozen_radius_census,vector_distance_km

class NativeValleyOrographySourceOnly(unittest.TestCase):
 def setUp(self):
  self.site={'lat':47.,'lon':15.,'sensor_height_MSL_m':380.}
  self.points=[(47.01,15.0),(47.04,15.0),(47.45,15.0),(47.66,15.0)]
  self.d=np.array([2.,5.,45.,75.])
  self.radii=(10.,50.,100.)
 def test_nearest_high_surface_must_not_be_used_below_ground(self):
  x=frozen_radius_census(self.points,self.d,np.array([410.,395.,370.,350.]),self.site,self.radii)
  self.assertEqual([r['n_air_domain_reaches_barometer_height_nominal'] for r in x['radii']],[0,1,2])
  self.assertEqual(x['radii'][1]['nearest_air_column_that_reaches_barometer']['distance_km'],45.)
 def test_all_above_station_stays_blocked(self):
  x=frozen_radius_census(self.points,self.d,[410.,395.,385.,384.],self.site,self.radii)
  self.assertEqual(x['status'],'NO_NATIVE_OROGRAPHY_BELOW_BAROMETER_WITHIN_PREDEFINED_RADIUS')
 def test_valid_but_distant_75km_is_not_qualified_pressure(self):
  x=frozen_radius_census(self.points,self.d,[410.,395.,385.,350.],self.site,self.radii)
  self.assertIn('HORIZONTAL_REPRESENTATIVENESS_NOT_QUALIFIED',x['status'])
  self.assertTrue(x['NO_STATION_PRESSURE_T_RH_VALUES_READ'])
 def test_permutation_order_does_not_select_model_by_point_index(self):
  a=frozen_radius_census(self.points,self.d,[410.,395.,370.,350.],self.site,self.radii)
  ix=[2,1,3,0]
  b=frozen_radius_census([self.points[j] for j in ix],self.d[ix],
      np.array([410.,395.,370.,350.])[ix],self.site,self.radii)
  self.assertEqual(a,b)
 def test_original_station_instrument_height_not_mutated(self):
  before=dict(self.site)
  x=frozen_radius_census(self.points,self.d,[410.,395.,370.,350.],self.site,self.radii)
  self.assertEqual(self.site,before)
  self.assertEqual(x['radii'][-1]['n_air_domain_reaches_barometer_height_nominal'],2)
 def test_native_geographical_distance_is_geodesic_not_index(self):
  ds=vector_distance_km([47.,47.,48.],[15.,16.,15.],self.site)
  self.assertAlmostEqual(ds[0],0.,places=6)
  self.assertGreater(ds[2],100.)
  self.assertGreater(ds[1],70.)
if __name__=='__main__':unittest.main()
