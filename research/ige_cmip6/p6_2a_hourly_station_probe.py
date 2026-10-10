#!/usr/bin/env python3
"""P6.2A GeoSphere Austria v2 hourly station-30 source and quality-flag probe.

A one-week source/metadata feasibility check, NOT a 20-year daily validation.
Source times are UTC; retain provider hour semantics and parameter units.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen

BASE='https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h'
STATION_ID=30
CORE=('tl','rf','rr','cglo','ff','p')
EXPECTED_UNITS={'tl':('°C','degC'),'rf':('%',),
                'rr':('mm',),'cglo':('W/m²','W/m2','J/cm²','J/cm2'),
                'ff':('m/s',),'p':('hPa',)}

def fetch(url,maxbytes):
    req=Request(url,headers={'Accept':'application/json','User-Agent':'IGE-P6.2A-geosphere-hourly-probe'})
    with urlopen(req,timeout=100) as r:
        raw=r.read(maxbytes+1)
        if r.status!=200 or len(raw)>maxbytes or not raw:
            raise ValueError('GeoSphere hourly response missing/truncated')
    return raw

def parse_provider(meta,response):
    params={x['name']:x for x in meta.get('parameters',[])}
    station={int(x['id']):x for x in meta.get('stations',[]) if 'id' in x}
    if STATION_ID not in station:
        raise ValueError('GeoSphere monthly station 30 does not exist in hourly dataset; no silent substitution')
    for key in CORE:
        if key not in params:
            raise ValueError('Missing hourly parameter metadata: '+key)
        unit=params[key].get('unit')
        if unit not in EXPECTED_UNITS[key]:
            raise ValueError(f'Unrecognized GeoSphere parameter unit {key}={unit!r}')
    timestamps=response.get('timestamps',[])
    if not 150<=len(timestamps)<=192 or len(set(timestamps))!=len(timestamps):
        raise ValueError('Unexpected incomplete/duplicate hourly timeline')
    # Require UTC-offset awareness; no implicit conversion from Vienna wall clock.
    if not all(str(x).endswith(('+00:00','Z')) for x in timestamps):
        raise ValueError('Provider timestamps are not explicitly UTC')
    items=response.get('features',[])
    if len(items)!=1:raise ValueError('Expected exactly one selected hourly station')
    property=items[0]['properties']
    s=property['station']
    ident=int(s if not isinstance(s,dict) else s['id'])
    if ident!=STATION_ID:raise ValueError('Wrong GeoSphere station returned')
    measurements=property['parameters']
    inventory={}
    flags={}
    for key in CORE:
        v=measurements.get(key)
        if not isinstance(v,dict) or len(v.get('data',[]))!=len(timestamps):
            raise ValueError('Hourly provider field length mismatch: '+key)
        if v.get('unit') not in EXPECTED_UNITS[key]:
            raise ValueError('Inconsistent provider hourly unit: '+key)
        values=v['data']
        numbers=[float(z) for z in values if z is not None]
        if any(not math.isfinite(z) for z in numbers):
            raise ValueError('Nonfinite station observation: '+key)
        inventory[key]={'unit':v['unit'],'total_hours':len(values),
                        'available':len(numbers),'missing':len(values)-len(numbers),
                        'minimum':min(numbers) if numbers else None,
                        'maximum':max(numbers) if numbers else None,
                        'measurement_semantics':'verify against GeoSphere parameter metadata before daily aggregation'}
        flag_key=key+'_flag'
        if flag_key in params:
            f=measurements.get(flag_key)
            if isinstance(f,dict) and len(f.get('data',[]))==len(timestamps):
                flags[flag_key]={'observed_code_counts':dict(Counter(str(z) for z in f['data'])),
                                 'flag_metadata':params[flag_key]}
            else:
                flags[flag_key]={'not_returned_or_incomplete':True,
                                 'flag_metadata':params[flag_key]}
    if inventory['tl']['available']<120:
        raise ValueError('Station 30 not sufficient for even a week of hourly temperature')
    return {'status':'PASS','stage':'P6.2A_hourly_source_feasibility',
            'site':station[STATION_ID], 'provider_timestamp_timezone':'UTC',
            'timestamps_count':len(timestamps),'first_timestamp':timestamps[0],
            'last_timestamp':timestamps[-1],'fields':inventory,'quality_flags':flags,
            'cautions':['This seven-day hourly source check is NOT daily or interannual validation.',
                        'Quality flag code meanings have not been mapped to accepted/rejected levels.',
                        'A missing field is not zero and no gap filling has been applied.',
                        'Use parameter-specific semantics before hourly to daily aggregation.']}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=Path('outputs/p6_2a_hourly_source'))
    opts=ap.parse_args()
    opts.out.mkdir(parents=True,exist_ok=True)
    meta_raw=fetch(BASE+'/metadata',7000000)
    meta=json.loads(meta_raw)
    flag_params={x['name'] for x in meta.get('parameters',[])}
    requested=list(CORE)+[key+'_flag' for key in CORE if key+'_flag' in flag_params]
    query=urlencode({'station_ids':str(STATION_ID),'parameters':','.join(requested),
                     'start':'2020-07-01T00:00','end':'2020-07-07T23:00',
                     'output_format':'geojson'})
    url=BASE+'?'+query
    result_raw=fetch(url,5000000)
    result=parse_provider(meta,json.loads(result_raw))
    (opts.out/'raw_station30_oneweek_hourly.geojson').write_bytes(result_raw)
    (opts.out/'metadata_hourly_station30.json').write_text(json.dumps(
        {'source':BASE,'station':result['site'],
         'parameters':[x for x in meta['parameters'] if x['name'] in requested],
         'metadata_sha256':hashlib.sha256(meta_raw).hexdigest()},
        indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    result['source_url']=url
    result['source_sha256']=hashlib.sha256(result_raw).hexdigest()
    result['metadata_sha256']=hashlib.sha256(meta_raw).hexdigest()
    (opts.out/'p6_2a_hourly_feasibility.json').write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print('P6.2A HOURLY GEOSPHERE PROBE',result['status'],
          'hours',result['timestamps_count'],
          'fields',len(result['fields']),'flags',len(result['quality_flags']),flush=True)

if __name__=='__main__':
    main()
