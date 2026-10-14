#!/usr/bin/env python3
"""IGE P8.2B: Switzerland external-site moisture holdout and measured-hourly closure.

Swiss independent monthly e, T, RH use real SwissMetNet fields pva200m0,
tre200m0, ure200m0; no constructing reference e from mean T/RH.
Humidity lapse and temperature lapse trained exclusively on Austrian 1991–2010.
Same-test-month Swiss donor observations permitted: spatial hindcast not future weather.
At station/site, target observations never enter predictor, not even target T.
"""
from __future__ import annotations
import argparse, collections, csv, datetime as dt, hashlib, json, math, re
from pathlib import Path
import numpy as np
from p8_1e_swiss_external import (inventory_probe,select_stations,fetch,decode_csv,pick_col,
                                   austria_train_lapse,MAX_KM,haversine)
from p8_2a_humidity import (decode_monthly,training_stations,loge_lapse,moisture_predictions,
                             esat_water_hpa,save_csv,FIELDS)
from p8_1b_temporal_holdout import BASE,fetch_json,metadata_contract
from p8_1b_terrain_holdout import global_slope
from urllib.parse import urlencode

YEARS=tuple(range(2011,2021));BUFFERS=(0,50)
METHODS_E=('e_linear_idw','e_log_idw','e_log_fixed_scale','e_log_regional')
REGIONS=('west','central','east')
MISSING={'','NA','NaN','nan','-','-9999'}
HOURLY_SITES=('ABO','PAY')
HOURLY_MONTHS={(2019,1),(2019,7),(2020,1),(2020,7)}

def region(s):
    x=s['lon'];return 'west' if x<7.5 else 'central' if x<9.0 else 'east'

def safe_number(v,lo,hi):
    if v is None or v.strip() in MISSING:return None
    x=float(v)
    return float(x) if math.isfinite(x) and lo<=x<=hi else None

def swiss_monthly(raw,station):
    rows,cols=decode_csv(raw)
    needed=('tre200m0','ure200m0','pva200m0')
    if not set(needed).issubset({str(x).lower() for x in cols}):
        raise ValueError('SWISS_INDEPENDENT_HUMIDITY_FIELDS_MISSING '+str(cols))
    fields={k:pick_col(cols,k) for k in needed}
    datecol=pick_col(cols,'reference_timestamp')
    stationcol=pick_col(cols,'station_abbr')
    if not datecol or not stationcol:raise ValueError('Swiss metadata fields missing')
    out={};qc=collections.Counter()
    for r in rows:
        if r[stationcol].strip().upper()!=station:continue
        d=(r[datecol] or '').strip()
        m=re.match(r'^(\d{2})\.(\d{2})\.(\d{4})(?:\s|$)',d)
        if not m:qc['bad_timestamp']+=1;continue
        year=int(m[3]);mon=int(m[2])
        if year not in YEARS:continue
        if not 1<=mon<=12:raise ValueError('Swiss monthly invalid month')
        k=f'{year:04d}-{mon:02d}'
        if k in out:raise ValueError('Duplicate Swiss monthly timestamp '+k)
        v={'T':safe_number(r[fields['tre200m0']],-75,60),
           'RH':safe_number(r[fields['ure200m0']],0,105),
           'e':safe_number(r[fields['pva200m0']],.001,80)}
        out[k]=v
        for variable,value in v.items():
            if value is None:qc['missing_'+variable]+=1
    return out,dict(qc)

def train_austria_humidity(normals_path):
    """No Switzerland used here and no 2011-2020 values enter fit."""
    raw=Path(normals_path).read_bytes();source=json.loads(raw)['stationen']
    metadata,sha,_=fetch_json(BASE+'/metadata')
    param={p['name']:p for p in metadata['parameters']}
    # Only vapor and temperature training; validate original QC field and unit.
    req={'tl_mittel':('°C','degC'),'dampf_mittel':('hPa',)}
    for k,unit in req.items():
        if k not in param or param[k].get('unit') not in unit or k+'_flag' not in param:
            raise RuntimeError('GeoSphere calibration field or QC contract changed '+k)
    stations,flag,skipped=metadata_contract(metadata,source)
    merged={};requests=[]
    for i in range(0,len(stations),12):
        ids=sorted(stations)[i:i+12]
        url=BASE+'?'+urlencode({'parameters':'tl_mittel,tl_mittel_flag,dampf_mittel,dampf_mittel_flag',
             'station_ids':','.join(map(str,ids)),'start':'1991-01-01','end':'2020-12-31','output_format':'geojson'})
        data,digest,n=fetch_json(url,maxbytes=24000000)
        # Read only two physical parameters, without 2011-2020 leakage into fit.
        extracted,qc=decode_monthly(data,set(ids),fields=req)
        if merged.keys() & extracted.keys():raise ValueError('Duplicate GeoSphere batch')
        merged.update(extracted);requests.append({'sha256':digest,'bytes':n,'n_ids':len(ids)})
    cal=training_stations(stations,merged)
    if len(cal)<120:raise RuntimeError('Not enough Austrian train moisture normals')
    logslopes=[loge_lapse(cal,k) for k in range(12)]
    tslopes=[global_slope(cal,k,'tmittel') for k in range(12)]
    return logslopes,tslopes,{'station_count':len(cal),'source_index_hash':hashlib.sha256(raw).hexdigest(),
       'metadata_hash':sha,'source_batches':requests,
       'trained_on':'1991-2010 GeoSphere Austria station data only',
       'test_years_not_in_parameters':True,
       'log_vapour_slope_m_inv':logslopes,'temperature_slope_K_m':tslopes}

def weights(donors):
    d=np.array([dist for dist,s in donors],float)
    w=np.maximum(.25,d)**-2
    return w/w.sum()

def predict_month(target,donors,ym,obs,loge_slope,t_slope):
    """Yield matched methods; no target T/RH/e is read for prediction."""
    assert all(s['station_id']!=target['station_id'] for dist,s in donors)
    if len(donors)<8:raise ValueError('Need eight external donors')
    donors=donors[:8]
    d=weights(donors)
    dd=np.array([target['hoehe_m']-s['hoehe_m'] for dist,s in donors])
    ee=np.array([obs[s['station_id']][ym]['e'] for dist,s in donors])
    tt=np.array([obs[s['station_id']][ym]['T'] for dist,s in donors])
    rr=np.array([obs[s['station_id']][ym]['RH'] for dist,s in donors])
    ln=np.log(ee)
    from p8_2a_humidity import FIXED_SCALE
    vap={'e_linear_idw':float(d@ee),'e_log_idw':float(np.exp(d@ln)),
         'e_log_fixed_scale':float(np.exp(d@(ln+FIXED_SCALE*dd))),
         'e_log_regional':float(np.exp(d@(ln+loge_slope*dd)))}
    t_pred=float(d@(tt+t_slope*dd))
    rh_direct=float(d@rr)
    rh_proxy=100*vap['e_log_regional']/esat_water_hpa(t_pred)
    return vap,{'rh_direct_idw':rh_direct,'rh_vapour_temperature_proxy':rh_proxy},t_pred

def evaluate_sites(sites,observed,loge_slope,t_slope):
    outputs=[];coverage=collections.Counter();fail=collections.Counter()
    for target in sites:
        tr=region(target)
        sid=target['station_id']
        for mode in ('station_loo','region_blocked'):
            donors=sorted(((float(haversine(target['lat'],target['lon'],s['lat'],s['lon'])),s)
              for s in sites if s['station_id']!=sid and (mode!='region_blocked' or region(s)!=tr)),
              key=lambda x:(x[0],x[1]['station_id']))
            for buffer in BUFFERS:
                pool=[(d,s) for d,s in donors if buffer<=d<=MAX_KM]
                if len(pool)<8:fail['geographic_donor_pool_under8']+=1;continue
                for y in YEARS:
                    for m in range(1,13):
                        ym=f'{y}-{m:02d}';truth=observed.get(sid,{}).get(ym)
                        if not truth or not all(truth[x] is not None for x in ('e','T','RH')):
                            fail['target_missing_joint_e_T_RH']+=1;continue
                        usable=[(d,s) for d,s in pool if ym in observed.get(s['station_id'],{}) and
                           all(observed[s['station_id']][ym].get(x) is not None for x in ('e','T','RH'))][:8]
                        if len(usable)<8:fail['joint_e_T_RH_donors_under8']+=1;continue
                        vap,rh,tp=predict_month(target,usable,ym,observed,loge_slope[m-1],t_slope[m-1]);coverage[(mode,buffer)]+=1
                        meta={'site':sid,'region':tr,'height_m':target['hoehe_m'],'year':y,'month':m,
                              'holdout':mode,'buffer_km':buffer,'n_donors':8}
                        for method,estimate in vap.items():
                            outputs.append({**meta,'variable':'e_hpa','method':method,'error':estimate-truth['e'],'abs_error':abs(estimate-truth['e'])})
                        for method,estimate in rh.items():
                            outputs.append({**meta,'variable':'rh_percent','method':method,'error':estimate-truth['RH'],'abs_error':abs(estimate-truth['RH'])})
                        outputs.append({**meta,'variable':'temperature_c','method':'austria_regional_T','error':tp-truth['T'],'abs_error':abs(tp-truth['T'])})
                        if rh['rh_vapour_temperature_proxy']>100:fail['monthly_derived_rh_gt100']+=1
                        if rh['rh_vapour_temperature_proxy']<0:fail['monthly_derived_rh_lt0']+=1
                        measured_proxy=100*truth['e']/esat_water_hpa(truth['T'])
                        if abs(measured_proxy-truth['RH'])>5:fail['monthly_measured_e_T_RH_proxy_diff_gt5pp']+=1
    return outputs,{str(k):v for k,v in coverage.items()},dict(fail)

def aggregate(rows,keys):
    groups=collections.defaultdict(list)
    for row in rows:groups[tuple(row[k] for k in keys)].append(row)
    answer=[]
    for k,a in sorted(groups.items()):
        er=np.array([v['error'] for v in a])
        answer.append({**dict(zip(keys,k)),'n_months':len(er),'n_stations':len({r['site'] for r in a}),
          'MAE':float(np.mean(np.abs(er))),'RMSE':float(np.sqrt(np.mean(er*er))),
          'bias':float(np.mean(er)),'P90_abs':float(np.quantile(np.abs(er),.9))})
    return answer

def bootstrap_station(rows,mode,buffer,variable,base,candidate,reps=1200):
    matched=collections.defaultdict(dict)
    for r in rows:
        if r['holdout']==mode and r['buffer_km']==buffer and r['variable']==variable and r['method'] in (base,candidate):
            matched[(r['site'],r['year'],r['month'])][r['method']]=r['abs_error']
    by_site=collections.defaultdict(list)
    for (sid,y,m),p in matched.items():
        if base in p and candidate in p:by_site[sid].append(p[base]-p[candidate])
    gain=np.array([np.mean(values) for values in by_site.values()])
    if len(gain)<10:return {'status':'INSUFFICIENT_STATIONS','n':len(gain)}
    rng=np.random.default_rng(82144+buffer+(0 if mode=='station_loo' else 500))
    means=np.mean(gain[rng.integers(0,len(gain),size=(reps,len(gain)))],axis=1)
    return {'sites':len(gain),'equal_site_MAE_gain':float(np.mean(gain)),
            'station_bootstrap_95':[float(x) for x in np.quantile(means,[.025,.975])],
            'caution':'conditional exploratory station bootstrap; spatial dependence not captured'}

def run(normals,out,max_sites=36):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    swiss,assets,probe=inventory_probe(out)
    selected=select_stations(swiss,assets,max_sites)
    obs={};origins=[];issues=[]
    for station in selected:
        sid=station['station_id'];merged={}
        for url in assets[sid]:
            try:
                raw,sha=fetch(url,max_bytes=20000000)
                vals,qc=swiss_monthly(raw,sid)
                for k,x in vals.items():
                    if k in merged and merged[k]!=x:raise ValueError('Conflicting MeteoSwiss observations '+sid)
                    merged[k]=x
                origins.append({'sid':sid,'sha256':sha,'bytes':len(raw),'n_months':len(vals),'qc':qc})
            except Exception as exc:issues.append({'sid':sid,'type':type(exc).__name__,'detail':str(exc)[:260]})
        joint=sum(all(v[k] is not None for k in ('e','T','RH')) for v in merged.values())
        if joint>=96:obs[sid]=merged
    chosen=[s for s in selected if s['station_id'] in obs]
    perregion=collections.Counter(region(s) for s in chosen)
    if len(chosen)<20 or len(perregion)!=3 or min(perregion.values())<3:
        raise RuntimeError('Insufficient independent Swiss humidity coverage '+str(perregion))
    loge,tlope,training=train_austria_humidity(normals)
    rows,coverage,diag=evaluate_sites(chosen,obs,loge,tlope)
    if len(rows)<7500 or len({r['site'] for r in rows})<20:raise RuntimeError('Insufficient Swiss humidity evaluation pairs')
    # Exactly same station-months, donor cohort for e/T/RH, no post-hoc cohort selection.
    for (mode,buffer),n in [((mode,b),sum(1 for r in rows if r['method']=='e_linear_idw' and r['holdout']==mode and r['buffer_km']==b)) for mode in ('station_loo','region_blocked') for b in BUFFERS]:
        if n<100:raise RuntimeError('Too few samples '+mode+str(buffer))
    ag=aggregate(rows,('holdout','buffer_km','variable','method'))
    byreg=aggregate(rows,('holdout','buffer_km','region','variable','method'))
    byheight=aggregate([{**r,'height_bin':'low' if r['height_m']<500 else 'mid' if r['height_m']<1500 else 'high'} for r in rows],('holdout','buffer_km','height_bin','variable','method'))
    for name,table in [('external_metrics.csv',ag),('external_regions.csv',byreg),('external_height.csv',byheight)]:save_csv(out/name,table)
    boot={f'{mode}_{b}':{
      'e_regional_vs_linear':bootstrap_station(rows,mode,b,'e_hpa','e_linear_idw','e_log_regional'),
      'e_regional_vs_fixed':bootstrap_station(rows,mode,b,'e_hpa','e_log_fixed_scale','e_log_regional'),
      'rh_proxy_vs_direct':bootstrap_station(rows,mode,b,'rh_percent','rh_direct_idw','rh_vapour_temperature_proxy')}
       for mode in ('station_loo','region_blocked') for b in BUFFERS}
    report={'phase':'P8.2B_EXTERNAL_HUMIDITY','country':'Switzerland','station_provider':'MeteoSwiss SwissMetNet OGD',
     'n_sites':len(chosen),'regions':dict(perregion),'scored':coverage,'qc':diag,
     'independent_e_reference_field':'pva200m0','rh_reference':'ure200m0','temperature_reference':'tre200m0',
     'source_has_direct_provider_e':True,
     'e_sensor_independence_not_asserted':'Swiss vapour pressure may be psychrometrically derived by provider from T/RH',
     'no_Swiss_observations_used_for_fit':True,'Austrian_model':training,'source_digests':origins,
     'source_errors':issues,'metrics':ag,'bootstrap':boot,
     'limitations':['Test-year donor observations, NOT a weather forecast',
       'Monthly mean e/T/RH do not obey pointwise psychrometric identity',
       'Station bootstrap does not represent spatially correlated sampling uncertainty',
       'Provider measured or derived e is independent country validation, not independent sensor method',
       'No vendor proprietary values published','No calibration on Swiss targets or test series']}
    (out/'external_humidity_provenance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print('IGE_P8_2B_SWISS_EXTERNAL',json.dumps({'n_sites':len(chosen),'scored':coverage,'metrics':ag,'bootstrap':boot,'qc':diag}),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--austria-station-normals',required=True)
    p.add_argument('--out',required=True);p.add_argument('--max-sites',type=int,default=36)
    a=p.parse_args();run(a.austria_station_normals,a.out,a.max_sites)