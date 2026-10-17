#!/usr/bin/env python3
"""IGE P9.2A one-shot authentic ERA5-derived three-country joint regimes pilot.

Training 2019+2020; evaluation 2022 at 3 fixed coordinates Jan/Jul 10–16.
Comparison is reanalysis-to-reanalysis independent-year distributional skill,
NOT independent measured 2m station validation or an EPW future generator.
"""
from __future__ import annotations
import argparse,datetime as dt,json
from pathlib import Path
import p9_1a_global_historical_backbone as era
from p9_2a_joint_weather_regimes import (
    ALGORITHM,KEY_METRICS,canonical_days,sampler,scoring,lineage
)

SITES=(('AT','Graz',47.0707,15.4395),
       ('DE','Oberstdorf',47.408,10.280),
       ('CH','Davos',46.801,9.830))
TRAIN_YEARS=(2019,2020)
TARGET_YEAR=2022
PERIODS=(('January','01-10','01-16'),('July','07-10','07-16'))
SEED=7313

def original_days(lat,lon,year,season,startpart,endpart):
    start=f'{year}-{startpart}';end=f'{year}-{endpart}'
    url=era.request_url(lat,lon,start,end)
    rawbytes=era.get_original_source(url)
    original,arrays,meta=era.parse_source(rawbytes,lat,lon,start,end)
    days=canonical_days([x+'Z' for x in original['hourly']['time']],
                        arrays,meta['raw_original_response_sha256'])
    if len(days)!=7 or any(d.date.year!=year for d in days):
        raise ValueError('P92A_GENUINE_SOURCE_YEAR_OR_DAY_MISMATCH')
    return days,{'year':year,'season':season,
                 'original_provider_http_SHA256':meta['raw_original_response_sha256'],
                 'canonical_ERA5_weather_SHA256':meta[
                      'canonical_hourly_weather_and_selected_cell_sha256'],
                 'n_original_source_hours':len(original['hourly']['time']),
                 'model':era.SOURCE_SCOPE,
                 'model_selected_ERA5_grid_lat':meta['selected_cell_latitude'],
                 'model_selected_ERA5_grid_lon':meta['selected_cell_longitude']}

def run(out):
    out.mkdir(parents=True,exist_ok=True)
    report={'phase':'IGE_P9_2A_SINGLE_AUTHENTIC_ERA5_REANALYSIS_JOINT_REGIMES_PILOT',
            'algorithm':ALGORITHM,
            'frozen_country_location_coordinates':[
                {'country':c,'name':n,'lat':a,'lon':b} for c,n,a,b in SITES],
            'registered_training_years':list(TRAIN_YEARS),
            'registered_target_year':TARGET_YEAR,'registered_windows':PERIODS,
            'seed_fixed_before_scorable_target_data':SEED,
            'year_2022_ERA5_source_was_not_fitted':True,
            'ERA5_via_OpenMeteo_not_original_CDS_GRIB':True,
            'NOT_independent_station_observation_validation':True,
            'NOT_CMIP6_future_weather_generation':True,
            'NOT_full_annual_EPW':True,
            'NOT_global_world_validation':True,
            'production_epw_ready':False,'members':[]}
    for country,city,lat,lon in SITES:
        for season,startpart,endpart in PERIODS:
            row={'country':country,'city':city,'season':season,
                 'status':'SOURCE_OR_MODEL_BLOCKED'}
            try:
                train=[];sha=[];reference=None
                for y in (*TRAIN_YEARS,TARGET_YEAR):
                    days,src=original_days(lat,lon,y,season,startpart,endpart)
                    sha.append(src)
                    if y in TRAIN_YEARS:train.extend(days)
                    else:reference=days
                if reference is None or len(train)!=14:
                    raise ValueError('P92A_GENUINE_TRAIN_AND_EVALUATION_DAYS_MISSING')
                dates=[d.date for d in reference]
                joint=sampler(train,dates,SEED,mode='joint_day_blocks')
                hourly=sampler(train,dates,SEED,mode='iid_hourly_joint_vector')
                trial=scoring(reference,joint,hourly)
                row.update({'status':'GENUINE_ERA5_SOURCE_2022_INTERNAL_CLIMATE_EVALUATION',
                            'source_original_SHA':sha,'n_training_original_hours':336,
                            'n_original_ERA5_2022_reference_hours':168,
                            'n_generated_hours_joint_days':168,
                            'n_generated_hours_hourly_baseline':168,
                            'joint_days_original_hourly_vector_provenance':lineage(joint),
                            'diagnostics':trial})
                print('P92A_REAL_SOURCE_SCORED',json.dumps({
                    'country':country,'season':season,
                    'reference_wet_fraction':trial['original_ERA5_2022']['wet_hour_fraction'],
                    'original_wet_persistence':trial['original_ERA5_2022']['P_next_wet_given_wet'],
                    'joint_wet_persistence':trial['joint_day_blocks']['P_next_wet_given_wet'],
                    'iid_wet_persistence':trial['iid_joint_hourly_control']['P_next_wet_given_wet'],
                    'better_metrics':trial['block_better'],
                    'worse_metrics':trial['block_worse'],
                    'unavailable_metrics':trial['unavailable'],
                    'seam_T_joint':trial['joint_day_blocks']['seam_mean_T_jump_C'],
                    'seam_T_iid':trial['iid_joint_hourly_control']['seam_mean_T_jump_C']
                }),flush=True)
            except Exception as e:
                row['status']='SOURCE_OR_MODEL_BLOCKED'
                row['reason']=f'{type(e).__name__}: {e}'[:500]
                print('P92A_REAL_SOURCE_BLOCKED',country,season,row['reason'],flush=True)
            report['members'].append(row)
    good=[x for x in report['members'] if x['status'].startswith('GENUINE_')]
    report['n_preregistered_cells']=6
    report['n_scorable_cells']=len(good)
    report['n_original_ERA5_2022_reference_hours']=168*len(good)
    report['n_training_ERA5_hours_for_scorable_cells']=336*len(good)
    report['n_improved_metric_cells']=sum(len(x['diagnostics']['block_better']) for x in good)
    report['n_worsened_metric_cells']=sum(len(x['diagnostics']['block_worse']) for x in good)
    report['n_equal_metric_cells']=sum(len(x['diagnostics']['block_equal']) for x in good)
    report['n_unavailable_metric_cells']=sum(len(x['diagnostics']['unavailable']) for x in good)
    report['independent_station_qualified']=False
    report['production_weather_generator_qualified']=False
    (out/'p9_2a_authentic_ERA5_regime_pilot_AT_DE_CH.json').write_text(
        json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf8')
    print('P92A_FINAL',json.dumps({
        'scored':len(good),
        'source_hours':report['n_original_ERA5_2022_reference_hours'],
        'better':report['n_improved_metric_cells'],
        'worse':report['n_worsened_metric_cells'],
        'equal':report['n_equal_metric_cells'],
        'unavailable':report['n_unavailable_metric_cells'],
        'production':False}),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default='outputs/p9_2a')
    run(Path(p.parse_args().out))
