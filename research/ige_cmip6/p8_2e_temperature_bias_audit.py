#!/usr/bin/env python3
"""P8.2E: non-invasive systematic T-bias diagnostic on held-out Swiss stations.

Frozen P8.2E spatial annual_predict. Target observations enter only scoring.
All exported metrics are aggregated; never export provider hourly series.
Selection by *observed* RH is diagnostic conditioning, not deployable inference.
"""
from __future__ import annotations
import argparse,collections,csv,datetime as dt,json,math
from pathlib import Path
import numpy as np

METHOD='full_multidonor_shape'
SEASONS={12:'DJF',1:'DJF',2:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'}
CONDITIONS=('all','observed_wet_ge90','missed_wet_ge90','detected_wet_ge90',
            'observed_80_to_90','observed_90_to_95','observed_ge95',
            'observed_below80','predicted_wet_ge90')

def masks(obs_rh,pred_rh):
    o=np.asarray(obs_rh,float);p=np.asarray(pred_rh,float)
    if o.shape!=p.shape or o.ndim!=1 or not len(o) or not np.isfinite(o).all() or not np.isfinite(p).all():
        raise ValueError('Unpaired nonfinite RH arrays')
    ow=o>=90;pw=p>=90
    return {'all':np.ones(len(o),bool),'observed_wet_ge90':ow,
        'missed_wet_ge90':ow&~pw,'detected_wet_ge90':ow&pw,
        'observed_80_to_90':(o>=80)&(o<90),'observed_90_to_95':ow&(o<95),
        'observed_ge95':o>=95,'observed_below80':o<80,'predicted_wet_ge90':pw}

def summer_winter(month):
    if month not in SEASONS:raise ValueError('Month outside calendar')
    return SEASONS[month]

def cet_daypart(utc_hour):
    if not isinstance(utc_hour,(int,np.integer)) or not 0<=utc_hour<24:raise ValueError('Invalid UTC hour')
    h=(int(utc_hour)+1)%24 # end-of-hour UTC -> local fixed-CET end-hour, NEVER DST
    if h<6:return 'CET_00_05'
    if h<12:return 'CET_06_11'
    if h<18:return 'CET_12_17'
    return 'CET_18_23'

def summarize(mask,dt_error,e_error,t_obs,t_model):
    m=np.asarray(mask,bool);de=np.asarray(dt_error,float);ee=np.asarray(e_error,float)
    to=np.asarray(t_obs,float);tm=np.asarray(t_model,float)
    if any(x.shape!=m.shape for x in (de,ee,to,tm)):raise ValueError('Unpaired weather arrays')
    if not np.isfinite(de).all() or not np.isfinite(ee).all():raise ValueError('Invalid temperature/e residuals')
    if not m.any():return None
    x=de[m]; y=ee[m]
    return {'n_hours':int(len(x)),'T_bias_C':float(x.mean()),'T_MAE_C':float(np.mean(abs(x))),
        'T_RMSE_C':float(np.sqrt(np.mean(x*x))),
        'T_warm_error_fraction':float(np.mean(x>0)),
        'T_error_p10_C':float(np.quantile(x,.10)),'T_error_median_C':float(np.median(x)),
        'T_error_p90_C':float(np.quantile(x,.90)),
        'e_bias_hpa':float(y.mean()),'e_MAE_hpa':float(np.mean(abs(y))),
        'mean_observed_T_C':float(to[m].mean()),'mean_predicted_T_C':float(tm[m].mean())}

def score_site(site,year,hours,pred,obs,elevation):
    """Observations are evaluated only after predicting via donor-only annual_predict."""
    indices=np.array([i for i,t in enumerate(hours) if t in obs and
             all(obs[t].get(k) is not None for k in ('T','P','e','RH'))],dtype=int)
    if len(indices)<.95*len(hours):raise ValueError('Fewer than 95% qualified target hours')
    stamps=[hours[i] for i in indices]
    pt=np.asarray(pred['T'])[indices];pe=np.asarray(pred['e'])[indices];prh=np.asarray(pred['RH'])[indices]
    ot=np.asarray([obs[t]['T'] for t in stamps]);oe=np.asarray([obs[t]['e'] for t in stamps]);orh=np.asarray([obs[t]['RH'] for t in stamps])
    residual=pt-ot;error_e=pe-oe
    if np.any(~np.isfinite(pt)) or np.any(~np.isfinite(ot)):raise ValueError('Nonfinite station T')
    groups=[];conditions=masks(orh,prh)
    local_seasons=np.asarray([summer_winter(t.month) for t in stamps])
    local_parts=np.asarray([cet_daypart(t.hour) for t in stamps])
    local_months=np.asarray([t.month for t in stamps])
    base={'year':year,'site':site,'elevation_m':float(elevation),'method':METHOD}
    def add(kind,label,cond):
        stats=summarize(cond,residual,error_e,ot,pt)
        if stats is not None:groups.append({**base,'group_type':kind,'group':str(label),**stats})
    for name,mask in conditions.items():add('condition',name,mask)
    for season in ('DJF','MAM','JJA','SON'):
        s=local_seasons==season
        for k in ('all','observed_wet_ge90','missed_wet_ge90'):
            add('season_'+k,season,s&conditions[k])
    for part in ('CET_00_05','CET_06_11','CET_12_17','CET_18_23'):
        p=local_parts==part
        for k in ('all','observed_wet_ge90','missed_wet_ge90'):
            add('daypart_'+k,part,p&conditions[k])
    for month in range(1,13):
        s=local_months==month
        for k in ('all','observed_wet_ge90','missed_wet_ge90'):
            add('month_'+k,f'{month:02d}',s&conditions[k])
    # Count selection-conditioned event prevalence; all counts remain aggregated.
    counts={k:int(v.sum()) for k,v in conditions.items()}
    return groups,{'year':year,'site':site,'elevation_m':float(elevation),
        'qualified_hours':len(indices),'observed_wet_rate':float(np.mean(orh>=90)),
        'predicted_wet_rate':float(np.mean(prh>=90)),
        'missed_count':counts['missed_wet_ge90'],'wet_count':counts['observed_wet_ge90'],
        'wet_recall':1-counts['missed_wet_ge90']/max(1,counts['observed_wet_ge90']),
        'counts':counts,'predictor_uses_target_station':False}

def combined(rows):
    """Weighted bias/MAE aggregation, but distribution quantiles remain site-level only."""
    out=[]
    for (typ,label),group in sorted(_group(rows).items()):
        n=sum(x['n_hours'] for x in group)
        out.append({'group_type':typ,'group':label,'n_hours':n,'n_site_year_groups':len(group),
                    **{key:sum(x['n_hours']*x[key] for x in group)/n for key in
                      ('T_bias_C','T_MAE_C','T_warm_error_fraction','e_bias_hpa','e_MAE_hpa')},
                    'T_RMSE_C':math.sqrt(sum(x['n_hours']*x['T_RMSE_C']**2 for x in group)/n)})
    return out

def _group(rows):
    z=collections.defaultdict(list)
    for r in rows:z[(r['group_type'],r['group'])].append(r)
    return z

def emit(path,rows):
    if not rows:raise ValueError('Empty audit')
    with Path(path).open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def run(normals,year,out,targets=('ABO','BER','PAY')):
    from p8_2e_crossyear import ROOT,POOL,annual_hours,parse_swiss_year,donor_set,annual_predict
    from p8_1e_swiss_external import fetch,parse_meta
    from p8_2b_humidity import swiss_monthly,train_austria_humidity
    if year not in (2018,2019,2020):raise ValueError('Frozen post-hoc audit years only')
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    b,mhash=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    metadata,_=parse_meta(b);sites={sid:metadata[sid] for sid in POOL if sid in metadata}
    if not set(targets).issubset(sites):raise RuntimeError('Target station missing in metadata')
    hours=annual_hours(year);weather={};monthly={};source=[];issues=[]
    decade='2020-2029' if year>=2020 else '2010-2019'
    for sid in sites:
        try:
            b,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_{decade}.csv',max_bytes=37000000)
            weather[sid],qc=parse_swiss_year(b,sid,year)
            source.append({'site':sid,'type':'hourly','sha256':sha,'n_utc_records':len(weather[sid])})
            b,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_m.csv',max_bytes=20000000)
            monthly[sid],qc=swiss_monthly(b,sid)
            source.append({'site':sid,'type':'monthly','sha256':sha})
        except Exception as ex:issues.append({'site':sid,'error_type':type(ex).__name__,'message':str(ex)[:140]})
    loge,tslopes,cal=train_austria_humidity(normals)
    allrows=[];coverage=[]
    for sid in targets:
        if sid not in weather:raise RuntimeError('Missing original target station '+sid)
        # Target observations EXCLUDED from all predictor inputs.
        donors_weather={k:v for k,v in weather.items() if k!=sid}
        donors_monthly={k:v for k,v in monthly.items() if k!=sid}
        donors=donor_set(sites[sid],sites,donors_weather,donors_monthly,year=year)
        pred,diagnostic=annual_predict(sites[sid],donors,hours,donors_weather,donors_monthly,loge,tslopes,year=year)
        if diagnostic.get('target_meteorology_read_for_prediction') is not False:raise AssertionError('Target leakage detected')
        r,c=score_site(sid,year,hours,pred[METHOD],weather[sid],sites[sid]['hoehe_m'])
        allrows.extend(r);coverage.append({**c,'donors':[s['station_id'] for _,s in donors]})
    if len(coverage)!=len(targets):raise RuntimeError('Unqualified target coverage')
    aggregate=combined(allrows)
    emit(dest/'temperature_bias_by_station.csv',allrows)
    emit(dest/'temperature_bias_overall.csv',aggregate)
    emit(dest/'temperature_bias_event_counts.csv',[{k:v for k,v in c.items() if k!='counts'} for c in coverage])
    summary={'phase':'IGE_P8_2E_TEMPERATURE_BIAS_POST_HOC','year':year,'n_sites':len(targets),
        'n_hours':sum(c['qualified_hours'] for c in coverage),
        'model':'P8.2E full_multidonor_shape FROZEN','train':'Austria 1991-2010 only',
        'observations_used_for_prediction':False,
        'bias_sign':'predicted temperature MINUS observed temperature; positive = model too warm',
        'selection_warning':'Conditioning on observed RH >=90 or on model false negatives is post-hoc, selection bias; do not calibrate on these groups.',
        'time':'source UTC end-of-hour; descriptive local fixed CET group labels using (UTC+1) modulo 24, no DST',
        'coverage':coverage,'combined_groups':aggregate,'austria_training':cal,
        'source_station_sha256':mhash,'source_digests':source,'failed_source_sites':issues,
        'raw_hourly_provider_series_published':False,
        'scientific_limits':['Already inspected 2018-2020 evaluation years, not untouched out-of-sample',
           'Three geographically limited sites; seasonal summaries not independently sampled',
           'RH>90 conditioning is based on observed target only for score analysis, never available to a generative model',
           'Short-term temperature bias can differ by threshold and by weather regime',
           'No original hourly source series exported; only station-group aggregate statistics']}
    (dest/'temperature_bias_provenance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    show={k:[r for r in aggregate if r['group_type']=='condition' and r['group']==k][0] for k in
          ('all','observed_wet_ge90','missed_wet_ge90','detected_wet_ge90','observed_80_to_90')}
    print('IGE_P8_2E_T_BIAS_RESULT',json.dumps({'year':year,'n_hours':summary['n_hours'],
       'key_groups':show,'sites':[{k:v for k,v in x.items() if k!='counts'} for x in coverage]},ensure_ascii=False),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--austria-station-normals',required=True)
    p.add_argument('--year',type=int,required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.austria_station_normals,a.year,a.out)