#!/usr/bin/env python3
"""P8.1F geographical block holdout: independent Switzerland 2011-2020;
regional lapse and terrain coefficients calibrated exclusively Austria 1991-2010.
Target region has zero donors; contemporaneous outside-region Swiss donor weather
is OBSERVED, therefore this is spatial reconstruction, NOT a future forecast.
"""
from __future__ import annotations
import argparse,collections,hashlib,json,math,csv
from pathlib import Path
import numpy as np
from p8_1e_swiss_external import (inventory_probe,select_stations,fetch,parse_month_csv,
                                 austria_train_lapse,TIME_YEARS)
from p8_1b_terrain_holdout import haversine,LAPSE,MAX_KM
from p8_1c_dem import TileCache,sample_locations,tile_point,BEARINGS
from p8_1d_regime import regime,predict_regime
from p8_1b_temporal_holdout import save_csv

BUFFERS=(0,50)
METHODS=('idw_raw','idw_fixed65','idw_austria_regional','frozen_austria_regime')
CO_FIELDS=('valley_cold_k','ridge_cold_k','valley_warm_k','ridge_warm_k')

def region(site):
    """Frozen country-wide longitude partition, no outcomes used."""
    lon=float(site['lon'])
    return 'west_lt7.5E' if lon<7.5 else 'central_7.5_to_9E' if lon<9.0 else 'east_ge9E'

def swiss_dem(sites,cache):
    """Original Mapzen DEM at center, radial 250,1500,5000 and 10000m."""
    coords={s['station_id']:sample_locations(s) for s in sites}
    keys={tile_point(lat,lon,cache.zoom)[0] for points in coords.values() for lat,lon in points}
    cache.prefetch(keys,workers=10)
    values=[];missing=[]
    for s in sites:
        try:heights=np.array([cache.point(lat,lon) for lat,lon in coords[s['station_id']]],float)
        except (ValueError,KeyError) as e:missing.append({'station':s['station_id'],'error':str(e)});continue
        center=heights[0];rings=[heights[1+i*len(BEARINGS):1+(i+1)*len(BEARINGS)] for i in range(4)]
        r250,r1500,r5000,_=rings
        slope=float(max(abs(r250[i]-r250[(i+6)%12]) for i in range(6))/500.)
        item={**s,'tpi_1500_m':float(center-np.mean(r1500)),
         'tpi_5000_m':float(center-np.mean(r5000)),'rugged_1500_m':float(np.std(r1500)),
         'slope_250m_proxy':slope,'dem_height_m':float(center),'dem_disagreement_m':float(center-s['hoehe_m'])}
        item['orographic_regime']=regime(item);item['heldout_region']=region(item)
        values.append(item)
    return values,missing

def predict_one(target,donors,values,year,month,monthly_lapse,frozen,buffer):
    ym=f'{year:04d}-{month:02d}'
    if ym not in values.get(target['station_id'],{}):return None
    train_donors=[]
    for d in donors:
        if region(d)==region(target):raise AssertionError('GEOGRAPHIC REGION LEAKAGE')
        if ym not in values.get(d['station_id'],{}):continue
        dist=haversine(target['lat'],target['lon'],d['lat'],d['lon'])
        if dist>=buffer and dist<=MAX_KM:train_donors.append((float(dist),d))
    train_donors=sorted(train_donors,key=lambda v:(v[0],v[1]['station_id']))[:8]
    if len(train_donors)<8:return None
    dist=np.array([d for d,_ in train_donors]);w=np.maximum(dist,.25)**(-2);w/=w.sum()
    temps=np.array([values[d['station_id']][ym] for _,d in train_donors]);delta=np.array([target['hoehe_m']-d['hoehe_m'] for _,d in train_donors])
    base=float(w@temps);f65=float(w@(temps+LAPSE*delta));reg=float(w@(temps+monthly_lapse[month-1]*delta))
    wcoeff=frozen['by_buffer'][str(buffer)];coef=np.array([wcoeff[n] for n in CO_FIELDS],float)
    adjusted,adjust=predict_regime(reg,target,[d for _,d in train_donors],w,coef,month)
    return {'idw_raw':base,'idw_fixed65':f65,'idw_austria_regional':reg,
            'frozen_austria_regime':adjusted},adjust

def evaluate(sites,values,monthly_lapse,frozen):
    result=[];counts=collections.Counter()
    for target in sites:
        other=[s for s in sites if region(s)!=region(target)]
        for b in BUFFERS:
            for year in TIME_YEARS:
                for mon in range(1,13):
                    x=predict_one(target,other,values,year,mon,monthly_lapse,frozen,b)
                    if x is None:counts[(region(target),b,'unscored')]+=1;continue
                    pred,cor=x;obs=values[target['station_id']][f'{year}-{mon:02d}']
                    for model,v in pred.items():
                        result.append({'region':region(target),'station_id':target['station_id'],
                         'elevation_m':target['hoehe_m'],'regime':target['orographic_regime'],
                         'buffer_km':b,'year':year,'month':mon,'method':model,'error_c':float(v-obs),
                         'abs_error_c':float(abs(v-obs)),'terrain_delta_c':float(cor) if model=='frozen_austria_regime' else 0.})
                    counts[(region(target),b,'scored')]+=1
    return result,dict((str(k),v) for k,v in counts.items())

def aggregate(rows,keys):
    groups=collections.defaultdict(list)
    for r in rows:groups[tuple(r[k] for k in keys)].append(r)
    ans=[]
    for tup,values in sorted(groups.items()):
        x=np.array([v['error_c'] for v in values])
        ans.append({**dict(zip(keys,tup)),'n':len(x),'stations':len({v['station_id'] for v in values}),
         'MAE_C':float(np.abs(x).mean()),'RMSE_C':float(np.sqrt(np.mean(x*x))),'bias_C':float(np.mean(x)),
         'mean_abs_terrain_delta_C':float(np.mean([abs(v['terrain_delta_c']) for v in values]))})
    return ans

def station_bootstrap(rows,buffer,compar='frozen_austria_regime',base='idw_austria_regional',reps=3000):
    paired=collections.defaultdict(dict)
    for r in rows:
        if r['buffer_km']==buffer and r['method'] in (compar,base):
            paired[(r['station_id'],r['year'],r['month'])][r['method']]=r['abs_error_c']
    bys=collections.defaultdict(list)
    for (site,_,_),pair in paired.items():
        if set(pair)=={base,compar}:bys[site].append(pair[base]-pair[compar])
    v=np.array([np.mean(x) for x in bys.values()]);
    if len(v)<8:return {'status':'INSUFFICIENT_STATIONS','n':len(v)}
    rng=np.random.default_rng(20261014+buffer);bootstrap=v[rng.integers(0,len(v),size=(reps,len(v)))].mean(1)
    return {'n_stations':len(v),'mean_station_gain_C':float(v.mean()),
      'station_cluster_CI95_C':np.quantile(bootstrap,[.025,.975]).tolist(),
      'note':'station-cluster CI ignores dependency among adjacent stations, conditional exploration only'}

def run(normals_path,coef_path,out,max_sites=36,cache=None):
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    frozen=json.loads(Path(coef_path).read_text());assert frozen['source_stage']=='P8.1D'
    swiss,assets,probe=inventory_probe(dest)
    selected=select_stations(swiss,assets,max_sites)
    samples={};digests=[];issues=[]
    for s in selected:
        sid=s['station_id'];merged={}
        for url in assets[sid]:
            try:
                blob,digest=fetch(url,max_bytes=15000000)
                obs,cols=parse_month_csv(blob,sid)
                merged.update(obs)
                digests.append({'station':sid,'sha256':digest,'n_test_months':len(obs),'bytes':len(blob)})
            except Exception as exc:issues.append({'station':sid,'error':str(exc)})
        if len(merged)>=96:samples[sid]=merged
    selected=[s for s in selected if s['station_id'] in samples]
    if len(selected)<18:raise RuntimeError('Insufficient Swiss weather stations')
    raw_normals=Path(normals_path).read_bytes();monthly,cal=austria_train_lapse(json.loads(raw_normals))
    dem=TileCache(cache or dest/'dem_cache',11)
    sites,demfail=swiss_dem(selected,dem)
    sites=[s for s in sites if s['station_id'] in samples]
    region_sizes=collections.Counter(region(x) for x in sites)
    if len(region_sizes)<3 or min(region_sizes.values())<3:raise RuntimeError('Insufficient geographic coverage '+str(region_sizes))
    rows,counts=evaluate(sites,samples,monthly,frozen)
    if len(rows)<4000:raise RuntimeError('Insufficient region-blocked comparisons')
    targets={(r['region'],r['station_id'],r['year'],r['month'],r['buffer_km']) for r in rows}
    if len(rows)!=len(targets)*len(METHODS):raise AssertionError('Unpaired method comparison')
    metrics=aggregate(rows,['buffer_km','method'])
    by_region=aggregate(rows,['region','buffer_km','method'])
    by_regime=aggregate(rows,['regime','buffer_km','method'])
    by_station=aggregate(rows,['region','station_id','elevation_m','regime','buffer_km','method'])
    for name,table in [('metrics',metrics),('regions',by_region),('regimes',by_regime),('stations',by_station)]:
        save_csv(dest/f'spatial_{name}.csv',table)
    boot={str(b):station_bootstrap(rows,b) for b in BUFFERS}
    manifest={'phase':'P8.1F','source':'MeteoSwiss SwissMetNet, Mapzen DEM; GeoSphere Austria calibration',
      'austria_train_period':[1991,2010],'swiss_test_period':[2011,2020],
      'n_swiss_sites':len(sites),'n_site_month_buffer':len(targets),'region_counts':dict(region_sizes),
      'excluded_donors':'ALL Swiss sites in same predefined longitude region as target',
      'max_donor_distance_km':MAX_KM,'spatial_buffers_km':BUFFERS,
      'frozen_terrain_source':frozen,'monthly_austria_training':cal,
      'station_source_sha256':hashlib.sha256(raw_normals).hexdigest(),
      'dem_tile_count':len(dem.sha),'dem_hashes':dem.sha,
      'dem_invalid_pixel_diagnostics':{k:v for k,v in dem.tile_stats.items() if v.get('implausible_pixels',0)>0},
      'dem_point_failures':demfail,'swiss_source_hashes':digests,'source_issues':issues,
      'scored':counts,'metrics':metrics,'region_metrics':by_region,'bootstrap':boot,
      'source_data_published':False,
      'important_caveat':'Same-month donor weather observed OUTSIDE heldout region; spatial interpolation NOT advance weather forecasting',
      'terrain_caveat':'Frozen P8.1D coefficients are exploratory averages across Austrian LOO folds, not prospectively preregistered parameters',
      'transfer_caveat':'Three longitude blocks are only geographically separated subregions of one Alpine country; no globally independent climate-regime benchmark.'}
    (dest/'spatial_provenance.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    print('IGE_P8_1F_SPATIAL_RESULT',json.dumps({'n_sites':len(sites),'regions':dict(region_sizes),'metrics':metrics,'by_region':by_region,'bootstrap':boot,'dem_tiles':len(dem.sha)}),flush=True)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--austria-station-normals',required=True)
    p.add_argument('--frozen-params',required=True);p.add_argument('--out',required=True)
    p.add_argument('--max-sites',type=int,default=36)
    a=p.parse_args();run(a.austria_station_normals,a.frozen_params,a.out,a.max_sites)