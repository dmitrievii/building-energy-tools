#!/usr/bin/env python3
"""P8.1D observed-month spatial reconstruction: terrain regime vs P8.1B/C.

Training strictly 1991-2010 donor stations, test observations 2011-2020.
Classification describes susceptibility, not an observed thermal inversion.
Public output contains aggregate errors only, never raw measured time series.
"""
from __future__ import annotations
import argparse,collections,csv,hashlib,json,math
from pathlib import Path
from urllib.parse import urlencode
import numpy as np
from p8_1b_terrain_holdout import haversine,global_slope,local_slope,MAX_KM
from p8_1b_temporal_holdout import (fetch_json,metadata_contract,decode_response,
                                    calibrate_donor_normals,TRAIN_YEARS,TEST_YEARS,FIELD,BASE,save_csv)
from p8_1c_validate import paired_prediction,dem_coefficients
from p8_1d_regime import regime,fit_donor_only,predict_regime,susceptibility

METHODS=('idw_regional','idw_local','dem_tpi_multiscale','orographic_winter','orographic_seasonal')
BUFFERS=(0,50)

def run_fold(stations,observed,terrain,buffer_km):
    eligible=calibrate_donor_normals(stations,observed)
    geometry={int(s['station_id']):s for s in terrain['stations']}
    required=('tpi_1500_m','tpi_5000_m','rugged_1500_m','slope_250m_proxy','dem_height_m')
    eligible=[{**s,**{name:geometry[s['station_id']][name] for name in required}}
              for s in eligible if s['station_id'] in geometry]
    rows=[];counter=collections.Counter();coeff_info=[]
    for target in eligible:
        tid=target['station_id']
        close=sorted([(float(haversine(target['lat'],target['lon'],s['lat'],s['lon'])),s)
            for s in eligible if s['station_id']!=tid],key=lambda x:(x[0],x[1]['station_id']))
        valid=[(d,s) for d,s in close if buffer_km<=d<=MAX_KM]
        if len(valid)<20:counter['inadequate_donors']+=1;continue
        fitdonors=[s for d,s in valid]
        monthly_fit={}
        for m in range(1,13):
            # Each target's 1991–2010 training data are excluded, no global
            # pooled coefficients that have seen this station's truth.
            g=global_slope(fitdonors,m-1,'tmittel')
            l=local_slope(valid[:16],'tmittel',m-1,g)
            topo=dem_coefficients(fitdonors,m-1)
            oro=fit_donor_only(fitdonors,m)
            monthly_fit[m]=(g,l,topo,oro)
            coeff_info.append({'target_station_id':tid,'buffer_km':buffer_km,'month':m,
                'valley_cold_k':float(oro[0]),'ridge_cold_k':float(oro[1]),
                'valley_warm_k':float(oro[2]),'ridge_warm_k':float(oro[3])})
        classification=regime(target)
        cap,ridge=susceptibility(target)
        for year in TEST_YEARS:
            for month in range(1,13):
                date=f'{year}-{month:02d}'
                truth=observed.get(tid,{}).get(date)
                if truth is None:counter['target_month_missing']+=1;continue
                d=[(distance,s) for distance,s in valid if date in observed.get(s['station_id'],{})]
                if len(d)<8:counter['donors_missing']+=1;continue
                top=d[:8];dd=np.array([dist for dist,_ in top]);ww=np.maximum(dd,.25)**-2;ww/=sum(ww)
                values={s['station_id']:observed[s['station_id']][date] for _,s in top}
                g,l,topo,co=monthly_fit[month]
                base=paired_prediction(target,top,values,(g,l),topo,month-1)
                donors=[s for _,s in top]
                cold,delta_c=predict_regime(base['idw_regional'],target,donors,ww,co,month,winter_only=True)
                full,delta_f=predict_regime(base['idw_regional'],target,donors,ww,co,month,winter_only=False)
                prediction={name:base[name] for name in ('idw_regional','idw_local','dem_tpi_multiscale')}
                prediction.update(orographic_winter=cold,orographic_seasonal=full)
                for name in METHODS:
                    value=float(prediction[name])
                    rows.append({'station_id':tid,'station':target['station'],'elevation_m':target['hoehe_m'],
                        'regime':classification,'valley_proxy':cap,'ridge_proxy':ridge,
                        'buffer_km':buffer_km,'year':year,'month':month,
                        'season':'cold' if month in (11,12,1,2,3) else 'warm' if month in (5,6,7,8,9) else 'shoulder',
                        'method':name,'error_C':value-float(truth),'abs_error_C':abs(value-float(truth))})
                counter['scored_station_months']+=1
    return rows,dict(counter),coeff_info

def aggregate(rows,groups):
    bins=collections.defaultdict(list)
    for x in rows:bins[tuple(x[g] for g in groups)].append(x)
    result=[]
    for key,values in sorted(bins.items()):
        e=np.asarray([v['error_C'] for v in values],float)
        result.append({**dict(zip(groups,key)),'n_observations':len(e),'n_stations':len({v['station_id'] for v in values}),
            'MAE_C':float(np.abs(e).mean()),'RMSE_C':float(np.sqrt(np.mean(e*e))),
            'bias_C':float(e.mean()),'P90_abs_C':float(np.quantile(np.abs(e),.9))})
    return result

def station_bootstrap(rows,baseline,challenger,buffer_km,scope_regime=None,reps=2000):
    data=[r for r in rows if r['buffer_km']==buffer_km and (scope_regime is None or r['regime']==scope_regime)]
    paired=collections.defaultdict(dict)
    for r in data:
        if r['method'] in (baseline,challenger):
            paired[(r['station_id'],r['year'],r['month'])][r['method']]=r['abs_error_C']
    grouped=collections.defaultdict(list)
    for (sid,_,_),pair in paired.items():
        if len(pair)==2:grouped[sid].append(pair[baseline]-pair[challenger])
    vals=np.array([np.mean(x) for x in grouped.values()])
    if len(vals)<5:return {'status':'INSUFFICIENT','n_stations':len(vals)}
    seed=20261014 + buffer_km + (0 if scope_regime is None else len(scope_regime))
    rng=np.random.default_rng(seed)
    boot=np.mean(vals[rng.integers(0,len(vals),(reps,len(vals)))],axis=1)
    ci=np.quantile(boot,[.025,.975]).tolist()
    return {'baseline':baseline,'candidate':challenger,'buffer_km':buffer_km,
         'regime':scope_regime or 'all','n_stations':len(vals),'mean_station_gain_mae_C':float(vals.mean()),
         'station_cluster_CI95_C':[float(i) for i in ci],
         'supports_improvement':bool(ci[0]>0)}

def execute(normals,dem,out,batch=16):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    source=Path(normals).read_bytes();reference=json.loads(source)['stationen']
    dembytes=Path(dem).read_bytes();terrain=json.loads(dembytes)
    if terrain['provenance']['source']!='Mapzen Terrain Tiles (Tilezen/Joerd) AWS Open Data':
        raise ValueError('Unexpected DEM source')
    meta,meta_sha,_=fetch_json(BASE+'/metadata')
    all_stations,flag,excluded=metadata_contract(meta,reference)
    matched={int(x['station_id']) for x in terrain['stations']}
    stations={sid:s for sid,s in all_stations.items() if sid in matched}
    ids=sorted(stations);observations={};requests=[];qc=collections.Counter()
    for offset in range(0,len(ids),batch):
        part=ids[offset:offset+batch]
        url=BASE+'?'+urlencode({'parameters':FIELD+(','+flag if flag else ''),
            'station_ids':','.join(str(i) for i in part),'start':'1991-01-01',
            'end':'2020-12-31','output_format':'geojson'})
        payload,sha,length=fetch_json(url)
        ob,diag=decode_response(payload,set(part),flag)
        if set(ob).intersection(observations):raise AssertionError('Duplicate weather stations')
        observations.update(ob);qc.update(diag)
        requests.append({'station_count':len(part),'sha256':sha,'bytes':length,'url':url})
    if len(observations)<150:raise RuntimeError('Too few GeoSphere source stations')
    rows=[];folds=[];coeff=[]
    for buffer in BUFFERS:
        rr,diag,co=run_fold({sid:s for sid,s in stations.items() if sid in observations},observations,terrain,buffer)
        if diag.get('scored_station_months',0)<18000:raise RuntimeError('Insufficient paired independent station-months')
        rows+=rr;coeff+=co;folds.append({'buffer_km':buffer,**diag})
    expected=set(METHODS);groups=collections.defaultdict(set)
    for row in rows:groups[(row['buffer_km'],row['station_id'],row['year'],row['month'])].add(row['method'])
    if any(v!=expected for v in groups.values()):raise AssertionError('Missing matched prediction method')
    metrics=aggregate(rows,['buffer_km','method'])
    by_regime=aggregate(rows,['buffer_km','regime','method'])
    by_season=aggregate(rows,['buffer_km','season','method'])
    by_station=aggregate(rows,['buffer_km','station_id','station','elevation_m','regime','method'])
    by_year=aggregate(rows,['buffer_km','year','method'])
    by_month=aggregate(rows,['buffer_km','month','method'])
    by_altitude=aggregate([{**r,'height_band':'high>=1500m' if r['elevation_m']>=1500 else 'mid500-1500m' if r['elevation_m']>=500 else 'low<500m'} for r in rows],['buffer_km','height_band','method'])
    for name,data in [('methods',metrics),('regimes',by_regime),('seasons',by_season),('stations',by_station),('years',by_year),('months',by_month),('altitudes',by_altitude)]:
        save_csv(out/('p8_1d_'+name+'.csv'),data)
    bootstrap=[]
    for buff in BUFFERS:
        for candidate in ('orographic_winter','orographic_seasonal'):
            bootstrap.append(station_bootstrap(rows,'idw_regional',candidate,buff))
            for label in ('enclosed_valley','alpine_crest','ridge','slope_transition','open_lowland'):
                bootstrap.append(station_bootstrap(rows,'idw_regional',candidate,buff,label))
    labels=collections.Counter(x['regime'] for x in rows if x['method']=='idw_regional' and x['buffer_km']==0)
    summary={'phase':'P8.1D','status':'NUMERICAL_RESEARCH_COMPLETED_NOT_PRODUCTION_VALIDATED',
        'observation_protocol':'1991-2010 donor-only calibration, 2011-2020 independently withheld target stations; contemporaneous donors observed',
        'inversion_statement':'Cold-air pooling susceptibility proxy from DEM; no measured inversion-layer heights or hourly inversion diagnoses in this experiment',
        'n_train_qualified_sites':len({v['station_id'] for v in rows}),
        'n_scored_stations_month_buffer':len(groups),'folds':folds,'regime_station_months':dict(labels),
        'source_station_index_sha256':hashlib.sha256(source).hexdigest(),
        'source_dem_features_sha256':hashlib.sha256(dembytes).hexdigest(),'geosphere_metadata_sha256':meta_sha,
        'source_requests':requests,'qc':dict(qc),'excluded_metadata_stations':len(excluded),
        'metrics':metrics,'bootstrap':bootstrap,'no_original_station_weather_published':True,
        'coefficients':{'ridge_lambda':35,'clipping_per_feature_k':[-1,1],'prediction_delta_limit_C':1.0,
            'fitted_exclusively_on_donor_train_years':True,
            'mean_fitted_coefficient_by_buffer':{str(buff):{name:float(np.mean([f[name] for f in coeff if f['buffer_km']==buff])) for name in ('valley_cold_k','ridge_cold_k','valley_warm_k','ridge_warm_k')} for buff in BUFFERS}},
        'limitations':['monthly mean air temperatures do not confirm nighttime vertical inversion profiles',
           'regime labels are heuristic morphology not externally classified',
           'model hyperparameters fixed by investigator on a repeatedly analyzed station collection',
           'full independent region and external DEM source holdout pending',
           'this reconstructs monthly weather from contemporary donor observations; does not forecast weather ten years ahead']}
    (out/'p8_1d_report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print('P8.1D FINAL',json.dumps({'metrics':metrics,'bootstrap_all':[x for x in bootstrap if x.get('regime')=='all'],
         'folds':folds,'regime_counts':dict(labels)},ensure_ascii=False),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--station-normals',required=True)
    p.add_argument('--terrain',required=True);p.add_argument('--out',required=True);p.add_argument('--batch',type=int,default=16)
    x=p.parse_args();execute(x.station_normals,x.terrain,x.out,x.batch)