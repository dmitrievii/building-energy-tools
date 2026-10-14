#!/usr/bin/env python3
"""IGE P8.1E: Frozen Austrian-trained lapse extrapolated to original MeteoSwiss observations.

The Swiss test observations NEVER calibrate lapse, choose model variants, or
select target sites. Same-month Swiss donors permitted: spatial hindcast, not
climate futures. GeoSphere Austria monthly 1991-2010 is the *sole training*.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,math,re,statistics,time,collections
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request,urlopen
import numpy as np
from p8_1b_terrain_holdout import haversine,global_slope,LAPSE,MAX_KM
from p8_1b_temporal_holdout import (BASE,FIELD,GOOD_FLAGS,fetch_json,metadata_contract,
                       decode_response,calibrate_donor_normals,save_csv)

STAC='https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn'
ROOT_HOST='data.geo.admin.ch'
TIME_YEARS=range(2011,2021)


def fetch(u,max_bytes=14000000):
    if urlparse(u).scheme!='https' or urlparse(u).hostname!=ROOT_HOST:
        raise ValueError('Refuse untrusted MeteoSwiss file host: '+u)
    failures=[]
    for t in range(3):
        try:
            with urlopen(Request(u,headers={'User-Agent':'IGE-P8.1E-scientific-external-holdout'}),timeout=75) as f:
                if f.status!=200:raise RuntimeError('HTTP '+str(f.status))
                raw=f.read(max_bytes+1)
                if len(raw)>max_bytes:raise ValueError('File exceeds response cap')
                return raw,hashlib.sha256(raw).hexdigest()
        except Exception as e:
            failures.append(str(e));time.sleep(t+1)
    raise RuntimeError('MeteoSwiss download failed '+u+' '+str(failures))

def decode_csv(raw):
    for encoding in ('utf-8-sig','cp1252'):
        try:t=raw.decode(encoding);break
        except UnicodeDecodeError:pass
    else:raise ValueError('Unsupported station CSV encoding')
    # MeteoSwiss OGD CSV semicolon delimiter; never use decimal comma replacement.
    r=csv.DictReader(io.StringIO(t),delimiter=';')
    if not r.fieldnames or len(r.fieldnames)<2:raise ValueError('Invalid MeteoSwiss CSV header')
    return list(r),tuple(r.fieldnames)

def pick_col(columns,*names):
    d={s.strip().casefold():s for s in columns}
    for n in names:
        if n.casefold() in d:return d[n.casefold()]
    return None

def parse_meta(raw):
    rows,cols=decode_csv(raw)
    c_id=pick_col(cols,'station_abbr','station','abbreviation','station_id')
    c_lat=pick_col(cols,'station_coordinates_wgs84_lat','station_wgs84_lat','latitude','lat')
    c_lon=pick_col(cols,'station_coordinates_wgs84_lon','station_wgs84_lon','longitude','lon')
    c_z=pick_col(cols,'station_height_masl','station_height_m','station_height','height','altitude')
    c_name=pick_col(cols,'station_name','name')
    if not all((c_id,c_lat,c_lon,c_z)):
        raise ValueError('UNRECOGNIZED_SWISS_STATION_METADATA_COLUMNS '+str(cols))
    out={}
    for row in rows:
        code=(row[c_id] or '').strip().upper()
        if not re.fullmatch('[A-Z]{3}',code):continue
        try:lat=float(row[c_lat]);lon=float(row[c_lon]);z=float(row[c_z])
        except (ValueError,TypeError):continue
        if not (45<lat<49 and 5<lon<12 and -100<z<5000):continue
        if code in out:raise ValueError('Duplicate Swiss station abbreviation '+code)
        out[code]={'station_id':code,'station':(row.get(c_name) or code).strip(),
                    'lat':lat,'lon':lon,'hoehe_m':z}
    if len(out)<50:raise ValueError('Too few qualified Swiss stations '+str(len(out)))
    return out,cols

def station_id_from_name(name):
    m=re.search(r'ogd-smn_([a-z]{3})_[tmhdy]_',name.lower())
    return m.group(1).upper() if m else None

def discover_assets(items):
    out=collections.defaultdict(list)
    for item in items:
        for key,meta in item.get('assets',{}).items():
            url=meta.get('href','')
            candidate=key+' '+url
            sid=station_id_from_name(candidate)
            if not sid:continue
            filename=urlparse(url).path.lower()
            if not re.search(r'_m_(?:historical|hist)',filename):continue
            if not filename.endswith('.csv'):continue
            if urlparse(url).hostname!=ROOT_HOST:continue
            out[sid].append(url)
    return {s:sorted(set(urls)) for s,urls in out.items()}

def inventory_probe(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    meta_url=STAC.replace('/api/stac/v1/collections/','/')+'/ogd-smn_meta_stations.csv'
    blob,digest=fetch(meta_url)
    stations,cols=parse_meta(blob)
    items=[];next_url=STAC+'/items?limit=100';seen=set();pages=[]
    for page in range(25):
        if not next_url:break
        if next_url in seen:raise RuntimeError('Cyclic STAC pagination')
        seen.add(next_url)
        raw,sha=fetch(next_url,max_bytes=18000000)
        obj=json.loads(raw)
        feats=obj.get('features',[])
        if not isinstance(feats,list):raise ValueError('Unexpected STAC item structure')
        items.extend(feats)
        pages.append({'url':next_url,'sha256':sha,'items':len(feats)})
        nxt=next((x.get('href') for x in obj.get('links',[]) if x.get('rel')=='next'),None)
        next_url=nxt
    discovered=discover_assets(items)
    diagnostic={'source':'MeteoSwiss SwissMetNet STAC','station_metadata_sha256':digest,
         'station_count':len(stations),'station_metadata_columns':list(cols),
         'stac_pages':pages,'n_stac_items':len(items),'n_station_monthly_historical_assets':len(discovered),
         'asset_sample':{k:v[:3] for k,v in list(sorted(discovered.items()))[:8]},
         'sample_stac_items':[{'id':x.get('id'),'asset_names':list(x.get('assets',{}))[:6]} for x in items[:3]],
         'policy':'Station metadata and headers only for probe, no MeteoSwiss observed temperature series published.'}
    (out/'swiss_stac_probe.json').write_text(json.dumps(diagnostic,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print('P8.1E_SWISS_STAC_PROBE',json.dumps(diagnostic),flush=True)
    if len(discovered)<20:raise RuntimeError('STAC monthly historical assets not discoverable; scientific gate')
    return stations,discovered,diagnostic

def parse_month_csv(raw,station):
    rows,cols=decode_csv(raw)
    idcol=pick_col(cols,'station','station_abbr')
    datecol=pick_col(cols,'time','date','datum')
    tempcol=pick_col(cols,'tre200m0')
    if not datecol or not tempcol:raise ValueError('MONTHLY_TEMP_SCHEMA_CHANGED '+str(cols))
    out={}
    for r in rows:
        if idcol and r[idcol].strip().upper()!=station:continue
        date=(r[datecol] or '').strip()
        ma=re.match(r'^(20\d\d)[-/.]?(0[1-9]|1[0-2])(?:\D|$)',date)
        if not ma:continue
        y=int(ma.group(1));m=int(ma.group(2))
        if y not in TIME_YEARS:continue
        rawtemp=(r[tempcol] or '').strip()
        if not rawtemp or rawtemp in ('-','-9999','NaN'):continue
        t=float(rawtemp)
        if not math.isfinite(t) or not -80<t<65:raise ValueError('Invalid Swiss monthly temperature')
        key=f'{y:04d}-{m:02d}'
        if key in out and abs(out[key]-t)>1e-6:raise ValueError('Conflicting station-month measurements')
        out[key]=t
    return out,cols

def select_stations(stations,assets,max_sites=65):
    """Frozen metadata-only stratified geography/height; no temperature-based selection."""
    eligible=[s for s in stations.values() if s['station_id'] in assets]
    # prioritize elevation and horizontal breadth, choose 3 elevation bins and 3 longitude bins
    buckets=collections.defaultdict(list)
    for s in eligible:
        z=s['hoehe_m'];b=0 if z<500 else 1 if z<1500 else 2
        lonbin=0 if s['lon']<7.5 else 1 if s['lon']<9 else 2
        buckets[(b,lonbin)].append(s)
    for arr in buckets.values():arr.sort(key=lambda s:s['station_id'])
    chosen=[]
    while len(chosen)<max_sites and any(buckets.values()):
        for k in sorted(buckets):
            if buckets[k]:chosen.append(buckets[k].pop(0))
            if len(chosen)>=max_sites:break
    return chosen

def austria_train_lapse(source_normals):
    meta,metadata_sha,_=fetch_json(BASE+'/metadata')
    ids,flag,skipped=metadata_contract(meta,source_normals['stationen'])
    vals={};checks=[]
    all_ids=sorted(ids)
    for i in range(0,len(all_ids),16):
        group=all_ids[i:i+16]
        from urllib.parse import urlencode
        url=BASE+'?'+urlencode({'parameters':FIELD+(','+flag if flag else ''),'station_ids':','.join(str(k) for k in group),
                   'start':'1991-01-01','end':'2020-12-31','output_format':'geojson'})
        data,sha,bytes_=fetch_json(url)
        decoded,diag=decode_response(data,set(group),flag)
        vals.update(decoded)
        checks.append({'sha256':sha,'bytes':bytes_,'count':len(group)})
    train=calibrate_donor_normals(ids,vals)
    if len(train)<130:raise ValueError('Insufficient Austrian historical calibration')
    monthly=[global_slope(train,m,'tmittel') for m in range(12)]
    return monthly,{'austria_training_n':len(train),'austria_metadata_sha256':metadata_sha,
                    'austria_request_digests':checks,'excluded_austrian_test_years':list(range(2011,2021)),
                    'trained_lapse_K_per_km':[1000*x for x in monthly]}

def evaluate(sites,series,lapse,buffer=0):
    pred=[]
    for target in sites:
        sid=target['station_id']
        others=sorted([(float(haversine(target['lat'],target['lon'],d['lat'],d['lon'])),d)
             for d in sites if d['station_id']!=sid and buffer<=float(haversine(target['lat'],target['lon'],d['lat'],d['lon']))<=MAX_KM],
             key=lambda pair:(pair[0],pair[1]['station_id']))
        for year in TIME_YEARS:
            for mon in range(1,13):
                ym=f'{year}-{mon:02d}';truth=series.get(sid,{}).get(ym)
                if truth is None:continue
                donor=[(d,s) for d,s in others if ym in series.get(s['station_id'],{})][:8]
                if len(donor)<8:continue
                dist=np.array([d for d,s in donor]);w=np.maximum(dist,0.25)**-2;w/=w.sum()
                tt=np.array([series[s['station_id']][ym] for d,s in donor]);dz=np.array([target['hoehe_m']-s['hoehe_m'] for d,s in donor])
                for name,rate in [('idw_raw',0.),('idw_fixed65',LAPSE),('idw_austria_regional',lapse[mon-1])]:
                    err=float(w@(tt+rate*dz)-truth)
                    pred.append({'station_id':sid,'station':target['station'],'elevation_m':target['hoehe_m'],
                       'year':year,'month':mon,'buffer_km':buffer,'method':name,'error':err,'abs_error':abs(err)})
    return pred

def aggregate(rows,keys):
    g=collections.defaultdict(list)
    for r in rows:g[tuple(r[k] for k in keys)].append(r)
    out=[]
    for k,arr in sorted(g.items()):
        e=np.array([r['error'] for r in arr]);out.append({**dict(zip(keys,k)),'n_station_months':len(arr),
                   'n_stations':len({r['station_id'] for r in arr}),
                   'MAE_C':float(np.abs(e).mean()),'RMSE_C':float(np.sqrt(np.mean(e*e))),
                   'bias_C':float(e.mean())})
    return out

def run(normals_path,out,max_sites=65):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    swiss,assets,meta=inventory_probe(out)
    chosen=select_stations(swiss,assets,max_sites)
    if len(chosen)<20:raise RuntimeError('Insufficient independent Swiss sites')
    series={};digests=[];fail=[]
    for s in chosen:
        sid=s['station_id'];merged={}
        for url in assets[sid]:
            # A decade archive outside 2011-2020 cannot add a test reading.
            years=re.search(r'(19\d\d|20\d\d)[-_](19\d\d|20\d\d)',urlparse(url).path)
            if years and (int(years.group(2))<2011 or int(years.group(1))>2020):continue
            try:
                raw,digest=fetch(url,max_bytes=15000000)
                vals,cols=parse_month_csv(raw,sid)
                for key,t in vals.items():
                    if key in merged and abs(t-merged[key])>1e-6:raise ValueError('Conflicting Swiss archive chunks')
                    merged[key]=t
                digests.append({'station':sid,'sha256':digest,'rows_in_test':len(vals),'bytes':len(raw)})
            except Exception as exc:
                fail.append({'station':sid,'error':str(exc),'url':url})
        if len(merged)>=96:series[sid]=merged
    matched=[s for s in chosen if s['station_id'] in series]
    if len(matched)<18:raise RuntimeError('Insufficient Swiss historical monthly coverage '+str(len(matched)))
    source=json.loads(Path(normals_path).read_bytes())
    lapse,cal=austria_train_lapse(source)
    rows=[]
    for radius in (0,50):rows.extend(evaluate(matched,series,lapse,radius))
    if len(rows)<2500:raise RuntimeError('Insufficient external Swiss station-month comparisons: '+str(len(rows)))
    ag=aggregate(rows,['method','buffer_km'])
    station=aggregate(rows,['method','buffer_km','station_id','station','elevation_m'])
    alt=aggregate([{**x,'altitude_band':'high' if x['elevation_m']>=1500 else 'mid' if x['elevation_m']>=500 else 'low'} for x in rows],['method','buffer_km','altitude_band'])
    save_csv(out/'external_swiss_metrics.csv',ag);save_csv(out/'external_swiss_stations.csv',station);save_csv(out/'external_swiss_altitude.csv',alt)
    report={'stage':'P8.1E','scope':'external SwissMetNet 2011–2020 temperature, Austrian-frozen seasonal regional lapse rates',
            'train_country':'Austria (GeoSphere)','target_country':'Switzerland (MeteoSwiss)',
            'time_validation':[2011,2020],'n_qualified_stations':len(matched),'n_scored_predictions':len(rows),
            'no_swiss_temperature_in_model_fit':True,
            'allow_test_year_swiss_donors':True,'not_weather_forecast':True,'not_Meteonorm_reference':True,
            'frozen_austria_calibration':cal,'stac_metadata':meta,'swiss_asset_hashes':digests,
            'swiss_qualification_failures':fail,'metrics':ag,
            'limitations':['Comparison is cross-country transfer with same-month observational donors, not 10-year forecast.',
                           'No DEM correction trained or tested here, only frozen P8.1B global lapse.',
                           'Swiss station network is also Alpine, not a globally independent climate regime.',
                           'Site selection based solely on available metadata and historical completeness, not temperature performance.',
                           'Some Swiss stations have nonhomogenized measurement histories; results are spatial skill not climate trends.']}
    (out/'external_swiss_provenance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print('P8.1E_EXTERNAL_SWISS_RESULT',json.dumps({'stations':len(matched),'predictions':len(rows),'metrics':ag}),flush=True)
    return report

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--austria-station-normals',required=True);a.add_argument('--out',required=True);
    a.add_argument('--max-sites',type=int,default=65);s=a.parse_args()
    run(s.austria_station_normals,s.out,s.max_sites)