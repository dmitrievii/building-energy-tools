"""No-provider-connection research contracts for IGRA profiles and Swiss geographic holdout."""
import io,unittest,collections
import numpy as np
from p8_1e_igra_profiles import header,level,soundings,classify,aggregate,parse_inventory
from p8_1e_swiss_external import (decode_csv,parse_meta,station_id_from_name,discover_assets,
                                 parse_month_csv,select_stations,evaluate,aggregate as swiss_agg)

def hdr(sid='AUM00011035',y=2018,m=1,d=4,h=0,n=3):
    s=[' ']*71;s[0]='#';s[1:12]=list(sid);s[13:17]=list(f'{y:04}');s[18:20]=list(f'{m:02}');s[21:23]=list(f'{d:02}');s[24:26]=list(f'{h:02}');s[32:36]=list(f'{n:4}')
    return ''.join(s)
def lvl(z,t,lf=' ',tf=' '):
    s=[' ']*51;s[16:21]=list(f'{z:5}');s[21]=lf;s[22:27]=list(f'{round(t*10):5}');s[27]=tf
    return ''.join(s)
class IGRA(unittest.TestCase):
    def test_header_fixedwidth(self):
        d=header(hdr());self.assertEqual((d['id'],d['year'],d['month'],d['day'],d['hour'],d['nlev']),('AUM00011035',2018,1,4,0,3))
    def test_measurement_units(self):self.assertEqual(level(lvl(1200,1.3)),(1200,1.3))
    def test_qc_missing(self):
        self.assertIsNone(level(lvl(-9999,0)))
        self.assertIsNone(level(lvl(280,0,tf='X')))
    def test_actual_profile_inversion(self):
        p=classify([(200,3.0),(500,4.0),(900,2.0)],198)
        self.assertTrue(p['inversion']);self.assertAlmostEqual(p['warmest_above_surface_C'],1.0)
    def test_normal_lapse_not_inversion(self):
        p=classify([(200,5.0),(500,3.0),(900,0)],198)
        self.assertFalse(p['inversion'])
    def test_no_vertical_reference_refused(self):
        self.assertIsNone(classify([(700,5),(1300,7)],198))
    def test_sparse_insufficient_upper_refused(self):
        self.assertIsNone(classify([(200,5),(300,6)],198))
    def test_stream_alignment(self):
        x='\n'.join([hdr(),lvl(198,2),lvl(500,3),lvl(900,-1),hdr(y=2019),lvl(198,1),lvl(500,2),lvl(900,-1)])+'\n'
        s=list(soundings(io.StringIO(x),'AUM00011035'))
        self.assertEqual(len(s),2);self.assertEqual(s[1][0]['year'],2019)
    def test_truncated_refused(self):
        with self.assertRaises(ValueError):list(soundings(io.StringIO(hdr()+'\n'+lvl(198,2)+'\n')))
    def test_profile_aggregate_per_season(self):
        r=[{'station':'A','season':'DJF','nominal_hour':0,'inversion':1,'inversion_strength_c':2},
           {'station':'A','season':'JJA','nominal_hour':12,'inversion':0,'inversion_strength_c':0}]
        a=aggregate(r)
        self.assertEqual(next(x for x in a if x['group_type']=='station')['n_profiles'],2)
        self.assertAlmostEqual(next(x for x in a if x['group_type']=='station')['inversion_frequency'],0.5)
class Swiss(unittest.TestCase):
    def test_metadata_parse_cp1252(self):
        s='station_abbr;station_name;station_coordinates_wgs84_lat;station_coordinates_wgs84_lon;station_height_masl\nBER;Bern;46.9;7.4;553\n'
        # parse_meta requires 50 legitimate sites, so assert schema rejection, not silent success
        with self.assertRaisesRegex(ValueError,'Too few qualified'):
            parse_meta(s.encode('cp1252'))
    def test_csv_meta_column(self):
        rows,cols=decode_csv(b'station;time;tre200m0\nBER;201101;3.5\n')
        self.assertEqual(len(rows),1)
    def test_month_csv_observed(self):
        s='station;time;tre200m0\nBER;201101;1.5\nBER;2011-02;2.2\nBER;1999-01;1\n'
        a,h=parse_month_csv(s.encode(),'BER');self.assertEqual(a,{'2011-01':1.5,'2011-02':2.2})
    def test_month_time_dd_mm_yyyy(self):
        s='station;reference_timestamp;tre200m0\nBER;01.01.2011 00:00;1.5\n'
        a,_=parse_month_csv(s.encode(),'BER')
        self.assertEqual(a,{'2011-01':1.5})
    def test_no_duplicate_date_inconsistent(self):
        s='station;time;tre200m0\nBER;201101;1.5\nBER;201101;3.5\n'
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            parse_month_csv(s.encode(),'BER')
    def test_asset_discovery_filters(self):
        src=[{'assets':{'a':{'href':'https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/ber/ogd-smn_ber_m.csv'},
                         'b':{'href':'https://example.net/ch.meteoschweiz.ogd-smn/ogd-smn_ber_m_historical.csv'}}}]
        self.assertEqual(len(discover_assets(src)['BER']),1)
    def test_spatial_holdout_identical_training_month(self):
        sites=[{'station_id':f'{i:03}', 'station':f'N{i}','lat':46.+i*.01,'lon':8.+i*.01,'hoehe_m':500+i*10} for i in range(10)]
        series={s['station_id']:{'2011-01':10-.0065*s['hoehe_m']} for s in sites}
        rows=evaluate(sites,series,[-.0065]*12,0)
        self.assertEqual(len(rows),30)
        self.assertAlmostEqual(next(r for r in rows if r['station_id']=='000' and r['method']=='idw_fixed65')['error'],0,places=9)
    def test_foreign_source_guard(self):
        src=[{'assets':{'a':{'href':'https://evil.com/ogd-smn_ber_m_historical.csv'}}}]
        self.assertEqual(discover_assets(src),{})
if __name__=='__main__':unittest.main()