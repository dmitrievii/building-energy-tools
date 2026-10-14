#!/usr/bin/env python3
"""IGE P8.1 independent 1991-2020 monthly station-normal spatial holdouts.

Public reference: Tauernwetter Forschung, processed from GeoSphere Austria klima-v2-1m
https://tauernwetter.at/klimamittel/klimamittel_oesterreich.json
https://doi.org/10.5281/zenodo.21281130 (CC BY 4.0).

The target station's meteorological values are NEVER used for prediction.
All hyperparameters below are fixed a priori. No Meteonorm/EPW inputs enter predictions.
This is station-space climatological leave-one-out, NOT holdout by year.
"""
from __future__ import annotations
import argparse, csv, json, math, random, hashlib, statistics
from pathlib import Path
from collections import defaultdict

FIELDS={'tmittel':'C','tmax':'C','tmin':'C','niederschlag_mm':'mm_month', 'luftfeuchte':'percent', 'wind_ms':'m_s'}
TEMP={'tmittel','tmax','tmin'}
METHODS=('nearest_raw','idw_raw','nearest_lapse','idw_lapse')
REFERENCE_PERIOD='1991–2020'
K=8
EXPONENT=2.0
LAPSE_K_PER_M=-0.0065
MAX_SEARCH_KM=350.0
EXCLUSION_KM=(0.0,10.0,25.0,50.0)
FIXED_SEED=20261014
DAYS=(31,28,31,30,31,30,31,31,30,31,30,31)


def haversine(a,b):
    lat1,lon1=map(math.radians,(a['lat'],a['lon']))
    lat2,lon2=map(math.radians,(b['lat'],b['lon']))
    dlat=lat2-lat1;dlon=lon2-lon1
    q=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371.0088*2*math.asin(min(1.,math.sqrt(q)))

def valid(st,field):
    v=st.get(field)
    return st.get('periode')==REFERENCE_PERIOD and isinstance(v,list) and len(v)==12 and all(isinstance(x,(float,int)) and math.isfinite(x) and x!=-999 for x in v)

def predict(target,donors,field,month,method,k=K):
    ranked=sorted(((haversine(target,d),d) for d in donors if d['station_id']!=target['station_id'] and valid(d,field)),key=lambda x:(x[0],x[1]['station_id']))
    near=ranked[:k]
    if not near:return None
    if method.startswith('nearest'):near=near[:1]
    if method.endswith('lapse') and field not in TEMP:
        raise ValueError('Lapse correction cannot be applied to non-temperature variable')
    if method.startswith('nearest'):
        w=[1.]
    else:
        # EPS stabilizes exact collocations; target removed by ID, and spatial gap enforced upstream.
        w=[(max(d,0.25)**(-EXPONENT)) for d,_ in near]
        z=sum(w);w=[x/z for x in w]
    y=[]
    for _,s in near:
        v=float(s[field][month])
        if method.endswith('lapse'):
            v+=LAPSE_K_PER_M*(target['hoehe_m']-s['hoehe_m'])
        y.append(v)
    return {'estimate':sum(a*b for a,b in zip(w,y)),
            'nearest_donor_km':near[0][0], 'n_donors':len(near),
            'effective_donors':1/sum(ww*ww for ww in w),
            'max_donor_km':near[-1][0],
            'max_abs_elev_diff_m':max(abs(target['hoehe_m']-s['hoehe_m']) for _,s in near),
            'donor_ids':';'.join(str(s['station_id']) for _,s in near)}


def compute(stations,radii=EXCLUSION_KM,fields=FIELDS.keys()):
    out=[]
    for t in stations:
        if t.get('periode')!=REFERENCE_PERIOD:continue
        # One geodesic distance calculation per station pair; no recompute per variable/month.
        distances=sorted(((haversine(t,s),s) for s in stations
                          if s['station_id']!=t['station_id'] and s.get('periode')==REFERENCE_PERIOD),
                         key=lambda x:(x[0],x[1]['station_id']))
        for radius in radii:
            candidates=[(dist,s) for dist,s in distances if radius <= dist <= MAX_SEARCH_KM]
            for field in fields:
                if not valid(t,field):continue
                ranked=[(dist,s) for dist,s in candidates if valid(s,field)]
                near=ranked[:K]
                if not near:continue
                wd=[max(dist,0.25)**(-EXPONENT) for dist,_ in near]
                wsum=sum(wd);weights=[w/wsum for w in wd]
                for m in range(12):
                    for method in METHODS:
                        if field not in TEMP and method.endswith('lapse'):continue
                        used=near[:1] if method.startswith('nearest') else near
                        w=[1.] if method.startswith('nearest') else weights
                        vals=[float(s[field][m])+(LAPSE_K_PER_M*(t['hoehe_m']-s['hoehe_m'])
                              if method.endswith('lapse') else 0.) for _,s in used]
                        estimate=sum(a*b for a,b in zip(w,vals))
                        obs=float(t[field][m])
                        out.append(dict(station=t['station'],station_id=t['station_id'],lat=t['lat'],lon=t['lon'],elev_m=t['hoehe_m'],period=t['periode'],radius_excluded_km=radius,
                            field=field,units=FIELDS[field],month=m+1,method=method,observed=obs,predicted=estimate,error=estimate-obs,abs_error=abs(estimate-obs),
                            nearest_donor_km=near[0][0],n_donors=len(used),effective_donors=1/sum(ww*ww for ww in w),
                            max_donor_km=used[-1][0],max_abs_elev_diff_m=max(abs(t['hoehe_m']-s['hoehe_m']) for _,s in used),
                            donor_ids=';'.join(str(s['station_id']) for _,s in used)))
    return out

def aggregates(rows,group_keys):
    groups=defaultdict(list)
    for r in rows:groups[tuple(r[k] for k in group_keys)].append(r)
    out=[]
    for key,items in sorted(groups.items()):
        es=[r['error'] for r in items]
        ids={r['station_id'] for r in items}
        out.append(dict(zip(group_keys,key),n_hours=0,n_station_months=len(items),n_unique_stations=len(ids),
          mae=sum(abs(e) for e in es)/len(es),rmse=math.sqrt(sum(e*e for e in es)/len(es)),
          bias=sum(es)/len(es),median_abs_error=statistics.median(map(abs,es)),
          p90_abs_error=sorted(map(abs,es))[min(len(es)-1,math.ceil(0.9*len(es))-1)],
          max_abs_error=max(map(abs,es)),max_donor_distance_km=max(r['max_donor_km'] for r in items),
          median_nearest_donor_km=statistics.median(r['nearest_donor_km'] for r in items)))
    return out

def station_aggregates(rows):
    arr=[]
    for r in aggregates(rows,['station','station_id','elev_m','field','method','radius_excluded_km']):
        arr.append(r)
    return arr

def confidence_by_station(rows,field='tmittel',method='idw_lapse',radius=0.0,n=1000):
    sel=[r for r in rows if r['field']==field and r['method']==method and r['radius_excluded_km']==radius]
    groups=defaultdict(list)
    for r in sel:groups[r['station_id']].append(r['error'])
    all_ids=sorted(groups)
    rng=random.Random(FIXED_SEED)
    draws=[]
    if not all_ids:return None
    for _ in range(n):
        sample=[rng.choice(all_ids) for _ in all_ids]
        vals=[e for s in sample for e in groups[s]]
        draws.append(sum(map(abs,vals))/len(vals))
    draws.sort()
    return {'field':field,'method':method,'radius_km':radius,'n_bootstrap':n,'station_resample_seed':FIXED_SEED,
        'ci2p5_mae':draws[int(0.025*(n-1))],'ci97p5_mae':draws[int(.975*(n-1))],'ci_method':'percentile station bootstrap (observed station-months clustered by station)'}

def save_csv(path,rows):
    if not rows:return
    with open(path,'w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)

def site_report(rows,names):
    sub=[r for r in rows if any(s in r['station'].casefold() for s in names) and r['radius_excluded_km']==0 and r['field']=='tmittel' and r['method'] in ('nearest_raw','idw_raw','nearest_lapse','idw_lapse')]
    return station_aggregates(sub)

def load(path):
    blob=Path(path).read_bytes();data=json.loads(blob)
    stations=data['stationen'];ids=[v['station_id'] for v in stations]
    assert len(stations)==258 and len(set(ids))==len(ids)
    return stations,hashlib.sha256(blob).hexdigest()

def run(src, dest,limit=None):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    stations,sha=load(src)
    selected=stations if limit is None else stations[:limit]
    rows=compute(selected)
    annual=aggregates(rows,['radius_excluded_km','field','method'])
    monthly=aggregates(rows,['radius_excluded_km','field','method','month'])
    altitude=[]
    for r in rows:
        if r['field']=='tmittel':
            cat='<500m' if r['elev_m']<500 else ('500-1500m' if r['elev_m']<1500 else '>=1500m')
            altitude.append({**r,'altitude_group':cat})
    altagg=aggregates(altitude,['radius_excluded_km','altitude_group','method'])
    targets=['graz universität','wien hohe warte','innsbruck flughafen','innsbruck universität','sonnblick']
    sites=site_report(rows,targets)
    for fn,arr in [('holdout_station_months.csv',rows),('aggregate_metrics.csv',annual),('monthly_skill.csv',monthly),('altitude_stratified.csv',altagg),('target_station_metrics.csv',sites)]:save_csv(dest/fn,arr)
    conf=[confidence_by_station(rows,method=m,radius=rad) for rad in EXCLUSION_KM for m in ('nearest_raw','idw_raw','nearest_lapse','idw_lapse')]
    summary={'stage':'P8.1','validation':'LEAVE_ONE_STATION_OUT_1991_2020_MONTHLY_NORMALS','station_source':'Tauernwetter Forschung; source GeoSphere Austria klima-v2-1m; CC BY 4.0','source_url':'https://tauernwetter.at/klimamittel/klimamittel_oesterreich.json',
     'doi':'https://doi.org/10.5281/zenodo.21281130','source_text_reconstructed_sha256':sha,'source_bytes_not_claimed_to_match_upstream_original':True,
     'n_source_stations':len(stations),'n_consistent_period_stations':sum(s['periode']==REFERENCE_PERIOD for s in stations),
     'n_short_period_excluded':sum(s['periode']!=REFERENCE_PERIOD for s in stations),'n_station_month_predictions':len(rows),
     'exclude_target_station_for_every_prediction':True,'predefined_lapse_rate_K_per_km':LAPSE_K_PER_M*1000,
     'idw_neighbors':K,'idw_exponent':EXPONENT,'spatial_exclusion_radii_km':EXCLUSION_KM,
     'qualification':{'period_holdout':'NOT_PERFORMED','independent_ground_station_monthly_normal_LOOCV':'PERFORMED','target_Tripoli_Greece':'BLOCKED_NON_AUSTRIAN_SOURCE','historic_yearly_reconstruction':'NOT_PERFORMED','future_SSP':'OUT_OF_SCOPE','Meteonorm_used_for_train':'NO'},
     'confidence_intervals':conf,'primary_aggregate_skill':[x for x in annual if x['field']=='tmittel'],
     'key_target_sites':[x for x in sites if x['method'] in ('idw_lapse','idw_raw')],
     'limits':['Monthly mean station normals only; no date-resolved historical validation','Climate normal source 1991-2020, Meteonorm Contemporary may have different reference period','8 nearest donors selected without spatial barrier/orographic shadow model','Fixed lapse is a global hypothesis not monthly local calibration','No physical solar/GHI spatial reconstruction proven','Sonde temperature / UHI at short separations may be strongly local','Tripoli Peloponnese is outside the Austrian station inventory','Bootstrap 95% interval is resampling over stations, not a probability of future climate']}
    (dest/'science_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('SOURCE',len(stations),'CONSISTENT',summary['n_consistent_period_stations'],'PREDICTIONS',len(rows))
    for a in annual:
        if a['field']=='tmittel':print(a['radius_excluded_km'],a['method'],'N=',a['n_unique_stations'],'MAE=',round(a['mae'],4),'RMSE=',round(a['rmse'],4),'BIAS=',round(a['bias'],4))
    print('TARGETS',[(s['station'],s['method'],round(s['mae'],3)) for s in sites if s['method']=='idw_lapse'])
    return summary

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('station_normals_json');a.add_argument('--out',default='p8_1_results');a.add_argument('--limit',type=int)
    opts=a.parse_args();run(opts.station_normals_json,opts.out,opts.limit)