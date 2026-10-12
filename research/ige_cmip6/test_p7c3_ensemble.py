"""P7C.3 public synthetic regression tests; NO licensed Meteonorm or proprietary source records."""
import csv,hashlib,io,json,math,sys,tempfile,unittest,zipfile
from datetime import date,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import p7c3_ensemble as p

class Contracts(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(len(set(p.MODELS)),8)
        self.assertEqual(len(p.WINDOWS),4)
        self.assertEqual(len(p.DELTA_KEYS),9)
    def test_quantile_empirical(self):
        self.assertEqual(p.quantile([8,4,6,2],.5),5)
        self.assertEqual(p.quantile([1,3,5],.9),4.6)
    def test_quantile_incorrect_bounds(self):
        for vals,prob in [([],0.1),([1],-0.1),([1],1.1)]:
            with self.assertRaises(ValueError):p.quantile(vals,prob)
    def test_daily_delta_zero(self):
        s={'annual_T_C':10,'tasmax_p95_C':20,'annual_hot_days_30':4,
            'annual_tropical_nights_20':3,'annual_pr_mm_365_equivalent':600,
            'annual_ghi_kwh_m2_365_equivalent':1000,'avg_huss_kg_kg':.006,
            'avg_wind_ms':2,'annual_rlds_kwh_m2_365_equivalent':2700}
        d=p.delta(s,s)
        self.assertTrue(all(abs(v)<1e-12 for v in d.values()))
    def test_missing_huss_is_not_imputed(self):
        s={'annual_T_C':10,'tasmax_p95_C':20,'annual_hot_days_30':4,
            'annual_tropical_nights_20':3,'annual_pr_mm_365_equivalent':600,
            'annual_ghi_kwh_m2_365_equivalent':1000,'avg_huss_kg_kg':None,
            'avg_wind_ms':2,'annual_rlds_kwh_m2_365_equivalent':2700}
        self.assertIsNone(p.delta(s,s)['huss_delta_pct'])
    def test_annual_hot_days_not_hourly(self):
        rows=[{'year':y,'tas_c':10.,'tasmax_c':32. if i<5 else 20.,'tasmin_c':21. if i<2 else 5.,
               'rsds_kwh_m2_day':2.,'pr_mm_day':1.,'rlds_kwh_m2_day':5.,'huss':None,
               'hurs':95.,'sfcWind':2.} for y in range(2000,2020) for i in range(365)]
        q=p.summary(rows)
        self.assertEqual(q['annual_hot_days_30'],5.)
        self.assertEqual(q['annual_tropical_nights_20'],2.)
        self.assertIsNone(q['avg_huss_kg_kg'])
        self.assertAlmostEqual(q['annual_ghi_kwh_m2_365_equivalent'],730)
    def test_ensemble_uses_one_member_per_model(self):
        rows=[]
        for w in p.WINDOWS:
            for i,m in enumerate(p.MODELS):
                rows.append({'window':w,'model':m,**{k:(None if k=='huss_delta_pct' and m=='IPSL-CM6A-LR' else float(i)) for k in p.DELTA_KEYS}})
        e=p.aggregate(rows)
        self.assertEqual(len(e),4)
        self.assertEqual(e[0]['temp_delta_C_p50'],3.5)
        self.assertAlmostEqual(e[0]['temp_delta_C_p10'],0.7)
        self.assertEqual(e[0]['huss_delta_pct_n_models'],7)
        self.assertEqual(e[0]['huss_delta_pct_models_missing'],'IPSL-CM6A-LR')
        self.assertEqual(e[0]['canesm5_temp_rank_ascending_1_to_8'],2)
        self.assertEqual(e[0]['quantile_type'],'EMPIRICAL_INTERMODEL_NOT_PROBABILISTIC')
    def test_missing_gcm_disallowed(self):
        rows=[{'window':w,'model':m,**{k:0. for k in p.DELTA_KEYS}} for w in p.WINDOWS for m in p.MODELS]
        with self.assertRaises(ValueError):p.aggregate(rows[1:])
    def test_seven_gcms_cannot_claim_eight(self):
        rows=[{'window':w,'model':m,**{k:1. for k in p.DELTA_KEYS}} for w in p.WINDOWS for m in p.MODELS]
        rows[0]['huss_delta_pct']=None;rows[1]['huss_delta_pct']=None;rows[2]['huss_delta_pct']=None
        with self.assertRaises(ValueError):p.aggregate(rows)
    def test_source_calendar_years(self):
        self.assertEqual(date(2048,12,31).timetuple().tm_yday,366)
        self.assertEqual(date(2049,12,31).timetuple().tm_yday,365)
    def _build_zip(self,dest,model='CanESM5',calendar='noleap',missing_huss=False,undocumented=False,over_hurs=False):
        start=date(1995,1,1);end=date(2015,1,1);rows=[];cur=start
        while cur<end:
            if calendar=='gregorian' or (cur.month,cur.day)!=(2,29):
                rows.append({'scenario':'historical','year':cur.year,'month':cur.month,'day':cur.day,
                  'date':cur.isoformat(),'model':model,'member':'r1i1p1f1',
                  'tas_c':10.,'tasmax_c':15.,'tasmin_c':5.,'hurs':101. if over_hurs and cur==start else 70.,
                  'huss':'' if missing_huss else .006,'pr_mm_day':1.2,
                  'rsds_kwh_m2_day':3.,'rlds_kwh_m2_day':6.,'sfcWind':2.})
            cur+=timedelta(days=1)
        sink=io.StringIO();w=csv.DictWriter(sink,fieldnames=rows[0].keys(),lineterminator='\n');w.writeheader();w.writerows(rows)
        b=sink.getvalue().encode();s=p.digest(b)
        q={'status':'PASS','model':model,'member':'r1i1p1f1','window':p.HIST,'grid':list(p.LAT_LON),'calendar':calendar,
           'days':len(rows),'years':20,'csv_sha256':{'joint_daily_raw.csv':s}}
        prov={'status':'PASS','model':model,'member':'r1i1p1f1','window':p.HIST,'site':[46.983,15.45],
          'missing_source_variables':(['huss'] if missing_huss and not undocumented else []),
          'csv_sha256':{'joint_daily_raw.csv':s}}
        with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('joint_daily_raw.csv',b)
            z.writestr('quality_report.json',json.dumps(q))
            z.writestr('source_provenance.json',json.dumps(prov))
    def test_noleap_imm_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'f.zip';self._build_zip(f)
            data,pro=p.read_source(f,'CanESM5',p.HIST)
            self.assertEqual(len(data),7300)
            self.assertEqual(pro['calendar'],'noleap')
    def test_gregorian_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'f.zip';self._build_zip(f,calendar='gregorian')
            d,pro=p.read_source(f,'CanESM5',p.HIST)
            self.assertEqual(len(d),7305)
            self.assertEqual(pro['calendar'],'gregorian')
    def test_missing_huss_must_be_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'f.zip';self._build_zip(f,missing_huss=True,undocumented=True)
            with self.assertRaisesRegex(ValueError,'Undeclared missing'):
                p.read_source(f,'CanESM5',p.HIST)
    def test_missing_huss_declared_stays_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'f.zip';self._build_zip(f,missing_huss=True)
            d,pro=p.read_source(f,'CanESM5',p.HIST)
            self.assertTrue(all(x['huss'] is None for x in d))
            self.assertEqual(pro['original_variable_census']['huss_missing'],7300)
    def test_hurs_over_100_not_clipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'f.zip';self._build_zip(f,over_hurs=True)
            d,pro=p.read_source(f,'CanESM5',p.HIST)
            self.assertIsNone(d[0]['hurs'])
            self.assertEqual(pro['original_variable_census']['hurs_outside_0_100'],1)
    def test_sha_modified_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'f.zip';self._build_zip(f)
            with zipfile.ZipFile(f,'a') as z:z.writestr('joint_daily_raw.csv',b'corrupted')
            with self.assertRaises(ValueError):p.read_source(f,'CanESM5',p.HIST)
    def test_wrong_model_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'f.zip';self._build_zip(f)
            with self.assertRaises(ValueError):p.read_source(f,'GFDL-ESM4',p.HIST)
    def test_missing_file_rejected(self):
        with self.assertRaises(ValueError):p.read_source('/tmp/surely-no-file-in-here.zip','CanESM5',p.HIST)
    def test_monthly_signal_count(self):
        rows=[]
        for y in range(2000,2020):
            d=date(y,1,1)
            while d.year==y:
                if not (d.month==2 and d.day==29):
                    rows.append({'year':y,'month':d.month,'tas_c':10.,'tasmax_c':16.,'tasmin_c':4.,'huss':.005,
                      'pr_mm_day':2.,'rsds_kwh_m2_day':2.4,'rlds_kwh_m2_day':7.,'sfcWind':1.5})
                d+=timedelta(days=1)
        f=[dict(r,tas_c=r['tas_c']+2, tasmax_c=r['tasmax_c']+2,tasmin_c=r['tasmin_c']+2) for r in rows]
        vals=p.monthly_signals(rows,f,'CanESM5',p.WINDOWS[0]);self.assertEqual(len(vals),12)
        self.assertTrue(all(abs(q['tas_delta_C']-2)<1e-9 for q in vals))
        self.assertTrue(all(abs(q['ghi_ratio']-1)<1e-9 for q in vals))

if __name__=='__main__':unittest.main()