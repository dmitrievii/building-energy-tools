"""CPU model jobs, sealed checkpoints, paired urban panel and streamed V errors."""
from __future__ import annotations
import concurrent.futures
import csv
import gzip
import math
import os
import platform
from pathlib import Path
import time
import numpy as np
from ige_local.common import InputError,digest,file_hash,log,now,peak_rss_bytes,read_json,write_csv,write_json
from . import VERSION
from .batches import MOISTURE,Provider,columns,tuning_targets
from .config import data_config,sealed
from .engine import evaluate,nested_auxiliaries,tune
from .linear import fit
from .store import DTYPE,Lock,Store
from .urban import vectors

def code_identity():
    root=Path(__file__).parent
    paths=list(root.glob('*.py'))
    for name in ('ige_auto','ige_hum','ige_local'):paths+=list((root.parent/name).glob('*.py'))
    return digest({str(p.relative_to(root.parent)):file_hash(p) for p in sorted(paths)})

def preflight(store,c):
    ap=store.meta.get('anchor_path')
    if ap and (Path(ap).parent.parent/'C_OPENED.json').exists():raise InputError("Original C has been evaluated since preparation; do not reuse its confirmatory role")
    per_worker=100*1024**2+min(80,len(store.stations))*store.n*3*DTYPE.itemsize+c['batch_hours']*c['donors']['candidate_count']*800
    effective=min(c['workers'],max(1,c['memory_budget_bytes']//per_worker),os.cpu_count() or 1)
    if per_worker>c['memory_budget_bytes']:raise InputError("Conservative worker memory estimate exceeds budget; reduce batch_hours or use a larger memory budget")
    d=[i for i,s in enumerate(store.stations) if s['role']=='D'];v=[i for i,s in enumerate(store.stations) if s['role']=='V'];cc=[i for i,s in enumerate(store.stations) if s['role']=='C']
    out={'version':VERSION,'store_id':store.meta['store_id'],'origin':store.meta['origin'],'full_calendar_ingestion':store.meta['full_calendar_ingestion'],'station_ID_counts':{'D':len(d),'V':len(v),'C':len(cc)},'calendar_labels_per_station':{r:len(store.hours(ys)) for r,ys in c['years'].items()},'workers_requested':c['workers'],'effective_workers':int(effective),'conservative_bytes_per_worker':per_worker,'memory_budget_bytes':c['memory_budget_bytes'],'station_array_bytes_on_disk':len(store.stations)*store.n*3*DTYPE.itemsize,'urban_requests_upper_bound':len(store.stations)*6,'V_calendar_rows_upper_bound_per_model':len(v)*len(store.hours(c['years']['V'])),'tuning_target_limit_per_country':c['tuning']['targets_per_country'],'tuning_hours_per_year':c['tuning']['hours_per_month']*12,'final_fit':'all available D station-hours, no case cap or full-year gate','confirmatory_C':'not evaluated; no C command in this version','GPU_used':False}
    if len(d)<6 or not v:raise InputError("Insufficient D/V families")
    return out

class Histogram:
    def __init__(self,co):
        step=.25 if co=='T' else (1. if co=='p' else 1.)
        bound=50. if co=='T' else (100. if co=='p' else 100.)
        self.edges=np.r_[-np.inf,np.arange(-bound,bound+step*.5,step),np.inf];self.by={};self.step=step
    def add(self,station,country,error):
        a=self.by.setdefault((station,country),np.zeros(len(self.edges)-1,dtype=np.int64));a+=np.histogram(error,self.edges)[0]
    def rows(self):
        countries={c for s,c in self.by};per={c:sum(c==cc for s,cc in self.by) for c in countries};total=np.zeros(len(self.edges)-1,float);raw=np.zeros(len(total),np.int64)
        for (st,c),a in self.by.items():
            if a.sum():total+=a/a.sum()/len(countries)/per[c];raw+=a
        return [{'lower':None if not np.isfinite(lo) else float(lo),'upper':None if not np.isfinite(hi) else float(hi),'raw_count':int(n),'macro_frequency_pct':float(w*100)} for lo,hi,n,w in zip(self.edges[:-1],self.edges[1:],raw,total)]

def _job(args):
    c,storepath,runpath,m,panel,urbanpath,aux_outer,aux_full=args
    root=Path(runpath)/'models'/panel/m['id'];root.mkdir(parents=True,exist_ok=True);resultpath=root/'result.json'
    if resultpath.exists():
        r=sealed(resultpath,'result_id')
        if r['model']!=m or r['panel']!=panel:raise InputError("Saved model identity differs")
        if r['status']=='COMPLETE' and all(file_hash(root/name)==sha for name,sha in r['artifacts'].items()):return r
    start=time.monotonic();cpu=time.process_time();store=Store(storepath);urban=None
    if urbanpath:_,urban=vectors(store,urbanpath)
    provider=Provider(store,c,urban,panel=='urban_common');d=[i for i,s in enumerate(store.stations) if s['role']=='D'];v=[i for i,s in enumerate(store.stations) if s['role']=='V']
    if panel=='urban_common':d=[i for i in d if np.isfinite(urban[i]).all()];v=[i for i in v if np.isfinite(urban[i]).all()]
    sampled=tuning_targets(store,d,c['tuning']['targets_per_country'],urban if panel=='urban_common' else None);cache=Path(runpath)/'cache'/panel;cache.mkdir(parents=True,exist_ok=True)
    try:
        search=tune(provider,sampled,c['years']['D'],m['coordinate'],m['basis'],cache,'model_'+m['id'],aux_by_fold=aux_outer)
        model=fit(provider,d,d,store.hours(c['years']['D']),m['coordinate'],m['basis'],search['eta'],checkpoint=root/'full_refit')
        hist=Histogram(m['coordinate']);fieldnames=['station','timestamp_utc','month_UTC','mean_solar_hour','observed','predicted','error','common_case','native_prediction','T_aux','p_aux','observed_T','observed_RH','observed_p','QC_T','QC_RH','QC_p']
        with gzip.open(root/'V_predictions.csv.gz','wt',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fieldnames);writer.writeheader()
            def callback(b,obs,pred,native,t,p,common):
                target=store.stations[b['target']];h=b['hours'];valid=b['valid'];ok=common&np.isfinite(pred)&np.isfinite(obs)
                if ok.any():hist.add(target['key'],target['country'],pred[ok]-obs[ok])
                for j in np.flatnonzero(valid):
                    writer.writerow({'station':target['key'],'timestamp_utc':str(store.times[h[j]])+':00:00Z','month_UTC':int(store.month[h[j]]),'mean_solar_hour':float((store.hour[h[j]]+target['lon']/15)%24),'observed':float(obs[j]),'predicted':float(pred[j]) if np.isfinite(pred[j]) else '', 'error':float(pred[j]-obs[j]) if np.isfinite(pred[j]) else '', 'common_case':int(common[j]),'native_prediction':float(native[j]),'T_aux':float(t[j]) if np.isfinite(t[j]) else '', 'p_aux':float(p[j]) if np.isfinite(p[j]) else '',**{'observed_'+x:float(b['reference'][j,k]) if np.isfinite(b['reference'][j,k]) else '' for k,x in enumerate(['T','RH','p'])},**{'QC_'+x:int(b['QC'][j,k]) for k,x in enumerate(['T','RH','p'])}})
            metrics=evaluate(provider,model,v,d,store.hours(c['years']['V']),aux_full,callback)
        write_json(root/'coefficients.json',model);write_json(root/'metrics.json',metrics);write_csv(root/'histogram.csv',hist.rows(),['lower','upper','raw_count','macro_frequency_pct']);write_csv(root/'station_strata.csv',metrics['station_rows'],['station','country','stratum','N','MAE','bias','MSE'])
        status='COMPLETE' if metrics['overall']['N'] and not metrics['invalid_predictions_on_expected_mask'] else 'INVALID_OR_EMPTY_VALIDATION'
        r={'model':m,'panel':panel,'status':status,'store_id':store.meta['store_id'],'tuning_id':search['tuning_id'],'primary_macro_MAE':metrics['overall']['MAE'],'N':metrics['overall']['N'],'expected_common_cases':metrics['expected_common_cases'],'case_fingerprint':metrics['case_fingerprint'],'fit_rows':model['fit_rows'],'fit_stations':model['fit_stations'],'fit_years':model['training_years'],'wall_seconds':time.monotonic()-start,'cpu_seconds':time.process_time()-cpu,'peak_RSS_bytes':peak_rss_bytes(),'holdout_evaluated':False,'GPU_used':False,'artifacts':{p.name:file_hash(p) for p in sorted(root.iterdir()) if p.name in ('V_predictions.csv.gz','coefficients.json','metrics.json','histogram.csv','station_strata.csv')}}
    except (InputError,OSError,ValueError,np.linalg.LinAlgError) as exc:
        r={'model':m,'panel':panel,'store_id':store.meta['store_id'],'status':'FAILED','error':str(exc),'wall_seconds':time.monotonic()-start,'cpu_seconds':time.process_time()-cpu,'artifacts':{},'holdout_evaluated':False}
    r['result_id']=digest(r);write_json(resultpath,r);return r

def run(c,storepath,suite='all'):
    store=Store(storepath,verify=True)
    if store.meta['data_configuration']!=data_config(c):raise InputError("Prepared store selection differs from configuration")
    info=preflight(store,c);urbanpath=store.path/'urban/features.json';urban=None;feature_id=None
    if urbanpath.exists():
        u,urban=vectors(store,urbanpath);feature_id=u['feature_id']
        if u['radii_m']!=c['urban']['radii_m'] or u['minimum_valid_fraction']!=c['urban']['minimum_valid_fraction']:raise InputError("Urban configuration differs from frozen feature preparation")
    selected=c['models'] if suite=='all' else [m for m in c['models'] if (m['basis'].startswith('urban') or m['aux_temperature_basis'].startswith('urban'))==(suite=='urban')]
    if not selected:raise InputError("No models in requested suite")
    requires_urban=any(m['basis'].startswith('urban') or m['aux_temperature_basis'].startswith('urban') for m in selected)
    if requires_urban and urban is None:raise InputError("Run urban first, or run --suite baseline; do not invent zero urban density")
    runid=digest({'store_id':store.meta['store_id'],'configuration':{k:v for k,v in c.items() if not k.startswith('_')},'suite':suite,'code_id':code_identity(),'urban_feature_id':feature_id})
    out=Path(c['results'])/'experiments'/runid[:20];out.mkdir(parents=True,exist_ok=True)
    with Lock(out/'run.lock'):
        import scipy
        spec={'schema':'IGE_FULL_CPU_EXPERIMENT_v1','run_id':runid,'created_at_utc':now(),'code_id':code_identity(),'configuration':c,'store_id':store.meta['store_id'],'urban_feature_id':feature_id,'preflight':info,'C_evaluated':False,'runtime':{'python':platform.python_version(),'platform':platform.platform(),'numpy':np.__version__,'scipy':scipy.__version__,'BLAS_threads':{n:os.environ.get(n) for n in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')}}};write_json(out/'specification.json',spec)
        log('CPU experiment: '+str(out));write_json(out/'preflight.json',info)
        d=[i for i,s in enumerate(store.stations) if s['role']=='D'];jobs=[];aux_failures=[]
        for panel in ('all','urban_common'):
            if panel=='urban_common' and (urban is None or not requires_urban):continue
            models=[m for m in selected if (m['basis'].startswith('urban') or m['aux_temperature_basis'].startswith('urban'))==(panel=='urban_common')]
            # Every urban candidate has a baseline twin evaluated with identical donor/context availability.
            if panel=='urban_common':
                extras=[]
                for m in models:
                    if m['basis'].startswith('urban') or m['aux_temperature_basis'].startswith('urban'):
                        twin={'id':'paired_base_'+m['coordinate']+'_harmonic','coordinate':m['coordinate'],'basis':'harmonic','aux_temperature_basis':'harmonic'}
                        extras.append(twin)
                models+=list({m['id']:m for m in extras}.values())
            pd=d if panel=='all' else [i for i in d if np.isfinite(urban[i]).all()]
            sample=tuning_targets(store,pd,c['tuning']['targets_per_country'],urban if panel=='urban_common' else None);cache=out/'cache'/panel;cache.mkdir(parents=True,exist_ok=True);provider=Provider(store,c,urban,panel=='urban_common');aux={}
            for basis in sorted({m['aux_temperature_basis'] for m in models if m['coordinate'] in MOISTURE-{'RH'}}):
                try:
                    cp=cache/('shared_aux_'+basis+'.json')
                    if cp.exists():a=sealed(cp,'bundle_id');aux[basis]=( {int(k):v for k,v in a['outer'].items()},a['full'])
                    else:
                        outer,full=nested_auxiliaries(provider,sample,pd,c['years']['D'],basis,cache)
                        a={'outer':{str(k):v for k,v in outer.items()},'full':full};a['bundle_id']=digest(a);write_json(cp,a);aux[basis]=(outer,full)
                except (InputError,OSError,ValueError,np.linalg.LinAlgError) as exc:aux_failures.append({'panel':panel,'basis':basis,'error':str(exc)})
            for m in models:
                needed=m['coordinate'] in MOISTURE-{'RH'}
                if needed and m['aux_temperature_basis'] not in aux:continue
                outer,full=aux[m['aux_temperature_basis']] if needed else (None,None)
                jobs.append((c,str(store.path),str(out),m,panel,str(urbanpath) if urban is not None else None,outer,full))
        results=[]
        if info['effective_workers']==1:
            for job in jobs:
                result=_job(job);results.append(result);log(result['panel']+'/'+result['model']['id']+': '+result['status'])
        else:
            with concurrent.futures.ProcessPoolExecutor(max_workers=info['effective_workers']) as executor:
                for result in executor.map(_job,jobs):results.append(result);log(result['panel']+'/'+result['model']['id']+': '+result['status'])
        mismatches=[]
        for panel in ('all','urban_common'):
            for group in ('T','p','humidity'):
                rr=[r for r in results if r['panel']==panel and ('humidity' if r['model']['coordinate'] in MOISTURE else r['model']['coordinate'])==group and r['status']=='COMPLETE']
                if len({r['case_fingerprint'] for r in rr})>1:mismatches.append({'panel':panel,'group':group,'reason':'COMMON_CASE_FINGERPRINT_MISMATCH'})
        store.verify()
        complete=not aux_failures and not mismatches and bool(results) and all(r['status']=='COMPLETE' for r in results)
        summary={'version':VERSION,'run_id':runid,'store_id':store.meta['store_id'],'full_calendar_ingestion':store.meta['full_calendar_ingestion'],'requested_primary_models':len(selected),'model_jobs':len(jobs),'completed_jobs':sum(r['status']=='COMPLETE' for r in results),'all_requested_work_complete':complete,'auxiliary_failures':aux_failures,'paired_case_errors':mismatches,'results':results,'C_evaluated':False,'GPU_used':False,'preflight':info,'exit_code':0 if complete else 3,'scope':'Sparse original-pilot engineering replay, NOT a full Database experiment' if not store.meta['full_calendar_ingestion'] else 'Full-calendar D coefficient refit and V evaluation; tuning on declared D screening subset'}
        write_json(out/'summary.json',summary);rows=[{'panel':r['panel'],'model':r['model']['id'],'coordinate':r['model']['coordinate'],'basis':r['model']['basis'],'status':r['status'],'MAE_macro':r.get('primary_macro_MAE'),'N_common':r.get('N'),'fit_rows':r.get('fit_rows'),'fit_stations':r.get('fit_stations'),'wall_seconds':r.get('wall_seconds'),'CPU_seconds':r.get('cpu_seconds')} for r in results]
        write_csv(out/'comparison.csv',rows,list(rows[0]) if rows else ['model','status']);report(out,summary,rows)
        latest={'path':str(out.resolve()),'run_id':runid,'exit_code':summary['exit_code']}
        write_json(Path(c['results'])/'LATEST_EXPERIMENT.json',latest)
        if suite in ('baseline','urban'):write_json(Path(c['results'])/('LATEST_'+suite.upper()+'.json'),latest)
        return out,summary

def report(out,summary,rows):
    lines=['# IGE CPU 0.4 — эксперимент','',summary['scope'],'','C не оценивалась. Исходная Database не изменена. Полные годы и ручная проверка QC не являются условиями допуска.','', '| Панель | Модель | Координата | MAE | N общих случаев | Часов в обучении | Статус |','|---|---|---|---:|---:|---:|---|']
    lines += [f"| {r['panel']} | {r['model']} | {r['coordinate']} | {r['MAE_macro']} | {r['N_common']} | {r['fit_rows']} | {r['status']} |" for r in rows]
    lines += ['', 'all — все доступные допустимые станции/часы. urban_common — один и тот же набор станций, доноров и часов с реальными городскими признаками, включая baseline-двойники. Сравнивать выигрыш UHI следует внутри urban_common.','', 'Частоты выровнены по странам и станциям. Месячные таблицы содержат численность; изменение состава станций не называется чистым сезонным эффектом. Геометрия датчиков и стационарность городского окружения во времени не подтверждены.','', 'В каждом каталоге модели: coefficients.json, metrics.json, station_strata.csv, histogram.csv, V_predictions.csv.gz. QC в CSV — индексы в qc_codebook manifest.json. Ничего не обрезано до 0–100% RH. Нефинитные прогнозы на обязательной маске делают модель INVALID, а не исчезают из оценки.','', 'Видимость артефактов и полнота: '+str(summary['all_requested_work_complete']), 'Ошибки вспомогательных моделей: '+str(summary['auxiliary_failures']), 'Ошибки парных масок: '+str(summary['paired_case_errors'])]
    (out/'REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
