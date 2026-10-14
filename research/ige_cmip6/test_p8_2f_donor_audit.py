import datetime as dt, unittest
import numpy as np
from p8_2f_donor_audit import effective_distance,event_audit,metrics,source_station_geometry,sorted_alt_donors
class TestDonorAudit(unittest.TestCase):
    def test_effective_distance_km_and_vertical_penalty(self):
        self.assertAlmostEqual(effective_distance(10,1000),np.sqrt(500))
        self.assertEqual(effective_distance(10,0),10)
    def test_altitude_ranking_can_change_order(self):
        target={'station_id':'TAR','lat':47.0,'lon':8.0,'hoehe_m':1000}
        meta={'NEA':{'station_id':'NEA','lat':47.01,'lon':8.0,'hoehe_m':0},
              'FAR':{'station_id':'FAR','lat':47.1,'lon':8.0,'hoehe_m':1010}}
        weather={k:{i:1 for i in range(8001)} for k in meta}
        monthly={k:{f'2019-{m:02d}':{'e':2} for m in range(1,13)} for k in meta}
        got=sorted_alt_donors(target,meta,weather,monthly,2019)
        self.assertEqual(got[0][1]['station_id'],'FAR')
    def test_event_any_donor_vs_all_donors_below(self):
        hrs=[dt.datetime(2019,1,1)+dt.timedelta(hours=i) for i in range(3)]
        donors=[(10,{'station_id':'AAA'}),(20,{'station_id':'BBB'})]
        weather={'AAA':{hrs[i]:{'T':5,'P':980,'e':10,'RH':r} for i,r in enumerate([95,85,91])},
                 'BBB':{hrs[i]:{'T':5,'P':980,'e':10,'RH':r} for i,r in enumerate([80,86,96])}}
        monthly={k:{'2019-01':{'e':9}} for k in weather}
        target={x:{'T':4,'P':970,'e':11,'RH':92} for x in hrs}
        pred={'RH':np.array([80.,80.,93.])}
        row,dc,_=event_audit(hrs,donors,weather,monthly,target,pred,2019,'TAR')
        self.assertEqual(row['wet_observed'],3)
        self.assertEqual(row['missed_total'],2)
        self.assertEqual(row['missed_any_wet_donor'],1)
        self.assertEqual(row['missed_all_donors_below90'],1)
        self.assertEqual(row['detected_wet'],1)
    def test_metrics_zero_error(self):
        h=[dt.datetime(2019,1,1)+dt.timedelta(hours=i) for i in range(2)]
        obs={x:{'T':5,'P':990,'e':11,'RH':93} for x in h}
        pred={'T':np.array([5.,5.]),'e':np.array([11.,11.]),'RH':np.array([93.,93.])}
        r=metrics(pred,obs,h,2019,'TEST','trial')
        self.assertEqual(r['recall_wet'],1.0)
        self.assertEqual(r['MAE_T'],0)
    def test_geometry_metric_is_physical(self):
        target={'station_id':'TAR','hoehe_m':1000}
        station={'station_id':'AAA','station':'Alpha','hoehe_m':900}
        r=source_station_geometry(target,[(20.,station)],{'AAA'},{'AAA'})[0]
        self.assertEqual(r['elevation_delta_m'],-100.)
        self.assertTrue(r['original_four'])
if __name__=='__main__':unittest.main()