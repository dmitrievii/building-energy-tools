"""Synthetic numerical contracts and native-layout integration; no weather claims."""
import copy
import csv
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from ige_local.common import HOUR,UTC,InputError,digest,file_hash,iso,read_json,write_json
from ige_full.config import anchor,data_config,load
from ige_full.store import DTYPE,Store,_init_station,assign,merge,prepare,recover_pending
from ige_full.batches import Provider,columns,dewpoint,features,restored,tuning_hours
from ige_full.linear import Metrics,fit
from ige_full.engine import evaluate,folds,tune,nested_auxiliaries
from ige_full.study import Histogram,preflight,run
from ige_full.urban import buffer_request,histogram,collect,vectors
from ige_auto.data import buck_water
from support import make_at,files_unchanged_state

def configuration(base):
    c=read_json(ROOT/'config_full_cpu.json');base=Path(base);(base/'Database').mkdir(exist_ok=True)
    c.update(database=str(base/'Database'),results=str(base/'results'),countries=['AT'],years={'D':[2019,2020,2021],'V':[2023],'C':[2025]},anchor_cube_id='',workers=1,batch_hours=744,memory_budget_bytes=512*1024**2)
    c['tuning'].update(hours_per_month=24,targets_per_country=24,max_evaluations=30,max_iterations=10,starts=1,min_fit_cases=20,ridge_lambda=1e-7)
    c['donors'].update(radius_km=500,candidate_count=24,max_donors=12,max_height_difference_m=5000)
    c['models']=[{'id':'T_height','coordinate':'T','basis':'height','aux_temperature_basis':'harmonic'}];c['_config_path']=str(base/'config.json')
    return c

def synthetic_store(base,c,urban=False):
    root=Path(base)/'store';root.mkdir(exist_ok=True);start=dt.datetime(2019,1,1,tzinfo=UTC);n=int((dt.datetime(2026,1,1,tzinfo=UTC)-start)/HOUR)
    stations=[];files={};hashes={};hours=[]
    for y in (2019,2020,2021,2023,2025):
        for m in (1,4,7,10):
            for h in range(24):hours.append(int((dt.datetime(y,m,31 if m in (1,7,10) else 30,h,tzinfo=UTC)-start)/HOUR))
    hours=np.array(hours)
    for i in range(18):
        s={'key':'AT:'+str(100+i),'country':'AT','station_id':str(100+i),'network':'','name':'SYNTHETIC','family':'AT:family:'+str(i),'lat':47+i*.015,'lon':14+i*.07,'height_m':200+i*70,'role':'D' if i<12 else ('V' if i<15 else 'C'),'fold':i%3,'station_type':'INDIVIDUAL','geometry_role':'synthetic'}
        stations.append(s);name='stations/'+str(i)+'.npy';files[s['key']]=name;_init_station(root/name,n);a=np.load(root/name,mmap_mode='r+')
        for h in hours:
            t=10+4*np.sin((h%24)*2*np.pi/24)-6.3*s['height_m']/1000;p=1015-103*s['height_m']/1000;rh=65.
            for j,x in enumerate([t,rh,p]):a[h,j]=(x,j+1,1,1,0,False)
        a.flush();del a;hashes[name]=file_hash(root/name)
    meta={'schema':'IGE_FULL_CPU_STORE_v1','origin':'SYNTHETIC_NOT_WEATHER','full_calendar_ingestion':False,'source_calendar_hours':hours.tolist(),'start':iso(start),'n_hours':n,'years':c['years'],'stations':stations,'files':files,'station_hashes':hashes,'operator_codebook':['unknown','T','RH','p'],'qc_codebook':[{'code':'missing','country':'AT'},{'code':'0','stratum':'unchecked','country':'AT'}],'source_codebook':[{},{}],'qc_mode':c['qc_mode'],'rejected_native_qc':c['rejected_native_qc'],'data_configuration':data_config(c)}
    meta['store_id']=digest(meta);write_json(root/'manifest.json',meta);return Store(root)

class FullCPU(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.base=Path(cls.tmp.name);cls.c=configuration(cls.base);cls.store=synthetic_store(cls.base,cls.c)
    @classmethod
    def tearDownClass(cls):cls.store.close();cls.tmp.cleanup()
    def test_analytic_buck_inverse(self):
        x=np.linspace(-80,50,500);self.assertLess(np.max(abs(dewpoint(buck_water(x))-x)),1e-10)
        self.assertTrue(np.isnan(dewpoint(np.array([-1.,0.,1e10]))).all())
    def test_month_end_leap_and_unchecked_are_not_gated(self):
        s=self.store;h=int((dt.datetime(2020,1,31,tzinfo=UTC)-s.start)/HOUR);v,op,ok,qc=s.read(0,np.array([h]));self.assertTrue(ok.all());self.assertEqual(int(qc[0,0]),1)
        self.assertEqual(len(s.hours([2020])),8784);self.assertEqual(len(s.hours([2019])),8760)
    def test_streaming_fit_uses_all_available_hours(self):
        c=self.c;s=self.store;d=list(range(12));p=Provider(s,c);h=s.hours(c['years']['D']);m=fit(p,d,d,h,'T','height',[2,0,-16])
        self.assertEqual(m['fit_rows'],12*3*4*24);self.assertAlmostEqual(m['coefficients'][0],-6.3,places=5)
        self.assertEqual(m['training_years'],[2019,2020,2021])
    def test_donor_excludes_target_family(self):
        p=Provider(self.store,self.c);d=list(range(12));self.assertNotIn(0,p.neighbours(0,d));self.assertIn(1,p.neighbours(0,d))
    def test_C_is_blocked_by_family_and_year(self):
        p=Provider(self.store,self.c);d=list(range(12))
        for targets,hours in [([15],self.store.hours([2023])),([12],self.store.hours([2025]))]:
            with self.assertRaises(InputError):next(p.blocks(targets,d,hours,'T','height',[2,0,-16]))
        with self.assertRaises(InputError):fit(p,[12],d,self.store.hours([2019]),'T','height',[2,0,-16])
    def test_all_nested_folds_exclude_families_and_years(self):
        s=self.store
        for outer in folds(s,list(range(12)),[2019,2020,2021],3,9):
            self.assertFalse(set(outer['train'])&set(outer['valid']));self.assertFalse(set(outer['train_years'])&set(outer['valid_years']))
            for inner in folds(s,outer['train'],outer['train_years'],2,99):
                self.assertTrue(set(inner['train']+inner['valid'])<=set(outer['train']));self.assertFalse(set(inner['train_years']+inner['valid_years'])&set(outer['valid_years']))
    def test_continuous_tuning_is_D_only(self):
        p=Provider(self.store,self.c)
        with tempfile.TemporaryDirectory() as b:
            a=tune(p,list(range(12)),[2019,2020,2021],'T','height',b,'test')
            self.assertEqual(a['status'],'CONVERGED');self.assertLess(a['objective'],1e-4)
            self.assertTrue(all('C' not in f['train_families'] for f in a['folds']))
    def test_streamed_validation_macro_matches_direct_error(self):
        p=Provider(self.store,self.c);d=list(range(12));m=fit(p,d,d,self.store.hours([2019,2020,2021]),'T','height',[2,0,-16]);r=evaluate(p,m,[12,13,14],d,self.store.hours([2023]))
        self.assertEqual(r['overall']['N'],3*4*24);self.assertLess(r['overall']['MAE'],1e-4);self.assertEqual(r['invalid_predictions_on_expected_mask'],0)
    def test_all_five_humidity_routes_share_identical_reference_cases(self):
        s=self.store;p=Provider(s,self.c);d=list(range(12));h=s.hours([2019,2020,2021]);eta=[2,0,-16]
        aux={co:fit(p,d,d,h,co,'height',eta) for co in ('T','p')};ids=[]
        for co in ('RH','log_e','q','Td','D'):
            model=fit(p,d,d,h,co,'height',eta);r=evaluate(p,model,[12,13,14],d,s.hours([2023]),aux)
            self.assertEqual(r['invalid_predictions_on_expected_mask'],0);self.assertEqual(r['expected_common_cases'],288);ids.append(r['case_fingerprint'])
        self.assertEqual(len(set(ids)),1)
    def test_nested_auxiliary_engine_executes_and_never_sees_outer_holdout(self):
        p=Provider(self.store,self.c);d=list(range(12))
        with tempfile.TemporaryDirectory() as b:
            outer,full=nested_auxiliaries(p,d,d,[2019,2020,2021],'height',b)
            self.assertEqual(set(outer),{0,1,2});self.assertEqual(set(full),{'T','p'})
            for f in folds(self.store,d,[2019,2020,2021],3,self.c['seed']):
                for model in outer[f['fold']].values():
                    self.assertFalse(set(model['training_families'])&{self.store.stations[i]['family'] for i in f['valid']})
                    self.assertFalse(set(model['training_years'])&set(f['valid_years']))
    def test_urban_and_paired_baseline_share_cases(self):
        s=self.store;u=np.random.default_rng(5).random((18,8));u[11]=np.nan;p=Provider(s,self.c,u,True);d=list(range(12));h=s.hours([2019,2020,2021]);ids=[]
        for basis in ('harmonic','urban_static','urban_harmonic'):
            m=fit(p,d,d,h,'T',basis,[2,0,-16]);r=evaluate(p,m,[12,13,14],d,s.hours([2023]));ids.append(r['case_fingerprint'])
        self.assertEqual(len(set(ids)),1)
    def test_RH_prediction_is_not_clipped(self):
        a=restored('RH',np.array([-5.,120.]),np.array([10.,10.]),np.array([1000.,1000.]));self.assertEqual(a.tolist(),[-5.,120.])
    def test_direct_RH_does_not_require_auxiliary_models(self):
        p=Provider(self.store,self.c);d=list(range(12));m=fit(p,d,d,self.store.hours([2019,2020,2021]),'RH','height',[2,0,-16]);r=evaluate(p,m,[12,13,14],d,self.store.hours([2023]),aux=None);self.assertEqual(r['overall']['N'],288);self.assertLess(r['overall']['MAE'],1e-10)
    def test_nonfinite_predictions_are_counted(self):
        m=Metrics();m.add('s','AT',np.array([1,1]),np.array([0,0]),np.array([1.,2]),np.array([np.nan,3.]),np.array([True,True]));r=m.report();self.assertEqual(r['invalid_predictions_on_expected_mask'],1)
    def test_histogram_keeps_tails(self):
        h=Histogram('RH');h.add('s','AT',np.array([-150.,0.,200.]));r=h.rows();self.assertEqual(sum(x['raw_count'] for x in r),3);self.assertEqual(r[0]['raw_count'],1);self.assertEqual(r[-1]['raw_count'],1)
    def test_urban_shape_and_difference(self):
        s=self.store;h=s.hours([2019])[:24];u=np.arange(18*8).reshape(18,8)/144
        for basis in ('height','monthly','harmonic','urban_static','urban_harmonic'):
            a=features(s.stations[:2],h,s,basis,u[:2]);self.assertEqual(a.shape,(24,2,columns(basis)))
    def test_missing_urban_is_not_zero(self):
        u=np.full((18,8),np.nan);p=Provider(self.store,self.c,u,True);self.assertEqual(p.neighbours(0,list(range(12))),[])
    def test_urban_histograms_keep_zero_and_exclude_nodata(self):
        r={'histograms':[{'size':256,'min':-.5,'max':255.5,'counts':[10]+[0]*49+[10]+[0]*203+[100,100]}]}
        a=histogram(r,20,.9);self.assertAlmostEqual(a['fraction'],.25);self.assertTrue(a['valid'])
        count=np.zeros(256,int);count[0]=10;count[1]=2;count[2]=3;count[3]=4;count[4]=1;count[254]=100
        r['histograms'][0]['counts']=count.tolist();a=histogram(r,20,.9,'water');self.assertEqual(a['fraction'],.25);self.assertEqual(a['wet_fraction'],.25)
    def test_urban_buffer_ground_scale_and_errors(self):
        r=buffer_request(47.,15.,500);self.assertAlmostEqual(r['expected_grid_cells'],np.pi*500**2/100,delta=30)
        with self.assertRaises(InputError):histogram({'error':{'code':500}},100,.9)
        with self.assertRaises(InputError):histogram({'histograms':[{'size':1,'min':0,'max':255,'counts':[1]}]},100,.9)
    def test_priority_conflicts_and_better_source(self):
        a=np.zeros((1,3),dtype=DTYPE);a['value']=np.nan;a['priority']=127;counter=__import__('collections').Counter()
        merge(a,0,0,1,1,1,1,1,counter);merge(a,0,0,2,1,1,2,1,counter);self.assertTrue(a[0,0]['conflict'])
        merge(a,0,0,3,1,1,3,0,counter);self.assertFalse(a[0,0]['conflict']);self.assertEqual(a[0,0]['value'],3.)
    def test_pending_commit_rolls_back_atomically(self):
        with tempfile.TemporaryDirectory() as b:
            p=Path(b);(p/'station.npy').write_bytes(b'new');(p/'part.backup.npy').write_bytes(b'old');write_json(p/'pending.json',{'part':'x','final':'station.npy','existed':True});recover_pending(p,{'done':{}});self.assertEqual((p/'station.npy').read_bytes(),b'old')
    def test_full_refit_checkpoints_resume_and_detect_tampering(self):
        p=Provider(self.store,self.c);d=list(range(12));h=self.store.hours([2019,2020,2021])
        with tempfile.TemporaryDirectory() as b:
            a=fit(p,d,d,h,'T','height',[2,0,-16],b)
            with patch.object(p,'blocks',side_effect=AssertionError('saved station QR must be reused')):
                again=fit(p,d,d,h,'T','height',[2,0,-16],b)
            self.assertEqual(a,again);path=next(Path(b).glob('*.npz'));path.write_bytes(b'corrupt')
            with self.assertRaises(InputError):fit(p,d,d,h,'T','height',[2,0,-16],b)
    def test_urban_collection_resume_and_frozen_raw_bytes(self):
        s=self.store;c=copy.deepcopy(self.c);c['urban']['seconds_between_requests']=.5;calls=[]
        def fetch(request):
            calls.append(request);n=round(request['expected_grid_cells']);counts=[n]
            return json.dumps({'histograms':[{'size':1,'min':-.5,'max':.5,'counts':counts}]}).encode()
        with patch('ige_full.urban.time.sleep'):
            path=collect(c,s.path,fetch);a,u=vectors(s,path);self.assertEqual(u.shape,(18,8));self.assertTrue(np.isfinite(u).all());n=len(calls)
            self.assertEqual(collect(c,s.path,fetch),path);self.assertEqual(len(calls),n)
            raw=path.parent/a['rows'][0]['raw_relative_path'];old=raw.read_bytes();raw.write_bytes(b'corrupt')
            try:
                with self.assertRaises(InputError):vectors(s,path)
            finally:raw.write_bytes(old)
    def test_parallel_model_jobs_and_completed_resume(self):
        c=copy.deepcopy(self.c);c['results']=str(self.base/'parallel_results');c['workers']=2;c['models'] += [{'id':'p_height','coordinate':'p','basis':'height','aux_temperature_basis':'harmonic'}]
        out,summary=run(c,self.store.path,suite='baseline');self.assertEqual(summary['exit_code'],0);self.assertEqual(summary['completed_jobs'],2)
        from ige_full.plots import create
        self.assertTrue(create(out));out2,r=run(c,self.store.path,suite='baseline');self.assertEqual(out,out2);self.assertEqual(r['completed_jobs'],2)
    def test_complete_humidity_pipeline_with_nested_auxiliaries(self):
        c=copy.deepcopy(self.c);c['results']=str(self.base/'humidity_pipeline');c['tuning'].update(max_evaluations=100,max_iterations=30);c['models']=[{'id':'H_log_e','coordinate':'log_e','basis':'height','aux_temperature_basis':'height'}]
        out,s=run(c,self.store.path,suite='baseline');self.assertEqual(s['exit_code'],0);self.assertEqual(s['completed_jobs'],1);self.assertFalse(s['C_evaluated'])
        r=s['results'][0];self.assertEqual(r['N'],288);self.assertEqual(r['fit_rows'],3456)
    def test_roles_of_original_C_and_new_alias_are_preserved(self):
        c=self.c;old={'stations':self.store.stations,'family_roles':{s['family']:s['role'] for s in self.store.stations}}
        alias=dict(self.store.stations[-1],key='AT:newalias',family='AT:newfamily');st,roles,folds_=assign([dict(s) for s in self.store.stations]+[alias],old,c)
        self.assertEqual(next(s for s in st if s['key']=='AT:newalias')['role'],'C')
    def test_native_prepare_full_calendar_and_resume(self):
        with tempfile.TemporaryDirectory() as b:
            base=Path(b);c=configuration(base);native,p=make_at(base/'Database',nsites=18,hours=48,start='2020-02-28T00:00:00Z')
            from ige_local.audit import stations_for
            stations=stations_for('AT',p);roles={s['family']:'D' if i<12 else ('V' if i<15 else 'C') for i,s in enumerate(stations)}
            old={'schema':'IGE_AUTO_SPLIT_v1','stations':stations,'family_roles':roles,'times':['2019-01-01T00:00:00Z','2023-01-01T00:00:00Z','2025-01-01T00:00:00Z'],'time_roles':['D','V','C']};old['split_id']=digest(old)
            cp=base/'old/cube';write_json(cp/'split.sealed.json',old);write_json(cp/'metadata.json',{'cube_id':'fixture'});c['cohort_anchor']=str(cp/'split.sealed.json')
            before=files_unchanged_state(base/'Database');path=prepare(c);s=Store(path,verify=True);self.assertEqual(len(s.stations),18);self.assertTrue(s.meta['full_calendar_ingestion']);h=int((dt.datetime(2020,2,29,23,tzinfo=UTC)-s.start)/HOUR);self.assertTrue(s.read(0,np.array([h]))[2].all());self.assertEqual(before,files_unchanged_state(base/'Database'));self.assertEqual(prepare(c),path);s.close()
    def test_config_rejects_D_C_overlap_and_GPU_option(self):
        with tempfile.TemporaryDirectory() as b:
            c=configuration(b);c.pop('_config_path');c['cohort_anchor']='auto';path=Path(b)/'config.json';write_json(path,c);self.assertEqual(load(path)['workers'],1)
            c['years']['D'].append(2025);write_json(path,c)
            with self.assertRaises(InputError):load(path)
            c['years']['D'].remove(2025);c['gpu']=True;write_json(path,c)
            with self.assertRaises(InputError):load(path)

if __name__=='__main__':unittest.main()
