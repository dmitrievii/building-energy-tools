#!/usr/bin/env python3
"""IGE P6.2A independent monthly Graz observation diagnostic (NO fitting).

GeoSphere station 30 vs the mean monthly NASA ACCESS-CM2 1995–2014
climatology; not aligned daily weather, not bias-correction training.

GeoSphere tl_mittel is an observation-time/extremes-based monthly air temperature
metric; NASA tas is mean daily near-surface temperature; definitions differ.
Station 30 (47.08N, 15.448056E, 366 m) does NOT coincide with NASA
model cell center (46.875N,15.375E). Both discrepancies are documented.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m"
STATION=30
PARAMS={'tl_mittel':'°C','rr':'mm'}
FIRST,LAST=1995,2014

def get(url,limit=12000000):
    with urlopen(Request(url,headers={'User-Agent':'IGE-P6.2A-OpenClimate-Research',
                                      'Accept':'application/json'}),timeout=120) as response:
        raw=response.read(limit+1)
        if response.status!=200 or len(raw)>limit:
            raise RuntimeError('GeoSphere response truncated or unavailable')
    return raw

def extract_monthly(d):
    stamp=d.get('timestamps',[])
    expected=[f'{y:04d}-{m:02d}' for y in range(FIRST,LAST+1) for m in range(1,13)]
    if len(stamp)!=240 or [str(s)[:7] for s in stamp]!=expected:
        raise ValueError('GeoSphere timeline is not complete 1995–2014')
    features=d.get('features',[])
    if len(features)!=1:
        raise ValueError('GeoSphere station selection does not contain exactly one feature')
    prop=features[0]['properties']
    station=prop['station']
    ident=int(station if not isinstance(station,dict) else station['id'])
    if ident!=STATION:raise ValueError('Unexpected station')
    parms=prop.get('parameters',{})
    for p,u in PARAMS.items():
        if p not in parms or parms[p]['unit']!=u or len(parms[p]['data'])!=240:
            raise ValueError(f'GeoSphere parameter coverage or units invalid: {p}')
    records=[]
    for i,label in enumerate(expected):
        y,m=map(int,label.split('-'))
        rr=parms['rr']['data'][i]
        t=parms['tl_mittel']['data'][i]
        def parse(v):
            if v is None:return None
            x=float(v)
            if not math.isfinite(x):raise ValueError('Nonfinite GeoSphere station value')
            return x
        rr=parse(rr);t=parse(t)
        if rr is not None and rr<0:raise ValueError('Negative station monthly precipitation')
        records.append({'year':y,'month':m,'obs_temp_c':t,'obs_pr_mm':rr})
    return records

def compare_monthly(records, model_climatology):
    with Path(model_climatology).open(newline='',encoding='utf8') as f:
        mod=list(csv.DictReader(f))
    if len(mod)!=12 or {int(x['month']) for x in mod}!=set(range(1,13)):
        raise ValueError('Wrong NASA 12-month climatology')
    bymonth={int(x['month']):x for x in mod}
    if any(x.get('window')!='historical-1995-2014' or
           x.get('scenario')!='historical' or int(x.get('years','0'))!=20 for x in mod):
        raise ValueError('Model climatology is not historical 1995–2014')
    details=[]
    for m in range(1,13):
        subset=[r for r in records if r['month']==m]
        obs_t=[r['obs_temp_c'] for r in subset if r['obs_temp_c'] is not None]
        obs_pr=[r['obs_pr_mm'] for r in subset if r['obs_pr_mm'] is not None]
        # Report incomplete station coverage instead of silently imputing it.
        if len(obs_t)<18 or len(obs_pr)<18:
            raise ValueError(f'Insufficient observed coverage month {m}')
        obs_t_mean=fmean(obs_t)
        obs_pr_mean=fmean(obs_pr)
        source=bymonth[m]
        model_t=float(source['tas_mean_c'])
        model_pr=float(source['pr_mean_mm'])
        details.append({'month':m,'station_temperature_samples':len(obs_t),
                        'station_precipitation_samples':len(obs_pr),
                        'station_tl_mittel_c':obs_t_mean,
                        'nasa_tas_c':model_t,
                        'nasa_minus_station_t_c':model_t-obs_t_mean,
                        'station_monthly_precip_mm':obs_pr_mean,
                        'nasa_monthly_precip_mm':model_pr,
                        'nasa_minus_station_pr_mm':model_pr-obs_pr_mean})
    return {
        'status':'PASS','station_id':STATION,'observation_period':'1995-2014',
        'monthly':details,
        'station_annual_mean_monthly_precip_total_mm':
            sum(x['station_monthly_precip_mm'] for x in details),
        'model_annual_mean_monthly_precip_total_mm':
            sum(x['nasa_monthly_precip_mm'] for x in details),
        'temperature_monthly_climatology_mae_c':
            fmean(abs(x['nasa_minus_station_t_c']) for x in details),
        'caution':'Spatially mismatched station/gridded NEX data; tl_mittel differs from tas. '
                  'Neither day-aligned error nor out-of-sample performance; NO bias correction.'
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model-climatology',type=Path,required=True)
    p.add_argument('--out',type=Path,default=Path('outputs/p6_2a/geosphere_graz'))
    a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    meta_raw=get(BASE+'/metadata')
    metadata=json.loads(meta_raw)
    stations={int(st['id']):st for st in metadata.get('stations',[]) if 'id' in st}
    if STATION not in stations:raise ValueError('GeoSphere Graz station 30 missing')
    spec={p['name']:p for p in metadata.get('parameters',[])}
    if any(spec.get(p,{}).get('unit')!=unit for p,unit in PARAMS.items()):
        raise ValueError('Provider parameter units changed')
    query=urlencode({'station_ids':str(STATION),'parameters':','.join(PARAMS),
                     'start':'1995-01-01','end':'2014-12-31',
                     'output_format':'geojson'})
    url=BASE+'?'+query
    raw=get(url)
    station_records=extract_monthly(json.loads(raw))
    (a.out/'geosphere_station30_1995_2014_raw.geojson').write_bytes(raw)
    report=compare_monthly(station_records,a.model_climatology)
    report['station_metadata']=stations[STATION]
    report['metadata_sha256']=hashlib.sha256(meta_raw).hexdigest()
    report['station_data_sha256']=hashlib.sha256(raw).hexdigest()
    report['geosphere_source_url']=url
    report['nasa_monthly_csv_sha256']=hashlib.sha256(a.model_climatology.read_bytes()).hexdigest()
    (a.out/'observed_vs_nasa_monthly_climatology.json').write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print('P6.2A GEOSPHERE MONTHLY COMPARISON',report['status'],
          'Graz station 30; 20 years; 12 months; temperature MAE',
          round(report['temperature_monthly_climatology_mae_c'],3),flush=True)

if __name__=='__main__':main()
