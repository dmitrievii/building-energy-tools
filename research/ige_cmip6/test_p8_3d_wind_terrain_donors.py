"""P8.3D physical ranker controls. Synthetic fixtures only, no provider network."""
import datetime as dt
import math
import types,sys
import unittest
from unittest.mock import patch
from p8_3d_wind_terrain_donors import (
    YEAR,TARGETS,ALT_KM_PER_M,eligible_station,ranking_score,choose_donors,
    landform_features,metadata_dem_features,score_site,compare_selectors,
    summarize,DEM_RING_M,DEM_BEARINGS)


def station(s,lat,z,tpi=0,rug=100):
    return {'station_id':s,'lat':lat,'lon':7.4,'hoehe_m':z}


def feature(s,tpi,rug):
    return {'station_id':s,'tpi_1500_m':tpi,'rugged_1500_m':rug}


class FakeTileCache:
    zoom=11
    def __init__(self):self.called=[]
    def prefetch(self,needed,workers=12):self.called.append(len(needed))
    def point(self,lat,lon):return 500+lat*2+lon


class TestPhysicalWindRanking(unittest.TestCase):
    def setUp(self):
        from math import asin,cos,sin,sqrt,radians
        def great_circle(a,b,c,d):
            x=radians(c-a);y=radians(d-b);
            z=sin(x/2)**2+cos(radians(a))*cos(radians(c))*sin(y/2)**2
            return 6371.0088*2*asin(min(1,sqrt(z)))
        self._modules=patch.dict(sys.modules,{
            'p8_1e_swiss_external':types.SimpleNamespace(haversine=great_circle),
            'p8_1c_dem':types.SimpleNamespace(radial=lambda lat,lon,dist,azi:(lat+.00001*(azi+1),lon), tile_point=lambda lat,lon,zoom:( (zoom,10,20),0,0)),
            'p8_2e_crossyear':types.SimpleNamespace(annual_hours=lambda year:[dt.datetime(year,1,1)+dt.timedelta(hours=i) for i in range(8784 if __import__('calendar').isleap(year) else 8760)])
        })
        self._modules.start()
        self.t=station('T',46.4,500)
        self.meta={'T':self.t,'A':station('A',46.401,2400),
                   'B':station('B',46.41,560),'C':station('C',46.42,520),
                   'D':station('D',46.43,540),'E':station('E',46.44,510)}
        self.f={s:feature(s,0,100) for s in self.meta}
        self.qualified=set(self.meta)

    def tearDown(self):
        self._modules.stop()

    def test_pre_registered_year(self):
        self.assertEqual(YEAR,2024)
        self.assertEqual(len(TARGETS),6)
        self.assertNotIn('ABO',TARGETS)
    def test_eligibility_requires_actual_wind_coverage(self):
        self.assertFalse(eligible_station({'usable_wind_hours':0},100))
        self.assertTrue(eligible_station({'usable_wind_hours':90},100))
        self.assertFalse(eligible_station({'usable_wind_hours':89},100))
    def test_distance_is_original_geographic_metric(self):
        self.assertEqual(ranking_score(self.t,self.meta['A'],15,self.f,'distance_idw4'),15)
    def test_terrain_exact_identical_reduces_to_distance(self):
        s=station('S',46.41,500)
        self.assertEqual(ranking_score(self.t,s,4,self.f,'altitude_idw4'),4)
        self.assertEqual(ranking_score(self.t,s,4,{'T':feature('T',2,3),'S':feature('S',2,3)},'terrain_idw4'),4)
    def test_altitude_penalty_metre_units(self):
        self.assertAlmostEqual(ranking_score(self.t,self.meta['A'],5,self.f,'altitude_idw4'),math.hypot(5,ALT_KM_PER_M*1900))
    def test_more_dissimilar_terrain_worsens_score(self):
        f=dict(self.f);f['T']=feature('T',-300,400);f['A']=feature('A',200,100)
        self.assertGreater(ranking_score(self.t,self.meta['A'],5,f,'terrain_idw4'),ranking_score(self.t,self.meta['A'],5,f,'altitude_idw4'))
    def test_nearest_not_preferred_when_height_extremely_different(self):
        distance=choose_donors(self.t,self.meta,self.qualified,self.f,'distance_idw4')
        altitude=choose_donors(self.t,self.meta,self.qualified,self.f,'altitude_idw4')
        self.assertEqual(distance[0][1]['station_id'],'A')
        self.assertNotIn('A',[s['station_id'] for d,s in altitude])
    def test_return_true_distance_not_effective_score(self):
        for d,s in choose_donors(self.t,self.meta,self.qualified,self.f,'altitude_idw4'):
            self.assertGreater(d,0)
            self.assertLess(d,20)
    def test_target_excluded_even_if_qualified(self):
        rows=choose_donors(self.t,self.meta,self.qualified,self.f,'terrain_idw4')
        self.assertNotIn('T',[s['station_id'] for d,s in rows])
    def test_insufficient_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):
            choose_donors(self.t,self.meta,{'A','B'},self.f,'terrain_idw4')
    def test_invalid_method_fails(self):
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED'):
            ranking_score(self.t,self.meta['A'],1,self.f,'ML')
    def test_landform_feature_requires_true_sample(self):
        cache=FakeTileCache()
        with patch('p8_1c_dem.radial',side_effect=lambda lat,lon,dist,azi:(lat+0.00001*(azi+1),lon)):
            f=landform_features(self.t,cache)
        self.assertEqual(f['station_id'],'T')
        self.assertIn('tpi_1500_m',f)
        self.assertIn('rugged_1500_m',f)
    def test_metadata_dem_derived_from_cache_only(self):
        cache=FakeTileCache()
        x=metadata_dem_features({'T':self.t,'A':self.meta['A']},cache)
        self.assertEqual(set(x),{'T','A'})
        self.assertGreater(cache.called[0],0)
    def test_no_target_observations_in_donor_predictor(self):
        h=dt.datetime(2024,1,1)
        donors=[(1.0,{'station_id':'A'}),(2.0,{'station_id':'B'}),
                (3.0,{'station_id':'C'}),(4.0,{'station_id':'D'})]
        obs={x:{h:{'speed':2.,'direction':90.}} for x in 'ABCD'}
        obs['T']={h:{'speed':2.,'direction':270.}}
        o=score_site('T',[h],donors,obs)
        self.assertAlmostEqual(o[h]['scalar'],2)
        self.assertAlmostEqual(o[h]['vector_direction'],90)
    def test_missing_hours_not_silently_imputed(self):
        donors=[(1.,{'station_id':'A'}),(2.,{'station_id':'B'}),
                (3.,{'station_id':'C'}),(4.,{'station_id':'D'})]
        h=dt.datetime(2024,1,1)
        obs={'T':{h:{'speed':5,'direction':90}}}
        obs.update({x:{} for x in 'ABCD'})
        self.assertEqual(score_site('T',[h],donors,obs),{})
    def test_matched_hour_per_method_fair(self):
        h=dt.datetime(2024,1,1)
        p={'reference_speed':3.,'reference_direction':0.,'scalar':4.,
           'vector_direction':0.,'unit_direction':20.,'nearest_direction':30.}
        r=summarize({h:p},'T','distance_idw4',strict_common={h})
        self.assertEqual(r['scalar_speed_MAE_mps'],1)
        self.assertAlmostEqual(r['vector_direction_emitted_MAE_deg'],0)
        self.assertAlmostEqual(r['unit_direction_emitted_MAE_deg'],20)
    def test_common_hour_missing_fails_closed(self):
        h=[dt.datetime(2024,1,1)+dt.timedelta(hours=k) for k in range(10)]
        obs={x:{} for x in 'ABCDE'}
        obs['T']={k:{'speed':3.,'direction':90.} for k in h}
        selections={m:[(i+1.,{'station_id':x}) for i,x in enumerate('ABCD')] for m in ('distance_idw4','altitude_idw4','terrain_idw4')}
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):
            compare_selectors('T',h,selections,obs)
    def test_target_in_donors_fails(self):
        with self.assertRaisesRegex(AssertionError,'TARGET_LEAK'):
            score_site('T',[],[(1.,{'station_id':'T'})],{'T':{}})
    def test_2024_is_leap_year(self):
        from p8_2e_crossyear import annual_hours
        self.assertEqual(len(annual_hours(2024)),8784)
    def test_source_restricted_to_research(self):
        self.assertEqual(DEM_RING_M,1500)
        self.assertEqual(len(DEM_BEARINGS),8)

if __name__=='__main__':unittest.main()