#!/usr/bin/env python3
"""IGE P8.2A: independent station-month humidity reconstruction; NOT hourly EPW.

GeoSphere klima-v2-1m original means + QC. Primary moisture variable is e [hPa],
not RH. Validation uses target station excluded from all donor data, historical
lapse calibration 1991-2010 and contemporaneous donor values 2011-2020.
Monthly psychrometric variables DO NOT generally satisfy instantaneous identities
when individually averaged; never force mean-RH == 100*mean-e/es(mean-T).
"""
from __future__ import annotations
import argparse,collections,csv,hashlib,json,math
from pathlib import Path
from urllib.parse import urlencode
import numpy as np
from p8_1b_terrain_holdout import haversine,global_slope,MAX_KM
from p8_1b_temporal_holdout import BASE,GOOD_FLAGS,TRAIN_YEARS,TEST_YEARS,fetch_json,metadata_contract,save_csv

FIELDS={'tl_mittel':('°C','degC'),'dampf_mittel':('hPa',),'rf_mittel':('%',),'absf_mittel':('g/m³','g/m3'),'p':('hPa',)}
RANGES={'tl_mittel':(-80,60),'dampf_mittel':(0,80),'rf_mittel':(0,105),'absf_mittel':(0,45),'p':(450,1120)}
METHODS_E=('e_linear_idw','e_log_idw','e_log_fixed_scale','e_log_regional')
BUFFERS=(0,50)
MIN_TRAIN=12
PRIOR_LOG_SLOPE=-1/2100.0  # log(e)/m physical prior, not empirical claim
FIXED_SCALE=-1/2000.0


def esat_water_hpa(temp_c):
    """Buck 1981 water curve: consistent formula used as monthly proxy only."""
    t=float(temp_c)
    return 6.1121*math.exp((18.678-t/234.5)*(t/(257.14+t)))


def loge_lapse(donors,month):
    """Donor TRAIN-only geography-adjusted regression ln(e) against elevation."""
    if len(donors)<8:raise ValueError('Not enough donors for loge lapse')
    z=np.asarray([x['hoehe_m'] for x in donors],float)
    la=np.asarray([x['lat'] for x in donors],float);lo=np.asarray([x['lon'] for x in donors],float)
    y=np.asarray([x['loge_train'][month] for x in donors],float)
    xy=np.column_stack([np.ones(len(z)),la-la.mean(),lo-lo.mean()])
    zr=z-xy@np.linalg.lstsq(xy,z,rcond=None)[0]
    yr=y-xy@np.linalg.lstsq(xy,y,rcond=None)[0]
    # 150 m prior pseudo-separation prevents wildly varying local regression.
    ans=(float(zr@yr)+150.**2*PRIOR_LOG_SLOPE)/(float(zr@zr)+150.**2)
    return float(np.clip(ans,-.0025,.0005))


def decode_monthly(response,request_ids,fields=FIELDS):
    """Strict 360-month axis, per-variable QC flags and absent-variable accounting."""
    axis=[f'{yr}-{mon:02d}' for yr in range(1991,2021) for mon in range(1,13)]
    timestamps=[str(x)[:7] for x in response.get('timestamps',[])]
    if timestamps!=axis:raise ValueError('GeoSphere chronology mismatch')
    seen=set();out={};diag=collections.Counter()
    for feature in response.get('features',[]):
        prop=feature.get('properties',{});sid=prop.get('station')
        if isinstance(sid,dict):sid=sid.get('id')
        sid=int(sid)
        if sid not in request_ids or sid in seen:raise ValueError('Duplicate or unknown station in response')
        seen.add(sid);param=prop.get('parameters',{});out[sid]={}
        for key,units in fields.items():
            entry=param.get(key)
            if not isinstance(entry,dict):diag[key+'_unavailable_station']+=1;continue
            if entry.get('unit') not in units:raise ValueError('GeoSphere unit mismatch: '+key+' '+str(entry.get('unit')))
            data=entry.get('data')
            if not isinstance(data,list) or len(data)!=360:raise ValueError('GeoSphere field axis mismatch '+key)
            flagentry=param.get(key+'_flag');flags=flagentry.get('data') if isinstance(flagentry,dict) else None
            if flags is not None and (not isinstance(flags,list) or len(flags)!=360):raise ValueError('QC chronology mismatch '+key)
            # No flag means unknown QC. Do not silently assume acceptability.
            if flags is None:diag[key+'_no_flag_station']+=1;continue
            values={}
            for i,(stamp,v) in enumerate(zip(axis,data)):
                if v is None:diag[key+'_null']+=1;continue
                vv=float(v)
                if not math.isfinite(vv) or not RANGES[key][0]<=vv<=RANGES[key][1]:
                    diag[key+'_implausible']+=1;continue
                if flags[i] not in GOOD_FLAGS:diag[key+'_flag_rejected']+=1;continue
                if key in ('dampf_mittel','absf_mittel') and vv<=0:diag[key+'_nonpositive']+=1;continue
                values[stamp]=vv
            out[sid][key]=values
    return out,dict(diag)


def training_stations(stations,series):
    result=[]
    for sid,s in stations.items():
        src=series.get(sid,{})
        e=src.get('dampf_mittel',{});tt=src.get('tl_mittel',{})
        logs=[];temps=[]
        for mon in range(1,13):
            ev=[e[f'{yr}-{mon:02d}'] for yr in TRAIN_YEARS if f'{yr}-{mon:02d}' in e]
            tv=[tt[f'{yr}-{mon:02d}'] for yr in TRAIN_YEARS if f'{yr}-{mon:02d}' in tt]
            logs.append(float(np.mean(np.log(ev))) if len(ev)>=MIN_TRAIN else None)
            temps.append(float(np.mean(tv)) if len(tv)>=MIN_TRAIN else None)
        if all(x is not None for x in logs) and all(x is not None for x in temps):
            result.append({**s,'loge_train':logs,'tmittel':temps})
    return result


def moisture_predictions(target,donors,stamp,series,slope):
    """Return predictions of mean vapour pressure on fixed, matched donors."""
    if target['station_id'] in [s['station_id'] for _,s in donors]:raise AssertionError('TARGET STATION LEAKAGE')
    if len(donors)<8:raise ValueError('Insufficient donors')
    donors=donors[:8]
    d=np.array([dist for dist,s in donors]);w=np.maximum(d,.25)**-2;w/=w.sum()
    e=np.array([series[s['station_id']]['dampf_mittel'][stamp] for dist,s in donors]);z=np.array([target['hoehe_m']-s['hoehe_m'] for dist,s in donors]); ln=np.log(e)
    return {
      'e_linear_idw':float(w@e),
      'e_log_idw':float(np.exp(w@ln)),
      'e_log_fixed_scale':float(np.exp(w@(ln+FIXED_SCALE*z))),
      'e_log_regional':float(np.exp(w@(ln+slope*z)))
    }


def evaluate(stations,series,buffer_km=0):
    calibrated=training_stations(stations,series)
    rows=[];diagnostics=collections.Counter()
    for target in calibrated:
        tid=target['station_id'];te=series.get(tid,{}).get('dampf_mittel',{})
        trh=series.get(tid,{}).get('rf_mittel',{});tt=series.get(tid,{}).get('tl_mittel',{})
        alt=sorted([(float(haversine(target['lat'],target['lon'],s['lat'],s['lon'])),s)
                    for s in calibrated if s['station_id']!=tid],key=lambda x:(x[0],x[1]['station_id']))
        candidates=[(d,s) for d,s in alt if buffer_km<=d<=MAX_KM]
        if len(candidates)<16:diagnostics['too_few_training_donors']+=1;continue
        monthly_e={m:loge_lapse([s for d,s in candidates],m) for m in range(12)}
        monthly_t={m:global_slope([s for d,s in candidates],m,'tmittel') for m in range(12)}
        for y in TEST_YEARS:
            for m in range(1,13):
                stamp=f'{y}-{m:02d}';true_e=te.get(stamp)
                if true_e is None:diagnostics['target_e_missing']+=1;continue
                available=[(d,s) for d,s in candidates if stamp in series.get(s['station_id'],{}).get('dampf_mittel',{})]
                if len(available)<8:diagnostics['donor_e_missing']+=1;continue
                donors=available[:8]
                estimates=moisture_predictions(target,donors,stamp,series,monthly_e[m-1])
                # All e methods scored against exact same target-month and donor cohort.
                for name,e_est in estimates.items():
                    rows.append({'station_id':tid,'station':target['station'],'elevation_m':target['hoehe_m'],
                       'year':y,'month':m,'buffer_km':buffer_km,'variable':'vapour_pressure_hpa',
                       'method':name,'error':e_est-true_e,'abs_error':abs(e_est-true_e)})
                # RH comparison only where measured RH and measured T exist, all
                # benchmark predictors generated without test target observations.
                if stamp not in trh or stamp not in tt:diagnostics['target_rh_or_temp_missing']+=1;continue
                t_donors=[(d,s) for d,s in candidates if stamp in series.get(s['station_id'],{}).get('tl_mittel',{})][:8]
                rh_donors=[(d,s) for d,s in candidates if stamp in series.get(s['station_id'],{}).get('rf_mittel',{})][:8]
                if len(t_donors)<8 or len(rh_donors)<8:diagnostics['donor_rh_or_temp_missing']+=1;continue
                dist=np.array([d for d,s in t_donors]);wt=np.maximum(dist,.25)**-2;wt/=wt.sum()
                t0=np.array([series[s['station_id']]['tl_mittel'][stamp] for d,s in t_donors]);delta=np.array([target['hoehe_m']-s['hoehe_m'] for d,s in t_donors]);
                t_hat=float(wt@(t0+monthly_t[m-1]*delta))
                dr=np.array([d for d,s in rh_donors]);wr=np.maximum(dr,.25)**-2;wr/=wr.sum()
                rh_hat=float(wr@np.array([series[s['station_id']]['rf_mittel'][stamp] for d,s in rh_donors]))
                derived=100*estimates['e_log_regional']/esat_water_hpa(t_hat)
                # RH from *monthly* mean e,T is a diagnostic proxy, not exact closure.
                for name,val in [('rh_direct_idw',rh_hat),('rh_vapour_temp_proxy',derived)]:
                    rows.append({'station_id':tid,'station':target['station'],'elevation_m':target['hoehe_m'],
                      'year':y,'month':m,'buffer_km':buffer_km,'variable':'monthly_rh_percent',
                      'method':name,'error':val-trh[stamp],'abs_error':abs(val-trh[stamp])})
                if derived<0 or derived>100:diagnostics['monthly_rh_proxy_outside_0_100']+=1
                abs_true=series.get(tid,{}).get('absf_mittel',{}).get(stamp)
                if abs_true is not None:
                    abs_available=[(d,s) for d,s in candidates if stamp in series.get(s['station_id'],{}).get('absf_mittel',{})][:8]
                    if len(abs_available)>=8:
                        da=np.array([d for d,s in abs_available]);wa=np.maximum(da,.25)**-2;wa/=wa.sum()
                        abs_direct=float(wa@np.array([series[s['station_id']]['absf_mittel'][stamp] for d,s in abs_available]))
                        abs_proxy=216.7*estimates['e_log_regional']/(t_hat+273.15)
                        for name,val in [('absf_direct_idw',abs_direct),('absf_vapour_temp_proxy',abs_proxy)]:
                            rows.append({'station_id':tid,'station':target['station'],'elevation_m':target['hoehe_m'],
                               'year':y,'month':m,'buffer_km':buffer_km,'variable':'monthly_abs_humidity_g_m3',
                               'method':name,'error':val-abs_true,'abs_error':abs(val-abs_true)})
                    else:diagnostics['donor_absf_missing']+=1
                else:diagnostics['target_absf_missing']+=1
                # Diagnostic: the measured *monthly* means need not algebraically close.
                measured_proxy=100*true_e/esat_water_hpa(tt[stamp])
                diagnostics['monthly_observed_mean_rh_difference_gt5pp']+=int(abs(measured_proxy-trh[stamp])>5)
    return rows,dict(diagnostics),len(calibrated)


def aggregates(rows,keys=('buffer_km','variable','method')):
    groups=collections.defaultdict(list)
    for r in rows:groups[tuple(r[k] for k in keys)].append(r)
    result=[]
    for key,items in sorted(groups.items()):
        errs=np.array([x['error'] for x in items],float)
        result.append({**dict(zip(keys,key)),'n_months':len(items),'n_stations':len({x['station_id'] for x in items}),
             'MAE':float(np.abs(errs).mean()),'RMSE':float(np.sqrt(np.mean(errs*errs))),
             'bias':float(errs.mean()),'P90_abs':float(np.quantile(np.abs(errs),.90))})
    return result


def station_bootstrap(rows,buffer,base,candidate,variable,reps=3000):
    paired=collections.defaultdict(dict)
    for r in rows:
        if r['buffer_km']!=buffer or r['variable']!=variable or r['method'] not in (base,candidate):continue
        paired[(r['station_id'],r['year'],r['month'])][r['method']]=r['abs_error']
    sites=collections.defaultdict(list)
    for (sid,y,m),p in paired.items():
        if base in p and candidate in p:sites[sid].append(p[base]-p[candidate])
    deltas=np.array([np.mean(x) for x in sites.values()]);
    if len(deltas)<10:return {'status':'INSUFFICIENT_STATIONS','n':len(deltas)}
    rng=np.random.default_rng(20261014+buffer)
    res=deltas[rng.integers(0,len(deltas),size=(reps,len(deltas)))].mean(axis=1)
    return {'n_stations':len(deltas),'mean_station_MAE_gain':float(deltas.mean()),
      'CI95':[float(x) for x in np.quantile(res,[.025,.975])],
      'interpretation':'Positive gain improves candidate; CI includes 0 means inconclusive'}


def execute(reference,out,batch=12):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    stationblob=Path(reference).read_bytes()
    meta,sha,size=fetch_json(BASE+'/metadata')
    p={x['name']:x for x in meta['parameters']}
    # Provider metadata has authority; fail on unknown/changed units.
    for name,units in FIELDS.items():
        if name not in p:raise RuntimeError('MISSING_GEOSPHERE_HUMIDITY_FIELD '+name)
        if p[name].get('unit') not in units:raise RuntimeError('UNIT_CHANGED '+name+' '+str(p[name].get('unit')))
        if name+'_flag' not in p:raise RuntimeError('MISSING_PER_VARIABLE_QC '+name)
    stations,tf,excluded=metadata_contract(meta,json.loads(stationblob)['stationen'])
    if len(stations)<100:raise RuntimeError('Too few identity-matched Austrian stations')
    merged={};provider_requests=[];qc=collections.Counter()
    all_fields=[item for k in FIELDS for item in (k,k+'_flag')]
    for i in range(0,len(stations),batch):
        group=sorted(stations)[i:i+batch]
        url=BASE+'?'+urlencode({'parameters':','.join(all_fields),'station_ids':','.join(map(str,group)),
                    'start':'1991-01-01','end':'2020-12-31','output_format':'geojson'})
        data,digest,length=fetch_json(url,maxbytes=40000000)
        decoded,diag=decode_monthly(data,set(group))
        if merged.keys()&decoded.keys():raise AssertionError('Duplicate provider station')
        merged.update(decoded);qc.update(diag)
        provider_requests.append({'group':i//batch,'station_count':len(group),'sha256':digest,'bytes':length,'url':url})
    rows=[];folds=[]
    for buffer in BUFFERS:
        part,diag,training_n=evaluate(stations,merged,buffer)
        if len(part)<2000:raise RuntimeError('Insufficient humidity test pairs buffer='+str(buffer))
        rows.extend(part)
        folds.append({'buffer_km':buffer,'n_train_sites':training_n,'n_e_months':len([x for x in part if x['method']=='e_linear_idw']),'n_rh_months':len([x for x in part if x['method']=='rh_direct_idw']),'n_absf_months':len([x for x in part if x['method']=='absf_direct_idw']),'qc':diag})
    ag=aggregates(rows);high=aggregates([{**r,'band':'high_ge1500' if r['elevation_m']>=1500 else 'mid_500_1499' if r['elevation_m']>=500 else 'low_lt500'} for r in rows],('buffer_km','variable','method','band'))
    bymonth=aggregates(rows,('buffer_km','variable','method','month'))
    bysite=aggregates(rows,('buffer_km','variable','method','station_id','station','elevation_m'))
    for name,table in [('humidity_methods.csv',ag),('humidity_altitude.csv',high),('humidity_months.csv',bymonth),('humidity_stations.csv',bysite)]:save_csv(out/name,table)
    boot={str(b):{
      'loge_regional_vs_linear':station_bootstrap(rows,b,'e_linear_idw','e_log_regional','vapour_pressure_hpa'),
      'loge_regional_vs_log_no_lapse':station_bootstrap(rows,b,'e_log_idw','e_log_regional','vapour_pressure_hpa'),
      'rh_vapour_proxy_vs_direct':station_bootstrap(rows,b,'rh_direct_idw','rh_vapour_temp_proxy','monthly_rh_percent'),
      'absf_vapour_proxy_vs_direct':station_bootstrap(rows,b,'absf_direct_idw','absf_vapour_temp_proxy','monthly_abs_humidity_g_m3')}
      for b in BUFFERS}
    manifest={'stage':'P8.2A_HISTORICAL_HUMIDITY_SPATIAL','source':'GeoSphere Austria klima-v2-1m','period_calibration':[1991,2010],
      'period_score':[2011,2020],'source_ref_sha256':hashlib.sha256(stationblob).hexdigest(),'metadata_sha256':sha,
      'source_identity_matched_stations':len(stations),'returned_stations':len(merged),'folds':folds,'metrics':ag,
      'bootstrap':boot,'qc':dict(qc),'request_provenance':provider_requests,
      'cautions':['Donor test-year observations make this station-excluded spatial reconstruction, NOT a weather forecast.',
        'Historical station normals used for identity and altitude, never humidity or temperature calibration.',
        'No target station T/RH/e used to generate test predictions.',
        'Mean RH is not 100 times mean e divided by e_sat(mean T); averages do not commute.',
        'Target RH and e are evaluated on potentially different paired subsets.',
        'No forced saturation capping or silent 0-100 RH clipping on monthly proxy.',
        'Independent external country and hourly EPW testing remain P8.2B+.'],
      'raw_geosphere_records_published':False}
    (out/'humidity_provenance.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    print('IGE_P8_2A_HUMIDITY_RESULT',json.dumps({'matched':len(stations),'folds':folds,'metrics':ag,'bootstrap':boot}),flush=True)
    return manifest

if __name__=='__main__':
    pa=argparse.ArgumentParser();pa.add_argument('--station-normals',required=True);pa.add_argument('--out',required=True);pa.add_argument('--batch',type=int,default=12)
    a=pa.parse_args();execute(a.station_normals,a.out,a.batch)