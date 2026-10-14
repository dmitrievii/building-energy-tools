#!/usr/bin/env python3
"""P8.3C: predeclared 2023 six-site holdout for frozen vector-first/unit-fallback wind.

No calibration/tuning against any target. Predictions use contemporaneous SwissMetNet
wind observations from other sites only; not future weather or independent EPW.
Publish only station/season/speed/condition aggregates, source digests, no raw hours.
"""
from __future__ import annotations
import argparse, collections, csv, datetime as dt, json, math
from pathlib import Path
import numpy as np

from p8_3a_wind_spatial import (
    CALM_MPS, parse_wind_year, wind_coverage, usable_wind, interpolate,
    circular_error_deg,
)
from p8_3b_wind_direction_qc import (
    UNIT_RESULTANT_THRESHOLD, csv_source_qc_profile, circular_unit_prediction,
)

YEAR = 2023
# Frozen before viewing ANY 2023 target wind results. They were donor sites in
# earlier years, so "previously unscored targets", not globally unseen stations.
TARGETS = ('DAV','GVE','LUG','SIO','SMA','WYN')
NEAREST_METADATA = 20
N_DONORS = 4
MIN_DONOR_USABILITY = .90       # inherited from P8.3A
MIN_TARGET_COVERAGE = .80      # inherited from P8.3A
SPEED_BINS = (('0.5-<2', .5, 2.),('2-<5',2.,5.),('>=5',5.,float('inf')))
SEASONS = {12:'DJF',1:'DJF',2:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'}
METHODS = ('nearest','vector','unit','hybrid')


def hybrid_direction(vector, unit):
    """Frozen P8.3C: use unchanged P8.3A vector if defined, else frozen unit R>=.20.

    Never use target temperature, wind direction, wind speed, year, region,
    observed azimuth, or score as switch criteria. No synthetic direction on calm.
    """
    if vector is not None:
        return vector,'vector'
    if unit is not None:
        return unit,'unit_fallback'
    return None,'unresolved'


def bin_speed(v):
    if v < CALM_MPS:return 'calm'
    for label,lower,upper in SPEED_BINS:
        if lower<=v<upper:return label
    raise ValueError('speed bin out of bounds')


def sector16(angle):
    if angle is None:return None
    return int(math.floor(((angle+11.25)%360)/22.5))


def build_scored_hours(target,year,hours,donors,donor_weather,target_weather):
    if target in donor_weather or any(station['station_id']==target for _,station in donors):
        raise AssertionError('TARGET_WIND_LEAKAGE')
    scored=[];target_usable=0;source_nonc=0
    for hour in hours:
        reference=target_weather.get(hour)
        if not usable_wind(reference):continue
        target_usable+=1
        if reference['speed']>=CALM_MPS and reference['direction'] is not None:source_nonc+=1
        original=interpolate(donors,donor_weather,hour)
        if original is None:continue
        unit=circular_unit_prediction(donors,donor_weather,hour,threshold=UNIT_RESULTANT_THRESHOLD)
        hdir,reason=hybrid_direction(original['vector_direction'],unit['unit_direction'])
        if original['vector_direction'] is not None and hdir != original['vector_direction']:
            raise AssertionError('FROZEN_VECTOR_NOT_RETAINED')
        if reason=='unit_fallback' and not (original['vector_direction'] is None and unit['unit_direction'] is not None):
            raise AssertionError('UNAUTHORIZED_FALLBACK')
        refdir = reference['direction'] if reference['speed']>=CALM_MPS else None
        pred={'nearest':original['nearest_direction'],'vector':original['vector_direction'],
              'unit':unit['unit_direction'],'hybrid':hdir}
        row={'time':hour,'site':target,'year':year,'obs_speed':reference['speed'],
             'obs_direction':refdir,'obs_sector':sector16(refdir),
             'speed_bin':bin_speed(reference['speed']), 'season':SEASONS[hour.month],
             'fallback_reason':reason,'unit_resultant':unit['unit_resultant'],
             'n_donors':original['n_used'],'vector_ratio':original['resultant_ratio'],
             'scalar_speed':original['scalar_speed']}
        row.update({k+'_direction':v for k,v in pred.items()})
        scored.append(row)
    if target_usable<math.ceil(MIN_TARGET_COVERAGE*len(hours)):
        raise ValueError('INSUFFICIENT_TARGET_REFERENCE_COVERAGE '+target)
    if len(scored)<math.ceil(MIN_TARGET_COVERAGE*len(hours)):
        raise ValueError('INSUFFICIENT_SHARED_PREDICTION_COVERAGE '+target)
    return scored,{'target_reference_usable':target_usable,'target_nonc_reference':source_nonc,
                   'qualified_scored_hours':len(scored),'n_target_hours':len(hours)}


def summarize(scored,group_type,group):
    """Fixed-denominator coverage; separately report errors on added fallback hours.

    Direction MAE conditional on emitted azimuth is never compared across methods
    as though their covered-hour populations were identical.
    """
    if not scored:raise ValueError('EMPTY_SCORE_GROUP')
    noncalm=[r for r in scored if r['obs_direction'] is not None]
    matched_all=[r for r in noncalm if all(r[m+'_direction'] is not None for m in METHODS)]
    base=[r for r in noncalm if r['vector_direction'] is not None]
    recovered=[r for r in noncalm if r['fallback_reason']=='unit_fallback']
    missing=[r for r in noncalm if r['hybrid_direction'] is None]
    n=len(noncalm)
    out={'group_type':group_type,'group':group,'n_scored_hours':len(scored),
         'n_observed_noncalm':n,'n_matched_all_four':len(matched_all),
         'n_vector_primary':len(base),'n_hybrid_newly_recovered':len(recovered),
         'n_hybrid_unresolved':len(missing),'n_fallback_with_nearest':sum(r['nearest_direction'] is not None for r in recovered),
         'scalar_speed_MAE_mps':sum(abs(r['scalar_speed']-r['obs_speed']) for r in scored)/len(scored),
         'scalar_speed_bias_mps':sum(r['scalar_speed']-r['obs_speed'] for r in scored)/len(scored)}
    for method in METHODS:
        good=[r for r in noncalm if r[method+'_direction'] is not None]
        out[method+'_resolved']=len(good)
        out[method+'_coverage_pct']=100*len(good)/n if n else None
        out[method+'_emitted_MAE_deg']=(sum(circular_error_deg(r[method+'_direction'],r['obs_direction']) for r in good)/len(good)) if good else None
        out[method+'_matched4_MAE_deg']=(sum(circular_error_deg(r[method+'_direction'],r['obs_direction']) for r in matched_all)/len(matched_all)) if matched_all else None
        out[method+'_fixeddenom_abs90_mean_deg']=(sum(circular_error_deg(r[method+'_direction'],r['obs_direction']) if r[method+'_direction'] is not None else 90 for r in noncalm)/n) if n else None
        out[method+'_fixeddenom_abs180_mean_deg']=(sum(circular_error_deg(r[method+'_direction'],r['obs_direction']) if r[method+'_direction'] is not None else 180 for r in noncalm)/n) if n else None
    if recovered:
        errors=[circular_error_deg(r['hybrid_direction'],r['obs_direction']) for r in recovered]
        out['recovered_MAE_deg']=sum(errors)/len(errors)
        out['recovered_within45_pct']=100*sum(e<=45 for e in errors)/len(errors)
        out['recovered_within90_pct']=100*sum(e<=90 for e in errors)/len(errors)
        paired_nearest=[r for r in recovered if r['nearest_direction'] is not None]
        out['recovered_vs_nearest_n']=len(paired_nearest)
        out['recovered_vs_nearest_hybrid_MAE_deg']=sum(circular_error_deg(r['hybrid_direction'],r['obs_direction']) for r in paired_nearest)/len(paired_nearest) if paired_nearest else None
        out['recovered_vs_nearest_nearest_MAE_deg']=sum(circular_error_deg(r['nearest_direction'],r['obs_direction']) for r in paired_nearest)/len(paired_nearest) if paired_nearest else None
    else:
        for field in ('recovered_MAE_deg','recovered_within45_pct','recovered_within90_pct',
                      'recovered_vs_nearest_hybrid_MAE_deg','recovered_vs_nearest_nearest_MAE_deg'):
            out[field]=None
        out['recovered_vs_nearest_n']=0
    # Sufficient statistics for pooled weighting without mistakenly averaging site MAEs.
    for method in METHODS:
        out[method+'_sum_emitted_abs_error_deg']=sum(circular_error_deg(r[method+'_direction'],r['obs_direction']) for r in noncalm if r[method+'_direction'] is not None)
    out['sum_recovered_abs_error_deg']=sum(circular_error_deg(r['hybrid_direction'],r['obs_direction']) for r in recovered)
    out['sum_scalar_abs_speed_error_mps']=sum(abs(r['scalar_speed']-r['obs_speed']) for r in scored)
    return out


def interval_failure_spells(scored):
    """Observed-noncalm periods with unresolved hybrid; gaps break spells."""
    episodes=[];n=0;prev=None
    for row in sorted(scored,key=lambda r:r['time']):
        bad=row['obs_direction'] is not None and row['hybrid_direction'] is None
        contiguous=prev is not None and row['time']-prev==dt.timedelta(hours=1)
        if n and not contiguous:
            episodes.append(n);n=0
        if bad:
            n+=1
        elif n:
            episodes.append(n);n=0
        prev=row['time']
    if n:episodes.append(n)
    return {'hybrid_unresolved_spells':len(episodes),'unresolved_max_consecutive_hours':max(episodes,default=0),
            'unresolved_spells_ge3h':sum(n>=3 for n in episodes),'unresolved_spells_ge6h':sum(n>=6 for n in episodes)}


def export_csv(path,rows):
    if not rows:raise ValueError('NO_EXPORT_ROWS')
    with Path(path).open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def run(year,out):
    if year!=YEAR:raise ValueError('P8.3C YEAR_LOCK: 2023 only')
    from p8_2e_crossyear import ROOT, POOL, annual_hours
    from p8_1e_swiss_external import fetch, parse_meta, haversine
    from p8_2f_station_selection import metadata_candidates
    hours=annual_hours(year);dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    raw,meta_sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    metadata,_=parse_meta(raw)
    if not set(TARGETS).issubset(metadata):raise ValueError('MISSING_PREGISTERED_TARGET_METADATA '+str(set(TARGETS)-set(metadata)))
    nearest,candidates=metadata_candidates(metadata,TARGETS,POOL,nearest_count=NEAREST_METADATA)
    obs={};coverage=[];sources=[];source_profiles=[]
    for sid in candidates:
        try:
            raw,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_2020-2029.csv',max_bytes=37000000)
            profile=csv_source_qc_profile(raw,sid,year)
            weather=parse_wind_year(raw,sid,year)
            c=wind_coverage(weather,hours)
            if c['eligible'] or sid in TARGETS:obs[sid]=weather
            sources.append({'station':sid,'sha256':sha,'success':True})
            source_profiles.append(profile)
        except Exception as ex:
            c={'recorded_rows':0,'speed_hours':0,'usable_wind_hours':0,
               'noncalm_speed_hours':0,'noncalm_direction_hours':0,'eligible':False}
            sources.append({'station':sid,'success':False,'error':type(ex).__name__+': '+str(ex)[:100]})
            source_profiles.append({'site':sid,'year':year,'hourly_wind_schema_present':False,
                'speed_field_present':False,'direction_field_present':False,
                'individual_quality_flag_columns':'','individual_qc_available':False,
                'individual_qc_codes_verified':False,'qc_status':'SOURCE_UNAVAILABLE',
                'historical_provider_review':'SOURCE_UNAVAILABLE'})
        coverage.append({'station':sid,'year':year,**c})
    eligible={x['station'] for x in coverage if x['eligible']}
    selected=[];summary=[];stratified=[];sectors=[];spell_summaries=[];qualified=[]
    for tid in TARGETS:
        if tid not in obs:raise RuntimeError('NO_TARGET_WEATHER '+tid)
        donors=sorted(((float(haversine(metadata[tid]['lat'],metadata[tid]['lon'],metadata[sid]['lat'],metadata[sid]['lon'])),metadata[sid])
                       for sid in eligible if sid!=tid),key=lambda x:(x[0],x[1]['station_id']))[:N_DONORS]
        if len(donors)!=N_DONORS:raise RuntimeError('INSUFFICIENT_DONORS '+tid)
        donor_weather={sid:v for sid,v in obs.items() if sid!=tid}
        rows,counts=build_scored_hours(tid,year,hours,donors,donor_weather,obs[tid])
        kval=summarize(rows,'site',tid)
        summary.append(kval);qualified.append({'site':tid,**counts})
        spell_summaries.append({'site':tid,'year':year,**interval_failure_spells(rows)})
        selected.append({'site':tid,'year':year,'donors':';'.join(s['station_id'] for _,s in donors),
                         'distances_km':';'.join(f'{d:.3f}' for d,_ in donors),
                         'donor_heights_m':';'.join(f'{s["hoehe_m"]:.1f}' for _,s in donors),
                         'no_target_data_in_predictors':True})
        for dimension,values in (
            ('season',('DJF','MAM','JJA','SON')),
            ('observed_speed_bin',('calm','0.5-<2','2-<5','>=5')),
            ('vector_agreement',('low_0-0.3','medium_0.3-0.6','high_0.6-1')),
        ):
            for value in values:
                if dimension=='season':part=[r for r in rows if r['season']==value]
                elif dimension=='observed_speed_bin':part=[r for r in rows if r['speed_bin']==value]
                else:
                    part=[r for r in rows if (value=='low_0-0.3' and r['vector_ratio']<.3) or
                          (value=='medium_0.3-0.6' and .3<=r['vector_ratio']<.6) or
                          (value=='high_0.6-1' and r['vector_ratio']>=.6)]
                if part:stratified.append({'site':tid,'dimension':dimension,**summarize(part,dimension,value)})
        good=[r for r in rows if r['obs_direction'] is not None]
        for method in ('observed',)+METHODS:
            angles=[r['obs_direction' if method=='observed' else method+'_direction'] for r in good]
            for sector in range(16):sectors.append({'site':tid,'year':year,'method':method,'sector_22p5_index':sector,
                'sector_start_deg':(sector*22.5-11.25)%360,
                'count':sum(sector16(a)==sector for a in angles if a is not None),
                'n_observed_noncalm':len(good),
                'n_resolved':sum(a is not None for a in angles)})
    if len(summary)!=len(TARGETS):raise AssertionError('INCOMPLETE_TARGET_EVALUATION')
    export_csv(dest/'p8_3c_station_skill.csv',summary)
    export_csv(dest/'p8_3c_stratified_skill.csv',stratified)
    export_csv(dest/'p8_3c_wind_rose_sectors.csv',sectors)
    export_csv(dest/'p8_3c_unresolved_spells.csv',spell_summaries)
    export_csv(dest/'p8_3c_selected_donors.csv',selected)
    export_csv(dest/'p8_3c_source_coverage.csv',coverage)
    export_csv(dest/'p8_3c_source_qc_visibility.csv',source_profiles)
    record={'stage':'IGE_P8_3C_INDEPENDENT_TARGETS_NEW_YEAR_WIND_HYBRID','year':year,'targets':TARGETS,
            'n_scored_hours':sum(r['n_scored_hours'] for r in summary),
            'method':'FROZEN vector-first / unit-circle IDW R>=0.20 fallback when vector undefined; 4 donors',
            'method_threshold_tuned_on_2023':False,'target_weather_in_predictor':False,
            'source':'Original contemporary SwissMetNet 2023 hourly station wind; RETROSPECTIVE ONLY',
            'qc_flag_certified':False,'historical_review_is_not_per_record_qc_pass':True,
            'n_metadata_stations':len(metadata),'n_candidate_stations':len(candidates),
            'n_eligible_wind_stations':len(eligible), 'site_counts':qualified,
            'site_results':summary,'donors':selected,'source_sha256':sources,'metadata_sha256':meta_sha,
            'source_failures':[s for s in sources if not s['success']],
            'raw_hourly_wind_exported':False,
            'scientific_restrictions':['2023 is a new target-year for wind research, the stations had already been present as donors in prior years.',
              'Spatial holdout excludes target station only; regional block exclusion NOT tested.',
              'QC flags not individually confirmed; missing source always reported.',
              'Emitted-only MAE on differing coverage cannot rank methods without matched and recovery metrics.',
              'Fixed-denominator losses with 90°/180° missing penalties are sensitivity diagnostics, not physical error observations.',
              'Direction reliability, instrument exposure, mountainous terrain, and EPW wind ready remain unvalidated.',
              'Not future wind generation, not production EPW.']}
    (dest/'p8_3c_provenance.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('IGE_P8_3C_RESULT',json.dumps({'year':year,'summary':summary,'donors':selected,
          'coverage':qualified,'qualified_sources':len(eligible)},ensure_ascii=False),flush=True)
    return record

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--year',type=int,default=YEAR)
    ap.add_argument('--out',required=True)
    args=ap.parse_args();run(args.year,args.out)