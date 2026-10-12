#!/usr/bin/env python3
"""IGE P7C.3: original-source 8-GCM change-signal ensemble (Graz NASA NEX-GDDP-CMIP6 v2).

Read source-registered *daily* files; never treat different model/calendar days as paired.
Equal one-member-one-model weighting, 20-year model climatologies, empirical model spread.
Does NOT infer probabilistic predictive intervals or create independent future hourly weather.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, statistics
from pathlib import Path
from collections import defaultdict
from datetime import date
from zipfile import ZipFile
MODELS=('ACCESS-CM2','CanESM5','EC-Earth3','GFDL-ESM4','IPSL-CM6A-LR','MPI-ESM1-2-HR','MRI-ESM2-0','NorESM2-MM')
HIST='historical-1995-2014'
WINDOWS=('ssp245-2040-2059','ssp245-2080-2099','ssp585-2040-2059','ssp585-2080-2099')
KEYS=('tas_c','tasmax_c','tasmin_c','hurs','huss','pr_mm_day','rsds_kwh_m2_day','rlds_kwh_m2_day','sfcWind')
DELTA_KEYS=('temp_delta_C','tasmax_p95_delta_C','hot_days_30_delta_per_year','tropical_nights_20_delta_per_year','pr_delta_pct','ghi_delta_pct','huss_delta_pct','wind_delta_pct','rlds_delta_pct')
LAT_LON=(46.875,15.375)
def digest(blob):return hashlib.sha256(blob).hexdigest()
def mean(xs):return statistics.fmean(xs)
def quantile(xs,p):
    if not xs or not (0<=p<=1):raise ValueError('Quantile inputs invalid')
    a=sorted(xs);u=(len(a)-1)*p;k=int(u)
    return a[k]+(a[min(k+1,len(a)-1)]-a[k])*(u-k)
def csv_text(raw):return list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
def archive_path(root,model,window):return Path(root)/f'IGE_P7C3_SRC_{model}_{window}.zip'
def read_source(path,model,window):
    path=Path(path)
    if not path.is_file():raise ValueError('Missing original GCM source: '+str(path))
    with ZipFile(path) as z:
        if z.testzip() is not None:raise ValueError('Corrupt ZIP source')
        required={'source_provenance.json','quality_report.json','joint_daily_raw.csv'}
        if not required.issubset(z.namelist()):raise ValueError('Missing mandatory immutable source files')
        pro=json.loads(z.read('source_provenance.json'))
        qa=json.loads(z.read('quality_report.json'))
        for q in (pro,qa):
            if q.get('status')!='PASS' or q.get('model')!=model or q.get('member','r1i1p1f1')!='r1i1p1f1' or q.get('window')!=window:
                raise ValueError('Provider model/member/window/quality mismatch')
        if tuple(qa['grid'])!=LAT_LON or tuple(pro.get('site',()))!=(46.983,15.45):
            raise ValueError('Incorrect original grid/site')
        for file,sha in qa['csv_sha256'].items():
            if file not in z.namelist() or digest(z.read(file))!=sha or pro['csv_sha256'].get(file)!=sha:
                raise ValueError('Source original CSV SHA mismatch: '+file)
        rows=csv_text(z.read('joint_daily_raw.csv'))
        if qa.get('days',qa.get('daily_records'))!=len(rows) or qa.get('years',qa.get('year_count'))!=20:raise ValueError('Incorrect window years/days')
        lo,hi=(1995,2014) if window==HIST else map(int,window.split('-')[1:]);lo=int(lo);hi=int(hi)
        scen='historical' if window==HIST else window.split('-')[0]
        seen=set();yearcounts=defaultdict(int);dat=[];last=None;invalid=defaultdict(int)
        for r in rows:
            try:
                dt=date(int(r['year']),int(r['month']),int(r['day']))
            except (ValueError,KeyError) as exc:raise ValueError('Invalid original calendar date') from exc
            if dt in seen or not lo<=dt.year<=hi or r['model']!=model or r['member']!='r1i1p1f1' or r['scenario']!=scen:
                raise ValueError('Duplicate / misidentified original model day')
            if last is not None and not last<dt:raise ValueError('Original dates not strictly increasing')
            seen.add(dt);last=dt;yearcounts[dt.year]+=1
            v={}
            for k in KEYS:
                try:
                    v[k]=float(r[k]) if r[k] not in ('',None) else None
                except (KeyError,TypeError,ValueError) as e:
                    raise ValueError('Malformed original model weather variable: '+k) from e
                if v[k] is not None and not math.isfinite(v[k]):raise ValueError('Nonfinite original source variable: '+k)
            # In P6 a PASS report may legitimately contain a *declared* missing
            # complete source variable, e.g. IPSL-CM6A-LR huss. Never impute.
            for k in KEYS:
                if v[k] is None:
                    if k not in pro.get('missing_source_variables',[]):
                        raise ValueError('Undeclared missing source variable: '+k)
                    invalid[k+'_missing']+=1
            for k in ('tas_c','tasmax_c','tasmin_c','pr_mm_day','rsds_kwh_m2_day','rlds_kwh_m2_day','sfcWind'):
                if v[k] is None:raise ValueError('Required climate signal source absent: '+k)
            if (not v['tasmin_c']-1e-8<=v['tas_c']<=v['tasmax_c']+1e-8 or
                any(v[k]<0 for k in ('pr_mm_day','rsds_kwh_m2_day','rlds_kwh_m2_day','sfcWind'))):
                raise ValueError('Unphysical required source climate variable')
            if v['hurs'] is not None and not 0<=v['hurs']<=100:
                invalid['hurs_outside_0_100']+=1
                v['hurs']=None
            if v['huss'] is not None and not 0<v['huss']<.1:
                raise ValueError('Invalid source specific humidity')
            dat.append({'date':dt,'year':dt.year,'month':dt.month,**v})
        calendar=qa.get('calendar')
        expect=({y:365 for y in range(lo,hi+1)} if calendar in ('365_day','noleap') else
                {y:(366 if date(y,12,31).timetuple().tm_yday==366 else 365) for y in range(lo,hi+1)} if calendar in ('standard','gregorian','proleptic_gregorian') else None)
        if expect is None or dict(yearcounts)!=expect or len(rows)!=sum(expect.values()):raise ValueError('Native model calendar incomplete')
        if calendar in ('noleap','365_day') and any(d['date'].month==2 and d['date'].day==29 for d in dat):raise ValueError('Leap day in noleap GCM')
        prov={'model':model,'window':window,'member':'r1i1p1f1','calendar':calendar,
              'source_zip_sha256':digest(path.read_bytes()),'daily_csv_sha256':qa['csv_sha256']['joint_daily_raw.csv'],
              'original_days':len(rows),'original_years':20,'source_grid':LAT_LON,'qa':'PASS','original_variable_census':dict(invalid), 'declared_missing_source_variables':pro.get('missing_source_variables',[])}
        return dat,prov

def summary(data):
    n=len(data);years=sorted({x['year'] for x in data})
    if len(years)!=20:raise ValueError('Required 20 years')
    avg=lambda k:mean([x[k] for x in data]); hot=lambda k,threshold:sum(x[k]>=threshold for x in data)/20
    annual_temperature=[mean([x['tas_c'] for x in data if x['year']==y]) for y in years]
    return {'annual_T_C':mean(annual_temperature),
      'tasmax_p95_C':quantile([x['tasmax_c'] for x in data],.95),
      'annual_hot_days_30':hot('tasmax_c',30.),
      'annual_tropical_nights_20':hot('tasmin_c',20.),
      # 365-day equivalent permits cross-calendar comparisons of 7300 and 7305 source days.
      'annual_ghi_kwh_m2_365_equivalent':avg('rsds_kwh_m2_day')*365,
      'annual_pr_mm_365_equivalent':avg('pr_mm_day')*365,
      'annual_rlds_kwh_m2_365_equivalent':avg('rlds_kwh_m2_day')*365,
      'avg_huss_kg_kg':(mean([x['huss'] for x in data if x['huss'] is not None]) if any(x['huss'] is not None for x in data) else None), 'avg_hurs_pct':(mean([x['hurs'] for x in data if x['hurs'] is not None]) if any(x['hurs'] is not None for x in data) else None),'avg_wind_ms':avg('sfcWind'),
      'interannual_T_sd_C':statistics.stdev(annual_temperature),'source_days':n}
def delta(hist,fun):
    def ratio(f,k):
        old=hist[k];new=fun[k]
        if old<=0:raise ValueError('Ratio undefined: '+k)
        return 100*(new/old-1)
    return {'temp_delta_C':fun['annual_T_C']-hist['annual_T_C'],
            'tasmax_p95_delta_C':fun['tasmax_p95_C']-hist['tasmax_p95_C'],
            'hot_days_30_delta_per_year':fun['annual_hot_days_30']-hist['annual_hot_days_30'],
            'tropical_nights_20_delta_per_year':fun['annual_tropical_nights_20']-hist['annual_tropical_nights_20'],
            'pr_delta_pct':ratio(fun,'annual_pr_mm_365_equivalent'),
            'ghi_delta_pct':ratio(fun,'annual_ghi_kwh_m2_365_equivalent'),
            'huss_delta_pct':(ratio(fun,'avg_huss_kg_kg') if hist['avg_huss_kg_kg'] is not None and fun['avg_huss_kg_kg'] is not None else None),
            'wind_delta_pct':ratio(fun,'avg_wind_ms'),
            'rlds_delta_pct':ratio(fun,'annual_rlds_kwh_m2_365_equivalent')}
def monthly_signals(hist,fun,model,win):
    rows=[]
    for m in range(1,13):
        h=[x for x in hist if x['month']==m];f=[x for x in fun if x['month']==m]
        if len(h)<560 or len(f)<560:raise ValueError('Incomplete monthly source')
        av=lambda r,k:mean([x[k] for x in r]);rat=lambda k:av(f,k)/av(h,k)
        dtr=lambda a:mean([x['tasmax_c']-x['tasmin_c'] for x in a])
        rows.append({'model':model,'window':win,'month':m,'tas_delta_C':av(f,'tas_c')-av(h,'tas_c'),
          'dtr_ratio':dtr(f)/dtr(h),'huss_ratio':(rat('huss') if any(x['huss'] is not None for x in h) and any(x['huss'] is not None for x in f) else None),'pr_ratio':rat('pr_mm_day'),
          'ghi_ratio':rat('rsds_kwh_m2_day'),'rlds_ratio':rat('rlds_kwh_m2_day'),
          'wind_ratio':rat('sfcWind')})
    return rows

def aggregate(rows):
    out=[]
    for w in WINDOWS:
        r=[x for x in rows if x['window']==w]
        if len(r)!=len(MODELS) or {x['model'] for x in r}!=set(MODELS):raise ValueError('Incomplete ensemble')
        entry={'window':w,'gcm_count':len(r),'quantile_type':'EMPIRICAL_INTERMODEL_NOT_PROBABILISTIC'}
        for k in DELTA_KEYS:
            x=[float(m[k]) for m in r if m[k] is not None]
            if len(x)<6:raise ValueError('Insufficient source availability for ensemble metric: '+k)
            entry[k+'_n_models']=len(x)
            entry[k+'_models_missing']=';'.join(m['model'] for m in r if m[k] is None)
            entry.update({k+'_mean':mean(x),k+'_p10':quantile(x,.10),k+'_p50':quantile(x,.50),k+'_p90':quantile(x,.90),k+'_min':min(x),k+'_max':max(x),k+'_range':max(x)-min(x)})
        ranked=sorted(r,key=lambda v:float(v['temp_delta_C']))
        entry['canesm5_temp_rank_ascending_1_to_8']=1+next(i for i,x in enumerate(ranked) if x['model']=='CanESM5')
        entry['coldest_delta_model']=ranked[0]['model'];entry['warmest_delta_model']=ranked[-1]['model']
        entry['representative_cool_model']=ranked[1]['model'];entry['representative_median_model']=ranked[3]['model'];entry['representative_warm_model']=ranked[-2]['model']
        out.append(entry)
    return out

def writecsv(path,records):
    if not records:raise ValueError('No output rows')
    with Path(path).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=records[0].keys());w.writeheader();w.writerows(records)
def run(root,out):
    out=Path(out);out.mkdir(exist_ok=True,parents=True)
    rows=[];monthly=[];sources=[];annual=[]
    for m in MODELS:
        h,ph=read_source(archive_path(root,m,HIST),m,HIST)
        hist=summary(h);sources.append(ph)
        for w in WINDOWS:
            f,pf=read_source(archive_path(root,m,w),m,w)
            ff=summary(f);metrics=delta(hist,ff)
            rows.append({'model':m,'window':w,'member':'r1i1p1f1',
               **metrics,'historical_annual_T_C':hist['annual_T_C'],
               'future_annual_T_C':ff['annual_T_C'],
               'historical_hot_days30_per_year':hist['annual_hot_days_30'],
               'future_hot_days30_per_year':ff['annual_hot_days_30'],
               'historical_annual_ghi_kwh_m2':hist['annual_ghi_kwh_m2_365_equivalent'],
               'future_annual_ghi_kwh_m2':ff['annual_ghi_kwh_m2_365_equivalent'],
               'historical_interannual_T_sd_C':hist['interannual_T_sd_C'],
               'future_interannual_T_sd_C':ff['interannual_T_sd_C']})
            annual.append({'model':m,'window':w,**ff})
            monthly.extend(monthly_signals(h,f,m,w))
            sources.append(pf)
    ens=aggregate(rows)
    writecsv(out/'p7c3_32_model_scenario_climate_signals.csv',rows)
    writecsv(out/'p7c3_384_monthly_model_signals.csv',monthly)
    writecsv(out/'p7c3_4window_empirical_ensemble_uncertainty.csv',ens)
    writecsv(out/'p7c3_32_future_absolute_climate_metrics.csv',annual)
    original_sources={x['model']+'_'+x['window']:x for x in sources}
    audit={'phase':'P7C.3','source':'original NASA NEX-GDDP-CMIP6 v2 P6 immutable quality-accepted daily archives',
       'research_status':'SOURCE_AUDITED_8GCM_4WINDOW_CLIMATE_SIGNAL_ENSEMBLE',
       'production_epw_ready':False,'future_hourly_EPWs_generated_in_this_run':False,
       'n_models':len(MODELS),'n_windows':len(WINDOWS),'n_original_archives':len(sources),
       'n_scenario_members':len(rows),'n_monthly_model_signals':len(monthly),'specific_humidity_source_availability':'7/8 model members; IPSL-CM6A-LR declares complete source huss unavailable',
       'member_per_model':'r1i1p1f1','model_weighting':'equal weight each distinct GCM; 1 ensemble member per GCM',
       'empirical_quantile_definition':'linear interpolation over 8 distinct GCM values; NOT probability, CI, coverage, or comprehensive GCM uncertainty',
       'historical_window':HIST,'future_windows':WINDOWS,
       'calendar_policy':'original noleap/Gregorian 20-year daily samples; annual flux totals normalized from daily mean to 365 days; EPW calendar conversion not applied',
       'canesm5_is_not_ensemble_median_by_default':True,
       'other_limits':['Only eight selected models with one realization each, no model independence guarantees',
         'NASA downscaled BCSD daily output; original bias correction retained (no additional calibration at this stage)',
         'One geographic grid centered on Graz; not spatially independent validation',
         'Original model window year sequences not event-paired to a contemporary EPW calendar',
         'Changes in daily tasmax/tasmin exceedances are GCM daily metrics, not 8760 EPW future hot hours',
         'No model performance skill weighting and no future observations',
         'No EnergyPlus run and no radiation partition independent validation'],
       'source_sha256':original_sources,'ensemble_windows':ens,
       'derived_sha256':{p.name:digest(p.read_bytes()) for p in out.glob('*.csv')}}
    (out/'p7c3_source_ensemble_science_audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
    return audit
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--original-zip-root',required=True);a.add_argument('--out',required=True)
    x=a.parse_args();a=run(x.original_zip_root,x.out)
    for e in a['ensemble_windows']:
        print(e['window'],'T med',round(e['temp_delta_C_p50'],3),'[p10 p90]',round(e['temp_delta_C_p10'],3),round(e['temp_delta_C_p90'],3),'CanESM5 rank',e['canesm5_temp_rank_ascending_1_to_8'],flush=True)
    print('P7C.3 original 40 source archives, 32 signals, 384 month model signals PASS',flush=True)