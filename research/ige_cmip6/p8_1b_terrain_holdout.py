#!/usr/bin/env python3
"""IGE P8.1B station-relief-aware temperature interpolation and strict spatial LOOCV.

Source: independent station monthly norms, Tauernwetter/GeoSphere, not Meteonorm.
This is a STATION-RELIEF proxy, NOT DEM-aware topography. All empirical
lapse rates are recomputed excluding each target station. Exploratory ablation
results MUST NOT be advertised as independently selected model accuracy.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from pathlib import Path
import numpy as np

FIELDS=('tmittel','tmax','tmin')
METHODS=('idw_raw','idw_fixed65','idw_global_lapse','idw_local_lapse')
MONTHS=range(1,13)
RADII=(0,10,25,50)
K=8
LAPSE=-0.0065
MAX_KM=350.0
PERIOD='1991–2020'

def haversine(lat1,lon1,lat2,lon2):
    la1,la2=np.radians([lat1,lat2]); dlo=np.radians(lon2-lon1)
    aa=np.sin((la2-la1)/2)**2+np.cos(la1)*np.cos(la2)*np.sin(dlo/2)**2
    return 12742.0176*np.arcsin(np.minimum(1,np.sqrt(aa)))

def valid(x,f):
    v=x.get(f)
    return x.get('periode')==PERIOD and isinstance(v,list) and len(v)==12 and all(isinstance(y,(float,int)) and math.isfinite(y) for y in v)

def weighted_slope(y,z,weight,prior=-.0065,prior_var=.002**2,lo=-.012,hi=.003):
    """One-parameter Gaussian-ridge estimate of lapse slope [K/m].

    Observation errors have temperature-scale sigma=2 C, and fixed prior
    sigma_lapse=0.002 K/m. Deterministic and fully out-of-station.
    """
    w=np.asarray(weight,float);w=w/w.sum()
    z=np.asarray(z,float);y=np.asarray(y,float)
    zz=z-np.sum(w*z); yy=y-np.sum(w*y)
    # A local data-driven slope shrunk to physical prior.  sigmaT=2C.
    sigma2=4.
    prec=1/prior_var
    den=np.sum(w*zz**2)/sigma2+prec
    estimate=(np.sum(w*zz*yy)/sigma2+prec*prior)/den
    return float(np.clip(estimate,lo,hi))

def global_slope(train,month,field):
    """Spatial regression: temperature ~ lat + lon + station elevation.

    2D coordinates are centered and scaled; shrink residual elevation slope
    toward the fixed environmental lapse. Target is omitted before fitting.
    """
    z=np.asarray([s['hoehe_m'] for s in train],float)
    lat=np.asarray([s['lat'] for s in train],float)
    lon=np.asarray([s['lon'] for s in train],float)
    y=np.asarray([s[field][month] for s in train],float)
    # Partial out regional lat/lon (unpenalized intercept and horizontal gradients).
    X=np.column_stack([np.ones(len(z)),lat-np.mean(lat),lon-np.mean(lon)])
    residual_z=z-X@np.linalg.lstsq(X,z,rcond=None)[0]
    residual_y=y-X@np.linalg.lstsq(X,y,rcond=None)[0]
    # Pseudo observations for lapse physical prior: ridge strength corresponds
    # to 100 m elevation separation at sigma_t=2 C, yielding stable estimates.
    denominator=float(np.dot(residual_z,residual_z)+100.**2)
    est=(float(np.dot(residual_z,residual_y))+100.**2*LAPSE)/denominator
    return float(np.clip(est,-.012,.003))

def local_slope(near,field,month,global_est):
    """Local regression slope and an explicit reliability-based shrinkage.

    Residualize against horizontal position to reduce geographic confounding.
    For 16 donors, use an elevation variance-driven statistical shrinkage;
    large variance supports local vertical signal, short range limits it.
    """
    distances=np.asarray([d for d,s in near],float)
    st=[s for d,s in near]
    weights=1/np.maximum(distances,5.)**1.5;weights/=weights.sum()
    z=np.asarray([s['hoehe_m'] for s in st],float)
    yy=np.asarray([s[field][month] for s in st],float)
    lat=np.asarray([s['lat'] for s in st],float)
    lon=np.asarray([s['lon'] for s in st],float)
    X=np.column_stack([np.ones(len(st)),lat-np.mean(lat),lon-np.mean(lon)])
    xw=X*np.sqrt(weights)[:,None]
    zhat=X@np.linalg.lstsq(xw,z*np.sqrt(weights),rcond=None)[0]
    yhat=X@np.linalg.lstsq(xw,yy*np.sqrt(weights),rcond=None)[0]
    dz=z-zhat; dy=yy-yhat
    # Equivalent 150 m prior elevation uncertainty, global donor slope as prior.
    denominator=float(np.sum(weights*dz*dz)+150.**2)
    estimate=(float(np.sum(weights*dz*dy))+150.**2*global_est)/denominator
    return float(np.clip(estimate,-.012,.003))

def experiment(stations,radii=RADII,fields=FIELDS):
    src=[s for s in stations if s.get('periode')==PERIOD]
    res=[]
    for target in src:
        good=[s for s in src if s['station_id']!=target['station_id']]
        distances=sorted([(float(haversine(target['lat'],target['lon'],s['lat'],s['lon'])),s) for s in good],key=lambda a:(a[0],a[1]['station_id']))
        for field in fields:
            if not valid(target,field): continue
            valid_all=[(d,s) for d,s in distances if valid(s,field) and d<=MAX_KM]
            for radius in radii:
                donors=[(d,s) for d,s in valid_all if d>=radius]
                if len(donors)<K:continue
                near=donors[:K]
                dists=np.array([d for d,s in near]); weights=1/np.maximum(.25,dists)**2
                weights/=weights.sum()
                dz=np.array([target['hoehe_m']-s['hoehe_m'] for d,s in near])
                # Global lapse also respects geographic buffer exclusion; near-target
                # holdout weather cannot leak into its trend calibration.
                training=[s for d,s in donors]
                for m in range(12):
                    gl=global_slope(training,m,field)
                    loc=local_slope(donors[:min(16,len(donors))],field,m,gl)
                    y=np.array([s[field][m] for d,s in near]);obs=target[field][m]
                    for method,lapse in [('idw_raw',0.),('idw_fixed65',LAPSE),('idw_global_lapse',gl),('idw_local_lapse',loc)]:
                        estimate=float(np.dot(weights,y+lapse*dz))
                        res.append({'station_id':target['station_id'],'station':target['station'],'latitude':target['lat'],'longitude':target['lon'],'elevation_m':target['hoehe_m'],'variable':field,'month':m+1,'radius_km':radius,'method':method,'observed':obs,'predicted':estimate,'error':estimate-obs,'abs_error':abs(estimate-obs),'lapse_K_km':lapse*1000,'donor_count':K,'nearest_km':dists[0],'nearest_elev_diff_m':abs(dz[0]),'donor_ids':';'.join(str(s['station_id']) for d,s in near)})
    return res

def metrics(rows,fields=('method','variable','radius_km')):
    groups={}
    for row in rows:
        key=tuple(row[x] for x in fields)
        groups.setdefault(key,[]).append(row)
    out=[]
    for key,items in sorted(groups.items()):
        a=np.array([x['error'] for x in items]);e=np.abs(a)
        out.append(dict(zip(fields,key),n_station_months=len(items),n_stations=len({x['station_id'] for x in items}),MAE=float(e.mean()),RMSE=float(np.sqrt(np.mean(a*a))),bias=float(a.mean()),P90_abs=float(np.quantile(e,.90)),max_abs=float(e.max())))
    return out

def save_csv(path,rows):
    if not rows:return
    with Path(path).open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def run(input_file,output_dir):
    blob=Path(input_file).read_bytes();raw=json.loads(blob);sites=raw['stationen'];out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    if len(sites)!=258:raise ValueError('Unexpected source station count; halt scientific comparability')
    rows=experiment(sites)
    ag=metrics(rows)
    heights=[{**r,'band':'<500m' if r['elevation_m']<500 else '500-1500m' if r['elevation_m']<1500 else '>=1500m'} for r in rows]
    agheight=metrics(heights,('method','variable','radius_km','band'))
    agmonths=metrics(rows,('method','variable','radius_km','month'))
    focus_ids={30,105,175,39,213,196}
    focus=metrics([r for r in rows if r['station_id'] in focus_ids],('station_id','station','method','variable','radius_km'))
    save_csv(out/'station_month_holdouts.csv',rows)
    save_csv(out/'aggregate_metrics.csv',ag)
    save_csv(out/'altitude_skill.csv',agheight)
    save_csv(out/'monthly_skill.csv',agmonths)
    save_csv(out/'key_station_skill.csv',focus)
    diag={'stage':'P8.1B','source_sha256':hashlib.sha256(blob).hexdigest(),'n_source_stations':len(sites),'n_common_period':sum(s['periode']==PERIOD for s in sites),'station_month_predictions':len(rows),'target_station_excluded':True,'monthly_normals_only':True,'historical_year_holdout_performed':False,'independent_of_meteonorm':True,'terrain_flag':'STATION_RELIEF_PROXY_NOT_DEM','fixed_lapse_K_km':LAPSE*1000,'model_selection_status':'EXPLORATORY_ABLATION_NO_INDEPENDENT_MODEL_SELECTION','altitude_band_station_count':{'low':sum(s['hoehe_m']<500 and s['periode']==PERIOD for s in sites),'mid':sum(500<=s['hoehe_m']<1500 and s['periode']==PERIOD for s in sites),'high':sum(s['hoehe_m']>=1500 and s['periode']==PERIOD for s in sites)}}
    (out/'manifest.json').write_text(json.dumps(diag,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(diag,indent=2));
    for a in ag:
        if a['radius_km']==0:print(a['method'],a['variable'],round(a['MAE'],4),round(a['RMSE'],4))
    return ag

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('source');ap.add_argument('--out',required=True)
    a=ap.parse_args();run(a.source,a.out)