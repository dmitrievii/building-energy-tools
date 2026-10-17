#!/usr/bin/env python3
"""P9.2A joint original-hourly weather regimes and seeded 24h-block prototype.

Uses existing P9.1A source, never independently synthesizes cloud/rain/RH/radiation.
Research-only: future anomalies, full-year TMY, and EPW remain separate stages.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import random
import statistics
from collections import Counter,defaultdict
from dataclasses import dataclass

FIELDS=('temperature_2m','dew_point_2m','relative_humidity_2m','surface_pressure',
        'precipitation','cloud_cover','shortwave_radiation','direct_radiation',
        'diffuse_radiation','direct_normal_irradiance','wind_speed_10m','wind_direction_10m')
ALGORITHM='P9.2A_FROZEN_JOINT_DAY_BLOCK_v0.1_20261017'

def check_vector(x):
    if not isinstance(x,dict) or set(x)!=set(FIELDS):
        raise ValueError('P92_MISSING_OR_EXTRA_WEATHER_VARIABLE')
    if any(not isinstance(x[k],(int,float)) or not math.isfinite(x[k]) for k in FIELDS):
        raise ValueError('P92_NONFINITE_SOURCE_WEATHER')
    t=x['temperature_2m'];td=x['dew_point_2m'];rh=x['relative_humidity_2m']
    if not (-95<t<65 and -100<td<65 and td<=t+.5 and 0<=rh<=100):
        raise ValueError('P92_THERMODYNAMIC_DOMAIN_INVALID')
    if not 300<x['surface_pressure']<1150 or not 0<=x['cloud_cover']<=100:
        raise ValueError('P92_PRESSURE_OR_CLOUD_INVALID')
    if not 0<=x['wind_speed_10m']<=90 or not 0<=x['wind_direction_10m']<=360:
        raise ValueError('P92_WIND_DOMAIN_INVALID')
    if not 0<=x['precipitation']<=500:
        raise ValueError('P92_PRECIPITATION_INVALID')
    for k in ('shortwave_radiation','direct_radiation','diffuse_radiation','direct_normal_irradiance'):
        if not 0<=x[k]<=1600:
            raise ValueError('P92_SHORTWAVE_SOURCE_INVALID_'+k)

def regime(x):
    check_vector(x)
    if x['precipitation']>0:return 'wet'
    if x['cloud_cover']>=70:return 'cloudy_dry'
    if x['cloud_cover']<=30:return 'clear_dry'
    return 'mixed_dry'

@dataclass(frozen=True)
class Day:
    date:dt.date
    vectors:tuple
    original_sha256:str

    def __post_init__(self):
        if len(self.vectors)!=24:
            raise ValueError('P92_DONOR_DAY_NEEDS_24_HOURS')
        if len(self.original_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.original_sha256):
            raise ValueError('P92_ORIGINAL_SOURCE_SHA_MISSING')
        for x in self.vectors:check_vector(x)

def canonical_days(times,arrays,source_sha):
    if not times or any(k not in arrays or len(arrays[k])!=len(times) for k in FIELDS):
        raise ValueError('P92_SOURCE_ARRAY_LENGTH_MISMATCH')
    if any(not isinstance(t,str) or not t.endswith('Z') for t in times):
        raise ValueError('P92_SOURCE_TIME_NOT_EXPLICIT_UTC')
    stamps=[dt.datetime.fromisoformat(t.replace('Z','+00:00')) for t in times]
    if len(set(stamps))!=len(stamps) or any(b-a!=dt.timedelta(hours=1) for a,b in zip(stamps,stamps[1:])):
        raise ValueError('P92_HOURLY_SOURCE_GAP_OR_DUPLICATE')
    if stamps[0].hour!=0 or len(stamps)%24:
        raise ValueError('P92_PARTIAL_UTC_DAY')
    output=[]
    for j in range(0,len(times),24):
        if stamps[j+23].date()!=stamps[j].date():
            raise ValueError('P92_DAY_TIMESTAMP_MISMATCH')
        pack=tuple({k:float(arrays[k][i]) for k in FIELDS} for i in range(j,j+24))
        output.append(Day(stamps[j].date(),pack,source_sha))
    return output

def seam_cost(prev,nxt):
    scales={'temperature_2m':6.,'dew_point_2m':5.,'surface_pressure':10.,
            'relative_humidity_2m':40.,'cloud_cover':70.,'wind_speed_10m':8.}
    distance=sum(((nxt[k]-prev[k])/s)**2 for k,s in scales.items())
    distance+=.8*(bool(prev['precipitation']>0)!=bool(nxt['precipitation']>0))
    return min(80.,distance)

def sampler(donors,target_dates,seed,mode='joint_day_blocks'):
    if mode not in ('joint_day_blocks','iid_hourly_joint_vector'):
        raise ValueError('P92_UNKNOWN_CONTROL_METHOD')
    if not donors or not target_dates or len(set(target_dates))!=len(target_dates):
        raise ValueError('P92_EMPTY_OR_DUPLICATE_COHORT')
    if any(d.date.year in {t.year for t in target_dates} for d in donors):
        raise ValueError('P92_TARGET_YEAR_SOURCE_LEAKAGE')
    if any((b-a).days!=1 for a,b in zip(target_dates,target_dates[1:])):
        raise ValueError('P92_TARGET_DATE_NOT_CONTIGUOUS')
    monthly=defaultdict(list)
    for d in donors:monthly[d.date.month].append(d)
    rng=random.Random(seed)
    output=[];used=set()
    for target in target_dates:
        candidates=monthly[target.month]
        if not candidates:raise ValueError('P92_NO_SOURCE_IN_TARGET_MONTH')
        if mode=='iid_hourly_joint_vector':
            vectors=tuple(dict(rng.choice(candidates).vectors[h]) for h in range(24))
            sha=hashlib.sha256(json.dumps(vectors,sort_keys=True).encode()).hexdigest()
            output.append(Day(target,vectors,sha))
            continue
        eligible=[d for d in candidates if d.date not in used]
        if not eligible:eligible=candidates[:];used.clear()
        last=output[-1].vectors[-1] if output else None
        weights=[math.exp(-.45*seam_cost(last,d.vectors[0])) if last else 1. for d in eligible]
        cutoff=rng.random()*sum(weights)
        selected=eligible[-1]
        for d,w in zip(eligible,weights):
            cutoff-=w
            if cutoff<=0:
                selected=d;break
        used.add(selected.date)
        output.append(Day(target,tuple(dict(v) for v in selected.vectors),
                          selected.original_sha256))
    return output

def diagnostics(days):
    if not days:raise ValueError('P92_NO_HOURLY_WEATHER_SERIES')
    vectors=[v for d in days for v in d.vectors]
    state=[regime(v) for v in vectors]
    c=Counter(state);n=Counter(zip(state,state[1:]))
    wet=[v for v in vectors if v['precipitation']>0]
    dry=[v for v in vectors if v['precipitation']==0]
    def contrast(key):
        return (statistics.fmean(v[key] for v in wet)-statistics.fmean(v[key] for v in dry)) if wet and dry else None
    summer_wet=[];summer_dry=[]
    for d in days:
        for h in range(9,16):
            v=d.vectors[h]
            (summer_wet if v['precipitation']>0 else summer_dry).append(v['shortwave_radiation'])
    tsolar=(statistics.fmean(summer_wet)-statistics.fmean(summer_dry)) if summer_wet and summer_dry else None
    spells=[];current=0
    for st in state:
        if st=='wet':current+=1
        elif current:spells.append(current);current=0
    if current:spells.append(current)
    prev_wet=sum(v for (a,b),v in n.items() if a=='wet')
    seams=[abs(a.vectors[-1]['temperature_2m']-b.vectors[0]['temperature_2m'])
           for a,b in zip(days,days[1:])]
    return {'n_hours':len(vectors),'n_days':len(days),
            'wet_hour_fraction':c['wet']/len(state),
            'n_wet_spells':len(spells),
            'mean_wet_spell_hours':statistics.fmean(spells) if spells else 0.,
            'P_next_wet_given_wet':n[('wet','wet')]/prev_wet if prev_wet else None,
            'wet_minus_dry_RH_pp':contrast('relative_humidity_2m'),
            'wet_minus_dry_cloud_pp':contrast('cloud_cover'),
            'wet_minus_dry_GHI_W_m2_daylight_UTC9to15':tsolar,
            'seam_mean_T_jump_C':statistics.fmean(seams) if seams else None,
            'regime_counts':dict(sorted(c.items())),
            'transition_count':{a+'->'+b:v for (a,b),v in sorted(n.items())}}

KEY_METRICS=('wet_hour_fraction','mean_wet_spell_hours',
             'P_next_wet_given_wet','wet_minus_dry_RH_pp',
             'wet_minus_dry_cloud_pp','wet_minus_dry_GHI_W_m2_daylight_UTC9to15')

def scoring(reference,blocks,iid):
    original,block,basic=(diagnostics(x) for x in (reference,blocks,iid))
    def diff(p):return {k:(abs(original[k]-p[k]) if original[k] is not None and p[k] is not None else None) for k in KEY_METRICS}
    b=diff(block);i=diff(basic)
    return {'original_ERA5_2022':original,'joint_day_blocks':block,
            'iid_joint_hourly_control':basic,'absolute_difference_block':b,
            'absolute_difference_hourly_control':i,
            'block_better':[k for k in KEY_METRICS if b[k] is not None and i[k] is not None and b[k]<i[k]-1e-12],
            'block_worse':[k for k in KEY_METRICS if b[k] is not None and i[k] is not None and b[k]>i[k]+1e-12],
            'block_equal':[k for k in KEY_METRICS if b[k] is not None and i[k] is not None and abs(b[k]-i[k])<=1e-12],
            'unavailable':[k for k in KEY_METRICS if b[k] is None or i[k] is None]}

def lineage(days):
    return {'algorithm':ALGORITHM,'N_generated_days':len(days),
            'original_ERA5_source_response_sha256s':sorted({d.original_sha256 for d in days}),
            'source_joints_unchanged_within_24h_blocks':True,
            'actual_rain_cloud_RH_solar_wind_vectors_preserved':True,
            'not_8760_EPW':True,'production_epw_ready':False}
