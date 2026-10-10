#!/usr/bin/env python3
"""IGE P6.2A: diagnostic-only joint daily climate physics and dependence audit.

NASA NEX-GDDP-CMIP6 v2 is already bias-corrected (BCSD); DO NOT fit or apply
another bias correction here. Model years are climate realisations, not
time-synchronised historical weather forecasts. No day-by-day comparison to
station observations and no synthetic/modified daily output.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import fmean

FIELDS = ("tas_c","tasmin_c","tasmax_c","hurs","pr_mm_day",
          "rsds_kwh_m2_day","rlds_kwh_m2_day","sfcWind","huss")
SEASONS = {"DJF":(12,1,2),"MAM":(3,4,5),"JJA":(6,7,8),"SON":(9,10,11)}
PAIRS = (("tas_c","hurs"),("tas_c","rsds_kwh_m2_day"),
         ("pr_mm_day","rsds_kwh_m2_day"),("hurs","rsds_kwh_m2_day"),
         ("pr_mm_day","sfcWind"),("tas_c","rlds_kwh_m2_day"))

def pearson(data, x, y):
    pairs = [(r[x],r[y]) for r in data
             if r.get(x) is not None and r.get(y) is not None]
    n=len(pairs)
    if n < 30:return None
    mx=fmean(a for a,b in pairs)
    my=fmean(b for a,b in pairs)
    xx=sum((a-mx)**2 for a,b in pairs)
    yy=sum((b-my)**2 for a,b in pairs)
    if xx<1.e-18 or yy<1.e-18:return None
    r=sum((a-mx)*(b-my) for a,b in pairs)/math.sqrt(xx*yy)
    return max(-1.,min(1.,r))

def quantile(vals,p):
    if not vals:return None
    s=sorted(vals)
    k=(len(s)-1)*p
    a=math.floor(k);b=math.ceil(k)
    return s[a]*(b-k)+s[b]*(k-a) if a!=b else s[a]

def load_daily(path):
    rows=[]
    with Path(path).open(newline='',encoding='utf8') as f:
        reader=csv.DictReader(f)
        needed=set(FIELDS)-{"huss"}
        if not needed <= set(reader.fieldnames or ()):
            raise ValueError('P6.1 required joint daily fields absent')
        for i,item in enumerate(reader,2):
            r={'model':item['model'],'member':item['member'],
               'scenario':item['scenario'],'date':item['date'],
               'year':int(item['year']),'month':int(item['month']),
               'day':int(item['day'])}
            for key in FIELDS:
                raw=item.get(key)
                r[key]=None if raw in (None,'') and key=='huss' else float(raw)
                if r[key] is not None and not math.isfinite(r[key]):
                    raise ValueError(f'Nonfinite {key} at CSV line {i}')
            if r['tasmin_c']>r['tas_c']+.25 or r['tas_c']>r['tasmax_c']+.25:
                raise ValueError(f'Daily temperature extrema inconsistency {r["date"]}')
            for field in ('pr_mm_day','rsds_kwh_m2_day','rlds_kwh_m2_day','sfcWind'):
                if r[field]<-1.e-8:raise ValueError(f'Negative {field} {r["date"]}')
            if r['hurs']<0 or r['hurs']>105:
                raise ValueError(f'Implausible source RH {r["hurs"]}: {r["date"]}')
            if item['date']!=f'{r["year"]:04d}-{r["month"]:02d}-{r["day"]:02d}':
                raise ValueError('Broken native CF daily date')
            if abs(float(item['tas'])-273.15-r['tas_c'])>1.e-7:
                raise ValueError('Temperature unit conversion mismatch')
            if abs(float(item['rsds'])*.024-r['rsds_kwh_m2_day'])>1.e-7:
                raise ValueError('Shortwave unit conversion mismatch')
            if abs(float(item['pr'])*86400-r['pr_mm_day'])>1.e-7:
                raise ValueError('Precipitation unit conversion mismatch')
            rows.append(r)
    if not rows:raise ValueError('Empty NASA daily source')
    return rows

def audit_period(rows, role):
    years=sorted(set(r['year'] for r in rows))
    if len(years)!=20 or years!=list(range(years[0],years[0]+20)):
        raise ValueError(f'{role}: 20 consecutive years required')
    model={r['model'] for r in rows}
    member={r['member'] for r in rows}
    scenario={r['scenario'] for r in rows}
    if len(model)!=1 or len(member)!=1 or len(scenario)!=1:
        raise ValueError(f'{role}: mixed source identity')
    if role=='historical' and scenario!={'historical'}:
        raise ValueError('Historical period must use historical scenario')
    if role=='future' and 'historical' in scenario:
        raise ValueError('Future period must use SSP scenario')
    keys=[(r['year'],r['date']) for r in rows]
    if len(set(keys))!=len(keys) or keys!=sorted(keys):
        raise ValueError('Unsorted/duplicated daily CF index')
    coverage={}
    for year in years:
        yr=[r for r in rows if r['year']==year]
        if len(yr) not in (360,365,366) or set(r['month'] for r in yr)!=set(range(1,13)):
            raise ValueError(f'Incomplete annual source {year}')
        coverage[str(year)]=len(yr)
    by_season={}
    for name,months in SEASONS.items():
        sample=[r for r in rows if r['month'] in months]
        correlations={f'{x}__{y}':pearson(sample,x,y) for x,y in PAIRS}
        wet=[r['pr_mm_day'] for r in sample if r['pr_mm_day']>=1.]
        by_season[name]={
            'days':len(sample),
            'tas_mean_c':fmean(r['tas_c'] for r in sample),
            'tasmax_p95_c':quantile([r['tasmax_c'] for r in sample],.95),
            'hurs_mean_raw_pct':fmean(r['hurs'] for r in sample),
            'hurs_exceedance_count':sum(r['hurs']>100 for r in sample),
            'wet_day_fraction_ge1mm':len(wet)/len(sample),
            'wet_day_pr_p95_mm':quantile(wet,.95),
            'rsds_mean_kwh_m2_day':fmean(r['rsds_kwh_m2_day'] for r in sample),
            'sfcwind_mean_m_s':fmean(r['sfcWind'] for r in sample),
            'pearson_daily_within_season':correlations,
        }
    huss_missing=sum(r['huss'] is None for r in rows)
    if huss_missing not in (0,len(rows)):
        raise ValueError('Incomplete optional specific humidity provenance')
    annual={str(y):{
        'days':coverage[str(y)],
        'pr_mm':sum(r['pr_mm_day'] for r in rows if r['year']==y),
        'ghi_kwh_m2':sum(r['rsds_kwh_m2_day'] for r in rows if r['year']==y),
        'tas_mean_c':fmean(r['tas_c'] for r in rows if r['year']==y)
    } for y in years}
    return {
        'role':role,'model':next(iter(model)),'member':next(iter(member)),
        'scenario':next(iter(scenario)),'start_year':years[0],'end_year':years[-1],
        'days':len(rows),'days_by_year':coverage,
        'huss_missing_days':huss_missing,
        'raw_hurs_above_100':sum(r['hurs']>100 for r in rows),
        'raw_hurs_max':max(r['hurs'] for r in rows),
        'annual_mean_pr_mm':fmean(r['pr_mm'] for r in annual.values()),
        'annual_mean_ghi_kwh_m2':fmean(r['ghi_kwh_m2'] for r in annual.values()),
        'annual_mean_tas_c':fmean(r['tas_mean_c'] for r in annual.values()),
        'seasons':by_season
    }

def compare(hist,future):
    if (hist['model'],hist['member'])!=(future['model'],future['member']):
        raise ValueError('Different model/member cannot form paired climate change comparison')
    out={'tas_annual_mean_change_c':future['annual_mean_tas_c']-hist['annual_mean_tas_c'],
         'precipitation_annual_mean_ratio':future['annual_mean_pr_mm']/hist['annual_mean_pr_mm']
                                         if hist['annual_mean_pr_mm']>0 else None,
         'ghi_annual_mean_ratio':future['annual_mean_ghi_kwh_m2']/hist['annual_mean_ghi_kwh_m2']
                                  if hist['annual_mean_ghi_kwh_m2']>0 else None,
         'seasonal_correlation_changes':{}}
    for season in SEASONS:
        a=hist['seasons'][season]['pearson_daily_within_season']
        b=future['seasons'][season]['pearson_daily_within_season']
        out['seasonal_correlation_changes'][season]={
            k:(b[k]-a[k] if a[k] is not None and b[k] is not None else None)
            for k in a}
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--historical',type=Path,required=True)
    p.add_argument('--future',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('outputs/p6_2a/daily_multivariate_audit.json'))
    a=p.parse_args()
    h=audit_period(load_daily(a.historical),'historical')
    f=audit_period(load_daily(a.future),'future')
    report={
        'status':'PASS',
        'stage':'P6.2A',
        'method':'diagnostic_only_no_bias_correction_applied',
        'source_description':'NASA NEX-GDDP-CMIP6 v2.0 (already BCSD-adjusted)',
        'historical':h,'future':f,'comparison':compare(h,f),
        'unassessed':[
            'local psychrometric closure needs site pressure and nonlinear temporal handling',
            'station time-series observation validation is separate',
            'daily wind direction and hourly weather unavailable',
            'no future year-by-year weather prediction or station-day RMSE',
        ]
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print('P6.2A DAILY DIAGNOSTIC',report['status'],
          'model',h['model'],'historical days',h['days'],'future days',f['days'],
          'temperature_delta',round(report['comparison']['tas_annual_mean_change_c'],3),
          flush=True)

if __name__=='__main__':main()
