#!/usr/bin/env python3
"""P8.1D observational hourly *paired-station* inversion-indicator pilot.

Two separated stations are never equivalent to a colocated vertical profile.
Positive upper-minus-lower air temperature documents warm-above-cold
horizontal-pair stratification, not proof of a continuous inversion layer.
"""
from __future__ import annotations
import argparse,collections,csv,datetime,hashlib,json,math
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from p8_1b_temporal_holdout import fetch_json,GOOD_FLAGS,save_csv

BASE='https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h'
# Valleys and their nearby upper stations; explicit IDs and elevations audited
# against station DEM inventory. Never select pairs using test temperature.
PAIRS=((119,14305,'St.Anton-Galzig'),(28,17005,'Galtuer-Idalpe'),
       (66,184,'Obergurgl-Pitztal'),(39,196,'Innsbruck-Patscherkofel'))
WINTERS=((2015,1),(2018,1)); SUMMERS=((2015,7),(2018,7))
PERIODS=WINTERS+SUMMERS


def unpack(data,station_ids,expected,flag_name):
    times=data.get('timestamps',[])
    if len(times)!=expected or not times:raise ValueError('Incomplete timestamp axis')
    datetime_utc=[]
    for t in times:
        dt=datetime.datetime.fromisoformat(str(t).replace('Z','+00:00'))
        if dt.tzinfo is None:raise ValueError('Missing timezone in hourly record')
        datetime_utc.append(dt.astimezone(datetime.timezone.utc))
    if len(set(datetime_utc))!=len(datetime_utc):raise ValueError('Duplicate times')
    if any((datetime_utc[i+1]-datetime_utc[i]).total_seconds()!=3600 for i in range(len(datetime_utc)-1)):
        raise ValueError('Discontinuous hourly observations')
    data_out={}
    for f in data.get('features',[]):
        p=f.get('properties',{});i=p['station'];sid=int(i if not isinstance(i,dict) else i['id'])
        if sid not in station_ids or sid in data_out:raise ValueError('Duplicate/unrequested hourly station')
        params=p.get('parameters',{});item=params.get('tl')
        if not item or item.get('unit') not in ('°C','degC'):continue
        temps=item.get('data',[])
        if len(temps)!=expected:raise ValueError('Shortened hourly temperature')
        flags=params.get(flag_name,{}).get('data') if flag_name else None
        if flag_name and (flags is None or len(flags)!=expected):continue
        values={}
        for j,val in enumerate(temps):
            if val is None:continue
            if flag_name and flags[j] not in GOOD_FLAGS:continue
            t=float(val)
            if not math.isfinite(t) or not -80<t<65:raise ValueError('Nonphysical hourly temperature')
            values[datetime_utc[j]]=t
        data_out[sid]=values
    return data_out


def summarize_pairs(series,sites,year,month,metadata):
    results=[];tz=ZoneInfo('Europe/Vienna')
    for lower,upper,name in PAIRS:
        if lower not in series or upper not in series:continue
        lower_meta=sites.get(lower);upper_meta=sites.get(upper)
        if not lower_meta or not upper_meta:continue
        dz=float(upper_meta['altitude'])-float(lower_meta['altitude'])
        if dz<=150:raise ValueError('Expected higher upper station')
        for phase in ('night','day'):
            indices=[]
            for stamp in sorted(set(series[lower]).intersection(series[upper])):
                local=stamp.astimezone(tz)
                hour=local.hour
                is_night=hour>=22 or hour<6
                if (phase=='night')!=is_night:continue
                # daytime strict solar-day 10..16, others excluded from phase summary
                if phase=='day' and not 10<=hour<16:continue
                v=series[upper][stamp]-series[lower][stamp]
                indices.append(v)
            if not indices:continue
            n=len(indices);q=sum(v>0 for v in indices)
            results.append({'pair':name,'lower_station_id':lower,'upper_station_id':upper,
                'vertical_separation_m':dz,'year':year,'month':month,
                'season':'winter' if month==1 else 'summer',
                'time_of_day':phase,'qualified_paired_hours':n,
                'fraction_upper_warmer':q/n,
                'mean_upper_minus_lower_C':sum(indices)/n,
                'qualified_upper_warmer_hours':q})
    return results


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    m,sha,_=fetch_json(BASE+'/metadata')
    meta={p['name']:p for p in m['parameters']}
    if meta.get('tl',{}).get('unit') not in ('°C','degC'):raise ValueError('Missing GeoSphere hourly tl')
    flag='tl_flag' if 'tl_flag' in meta else None
    sites={int(s['id']):s for s in m['stations']}
    ids=sorted({j for pair in PAIRS for j in pair[:2]})
    rows=[];req=[]
    for year,month in PERIODS:
        last=(datetime.date(year+1,1,1)-datetime.timedelta(days=1)).day if month==12 else (datetime.date(year,month+1,1)-datetime.timedelta(days=1)).day
        url=BASE+'?'+urlencode({'parameters':'tl'+(','+flag if flag else ''),'station_ids':','.join(map(str,ids)),
              'start':f'{year:04d}-{month:02d}-01T00:00Z','end':f'{year:04d}-{month:02d}-{last}T23:00Z',
              'output_format':'geojson'})
        data,digest,bytesread=fetch_json(url)
        values=unpack(data,set(ids),last*24,flag)
        rows+=summarize_pairs(values,sites,year,month,m)
        req.append({'year':year,'month':month,'sha256':digest,'bytes':bytesread,'stations_with_valid_data':len(values)})
    if sum(r['qualified_paired_hours'] for r in rows)<800 or len({r['pair'] for r in rows})<2:
        raise RuntimeError('Insufficient hourly validation station-pairs')
    save_csv(out/'p8_1d_hourly_pair_stratification.csv',rows)
    diag={'inference':'paired-station warm-above-cold temperature frequency, not collocated atmospheric profile inversion',
        'registered_pairs':list(PAIRS),'periods':list(PERIODS),'n_aggregates':len(rows),
        'n_station_pairs':len({r['pair'] for r in rows}),
        'n_qualified_pair_hours':sum(r['qualified_paired_hours'] for r in rows),
        'original_api_sha256':req,'metadata_sha256':sha,'no_hourly_originals_published':True,
        'limit':'Upper and valley sites differ horizontally and in exposure: warm-above-cold pairing is not proof of a local inversion layer.'}
    (out/'p8_1d_hourly_pilot_provenance.json').write_text(json.dumps(diag,indent=2)+'\n')
    print('P8.1D OBSERVATIONAL HOURLY PILOT',json.dumps({'pairs':diag['n_station_pairs'],'hours':diag['n_qualified_pair_hours'],'rows':rows}),flush=True)
    return diag

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    run(parser.parse_args().out)