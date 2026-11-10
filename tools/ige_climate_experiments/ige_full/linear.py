"""Streaming square-root least squares; every admitted D hour enters the fit."""
from __future__ import annotations
import math
import os
import time
from pathlib import Path
import numpy as np
from ige_local.common import InputError,digest,file_hash,read_json,write_json,log
from .batches import columns,feature_names

class QR:
    def __init__(self,p):self.r=np.empty((0,p+1));self.n=0;self.years={}
    def add(self,x,y):
        if not len(y):return
        self.r=np.linalg.qr(np.vstack([self.r,np.column_stack([x,y])]),mode='r');self.n+=len(y)

def fit(provider,targets,donors,hours,coordinate,basis,eta,checkpoint=None):
    st=provider.store.stations
    if any(st[i]['role']!='D' for i in targets+donors) or not set(map(int,provider.store.years[hours]))<=set(provider.store.meta['years']['D']):
        raise InputError("Regression fitting is restricted to D families and D years")
    local={};p=columns(basis);state={'done':{}}
    if checkpoint:
        checkpoint=Path(checkpoint);checkpoint.mkdir(parents=True,exist_ok=True)
        ident=digest([provider.store.meta['store_id'],targets,donors,digest(np.asarray(hours,dtype=np.int64).tobytes()),coordinate,basis,list(map(float,eta)),provider.c['donors'],provider.require_urban,digest(provider.urban.tobytes()) if provider.urban is not None else None])
        index=checkpoint/'index.json'
        if index.exists():
            state=read_json(index)
            if state['identity']!=ident:raise InputError("Full-refit checkpoint identity differs")
        else:state['identity']=ident
        for i in targets:
            key=str(i)
            if key in state['done']:
                r=state['done'][key];path=checkpoint/r['file']
                if file_hash(path)!=r['sha256']:raise InputError("Full-refit QR checkpoint changed")
                with np.load(path,allow_pickle=False) as a:q=QR(p);q.r=a['r'].copy();q.n=int(a['n'])
                q.years=r.get('years',{})
                local[i]=q
    last=time.monotonic()
    for target in targets:
        if target in local:continue
        q=QR(p)
        for b in provider.blocks([target],donors,hours,coordinate,basis,eta):
            mask=b['valid'];q.add(b['x'][mask],(b['y']-b['base'])[mask])
            yy,nn=np.unique(provider.store.years[b['hours'][mask]],return_counts=True)
            for year,n in zip(yy,nn):q.years[str(int(year))]=q.years.get(str(int(year)),0)+int(n)
        local[target]=q
        if checkpoint:
            name=str(target)+'.npz';tmp=checkpoint/(name+'.tmp')
            with tmp.open('wb') as f:np.savez(f,r=q.r,n=np.array(q.n))
            os.replace(tmp,checkpoint/name);state['done'][str(target)]={'file':name,'sha256':file_hash(checkpoint/name),'years':q.years};write_json(index,state)
        if time.monotonic()-last>=15:log(f"  {coordinate}/{basis} full refit: {len(local)}/{len(targets)} sites");last=time.monotonic()
    local={i:q for i,q in local.items() if q.n}
    if sum(q.n for q in local.values())<provider.c['tuning']['min_fit_cases']:raise InputError("Insufficient training cases")
    countries={provider.store.stations[i]['country'] for i in local};per={c:sum(provider.store.stations[i]['country']==c for i in local) for c in countries}
    allq=QR(p)
    for i,q in local.items():
        scale=math.sqrt(len(countries)*per[provider.store.stations[i]['country']]*q.n)
        allq.add(q.r[:,:p]/scale,q.r[:,p]/scale)
    x,y=allq.r[:,:p],allq.r[:,p];rms=np.sqrt(np.sum(x*x,axis=0));active=rms>1e-12
    if not active.any():raise InputError("No identifiable transfer features in training data")
    a=x[:,active]/rms[active];sing=np.linalg.svd(a,compute_uv=False);lam=math.exp(float(eta[2]))
    design=np.vstack([a,math.sqrt(lam)*np.eye(active.sum())]);response=np.r_[y,np.zeros(active.sum())]
    coeff=np.zeros(p);coeff[active]=np.linalg.lstsq(design,response,rcond=1e-10)[0]/rms[active]
    years={}
    for q in local.values():
        for year,n in q.years.items():years[year]=years.get(year,0)+n
    return {'coordinate':coordinate,'basis':basis,'eta':list(map(float,eta)),'coefficients':coeff.tolist(),'feature_names':feature_names(basis),'fit_rows':sum(q.n for q in local.values()),'fit_stations':len(local),'training_families':sorted({provider.store.stations[i]['family'] for i in targets}),'training_years':sorted(set(map(int,provider.store.years[hours]))),'actual_fit_cases_by_year':years,'country_station_weights':True,'solver':'streaming augmented QR, float64, RMS-scaled ridge','ridge_lambda':lam,'active_columns':active.tolist(),'numerical_rank':int((sing>sing[0]*1e-10).sum()),'columns':p,'scaled_condition':float(sing[0]/sing[-1]) if sing[-1]>0 else None,'coefficient_causal_interpretation':False}

def predict(model,b):return b['base']+b['x']@np.asarray(model['coefficients'])

class Metrics:
    def __init__(self,detail=True):self.s={};self.invalid=0;self.detail=detail
    def add(self,station,country,month,hour,observed,predicted,mask):
        expected=mask.copy();good=mask&np.isfinite(predicted)&np.isfinite(observed);self.invalid+=int((expected&~good).sum())
        e=predicted[good]-observed[good];m=month[good];h=hour[good]
        groups=[('all',np.ones(len(e),bool))]
        if self.detail:groups += [('month:'+str(i),m==i) for i in range(1,13)]+[('hour3:'+str(i),h//3==i) for i in range(8)]
        for name,sel in groups:
            if not sel.any():continue
            z=e[sel];key=(station,country,name);r=self.s.setdefault(key,[0,0.,0.,0.]);r[0]+=len(z);r[1]+=float(np.abs(z).sum());r[2]+=float(z.sum());r[3]+=float((z*z).sum())
    def report(self):
        rows=[{'station':s,'country':c,'stratum':k,'N':r[0],'MAE':r[1]/r[0],'bias':r[2]/r[0],'MSE':r[3]/r[0]} for (s,c,k),r in sorted(self.s.items())]
        def aggregate(name):
            chosen=[r for r in rows if r['stratum']==name]
            countries=sorted({r['country'] for r in chosen})
            if not countries:return {'N':0,'stations':0,'MAE':None,'RMSE':None,'bias':None}
            vals={k:float(np.mean([np.mean([r[k] for r in chosen if r['country']==c]) for c in countries])) for k in ('MAE','bias','MSE')}
            return {'N':sum(r['N'] for r in chosen),'stations':len(chosen),'countries':len(countries),'MAE':vals['MAE'],'RMSE':math.sqrt(vals['MSE']),'bias':vals['bias']}
        return {'overall':aggregate('all'),'by_month':{str(i):aggregate('month:'+str(i)) for i in range(1,13)},'by_solar_3h':{str(i):aggregate('hour3:'+str(i)) for i in range(8)},'station_rows':rows,'invalid_predictions_on_expected_mask':self.invalid}
