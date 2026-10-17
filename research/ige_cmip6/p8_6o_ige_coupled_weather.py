#!/usr/bin/env python3
"""IGE P8.6O: same-month/hour rain–RH–q–Kt–diffuse–LW coherence on original EPWs.

Read ONLY original archived public P7B4/P7B5/P7C1 EPW bytes. No proprietary
Meteonorm data, fake clouds or invented rainy hours. Scalar/conditional
results must not be called independent forecast accuracy.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import numpy as np

MONTHS=np.repeat([(dt.date(2001,1,1)+dt.timedelta(days=i)).month for i in range(365)],24)
HOURS=np.tile(np.arange(24),365)
DAY=np.repeat(np.arange(365),24)
R=1361.
SIGMA=5.670374419e-8

def solar_cos(lat,lon,tz):
    gamma=(2*np.pi/365)*(DAY+(HOURS+.5-12)/24)
    eq=229.18*(.000075+.001868*np.cos(gamma)-.032077*np.sin(gamma)
               -.014615*np.cos(2*gamma)-.040849*np.sin(2*gamma))
    dec=(.006918-.399912*np.cos(gamma)+.070257*np.sin(gamma)
         -.006758*np.cos(2*gamma)+.000907*np.sin(2*gamma)
         -.002697*np.cos(3*gamma)+.00148*np.sin(3*gamma))
    ha=np.deg2rad((HOURS+.5)*15+eq/4+lon-15*tz-180)
    la=np.deg2rad(lat)
    return np.sin(la)*np.sin(dec)+np.cos(la)*np.cos(dec)*np.cos(ha)

def monthly_hour_conditional(v,wet,dry,valid):
    contrasts=[];n=[]
    for m in range(1,13):
        for h in range(24):
            scope=(MONTHS==m)&(HOURS==h)&valid&np.isfinite(v)
            w=scope&wet;d=scope&dry
            if w.any() and d.any():
                contrasts.append(float(v[w].mean()-v[d].mean()))
                n.append(int(w.sum()))
    return (float(np.average(contrasts,weights=n)) if n else None,
            int(sum(n)))

def read_original(path):
    path=Path(path)
    with path.open(newline='',encoding='utf-8-sig') as fp:
        src=list(csv.reader(fp))
    if len(src)!=8768 or any(len(r)!=35 for r in src[8:]):
        raise ValueError("P8_6O_INVALID_8760_X_35_EPWS")
    rows=src[8:]
    if any(int(r[1])!=MONTHS[i] or int(r[3])!=HOURS[i]+1 for i,r in enumerate(rows)):
        raise ValueError("P8_6O_EPW_HOUR_OR_MONTH_DRIFT")
    cols=(6,7,8,9,12,13,14,15,20,21,22,23,33,34)
    mat=np.array([[float(r[c]) for c in cols] for r in rows])
    if not np.all(np.isfinite(mat)):
        raise ValueError("P8_6O_NONFINITE_EPW_WEATHER")
    return src[0],mat,hashlib.sha256(path.read_bytes()).hexdigest()

def metric(path):
    header,mat,sha=read_original(path)
    T,Td,RH,p,L,G,DNI,DHI,direction,speed,cloud,opaque,rain,period=mat.T
    if np.any(rain<0) or np.any((RH<0)|(RH>100)):
        raise ValueError("P8_6O_INVALID_RAIN_OR_RH")
    wet=rain>0;dry=rain==0
    lat,lon,tz=map(float,(header[6],header[7],header[8]))
    cos=solar_cos(lat,lon,tz)
    ex=R*(1+.033*np.cos(2*np.pi*(DAY+1)/365))*np.maximum(0,cos)
    daylight=(cos>.15)&(ex>100)
    kt=np.divide(G,ex,out=np.full(8760,np.nan),where=daylight)
    diffuse=np.divide(DHI,G,out=np.full(8760,np.nan),where=daylight&(G>20))
    sat=611.21*np.exp((18.678-T/234.5)*T/(257.14+T))
    vap=sat*RH/100
    q=.621945*vap/(p-(1-.621945)*vap)*1000
    eps=L/(SIGMA*(T+273.15)**4)
    valid_cloud=(cloud>=0)&(cloud<=10)
    observables={
        'cloud_tenths':(cloud,valid_cloud),
        'RH_pp':(RH,np.isfinite(RH)),
        'q_gkg':(q,np.isfinite(q)),
        'daylight_Kt':(kt,daylight),
        'diffuse_fraction':(diffuse,np.isfinite(diffuse)),
        'sky_emissivity':(eps,np.isfinite(eps)),
        'dewpoint_depression_C':(T-Td,np.isfinite(T)),
    }
    result={
        'filename':Path(path).name,'source_sha256':sha,
        'source_public_research_only':True,
        'n_hours':8760,'n_wet':int(wet.sum()),
        'wet_occurrence_binary_sha256':hashlib.sha256(wet.tobytes()).hexdigest(),
        'n_sky_cover_missing_99':int((cloud==99).sum()),
        'cloud_available_for_physical_rain_coupling':bool(valid_cloud.sum()>=100),
        'n_missing_noncalm_direction':int(((speed>=.5)&(direction==999)).sum()),
        'n_wet_RH_below_60':int((wet&(RH<60)).sum()),
        'n_wet_RH_below_40':int((wet&(RH<40)).sum()),
        'n_daytime_wet_Kt_above_0p7':int((wet&daylight&(kt>.7)).sum()),
        'n_precip_period_1h':int((period==1).sum()),
        'n_precip_depth_nonzero_period_0h':int((wet&(period==0)).sum()),
        'Meteonorm_RCP_and_IGE_SSP_same_scenarios':False,
    }
    for name,(values,valid) in observables.items():
        result['rain_minus_dry_month_hour_'+name],result[
            'n_rain_matched_'+name]=monthly_hour_conditional(values,wet,dry,valid)
    return result

def run(p7b4,p7b5,p7c1_dir,out):
    p7c1=sorted(Path(p7c1_dir).glob('*.epw'))
    if len(p7c1)!=4:raise ValueError("P8_6O_EXPECT_FOUR_ORIGINAL_P7C1_EPWS")
    original=[Path(p7b4),Path(p7b5),*p7c1]
    result=[metric(p) for p in original]
    if not all(x['n_hours']==8760 for x in result):
        raise AssertionError("P8_6O_MISSING_ORIGINAL_HOURLY_EPWS")
    research={
        'phase':'IGE_P8_6O',
        'original_public_IGE_EPWs_verified':len(original),
        'private_P7C5B_28_verified':0,
        'n_original_hours_reloaded':len(original)*8760,
        'same_hourly_rain_mask_all_six':len(set(x['wet_occurrence_binary_sha256'] for x in result))==1,
        'all_six_cloud_99_every_hour':all(x['n_sky_cover_missing_99']==8760 for x in result),
        'n_distinct_original_historical_weather_realizations':1,
        'conditional_metric_signs_expected':all(
            x['rain_minus_dry_month_hour_RH_pp']>0
            and x['rain_minus_dry_month_hour_daylight_Kt']<0
            and x['rain_minus_dry_month_hour_diffuse_fraction']>0
            and x['rain_minus_dry_month_hour_sky_emissivity']>0
            for x in result),
        'member_metrics':result,
        'independent_observational_accuracy_established':False,
        'production_epw_ready':False,
    }
    path=Path(out);path.mkdir(parents=True,exist_ok=True)
    (path/'ige_p8_6o_original_epw_coupled_metrics.json').write_text(
        json.dumps(research,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('IGE_P8_6O',json.dumps({
        'originals':len(original),
        'n_wet':result[0]['n_wet'],
        'all_six_rain_mask_identical':research['same_hourly_rain_mask_all_six'],
        'cloud_complete':not research['all_six_cloud_99_every_hour'],
        'base_RH_pp':result[0]['rain_minus_dry_month_hour_RH_pp'],
        'base_delta_Kt':result[0]['rain_minus_dry_month_hour_daylight_Kt'],
        'production_epw_ready':False,
    }),flush=True)
    return research

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--p7b4-epw',required=True)
    a.add_argument('--p7b5-epw',required=True)
    a.add_argument('--p7c1-dir',required=True)
    a.add_argument('--out',required=True)
    args=a.parse_args()
    run(args.p7b4_epw,args.p7b5_epw,args.p7c1_dir,args.out)
