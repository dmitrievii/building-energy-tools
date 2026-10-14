#!/usr/bin/env python3
"""IGE P8.1C DEM-aware model: strict out-of-station and out-of-year comparisons.

Calibrate temperature/topography relation on 1991-2010 GeoSphere donor normals,
never on 2011-2020 truth or target-station observations. 2011-2020 donor
observations are allowed, so this is observed-spatial reconstruction and
NOT a ten-year-ahead weather forecast. DEM features pre-exist all weather.
"""
from __future__ import annotations
import argparse,collections,csv,json,math,hashlib
from pathlib import Path
import numpy as np
from p8_1b_terrain_holdout import haversine,global_slope,local_slope,LAPSE,MAX_KM
from p8_1b_temporal_holdout import (fetch_json,metadata_contract,decode_response,calibrate_donor_normals,
                                     TRAIN_YEARS,TEST_YEARS,FIELD,BASE,save_csv)
from urllib.parse import urlencode

METHODS=('idw_raw','idw_fixed65','idw_regional','idw_local','dem_tpi_1500','dem_tpi_multiscale')
BUFFERS=(0,50)


def dem_coefficients(donors,month,names=('tpi_1500_m','tpi_5000_m')):
    """Ridge estimation on donor-only TRAIN normals, spatial trend removed.

    Coefficient units K/m.  tpi_1500 and tpi_5000 have independent ridge
    strengths ~ 250m. Clipped to conservative physical domain ±0.008 K/m.
    The target's terrain descriptors are *not used* in this calibration.
    """
    if len(donors)<12:raise ValueError('Insufficient donor stations for topographic fit')
    lat=np.array([s['lat'] for s in donors]);lon=np.array([s['lon'] for s in donors]);z=np.array([s['hoehe_m'] for s in donors]);y=np.array([s['tmittel'][month] for s in donors])
    geo=np.column_stack([np.ones(len(donors)),lat-np.mean(lat),lon-np.mean(lon),z-np.mean(z)])
    extra=np.column_stack([np.clip([s[n] for s in donors],-2500,2500) for n in names])
    # Partial out geography to reduce DEM-proxy confounding with elevation.
    tres=extra-geo@np.linalg.lstsq(geo,extra,rcond=None)[0]
    yres=y-geo@np.linalg.lstsq(geo,y,rcond=None)[0]
    lam=250.**2*np.eye(len(names))
    coeff=np.linalg.solve(tres.T@tres+lam,tres.T@yres)
    return np.clip(coeff,-.008,.008)


def paired_prediction(target,donors,dated,slopes,coeff,month):
    """All donors must be contemporaneously observed; target is excluded."""
    if any(s['station_id']==target['station_id'] for d,s in donors):raise AssertionError('TARGET DATA LEAKAGE')
    if len(donors)<8:raise ValueError('Need 8 actual donor station-month readings')
    top=donors[:8];d=np.array([r for r,s in top]);w=np.maximum(d,.25)**-2;w/=sum(w)
    temps=np.array([dated[s['station_id']] for r,s in top]);delta=np.array([target['hoehe_m']-s['hoehe_m'] for r,s in top])
    g,l=slopes
    baseline={
        'idw_raw':float(w@temps),
        'idw_fixed65':float(w@(temps+LAPSE*delta)),
        'idw_regional':float(w@(temps+g*delta)),
        'idw_local':float(w@(temps+l*delta)),
    }
    t1=np.array([s['tpi_1500_m'] for r,s in top]);t5=np.array([s['tpi_5000_m'] for r,s in top])
    dt1=float(target['tpi_1500_m']-w@t1);dt5=float(target['tpi_5000_m']-w@t5)
    baseline['dem_tpi_1500']=baseline['idw_regional']+float(coeff[0])*dt1
    baseline['dem_tpi_multiscale']=baseline['idw_regional']+float(coeff[0]*dt1+coeff[1]*dt5)
    return baseline


def evaluate(stations,series,normal,buffer_km=0):
    """Output only derived prediction/error tuples, not raw time series."""
    out=[];n=0;skips=collections.Counter();slopes_month={}
    train=calibrate_donor_normals(stations,series)
    features={int(x['station_id']):x for x in normal['stations']}
    train=[{**s,**{k:features[s['station_id']][k] for k in ('tpi_1500_m','tpi_5000_m','rugged_1500_m','dem_height_m','dem_minus_station_m')}}
           for s in train if s['station_id'] in features]
    for target in train:
        tid=target['station_id']
        others=sorted([(float(haversine(target['lat'],target['lon'],s['lat'],s['lon'])),s)
                  for s in train if s['station_id']!=tid],key=lambda a:(a[0],a[1]['station_id']))
        allowed=[(d,s) for d,s in others if buffer_km<=d<=MAX_KM]
        if len(allowed)<16:skips['too_few_donors']+=1;continue
        for m in range(12):
            donors_for_fit=[s for d,s in allowed]
            g=global_slope(donors_for_fit,m,'tmittel')
            l=local_slope(allowed[:16],'tmittel',m,g)
            c=dem_coefficients(donors_for_fit,m)
            slopes_month[m]=(g,l,c)
        for yr in TEST_YEARS:
            for m in range(1,13):
                ts=f'{yr}-{m:02d}'
                obs=series.get(tid,{}).get(ts)
                if obs is None:skips['target_month_missing']+=1;continue
                observed={s['station_id']:series[s['station_id']][ts] for d,s in allowed if ts in series.get(s['station_id'],{})}
                donors=[(d,s) for d,s in allowed if s['station_id'] in observed]
                if len(donors)<8:skips['donor_month_missing']+=1;continue
                g,l,c=slopes_month[m-1]
                predicted=paired_prediction(target,donors,observed,(g,l),c,m-1)
                for method,v in predicted.items():
                    out.append({'station_id':tid,'station':target['station'],'elevation_m':target['hoehe_m'],
                        'dem_height_m':target['dem_height_m'],'dem_height_mismatch':target['dem_minus_station_m'],
                        'tpi_1500_m':target['tpi_1500_m'],'tpi_5000_m':target['tpi_5000_m'],
                        'year':yr,'month':m,'buffer_km':buffer_km,'method':method,
                        'error':v-float(obs),'abs_error':abs(v-float(obs))})
                n+=1
    return out,{'usable_train_stations':len(train),'n_scored_station_months':n,'rejection':dict(skips)}


def aggregate(rows,keys):
    grouped=collections.defaultdict(list)
    for r in rows:grouped[tuple(r[k] for k in keys)].append(r)
    out=[]
    for key,items in sorted(grouped.items()):
        e=np.array([r['error'] for r in items]);out.append({**dict(zip(keys,key)),
           'n_months':len(items),'n_stations':len({x['station_id'] for x in items}),
           'MAE_C':float(np.abs(e).mean()),'RMSE_C':float(np.sqrt(np.mean(e*e))),
           'bias_C':float(e.mean()),'P90_abs_C':float(np.quantile(np.abs(e),.9))})
    return out


def station_cluster_bootstrap(rows,base='idw_regional',challenger='dem_tpi_multiscale',reps=2000):
    paired={}
    for x in rows:
        if x['method'] in (base,challenger):
            key=(x['station_id'],x['year'],x['month'],x['buffer_km'])
            paired.setdefault(key,{})[x['method']]=x['abs_error']
    bystation=collections.defaultdict(list)
    for (sid,yr,month,b),p in paired.items():
        if base in p and challenger in p:
            bystation[sid].append(p[base]-p[challenger])
    val=np.array([float(np.mean(v)) for v in bystation.values()],float)
    if len(val)<10:return {'status':'INSUFFICIENT','n_stations':len(val)}
    rng=np.random.default_rng(20261014)
    idx=rng.integers(0,len(val),size=(reps,len(val)))
    boot=val[idx].mean(axis=1)
    return {'base':base,'candidate':challenger,'station_count':len(val),
            'gain_mae_C':float(val.mean()),'station_bootstrap_95_C':[float(v) for v in np.quantile(boot,[.025,.975])],
            'conclusion':'positive CI supports DEM improvement; includes zero means no conclusive benefit',
            'note':'station-cluster bootstrap, descriptive conditional uncertainty'}


def execute(station_normals,terrain,out,batch=16):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    original=Path(station_normals).read_bytes();reference=json.loads(original)['stationen']
    demblob=Path(terrain).read_bytes();dem=json.loads(demblob)
    if dem['provenance'].get('source')!='Mapzen Terrain Tiles (Tilezen/Joerd) AWS Open Data':
        raise ValueError('Unverified DEM source schema')
    meta,metasha,metabytes=fetch_json(BASE+'/metadata')
    registered,flag,skipped=metadata_contract(meta,reference)
    ds={int(x['station_id']) for x in dem['stations']}
    eligible={k:v for k,v in registered.items() if k in ds}
    if len(eligible)<150:raise ValueError('Insufficient matched independent station+DEM sites')
    ids=sorted(eligible);series={};req=[];qc=collections.Counter()
    for i in range(0,len(ids),batch):
        part=ids[i:i+batch]
        args={'parameters':FIELD+(','+flag if flag else ''),'station_ids':','.join(str(s) for s in part),
              'start':'1991-01-01','end':'2020-12-31','output_format':'geojson'}
        url=BASE+'?'+urlencode(args)
        obj,sha,nbytes=fetch_json(url)
        x,diag=decode_response(obj,set(part),flag)
        if set(x)&set(series):raise AssertionError('Duplicate provider station ID')
        series.update(x);qc.update(diag)
        req.append({'batch':i//batch,'station_count':len(part),'bytes':nbytes,'sha256':sha,'source_url':url})
    if len(series)<150:raise ValueError('Too few original GeoSphere observations')
    predictions=[];folds=[]
    for buffer in BUFFERS:
        pred,diag=evaluate({k:v for k,v in eligible.items() if k in series},series,dem,buffer)
        if len(pred)<5000:raise RuntimeError('Insufficient DEM temporal holdout data')
        predictions.extend(pred);folds.append({'buffer_km':buffer,**diag})
    # Baseline and terrain predictions made on exactly the same eligible station-months.
    names=set(METHODS)
    grouped=collections.defaultdict(set)
    for x in predictions:grouped[(x['station_id'],x['year'],x['month'],x['buffer_km'])].add(x['method'])
    if any(vals!=names for vals in grouped.values()):raise AssertionError('Unmatched comparative sample')
    ag=aggregate(predictions,['buffer_km','method'])
    hg=[]
    for r in predictions:
        band='>=1500m' if r['elevation_m']>=1500 else '500-1500m' if r['elevation_m']>=500 else '<500m'
        hg.append({**r,'height_band':band})
    alt=aggregate(hg,['buffer_km','height_band','method'])
    sites=aggregate(predictions,['buffer_km','station_id','station','elevation_m','method'])
    months=aggregate(predictions,['buffer_km','month','method'])
    years=aggregate(predictions,['buffer_km','year','method'])
    c0=station_cluster_bootstrap([x for x in predictions if x['buffer_km']==0])
    c50=station_cluster_bootstrap([x for x in predictions if x['buffer_km']==50])
    save_csv(out/'temporal_methods.csv',ag);save_csv(out/'temporal_altitude_bands.csv',alt)
    save_csv(out/'temporal_stations.csv',sites);save_csv(out/'temporal_months.csv',months)
    save_csv(out/'temporal_years.csv',years)
    # No observed timestamp-level station series published, only aggregate metrics.
    report={'stage':'P8.1C','scientific_test':'original GeoSphere 1991–2010 lapse and DEM parameter fitting, 2011–2020 withheld target truth',
       'validation_not_forecast':True,'source_station_sha256':hashlib.sha256(original).hexdigest(),
       'terrain_feature_sha256':hashlib.sha256(demblob).hexdigest(),'geosphere_metadata_sha256':metasha,
       'matched_sites':len(eligible),'fetched_stations':len(series),'folds':folds,
       'model_comparisons':'matched station-month predictions only',
       'source_requests':req,'qc':dict(qc),'weather_raw_published':False,
       'bootstrap':{'buffer0':c0,'buffer50':c50},
       'limitations':['DEM is multi-provider Mapzen Terrain Tiles, not Austria DGM ground truth',
            'DEM TPI used for temperature only, not rainfall or radiation',
            '2011–2020 donor observations used, hence spatial hindcast not weather forecast',
            'Benchmark dataset reused for model exploration; independent geographic holdout pending',
            'DEM predictor spatial resolution/vertical datum uncertainty; station height not silently replaced by DEM',
            'DEM coefficient constrained via ridge but hypotheses chosen on this project, not a blinded publication preregistration']}
    (out/'temporal_provenance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print('P8.1C ORIGINAL-GEOSPHERE TEMPORAL HOLDOUt',json.dumps({'matched_sites':len(eligible),'n_folds':len(grouped),'folds':folds,'metrics':ag,'bootstrap':report['bootstrap']}),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--station-normals',required=True);p.add_argument('--terrain',required=True);p.add_argument('--out',required=True);p.add_argument('--batch',type=int,default=16)
    a=p.parse_args();execute(a.station_normals,a.terrain,a.out,a.batch)