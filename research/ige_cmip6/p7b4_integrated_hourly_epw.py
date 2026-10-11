#!/usr/bin/env python3
"""IGE P7B.4 — integrated original-source EPW solar update and bounded 1R1C impact.

Research only: PRESERVE every existing P7B.2 non-solar EPW value, time, RH,
pressure, wind, precipitation. Replace only EPW GHI/DNI/DHI (columns 13–15)
with 20-seed P7B.3F-repaired M2 and Erbs components. Only seed 0 EPW is
published; all seed diagnostics are recorded. THIS IS NOT an EnergyPlus run.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from collections import defaultdict, Counter
from datetime import date,datetime,timedelta
from pathlib import Path
from statistics import fmean
from p7b3c_conditional_solar import load_original_station,build_library
from p7b3f_feasibility_repair import prepare_daily,generate_repaired,minimum_relaxed_cap
from p7b3e_multigcm_radiometric_closure import reconstruct_components

YEAR=2013
LAT,LON=46.875,15.375
ORIGINAL_HOURLY_SHA='099c5b29f5c2ecdc9a72d274db5eb2a8bb870c7e3b54cfb5588c1567c6b2036a'
ORIGINAL_DAILY_SHA='5835eff14472367f5eb30bfab9e69a50c358d965e856e757a1377c2224bd3021'
ORIGINAL_EPW_SHA='ab7c06dcb28c969c7de7886a1afe0afb7917cc78815bb847d0fff1d846e7bd45'
ORIGINAL_GROUND_SHA='95dc8f9b7341be69d0ee236b38029a3f171b7f6a9eb0aed75b03cd2e473500c0'
NROWS=8760
BASE_FIELDS=35
SOLAR_COLS=(13,14,15)
EPW_FILENAME='Graz_CanESM5_2013_IGE_P7B4_M2_SOLAR_INTEGRATED_RESEARCH_ONLY.epw'


def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with open(path,encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def read_baseline_epw(path):
    with open(path,encoding='utf-8',newline='') as f:records=list(csv.reader(f))
    if len(records)!=NROWS+8:raise ValueError('Original EPW: expected 8 headers and 8760 hours')
    if any(len(r)!=BASE_FIELDS for r in records[8:]):raise ValueError('Original EPW: 35-field record violation')
    header=records[:8]
    if [r[0] for r in header] != ['LOCATION','DESIGN CONDITIONS','TYPICAL/EXTREME PERIODS',
         'GROUND TEMPERATURES','HOLIDAYS/DAYLIGHT SAVINGS','COMMENTS 1','COMMENTS 2','DATA PERIODS']:
         raise ValueError('EPW header layout mismatch')
    if len(header[0])<10 or abs(float(header[0][6])-LAT)>1e-8 or abs(float(header[0][7])-LON)>1e-8:
        raise ValueError('EPW coordinates do not correspond to registered model grid')
    if int(header[0][8])!=1:raise ValueError('Fixed CET time zone expected')
    if len(header[7])<7 or header[7][-2:]!=['1/1','12/31']:
        raise ValueError('Unexpected EPW data period')
    expected=datetime(YEAR,1,1)
    if any([int(v) for v in r[:5]] !=
            [YEAR,(expected+timedelta(hours=i)).month,(expected+timedelta(hours=i)).day,
             (expected+timedelta(hours=i)).hour+1,60]
           for i,r in enumerate(records[8:])):
        raise ValueError('EPW timestamps noncontiguous or 1–24 clock invalid')
    return header,records[8:]


def source_hours_by_date(hour_path):
    if sha(hour_path)!=ORIGINAL_HOURLY_SHA:raise ValueError('P7B.2 original hourly SHA256 mismatch')
    rows=read_csv(hour_path)
    if len(rows)!=NROWS:raise ValueError('P7B.2 missing model hours')
    out=defaultdict(list)
    for i,r in enumerate(rows):
        t=datetime.fromisoformat(r['local_hour'])
        dt=datetime(YEAR,1,1)+timedelta(hours=i)
        if (t.utcoffset()!=timedelta(hours=1) or t.replace(tzinfo=None)!=dt or
                int(r['hour'])!=dt.hour or date.fromisoformat(r['date'])!=dt.date()):
            raise ValueError('Model synthetic noleap fixed-CET calendar mismatch')
        p=float(r['pressure_pa']);ta=float(r['T_C']);rh=float(r['RH_pct']);td=float(r['dewpoint_C'])
        wind=float(r['wind_ms']);pr=float(r['rain_mm']);lw=float(r['sky_lw_Wh'])
        if (not all(math.isfinite(x) for x in (p,ta,rh,td,wind,pr,lw)) or
                not 70000<p<110000 or not -70<ta<70 or not 1<=rh<=100 or
                td>ta+1e-7 or wind<0 or pr<0 or lw<0):
            raise ValueError('Original non-solar physical invalidity')
        out[dt.date()].append(r)
    if len(out)!=365 or any(len(v)!=24 for v in out.values()):
        raise ValueError('Incomplete 365-day P7B.2 source')
    return out


def original_daily_targets(path,hours):
    rows=read_csv(path);out={}
    for r in rows:
        d=date.fromisoformat(r['date']);target=float(r['calibrated_GHI_kwh_m2_day'])
        native=float(r['original_can_esm5_native_GHI_kwh_m2_day'])
        if d in out or not math.isfinite(target+native) or min(target,native)<0:
            raise ValueError('Invalid or duplicate source daily solar')
        ghis=sum(float(v['ghi_Wh']) for v in hours[d])/1000
        if abs(target-ghis)>1e-8:raise ValueError('P7B.2 hourly/corrected daily GHI discrepancy')
        out[d]=target
    if set(out)!=set(hours):raise ValueError('P7B.2 daily target/calendar mismatch')
    return out


def component_day(prepared,generated):
    result={};max_identity=0.;max_dni=0.
    for day,datum in prepared.items():
        for dt,_,toa,clear in datum['records']:
            ghi=generated[dt]
            # The P7B.3F algorithm uses the same extraterrestrial eccentricity
            # and integrated 5-minute hour geometry as the source day.
            ecc=1+.033*math.cos(2*math.pi*(dt.timetuple().tm_yday-3)/365.25)
            cos=max(0.,min(1.,toa/(1.361*ecc))) if toa>0 else 0.
            dhi,dni,err=reconstruct_components(ghi,toa,cos)
            if not (0<=dhi<=ghi+1e-10 and 0<=dni<=1.361*ecc+1e-9):
                raise ValueError('Radiometric component cap violated')
            max_identity=max(max_identity,err)
            max_dni=max(max_dni,max(0.,dni-1.361*ecc))
            result[dt]=(ghi,dni,dhi,cos,toa)
    return result,max_identity,max_dni


def patch_epw(header,original,components,path):
    if len(original)!=NROWS or len(components)!=NROWS:raise ValueError('Patch requires complete year')
    newhead=[r.copy() for r in header]
    newhead[0][4]='IGE_P7B4_M2_RESEARCH_ONLY'
    newhead[5]=['COMMENTS 1','2013 synthetic CanESM5 P7B2 non-solar + station analogue M2 GHI; no observed event pairing']
    newhead[6]=['COMMENTS 2','Research only; wind direction unknown; RH/pressure proxies; Erbs DHI/DNI NOT sensor-validated; see JSON audit']
    newhead[7][3]='P7B4 research CanESM5 noleap 2013 fixed CET'
    rows=[];maxoldother=0
    for i,src in enumerate(original):
        dt=datetime(YEAR,1,1)+timedelta(hours=i)
        ghi,dni,dhi,cos,toa=components[dt]
        current=src.copy()
        for j,value in zip(SOLAR_COLS,(ghi,dni,dhi)):
            current[j]=f'{value*1000:.9f}'
        if any(current[j]!=src[j] for j in range(BASE_FIELDS) if j not in SOLAR_COLS):
            raise ValueError('Non-solar EPW field changed')
        # Original P7B.2 wind direction uses EPW missing value 999.
        if current[20]!='999':raise ValueError('Unregistered generated wind direction')
        rows.append(current)
    with open(path,'w',encoding='utf-8',newline='') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerows(newhead);writer.writerows(rows)
    parsed_header,parsed=read_baseline_epw(path)
    if len(parsed)!=NROWS:raise ValueError('Independent EPW reader failed')
    for base,new in zip(original,parsed):
        if any(base[j]!=new[j] for j in range(BASE_FIELDS) if j not in SOLAR_COLS):
            raise ValueError('EPW round-trip modified non-solar source')
    return rows


def pearson(a,b):
    if len(a)!=len(b) or not a:return None
    x=fmean(a);y=fmean(b)
    cov=sum((v-x)*(w-y) for v,w in zip(a,b))
    var1=sum((v-x)**2 for v in a);var2=sum((w-y)**2 for w in b)
    return cov/math.sqrt(var1*var2) if var1>0 and var2>0 else None


def solar_south_vertical(ghi,dni,dhi,dt):
    """Approx NOAA solar geometry; diagnostic facade signal, not site horizon."""
    n=dt.timetuple().tm_yday
    gamma=2*math.pi/365*(n-1+(dt.hour+.5-12)/24)
    decl=(.006918-.399912*math.cos(gamma)+.070257*math.sin(gamma)
          -.006758*math.cos(2*gamma)+.000907*math.sin(2*gamma)
          -.002697*math.cos(3*gamma)+.00148*math.sin(3*gamma))
    eq=229.18*(.000075+.001868*math.cos(gamma)-.032077*math.sin(gamma)
        -.014615*math.cos(2*gamma)-.040849*math.sin(2*gamma))
    hour_angle=math.radians(((dt.hour+.5)*60 +eq+4*LON-60)/4-180)
    lat=math.radians(LAT)
    north=math.cos(lat)*math.sin(decl)-math.sin(lat)*math.cos(decl)*math.cos(hour_angle)
    return dni*max(0.,-north)+.5*dhi+.1*ghi


def simple_zone_proxy(hourly_weather, solar, label):
    """Explicit synthetic 1R1C demand proxy; NOT EnergyPlus or real building.

    100 m2 demonstration zone, fixed UA, heat capacity, internal gains,
    south vertical aperture. Demand is an imposed ideal controller.
    """
    c_kwh_k=28.0;ua_kw_k=.16;g_a_m2=10.;int_kw=.25
    t=21.;totals=Counter();peak=Counter()
    for dt,ta,rh,wind,ghi,dni,dhi in hourly_weather:
        vertical=solar_south_vertical(ghi,dni,dhi,dt)
        gains=g_a_m2*.5*vertical # kWh per hour / aperture
        free=t+(ua_kw_k*(ta-t)+int_kw+gains)/c_kwh_k
        heat=max(0.,20.-free)*c_kwh_k
        cool=max(0.,free-26.)*c_kwh_k
        t=min(26.,max(20.,free))
        totals['heat_kwh']+=heat;totals['cool_kwh']+=cool
        peak['heat_kw']=max(peak['heat_kw'],heat);peak['cool_kw']=max(peak['cool_kw'],cool)
    return {'label':label,'ideal_heating_kwh_100m2':totals['heat_kwh'],
            'ideal_cooling_kwh_100m2':totals['cool_kwh'],
            'peak_hourly_heating_kw':peak['heat_kw'],'peak_hourly_cooling_kw':peak['cool_kw'],
            'model':'EXPLICIT_1R1C_SOUTH_FACADE_IDEAL_SETPOINT_PROXY_NOT_ENERGYPLUS',
            'UA_kW_K':ua_kw_k,'C_kWh_K':c_kwh_k,'internal_gains_kW':int_kw,
            'south_window_area_m2':g_a_m2,'glazing_g':.5,
            'heating_C':20.,'cooling_C':26.}


def load_weather(original,components):
    rows=[]
    for i,r in enumerate(original):
        dt=datetime(YEAR,1,1)+timedelta(hours=i)
        ghi,dni,dhi,_,_=components[dt]
        rows.append((dt,float(r[6]),float(r[8]),float(r[21]),ghi,dni,dhi))
    return rows


def epw_components(original):
    return {datetime(YEAR,1,1)+timedelta(hours=i):
      (float(r[13])/1000,float(r[14])/1000,float(r[15])/1000,0.,0.)
      for i,r in enumerate(original)}


def run(hour_path,daily_path,base_epw,ground_path,out_dir,seeds=8):
    if not 2<=seeds<=20:raise ValueError('Expected 2 to 20 ensemble members')
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    if sha(ground_path)!=ORIGINAL_GROUND_SHA:raise ValueError('Original GeoSphere QA source SHA mismatch')
    if sha(daily_path)!=ORIGINAL_DAILY_SHA:raise ValueError('P7B.2 frozen daily source SHA256 mismatch')
    if sha(base_epw)!=ORIGINAL_EPW_SHA:raise ValueError('P7B.2 frozen EPW source SHA256 mismatch')
    source=source_hours_by_date(hour_path)
    target=original_daily_targets(daily_path,source)
    header,original=read_baseline_epw(base_epw)
    obs,counts=load_original_station(ground_path,'record_start',(2007,2008))
    lib=build_library(obs)
    prepared,counters,lambdas,rejected,examples=prepare_daily(target,LAT,LON,stress_years=(YEAR,))
    if rejected or len(prepared)!=365:raise ValueError('P7B.4 corrected target feasibility failure; no silent loss')
    if any(datum['fraction']!=0 for datum in prepared.values()):
        raise ValueError('P7B.4 unexpectedly changes prior feasible source cap')
    prev=epw_components(original)
    oldweather=load_weather(original,prev)
    before=simple_zone_proxy(oldweather,prev,'P7B2_PRESERVED_BASELINE')
    metrics=[];all_weather=[];components0=None
    for seed in range(seeds):
        generated,diag=generate_repaired(prepared,lib,seed)
        components,err,dnerr=component_day(prepared,generated)
        if diag['max_daily_energy_residual']>1e-9 or err>1e-10 or dnerr>1e-10:
            raise ValueError('Independent physical closure guard failed')
        weather=load_weather(original,components)
        proxy=simple_zone_proxy(weather,components,'M2_SEED_'+str(seed))
        gh0=[x[4] for x in oldweather];gh1=[x[4] for x in weather]
        daily_bad=0
        for day,rows in source.items():
            measured=sum(components[datetime(day.year,day.month,day.day,h)][0] for h in range(24))
            if abs(measured-target[day])>1e-9:daily_bad+=1
        if daily_bad:raise ValueError('Daily source GHI changed in integration')
        metrics.append({'seed':seed,**{k:proxy[k] for k in ('ideal_heating_kwh_100m2',
                       'ideal_cooling_kwh_100m2','peak_hourly_heating_kw','peak_hourly_cooling_kw')},
              'annual_ghi_kwh_m2':sum(gh1),
              'mean_abs_change_hourly_GHI_kwh_m2':fmean(abs(x-y) for x,y in zip(gh0,gh1)),
              'corr_ghi_temperature':pearson(gh1,[v[1] for v in weather]),
              'corr_ghi_RH':pearson(gh1,[v[2] for v in weather]),
              'corr_ghi_wind_speed':pearson(gh1,[v[3] for v in weather]),
              'max_daily_ghi_residual_kwh_m2':diag['max_daily_energy_residual'],
              'max_radiometric_residual_kwh_m2_h':err})
        if seed==0:components0=components;all_weather=weather
    epwfile=out/EPW_FILENAME
    changed=patch_epw(header,original,components0,epwfile)
    if not any(changed[i][13]!=original[i][13] for i in range(NROWS)):
        raise ValueError('M2 did not replace solar fields')
    for r in original:
        if not (0<=float(r[8])<=100 and float(r[7])<=float(r[6])+0.05):
            raise ValueError('EPW pyschrometrics inconsistent')
    # Non-solar source includes previous source RH/wind etc; do not modify.
    with open(out/'p7b4_seed_load_sensitivity.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(metrics[0]));w.writeheader();w.writerows(metrics)
    solar_csv=out/'p7b4_seed0_hourly_solar_components.csv'
    with open(solar_csv,'w',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['local_hour_fixed_CET','GHI_Wh_m2_hour','DNI_Wh_m2_hour','DHI_Wh_m2_hour',
                         'coszen_hour_integrated','TOA_horizontal_Wh_m2_hour'])
        for dt in sorted(components0):
            ghi,dni,dhi,cos,toa=components0[dt]
            writer.writerow([dt.isoformat(),ghi*1000,dni*1000,dhi*1000,cos,toa*1000])
    cal_flags={
      'original_GCM_calendar':'noleap_2013_synthetic_365_days',
      'CET_UTC_offset_hours':1,'DST_applied':False,'leap_day_interpolated':False,
      'future_GCM_calendar_mapping_validated':False,
      'EPW_1_to_24_hours_validated':True}
    audit={
      'stage':'IGE_P7B4_CANESM5_2013_INTEGRATED_HOURLY_EPW_RESEARCH_PILOT',
      'status':'STRUCTURAL_EPW_AND_SOURCE_DAILY_PHYSICS_AUDIT',
      'production_ready':False,'full_EnergyPlus_simulation_executed':False,
      'model_weather_is_observed_date_matched':False,'wind_direction_available':False,
      'wind_direction_EPW_missing_code':999,
      'pressure_is_proxy_not_measured':True,
      'DHI_DNI_independently_sensor_validated':False,
      'solar_model':'P7B3F_MINIMUM_CAP_PLUS_P7B3C_FROZEN_M2_ERBS_PARTITION',
      'p7b3f_repair_applied_to_2013_calibrated_source_days':sum(x['fraction']>0 for x in prepared.values()),
      'source_day_count':len(prepared),'hour_count':NROWS,'EPW_columns':BASE_FIELDS,
      'non_solar_EPWhourly_fields_preserved':32,
      'seeds':seeds,'calendar':cal_flags,
      'original_ghi_calibration_2005_2009_still_applied':True,
      'source_Sha256':{'P7B2_hourly':sha(hour_path),'P7B2_daily':sha(daily_path),
        'P7B2_accepted_epw':sha(base_epw),'GeoSphere_original_10min_hourly':sha(ground_path)},
      'original_P7B2_energy_proxy':before,
      'M2_energy_proxy_ensemble':{
        'heating_kwh_mean':fmean(m['ideal_heating_kwh_100m2'] for m in metrics),
        'cooling_kwh_mean':fmean(m['ideal_cooling_kwh_100m2'] for m in metrics),
        'heating_kwh_range':[min(m['ideal_heating_kwh_100m2'] for m in metrics),max(m['ideal_heating_kwh_100m2'] for m in metrics)],
        'cooling_kwh_range':[min(m['ideal_cooling_kwh_100m2'] for m in metrics),max(m['ideal_cooling_kwh_100m2'] for m in metrics)],
        'heating_relative_change_pct':100*(fmean(m['ideal_heating_kwh_100m2'] for m in metrics)/before['ideal_heating_kwh_100m2']-1) if before['ideal_heating_kwh_100m2'] else None,
        'cooling_relative_change_pct':100*(fmean(m['ideal_cooling_kwh_100m2'] for m in metrics)/before['ideal_cooling_kwh_100m2']-1) if before['ideal_cooling_kwh_100m2'] else None,
      },
      'derived_sha256':{n:sha(out/n) for n in [EPW_FILENAME,'p7b4_seed_load_sensitivity.csv',
                                            'p7b4_seed0_hourly_solar_components.csv']},
      'unresolved_scientific_gates':['SOURCE_MISSING_WIND_DIRECTION','RH_SMOOTHING_NOT_STATION_CALIBRATED',
           'NOT_MEASURED_DHI_DNI','NO_ENERGYPLUS_SIZING_OR_ZONE_MODEL','ONLY_ONE_GCM_ONE_YEAR',
           'NO_FUTURE_GCM_CALENDAR_MAPPING','REGIONAL_TRAINING_ONLY'],
    }
    (out/'p7b4_scientific_audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
    return audit


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--p7b2-hourly',required=True);p.add_argument('--p7b2-daily',required=True)
    p.add_argument('--p7b2-epw',required=True);p.add_argument('--geosphere-hourly',required=True)
    p.add_argument('--out',required=True);p.add_argument('--seeds',type=int,default=8)
    a=p.parse_args()
    j=run(a.p7b2_hourly,a.p7b2_daily,a.p7b2_epw,a.geosphere_hourly,a.out,a.seeds)
    print(json.dumps({'status':j['status'],'daily_days':j['source_day_count'],
          'solar_repair_days':j['p7b3f_repair_applied_to_2013_calibrated_source_days'],
          'baseline_zone_proxy':j['original_P7B2_energy_proxy'],
          'M2_zone_proxy':j['M2_energy_proxy_ensemble']},indent=2))