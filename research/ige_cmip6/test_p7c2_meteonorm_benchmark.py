"""Synthetic data only. No Meteonorm originals, no derivative hourly records."""
import csv
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from p7c2_meteonorm_benchmark import (
    COLUMNS,N_HOURS,read_epw,percentiles,q_air,ks_distance,wind_rose,
    pearson,max_run,metric,monthly_metrics,observed_deltas,run,sha256,verify_registered_site,
)

NAME_MAP=(
    'Graz-hour_contemporary_seed1.epw',
    'Graz-hour_RCP2.6_2050_seed1.epw',
    'Graz-hour_RCP4.5_2050_seed1.epw',
    'Graz-hour_RCP8.5_2050_seed1.epw',
    'Graz-hour_RCP8.5_2100_seed1.epw',
    'Tripoli-hour_contemporary_seed1.epw',
    'Tripoli-hour_RCP8.5_2100_seed1.epw',
    'Wien-Hohe_Warte-hourRCP2.5_2050.epw',
    'Wien-Hohe_Warte-hourRCP4.5_2050.epw',
    'Wien-Hohe_Warte-hourRCP8.5_2050.epw',
    'Wien-Hohe_Warte-hourRCP8.5_2050_heatinsel.epw',
    'Wien-Hohe_Warte-hourRCP8.5_2100.epw',
    'Wien-Hohe_Warte-hourRCP8.5_2100_seed1.epw',
    'Wien-Hohe_Warte-hourRCP8.5_2100_seed2.epw',
    'Wien-Hohe_Warte-hourRCP_2050_heatinsel.epw',
    'Wien-Hohe_Warte-hour_contemporary.epw',
    'Wien-Hohe_Warte-hour_contemporary_seed1.epw',
    'Wien-Hohe_Warte-hour_contemporary_seed2.epw',
)


def fixture(year=2005,shift=0,city='Graz'):
    import datetime
    out=io.StringIO();w=csv.writer(out,lineterminator='\n')
    coords={'Graz':(46.983,15.450),'Vienna':(48.250,16.367),
            'Tripoli_Peloponnese_Greece':(37.527,22.412)}
    lat,lon=coords[city]
    w.writerow(['LOCATION',city,'-','-','FAKE_UNIT_TEST_NOT_METEONORM',1,lat,lon,1,342])
    for h in ('DESIGN CONDITIONS','TYPICAL/EXTREME PERIODS','GROUND TEMPERATURES',
              'HOLIDAYS/DAYLIGHT SAVINGS','COMMENTS 1','COMMENTS 2','DATA PERIODS'):
        w.writerow([h,0])
    dt=datetime.date(2001,1,1)
    for i in range(N_HOURS):
        at=dt+datetime.timedelta(days=i//24)
        t=10+shift+5*math.sin(i%24*math.pi/12)
        row=['0']*COLUMNS
        row[:5]=[year,at.month,at.day,i%24+1,60]
        row[6]=f'{t:.5f}';row[7]=f'{t-2:.5f}';row[8]='85';row[9]='97400'
        row[13]='250' if 8<=i%24<=17 else '0'
        row[14]='200' if 8<=i%24<=17 else '0'
        row[15]='50' if 8<=i%24<=17 else '0'
        row[20]='45';row[21]='2';row[33]='0'
        w.writerow(row)
    return out.getvalue().encode('utf8')


class BenchmarkMethods(unittest.TestCase):
    def test_percentiles_derive_not_index_only(self):
        self.assertEqual(percentiles([0.,10.,20.,30.,40.])['p95'],38.)
    def test_ks_identical_zero(self):
        self.assertEqual(ks_distance([3,2,1],[1,2,3]),0.)
    def test_ks_separated_one(self):
        self.assertEqual(ks_distance([1,1,1],[2,2,2]),1.)
    def test_wind_direction_north_wrap(self):
        r=wind_rose([359,1,360,180],[2,2,2,2]);self.assertEqual(r['fraction'][0],.75)
    def test_wind_calm_excluded(self):
        r=wind_rose([None,90],[0,2]);self.assertEqual(r['valid_hours'],1)
    def test_q_moistens_with_rh_and_temperature(self):
        self.assertGreater(q_air(25,80,100000),q_air(25,60,100000))
        self.assertGreater(q_air(25,60,100000),q_air(15,60,100000))
    def test_vapor_partial_pressure_over_total_blocks(self):
        with self.assertRaises(ValueError):q_air(90,100,30000)
    def test_pearson_independence_and_identity(self):
        self.assertAlmostEqual(pearson([1,2,3],[1,2,3]),1)
        self.assertIsNone(pearson([1,1,1],[1,2,3]))
    def test_dryrun_maximum(self):
        self.assertEqual(max_run([True,True,False,True]*2),3)
    def test_parser_accepts_one_correct_epw(self):
        e=read_epw(fixture(),'fake.epw');self.assertEqual(len(e['hours']['temp']),8760)
        self.assertEqual(e['year_label'],2005)
        self.assertEqual(len(monthly_metrics(e)),12)
    def test_registered_site_blocks_false_tripoli_libya(self):
        e=read_epw(fixture(city='Tripoli_Peloponnese_Greece'),'Tripoli-hour_contemporary_seed1.epw')
        verify_registered_site(e,'Tripoli_Peloponnese_Greece')
        with self.assertRaises(ValueError):verify_registered_site(e,'Graz')
    def test_parser_rejects_invalid_non_epw(self):
        with self.assertRaises(ValueError):read_epw(b'wrong','fake.epw')
    def test_parser_rejects_missing_hour(self):
        raw=fixture();lines=raw.decode().splitlines();lines.pop(200)
        with self.assertRaises(ValueError):read_epw(('\n'.join(lines)+'\n').encode(),'fake.epw')
    def test_parser_rejects_invalid_solar(self):
        raw=fixture().decode().splitlines();cols=raw[200].split(',');cols[13]='9999';raw[200]=','.join(cols)
        with self.assertRaises(ValueError):read_epw(('\n'.join(raw)+'\n').encode(),'fake.epw')
    def test_metric_conserves_hour_sum(self):
        e=read_epw(fixture(),'fake.epw');m=metric(e)
        self.assertEqual(m['hour_count'],8760)
        self.assertAlmostEqual(m['GHI_kwh_m2'],8760*10/24*250/1000,places=5)
        self.assertEqual(m['wind_dir_valid_hours'],8760)
    def test_delta_identity_zero(self):
        x=metric(read_epw(fixture(),'fake.epw'))
        self.assertTrue(all(abs(d)<1e-10 for d in observed_deltas(x,x).values()))
    def test_provenance_digests_stable(self):
        self.assertEqual(sha256(b'source'),sha256(b'source'))
        self.assertNotEqual(sha256(b'source'),sha256(b'Source'))


class FullResearchPipeline(unittest.TestCase):
    def test_registration_fail_closed_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'mn.zip';b=Path(tmp)/'ige.zip'
            with ZipFile(a,'w') as f:f.writestr('one.epw',fixture())
            with ZipFile(b,'w') as f:f.writestr('ssp245-2040-2059.epw',fixture())
            with self.assertRaises(ValueError):run(a,b,Path(tmp)/'output')

    def test_public_fixture_full_pipeline_no_raw_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'mn.zip';b=Path(tmp)/'ige.zip'
            with ZipFile(a,'w',compression=ZIP_DEFLATED) as f:
                for i,n in enumerate(NAME_MAP):
                    # Force exact duplicate pair in synthetic Vienna RCP 2100.
                    adj=13 if i==11 else 13 if i==12 else i
                    city='Vienna' if n.startswith('Wien-') else 'Tripoli_Peloponnese_Greece' if n.startswith('Tripoli') else 'Graz'
                    f.writestr(n,fixture(2005,shift=adj/100,city=city))
            with ZipFile(b,'w',compression=ZIP_DEFLATED) as f:
                for i,w in enumerate(('ssp245-2040-2059','ssp245-2080-2099',
                                        'ssp585-2040-2059','ssp585-2080-2099')):
                    f.writestr(f'outputs/fake_{w}_P7C1C.epw',fixture(2005,shift=i/5))
            result=run(a,b,Path(tmp)/'output')
            self.assertEqual(result['meteonorm_count'],18)
            self.assertEqual(result['ige_count'],4)
            self.assertEqual(len(result['method_comparisons']),3)
            self.assertEqual(len(result['duplicate_epw_sets']),1)
            with open(Path(tmp)/'output'/'p7c2_epw_monthly_aggregate_metrics.csv') as f:
                self.assertEqual(len(list(csv.DictReader(f))),22*12)
            for path in Path(tmp,'output').iterdir():
                self.assertNotIn('.epw',path.name)
                self.assertNotIn('2005,1,1,1,60',path.read_text())
            self.assertFalse(result['production_epw_ready'])
            self.assertFalse(result['external_truth_validation'])

if __name__=='__main__':unittest.main()