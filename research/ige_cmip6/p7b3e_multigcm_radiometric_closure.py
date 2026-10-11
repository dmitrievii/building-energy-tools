#!/usr/bin/env python3
"""P7B.3E: eight-GCM ORIGINAL historical daily GHI physical feasibility and
experimental hourly GHI/DHI/DNI closure. NO sensor-validated DHI/DNI, NO EPW.

GCM daily NEX-GDDP v2 sources are independently verified via original QA+SHA.
Physical caps are hypotheses and may invalidate daily energy; never force pass.
"""
from __future__ import annotations
import argparse,csv,json,hashlib,math,calendar
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta
from functools import lru_cache
from pathlib import Path
from statistics import fmean
from p7b3c_conditional_solar import build_library,load_original_station,generate,project_energy,SEASONS,sha
from p7b3d_crosssite_generalization import geometry

MODELS=('ACCESS-CM2','CanESM5','EC-Earth3','GFDL-ESM4','IPSL-CM6A-LR','MPI-ESM1-2-HR','MRI-ESM2-0','NorESM2-MM')
WINDOW='historical-1995-2014'
CALENDARS=('noleap','gregorian','standard','proleptic_gregorian','365_day')
FLOORS=(.45,.65,.85)
FROZEN_ALPHA=.75
PERIODS={'historical_test':(2012,2013,2014)}


def original_source(folder,model):
    folder=Path(folder);qa=json.loads((folder/'quality_report.json').read_text())
    prov=json.loads((folder/'source_provenance.json').read_text())
    if qa.get('status')!='PASS' or prov.get('status')!='PASS' or qa.get('model')!=model or prov.get('model')!=model:
        raise ValueError('original model QA/provenance does not match '+model)
    if qa.get('window')!=WINDOW or prov.get('window')!=WINDOW:
        raise ValueError('wrong scenario/window '+model)
    if qa.get('calendar') not in CALENDARS:
        raise ValueError('unsupported original CF calendar '+model)
    expected=qa.get('csv_sha256',{}).get('joint_daily_raw.csv')
    if not expected or expected!=prov.get('csv_sha256',{}).get('joint_daily_raw.csv'):
        raise ValueError('untrusted daily source checksum '+model)
    f=folder/'joint_daily_raw.csv'
    if sha(f)!=expected:raise ValueError('original source hash mismatch '+model)
    with f.open(newline='',encoding='utf-8') as stream:
        items=list(csv.DictReader(stream))
    expected_n=qa.get('days',qa.get('daily_records'))
    if len(items)!=expected_n or not 7000<=len(items)<=7400:
        raise ValueError('unexpected original 20-year calendar '+model)
    lat,lon=map(float,qa['grid'])
    result={};years=Counter()
    for row in items:
        if row['model']!=model or row['scenario']!='historical':
            raise ValueError('wrong model or scenario record')
        y,m,d=(int(row[k]) for k in ('year','month','day'))
        if not 1995<=y<=2014:raise ValueError('unexpected year')
        day=date(y,m,d)
        if day in result:raise ValueError('duplicate model date')
        ghi=float(row['rsds_kwh_m2_day'])
        if not math.isfinite(ghi) or ghi<0:raise ValueError('invalid original daily GHI')
        result[day]=ghi;years[y]+=1
    if set(years)!=set(range(1995,2015)) or any(c not in (365,366) for c in years.values()):
        raise ValueError('incomplete historic model years')
    return result,(lat,lon),{'model':model,'calendar':qa['calendar'],'native_records':len(result),
        'original_daily_sha256':expected,'quality_report_sha256':sha(folder/'quality_report.json'),
        'source_provenance_sha256':sha(folder/'source_provenance.json'),
        'grid_latitude_deg':lat,'grid_longitude_deg':lon}


def source_dirs(root):
    root=Path(root)
    mapping={}
    for model in MODELS:
        candidates=[root/model, (root/f'ige-p6-access-{WINDOW}' if model=='ACCESS-CM2' else root/f'ige-p6-{model}-{WINDOW}')]
        # Github download action preserves source artifact directory under root.
        allowed=[p for p in candidates if (p/'quality_report.json').is_file()]
        if len(allowed)!=1:raise ValueError(f'missing or ambiguous immutable source for {model}: {allowed}')
        mapping[model]=allowed[0]
    return mapping


@lru_cache(maxsize=12000)
def solar_vectors(day,lat,lon):
    records=geometry(day,lat,lon)
    return tuple((dt,toa,clear) for dt,toa,clear in records)


def cap_profile(records,floor):
    if floor not in FLOORS:raise ValueError('unregistered clear-sky sensitivity bound')
    return [min(toa,max(1.25*clear,floor*toa)) for _,toa,clear in records]


def erbs_fraction(kt):
    kt=min(1.,max(0.,kt))
    if kt<=.22:return 1-.09*kt
    if kt<=.8:return .9511-.1604*kt+4.388*kt**2-16.638*kt**3+12.336*kt**4
    return .165


def reconstruct_components(ghi,toa,zen_cos,low_sun=.065):
    """Hourly mean energy, kWh/m² per 1h; original Erbs estimated diffuse.

    Important: identity is an algebraic enforced closure, not a DHI/DNI
    ground validation. Low-sun guard never fabricates infinite DNI.
    """
    if not (math.isfinite(ghi) and math.isfinite(toa) and math.isfinite(zen_cos)):
        raise ValueError('nonfinite radiometry')
    if not 0<=zen_cos<=1 or ghi<0 or toa<0 or ghi>toa+1e-8:
        raise ValueError('invalid input GHI/TOA/zenith')
    if ghi<=1e-12:return (0.,0.,0.)
    if toa<=1e-12 or zen_cos<low_sun:return (ghi,0.,0.)
    kt=min(1.,ghi/toa)
    fraction=max(0.,min(1.,erbs_fraction(kt)))
    dhi=ghi*fraction
    dni=(ghi-dhi)/zen_cos
    # Extraterrestrial-normal physical maximum; redistribute remainder into
    # diffuse for closure instead of clipping direct and breaking identity.
    normal_toa=toa/zen_cos
    if dni>normal_toa:
        dni=normal_toa;dhi=ghi-dni*zen_cos
    if min(dni,dhi)<-1e-10:raise ValueError('negative inferred component')
    error=abs(ghi-dhi-dni*zen_cos)
    if error>1e-10:raise ValueError('radiative closure violated')
    return dhi,dni,error


def compute_model(model,days,lat,lon,library,years=(2012,2013,2014),seeds=(0,1,2)):
    thresholds={floor:Counter() for floor in FLOORS}
    probe=[]
    for day,source_energy in days.items():
        g=solar_vectors(day,lat,lon)
        horizon=sum(t for _,t,_ in g)
        for floor in FLOORS:
            c=sum(cap_profile(g,floor))
            if source_energy>c+1e-8:thresholds[floor]['infeasible_days']+=1
            if source_energy>horizon+1e-8:thresholds[floor]['original_daily_exceeds_toa']+=1
            thresholds[floor]['evaluated_days']+=1
        if day.year in years:
            probe.append((day,source_energy,g))
    # Each GCM has its OWN original daily radiation; no CanESM5 solar-factors
    # are transferred. A failing 0.65 cap is flagged and excluded, not clipped.
    synthetic={};bad=[];peryear=Counter()
    for day,energy,g in probe:
        toas=[toa for _,toa,_ in g];clear=[v for _,_,v in g]
        caps=cap_profile(g,.65)
        if energy>sum(caps)+1e-8:
            bad.append({'model':model,'date':str(day),'original_kwh_m2_day':energy,
                        'cap_kwh_m2_day':sum(caps)})
            continue
        baseline=project_energy(clear,energy,caps)
        synthetic[day]=[(g[h][0],baseline[h],toas[h],clear[h]) for h in range(24)]
        peryear[day.year]+=1
    if not synthetic:raise ValueError('no physically feasible model-days')
    # One generated sample for each seed / all 3 model-years; all use fixed Graz
    # observed-day library. This is a within-location, across-GCM stress test.
    summary={};sample_hourly=[]
    for seed in seeds:
        values,info=generate(synthetic,library,FROZEN_ALPHA,seed)
        if info['max_daily_energy_residual']>1e-9:raise ValueError('source energy closure failure')
        max_res=0.;day_n=Counter();totals=Counter();proxy_m0=0.;proxy_m2=0.
        for day,records in synthetic.items():
            for timestamp,m0,toa,clear in records:
                hour_m2=values[timestamp]
                if not 0<=hour_m2<=toa+1e-8:raise ValueError('M2 GHI above extraterrestrial')
                # Approx subhour averaged coszen: TOA = normal extraterrestrial
                # one-hour energy times cos(z) for this location/day.
                year_day=timestamp.timetuple().tm_yday
                ecc=1+.033*math.cos(2*math.pi*(year_day-3)/365.25)
                cosmean=toa/(1.361*ecc) if toa>0 else 0.
                cosmean=min(1.,max(0.,cosmean))
                dhi,dni,err=reconstruct_components(hour_m2,toa,cosmean)
                max_res=max(max_res,err);day_n[day.year]+=1
                totals['ghi']+=hour_m2;totals['dhi']+=dhi
                totals['dni_normal']+=dni
                if seed==0 and day.year==2013 and len(sample_hourly)<96:
                    sample_hourly.append({'model':model,'timestamp_local_cet':timestamp.isoformat(),
                     'M0_GHI_kwh_m2_h':m0,'M2_GHI_kwh_m2_h':hour_m2,
                     'M2_DHI_Erbs_kwh_m2_h':dhi,'M2_DNI_Erbs_kwh_m2_normal_h':dni,
                     'hour_coszen_mean':cosmean,'TOA_horizontal_kwh_m2_h':toa})
        summary[str(seed)]={'source_days':len(synthetic),'hours':sum(day_n.values()),
           'max_ghi_day_residual_kwh_m2':info['max_daily_energy_residual'],
           'max_component_closure_residual_kwh_m2_h':max_res,
           'total_ghi_kwh_m2':totals['ghi'],'total_dhi_kwh_m2':totals['dhi'],
           'total_dni_normal_kwh_m2':totals['dni_normal']}
    return {'model':model,'historical_record_count':len(days),
       'cap_feasibility':{str(k):dict(v) for k,v in thresholds.items()},
       'stress_years':list(years),'original_days_by_stress_year':dict(Counter(d.year for d,_,_ in probe)),
       'feasible_days_by_stress_year':dict(peryear),
       'excluded_model_days_under_frozen_cap':len(bad),
       'excluded_examples':bad[:5],
       'three_seed_hourly_component_closure':summary},sample_hourly


def write_csv(path,rows):
    if not rows:raise ValueError('no records to write')
    with Path(path).open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def run(source_root,graz_original,out,seeds=(0,1,2),models=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    dirs=source_dirs(source_root) if models is None else models
    training,counts=load_original_station(graz_original,'record_start',(2007,2008))
    library=build_library(training)
    if not all(len(library[s])>=30 for s in ('DJF','MAM','JJA','SON')):
        raise ValueError('no training library')
    results=[];sources=[];sample=[]
    for model in MODELS:
        data,coords,src=original_source(dirs[model],model)
        answer,examples=compute_model(model,data,*coords,library,seeds=seeds)
        results.append(answer);sources.append(src);sample.extend(examples)
        print('P7B3E original model',model,'daily',len(data),'excluded',answer['excluded_model_days_under_frozen_cap'],flush=True)
    write_csv(out/'p7b3e_8gcm_hourly_seed0_2013_excerpt.csv',sample)
    stat=[]
    for r in results:
        stat.append({'model':r['model'],'historical_days':r['historical_record_count'],
          'cap_infeasible_floor045':r['cap_feasibility']['0.45'].get('infeasible_days',0),
          'cap_infeasible_floor065':r['cap_feasibility']['0.65'].get('infeasible_days',0),
          'cap_infeasible_floor085':r['cap_feasibility']['0.85'].get('infeasible_days',0),
          'stress_days_rejected_2012_14':r['excluded_model_days_under_frozen_cap'],
          'stress_hours_seed0':r['three_seed_hourly_component_closure']['0']['hours'],
          'max_radiometric_residual':max(q['max_component_closure_residual_kwh_m2_h'] for q in r['three_seed_hourly_component_closure'].values())})
    write_csv(out/'p7b3e_8gcm_original_daily_stress_summary.csv',stat)
    audit={'stage':'IGE_P7B3E_EIGHT_GCM_CLIMATE_STRESS_AND_RADIOMETRIC_CLOSURE',
        'status':'NUMERIC_ORIGINAL_HISTORICAL_8_GCM_STRESS_DIAGNOSTIC',
        'scientific_release':'NOT_YET_VALIDATED',
        'production_epw_ready':False,
        'original_input_is_nex_gddp_cmip6_v2_bcsd':True,
        'no_external_station_daily_ghi_or_local_bias_correction_used':True,
        'solar_grid_not_observation_station':True,
        'ground_DHI_or_DNI_independently_validated':False,
        'DHI_DNI_are_empirical_Erbs_estimates_not_measured':True,
        'low_sun_guard_coszen':.065,
        'caps_are_engineering_hypotheses_not_observed_climatology':list(FLOORS),
        'original_source_sha256':sources,
        'source_Graz_QC_training_SHA256':sha(graz_original),
        'frozen_Graz_training_years':[2007,2008],
        'frozen_alpha_p7b3c':FROZEN_ALPHA,'seeds':list(seeds),
        'multi_model_results':results,
        'limitations':['GCM scenario weather is a realization not temporally synchronized with station events',
            'Original NASA BCSD solar rsds is not re-calibrated: stress tests native daily values only',
            'All eight GCM gridpoints represent the Graz region, NOT broad geographic climates',
            'Different model native calendars must not be silently interpolated to civil time',
            'Erbs+DNI closure is algebraic only; without QC verified station DHI and DNI it cannot certify direct/diffuse partition',
            'The frozen clear-sky cap contains a provisional TOA fraction horizon floor',
            'Some GCM original days can be physically incompatible with these engineering cap assumptions',
            'No completed building-energy load calculation or future-SSP release'],
        'derived_sha256':{p.name:sha(p) for p in out.glob('*.csv')}}
    (out/'p7b3e_multigcm_physics_audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
    return audit

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',required=True);p.add_argument('--graz-original',required=True)
    p.add_argument('--out',required=True);p.add_argument('--seeds',type=int,default=3)
    a=p.parse_args();run(a.source_root,a.graz_original,a.out,seeds=tuple(range(a.seeds)))