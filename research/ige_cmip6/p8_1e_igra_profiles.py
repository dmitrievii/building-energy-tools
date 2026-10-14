#!/usr/bin/env python3
"""IGE P8.1E: NOAA IGRA 2.2 *same-launch measured* low-level inversion audit.
No spatially separated stations are treated as continuous vertical profiles.
Only NOAA IGRA qc-accepted measured GPH and TEMP; no interpolation of missing levels.
"""
from __future__ import annotations
import argparse, collections, csv, hashlib, io, json, math, time, zipfile
from pathlib import Path
from urllib.request import urlopen, Request

ROOT='https://www.ncei.noaa.gov/pub/data/igra'
SITES=('AUM00011035','AUM00011120','SZM00006610','GMM00010868')
START,END=2017,2020
VALID_FLAGS={' ','A','B'}

def http(url,max_size=65000000):
    issues=[]
    for k in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'IGE-P8.1E-academic-radiosonde-research','Accept':'*/*'}),timeout=150) as f:
                if f.status!=200:raise RuntimeError('HTTP '+str(f.status))
                b=f.read(max_size+1)
            if len(b)>max_size:raise ValueError('Too-large response '+url)
            return b
        except Exception as e:
            issues.append(str(e));time.sleep(k+1)
    raise RuntimeError('NOAA IGRA fetch failed '+url+' '+repr(issues))

def parse_inventory(blob):
    d={}
    for line in blob.decode('ascii','replace').splitlines():
        if len(line)<88:continue
        try:
            ident=line[0:11].strip()
            lat=float(line[12:20]);lon=float(line[21:30]);z=float(line[31:37]);
            first=int(line[72:76]);last=int(line[77:81]);n=int(line[82:88]);
        except ValueError:continue
        if ident in d:raise ValueError('Duplicate IGRA station')
        d[ident]={'id':ident,'lat':lat,'lon':lon,'elev_m':z,'name':line[41:71].strip(),
                  'first':first,'last':last,'count':n}
    return d

def header(line):
    if len(line)<36 or line[0]!='#':raise ValueError('Malformed IGRA header')
    sid=line[1:12].strip()
    year=int(line[13:17]);month=int(line[18:20]);day=int(line[21:23]);hour=int(line[24:26]);nlev=int(line[32:36])
    if not 1<=month<=12 or not 1<=day<=31 or not 0<=hour<=99 or not 0<nlev<10000:
        raise ValueError('Malformed IGRA date/hour/number of levels')
    return {'id':sid,'year':year,'month':month,'day':day,'hour':hour,'nlev':nlev}

def level(line):
    if len(line)<28:return None
    try:
        height=int(line[16:21]);temp=int(line[22:27]);zf=line[21];tf=line[27]
    except (ValueError,IndexError):return None
    if height in (-8888,-9999) or temp in (-8888,-9999):return None
    if zf not in VALID_FLAGS or tf not in VALID_FLAGS:return None
    if not -1000<=height<=35000 or not -1100<=temp<=700:return None
    return height,temp/10

def soundings(fh,site=None):
    """Streaming IGRA parser; number of level lines validated, no date leakage."""
    it=iter(fh)
    for raw in it:
        l=raw.decode('ascii','replace').rstrip('\r\n') if isinstance(raw,bytes) else raw.rstrip('\r\n')
        if not l:continue
        h=header(l)
        if site and h['id']!=site:raise ValueError('Unexpected station id: '+h['id'])
        levels=[]
        for i in range(h['nlev']):
            raw=next(it,None)
            if raw is None:raise ValueError('Truncated IGRA sounding')
            row=raw.decode('ascii','replace') if isinstance(raw,bytes) else raw
            item=level(row)
            if item is not None:levels.append(item)
        yield h,levels

def classify(levels,z0,threshold_c=0.5,limit_agl=1200):
    """Near-surface cold-layer warming **within one sounding**.
    Require >=2 distinct levels and lowest valid height within 150 m AGL.
    Requires at least one upper valid observation at >=250 m AGL but <=1200 m.
    A warm maximum at e.g. 900m AGL indicates a vertically measured layer,
    not a continuous lapse resolution between levels.
    """
    pts=sorted({(float(z),float(t)) for z,t in levels if -40<=z-z0<=limit_agl and math.isfinite(t)})
    if not pts:return None
    pts=[(z-z0,t) for z,t in pts if z-z0>=-40]
    if len(pts)<2 or pts[0][0]>150 or max(z for z,t in pts)<250:return None
    lo_z,lo_t=pts[0]
    upper=[(z,t) for z,t in pts if z>lo_z+50]
    if not upper:return None
    difference=max(t-lo_t for z,t in upper)
    peak_z=min(z for z,t in upper if abs((t-lo_t)-difference)<1e-9)
    return {'surface_agl_m':lo_z,'surface_t_c':lo_t,
            'warmest_above_surface_C':difference,
            'warmest_above_surface_agl_m':peak_z,
            'inversion':difference>=threshold_c,
            'levels_in_1200m':len(pts)}

def aggregate(rows):
    grouped=collections.defaultdict(list)
    for r in rows:
        for group in [('station',r['station']),('station_season',r['station'],r['season']),
                      ('station_nominal_hour',r['station'],r['nominal_hour']),
                      ('station_season_hour',r['station'],r['season'],r['nominal_hour'])]:
            grouped[group].append(r)
    out=[]
    for k,a in sorted(grouped.items()):
        strength=[v['inversion_strength_c'] for v in a]
        n=sum(v['inversion'] for v in a)
        out.append({'group_type':k[0],'station':k[1],'season':k[2] if len(k)>2 and 'season' in k[0] else 'all',
             'nominal_hour':k[-1] if 'hour' in k[0] else 'all','n_profiles':len(a),'n_inversions':n,
             'inversion_frequency':n/len(a),'mean_max_above_surface_C':sum(strength)/len(strength),
             'mean_detected_inversion_strength_C':sum(v['inversion_strength_c'] for v in a if v['inversion'])/n if n else None})
    return out

def season(m):return 'DJF' if m in (12,1,2) else 'MAM' if m in (3,4,5) else 'JJA' if m in (6,7,8) else 'SON'

def savecsv(p,items):
    if not items:return
    with open(p,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=items[0].keys());w.writeheader();w.writerows(items)

def run(out,site_ids=SITES):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    inv_url=ROOT+'/igra2-station-list.txt';raw=http(inv_url,1000000)
    inventory=parse_inventory(raw);provenance=[];results=[];coverage=[]
    for sid in site_ids:
        if sid not in inventory:raise RuntimeError('IGRA station missing '+sid)
        station=inventory[sid]
        if station['last']<END-1 or station['first']>START:raise RuntimeError('Station does not cover fixed pilot '+sid)
        if station['elev_m']<0:raise RuntimeError('Invalid station elevation '+sid)
        url=f'{ROOT}/data/data-por/{sid}-data.txt.zip'
        blob=http(url)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            files=[name for name in z.namelist() if name.endswith('.txt')]
            if len(files)!=1:raise ValueError('IGRA archive member mismatch '+sid)
            with z.open(files[0]) as records:
                counted=collections.Counter()
                for h,levels in soundings(records,sid):
                    if not START<=h['year']<=END:continue
                    counted['total_soundings']+=1
                    if h['hour'] not in (0,12):
                        counted['nonstandard_hour']+=1;continue
                    p=classify(levels,station['elev_m'])
                    if p is None:
                        counted['insufficient_surface_vertical_coverage']+=1;continue
                    counted['qualified']+=1
                    results.append({'station':sid,'season':season(h['month']),'nominal_hour':h['hour'],
                        'inversion':int(p['inversion']), 'inversion_strength_c':max(0.,p['warmest_above_surface_C']),
                        'height_to_peak_m':p['warmest_above_surface_agl_m'], 'n_levels':p['levels_in_1200m']})
        coverage.append({'station':sid,'country':sid[:2],'name':station['name'],**dict(counted)})
        provenance.append({'station':sid,'source':url,'source_zip_sha256':hashlib.sha256(blob).hexdigest(),
                           'compressed_bytes':len(blob),'station_metadata':station})
    ag=aggregate(results)
    savecsv(out/'igra_inversion_profiles_aggregates.csv',ag)
    savecsv(out/'igra_station_coverage.csv',coverage)
    report={'stage':'P8.1E_IGRA_VERITCAL_PROFILES','source':'NOAA IGRA 2.2 quality-controlled vertical sounding data',
         'inventory_sha256':hashlib.sha256(raw).hexdigest(),'station_archives':provenance,
         'target_period':[START,END],'threshold_inversion_C':0.5,'above_surface_max_m':1200,
         'n_measured_profiles':len(results),'by_station':coverage,
         'scope':'Measured radiosonde positive-temperature-with-height proxy in 0–1200 m AGL. GPH values required.',
         'not_station_temporal_model_validation':True,
         'limitations':['Sparse standard/significant levels do not resolve shallow 10–100m nocturnal inversions.',
           'Station launch may drift horizontally and is not a valley-floor vertical mast.',
           'Nominal UTC 00/12 may differ from exact balloon launch time; no local-night classification.',
           'No source profiles or copyright-restricted Meteonorm weather redistributed.']}
    (out/'igra_profile_provenance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    if len(results)<500 or len({x['station'] for x in results})<2:
        raise RuntimeError('Insufficient genuine colocated IGRA profiles; report not validated')
    print('P8.1E_IGRA_PROFILE_RESULT',json.dumps({'n':len(results),'coverage':coverage,'ag':ag}),flush=True)
    return report

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--out',required=True);a.add_argument('--sites',nargs='*',default=SITES)
    args=a.parse_args();run(args.out,args.sites)