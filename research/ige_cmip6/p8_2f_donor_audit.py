#!/usr/bin/env python3
"""P8.2F diagnostic: original Swiss donor suitability and predeclared donor alternatives.
No target readings in prediction. No raw MeteoSwiss hourly series in outputs.
"""
from __future__ import annotations
import argparse, collections, csv, json, math
from pathlib import Path
import numpy as np
from p8_2e_crossyear import (ROOT, POOL, TARGETS, annual_hours, parse_swiss_year,
    donor_set, annual_predict, weights)
from p8_1e_swiss_external import fetch, parse_meta, haversine
from p8_2b_humidity import swiss_monthly, train_austria_humidity

METHOD='full_multidonor_shape'
ALT_PENALTY_KM_PER_KM=20.0  # predeclared, NOT fitted; sensitivity candidate

def effective_distance(distance_km,height_difference_m):
    return math.hypot(float(distance_km),ALT_PENALTY_KM_PER_KM*abs(float(height_difference_m))/1000)

def sorted_alt_donors(target, meta, donor_weather, donor_monthly,year):
    candidates=[]
    for sid, station in meta.items():
        if sid==target['station_id'] or sid not in donor_weather or sid not in donor_monthly:continue
        if len(donor_weather[sid])<8000 or any(donor_monthly[sid].get(f'{year}-{m:02d}',{}).get('e') is None for m in range(1,13)):continue
        d=haversine(target['lat'],target['lon'],station['lat'],station['lon'])
        score=effective_distance(d, target['hoehe_m']-station['hoehe_m'])
        candidates.append((float(score),station))
    return sorted(candidates,key=lambda a:(a[0],a[1]['station_id']))[:4]

def source_station_geometry(target, candidates, base_ids, alt_ids):
    items=[]
    for d,s in sorted(candidates,key=lambda z:(z[0],z[1]['station_id'])):
        dz=float(s['hoehe_m']-target['hoehe_m'])
        items.append({'target':target['station_id'],'station':s['station_id'],
            'station_name':s['station'],'target_altitude_m':float(target['hoehe_m']),
            'donor_altitude_m':float(s['hoehe_m']),'elevation_delta_m':dz,
            'distance_km':float(d),'effective_alt_distance_km':effective_distance(d,dz),
            'original_four':s['station_id'] in base_ids,
            'altitude_aware_four':s['station_id'] in alt_ids})
    return items

def event_audit(hours,donors,weather,monthly,target_obs,pred,year,site):
    # Same per-hour donor set as annual_predict: require T, P, e and monthly e.
    counts=collections.Counter(); donor_counts=collections.defaultdict(collections.Counter)
    month_counts=collections.defaultdict(collections.Counter)
    for i,t in enumerate(hours):
        target=target_obs.get(t)
        if not target or any(target.get(k) is None for k in ('T','P','e','RH')):continue
        valid=[]
        for d,s in donors:
            sid=s['station_id'];row=weather.get(sid,{}).get(t)
            if row is None or any(row.get(k) is None for k in ('T','P','e')) or monthly.get(sid,{}).get(f'{year}-{t.month:02d}',{}).get('e') is None:continue
            if row.get('RH') is None:raise ValueError('USED_DONOR_RH_MISSING '+sid)
            valid.append((d,sid,row))
        if len(valid)<2:raise ValueError('Missing original donor coverage')
        target_wet=target['RH']>=90
        missed=target_wet and float(pred['RH'][i])<90
        w=weights([a[0] for a in valid]); drh=np.array([a[2]['RH'] for a in valid])
        any_wet=bool(np.any(drh>=90));all_dry=not any_wet
        weighted=float(w@drh)
        if not target_wet: continue
        counts['wet_observed']+=1
        month_counts[t.month]['wet_observed']+=1
        if any_wet:counts['wet_with_any_donor_wet']+=1
        else:counts['wet_with_all_donors_below90']+=1
        if weighted>=90:counts['wet_with_weighted_donor_ge90']+=1
        if missed:
            counts['missed_total']+=1;month_counts[t.month]['missed_total']+=1
            counts['missed_any_wet_donor' if any_wet else 'missed_all_donors_below90']+=1
            if weighted>=90:counts['missed_weighted_donor_ge90']+=1
            for _,sid,row in valid:
                donor_counts[sid]['missed_used']+=1
                if row['RH']>=90:donor_counts[sid]['missed_rh_ge90']+=1
                if row['e']>=target['e']:donor_counts[sid]['missed_e_ge_target']+=1
        else:counts['detected_wet']+=1
    if not counts['wet_observed']:raise ValueError('No held-out RH >=90 event')
    out={'year':year,'site':site,**dict(counts)}
    for k in ('wet_observed','wet_with_any_donor_wet','wet_with_all_donors_below90','wet_with_weighted_donor_ge90',
             'missed_total','missed_any_wet_donor','missed_all_donors_below90','missed_weighted_donor_ge90','detected_wet'):
        out.setdefault(k,0)
    return out,[{'year':year,'site':site,'donor':sid,**dict(c)} for sid,c in sorted(donor_counts.items())],month_counts

def metrics(pred,ref,hours,year,site,variant,original=False):
    ix=np.array([i for i,t in enumerate(hours) if t in ref and all(ref[t].get(k) is not None for k in ('T','P','e','RH'))])
    if len(ix)<.95*len(hours):raise ValueError('Too few target observations')
    arr={k:np.asarray([ref[hours[i]][k] for i in ix]) for k in ('T','P','e','RH')}
    rows={'year':year,'site':site,'variant':variant,'n_hours':len(ix),
          'n_obs_wet':int(np.sum(arr['RH']>=90)),'baseline_same_timestamps':True}
    for k in ('T','e','RH'):
        err=np.asarray(pred[k])[ix]-arr[k]
        rows['MAE_'+k]=float(np.abs(err).mean());rows['BIAS_'+k]=float(err.mean())
        rows['SSE_'+k]=float(np.square(err).sum())
        rows['SAE_'+k]=float(np.abs(err).sum())
    rh=np.asarray(pred['RH'])[ix];mask=arr['RH']>=90
    rows['pred_wet']=int(np.count_nonzero(rh>=90))
    rows['true_positive']=int(np.count_nonzero((rh>=90)&mask))
    rows['false_positive']=int(np.count_nonzero((rh>=90)&~mask))
    rows['missed_wet']=int(np.count_nonzero((rh<90)&mask))
    rows['recall_wet']=rows['true_positive']/rows['n_obs_wet']
    rows['pred_wet_rate']=rows['pred_wet']/len(ix)
    rows['orig']=bool(original)
    return rows

def export(path,rows):
    if not rows:raise ValueError('No rows to export')
    with open(path,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),extrasaction='ignore');w.writeheader();w.writerows(rows)

def execute(year,normals,out):
    if year not in (2018,2019,2020):raise ValueError('Only pre-examined years')
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    blob,msha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    metadata,_=parse_meta(blob)
    sites={sid:metadata[sid] for sid in POOL if sid in metadata}
    weather={};monthly={};sources=[];excluded=[]
    decade='2020-2029' if year>=2020 else '2010-2019'
    for sid in sites:
        try:
            blob,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_{decade}.csv',max_bytes=37000000)
            weather[sid],_=parse_swiss_year(blob,sid,year)
            sources.append({'sid':sid,'kind':'hourly','sha256':sha})
            blob,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_m.csv',max_bytes=20000000)
            monthly[sid],_=swiss_monthly(blob,sid)
            sources.append({'sid':sid,'kind':'monthly','sha256':sha})
        except Exception as e:excluded.append({'sid':sid,'reason':type(e).__name__,'message':str(e)[:100]})
    loge,tslope,cal=train_austria_humidity(normals)
    hours=annual_hours(year)
    event_rows=[]; donor_event_rows=[];geometry=[];stats=[];sets=[]
    for sid in TARGETS:
        dw={k:v for k,v in weather.items() if k!=sid};dm={k:v for k,v in monthly.items() if k!=sid}
        orig=donor_set(sites[sid],sites,dw,dm,year=year)
        altitude=sorted_alt_donors(sites[sid],sites,dw,dm,year)
        geom_candidates=[]
        for other in sites.values():
            if other['station_id']!=sid and other['station_id'] in dw and other['station_id'] in dm:
                d=haversine(sites[sid]['lat'],sites[sid]['lon'],other['lat'],other['lon'])
                geom_candidates.append((float(d),other))
        geometry+=source_station_geometry(sites[sid],geom_candidates,
            {s['station_id'] for d,s in orig},{s['station_id'] for d,s in altitude})
        variants={'original_idw4':orig,'nearest_idw2':orig[:2], 'altitude_aware_idw4':altitude}
        for variant, donors in variants.items():
            nmin=1 if variant=='nearest_idw2' else 2
            try:
                pred,trace=annual_predict(sites[sid],donors,hours,dw,dm,loge,tslope,
                    min_hourly_donors=nmin,year=year)
                stats.append(metrics(pred[METHOD],weather[sid],hours,year,sid,variant,variant=='original_idw4'))
                sets.append({'year':year,'site':sid,'variant':variant,'donor_ids':','.join(s['station_id'] for d,s in donors),
                             'distance_or_score_km':','.join(f'{d:.2f}' for d,s in donors),
                             'hourly_donor_counts':str(trace['donor_hour_availability']),
                             'status':'SUCCESS','reason':''})
                if variant=='original_idw4':
                    e, donor_events,_=event_audit(hours,donors,dw,dm,weather[sid],pred[METHOD],year,sid)
                    event_rows.append(e);donor_event_rows+=donor_events
            except (ValueError,AssertionError) as e:
                sets.append({'year':year,'site':sid,'variant':variant,'donor_ids':','.join(s['station_id'] for d,s in donors),
                             'distance_or_score_km':','.join(f'{d:.2f}' for d,s in donors),
                             'hourly_donor_counts':'','status':'FAILED','reason':str(e)[:180]})
                if variant=='original_idw4':raise
    export(dest/'donor_metadata_and_distance.csv',geometry)
    export(dest/'donor_selection_and_coverage.csv',sets)
    export(dest/'donor_wet_event_mechanisms.csv',event_rows)
    export(dest/'donor_wet_individual_stations.csv',donor_event_rows)
    export(dest/'donor_alternative_skill.csv',stats)
    manifest={'stage':'P8.2F_DONOR_SUITABILITY_AUDIT','year':year,'n_scored_hours':sum(x['n_hours'] for x in stats if x['variant']=='original_idw4'),
              'baseline_code':'P8.2E unchanged original annual_predict','alternative_comparisons':'Same original frozen algorithm, predeclared donor-count=2 and altitude adjusted top4, no fit',
              'altitude_penalty_km_per_km':ALT_PENALTY_KM_PER_KM,
              'alternative_idw2_hourly_minimum_donors':1,
              'original_pool_only':list(POOL),'not_full_swissmetnet_search':True,
              'station_metadata_sha256':msha,'source_sha256':sources,'missing_input_stations':excluded,
              'austria_calibration':cal,'raw_hourly_observations_exported':False,
              'no_target_used_to_select_donor':True,
              'research_caveats':['All 2018-2020 years already analyzed, not a fresh external test',
                'Alternative donor selection is exploratory; do not choose winner as if independent validation',
                'Event donor RH can be <90 while target is >=90 due to target T differences',
                'Baseline/monthly mean differs when changing donors, so comparisons measure total donor-choice effect, not weighting effect alone',
                'Altitude-weighted score is a prespecified heuristic, not a calibrated or validated transfer law']}
    (dest/'donor_audit_provenance.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('IGE_DONOR_STATION_AUDIT',json.dumps({'year':year,'events':event_rows,'model_metrics':stats,'donor_sets':sets,'station_metadata':geometry},ensure_ascii=False),flush=True)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',required=True,type=int)
    p.add_argument('--austria-station-normals',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();execute(a.year,a.austria_station_normals,a.out)