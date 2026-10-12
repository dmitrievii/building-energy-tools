#!/usr/bin/env python3
"""IGE P7C.2 independent *method* benchmark, NOT verification against observed future climate.

User-provided Meteonorm files remain local and are never redistributed. This program
writes only aggregate metrics and SHA256 provenance. RCP and SSP experiments are
non-equivalent; comparative contrasts are explicitly tagged unmatched.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean
from zipfile import ZipFile

COLUMNS = 35
N_HOURS = 8760
COL = {'temp':6,'dewpoint':7,'rh':8,'pressure':9,'ghi':13,'dni':14,'dhi':15,
       'wind_dir':20,'wind_speed':21,'rain':33}
SENTINELS = {'temp':99.9,'dewpoint':99.9,'rh':999.,'pressure':999999.,
             'ghi':9999.,'dni':9999.,'dhi':9999.,'wind_dir':999.,'wind_speed':999.,'rain':999.}
SITE = {'Graz':'Graz','Wien-Hohe_Warte':'Vienna','Tripoli':'Tripoli'}
MONTH_DAYS = (31,28,31,30,31,30,31,31,30,31,30,31)
GRAZ_IGE = {'ssp245-2040-2059':'ssp245','ssp245-2080-2099':'ssp245',
            'ssp585-2040-2059':'ssp585','ssp585-2080-2099':'ssp585'}
MN_COMPARISONS = (
    ('ssp245-2040-2059','Graz-hour_RCP4.5_2050_seed1.epw','nominal_4.5_2050_different_forcing_families'),
    ('ssp585-2040-2059','Graz-hour_RCP8.5_2050_seed1.epw','nominal_8.5_2050_different_forcing_families'),
    ('ssp585-2080-2099','Graz-hour_RCP8.5_2100_seed1.epw','late_century_8.5_different_periods_and_forcing_families'),
)


def sha256(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def numeric(row, key):
    n=COL[key]
    try: v=float(row[n])
    except (ValueError,IndexError,TypeError): return None
    if not math.isfinite(v) or v>=SENTINELS[key] or (key in ('ghi','dni','dhi','rain','wind_speed') and v<0):
        return None
    return v


def read_epw(raw:bytes,name:str)->dict:
    text=raw.decode('utf-8-sig',errors='strict')
    content=list(csv.reader(io.StringIO(text)))
    if len(content)!=N_HOURS+8 or not content[0] or content[0][0]!='LOCATION':
        raise ValueError(f'{name}: invalid header or expected EPW 8760 length')
    loc=content[0]
    if len(loc)<10:raise ValueError(f'{name}: LOCATION incomplete')
    records=content[8:]
    if any(len(r)!=COLUMNS for r in records):raise ValueError(f'{name}: non-35 EPW record')
    hours=defaultdict(list)
    year=None
    for i,row in enumerate(records):
        y=int(row[0]); month=int(row[1]); day=int(row[2]); hour=int(row[3]); minute=int(row[4]);
        if year is None: year=y
        if year!=y:raise ValueError(f'{name}: multi-year EPW blocked')
        expected=date(2001,1,1)+timedelta(days=i//24)
        if (month,day,hour,minute)!=(expected.month,expected.day,i%24+1,60):
            raise ValueError(f'{name}: wrong EPW non-leap timestamp @ {i}: {month}/{day}/{hour}:{minute}')
        for key in COL:hours[key].append(numeric(row,key))
    for key in ('temp','dewpoint','rh','pressure','ghi','dni','dhi'):
        if any(v is None for v in hours[key]):raise ValueError(f'{name}: critical field {key} has missing')
    for key,low,high in (('temp',-90,65),('rh',0,100),('pressure',30000,115000),
                         ('ghi',0,1800),('dni',0,1600),('dhi',0,1400)):
        if any(not low<=x<=high for x in hours[key]):
            raise ValueError(f'{name}: field {key} outside sanity envelope')
    return {'name':name,'sha256':sha256(raw),'location':loc,'year_label':year,'hours':hours}


def percentiles(v):
    s=sorted(v)
    def q(p):
        idx=(len(s)-1)*p; a=int(idx); f=idx-a
        return s[a]*(1-f)+s[min(a+1,len(s)-1)]*f
    return {f'p{int(p*100):02d}':q(p) for p in (.01,.05,.5,.95,.99)}


def q_air(temp,rh,pressure):
    # Buck saturation formula, physically bounded station pressure q [kg/kg].
    es=611.21*math.exp((18.678-temp/234.5)*(temp/(257.14+temp)))
    pv=es*rh/100
    if pv>=pressure:raise ValueError('Vapor partial pressure >= total pressure')
    return 0.621945*pv/(pressure-0.378055*pv)


def max_run(flags):
    a=b=0
    for f in flags:
        a=a+1 if f else 0;b=max(a,b)
    return b


def ks_distance(a,b):
    """Two-sample empirical KS statistic (no paired-day assumption)."""
    a=sorted(a);b=sorted(b);ia=ib=0;mx=0.;na=len(a);nb=len(b)
    while ia<na or ib<nb:
        if ia==na:next_value=b[ib]
        elif ib==nb:next_value=a[ia]
        else:next_value=min(a[ia],b[ib])
        while ia<na and a[ia]<=next_value:ia+=1
        while ib<nb and b[ib]<=next_value:ib+=1
        mx=max(mx,abs(ia/na-ib/nb))
    return mx


def pearson(a,b):
    if len(a)!=len(b) or len(a)<3:raise ValueError('Pearson inputs incomplete')
    ma=fmean(a);mb=fmean(b)
    aa=[x-ma for x in a];bb=[y-mb for y in b]
    den=math.sqrt(sum(x*x for x in aa)*sum(y*y for y in bb))
    return sum(x*y for x,y in zip(aa,bb))/den if den>1e-18 else None


def wind_rose(direction,speed):
    counters=[0]*8; valid=0;calm=0
    for d,s in zip(direction,speed):
        if s is None:continue
        if s<.2:calm+=1;continue
        if d is None:continue
        if not 0<=d<=360:raise ValueError('Wind azimuth out of bounds')
        counters[int(((d%360)+22.5)//45)%8]+=1;valid+=1
    return {'valid_hours':valid,'calm_hours':calm,'fraction':[x/valid if valid else None for x in counters]}


def metric(epw):
    d=epw['hours'];t=d['temp'];rh=d['rh'];p=d['pressure'];dew=d['dewpoint'];ghi=d['ghi']
    q=[q_air(*trp) for trp in zip(t,rh,p)]
    observed_rh_jumps=[abs(a-b)>20 for a,b in zip(rh[1:],rh[:-1])]
    # Hours >=1°C above dewpoint are candidate consistency violation, tolerance to EPW rounding.
    violations=sum(td>ta+.6 for td,ta in zip(dew,t))
    result={'file':epw['name'],'sha256':epw['sha256'],'year_label':epw['year_label'],
        'location_name':epw['location'][1],'location_lat':float(epw['location'][6]),
        'location_lon':float(epw['location'][7]), 'data_source_label':epw['location'][4],
        'T_mean_C':fmean(t),'T_min_C':min(t),'T_max_C':max(t),
        'T_p01_C':percentiles(t)['p01'],'T_p95_C':percentiles(t)['p95'],
        'T_p99_C':percentiles(t)['p99'],
        'hot_hours_T30':sum(v>=30 for v in t),'extreme_hot_hours_T35':sum(v>=35 for v in t),
        'longest_hot_run_T30_h':max_run([v>=30 for v in t]),
        'CDH26_Kh':sum(max(0.,v-26) for v in t),
        'HDH18_Kh':sum(max(0.,18-v) for v in t),
        'RH_mean_pct':fmean(rh),'RH_p05_pct':percentiles(rh)['p05'],
        'RH_temp_hourly_pearson':pearson(t,rh),
        'q_temp_hourly_pearson':pearson(t,q),
        'T_lag1_pearson':pearson(t[:-1],t[1:]),
        'RH_lag1_pearson':pearson(rh[:-1],rh[1:]),
        'T_abs_hourly_change_p99_C':percentiles([abs(x-y) for x,y in zip(t[1:],t[:-1])])['p99'],
        'RH_saturation_h':sum(v>=99.95 for v in rh),
        'RH_jump_over20_h':sum(observed_rh_jumps),
        'RH_max_jump_pp':max(abs(a-b) for a,b in zip(rh[1:],rh[:-1])),
        'q_mean_gkg':fmean(q)*1000,
        'dewpoint_exceeds_drybulb_over0p6_h':violations,
        'GHI_kwh_m2':sum(ghi)/1000,
        'DNI_kwh_m2':sum(d['dni'])/1000,
        'DHI_kwh_m2':sum(d['dhi'])/1000,
        'rain_mm':sum(v for v in d['rain'] if v is not None),
        'wet_hours_rain_gt0p1mm':sum(v is not None and v>.1 for v in d['rain']),
        'longest_dry_spell_h':max_run([v is not None and v<=.1 for v in d['rain']]),
        'rain_valid_hours':sum(v is not None for v in d['rain']),
        'wind_speed_mean_ms':fmean(v for v in d['wind_speed'] if v is not None),
        'wind_dir_valid_hours':sum(v is not None for v in d['wind_dir']),
        'daylight_T_GHI_pearson':pearson(
            [temp for temp,g in zip(t,ghi) if g>10],
            [g for g in ghi if g>10]),
        'wind_rose':wind_rose(d['wind_dir'],d['wind_speed']),
        'hour_count':len(t)}
    return result


def monthly_metrics(epw):
    h=epw['hours'];result=[];start=0
    for m,days in enumerate(MONTH_DAYS,1):
        sl=slice(start,start+days*24); t=h['temp'][sl];r=h['rh'][sl];p=h['pressure'][sl];
        ghi=h['ghi'][sl];rain=h['rain'][sl]
        result.append({'file':epw['name'],'month':m,
            'T_mean_C':fmean(t),'T_p95_C':percentiles(t)['p95'],
            'RH_mean_pct':fmean(r),'q_mean_gkg':1000*fmean(q_air(*x) for x in zip(t,r,p)),
            'GHI_kwh_m2':sum(ghi)/1000,'rain_mm':sum(x for x in rain if x is not None),
            'hot_hours_T30':sum(x>=30 for x in t),
            'CDH26_Kh':sum(max(0.,x-26) for x in t)})
        start+=days*24
    return result


def observed_deltas(new,base):
    k=('T_mean_C','T_p99_C','hot_hours_T30','CDH26_Kh','HDH18_Kh',
       'q_mean_gkg','GHI_kwh_m2','rain_mm','wind_speed_mean_ms','RH_jump_over20_h')
    return {key:new[key]-base[key] for key in k}


def site_of(name):
    for prefix,site in SITE.items():
        if name.startswith(prefix):return site
    return None


def safe_write_csv(path,records):
    if not records:return
    columns=list(records[0])
    with open(path,'w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for rec in records:
            w.writerow({key:(json.dumps(val,separators=(',',':')) if isinstance(val,(list,dict)) else val) for key,val in rec.items()})


def run(meteonorm_zip:str,ige_zip:str,out_dir:str):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    metas={};ige={};aggregate=[];monthly=[]
    with ZipFile(meteonorm_zip) as z:
        names=z.namelist()
        if len(names)!=18 or len(set(names))!=18:raise ValueError('Registered 18 Meteonorm source files required')
        for name in names:
            if not name.lower().endswith('.epw') or '/' in name:raise ValueError('Unexpected source ZIP path')
            e=read_epw(z.read(name),name);metas[name]=e
            aggregate.append({'provider':'Meteonorm_8_2','site':site_of(name),**metric(e)})
            monthly.extend([{'provider':'Meteonorm_8_2','site':site_of(name),**m} for m in monthly_metrics(e)])
    with ZipFile(ige_zip) as z:
        files=[n for n in z.namelist() if n.endswith('.epw')]
        if len(files)!=4:raise ValueError('Expected 4 independent IGE scenarios')
        for name in files:
            key=next((w for w in GRAZ_IGE if w in name),None)
            if key is None or key in ige:raise ValueError('Unexpected or duplicated IGE scenario')
            e=read_epw(z.read(name),name);ige[key]=e
            aggregate.append({'provider':'IGE_CanESM5_P7C1C','site':'Graz',**metric(e)})
            monthly.extend([{'provider':'IGE_CanESM5_P7C1C','site':'Graz',**m} for m in monthly_metrics(e)])
    if set(ige)!=set(GRAZ_IGE):raise ValueError('Incomplete IGE scenario ensemble')
    provenance={e['name']:e['sha256'] for e in list(metas.values())+list(ige.values())}
    # Source-wise reference is the same *underlying* Graz Meteonorm baseline,
    # but the two sets of future climate signals were separately derived.
    references={
        'Graz':'Graz-hour_contemporary_seed1.epw',
        'Vienna':'Wien-Hohe_Warte-hour_contemporary_seed1.epw',
        'Tripoli':'Tripoli-hour_contemporary_seed1.epw',
    }
    meta_stats={x['file']:x for x in aggregate}
    comparisons=[]
    for site,ref in references.items():
        base=meta_stats[ref]
        for file_name,epw in metas.items():
            if site_of(file_name)!=site or file_name==ref:continue
            future=meta_stats[file_name]
            delta=observed_deltas(future,base)
            comparisons.append({'family':'METEONORM_INTERNAL_CHANGE','site':site,'baseline':ref,'future':file_name,
                'warning':'same_provider_weather_generator_not_independent_observed_future',
                **{f'delta_{k}':v for k,v in delta.items()}})
    for key, epw in ige.items():
        future=meta_stats[epw['name']];base=meta_stats[references['Graz']]
        delta=observed_deltas(future,base)
        comparisons.append({'family':'IGE_CMIP6_CHANGE','site':'Graz','baseline':references['Graz'],'future':epw['name'],
            'warning':'research_CanESM5_SSP_morph_derived_from_same_Meteonorm_baseline',
            **{f'delta_{k}':v for k,v in delta.items()}})
    method=[]
    for key,mn_name,reason in MN_COMPARISONS:
        mn=meta_stats[mn_name];ie=meta_stats[ige[key]['name']];base=meta_stats[references['Graz']]
        mn_delta=observed_deltas(mn,base);ige_delta=observed_deltas(ie,base)
        it=ige[key]['hours']['temp'];mt=metas[mn_name]['hours']['temp']
        irm=ige[key]['hours']['rh'];mrm=metas[mn_name]['hours']['rh']
        method.append({'method_contrast':'NOT_A_MODEL_ACCURACY_METRIC',
            'scenario_ige':key,'scenario_meteonorm':mn_name,
            'comparability':reason,
            'difference_delta_T_mean_C':ige_delta['T_mean_C']-mn_delta['T_mean_C'],
            'difference_delta_T_p99_C':ige_delta['T_p99_C']-mn_delta['T_p99_C'],
            'difference_delta_hot_hours_T30':ige_delta['hot_hours_T30']-mn_delta['hot_hours_T30'],
            'difference_delta_CDH26_Kh':ige_delta['CDH26_Kh']-mn_delta['CDH26_Kh'],
            'difference_delta_HDH18_Kh':ige_delta['HDH18_Kh']-mn_delta['HDH18_Kh'],
            'difference_delta_q_mean_gkg':ige_delta['q_mean_gkg']-mn_delta['q_mean_gkg'],
            'difference_delta_GHI_kwh_m2':ige_delta['GHI_kwh_m2']-mn_delta['GHI_kwh_m2'],
            'difference_delta_rain_mm':ige_delta['rain_mm']-mn_delta['rain_mm'],
            'KSD_T_hourly_unpaired':ks_distance(it,mt),
            'KSD_RH_hourly_unpaired':ks_distance(irm,mrm),
            'MN_hourly_rh_jumps_over20':mn['RH_jump_over20_h'],
            'IGE_hourly_rh_jumps_over20':ie['RH_jump_over20_h'],
            'IGE_new_rh_jumps_vs_original_baseline':sum(
                abs(irm[i]-irm[i-1])>20 and abs(metas[references['Graz']]['hours']['rh'][i]-metas[references['Graz']]['hours']['rh'][i-1])<=20
                for i in range(1,N_HOURS)),
        })
    # Independent structural comparisons in Vienna: same source seed and scenario UHI,
    # plus two stochastic seeds. Explicitly exclude exact duplicate 2100 as extra sample.
    v='Wien-Hohe_Warte-hour'
    uhi={
        'future_RCP8.5_2050_UHI':(v+'RCP8.5_2050.epw',v+'RCP8.5_2050_heatinsel.epw'),
        'future_RCP8.5_2100_seed':(v+'RCP8.5_2100_seed1.epw',v+'RCP8.5_2100_seed2.epw'),
        'contemporary_seed_variability':(v+'_contemporary_seed1.epw',v+'_contemporary_seed2.epw'),
    }
    controlled=[]
    for kind,(a,b) in uhi.items():
        aa=metas[a]['hours']['temp'];bb=metas[b]['hours']['temp'];
        ms=metric(metas[a]);mf=metric(metas[b]);
        night=[i for i in range(N_HOURS) if i%24 in (0,1,2,3,4,5,20,21,22,23)]
        controlled.append({'comparison':kind,'source_a':a,'source_b':b,
            'delta_T_mean_C':mf['T_mean_C']-ms['T_mean_C'],
            'delta_T_night_C':fmean(bb[i]-aa[i] for i in night),
            'delta_T_p99_C':mf['T_p99_C']-ms['T_p99_C'],
            'delta_hot_hours_T30':mf['hot_hours_T30']-ms['hot_hours_T30'],
            'delta_GHI_kwh_m2':mf['GHI_kwh_m2']-ms['GHI_kwh_m2'],
            'T_hourly_KS':ks_distance(aa,bb),
            'identical_bytes':metas[a]['sha256']==metas[b]['sha256']})
    dupe=defaultdict(list)
    for n,x in metas.items():dupe[x['sha256']].append(n)
    duplicates=[v for v in dupe.values() if len(v)>1]
    total_invalid=sum(x['dewpoint_exceeds_drybulb_over0p6_h'] for x in aggregate)
    # Only aggregate outputs: no EPW rows, matched-hour series, provider metadata beyond original filename and SHA.
    safe_write_csv(out/'p7c2_epw_aggregate_metrics.csv',aggregate)
    safe_write_csv(out/'p7c2_epw_monthly_aggregate_metrics.csv',monthly)
    safe_write_csv(out/'p7c2_provider_internal_climate_signals.csv',comparisons)
    safe_write_csv(out/'p7c2_ige_vs_meteonorm_method_contrasts.csv',method)
    safe_write_csv(out/'p7c2_vienna_uhi_seed_sensitivity.csv',controlled)
    audit={'stage':'P7C.2_INDEPENDENT_METEONORM_METHOD_BENCHMARK',
        'data_kind':'USER_LICENSED_METEONORM_8_2_AND_LOCALLY_DERIVED_IGE_P7C1C',
        'research_only':True,'production_epw_ready':False,'actual_historical_measurements':False,
        'future_observations_available':False,'external_truth_validation':False,
        'sources':provenance,'source_zip_sha256':sha256(Path(meteonorm_zip).read_bytes()),
        'ige_zip_sha256':sha256(Path(ige_zip).read_bytes()),
        'meteonorm_count':len(metas),'ige_count':len(ige),
        'unique_meteonorm_sha_count':len(dupe),'duplicate_epw_sets':duplicates,
        'reference_files':references,'method_comparisons':method,
        'controlled_vienna':controlled,
        'structural_dewpoint_discrepancy_over0p6_C_hours_total':total_invalid,
        'constraints':[
          'Meteonorm future RCP and CMIP6 SSP differ in forcing pathway and climate-model family',
          'Meteonorm labeled 2050/2100 is NOT an identical climate averaging interval to SSP 2040-59/2080-99',
          'Different weather-generator seeds are separate stochastic realizations, not forecast skill',
          'Meteonorm future EPWs are NOT future observations/ground truth',
          'IGE only evaluated for Graz, not for Vienna or Tripoli',
          'No redistribution of user original or transformed licensed hourly Meteonorm EPW records',
          'No building energy simulation or independent future-variable validation'],
        'aggregate_file_sha256':{},
    }
    for path in sorted(out.glob('*.csv')):
        audit['aggregate_file_sha256'][path.name]=sha256(path.read_bytes())
    (out/'p7c2_science_audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print('P7C2',{'mn':len(metas),'ige':len(ige),'dupes':len(duplicates),'contrasts':len(method),
        'structural_dewpoint_discrepancy_over0p6_C_hours_total':total_invalid},flush=True)
    for x in method:print('METHOD',x['scenario_ige'],'dT',round(x['difference_delta_T_mean_C'],3),
                           'dHot',round(x['difference_delta_hot_hours_T30'],1),
                           'dGHI',round(x['difference_delta_GHI_kwh_m2'],1),flush=True)
    return audit

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--meteonorm-zip',required=True);p.add_argument('--ige-zip',required=True)
    p.add_argument('--out',required=True);a=p.parse_args()
    run(a.meteonorm_zip,a.ige_zip,a.out)