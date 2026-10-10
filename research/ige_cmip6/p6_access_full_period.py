#!/usr/bin/env python3
"""IGE P6.1 ACCESS-CM2 complete 20-year, nine-variable daily research extraction.

Five independent windows, each 20 years and 180 NASA NCSS annual subsets.
Raw daily values only; no EPW, bias correction, or future-weather forecast.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

from p6_daily_multivariable import (
    MODEL, MEMBER, SITE, SPECS, FIELDS, catalog, fetch_one, strict_join,
)

WINDOWS = {
    'historical-1995-2014': ('historical', 1995, 2014),
    'ssp245-2040-2059': ('ssp245', 2040, 2059),
    'ssp245-2080-2099': ('ssp245', 2080, 2099),
    'ssp585-2040-2059': ('ssp585', 2040, 2059),
    'ssp585-2080-2099': ('ssp585', 2080, 2099),
}
REFERENCE_PATH = Path(__file__).with_name('p6_access_p5_solar_reference.json')
MONTHLY_FIELDS = [
    'window', 'scenario', 'year', 'month', 'days', 'ghi_kwh_m2',
    'rlds_kwh_m2', 'pr_mm', 'tas_mean_c', 'hurs_mean_pct',
    'huss_mean_kg_kg', 'wind_mean_m_s',
]
ANNUAL_FIELDS = [
    'window', 'scenario', 'year', 'days', 'ghi_kwh_m2', 'rlds_kwh_m2',
    'pr_mm', 'tas_mean_c', 'hurs_mean_pct', 'wind_mean_m_s',
]
CLIMO_FIELDS = [
    'window', 'scenario', 'month', 'years', 'ghi_mean_kwh_m2',
    'ghi_min_kwh_m2', 'ghi_max_kwh_m2', 'pr_mean_mm', 'tas_mean_c',
]

def write_csv(path, fields, records):
    with Path(path).open('w', newline='', encoding='utf-8') as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(records)

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def summarize_daily(rows, window, scenario, years):
    if len(set(years)) != len(years):
        raise ValueError('Repeated year in supplied period')
    groups = defaultdict(list)
    for row in rows:
        if row['scenario'] != scenario or row['year'] not in years:
            raise ValueError('Cross-scenario/year contamination')
        groups[(row['year'], row['month'])].append(row)
    expected_groups = {(y, m) for y in years for m in range(1, 13)}
    if set(groups) != expected_groups:
        raise ValueError('Missing or extra year-month(s)')
    monthly = []
    for y, m in sorted(groups):
        rr = groups[y, m]
        monthly.append({
            'window': window, 'scenario': scenario, 'year': y, 'month': m,
            'days': len(rr),
            'ghi_kwh_m2': sum(r['rsds_kwh_m2_day'] for r in rr),
            'rlds_kwh_m2': sum(r['rlds_kwh_m2_day'] for r in rr),
            'pr_mm': sum(r['pr_mm_day'] for r in rr),
            'tas_mean_c': statistics.fmean(r['tas_c'] for r in rr),
            'hurs_mean_pct': statistics.fmean(r['hurs'] for r in rr),
            'huss_mean_kg_kg': statistics.fmean(r['huss'] for r in rr),
            'wind_mean_m_s': statistics.fmean(r['sfcWind'] for r in rr),
        })
    annual = []
    for y in years:
        yr = [r for r in rows if r['year'] == y]
        mm = [r for r in monthly if r['year'] == y]
        annual.append({
            'window': window, 'scenario': scenario, 'year': y, 'days': len(yr),
            'ghi_kwh_m2': sum(r['ghi_kwh_m2'] for r in mm),
            'rlds_kwh_m2': sum(r['rlds_kwh_m2'] for r in mm),
            'pr_mm': sum(r['pr_mm'] for r in mm),
            'tas_mean_c': statistics.fmean(r['tas_c'] for r in yr),
            'hurs_mean_pct': statistics.fmean(r['hurs'] for r in yr),
            'wind_mean_m_s': statistics.fmean(r['sfcWind'] for r in yr),
        })
    climo = []
    for m in range(1,13):
        items = [r for r in monthly if r['month']==m]
        ghi = [r['ghi_kwh_m2'] for r in items]
        climo.append({
            'window': window, 'scenario': scenario, 'month': m,
            'years': len(items), 'ghi_mean_kwh_m2': statistics.fmean(ghi),
            'ghi_min_kwh_m2': min(ghi), 'ghi_max_kwh_m2': max(ghi),
            'pr_mean_mm': statistics.fmean(r['pr_mm'] for r in items),
            'tas_mean_c': statistics.fmean(r['tas_mean_c'] for r in items),
        })
    return monthly, annual, climo

def compare_p5_ghi(window, climo, tolerance=1.e-4):
    baseline = json.loads(REFERENCE_PATH.read_text(encoding='utf8'))
    if baseline.get('model') != MODEL or baseline.get('member') != MEMBER:
        raise ValueError('Wrong historical P5 provenance')
    expected = baseline['windows'][window]
    if len(expected)!=12 or len(climo)!=12:
        raise ValueError('P5 monthly reference incomplete')
    diagnostics = []
    for r in climo:
        month=int(r['month'])
        value=float(r['ghi_mean_kwh_m2'])
        target=float(expected[month-1])
        error=abs(value-target)
        diagnostics.append({'month':month,'computed':value,'p5':target,
                            'absolute_error_kwh_m2':error})
    max_error=max(d['absolute_error_kwh_m2'] for d in diagnostics)
    if max_error>tolerance:
        raise ValueError(f'P5 solar regression mismatch: max monthly error={max_error:.8g}, allowable={tolerance}')
    return {'status':'PASS','p5_reference_file':REFERENCE_PATH.name,
            'months':len(diagnostics),'tolerance_kwh_m2':tolerance,
            'max_abs_error_kwh_m2':max_error,'monthly_diagnostics':diagnostics}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--window',required=True,choices=tuple(WINDOWS))
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--output-root',type=Path,default=Path('outputs/p6_access_cm2'))
    args=p.parse_args()
    if not 1<=args.workers<=4: p.error('workers must be in [1,4]')
    scenario,first,last=WINDOWS[args.window]
    years=tuple(range(first,last+1))
    if len(years)!=20: raise AssertionError('Only complete 20-year windows')
    out=args.output_root/args.window
    out.mkdir(parents=True,exist_ok=True)
    provenance = {'stage':'P6.1','status':'IN_PROGRESS','window':args.window,
                  'model':MODEL,'member':MEMBER,'scenario':scenario,'year_start':first,
                  'year_end':last,'site':SITE,'variables':list(SPECS),
                  'subset_provenance':[],
                  'caution':'RAW NEX-GDDP-CMIP6; not calibrated; not EPW'}
    start=time.monotonic()
    try:
        catalogs={v:catalog(scenario,v) for v in SPECS}
        requests=[]
        for y in years:
            for v in SPECS:
                if y not in catalogs[v]:raise ValueError(f'Missing catalog {scenario}/{y}/{v}')
                requests.append((scenario,y,v,catalogs[v][y]))
        if len(requests)!=180:raise AssertionError('Expected 180 annual NetCDF subsets')
        data={}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures={pool.submit(fetch_one,*job):(job[1],job[2]) for job in requests}
            for future in as_completed(futures):
                y,v=futures[future]
                payload,meta=future.result()
                if (y,v) in data:raise ValueError('Duplicate NASA response')
                data[(y,v)]=payload
                provenance['subset_provenance'].append(meta)
                print('SOURCE',scenario,y,v,meta['days'],meta['sha256'][:12],flush=True)
        if len(data)!=180:raise ValueError('Not all 180 annual subsets returned')
        records=[]; yearly_qa=[]; locations=set(); calendars=set()
        for y in years:
            daily,qa=strict_join({v:data[y,v] for v in SPECS},scenario,y)
            records.extend(daily)
            yearly_qa.append(qa)
            locations.add((qa['grid_lat'],qa['grid_lon']))
            calendars.add(qa['calendar'])
        if len(locations)!=1: raise ValueError(f'Grid drift across years: {locations}')
        if len(calendars)!=1: raise ValueError(f'Calendar drift across years: {calendars}')
        if len({(r['scenario'],r['year'],r['date']) for r in records})!=len(records):
            raise ValueError('Duplicate scenario-year-date')
        if not 20*360<=len(records)<=20*366:
            raise ValueError('Unexpected daily record count')
        monthly,annual,climo=summarize_daily(records,args.window,scenario,years)
        p5_result=compare_p5_ghi(args.window,climo)
        files={'joint_daily_raw.csv':(FIELDS,records),
               'model_monthly.csv':(MONTHLY_FIELDS,monthly),
               'model_annual.csv':(ANNUAL_FIELDS,annual),
               'model_monthly_climatology.csv':(CLIMO_FIELDS,climo)}
        sha={}
        for name,(cols,rr) in files.items():
            path=out/name
            write_csv(path,cols,rr)
            sha[name]=sha256(path)
        quality={'status':'PASS','model':MODEL,'window':args.window,
                 'year_count':len(years),'daily_records':len(records),
                 'annual_rows':len(annual),'monthly_rows':len(monthly),
                 'monthly_climatology_rows':len(climo),'grid':list(locations)[0],
                 'calendar':list(calendars)[0],'yearly_qa':yearly_qa,
                 'p5_ghi_numerical_regression':p5_result,
                 'csv_sha256':sha}
        (out/'quality_report.json').write_text(json.dumps(quality,indent=2)+'\n',encoding='utf8')
        provenance['status']='PASS'
        provenance['daily_records']=len(records)
        provenance['source_count']=len(provenance['subset_provenance'])
        provenance['csv_sha256']=sha
    except Exception as exc:
        provenance['status']='FAIL'
        provenance['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        provenance['subset_provenance'].sort(key=lambda r:(r['scenario'],r['year'],r['variable']))
        provenance['elapsed_seconds']=round(time.monotonic()-start,2)
        (out/'source_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf8')
        print('P6.1',args.window,provenance['status'],
              'sources',len(provenance['subset_provenance']),flush=True)

if __name__=='__main__':
    main()
