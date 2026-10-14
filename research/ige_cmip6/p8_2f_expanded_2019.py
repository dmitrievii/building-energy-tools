#!/usr/bin/env python3
"""2019 exploratory SwissMetNet expansion: original 12 donors vs closest 12 metadata candidates per target.
Source station observations never exported. Previously evaluated year: NOT independent confirmation.
"""
import argparse,csv,json,math,collections
from pathlib import Path
import numpy as np
from p8_2e_crossyear import ROOT,POOL,TARGETS,annual_hours,parse_swiss_year,donor_set,annual_predict
from p8_1e_swiss_external import fetch,parse_meta,haversine
from p8_2b_humidity import swiss_monthly,train_austria_humidity
from p8_2f_donor_audit import metrics,event_audit,source_station_geometry,export
YEAR=2019

def strict_source_eligible(n_hour_rows,n_hour_complete_tperh,n_month_e,expected=8760):
    return n_hour_rows==expected and n_hour_complete_tperh==expected and n_month_e==12

def prioritized_candidates(metadata,targets=TARGETS,original_pool=POOL,limit=12):
    per={}
    for sid in targets:
        t=metadata[sid]; nearest=sorted((
            (float(haversine(t['lat'],t['lon'],s['lat'],s['lon'])),s['station_id'])
            for s in metadata.values() if s['station_id']!=sid),key=lambda x:(x[0],x[1]))
        per[sid]=[x[1] for x in nearest[:limit]]
    chosen=sorted(set(original_pool).union(*[set(v) for v in per.values()]))
    return per,chosen

def run(normals,out):
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    raw,msha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    metadata,_=parse_meta(raw)
    nearest,candidates=prioritized_candidates(metadata)
    weather={};monthly={};status=[];digests=[]
    for sid in candidates:
        if sid not in metadata:continue
        h='';valid=0;complete=0;monthcount=0;reason=''
        try:
            raw,h=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_2010-2019.csv',max_bytes=37000000)
            weather[sid],qc=parse_swiss_year(raw,sid,YEAR)
            valid=len(weather[sid]);complete=sum(all(r.get(k) is not None for k in ('T','P','e','RH')) for r in weather[sid].values())
            digests.append({'station':sid,'field':'hourly','sha256':h})
            raw,msha2=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_m.csv',max_bytes=20000000)
            monthly[sid],qc=swiss_monthly(raw,sid)
            monthcount=sum(monthly[sid].get(f'2019-{i:02d}',{}).get('e') is not None for i in range(1,13))
            digests.append({'station':sid,'field':'monthly','sha256':msha2})
        except Exception as e:
            reason=type(e).__name__+':'+str(e)[:130]
        eligible=valid>=8000 and monthcount==12
        status.append({'sid':sid,'name':metadata[sid]['station'],'elevation_m':metadata[sid]['hoehe_m'],
           'n_hour_rows':valid,'n_hour_complete_TPeRH':complete,'n_monthly_e_2019':monthcount,
           'eligible_original_selection_rule':eligible,'source_error':reason,
           'in_initial_pool':sid in POOL,
           'in_nearest_12_of_targets':','.join(t for t,v in nearest.items() if sid in v)})
    # Strict completeness is essential: MeteoSwiss may expose 8760 timestamp rows with
    # entirely missing T/e/P/RH. Never treat row count as observed variable coverage.
    strict_valid={r['sid'] for r in status if strict_source_eligible(
        r['n_hour_rows'],r['n_hour_complete_TPeRH'],r['n_monthly_e_2019'])}
    for r in status:r['eligible_strict_full_2019']=r['sid'] in strict_valid
    train_e,train_t,cal=train_austria_humidity(normals)
    hours=annual_hours(YEAR)
    subsets=[];scores=[];events=[];geometry=[]
    for target_id in TARGETS:
        if target_id not in weather:raise RuntimeError('Target station unavailable '+target_id)
        t=metadata[target_id]
        original_meta={sid:metadata[sid] for sid in POOL if sid in metadata}
        expanded_meta={sid:metadata[sid] for sid in strict_valid if sid in metadata}
        safe_weather={sid:wx for sid,wx in weather.items() if sid!=target_id}
        safe_monthly={sid:wx for sid,wx in monthly.items() if sid!=target_id}
        selections={}
        for label,space in [('restricted_12_pool',original_meta),('expanded_nearest_12',expanded_meta)]:
            donor=donor_set(t,space,safe_weather,safe_monthly,year=YEAR)
            selections[label]=donor
            rec={'year':YEAR,'site':target_id,'variant':label,
                 'donor_ids':','.join(s['station_id'] for _,s in donor),
                 'distances_km':','.join(f'{d:.1f}' for d,s in donor)}
            try:
                pred,trace=annual_predict(t,donor,hours,safe_weather,safe_monthly,train_e,train_t,year=YEAR)
                scores.append(metrics(pred['full_multidonor_shape'],weather[target_id],hours,YEAR,target_id,label,label=='restricted_12_pool'))
                e,details,_=event_audit(hours,donor,safe_weather,safe_monthly,weather[target_id],pred['full_multidonor_shape'],YEAR,target_id)
                events.append({'variant':label,**e})
                rec.update(status='SUCCESS',reason='',n_hours=len(hours))
            except Exception as err:
                rec.update(status='FAILED',reason=type(err).__name__+':'+str(err)[:130],n_hours=0)
                if label=='restricted_12_pool':raise
            subsets.append(rec)
    export(dest/'expanded_2019_source_availability.csv',status)
    export(dest/'expanded_2019_selected_donors.csv',subsets)
    export(dest/'expanded_2019_model_skill.csv',scores)
    export(dest/'expanded_2019_wet_event_mechanisms.csv',events)
    source={'stage':'P8.2F_NEARBY_EXPANDED_SWISS_DONOR_2019_PILOT','year':YEAR,
        'source_metadata_sha256':msha,'source_sha256':digests,'calibration':cal,
        'candidates_discovered':len(candidates),'n_fully_qualified_candidates':len(strict_valid),
       'eligibility':'EXACT_8760_COMPLETE_T_P_e_RH plus 12 monthly e; no row-count-only candidate admission',
       'station_meta_count':len(metadata),'nearest_candidates':nearest,
        'raw_hourly_obs_exported':False,'all_site_observations_excluded_from_predictors':True,
        'explicit_limit':'Expanded candidate ranking checks station source availability; 2019 examined before, no untouched confirmation',
        'failure_policy':'If original baseline or data parsing fails, report failure; expanded donor failures not treated as zero error'}
    (dest/'expanded_2019_provenance.json').write_text(json.dumps(source,ensure_ascii=False,indent=2)+'\n')
    print('IGE_P8_2F_EXPANDED_SOURCE',json.dumps({'stations':status,'sets':subsets,'scores':scores,'events':events},ensure_ascii=False),flush=True)
    return source
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--austria-station-normals',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.austria_station_normals,a.out)