"""Generate transfer designs a station/time block at a time, without N×N caches."""
from __future__ import annotations
import math
import numpy as np
from ige_auto.data import buck_water
from ige_hum.physics import e_from_q,q_from_e
from ige_local.common import InputError,digest,distance

MOISTURE={'RH','log_e','q','Td','D'}

def dewpoint(e):
    """Stable analytic inverse of the SAME Buck-water curve, [-80,50] °C."""
    e=np.asarray(e,dtype=float)
    with np.errstate(invalid='ignore',divide='ignore'):
        l=np.log(e/6.1121);b=18.678-l;disc=b*b-4*257.14*l/234.5
        t=2*257.14*l/(b+np.sqrt(disc))
    return np.where((e>=buck_water(-80.))&(e<=buck_water(50.))&np.isfinite(t),t,np.nan)

def native(coordinate,v,eligible):
    if coordinate in ('T','RH','p'):
        j={'T':0,'RH':1,'p':2}[coordinate];return v[...,j],eligible[...,j]
    e=v[...,1]*buck_water(v[...,0])/100
    valid=eligible[...,:2].all(axis=-1)&(e>0)&np.isfinite(e)
    if coordinate=='log_e':
        with np.errstate(divide='ignore',invalid='ignore'):return np.log(e),valid
    if coordinate=='q':
        q=q_from_e(e,v[...,2]);return q,valid&eligible[...,2]&(v[...,2]>e)&np.isfinite(q)&(q>=0)&(q<1)
    td=dewpoint(e)
    return (td if coordinate=='Td' else v[...,0]-td),valid&np.isfinite(td)

def restored(coordinate,y,t,p):
    if coordinate in ('T','p','RH'):return np.asarray(y)
    if coordinate=='q':e=e_from_q(y,p)
    elif coordinate=='log_e':
        with np.errstate(over='ignore'):e=np.exp(y)
    else:e=buck_water(y if coordinate=='Td' else t-y)
    with np.errstate(divide='ignore',invalid='ignore'):return 100*e/buck_water(t)

def features(st,hours,store,basis,urban=None):
    st=list(st);h=np.asarray(hours);z=np.array([s['height_m']/1000 for s in st])
    # Shapes are (hours, sites, columns); station-local mean solar hour.
    times=store.times[h];yr=times.astype('datetime64[Y]');nextyr=(yr.astype(int)+1).astype('datetime64[Y]')
    phase=2*np.pi*((times-yr).astype('timedelta64[h]').astype(float)/((nextyr-yr).astype('timedelta64[h]').astype(float)))
    local=2*np.pi*(store.hour[h,None]+np.array([s['lon']/15 for s in st])[None,:])/24
    one=np.ones((len(h),len(st)));zz=one*z
    if basis=='height':return zz[...,None]
    if basis=='monthly':return zz[...,None]*(store.month[h,None,None]==np.arange(1,13)[None,None,:])
    base=np.stack([zz,zz*np.sin(phase[:,None]),zz*np.cos(phase[:,None]),zz*np.sin(local),zz*np.cos(local)],axis=-1)
    if basis=='harmonic':return base
    if urban is None:raise InputError("Urban model requested without real frozen features")
    u=np.broadcast_to(np.asarray(urban)[None,:,:],(len(h),len(st),8))
    if basis=='urban_static':return np.concatenate([base,u],axis=-1)
    more=np.stack([u,u*np.sin(phase[:,None,None]),u*np.cos(phase[:,None,None]),u*np.sin(local[...,None]),u*np.cos(local[...,None])],axis=-1).reshape((len(h),len(st),40))
    return np.concatenate([base,more],axis=-1)

def columns(basis):return {'height':1,'monthly':12,'harmonic':5,'urban_static':13,'urban_harmonic':45}[basis]

def feature_names(basis):
    if basis=='height':return ['height_km']
    if basis=='monthly':return ['height_km_month_'+str(m) for m in range(1,13)]
    names=['height_km','height_sin_year','height_cos_year','height_sin_solar_hour','height_cos_solar_hour']
    fields=[f'{name}_radius_{r}' for name in ('impervious','tree_canopy','open_water','wet_surface') for r in (0,1)]
    if basis=='urban_static':names+=fields
    if basis=='urban_harmonic':names += [f+'_'+time for f in fields for time in ('constant','sin_year','cos_year','sin_solar_hour','cos_solar_hour')]
    return names

def tuning_hours(store,years,limit,seed):
    out=[]
    for y in years:
        for m in range(1,13):
            h=np.flatnonzero((store.years==y)&(store.month==m))
            if 'source_calendar_hours' in store.meta:h=np.intersect1d(h,store.meta['source_calendar_hours'],assume_unique=True)
            # Fixed before observations. Different hours across each year/month.
            rng=np.random.default_rng(int(digest([seed,y,m])[:12],16));out.extend(np.sort(rng.choice(h,min(limit,len(h)),replace=False)))
    return np.sort(np.asarray(out,dtype=np.int64))

def tuning_targets(store,targets,limit,urban=None):
    chosen=[]
    for country in sorted({store.stations[i]['country'] for i in targets}):
        ix=sorted([i for i in targets if store.stations[i]['country']==country],key=lambda i:(store.stations[i]['height_m'],store.stations[i]['key']))
        if urban is None:
            choose=np.linspace(0,len(ix)-1,min(limit,len(ix))).round().astype(int);chosen.extend(ix[j] for j in choose)
        else:
            half=(limit+1)//2;take={ix[j] for j in np.linspace(0,len(ix)-1,min(half,len(ix))).round().astype(int)}
            by_urban=sorted(ix,key=lambda i:(urban[i,0],store.stations[i]['key']))
            take.update(by_urban[j] for j in np.linspace(0,len(ix)-1,min(limit-half,len(ix))).round().astype(int))
            for i in sorted(ix,key=lambda i:digest(store.stations[i]['key'])):
                if len(take)>=min(limit,len(ix)):break
                take.add(i)
            chosen.extend(take)
    return sorted(set(chosen))

class Provider:
    def __init__(self,store,c,urban=None,require_urban=False):
        self.store=store;self.c=c;self.urban=urban;self.require_urban=require_urban;self.geometry={};self.counts_cache={}
    def neighbours(self,target,donors):
        key=(target,tuple(donors),self.require_urban)
        if key in self.geometry:return self.geometry[key]
        st=self.store.stations;d=self.c['donors'];a=st[target];found=[]
        if self.require_urban and (self.urban is None or not np.isfinite(self.urban[target]).all()):return []
        for j in donors:
            b=st[j]
            if a['family']==b['family'] or a['country']!=b['country']:continue
            if self.require_urban and not np.isfinite(self.urban[j]).all():continue
            dist=distance(a,b)
            if dist<=d['co_location_km'] or dist>d['radius_km'] or abs(a['height_m']-b['height_m'])>d['max_height_difference_m']:continue
            found.append((dist,b['key'],j))
        found=sorted(found)[:d['candidate_count']];result=[j for _,_,j in found];self.geometry[key]=result;return result
    def blocks(self,targets,donors,hours,coordinate,basis,eta):
        store=self.store;st=store.stations;cfg=self.c;urban_basis=basis.startswith('urban')
        if urban_basis and not self.require_urban:raise InputError("Urban models require the paired urban-data panel")
        if any(st[i]['role']=='C' for i in targets+donors):raise InputError("C families cannot enter development/validation generators")
        if np.isin(store.years[hours],store.meta['years']['C']).any():raise InputError("C years cannot enter development/validation generators")
        for target in targets:
            ids=self.neighbours(target,donors)
            if len(ids)<cfg['donors']['min_donors']:continue
            dist=np.array([distance(st[target],st[j]) for j in ids]);dz=np.array([abs(st[target]['height_m']-st[j]['height_m'])/1000 for j in ids])
            for start in range(0,len(hours),cfg['batch_hours']):
                h=hours[start:start+cfg['batch_hours']];tv,to,te,tq=store.read(target,h);y,observed=native(coordinate,tv,te)
                if not observed.any():continue
                dd=[store.read(j,h) for j in ids];dv=np.stack([x[0] for x in dd],axis=1);dop=np.stack([x[1] for x in dd],axis=1);de=np.stack([x[2] for x in dd],axis=1)
                _,dvalid=native(coordinate,dv,de);native_d,_=native(coordinate,dv,de)
                req={'T':[0],'p':[2],'RH':[1],'log_e':[0,1],'q':[0,1,2],'Td':[0,1],'D':[0,1]}[coordinate]
                mask=dvalid&(dop[:,:,req]==to[:,None,req]).all(axis=-1)
                joint=de.all(axis=-1)&(dop==to[:,None,:]).all(axis=-1)
                ej=dv[:,:,1]*buck_water(dv[:,:,0])/100;tdj=dewpoint(ej)
                joint&=(ej>0)&(dv[:,:,2]>ej)&np.isfinite(tdj)
                # At most one alias per physical family per hour, then nearest k available.
                for masks in (mask,joint):
                    seen={}
                    for j,donor in enumerate(ids):
                        fam=st[donor]['family'];was=seen.setdefault(fam,np.zeros(len(h),dtype=bool));masks[:,j]&=~was;was|=masks[:,j]
                    masks&=np.cumsum(masks,axis=1)<=cfg['donors']['max_donors']
                ready=mask.sum(axis=1)>=cfg['donors']['min_donors']
                raw=np.exp(-float(eta[0])*np.log(np.maximum(dist,1.))[None,:]-float(eta[1])*dz[None,:])*mask
                den=raw.sum(axis=1);w=np.divide(raw,den[:,None],out=np.zeros_like(raw),where=den[:,None]>0)
                base=np.sum(w*np.where(mask,native_d,0.),axis=1)
                ut=self.urban[target:target+1] if urban_basis else None;ud=self.urban[ids] if urban_basis else None
                xt=features([st[target]],h,store,basis,ut)[:,0,:];xd=features([st[j] for j in ids],h,store,basis,ud)
                x=xt-np.sum(w[:,:,None]*xd,axis=1)
                et=tv[:,1]*buck_water(tv[:,0])/100;tdt=dewpoint(et)
                common=te.all(axis=1)&(et>0)&(tv[:,2]>et)&np.isfinite(tdt)&(joint.sum(axis=1)>=cfg['donors']['min_donors'])
                valid=ready&observed&np.isfinite(y)&np.isfinite(x).all(axis=1)
                yield {'target':target,'hours':h,'y':y,'base':base,'x':x,'valid':valid,'common':common,'reference':tv,'QC':tq,'donors':ids,'weights':w,'population':len(h)}
