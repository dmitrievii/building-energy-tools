"""Continuous D-only tuning and reusable nested auxiliary T/p models."""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
import time
import numpy as np
from scipy.optimize import minimize
from ige_local.common import InputError,digest,log,read_json,write_json
from .batches import MOISTURE,Provider,restored,tuning_hours,tuning_targets
from .config import sealed
from .linear import Metrics,fit,predict
from .store import Lock

def folds(store,targets,years,k,seed):
    groups={}
    for country in sorted({store.stations[i]['country'] for i in targets}):
        families=sorted({store.stations[i]['family'] for i in targets if store.stations[i]['country']==country},key=lambda f:digest([seed,f]))
        groups.update({f:j%k for j,f in enumerate(families)})
    for f in range(k):
        train=[i for i in targets if groups[store.stations[i]['family']]!=f];valid=[i for i in targets if groups[store.stations[i]['family']]==f]
        ty=[y for j,y in enumerate(sorted(years)) if j%k!=f];vy=[y for j,y in enumerate(sorted(years)) if j%k==f]
        if not train or not valid or not ty or not vy:raise InputError("Insufficient independent families/years for nested validation")
        yield {'fold':f,'train':train,'valid':valid,'train_years':ty,'valid_years':vy}

def at(provider,model,target,donors,hours):
    out=np.full(len(hours),np.nan);lookup={int(h):i for i,h in enumerate(hours)}
    for b in provider.blocks([target],donors,hours,model['coordinate'],model['basis'],model['eta']):
        mask=b['valid'];ix=np.array([lookup[int(h)] for h in b['hours'][mask]])
        out[ix]=predict(model,b)[mask]
    return out

def evaluate(provider,model,targets,donors,hours,aux=None,callback=None,detail=True):
    own=Metrics(detail);common=Metrics(detail);store=provider.store;casehash=hashlib.sha256();common_n=0
    for b in provider.blocks(targets,donors,hours,model['coordinate'],model['basis'],model['eta']):
        native_pred=predict(model,b);co=model['coordinate'];h=b['hours'];st=store.stations[b['target']]
        t=p=np.full(len(h),np.nan)
        if co in MOISTURE:
            if aux is None and co!='RH':raise InputError("Missing frozen auxiliary T/p models")
            if aux is not None:
                t=at(provider,aux['T'],b['target'],donors,h);p=at(provider,aux['p'],b['target'],donors,h)
            pred=restored(co,native_pred,t,p);observed=b['reference'][:,1]
            expected=b['valid']&b['common'];own_mask=b['valid']
            if co!='RH':
                # Do not silently remove broken predictions from common accuracy.
                good_aux=np.isfinite(t)&(t>-273.15)&np.isfinite(p)&(p>0)
                pred=np.where(good_aux,pred,np.nan)
        else:pred=native_pred;observed=b['y'];expected=b['valid'];own_mask=expected
        local=((store.hour[h]+st['lon']/15)%24).astype(int)
        own.add(st['key'],st['country'],store.month[h],local,observed,pred,own_mask)
        common.add(st['key'],st['country'],store.month[h],local,observed,pred,expected)
        for hh in h[expected]:casehash.update((st['key']+'|'+str(store.times[hh])+'\n').encode())
        common_n+=int(expected.sum())
        if callback is not None:callback(b,observed,pred,native_pred,t,p,expected)
    a=common.report();a.update(own_coverage=own.report(),case_fingerprint=casehash.hexdigest(),expected_common_cases=common_n)
    return a

def tune(provider,targets,years,coordinate,basis,cache,identity,aux_by_fold=None,k=None,seed=None):
    c=provider.c;store=provider.store;opt=c['tuning'];k=k or c['inner_folds'];seed=c['seed'] if seed is None else seed
    path=Path(cache)/(identity+'.json')
    if path.exists():
        previous=sealed(path,'tuning_id')
        if previous['status']=='CONVERGED':return previous
        path.rename(path.with_name(path.stem+'.failed_'+previous['tuning_id'][:12]+'.json'))
    plan=list(folds(store,targets,years,k,seed));allhours=tuning_hours(store,years,opt['hours_per_month'],c['seed'])
    history=[];best=None;begin=time.monotonic();last_log=begin
    def objective(eta):
        nonlocal best,last_log
        try:
            metrics=Metrics(False);n=0
            for f in plan:
                trainh=allhours[np.isin(store.years[allhours],f['train_years'])];validh=allhours[np.isin(store.years[allhours],f['valid_years'])]
                m=fit(provider,f['train'],f['train'],trainh,coordinate,basis,eta)
                aux=aux_by_fold[f['fold']] if aux_by_fold else None
                # Aggregation across all spatial/temporal folds by country/station.
                def cb(b,obs,pred,native,t,p,mask):
                    st=store.stations[b['target']];h=b['hours'];local=((store.hour[h]+st['lon']/15)%24).astype(int)
                    metrics.add(st['key'],st['country'],store.month[h],local,obs,pred,mask)
                report=evaluate(provider,m,f['valid'],f['train'],validh,aux,cb,detail=False);n+=report['expected_common_cases']
            r=metrics.report();value=r['overall']['MAE']
            if n<opt['min_fit_cases'] or value is None or r['invalid_predictions_on_expected_mask']:raise InputError("Insufficient or nonfinite inner-validation predictions")
            value=float(value)
        except (InputError,np.linalg.LinAlgError,FloatingPointError) as exc:
            value=1e30;history.append({'eta':list(map(float,eta)),'objective':None,'error':str(exc)})
        else:
            history.append({'eta':list(map(float,eta)),'objective':value,'cases':n})
            if best is None or value<best['objective']:best={'eta':list(map(float,eta)),'objective':value}
        if time.monotonic()-last_log>=15:log(f"  {coordinate}/{basis} D tuning: {len(history)} evaluations, objective {value:.6g}");last_log=time.monotonic()
        return value
    bounds=[(.1,8.),(0.,8.),(-16.,2.)];starts=[[2.,0.,math.log(max(opt['ridge_lambda'],1e-7))],[1.,1.,-8.]];attempts=[];eligible=[]
    for initial in starts[:opt['starts']]:
        r=minimize(objective,initial,method='L-BFGS-B',bounds=bounds,options={'maxfun':opt['max_evaluations'],'maxiter':opt['max_iterations'],'ftol':1e-8,'gtol':1e-5,'eps':1e-5})
        attempts.append({'method':'L-BFGS-B','success':bool(r.success),'eta':r.x.tolist(),'objective':float(r.fun) if r.fun<1e29 else None,'message':str(r.message),'nfev':int(r.nfev)})
        if r.success and r.fun<1e29:eligible.append({'eta':r.x.tolist(),'objective':float(r.fun)})
    # Independent starts are local searches, not a global optimum guarantee.
    if not eligible and best:
        r=minimize(objective,best['eta'],method='Powell',bounds=bounds,options={'maxfev':opt['max_evaluations']*3,'maxiter':opt['max_iterations']*3,'ftol':1e-7,'xtol':1e-5})
        attempts.append({'method':'Powell','success':bool(r.success),'eta':r.x.tolist(),'objective':float(r.fun) if r.fun<1e29 else None,'message':str(r.message),'nfev':int(r.nfev)})
        if r.success and r.fun<1e29:eligible.append({'eta':r.x.tolist(),'objective':float(r.fun)})
    result={'identity':identity,'status':'CONVERGED' if eligible else 'UNRESOLVED_OPTIMIZATION','coordinate':coordinate,'basis':basis,'attempts':attempts,'trace':history,'wall_seconds':time.monotonic()-begin,'tuning_scope':'metadata-only target and hour screening in D; spatial AND year-block inner holdouts; not full-calendar final fit','training_families':sorted({store.stations[i]['family'] for i in targets}),'training_years':years,'search_claim':'continuous local multi-start optimization; no global optimum guarantee','folds':[{'train_families':sorted({store.stations[i]['family'] for i in f['train']}),'valid_families':sorted({store.stations[i]['family'] for i in f['valid']}),'train_years':f['train_years'],'valid_years':f['valid_years']} for f in plan]}
    if eligible:result.update(min(eligible,key=lambda x:x['objective']))
    result['tuning_id']=digest(result);write_json(path,result)
    if not eligible:raise InputError("Unresolved D-only optimization: "+coordinate+'/'+basis+"; see "+str(path))
    return result

def auxiliary(provider,targets,years,basis,cache,context,k=None,seed=None,full_fit=False):
    store=provider.store;c=provider.c
    ident=digest([context,basis,targets,years,full_fit,k,seed])[:24];path=Path(cache)/('aux_'+ident+'.json')
    if path.exists():return sealed(path,'auxiliary_id')['models']
    models={}
    for co,b in [('T',basis),('p','height')]:
        tuning=tune(provider,targets,years,co,b,cache,'aux_'+ident+'_'+co,k=k,seed=seed)
        hours=store.hours(years) if full_fit else tuning_hours(store,years,c['tuning']['hours_per_month'],c['seed'])
        models[co]=fit(provider,targets,targets,hours,co,b,tuning['eta']);models[co]['tuning_id']=tuning['tuning_id']
    a={'models':models,'context':context,'full_fit':full_fit};a['auxiliary_id']=digest(a);write_json(path,a);return models

def nested_auxiliaries(provider,tune_targets,all_targets,years,basis,cache):
    c=provider.c;store=provider.store;outer={}
    for f in folds(store,tune_targets,years,c['inner_folds'],c['seed']):
        # These searches never consult the outer held-out families/years.
        log(f"  shared auxiliary {basis}, outer fold {f['fold']}: D-only nested search")
        outer[f['fold']]=auxiliary(provider,f['train'],f['train_years'],basis,cache,'outer:'+str(f['fold']),k=2,seed=c['seed']+1009+f['fold'])
    # Shared hyperparameters selected on D, then coefficients refit on every D hour/site.
    screen=auxiliary(provider,tune_targets,years,basis,cache,'full_D_screen')
    full={}
    for co in ('T','p'):
        full[co]=fit(provider,all_targets,all_targets,store.hours(years),co,screen[co]['basis'],screen[co]['eta'],checkpoint=Path(cache)/('full_aux_'+basis+'_'+co))
        full[co]['tuning_id']=screen[co]['tuning_id']
    return outer,full
