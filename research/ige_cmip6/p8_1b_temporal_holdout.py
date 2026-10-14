#!/usr/bin/env python3
"""GeoSphere Austria 1991–2020: spatially withheld STATIONS + temporally withheld YEARS.

Source: https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m
1991–2010: climate lapse calibration on donor stations only.
2011–2020: withheld target observations scored; target station never a donor.
Contemporaneous 2011–2020 donor observations ARE used for reconstruction.
Therefore this is OUT-OF-PERIOD SPATIAL INTERPOLATION, not a year-ahead forecast.
No Meteonorm data. Raw monthly source responses remain ephemeral/private and are
not included in GitHub or released aggregated results. Standard library + NumPy.
"""
from __future__ import annotations
import argparse,collections,csv,hashlib,json,math,time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen,Request
import numpy as np
from p8_1b_terrain_holdout import haversine,global_slope,local_slope,METHODS,MAX_KM,LAPSE

BASE='https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m'
TRAIN_YEARS=tuple(range(1991,2011)); TEST_YEARS=tuple(range(2011,2021))
GOOD_FLAGS={10,11,12,20,21,22}
FIELD='tl_mittel'


def fetch_json(url,maxbytes=18000000):
    errors=[]
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'IGE-P8.1B-station-temporal-validation','Accept':'application/json'}),timeout=125) as f:
                if f.status!=200:raise RuntimeError('HTTP status '+str(f.status))
                data=f.read(maxbytes+1)
                if len(data)>maxbytes:raise RuntimeError('GeoSphere response > limit')
            return json.loads(data),hashlib.sha256(data).hexdigest(),len(data)
        except (OSError,RuntimeError,ValueError) as e:
            errors.append(str(e))
            if attempt!=2:time.sleep(2**attempt)
    raise RuntimeError('GeoSphere request unavailable '+url+': '+' / '.join(errors))

def metadata_contract(meta,reference):
    params={x['name']:x for x in meta.get('parameters',[])}
    if FIELD not in params or params[FIELD].get('unit') not in ('°C','degC'):
        raise ValueError('GeoSphere monthly temperature param/units mismatch')
    ref={int(s['station_id']):s for s in reference if s.get('periode')=='1991–2020'}
    stations={int(s['id']):s for s in meta['stations'] if s.get('id') is not None}
    eligible={}
    skipped={}
    for sid,r in ref.items():
        s=stations.get(sid)
        if not s:
            skipped[sid]='provider station_id missing'
            continue
        lat=float(s.get('lat'));lon=float(s.get('lon'))
        # 5 km max station movement to safeguard cross-provider site identity.
        if float(haversine(lat,lon,r['lat'],r['lon']))>5:
            skipped[sid]='moved/other station coordinates > 5 km'
            continue
        altitude=s.get('altitude')
        if altitude is not None and abs(float(altitude)-float(r['hoehe_m']))>100:
            skipped[sid]='altitude metadata mismatch >100 m'
            continue
        eligible[sid]={'station_id':sid,'station':r['station'],'lat':lat,'lon':lon,'hoehe_m':float(r['hoehe_m'])}
    flag=FIELD+'_flag' if FIELD+'_flag' in params else None
    return eligible,flag,skipped

def station_id(p):
    obj=p['station']
    return int(obj if not isinstance(obj,dict) else obj['id'])

def decode_response(data,requested,flag_name):
    expected=[f'{year}-{m:02d}' for year in range(1991,2021) for m in range(1,13)]
    actual=[str(x)[:7] for x in data.get('timestamps',[])]
    if actual!=expected:raise ValueError(f'GeoSphere monthly axis incomplete/shifted: {len(actual)} vs 360')
    result={};diag=collections.Counter()
    for feature in data.get('features',[]):
        p=feature.get('properties',{});sid=station_id(p)
        if sid not in requested or sid in result:raise ValueError('Unexpected/duplicated station')
        param=p.get('parameters',{}).get(FIELD)
        if not isinstance(param,dict) or param.get('unit') not in ('°C','degC'):
            diag['missing_temperature_field_stations']+=1
            continue
        arr=param.get('data')
        if not isinstance(arr,list) or len(arr)!=360:raise ValueError('Wrong length temperature for '+str(sid))
        flag_data=None
        if flag_name:
            flagp=p.get('parameters',{}).get(flag_name)
            if isinstance(flagp,dict):flag_data=flagp.get('data')
            if flag_data is not None and len(flag_data)!=360:raise ValueError('Wrong QC flag axis')
            if flag_data is None:diag['stations_without_flag']+=1
        series={}
        for i,month in enumerate(expected):
            v=arr[i];good=False
            if v is not None:
                n=float(v)
                if not math.isfinite(n) or not -80<n<65:raise ValueError('Out-of-domain monthly T')
                good=not flag_name or (flag_data is not None and flag_data[i] in GOOD_FLAGS)
                if good:series[month]=n
                else:diag['rejected_unqualified_hours']+=1
            else:diag['null_station_months']+=1
        result[sid]=series
    return result,dict(diag)

def calibrate_donor_normals(stations,series):
    out=[]
    for sid,s in stations.items():
        avg=[]
        for month in range(1,13):
            a=[series.get(sid,{}).get(f'{year}-{month:02d}') for year in TRAIN_YEARS]
            valid=[v for v in a if v is not None]
            avg.append(float(np.mean(valid)) if len(valid)>=16 else None)
        if all(x is not None for x in avg):out.append({**s,'tmittel':avg})
    return out

def run_temporal(stations,series,flag_name,exclusion=0):
    """Never use 1991–2020 station normals for temperature; metadata only."""
    norms=calibrate_donor_normals(stations,series)
    out=[];eligible_count=len(norms)
    for target in norms:
        tid=target['station_id']; tseries=series.get(tid,{})
        dist=sorted([(float(haversine(target['lat'],target['lon'],s['lat'],s['lon'])),s)
                     for s in norms if s['station_id']!=tid],key=lambda x:(x[0],x[1]['station_id']))
        local=[(d,s) for d,s in dist if exclusion<=d<=MAX_KM]
        if len(local)<8:continue
        # Compute fixed historical lapse parameters solely from 1991-2010.
        slopes={}
        for month in range(12):
            g=global_slope([s for d,s in local],month,'tmittel')
            l=local_slope(local[:16], 'tmittel',month,g)
            slopes[month]=(g,l)
        for year in TEST_YEARS:
            for month in range(1,13):
                timestamp=f'{year}-{month:02d}';obs=tseries.get(timestamp)
                if obs is None:continue
                donors=[(d,s) for d,s in local if series.get(s['station_id'],{}).get(timestamp) is not None]
                if len(donors)<8:continue
                donors=donors[:8]
                weights=1/np.maximum(np.array([d for d,s in donors]),0.25)**2
                weights/=weights.sum()
                yd=np.array([series[s['station_id']][timestamp] for d,s in donors]);dz=np.array([target['hoehe_m']-s['hoehe_m'] for d,s in donors]);g,l=slopes[month-1]
                for method,rate in [('idw_raw',0.),('idw_fixed65',LAPSE),('idw_global_lapse',g),('idw_local_lapse',l)]:
                    pred=float(np.dot(weights,yd+rate*dz))
                    out.append({'station_id':tid,'station':target['station'],'elevation_m':target['hoehe_m'],'year':year,'month':month,'method':method,'observed':obs,'predicted':pred,'error':pred-obs,'MAE':abs(pred-obs),'calibration_years':'1991-2010','holdout_years':'2011-2020','n_donors':8})
    return out,eligible_count

def aggregates(rows,keys):
    groups=collections.defaultdict(list)
    for row in rows:groups[tuple(row[k] for k in keys)].append(row)
    out=[]
    for key,a in sorted(groups.items()):
        e=np.array([r['error'] for r in a],float)
        out.append({**dict(zip(keys,key)),'n_months':len(a),'n_stations':len({r['station_id'] for r in a}),'MAE_C':float(np.mean(np.abs(e))),'RMSE_C':float(np.sqrt(np.mean(e*e))),'bias_C':float(np.mean(e))})
    return out

def save_csv(path,rows):
    if not rows:return
    with open(path,'w',newline='',encoding='utf-8') as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)

def execute(source,out,batch=16):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    raw=Path(source).read_bytes();sdata=json.loads(raw)
    meta,meta_sha,meta_bytes=fetch_json(BASE+'/metadata')
    registered,flag,skipped=metadata_contract(meta,sdata['stationen'])
    if len(registered)<40:raise RuntimeError('Too few matching station ids: '+str(len(registered)))
    ids=sorted(registered);merged={};requests=[];quality=collections.Counter()
    for i in range(0,len(ids),batch):
        pack=ids[i:i+batch]
        args={'parameters':FIELD+(','+flag if flag else ''),'station_ids':','.join(str(v) for v in pack),'start':'1991-01-01','end':'2020-12-31','output_format':'geojson'}
        url=BASE+'?'+urlencode(args)
        data,sha,nbytes=fetch_json(url)
        rows,diag=decode_response(data,set(pack),flag)
        for key,n in diag.items():quality[key]+=n
        if set(rows)&set(merged):raise ValueError('Duplicate source station batch')
        merged.update(rows)
        requests.append({'batch':i//batch,'n_request_stations':len(pack),'n_response_stations':len(rows),'response_sha256':sha,'bytes':nbytes,'url':url})
    if len(merged)<40:raise RuntimeError('Too few available response stations')
    predictions,norms=run_temporal({k:v for k,v in registered.items() if k in merged},merged,flag)
    if not predictions:raise RuntimeError('No temporal holdout predictions')
    bymodel=aggregates(predictions,['method'])
    byyear=aggregates(predictions,['method','year'])
    bymonth=aggregates(predictions,['method','month'])
    bystation=aggregates(predictions,['method','station_id','station','elevation_m'])
    save_csv(out/'temporal_metrics.csv',bymodel);save_csv(out/'temporal_by_year.csv',byyear)
    save_csv(out/'temporal_by_month.csv',bymonth);save_csv(out/'temporal_by_station.csv',bystation)
    report={'stage':'P8.1B','evaluation_type':'station-excluded reconstruction using contemporaneous donor observations; lapse calibrated strictly 1991-2010','years_train':'1991–2010','years_test':'2011–2020','n_source_sites':len(sdata['stationen']),'matched_stations':len(registered),'returned_stations':len(merged),'usable_calibration_stations':norms,'n_predictions':len(predictions),'n_scored_target_months':len(predictions)//len(METHODS),'provider_metadata_sha256':meta_sha,'provider_metadata_bytes':meta_bytes,'source_station_normals_sha256':hashlib.sha256(raw).hexdigest(),'qc_flag_field':flag,'missing_provider_stations':len(skipped),'q21_qc':dict(quality),'provider_requests':requests,'metrics':bymodel,'limitations':['Scoring uses donor observations from target evaluation years, not a future-weather forecast','No target-station weather allowed in calibration, donor set, or prediction','Available 1991-2020 P8.1 normals used for identifiers/elevation only, never model temperature','Metadata and QC availability affect station sample; missing station-months are not filled','Station-relief proxy, no independent DEM','No third-party raw station series or commercial Meteonorm data published']}
    (out/'temporal_source_provenance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print('GEOSPHERE TEMPORAL HOLDOUT',json.dumps({'n':report['n_scored_target_months'],'matched':len(registered),'usable':norms,'metrics':bymodel}))
    return report

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--station-normals',required=True);a.add_argument('--out',required=True);a.add_argument('--batch',type=int,default=16)
    x=a.parse_args();execute(x.station_normals,x.out,x.batch)