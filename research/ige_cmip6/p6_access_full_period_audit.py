#!/usr/bin/env python3
"""Fail-closed P6.1 ACCESS-CM2 closeout across five 20-year GitHub artifacts."""
from __future__ import annotations
import argparse
import csv
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from p6_access_full_period import WINDOWS, MONTHLY_FIELDS, ANNUAL_FIELDS, CLIMO_FIELDS, FIELDS, MODEL, MEMBER, SPECS

def rows(path):
    with path.open(newline='',encoding='utf8') as f:
        return list(csv.DictReader(f))

def read(path):
    return json.loads(path.read_text(encoding='utf8'))

def check_files(out,sha):
    for filename,digest in sha.items():
        file=out/filename
        if not file.is_file():raise ValueError(f'Missing output {file}')
        actual=hashlib.sha256(file.read_bytes()).hexdigest()
        if actual!=digest:raise ValueError(f'Corrupted or modified {file}')

def validate(root):
    summary={'status':'IN_PROGRESS','stage':'P6.1','model':MODEL,'member':MEMBER,
             'windows':{},'raw_sources':0,'year_count':0,'daily_count':0,
             'p5_month_comparisons':0,'scientific_status':'Research daily source validation only; not EPW'}
    coords=set();calendars=set();seen=set()
    for window,(scenario,first,last) in WINDOWS.items():
        out=root/f'ige-p6-access-{window}'
        if not out.is_dir():raise ValueError(f'Missing GitHub artifact folder {out}')
        prov=read(out/'source_provenance.json')
        qa=read(out/'quality_report.json')
        if prov.get('status')!='PASS' or qa.get('status')!='PASS':
            raise ValueError(f'Failed/missing QA {window}')
        if prov.get('model')!=MODEL or prov.get('member')!=MEMBER or prov.get('window')!=window:
            raise ValueError('Mislabelled source provenance')
        if prov.get('scenario')!=scenario or (prov.get('year_start'),prov.get('year_end'))!=(first,last):
            raise ValueError('Wrong model time range')
        source=prov.get('subset_provenance',[])
        source_set={(x['scenario'],x['year'],x['variable']) for x in source}
        expected={(scenario,y,v) for y in range(first,last+1) for v in SPECS}
        if len(source)!=180 or source_set!=expected:
            raise ValueError(f'Incomplete/duplicated NASA provenance for {window}')
        qa_years=qa.get('yearly_qa',[])
        if len(qa_years)!=20 or [x['year'] for x in qa_years]!=list(range(first,last+1)):
            raise ValueError(f'Incomplete annual QA {window}')
        csv_shas=qa.get('csv_sha256')
        if not isinstance(csv_shas,dict) or set(csv_shas)!={
            'joint_daily_raw.csv','model_monthly.csv','model_annual.csv','model_monthly_climatology.csv'}:
            raise ValueError(f'Incomplete data file inventory {window}')
        if csv_shas!=prov.get('csv_sha256'):
            raise ValueError(f'Provenance checksum mismatch {window}')
        check_files(out,csv_shas)
        rr=rows(out/'joint_daily_raw.csv')
        mm=rows(out/'model_monthly.csv')
        aa=rows(out/'model_annual.csv')
        cc=rows(out/'model_monthly_climatology.csv')
        if len(mm)!=240 or len(aa)!=20 or len(cc)!=12:
            raise ValueError(f'Incorrect monthly/annual/climatology counts {window}')
        if len(rr)!=qa.get('daily_records') or len(rr)!=sum(x['days'] for x in qa_years):
            raise ValueError(f'Incorrect daily record count {window}')
        dates_by_year=defaultdict(list)
        for row in rr:
            if set(row)!=set(FIELDS) or row['scenario']!=scenario or row['model']!=MODEL or row['member']!=MEMBER:
                raise ValueError('Bad daily variable identity')
            y=int(row['year']);m=int(row['month'])
            if y<first or y>last or m<1 or m>12 or row['date']!=f'{y:04d}-{m:02d}-{int(row["day"]):02d}':
                raise ValueError('Bad daily date')
            key=(scenario,y,row['date'])
            if key in seen:raise ValueError(f'Duplicate daily scenario/date {key}')
            seen.add(key)
            dates_by_year[y].append(row['date'])
        for yearly in qa_years:
            dates=dates_by_year[yearly['year']]
            if len(dates)!=yearly['days'] or dates!=sorted(dates):
                raise ValueError('Incomplete/unsorted joint date index')
            coords.add((yearly['grid_lat'],yearly['grid_lon']))
            calendars.add(yearly['calendar'])
        p5=qa.get('p5_ghi_numerical_regression',{})
        if p5.get('status')!='PASS' or p5.get('months')!=12 or p5.get('max_abs_error_kwh_m2',float('inf'))>1e-4:
            raise ValueError('Incomplete P5 GHI monthly numerical regression')
        summary['windows'][window]={'status':'PASS','days':len(rr),'years':len(aa),
                                    'source_count':len(source),'p5_max_ghi_monthly_error_kwh_m2':
                                    p5['max_abs_error_kwh_m2'],'sha256':csv_shas}
        summary['raw_sources']+=len(source)
        summary['year_count']+=len(aa)
        summary['daily_count']+=len(rr)
        summary['p5_month_comparisons']+=12
    if len(coords)!=1 or len(calendars)!=1:
        raise ValueError(f'Mixed grids/calendars across windows: {coords}, {calendars}')
    if summary['raw_sources']!=900 or summary['year_count']!=100 or summary['p5_month_comparisons']!=60:
        raise ValueError('Total P6.1 100-year/900-source/60-P5-month closure failed')
    if summary['daily_count']!=len(seen):raise ValueError('Global daily index mismatch')
    summary['grid']=list(coords)[0]
    summary['calendar']=next(iter(calendars))
    summary['status']='PASS'
    return summary

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--artifacts-root',type=Path,default=Path('p6_downloaded'))
    p.add_argument('--output',type=Path,default=Path('p6_closeout.json'))
    args=p.parse_args()
    try:
        result=validate(args.artifacts_root)
    except Exception as e:
        result={'status':'FAIL','error':f'{type(e).__name__}: {e}'}
        raise
    finally:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print('P6.1 full-period audit',result['status'],flush=True)

if __name__=='__main__':
    main()
