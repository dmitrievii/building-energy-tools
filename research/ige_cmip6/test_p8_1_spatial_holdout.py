"""Synthetic fixture tests; no third-party station or Meteonorm files required."""
import unittest, math
from p8_1_spatial_holdout import haversine, predict, valid, compute, REFERENCE_PERIOD

def st(i, lat, lon, z, t, p=50, period=REFERENCE_PERIOD):
    return {'station_id':i,'station':str(i),'lat':lat,'lon':lon,'hoehe_m':z,'periode':period,
       'tmittel':[t]*12,'tmin':[t-5]*12,'tmax':[t+5]*12,'niederschlag_mm':[p]*12,
       'luftfeuchte':[50]*12,'wind_ms':[2]*12}

class HoldoutContract(unittest.TestCase):
    def test_haversine(self):
        a=st(1,0,0,0,0);b=st(2,0,1,0,0)
        self.assertAlmostEqual(haversine(a,b),111.195,places=2)
    def test_leave_target_out_even_if_closest(self):
        target=st(1,47,15,100,999)
        donors=[target,st(2,47.1,15,100,10),st(3,47.2,15,100,10)]
        pred=predict(target,donors,'tmittel',0,'idw_raw')
        self.assertAlmostEqual(pred['estimate'],10)
        self.assertNotIn('1',pred['donor_ids'].split(';'))
    def test_exact_synthetic_lapse(self):
        d=st(2,47.1,15.1,200,20)
        t=st(1,47,15,1200,13.5)
        self.assertAlmostEqual(predict(t,[d],'tmittel',0,'nearest_lapse')['estimate'],13.5)
        self.assertAlmostEqual(predict(t,[d],'tmittel',0,'nearest_raw')['estimate'],20)
    def test_idw_convex_and_monotonic(self):
        a,b=st(2,47,15.2,300,11),st(3,47,15.4,400,13)
        t=st(1,47,15.3,350,12)
        p=predict(t,[a,b],'tmittel',0,'idw_raw')['estimate']
        self.assertGreaterEqual(p,11);self.assertLessEqual(p,13)
    def test_short_period_excluded_as_donor_and_target(self):
        t=st(1,47,15,100,0)
        near_short=st(2,47.0001,15,100,100,period='2000–2020')
        far_valid=st(3,47.1,15,100,10)
        data=compute([t,near_short,far_valid],radii=[0],fields=['tmittel'])
        assert data
        self.assertEqual({r['station_id'] for r in data},{1,3})
        self.assertTrue(all(abs(r['predicted'])<=11 for r in data))
    def test_buffer_excludes_neighbor(self):
        t=st(1,47,15,100,10);near=st(2,47.001,15,100,20);far=st(3,47.3,15,100,1)
        data=compute([t,near,far],radii=[25],fields=['tmittel'])
        p=[r for r in data if r['station_id']==1 and r['method']=='nearest_raw']
        self.assertEqual(len(p),12)
        self.assertTrue(all(abs(x['predicted']-1)<1e-9 for x in p))
    def test_no_invalid_radiation_claims(self):
        t=st(1,47,15,100,10);near=st(2,47.3,15,100,20)
        with self.assertRaises(ValueError):predict(t,[near],'niederschlag_mm',0,'nearest_lapse')
    def test_period_validation(self):
        x=st(1,47,15,200,0);self.assertTrue(valid(x,'tmittel'))
        x['tmittel'][3]=None;self.assertFalse(valid(x,'tmittel'))

if __name__=='__main__':unittest.main()