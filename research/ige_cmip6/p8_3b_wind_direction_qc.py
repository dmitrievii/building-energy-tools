#!/usr/bin/env python3
"""IGE P8.3B: source-QC visibility and pre-registered robust circular wind hindcast.

No modifications to original P8.3A scalar wind reconstruction. Targets excluded
from donor selection and prediction; 2021 exploratory, 2022 temporal test.
Exports only aggregates, selection and provider source SHA (NO hourly series).
"""
from __future__ import annotations
import argparse, collections, csv, datetime as dt, json, math
from pathlib import Path
import numpy as np

from p8_3a_wind_spatial import (
    CALM_MPS, TARGETS, SPEED, DIRECTION, idw_weights, usable_wind,
    parse_wind_year, wind_coverage, interpolate, circular_error_deg,
)

YEARS = (2021, 2022)
UNIT_RESULTANT_THRESHOLD = 0.20  # frozen before inspecting P8.3B real results
SOURCE_QC_SUFFIXES = ('_qc', '_flag', '_quality', '_q')
SPEED_BINS = (('0.5-<2', .5, 2.), ('2-<5', 2., 5.), ('>=5', 5., float('inf')))
RESULTANT_BINS = (('0-<0.3',0.,.3),('0.3-<0.6',.3,.6),('0.6-<0.85',.6,.85),('0.85-1',.85,1.00000001))
SEASONS={12:'DJF',1:'DJF',2:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'}


def csv_source_qc_profile(raw:bytes, site:str, year:int):
    """Explicitly distinguish source historical review from per-record QC flags.

    This OGD format commonly has numeric values but no exported per-hour QC;
    never invent a positive QC flag or a code mapping. If flags occur, report
    presence but DO NOT classify unregistered codes as quality accepted.
    """
    header=raw.decode('utf-8-sig', errors='replace').splitlines()[0]
    cols=next(csv.reader([header],delimiter=';'))
    required={'station_abbr','reference_timestamp',SPEED,DIRECTION}
    if not required.issubset(cols): raise ValueError('MISSING_OFFICIAL_WIND_FIELDS')
    flag_fields=[name for name in cols if name.lower() in {
        p+s for p in (SPEED,DIRECTION) for s in SOURCE_QC_SUFFIXES}]
    return {'site':site,'year':year,'hourly_wind_schema_present':True,
            'speed_field_present':SPEED in cols,'direction_field_present':DIRECTION in cols,
            'individual_quality_flag_columns':';'.join(flag_fields),
            'individual_qc_available':bool(flag_fields),
            'individual_qc_codes_verified':False,
            'qc_status':'FLAGS_PRESENT_CODES_UNMAPPED' if flag_fields else 'NO_EXPLICIT_PER_RECORD_QC_IN_HOURLY_CSV',
            'historical_provider_review':'MeteoSwiss historic observations have post-acquisition review, per provider FAQ; not record-level flag proof'}


def circular_unit_prediction(donors,weather,stamp,threshold=UNIT_RESULTANT_THRESHOLD):
    """Unit vectors of directional donors; never let calm observations set azimuth.

    Same four stations and IDW weights as P8.3A; within-hour re-normalization
    among non-calm measured directional donors. A pure directional alternative,
    NOT a source instrument vector-speed estimator.
    """
    good=[]
    for distance,station in donors:
        x=weather.get(station['station_id'],{}).get(stamp)
        if usable_wind(x) and x['speed']>=CALM_MPS:
            good.append((distance,float(x['direction'])))
    if len(good)<2:
        return {'unit_direction':None,'unit_resultant':None,'unit_noncalm_count':len(good),'unit_reason':'INSUFFICIENT_DIRECTION_DONORS'}
    w=idw_weights([d for d,_ in good]);a=np.radians([a for _,a in good]);east=float(w@np.sin(a));north=float(w@np.cos(a))
    resultant=math.hypot(east,north)
    if resultant<0 or resultant>1+1e-8:raise AssertionError('UNIT_RESULTANT_OUT_OF_RANGE')
    direction=math.degrees(math.atan2(east,north))%360. if resultant>=threshold else None
    return {'unit_direction':direction,'unit_resultant':resultant,'unit_noncalm_count':len(good),
            'unit_reason':'RESOLVED' if direction is not None else 'DIRECTION_DISAGREEMENT'}


def bin_label(x, bins):
    if x is None:return 'undefined'
    for label,lower,upper in bins:
        if lower<=x<upper:return label
    raise ValueError(f'Value outside bins: {x}')


def summarize_angles(rows,site,year,group_type,group,strict_min=0):
    """Paired-comparison numerator and denominator, no coverage cheating."""
    observed=[r for r in rows if r['observed_direction'] is not None]
    paired=[r for r in observed if all(r[k] is not None for k in ('vector_direction','unit_direction','nearest_direction'))]
    def stats(k, subset):
        angles=[circular_error_deg(r[k],r['observed_direction']) for r in subset if r[k] is not None]
        return len(angles), (sum(angles)/len(angles) if angles else None)
    all_stat={k:stats(k,observed) for k in ('vector_direction','unit_direction','nearest_direction')}
    paired_stat={k:stats(k,paired) for k in ('vector_direction','unit_direction','nearest_direction')}
    speeds=np.asarray([r['observed_speed'] for r in rows],float)
    scalar=np.asarray([r['scalar_speed'] for r in rows],float)
    if len(rows)<strict_min:raise ValueError('Insufficient paired wind coverage')
    return dict(year=year,site=site,group_type=group_type,group=group,
       target_noncalm_reference_hours=len(observed),scored_all_hours=len(rows),
       matched_all_three_hours=len(paired),
       vector_resolved_hours=all_stat['vector_direction'][0],unit_resolved_hours=all_stat['unit_direction'][0],
       nearest_resolved_hours=all_stat['nearest_direction'][0],
       vector_unpaired_MAE_deg=all_stat['vector_direction'][1],
       unit_unpaired_MAE_deg=all_stat['unit_direction'][1],
       nearest_unpaired_MAE_deg=all_stat['nearest_direction'][1],
       vector_strict_matched_MAE_deg=paired_stat['vector_direction'][1],
       unit_strict_matched_MAE_deg=paired_stat['unit_direction'][1],
       nearest_strict_matched_MAE_deg=paired_stat['nearest_direction'][1],
       scalar_speed_MAE_mps=float(np.mean(abs(scalar-speeds))) if len(rows) else None,
       scalar_speed_bias_mps=float(np.mean(scalar-speeds)) if len(rows) else None,
       resultant_unit_mean=float(np.mean([r['unit_resultant'] for r in rows if r['unit_resultant'] is not None])) if any(r['unit_resultant'] is not None for r in rows) else None,
       weighted_opposition_hours=sum(r['vector_ratio']<.3 for r in rows),
       vector_missing_noncalm_hours=sum(r['vector_direction'] is None for r in observed),
       unit_missing_noncalm_hours=sum(r['unit_direction'] is None for r in observed))


def evaluate_target(year,site,hours,donors,donor_w,reference,minimum_coverage=.80):
    """One target's original 4-donor P8.3A reconstruction + unit direction.

    The original P8.3A speed and vector model are invoked unchanged.
    All observed target values enter only after donor predictions are computed.
    """
    if site in donor_w or any(s['station_id']==site for _,s in donors):raise AssertionError('TARGET_WIND_LEAK')
    rows=[];total_reference_noncalm=0
    for stamp in hours:
        p=interpolate(donors,donor_w,stamp)
        unit=circular_unit_prediction(donors,donor_w,stamp)
        ref=reference.get(stamp)
        if not usable_wind(ref):continue
        if ref['speed']>=CALM_MPS and ref['direction'] is not None:total_reference_noncalm+=1
        if p is None:continue
        rows.append(dict(year=year,site=site,season=SEASONS[stamp.month],
            obs_speed_group=bin_label(ref['speed'],SPEED_BINS) if ref['speed']>=CALM_MPS else 'calm',
            unit_reliability_group=bin_label(unit['unit_resultant'],RESULTANT_BINS),
            wind_resultant_group=bin_label(p['resultant_ratio'],RESULTANT_BINS),
            observed_speed=float(ref['speed']),
            observed_direction=float(ref['direction']) if ref['speed']>=CALM_MPS else None,
            vector_direction=p['vector_direction'],unit_direction=unit['unit_direction'],
            nearest_direction=p['nearest_direction'],vector_ratio=p['resultant_ratio'],
            unit_resultant=unit['unit_resultant'],scalar_speed=p['scalar_speed']))
    if len(rows)<minimum_coverage*len(hours):raise ValueError('INSUFFICIENT_TARGET_COVERAGE_'+site)
    groups=[summarize_angles(rows,site,year,'site','all')]
    for name in ['DJF','MAM','JJA','SON']:
        r=[x for x in rows if x['season']==name]
        if r:groups.append(summarize_angles(r,site,year,'season',name))
    for key in ('obs_speed_group','unit_reliability_group','wind_resultant_group'):
        labels=sorted({x[key] for x in rows})
        for name in labels:
            r=[x for x in rows if x[key]==name]
            if r:groups.append(summarize_angles(r,site,year,key,name))
    return groups,{'site':site,'year':year,'n_scored_hours':len(rows),
      'n_source_reference_noncalm':total_reference_noncalm,
      'total_available_target_hours':sum(usable_wind(reference.get(h)) for h in hours),
      'n_matched_three':groups[0]['matched_all_three_hours'],
      'no_target_weather_used_for_prediction':True}


def save_csv(path,rows):
    if not rows:raise ValueError('EMPTY_P8_3B_OUTPUT')
    with Path(path).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def run(year,out):
    if year not in YEARS:raise ValueError('P8.3B only pre-registered 2021/2022')
    from p8_2e_crossyear import ROOT,POOL,annual_hours
    from p8_1e_swiss_external import fetch,parse_meta,haversine
    from p8_2f_station_selection import metadata_candidates
    hours=annual_hours(year);dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    meta,meta_sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    md,_=parse_meta(meta)
    nearest,candidates=metadata_candidates(md,TARGETS,POOL,nearest_count=20)
    sources=[];cover=[];weather={};headers=[]
    for sid in candidates:
        try:
            raw,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_2020-2029.csv',max_bytes=37000000)
            headers.append(csv_source_qc_profile(raw,sid,year))
            data=parse_wind_year(raw,sid,year)
            c=wind_coverage(data,hours)
            sources.append({'site':sid,'sha256':sha,'fetched':True})
            if c['eligible'] or sid in TARGETS:weather[sid]=data
        except Exception as exc:
            c={'recorded_rows':0,'speed_hours':0,'usable_wind_hours':0,
              'noncalm_speed_hours':0,'noncalm_direction_hours':0,'eligible':False}
            headers.append({'site':sid,'year':year,'hourly_wind_schema_present':False,
                'speed_field_present':False,'direction_field_present':False,
                'individual_quality_flag_columns':'','individual_qc_available':False,
                'individual_qc_codes_verified':False,'qc_status':'SOURCE_UNAVAILABLE',
                'historical_provider_review':'UNAVAILABLE'})
            sources.append({'site':sid,'fetched':False,'error_type':type(exc).__name__,'error':str(exc)[:110]})
        cover.append({'year':year,'site':sid,**c})
    eligible={x['site'] for x in cover if x['eligible']}
    selection=[];overall=[];provenance=[]
    for tid in TARGETS:
        if tid not in weather:raise ValueError('TARGET_SOURCE_UNAVAILABLE_'+tid)
        chosen=sorted(((float(haversine(md[tid]['lat'],md[tid]['lon'],md[sid]['lat'],md[sid]['lon'])),md[sid])
                       for sid in eligible if sid!=tid),key=lambda x:(x[0],x[1]['station_id']))[:4]
        if len(chosen)<4:raise ValueError('INSUFFICIENT_DONORS_'+tid)
        dw={sid:w for sid,w in weather.items() if sid!=tid}
        rows,diag=evaluate_target(year,tid,hours,chosen,dw,weather[tid])
        overall.extend(rows);provenance.append(diag)
        selection.append({'year':year,'target':tid,
          'donors':';'.join(s['station_id'] for _,s in chosen),
          'distances_km':';'.join(f'{d:.3f}' for d,_ in chosen),
          'donor_heights_m':';'.join(str(s['hoehe_m']) for _,s in chosen),
          'prediction_uses_target':False})
    save_csv(dest/'p8_3b_source_wind_coverage.csv',cover)
    save_csv(dest/'p8_3b_header_qc_visibility.csv',headers)
    save_csv(dest/'p8_3b_station_selection.csv',selection)
    save_csv(dest/'p8_3b_direction_stratified.csv',overall)
    report={'phase':'IGE_P8_3B_SOURCE_QC_AND_CIRCULAR_DIRECTION',
       'year':year,'status':'RESEARCH_ONLY_NOT_APPROVED_EPWS',
       'source':'MeteoSwiss original reviewed historical station files',
       'source_qc_semantics':'Historical files are provider-reviewed; numeric presence is not an individual source-QC-flag pass',
       'qc_flag_certified':False,
       'unit_method':'IDW-weighted unit circle from noncalm donor directions (speed ignored in azimuth), 2+ directional donors, R>=0.20',
       'legacy_method':'P8.3A original vector direction and scalar speed unchanged',
       'source_sha256':sources,'meta_sha256':meta_sha,'selection':selection,
       'coverage':provenance,'site_aggregate':[x for x in overall if x['group_type']=='site'],
       'unseen_year_note':'2022 is newer temporal confirmation; target regions/stations were known from 2021',
       'limitations':['No verified MeteoSwiss per-hour QC flags in source CSV by default',
           'No arbitrary directions for calm or unresolved cases',
           'No score tuning or model adoption based on 2021',
           'Direction metrics must be matched-hour compared with resolved coverage reported',
           'The experiment uses contemporaneous observed stations and does not generate future wind',
           'Terrain flow and station exposure are not modelled or validated'],
       'original_provider_hourly_records_redistributed':False}
    (dest/'p8_3b_provenance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('IGE_P8_3B_RESULT',json.dumps({'year':year,'site_aggregate':report['site_aggregate'],
        'selection':selection,'source_QC_flag_columns':{h['site']:h['qc_status'] for h in headers if h['site'] in TARGETS},
        'qualified_source_count':len(eligible)},ensure_ascii=False),flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int,choices=YEARS,required=True)
    parser.add_argument('--out',required=True)
    opts=parser.parse_args();run(opts.year,opts.out)