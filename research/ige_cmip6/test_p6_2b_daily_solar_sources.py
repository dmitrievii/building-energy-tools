"""GeoSphere daily/monthly solar catalogue does not mislabel sunshine as GHI."""
from __future__ import annotations
import unittest
from p6_2b_geosphere_daily_solar_sources import candidates,extract

class DailySolarContracts(unittest.TestCase):
    def test_only_direct_global_radiation_parameter_is_candidate(self):
        metadata={'parameters':[
            {'name':'cglo','long_name':'Globalstrahlung'},
            {'name':'cglo_flag','long_name':'Qualitätsflag Globalstrahlung'},
            {'name':'so','long_name':'Sonnenscheindauer'},
            {'name':'som','long_name':'Total solar irradiance unrelated'},
            {'name':'glo_tages','long_name':'Globalstrahlung Tagesumme'},
            {'name':'tmax','long_name':'Maximum Lufttemperatur'},
        ]}
        self.assertEqual([x['name'] for x in candidates(metadata)],['cglo','glo_tages'])

    def test_unchecked_raw_daily_global_radiation_not_promoted(self):
        d={'timestamps':[f'1995-07-{i:02d}' for i in range(1,32)],
           'features':[{'properties':{'station':30,'parameters':{
               'cglo':{'unit':'kWh/m2','data':[5.0]*31},
               'cglo_flag':{'unit':'code','data':[0]*31}
           }}}]}
        q=extract(d,30,'cglo','cglo_flag',1995,7)
        self.assertTrue(q['present'])
        self.assertEqual(q['non_null'],31)
        self.assertEqual(q['quality_checked'],0)
        self.assertEqual(q['flag_codes'],{'0':31})
        d['features'][0]['properties']['parameters']['cglo_flag']['data']=[10]*31
        q=extract(d,30,'cglo','cglo_flag',1995,7)
        self.assertEqual(q['quality_checked'],31)

    def test_absent_station_source_is_missing_not_zero_irradiation(self):
        d={'timestamps':[f'1995-07-{i:02d}' for i in range(1,32)],'features':[]}
        q=extract(d,30,'cglo','cglo_flag',1995,7)
        self.assertFalse(q['present'])
        self.assertEqual(q['non_null'],0)

    def test_partial_day_source_is_rejected(self):
        d={'timestamps':[f'1995-07-{i:02d}' for i in range(1,31)],'features':[]}
        with self.assertRaisesRegex(ValueError,'daily sample timeline'):
            extract(d,30,'cglo',None,1995,7)

if __name__=='__main__':unittest.main()
