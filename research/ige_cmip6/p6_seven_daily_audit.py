#!/usr/bin/env python3
"""P6.1 seven-GCM fail-closed audit: 35 artifacts, 6300 sources, 700 model-years."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from p6_seven_daily import MODELS, WINDOWS, check_reference
from p6_daily_multivariable import MEMBER, SPECS, FIELDS

def load(p):
    return json.loads(p.read_text(encoding='utf8'))

def csv_rows(p):
    with p.open(newline='',encoding='utf8') as f:
        return list(csv.DictReader(f))

def audit(root):
    out={'status':'IN_PROGRESS','models':{},'artifacts':0,'netcdf':0,
         'years':0,'days':0,'p5_month_checks':0,'research_only':True}
    grids=set()
    expected_csv={'joint_daily_raw.csv','model_monthly.csv',
                  'model_annual.csv','model_monthly_climatology.csv'}
    for model in MODELS:
        calendars=set()
        model_grids=set()
        for window,(sc,start,end) in WINDOWS.items():
            path=root/f'ige-p6-{model}-{window}'
            if not path.is_dir():raise ValueError(f'Missing artifact {path}')
            p=load(path/'source_provenance.json')
            q=load(path/'quality_report.json')
            for d in (p,q):
                for k,v in {'status':'PASS','model':model,'member':MEMBER,
                            'scenario':sc,'window':window}.items():
                    if d.get(k)!=v:raise ValueError(f'{model}/{window}: {k} mismatch')
            sources=p['subset_provenance']
            expected={(sc,y,v) for y in range(start,end+1) for v in SPECS}
            observed={(r['scenario'],r['year'],r['variable']) for r in sources}
            if len(sources)!=180 or observed!=expected:raise ValueError('Incomplete source provenance')
            for r in sources:
                if r['model']!=model or r['member']!=MEMBER or len(r['sha256'])!=64:
                    raise ValueError('Invalid source hash/model')
            digests=q['csv_sha256']
            if set(digests)!=expected_csv or digests!=p['csv_sha256']:
                raise ValueError('Invalid output checksum inventory')
            for name,sha in digests.items():
                if hashlib.sha256((path/name).read_bytes()).hexdigest()!=sha:
                    raise ValueError(f'Wrong SHA256 {model}/{window}/{name}')
            daily=csv_rows(path/'joint_daily_raw.csv')
            yearly=csv_rows(path/'model_annual.csv')
            monthly=csv_rows(path/'model_monthly.csv')
            clim=csv_rows(path/'model_monthly_climatology.csv')
            if len(yearly)!=20 or len(monthly)!=240 or len(clim)!=12 or len(daily)!=q['days']:
                raise ValueError('Invalid daily/monthly/annual dimensions')
            yearly_dates={y:[] for y in range(start,end+1)}
            for row in daily:
                if set(row)!=set(FIELDS) or row['model']!=model or row['member']!=MEMBER or row['scenario']!=sc:
                    raise ValueError('Bad daily schema/model/scenario')
                y,m,d=map(int,(row['year'],row['month'],row['day']))
                if y not in yearly_dates or row['date']!=f'{y:04d}-{m:02d}-{d:02d}':
                    raise ValueError('Invalid model-day index')
                yearly_dates[y].append(row['date'])
            if len(q['yearly_qa'])!=20:raise ValueError('Missing yearly QA')
            for record in q['yearly_qa']:
                dates=yearly_dates[record['year']]
                if len(dates)!=record['days'] or dates!=sorted(set(dates)):
                    raise ValueError('Incomplete CF calendar/year')
                model_grids.add((record['grid_lat'],record['grid_lon']))
                calendars.add(record['calendar'])
            if check_reference(model,window,
               [{'ghi_mean_kwh_m2':float(r['ghi_mean_kwh_m2'])} for r in clim])['status']!='PASS':
                raise ValueError('P5 GHI baseline mismatch')
            out['artifacts']+=1;out['netcdf']+=len(sources);out['years']+=20
            out['days']+=len(daily);out['p5_month_checks']+=12
        if len(model_grids)!=1 or len(calendars)!=1:
            raise ValueError(f'Across-window grid/calendar drift: {model}')
        grids.update(model_grids)
        out['models'][model]={'status':'PASS','calendar':next(iter(calendars)),
                              'grid':next(iter(model_grids))}
    if len(grids)!=1 or tuple(out[k] for k in
       ('artifacts','netcdf','years','p5_month_checks'))!=(35,6300,700,420):
        raise ValueError('Cross-model totals mismatch')
    out['grid']=next(iter(grids));out['status']='PASS'
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path('p6_downloaded'))
    p.add_argument('--output',type=Path,default=Path('outputs/p6_seven_closeout.json'))
    a=p.parse_args()
    result={'status':'NOT_RUN'}
    try:result=audit(a.root)
    except Exception as e:
        result={'status':'FAIL','error':str(e)}
        raise
    finally:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
        print('P6.1 Seven-GCM audit',result['status'],flush=True)

if __name__=='__main__':main()
