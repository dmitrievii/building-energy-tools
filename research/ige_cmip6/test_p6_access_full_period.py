"""Offline science contracts for five 20-year P6.1 ACCESS-CM2 windows."""
import unittest
from p6_access_full_period import WINDOWS, summarize_daily, compare_p5_ghi, sha256, MODEL, MEMBER
import json
from pathlib import Path

def synthetic(year, scenario):
    rows=[]
    for month in range(1,13):
        rows.append({'scenario':scenario,'year':year,'month':month,
                     'rsds_kwh_m2_day':2.0,'rlds_kwh_m2_day':3.0,
                     'pr_mm_day':1.0,'tas_c':10.0,'hurs':65.0,
                     'huss':0.006,'sfcWind':2.0})
    return rows

class FullPeriodContract(unittest.TestCase):
    def test_five_nonoverlapping_windows(self):
        self.assertEqual(len(WINDOWS),5)
        groups={}
        for key,(scenario,start,end) in WINDOWS.items():
            self.assertEqual(end-start+1,20)
            for year in range(start,end+1):
                self.assertNotIn((scenario,year),groups)
                groups[(scenario,year)]=key
        self.assertEqual(len(groups),100)

    def test_monthly_annual_energy_conservation(self):
        rows=synthetic(2013,'historical')+synthetic(2014,'historical')
        mm,aa,cc=summarize_daily(rows,'historical-1995-2014','historical',(2013,2014))
        self.assertEqual((len(mm),len(aa),len(cc)),(24,2,12))
        self.assertAlmostEqual(aa[0]['ghi_kwh_m2'],24.)
        self.assertAlmostEqual(aa[0]['pr_mm'],12.)
        self.assertAlmostEqual(cc[0]['ghi_mean_kwh_m2'],2.)
        self.assertEqual(cc[0]['years'],2)

    def test_missing_month_blocks_closeout(self):
        rows=synthetic(2014,'historical')
        rows=rows[1:]
        with self.assertRaisesRegex(ValueError,'Missing or extra'):
            summarize_daily(rows,'historical-1995-2014','historical',(2014,))

    def test_mixed_scenario_is_rejected(self):
        rows=synthetic(2014,'historical')
        rows[0]['scenario']='ssp245'
        with self.assertRaisesRegex(ValueError,'contamination'):
            summarize_daily(rows,'historical-1995-2014','historical',(2014,))

    def test_p5_monthly_reference_and_sensitive_tolerance(self):
        source=json.loads(Path(__file__).with_name('p6_access_p5_solar_reference.json').read_text())
        self.assertEqual(source['model'],MODEL)
        self.assertEqual(source['member'],MEMBER)
        self.assertEqual(set(source['windows']),set(WINDOWS))
        for key in WINDOWS:
            x=source['windows'][key]
            self.assertEqual(len(x),12)
            climo=[{'month':i+1,'ghi_mean_kwh_m2':v} for i,v in enumerate(x)]
            self.assertEqual(compare_p5_ghi(key,climo)['status'],'PASS')
            climo[0]['ghi_mean_kwh_m2']+=0.01
            with self.assertRaisesRegex(ValueError,'P5 solar regression mismatch'):
                compare_p5_ghi(key,climo)

if __name__=='__main__':
    unittest.main()
