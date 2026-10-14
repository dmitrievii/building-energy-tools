#!/usr/bin/env python3
"""IGE P8.2F: 2018/2019/2020 Swiss expanded-source donor-only reconstruction.

Original Austrian 1991-2020 station index calibration, SAME frozen annual_predict.
Donor selection uses only provider metadata and station source availability.
MeteoSwiss target weather MUST be excluded from donor weather/monthly dictionaries.
No original hourly station measurements exported (derived metrics / source SHA only).
Years 2018-2020 already inspected: EXPLORATORY, not blind validation.
"""
from __future__ import annotations
import argparse, collections, csv, hashlib, json
from pathlib import Path
from p8_2e_crossyear import ROOT,POOL,TARGETS,annual_hours,parse_swiss_year,donor_set,annual_predict
from p8_1e_swiss_external import fetch,parse_meta,haversine
from p8_2b_humidity import swiss_monthly,train_austria_humidity
from p8_2f_donor_audit import metrics,event_audit,export
from p8_2f_station_selection import (metadata_candidates, coverage,
    closest_eligible_donors, physical_donor_distance_report)

METHOD='full_multidonor_shape'
PERMITTED_YEARS=(2018,2019,2020)


def evaluate(normals,year,out,nearest_count=20):
    if year not in PERMITTED_YEARS:
        raise ValueError('Only pre-examined 2018-2020 audit years are permitted')
    dest=Path(out); dest.mkdir(parents=True,exist_ok=True)
    hours=annual_hours(year); expected=len(hours)
    raw,meta_sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    metadata,_=parse_meta(raw)
    nearest,candidates=metadata_candidates(metadata,TARGETS,POOL,nearest_count=nearest_count)
    status=[];weather={};monthly={};digests=[]
    decade='2020-2029' if year>=2020 else '2010-2019'
    for sid in candidates:
        wx={};m={};error=''
        try:
            raw,h=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_{decade}.csv',max_bytes=37000000)
            wx,_=parse_swiss_year(raw,sid,year)
            digests.append({'station':sid,'kind':'hourly','sha256':h})
            raw,h=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_m.csv',max_bytes=20000000)
            m,_=swiss_monthly(raw,sid)
            digests.append({'station':sid,'kind':'monthly','sha256':h})
            weather[sid]=wx;monthly[sid]=m
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc)[:160]
        counts=coverage(wx,m,year,expected)
        status.append({'year':year,'site':sid,'station':metadata[sid]['station'],
            'elevation_m':float(metadata[sid]['hoehe_m']),
            'in_original_pool':sid in POOL,
            'in_nearest_metadata_for':';'.join(t for t,v in nearest.items() if sid in v),
            **counts,'source_error':error})
    qualified={r['site'] for r in status if r['eligible_complete']}
    if not set(TARGETS).issubset(qualified):
        raise RuntimeError('No fully observed reference target sites '+str(set(TARGETS)-qualified))
    loge,t_slope,cal=train_austria_humidity(normals)
    selected=[];stat=[];events=[];per_donor=[];preserved_baseline=[]
    for tid in TARGETS:
        target=metadata[tid]
        # Neither donor sourcing nor eligibility reads target weather for prediction.
        safe_w={sid:wx for sid,wx in weather.items() if sid!=tid}
        safe_m={sid:m for sid,m in monthly.items() if sid!=tid}
        restricted_meta={sid:metadata[sid] for sid in POOL if sid in metadata}
        expanded_meta={sid:metadata[sid] for sid in qualified if sid in metadata}
        donors_original=donor_set(target,restricted_meta,safe_w,safe_m,year=year)
        donors_expanded=closest_eligible_donors(target,expanded_meta,qualified,tid)
        for label,donors in (('original_12_pool',donors_original),('expanded_complete_nearest',donors_expanded)):
            if any(s['station_id']==tid for d,s in donors):raise AssertionError('Target in selected donors')
            predicted,trace=annual_predict(target,donors,hours,safe_w,safe_m,
                                            loge,t_slope,year=year)
            if trace.get('target_meteorology_read_for_prediction') is not False:
                raise AssertionError('Target observation leakage in predictor')
            rows=metrics(predicted[METHOD],weather[tid],hours,year,tid,label,label=='original_12_pool')
            if rows['n_hours']!=expected:
                raise ValueError('Incomplete target scoring')
            stat.append(rows)
            ev,detail,_=event_audit(hours,donors,safe_w,safe_m,weather[tid],predicted[METHOD],year,tid)
            events.append({'variant':label,**ev});per_donor.extend([{'variant':label,**x} for x in detail])
            selected.append({'year':year,'site':tid,'variant':label,
                'donor_ids':','.join(s['station_id'] for d,s in donors),
                'physical_distances_km':','.join(f'{d:.3f}' for d,s in donors),
                'donor_heights_m':','.join(f'{s["hoehe_m"]:.1f}' for d,s in donors),
                'max_abs_height_difference_m':round(max(abs(s['hoehe_m']-target['hoehe_m']) for d,s in donors),1),
                'qualified_hours':rows['n_hours'], 'used_target_for_prediction':False,
                'donor_metadata':json.dumps(physical_donor_distance_report(target,donors))})
    # Aggregate integer event contingency directly instead of mean-of-rates.
    consolidated=[]
    for label in ('original_12_pool','expanded_complete_nearest'):
        part=[x for x in stat if x['variant']==label]
        total=sum(x['n_hours'] for x in part)
        o=sum(x['n_obs_wet'] for x in part);tp=sum(x['true_positive'] for x in part)
        fp=sum(x['false_positive'] for x in part);fn=sum(x['missed_wet'] for x in part)
        consolidated.append({'year':year,'variant':label,'n_hours':total,
           'MAE_T_C':sum(x['SAE_T'] for x in part)/total,
           'MAE_e_hPa':sum(x['SAE_e'] for x in part)/total,
           'MAE_RH_pp':sum(x['SAE_RH'] for x in part)/total,
           'bias_RH_pp':sum(x['BIAS_RH']*x['n_hours'] for x in part)/total,
           'observed_wet':o,'predicted_wet':sum(x['pred_wet'] for x in part),
           'true_positive':tp,'false_positive':fp,'missed_wet':fn,
           'observed_wet_rate_pct':100*o/total,
           'predicted_wet_rate_pct':100*(tp+fp)/total,
           'wet_recall':tp/o,'wet_precision':tp/(tp+fp),
           'wet_f1':2*tp/(2*tp+fp+fn)})
    export(dest/'source_coverage.csv',status)
    export(dest/'selected_donors.csv',selected)
    export(dest/'station_skill.csv',stat)
    export(dest/'annual_skill.csv',consolidated)
    export(dest/'wet_event_mechanisms.csv',events)
    export(dest/'wet_donor_individual_summaries.csv',per_donor)
    prov={'stage':'IGE_P8_2F_EXPANDED_DONOR_SELECTION_CROSSYEAR',
      'year':year,'station_metadata_count':len(metadata),
      'candidate_nearest_count':nearest_count,'n_candidates_fetched':len(candidates),
      'n_candidates_full_coverage':len(qualified),'n_scored_hours':expected*len(TARGETS),
      'selection':'nearest by physical distance AFTER exact full-year T/P/e/RH and 12 monthly e screening',
      'uncertainty':'Exhaustive among screened closest candidates, not all 159 stations with source availability',
      'model':'Frozen P8.2E annual_predict, no changes to T/e/RH reconstruction, lapse rate, IDW weights or monthly reconciliation',
      'original_baseline':'Original donor_set unchanged, original 12 stations included in candidate pool',
      'target_isolation':'Target values score-only, excluded from both predictor collections and rank',
      'data_source_sha256':digests,'metadata_sha256':meta_sha,
      'austria_training':cal,'no_original_hourly_obs_redistributed':True,
      'not_fresh_holdout':True,'limitations':[
       '2018-2020 target years already assessed; results exploratory not independent validation',
       'Exact complete-year eligibility conservative and can reject stations with small gaps',
       'RH wet recall alone cannot be maximized without false-positive and moisture balance penalties',
       'Alternative annual station blend is not a future-climate generator or complete EPW',
       'Changing donor set also changes monthly target humidity estimate; decomposition not isolated'],
      'summary':consolidated,'selections':selected}
    (dest/'selection_provenance.json').write_text(json.dumps(prov,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('IGE_P8_2F_CROSSYEAR_RESULT',json.dumps({'year':year,'n_candidates':len(candidates),
          'n_qualified':len(qualified),'summary':consolidated,
          'selections':selected},ensure_ascii=False),flush=True)
    return prov

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--year',type=int,required=True)
    p.add_argument('--austria-station-normals',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--nearest-metadata',type=int,default=20)
    a=p.parse_args()
    evaluate(a.austria_station_normals,a.year,a.out,a.nearest_metadata)