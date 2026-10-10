"""P6.2A offline science contracts: never change NASA observations or overclaim station skill."""
from __future__ import annotations
import csv
import datetime as dt
import math
import tempfile
from pathlib import Path
import unittest

from p6_2a_joint_diagnostics import (
    pearson, quantile, audit_period, compare, load_daily,
)
from p6_2a_geosphere_monthly import extract_monthly, compare_monthly

def synthetic_daily(role='historical',model='ACCESS-CM2'):
    rows=[]
    years=range(1995,2015) if role=='historical' else range(2080,2100)
    for year in years:
        for j in range(365):
            when=dt.date(2001,1,1)+dt.timedelta(days=j)
            month,day=when.month,when.day
            rows.append({
                'model':model,'member':'r1i1p1f1',
                'scenario':'historical' if role=='historical' else 'ssp585',
                'year':year,'month':month,'day':day,
                'date':f'{year}-{month:02d}-{day:02d}',
                'tas_c':10.+month*.5+(3 if role=='future' else 0),
                'tasmax_c':16.+month*.5+(3 if role=='future' else 0),
                'tasmin_c':4.+month*.5+(3 if role=='future' else 0),
                'hurs':100.2 if j==0 else 67.+math.sin(j/11),
                'pr_mm_day':5. if j%7==0 else 0.,
                'rsds_kwh_m2_day':max(.1,3.+math.sin(j/19)),
                'rlds_kwh_m2_day':7.+math.sin(j/27),
                'sfcWind':1.7+math.sin(j/15),
                'huss':.005
            })
    return rows

def synthetic_provider():
    stamp=[f'{year:04d}-{month:02d}-01T00:00+00:00'
           for year in range(1995,2015) for month in range(1,13)]
    return {'timestamps':stamp,'features':[{
        'properties':{'station':30,'parameters':{
            'tl_mittel':{'unit':'°C','data':[10.]*240},
            'rr':{'unit':'mm','data':[60.]*240}
        }}
    }]}

class JointClimateScienceContract(unittest.TestCase):
    def test_pearson_constant_is_undefined(self):
        self.assertIsNone(pearson([{'x':1,'y':2}]*40,'x','y'))
        self.assertIsNone(pearson([{'x':j,'y':j} for j in range(5)],'x','y'))

    def test_temperature_delta_not_day_to_day_rmse(self):
        a=audit_period(synthetic_daily('historical'),'historical')
        b=audit_period(synthetic_daily('future'),'future')
        self.assertEqual(a['days'],7300)
        self.assertEqual(b['days'],7300)
        self.assertAlmostEqual(compare(a,b)['tas_annual_mean_change_c'],3.0)
        self.assertEqual(a['raw_hurs_above_100'],20)
        self.assertEqual(len(a['seasons']),4)

    def test_raw_hurs_exceedance_not_adjusted(self):
        rows=synthetic_daily()
        audit=audit_period(rows,'historical')
        self.assertAlmostEqual(audit['raw_hurs_max'],100.2)
        self.assertEqual(rows[0]['hurs'],100.2)

    def test_bad_source_identity_rejected(self):
        rows=synthetic_daily()
        rows[0]['model']='Other-GCM'
        with self.assertRaisesRegex(ValueError,'mixed source identity'):
            audit_period(rows,'historical')

    def test_duplicate_date_rejected(self):
        rows=synthetic_daily()
        rows[1]['date']=rows[0]['date']
        with self.assertRaisesRegex(ValueError,'Unsorted/duplicated'):
            audit_period(rows,'historical')

    def test_model_member_mismatch_rejected(self):
        a=audit_period(synthetic_daily(),'historical')
        b=audit_period(synthetic_daily('future','Different'),'future')
        with self.assertRaisesRegex(ValueError,'Different model'):
            compare(a,b)

    def test_observed_station_monthly_full_coverage(self):
        obs=extract_monthly(synthetic_provider())
        self.assertEqual(len(obs),240)
        self.assertEqual(obs[0]['year'],1995)
        self.assertEqual(obs[-1]['month'],12)

    def test_observed_station_missing_values_reported(self):
        p=synthetic_provider()
        p['features'][0]['properties']['parameters']['rr']['data'][0]=None
        rows=extract_monthly(p)
        self.assertIsNone(rows[0]['obs_pr_mm'])

    def test_station_vs_model_climatology_not_daily_fit(self):
        obs=extract_monthly(synthetic_provider())
        with tempfile.TemporaryDirectory() as directory:
            f=Path(directory)/'climo.csv'
            with f.open('w',newline='') as stream:
                w=csv.DictWriter(stream,fieldnames=['window','scenario','years','month','tas_mean_c','pr_mean_mm'])
                w.writeheader()
                for month in range(1,13):
                    w.writerow({'window':'historical-1995-2014','scenario':'historical',
                                'years':20,'month':month,'tas_mean_c':11.,'pr_mean_mm':65.})
            out=compare_monthly(obs,f)
        self.assertAlmostEqual(out['temperature_monthly_climatology_mae_c'],1.)
        self.assertAlmostEqual(out['station_annual_mean_monthly_precip_total_mm'],720.)
        self.assertAlmostEqual(out['model_annual_mean_monthly_precip_total_mm'],780.)

    def test_wrong_geosphere_monthly_unit_rejected(self):
        p=synthetic_provider()
        p['features'][0]['properties']['parameters']['tl_mittel']['unit']='K'
        with self.assertRaisesRegex(ValueError,'units invalid'):
            extract_monthly(p)

if __name__=='__main__':unittest.main()
