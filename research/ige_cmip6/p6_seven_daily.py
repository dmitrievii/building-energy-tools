#!/usr/bin/env python3
"""P6.1: synchronized daily NASA NEX-GDDP-CMIP6 for seven further GCMs.

Extends the validated ACCESS-CM2 process without altering it.
A single invocation is bound to one model and one CF calendar/scenario window.
Research data only. No bias correction, synthetic hourly data, or EPW.
"""
from __future__ import annotations
import argparse
import csv
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import statistics
import time
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from p6_daily_multivariable import (
    BASE, SITE, MEMBER, MODEL as BASE_MODEL, SPECS, FIELDS, decode,
    download, strict_join,
)
from p6_access_full_period import (
    WINDOWS, MONTHLY_FIELDS, ANNUAL_FIELDS, CLIMO_FIELDS,
    write_csv, sha256, summarize_daily,
)

REFERENCE = Path(__file__).with_name('p6_seven_gcm_p5_ghi_reference.json')
MODELS = ('CanESM5','EC-Earth3','GFDL-ESM4','IPSL-CM6A-LR',
          'MPI-ESM1-2-HR','MRI-ESM2-0','NorESM2-MM')
SMOKE = {'historical-2014':('historical',2014,2014),
         'ssp245-2050':('ssp245',2050,2050)}

def check_reference(model, window, clim):
    ref=json.loads(REFERENCE.read_text(encoding='utf8'))
    if ref['scale']!=100000 or ref['order']!=list(WINDOWS) or set(ref['models'])!=set(MODELS):
        raise ValueError('P5 frozen source reference is inconsistent')
    expected=ref['models'][model][ref['order'].index(window)]
    if len(expected)!=12 or len(clim)!=12:
        raise ValueError('Incomplete P5 reference')
    diff=[abs(float(clim[m-1]['ghi_mean_kwh_m2'])-expected[m-1]/ref['scale'])
          for m in range(1,13)]
    if max(diff)>1e-4:
        raise ValueError(f'P5 {model}/{window} GHI mismatch: max {max(diff)} kWh/m²/month')
    return {'status':'PASS','months':12,'tolerance_kwh_m2':1e-4,
            'max_abs_error_kwh_m2':max(diff),
            'reference':'P5 CLOSED raw model rsds 20-year monthly means'}

def nasa_catalog(model,scenario,variable):
    url=f'{BASE}/thredds/catalog/AMES/NEX/GDDP-CMIP6/{model}/{scenario}/{MEMBER}/{variable}/catalog.xml'
    root=ET.fromstring(download(url,2000000))
    available={}
    for el in root.iter():
        if not el.tag.endswith('dataset'):continue
        name=el.attrib.get('name','')
        path=el.attrib.get('urlPath','')
        if path and name.endswith('_v2.0.nc'):
            y=name[:-len('_v2.0.nc')].rsplit('_',1)[-1]
            if len(y)==4 and y.isdigit():available[int(y)]=path
    if not available:raise ValueError(f'NASA empty catalog: {model}/{scenario}/{variable}')
    return available

def nasa_fetch(model,scenario,year,variable,path):
    expected=f'AMES/NEX/GDDP-CMIP6/{model}/{scenario}/{MEMBER}/{variable}/'
    if not path.startswith(expected):raise ValueError(f'Catalog directory mismatch {path}')
    url=f'{BASE}/thredds/ncss/grid/{path}?'+urlencode({
        'var':variable,'north':'47.11','south':'46.88','west':'15.33','east':'15.59',
        'time_start':f'{year}-01-01T12:00:00Z',
        'time_end':f'{year}-12-31T12:00:00Z',
        'accept':'netcdf3','addLatLon':'true'})
    raw=download(url)
    payload=decode(raw,variable,year)
    provenance={'model':model,'member':MEMBER,'scenario':scenario,'year':year,
                'variable':variable,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),
                'bytes':len(raw),'calendar':payload['calendar'],
                'units':payload['unit'],'lat':payload['lat'],
                'lon':payload['lon'],'days':len(payload['days'])}
    return payload,provenance

def execute(model,window,workers,root,smoke=False):
    if model not in MODELS:raise ValueError(f'Unapproved model: {model}')
    if window not in (SMOKE if smoke else WINDOWS):
        raise ValueError(f'Unsupported window: {window}')
    scenario,first,last=(SMOKE if smoke else WINDOWS)[window]
    years=tuple(range(first,last+1))
    out=root/model/window
    out.mkdir(parents=True,exist_ok=True)
    provenance={'status':'IN_PROGRESS','stage':'P6.1','model':model,'member':MEMBER,
                'window':window,'scenario':scenario,'start_year':first,
                'end_year':last,'variables':list(SPECS),'site':SITE,
                'subset_provenance':[],'research_only':True}
    t0=time.monotonic()
    try:
        catalogs={v:nasa_catalog(model,scenario,v) for v in SPECS}
        jobs=[(model,scenario,y,v,catalogs[v][y]) for y in years for v in SPECS
              if y in catalogs[v]]
        if len(jobs)!=len(years)*len(SPECS):
            raise ValueError(f'Incomplete catalogs: requested {len(years)*9}, found {len(jobs)}')
        result={}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending={pool.submit(nasa_fetch,*job):(job[2],job[3]) for job in jobs}
            for future in as_completed(pending):
                key=pending[future]
                payload,prov=future.result()
                if key in result:raise ValueError('Duplicate annual NASA variable')
                result[key]=payload
                provenance['subset_provenance'].append(prov)
                print('SOURCE',model,scenario,key[0],key[1],prov['days'],prov['sha256'][:12],flush=True)
        rows=[];yearqa=[];coords=set();calendars=set()
        for y in years:
            joined,qa=strict_join({v:result[y,v] for v in SPECS},scenario,y)
            # strict_join is the validated ACCESS-CM2 mathematical joining contract;
            # only its output model label is rebound to this single immutable job model.
            if any(r['model']!=BASE_MODEL for r in joined):
                raise ValueError('Unexpected provenance label from shared join')
            for row in joined:row['model']=model
            rows.extend(joined)
            qa['model']=model
            yearqa.append(qa)
            coords.add((qa['grid_lat'],qa['grid_lon']))
            calendars.add(qa['calendar'])
        if len(coords)!=1 or len(calendars)!=1:
            raise ValueError(f'CF calendar or grid varies within {model}/{window}')
        if len(rows)!=sum(r['days'] for r in yearqa):
            raise ValueError('Annual day-count closure failed')
        if len(set((r['scenario'],r['year'],r['date']) for r in rows))!=len(rows):
            raise ValueError('Repeated model-day')
        monthly,annual,climo=summarize_daily(rows,window,scenario,years)
        p5check=check_reference(model,window,climo) if not smoke else {'status':'NOT_APPLICABLE_SMOKE'}
        files={
            'joint_daily_raw.csv':(FIELDS,rows),
            'model_monthly.csv':(MONTHLY_FIELDS,monthly),
            'model_annual.csv':(ANNUAL_FIELDS,annual),
            'model_monthly_climatology.csv':(CLIMO_FIELDS,climo),
        }
        checksums={}
        for name,(columns,records) in files.items():
            write_csv(out/name,columns,records)
            checksums[name]=sha256(out/name)
        qa={'status':'PASS','model':model,'member':MEMBER,'window':window,
            'scenario':scenario,'source_count':len(result),'years':len(years),
            'days':len(rows),'monthly_rows':len(monthly),
            'annual_rows':len(annual),'climatology_rows':len(climo),
            'grid':list(coords)[0],'calendar':list(calendars)[0],
            'yearly_qa':yearqa,'p5_ghi_regression':p5check,
            'csv_sha256':checksums}
        (out/'quality_report.json').write_text(json.dumps(qa,indent=2)+'\n',encoding='utf8')
        provenance.update({'status':'PASS','source_count':len(result),
                           'days':len(rows),'csv_sha256':checksums})
        return qa
    except Exception as e:
        provenance['status']='FAIL'
        provenance['error']=f'{type(e).__name__}: {e}'
        raise
    finally:
        provenance['subset_provenance'].sort(key=lambda z:(z['year'],z['variable']))
        provenance['elapsed_seconds']=round(time.monotonic()-t0,2)
        (out/'source_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf8')
        print('P6.1',model,window,provenance['status'],
              'NASA subsets',len(provenance['subset_provenance']),flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',choices=MODELS,required=True)
    p.add_argument('--window',required=True)
    p.add_argument('--smoke',action='store_true')
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--output-root',type=Path,default=Path('outputs/p6_seven_daily'))
    a=p.parse_args()
    if a.workers not in (1,2,3,4):p.error('workers must be in range 1..4')
    execute(a.model,a.window,a.workers,a.output_root,a.smoke)

if __name__=='__main__':main()
