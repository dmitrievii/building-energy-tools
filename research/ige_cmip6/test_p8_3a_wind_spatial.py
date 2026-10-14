"""P8.3A scientific tests, pure synthetic fixtures, no Swiss source download."""
import unittest,datetime as dt, math
import numpy as np
from p8_3a_wind_spatial import (
    number,parse_wind_year,wind_from_to_uv,uv_to_wind_from,circular_error_deg,
    wind_coverage,interpolate,score_target,CALM_MPS)

class TestP83WindContracts(unittest.TestCase):
    def test_cardinal_from_north(self):
        e,n=wind_from_to_uv(5,0)
        self.assertAlmostEqual(e,0,8);self.assertAlmostEqual(n,-5)
        sp,d=uv_to_wind_from(e,n);self.assertAlmostEqual(sp,5);self.assertAlmostEqual(d,0)
    def test_cardinal_from_east(self):
        u,v=wind_from_to_uv(5,90)
        self.assertAlmostEqual(u,-5);self.assertAlmostEqual(v,0,8)
        _,d=uv_to_wind_from(u,v);self.assertAlmostEqual(d,90)
    def test_opposing_winds_cancel_not_naively_average_azimuth(self):
        donors=[(10.,{'station_id':'A'}),(10.,{'station_id':'B'})]
        obs={'A':{0:{'speed':4.,'direction':0}},'B':{0:{'speed':4.,'direction':180}}}
        p=interpolate(donors,obs,0)
        self.assertAlmostEqual(p['vector_speed'],0,7)
        self.assertIsNone(p['vector_direction'])
        self.assertAlmostEqual(p['scalar_speed'],4)
    def test_near_north_wrapping(self):
        a=wind_from_to_uv(6,359);b=wind_from_to_uv(6,1)
        _,d=uv_to_wind_from(*((a[0]+b[0])/2,(a[1]+b[1])/2))
        self.assertLess(circular_error_deg(d,0),1e-8)
    def test_direction_shortest_difference(self):
        self.assertAlmostEqual(circular_error_deg(355,5),10)
        self.assertAlmostEqual(circular_error_deg(5,355),10)
        self.assertAlmostEqual(circular_error_deg(90,270),180)
        self.assertIsNone(circular_error_deg(None,5))
    def test_calm_direction_may_be_absent(self):
        self.assertEqual(wind_from_to_uv(.3,None),(0.,0.))
    def test_calm_direction_output_never_invented(self):
        self.assertIsNone(uv_to_wind_from(0.2,0.2)[1])
    def test_swiss_column_and_unit_parsing(self):
        raw=b'station_abbr;reference_timestamp;fkl010h0;dkl010h0\nABO;01.01.2021 01:00;3.2;270\nABO;01.01.2021 02:00;0.0;\n'
        out=parse_wind_year(raw,'ABO',2021)
        self.assertEqual(len(out),2)
        self.assertEqual(out[dt.datetime(2021,1,1,1)]['direction'],270.)
        self.assertIsNone(out[dt.datetime(2021,1,1,2)]['direction'])
    def test_duplicate_source_hour_rejected(self):
        raw=b'station_abbr;reference_timestamp;fkl010h0;dkl010h0\nABO;01.01.2021 01:00;3.2;270\nABO;01.01.2021 01:00;3.2;270\n'
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):parse_wind_year(raw,'ABO')
    def test_schema_drift_fails_closed(self):
        raw=b'station_abbr;reference_timestamp;incorrect_speed;dkl010h0\nABO;01.01.2021 01:00;3.2;270\n'
        with self.assertRaisesRegex(ValueError,'SCHEMA'):parse_wind_year(raw,'ABO')
    def test_coverage_counts_observations_not_rows(self):
        hours=[dt.datetime(2021,1,1)+dt.timedelta(hours=i) for i in range(10)]
        obs={h:{'speed':None,'direction':None} for h in hours}
        s=wind_coverage(obs,hours)
        self.assertEqual(s['recorded_rows'],10)
        self.assertEqual(s['usable_wind_hours'],0)
        self.assertFalse(s['eligible'])
    def test_vector_magnitude_bounded_by_scalar_idw(self):
        donors=[(20.,{'station_id':'A'}),(21.,{'station_id':'B'})]
        obs={'A':{0:{'speed':7.,'direction':30}},'B':{0:{'speed':12.,'direction':90}}}
        p=interpolate(donors,obs,0)
        self.assertLessEqual(p['vector_speed'],p['scalar_speed']+1e-8)
        self.assertLess(p['vector_speed'],p['scalar_speed'])
    def test_missing_wind_direction_excludes_noncaml_station(self):
        donors=[(10.,{'station_id':'A'}),(20.,{'station_id':'B'})]
        o={'A':{0:{'speed':3.,'direction':None}},'B':{0:{'speed':5.,'direction':0}}}
        self.assertIsNone(interpolate(donors,o,0))
    def test_withheld_site_not_used_for_prediction(self):
        donors=[(10.,{'station_id':'A'}),(10.,{'station_id':'B'})]
        o={'A':{0:{'speed':3.,'direction':0}},'B':{0:{'speed':4.,'direction':0}}}
        p=interpolate(donors,o,0)
        self.assertAlmostEqual(p['scalar_speed'],3.5)
        self.assertNotIn('TARGET',o)
    def test_score_fails_if_target_coverage_insufficient(self):
        hours=[dt.datetime(2021,1,1)+dt.timedelta(hours=i) for i in range(24)]
        p={hours[0]:{'vector_speed':1.,'scalar_speed':1.,'nearest_speed':1.,'vector_direction':0.,'nearest_direction':0.,'resultant_ratio':1.}}
        obs={hours[0]:{'speed':1.,'direction':0.}}
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):score_target('ABO',2021,hours,[],obs,p)
    def test_speed_clamp_rejects_nonphysical(self):
        self.assertIsNone(number('infinite',0,90));self.assertIsNone(number('-1',0,90))

if __name__=='__main__':unittest.main()