"""Source-only, fail-closed Graz station donor and radiation QC reconnaissance."""
from __future__ import annotations
import calendar
import unittest
from p6_2b_graz_station_network import (
    ACCEPTED_Q21,P3_DONORS,extract_snapshot,haversine,select_stations,
)

def source(y=2005,m=7):
    n=calendar.monthrange(y,m)[1]*24
    stamp=[f'{y}-{m:02d}-{d:02d}T{h:02d}:00:00+00:00'
           for d in range(1,calendar.monthrange(y,m)[1]+1) for h in range(24)]
    assert len(stamp)==n
    p={
        'tl':{'unit':'°C','data':[21.]*n},
        'rr':{'unit':'mm','data':[0.]*n},
        'cglo':{'unit':'W/m²','data':[350.]*n},
        'tl_flag':{'unit':'code','data':[10]*n},
        'rr_flag':{'unit':'code','data':[10]*n},
        'cglo_flag':{'unit':'code','data':[0]*n},
    }
    return {'timestamps':stamp,'features':[{'properties':{'station':30,'parameters':p}}]}

class GrazNetworkContract(unittest.TestCase):
    def test_distance_and_no_outside_station_guessing(self):
        self.assertLess(haversine(46.983,15.450),.001)
        metadata={'stations':[{'id':30,'name':'Graz','lat':46.983,'lon':15.45},
                              {'id':116,'name':'Donor','lat':47.1,'lon':15.5},
                              {'id':200,'name':'Remote','lat':48,'lon':16}]}
        ids,where=select_stations(metadata,max_nearby=2)
        self.assertEqual(ids[:2],[30,116])
        self.assertTrue(where[200]['distance_from_Graz_target_km']>75)

    def test_original_ungauged_radiation_not_promoted_to_verified(self):
        y,m=2005,7
        n=calendar.monthrange(y,m)[1]*24
        rows=extract_snapshot(source(y,m),[30],
                              ('tl','rr','cglo'),
                              {'tl':'tl_flag','rr':'rr_flag','cglo':'cglo_flag'},y,m)
        solar=next(x for x in rows if x['variable']=='cglo')
        self.assertEqual(solar['raw_nonnull'],n)
        self.assertEqual(solar['qc_accepted'],0)
        self.assertIn('"0":',solar['q21_codes'])
        temp=next(x for x in rows if x['variable']=='tl')
        self.assertEqual(temp['qc_accepted'],n)

    def test_positive_radiation_quality_alternative_is_detectable(self):
        y,m=2005,7
        data=source(y,m)
        n=calendar.monthrange(y,m)[1]*24
        data['features'][0]['properties']['parameters']['cglo_flag']['data']=[10]*n
        solar=extract_snapshot(data,[30],('cglo',),{'cglo':'cglo_flag'},y,m)[0]
        self.assertEqual(solar['qc_accepted'],n)

    def test_unknown_station_becomes_missing_not_fabricated(self):
        row=extract_snapshot(source(2005,7),[30,116],
                             ('cglo',),{'cglo':'cglo_flag'},2005,7)
        missing=next(x for x in row if x['station_id']==116)
        self.assertEqual(missing['raw_nonnull'],0)
        self.assertEqual(missing['qc_accepted'],0)
        self.assertTrue(missing['source_field_missing'])

    def test_missing_flag_is_not_accepted(self):
        d=source(2005,7)
        block=d['features'][0]['properties']['parameters']
        block.pop('cglo_flag')
        row=extract_snapshot(d,[30],('cglo',),{'cglo':'cglo_flag'},2005,7)[0]
        self.assertFalse(row['quality_flag_available'])
        self.assertEqual(row['qc_accepted'],0)

    def test_incomplete_station_parameter_does_not_silently_pass(self):
        d=source(2005,7)
        d['features'][0]['properties']['parameters']['tl']['data'].pop()
        with self.assertRaisesRegex(ValueError,'Wrong hourly variable array length'):
            extract_snapshot(d,[30],('tl',),{'tl':'tl_flag'},2005,7)

    def test_duplicated_timestamps_rejected(self):
        d=source(2005,7)
        d['timestamps'][1]=d['timestamps'][0]
        with self.assertRaisesRegex(ValueError,'Duplicate hourly'):
            extract_snapshot(d,[30],('tl',),{'tl':'tl_flag'},2005,7)

    def test_checked_codes_only(self):
        self.assertNotIn(0,ACCEPTED_Q21)
        self.assertEqual(ACCEPTED_Q21,{10,11,12,20,21,22})
        self.assertEqual(P3_DONORS,(30,116,200,54,8,13605))

if __name__=='__main__':
    unittest.main()
