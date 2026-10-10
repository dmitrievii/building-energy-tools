#!/usr/bin/env python3
"""IGE P6.2A complete 8-GCM diagnostic ensemble from accepted P6.1 artifacts.

No second bias correction, no matching individual GCM days to station days,
no inferred probabilistic confidence intervals, and no generated weather.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import fmean

from p6_2a_joint_diagnostics import audit_period, load_daily, compare, quantile
from p6_2a_geosphere_monthly import compare_monthly, extract_monthly
from p6_access_full_period import WINDOWS, MODEL as ACCESS
from p6_seven_daily import MODELS as SEVEN, model_variables, SOURCE_EXCEPTIONS

MODELS=(ACCESS,)+SEVEN
EXPECTED_WINDOWS=tuple(WINDOWS)
ANNUAL_KEYS=('annual_mean_tas_c','annual_mean_pr_mm','annual_mean_ghi_kwh_m2')
CHANGE_KEYS=('tas_annual_mean_change_c','precipitation_annual_mean_ratio','ghi_annual_mean_ratio')
DAILY_FILES=('joint_daily_raw.csv','model_monthly.csv','model_annual.csv',
             'model_monthly_climatology.csv')

def jsonread(path):
    return json.loads(Path(path).read_text(encoding='utf8'))

def check_files(folder, metadata):
    digests=metadata.get('csv_sha256',{})
    if set(digests)!=set(DAILY_FILES):
        raise ValueError(f'Expected four original P6.1 data files in {folder}')
    for name,digest in digests.items():
        path=folder/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError(f'P6.1 CSV digest mismatch: {path}')
    return digests

def original_quality(folder,model,window):
    qa=jsonread(folder/'quality_report.json')
    prov=jsonread(folder/'source_provenance.json')
    for record in (qa,prov):
        if record.get('status')!='PASS':
            raise ValueError(f'Invalid P6.1 source QA in {folder}')
        if record.get('model')!=model:
            raise ValueError(f'Wrong provenance model in {folder}')
        if record.get('window')!=window:
            raise ValueError(f'Wrong provenance window in {folder}')
    if qa.get('csv_sha256')!=prov.get('csv_sha256'):
        raise ValueError('P6.1 source hashes disagree')
    digests=check_files(folder,qa)
    if model==ACCESS:
        expected_sources=180
        source=prov['subset_provenance']
        raise_unexpected=qa.get('days')  # ACCESS P6.1 uses daily_records, see below
        source_count=len(source)
        count=qa.get('daily_records')
    else:
        expected_sources=20*len(model_variables(model))
        source=prov['subset_provenance']
        source_count=len(source)
        count=qa.get('days')
        absent=SOURCE_EXCEPTIONS.get(model,())
        if qa.get('missing_source_variables')!=list(absent):
            raise ValueError(f'Optional variable provenance mismatch in {folder}')
    if source_count!=expected_sources or count is None:
        raise ValueError(f'P6.1 model source coverage failure: {folder}')
    if qa.get('calendar') is None:
        raise ValueError('CF calendar provenance missing')
    return qa,prov,digests,count

def write_csv(path,rows):
    if not rows:raise ValueError(f'No output rows for {path}')
    with path.open('w',newline='',encoding='utf8') as file:
        w=csv.DictWriter(file,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()

def summary_from_audits(audits):
    """Eight paired-model changes; never weight calendars/days across models."""
    if set(audits)!=set(MODELS):
        raise ValueError('Exactly eight named P5 models required')
    change_rows=[]
    for model in MODELS:
        groups=audits[model]
        if set(groups)!=set(EXPECTED_WINDOWS):
            raise ValueError(f'Incomplete five-window model ensemble: {model}')
        h=groups['historical-1995-2014']
        for window in EXPECTED_WINDOWS[1:]:
            f=groups[window]
            changes=compare(h,f)
            change_rows.append({
                'model':model,'window':window,'scenario':f['scenario'],
                'tas_annual_mean_change_c':changes['tas_annual_mean_change_c'],
                'precipitation_annual_mean_ratio':changes['precipitation_annual_mean_ratio'],
                'ghi_annual_mean_ratio':changes['ghi_annual_mean_ratio'],
                'jja_tas_mean_change_c':
                    f['seasons']['JJA']['tas_mean_c']-h['seasons']['JJA']['tas_mean_c'],
                'jja_tmax_p95_change_c':
                    f['seasons']['JJA']['tasmax_p95_c']-h['seasons']['JJA']['tasmax_p95_c'],
                'jja_wet_day_fraction_change':
                    f['seasons']['JJA']['wet_day_fraction_ge1mm']-
                    h['seasons']['JJA']['wet_day_fraction_ge1mm'],
                'jja_tas_rsds_correlation_change':
                    changes['seasonal_correlation_changes']['JJA']['tas_c__rsds_kwh_m2_day'],
                'jja_pr_rsds_correlation_change':
                    changes['seasonal_correlation_changes']['JJA']['pr_mm_day__rsds_kwh_m2_day'],
            })
    metrics=[k for k in change_rows[0] if k not in ('model','window','scenario')]
    output=[]
    for window in EXPECTED_WINDOWS[1:]:
        selected=[r for r in change_rows if r['window']==window]
        if len(selected)!=8:raise ValueError('One or more model climate change members missing')
        for metric in metrics:
            vals=[float(r[metric]) for r in selected if r[metric] is not None]
            if len(vals)<6:raise ValueError(f'Insufficient model-member pairs {window}/{metric}')
            output.append({'window':window,'metric':metric,'models_with_metric':len(vals),
                           'ensemble_median':quantile(vals,.5),
                           'ensemble_p10':quantile(vals,.1),
                           'ensemble_p90':quantile(vals,.9),
                           'ensemble_min':min(vals),'ensemble_max':max(vals),
                           'interpretation':'descriptive_8_GCM_spread_not_probability'})
    return change_rows,output

def execute(access,seven,obs_geojson,out):
    obs=extract_monthly(jsonread(obs_geojson))
    audits={};quality_inventory={}; model_rows=[];residual_rows=[];residual_models=[]
    total_days=0;total_source_files=0
    for model in MODELS:
        audits[model]={}
        quality_inventory[model]={}
        for window in EXPECTED_WINDOWS:
            folder=(access/window if model==ACCESS else seven/f'ige-p6-{model}-{window}')
            qa,prov,digests,day_count=original_quality(folder,model,window)
            daily=load_daily(folder/'joint_daily_raw.csv')
            if len(daily)!=day_count:
                raise ValueError(f'Daily source count mismatch {model}/{window}')
            role='historical' if window=='historical-1995-2014' else 'future'
            a=audit_period(daily,role)
            if a['model']!=model or a['days']!=day_count or \
               a['start_year']!=WINDOWS[window][1] or a['end_year']!=WINDOWS[window][2]:
                raise ValueError(f'Audit identity/coverage disagreement {model}/{window}')
            audits[model][window]=a
            total_days+=a['days']
            total_source_files+=len(prov['subset_provenance'])
            quality_inventory[model][window]={
                'calendar':qa['calendar'],'grid':qa['grid'],
                'source_NetCDF_count':len(prov['subset_provenance']),
                'daily_count':day_count,'csv_sha256':digests,
                'raw_hurs_above_100':a['raw_hurs_above_100'],
                'huss_unavailable_days':a['huss_missing_days']
            }
            model_rows.append({
                'model':model,'window':window,'scenario':a['scenario'],
                'days':a['days'],'calendar':qa['calendar'],
                'annual_tas_mean_c':a['annual_mean_tas_c'],
                'annual_pr_mean_mm':a['annual_mean_pr_mm'],
                'annual_ghi_mean_kwh_m2':a['annual_mean_ghi_kwh_m2'],
                'jja_tas_mean_c':a['seasons']['JJA']['tas_mean_c'],
                'jja_tmax_p95_c':a['seasons']['JJA']['tasmax_p95_c'],
                'jja_wetday_fraction_ge1mm':a['seasons']['JJA']['wet_day_fraction_ge1mm'],
                'raw_hurs_gt100_count':a['raw_hurs_above_100'],
                'raw_hurs_max_pct':a['raw_hurs_max'],
                'missing_huss_days':a['huss_missing_days'],
                'jja_tas_rsds_pearson':a['seasons']['JJA']['pearson_daily_within_season']['tas_c__rsds_kwh_m2_day'],
                'jja_pr_rsds_pearson':a['seasons']['JJA']['pearson_daily_within_season']['pr_mm_day__rsds_kwh_m2_day'],
            })
            if role=='historical':
                comp=compare_monthly(obs,folder/'model_monthly_climatology.csv')
                for rec in comp['monthly']:
                    residual_rows.append({'model':model,**rec})
                residual_models.append({
                    'model':model,
                    'station30_temperature_climatology_monthly_mae_c':
                        comp['temperature_monthly_climatology_mae_c'],
                    'station30_precipitation_climatology_year_mm':
                        comp['station_annual_mean_monthly_precip_total_mm'],
                    'model_precipitation_climatology_year_mm':
                        comp['model_annual_mean_monthly_precip_total_mm'],
                    'nasa_minus_station_precip_mm':
                        comp['model_annual_mean_monthly_precip_total_mm']-
                        comp['station_annual_mean_monthly_precip_total_mm'],
                    'observation_period':'1995-2014',
                    'interpretation':'climatological_spatial_and_metric_residual_not_holdout_error'
                })
    if total_source_files!=7100 or len(model_rows)!=40 or len(residual_rows)!=96:
        raise ValueError(f'Expected 7100 sources, 40 model windows, 96 monthly station comparisons; got {total_source_files}/{len(model_rows)}/{len(residual_rows)}')
    change_rows,spread=summary_from_audits(audits)
    if len(change_rows)!=32:
        raise ValueError('Expected 8x4 paired model climate changes')
    out.mkdir(parents=True,exist_ok=True)
    output={
        'all_model_period_climate.csv':model_rows,
        'paired_model_climate_changes.csv':change_rows,
        'eight_gcm_change_spread.csv':spread,
        'station30_monthly_residuals.csv':residual_rows,
        'station30_residual_by_model.csv':residual_models,
    }
    files={}
    for filename,rows in output.items():
        files[filename]=write_csv(out/filename,rows)
    result={
        'status':'PASS','stage':'P6.2A','method':'unchanged NASA NEX-GDDP-CMIP6 v2.0 BCSD source diagnostic',
        'model_count':8,'periods_per_model':5,'model_years':800,
        'source_NetCDF_files':total_source_files,
        'daily_records':total_days,'paired_model_future_windows':32,
        'monthly_station_comparison_rows':len(residual_rows),
        'observed_station_id':30,'observed_station_data_sha256':
            hashlib.sha256(Path(obs_geojson).read_bytes()).hexdigest(),
        'source_quality_inventory':quality_inventory,
        'outputs_sha256':files,
        'methodological_caveats':[
            'P10/P90 across eight selected GCMs are descriptive model spread, not a confidence interval.',
            'Model climate years are not temporally matched to station observation years.',
            'Station 30 is spatially distinct from NASA sampled grid cell.',
            'GeoSphere tl_mittel and NASA tas are not identically defined measurements.',
            'NASA data already BCSD-adjusted, so no local bias correction was applied.',
            'Source RH above 100 percent is preserved/flagged rather than silently clamped.',
            'Source-specific IPSL-CM6A-LR huss is missing, not reconstructed.',
            'No hourly weather or EPW produced.',
        ]}
    (out/'p6_2a_eight_model_report.json').write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--access-root',type=Path,required=True)
    p.add_argument('--seven-root',type=Path,required=True)
    p.add_argument('--station-geojson',type=Path,required=True)
    p.add_argument('--out',type=Path,default=Path('outputs/p6_2a_eight_models'))
    a=p.parse_args()
    report=execute(a.access_root,a.seven_root,a.station_geojson,a.out)
    print('P6.2A 8-GCM',report['status'],'models',report['model_count'],
          'sources',report['source_NetCDF_files'],'days',report['daily_records'],
          'CSV',len(report['outputs_sha256']),flush=True)

if __name__=='__main__':
    main()
