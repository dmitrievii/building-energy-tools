#!/usr/bin/env python3
"""IGE P6.1 research pilot: nine synchronized daily NASA NEX-GDDP-CMIP6 variables.

No local calibration, hourly weather generation, engineering validation or EPW.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

MODEL = 'ACCESS-CM2'
MEMBER = 'r1i1p1f1'
BASE = 'https://ds.nccs.nasa.gov'
SITE = (46.983, 15.450)
YEARS = (('historical', 2014), ('ssp245', 2050))
SPECS = {
    'tas': ('K', 180., 350.), 'tasmax': ('K', 180., 355.),
    'tasmin': ('K', 170., 350.), 'hurs': ('%', 0., 100.),
    'huss': ('kg kg-1', 0., .06), 'pr': ('kg m-2 s-1', 0., .05),
    'rsds': ('W m-2', 0., 750.), 'rlds': ('W m-2', 0., 750.),
    'sfcWind': ('m s-1', 0., 120.),
}
UNITS = {
    'K': {'k','kelvin','degreeskelvin'},
    '%': {'%','percent','percentage'},
    'kg kg-1': {'kgkg-1','kg/kg','1','kgkg**-1','kgkg^-1'},
    'kg m-2 s-1': {'kgm-2s-1','kg/m2/s','kgm**-2s**-1','kgm^-2s^-1'},
    'W m-2': {'wm-2','w/m2','wm**-2','wm^-2','wm−2','wm-²'},
    'm s-1': {'ms-1','m/s','ms**-1','ms^-1'}
}
FIELDS = ['scenario','year','month','day','date','model','member',
          *SPECS,'tas_c','tasmax_c','tasmin_c','pr_mm_day',
          'rsds_kwh_m2_day','rlds_kwh_m2_day']

def leap_year(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)

def validate_unit(variable, unit):
    norm = str(unit).lower().strip().replace(' ','').replace('\u00a0','')
    expected = SPECS[variable][0]
    if norm not in UNITS[expected]:
        raise ValueError(f'{variable}: noncanonical unit {unit!r}; expected {expected}')

def validate_value(variable, value):
    v = float(value)
    lo,hi = SPECS[variable][1:]
    if not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f'{variable}: invalid daily value {value!r}')
    return v

def strict_join(payloads, scenario, year, allowed_missing=()):
    """Join by identical dated CF time axis and nearest-point grid; reject mismatches."""
    missing = frozenset(allowed_missing)
    if not missing <= set(SPECS) or set(payloads) != set(SPECS)-missing:
        raise ValueError(f'Nine variables required unless explicit source exception: missing={set(SPECS)-set(payloads)}, permitted={set(missing)}')
    variables = tuple(v for v in SPECS if v not in missing)
    dates = None
    series = {}
    coords, calendars = set(), set()
    for variable in variables:
        p = payloads[variable]
        validate_unit(variable, p['unit'])
        days = [tuple(map(int, d)) for d in p['days']]
        values = [validate_value(variable, v) for v in p['values']]
        if not days or len(days)!=len(values) or len(set(days))!=len(days):
            raise ValueError(f'{variable}: repeated or missing daily values')
        if days != sorted(days) or any(y != year for y,m,d in days):
            raise ValueError(f'{variable}: unsorted/mismatched year')
        if dates is None: dates = days
        elif dates != days:
            raise ValueError(f'{variable}: misaligned daily time axis')
        coords.add((round(float(p['lat']),7),round(float(p['lon']),7)))
        cal = str(p['calendar']).lower()
        cal = 'gregorian' if cal in ('standard','gregorian','proleptic_gregorian') else cal
        if cal not in ('gregorian','noleap','365_day','360_day'):
            raise ValueError(f'Unsupported CF calendar: {cal}')
        calendars.add('noleap' if cal=='365_day' else cal)
        series[variable] = values
    if len(coords)!=1: raise ValueError('Mixed grid locations')
    if len(calendars)!=1: raise ValueError('Mixed CF calendars')
    calendar = next(iter(calendars))
    if calendar=='360_day':
        expected = [(year,m,d) for m in range(1,13) for d in range(1,31)]
    elif calendar=='noleap':
        expected = [(year,(dt.date(2001,1,1)+dt.timedelta(days=i)).month,
                           (dt.date(2001,1,1)+dt.timedelta(days=i)).day) for i in range(365)]
    else:
        expected = [(day.year,day.month,day.day) for day in
                    (dt.date(year,1,1)+dt.timedelta(days=i)
                     for i in range(366 if leap_year(year) else 365))]
    if dates!=expected: raise ValueError('Incomplete CF daily calendar/year; missing/extra day')
    rows=[]
    for i,(yy,mm,dd) in enumerate(dates):
        r={'scenario':scenario,'year':yy,'month':mm,'day':dd,
           'date':f'{yy:04d}-{mm:02d}-{dd:02d}','model':MODEL,'member':MEMBER}
        # The blank represents an unavailable source variable, not observed zero or an estimate.
        r.update({v:series[v][i] if v in series else '' for v in SPECS})
        if r['tasmin']>r['tas']+.25 or r['tas']>r['tasmax']+.25:
            raise ValueError(f'{r["date"]}: tas lies outside daily extrema')
        for v in ('tas','tasmin','tasmax'):r[v+'_c']=r[v]-273.15
        r['pr_mm_day']=r['pr']*86400
        r['rsds_kwh_m2_day']=r['rsds']*.024
        r['rlds_kwh_m2_day']=r['rlds']*.024
        rows.append(r)
    lat,lon=next(iter(coords))
    return rows, {'scenario':scenario,'year':year,'calendar':calendar,'days':len(rows),
                  'grid_lat':lat,'grid_lon':lon,
                  'first_date':rows[0]['date'],'last_date':rows[-1]['date'],
                  'available_variables':list(variables),'missing_variables':sorted(missing)}

def download(url, max_bytes=8000000):
    errors=[]
    for attempt in range(4):
        try:
            with urlopen(Request(url,headers={'User-Agent':'IGE-Climate-Engine-P6.1-research'}),timeout=110) as f:
                data=f.read(max_bytes+1)
                if f.status!=200 or not data or len(data)>max_bytes:
                    raise ValueError(f'HTTP={f.status}, len={len(data)}')
            return data
        except Exception as e:
            errors.append(str(e))
            if attempt<3: time.sleep(3*(attempt+1))
    raise RuntimeError(f'NASA source failed: {url} {errors}')

def catalog(scenario,variable):
    u=f'{BASE}/thredds/catalog/AMES/NEX/GDDP-CMIP6/{MODEL}/{scenario}/{MEMBER}/{variable}/catalog.xml'
    root=ET.fromstring(download(u,2000000))
    result={}
    for item in root.iter():
        if not item.tag.endswith('dataset'):continue
        name=item.attrib.get('name','')
        path=item.attrib.get('urlPath','')
        if name.endswith('_v2.0.nc') and path:
            y=name[:-len('_v2.0.nc')].rsplit('_',1)[-1]
            if len(y)==4 and y.isdigit():result[int(y)]=path
    if not result:raise RuntimeError(f'Empty catalog: {scenario}/{variable}')
    return result

def decode(raw,var,year):
    import netCDF4
    import numpy as np
    if not raw.startswith(b'CDF'):raise ValueError('NASA subset not NetCDF3')
    with tempfile.NamedTemporaryFile(suffix='.nc') as fp:
        fp.write(raw);fp.flush()
        with netCDF4.Dataset(fp.name) as ds:
            if var not in ds.variables:raise ValueError(f'Missing {var}')
            f=ds.variables[var]
            units=str(getattr(f,'units',''))
            validate_unit(var,units)
            t=ds.variables['time']
            cal=str(getattr(t,'calendar','standard'))
            dates=netCDF4.num2date(t[:],t.units,calendar=cal,only_use_cftime_datetimes=True)
            days=[(int(d.year),int(d.month),int(d.day)) for d in dates]
            lat=ds.variables['lat'];lon=ds.variables['lon']
            lats=np.asarray(lat[:],dtype=float).reshape(-1)
            lons=np.asarray(lon[:],dtype=float).reshape(-1)
            target_lon=SITE[1]%360 if np.max(lons)>180 else SITE[1]
            iy=int(np.argmin(np.abs(lats-SITE[0])))
            ix=int(np.argmin(np.abs(lons-target_lon)))
            yl=float(lats[iy]);xl=float(lons[ix])
            if abs(yl-SITE[0])>.3 or abs(xl-target_lon)>.3:
                raise ValueError('Wrong NASA grid point')
            axes=f.dimensions
            if len(axes)!=3 or set(axes)!={t.dimensions[0],lat.dimensions[0],lon.dimensions[0]}:
                raise ValueError(f'Unexpected {var} dimensions: {axes}')
            index=tuple(slice(None) if d==t.dimensions[0] else iy if d==lat.dimensions[0] else ix for d in axes)
            vals=np.asarray(np.ma.filled(f[index],np.nan),dtype=float).reshape(-1)
            if len(vals)!=len(days) or any(y!=year for y,m,d in days):
                raise ValueError('Wrong or incomplete time data')
            return {'days':days,'values':vals.tolist(),'unit':units,
                    'calendar':cal,'lat':yl,'lon':xl}

def fetch_one(scenario,year,var,path):
    prefix=f'AMES/NEX/GDDP-CMIP6/{MODEL}/{scenario}/{MEMBER}/{var}/'
    if not path.startswith(prefix):raise ValueError('NASA source path mismatch')
    u=f'{BASE}/thredds/ncss/grid/{path}?'+urlencode({
        'var':var,'north':'47.11','south':'46.88','west':'15.33','east':'15.59',
        'time_start':f'{year}-01-01T12:00:00Z','time_end':f'{year}-12-31T12:00:00Z',
        'accept':'netcdf3','addLatLon':'true'})
    raw=download(u)
    payload=decode(raw,var,year)
    prov={'scenario':scenario,'year':year,'variable':var,'url':u,
          'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
          'calendar':payload['calendar'],'units':payload['unit'],
          'grid_lat':payload['lat'],'grid_lon':payload['lon'],'days':len(payload['days'])}
    return payload,prov

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--output',type=Path,default=Path('outputs/p6_daily_access_cm2_2014_2050'))
    args=p.parse_args()
    if not 1<=args.workers<=4:p.error('workers must be 1..4')
    args.output.mkdir(parents=True,exist_ok=True)
    source={'status':'IN_PROGRESS','stage':'P6.1','model':MODEL,'member':MEMBER,
            'site':SITE,'years':YEARS,'variables':list(SPECS),'subsets':[],
            'scientific_status':'RESEARCH PILOT; NOT VALIDATED EPW'}
    try:
        catalogues={(s,v):catalog(s,v) for s in {x[0] for x in YEARS} for v in SPECS}
        jobs=[]
        for s,y in YEARS:
            for v in SPECS:
                if y not in catalogues[s,v]:raise ValueError(f'No catalog entry {s}/{y}/{v}')
                jobs.append((s,y,v,catalogues[s,v][y]))
        data={}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            running={pool.submit(fetch_one,*j):j[:3] for j in jobs}
            for future in as_completed(running):
                key=running[future]
                payload,prov=future.result()
                data[key]=payload
                source['subsets'].append(prov)
                print('SOURCE',key,prov['days'],prov['sha256'][:12],flush=True)
        rows=[];qa=[]
        for s,y in YEARS:
            r,q=strict_join({v:data[s,y,v] for v in SPECS},s,y)
            rows.extend(r);qa.append(q)
        csv_path=args.output/'joint_daily_raw.csv'
        with csv_path.open('w',newline='',encoding='utf8') as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
        source['subsets'].sort(key=lambda p:(p['scenario'],p['year'],p['variable']))
        source['csv_sha256']=hashlib.sha256(csv_path.read_bytes()).hexdigest()
        source['record_count']=len(rows)
        (args.output/'daily_qa.json').write_text(json.dumps({'status':'PASS','groups':qa},indent=2)+'\n')
        source['status']='PASS'
    except Exception as e:
        source['status']='FAIL';source['error']=f'{type(e).__name__}: {e}'
        raise
    finally:
        source['finished_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
        (args.output/'source_provenance.json').write_text(json.dumps(source,indent=2)+'\n')
        print('P6.1 status',source['status'],'subsets',len(source['subsets']),flush=True)

if __name__=='__main__':main()
