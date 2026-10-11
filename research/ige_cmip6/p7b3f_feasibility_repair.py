#!/usr/bin/env python3
"""IGE P7B.3F independent minimal-relaxation solar cap repair.

The 0.65 TOA-fraction cap of P7B.3C is an *engineering hypothesis*, not an
observationally established upper bound. A source day exceeding that cap is
conserved by the smallest convex relaxation towards TOA which admits its GHI.
No original day is silently clipped. TOA is only a conservative working cap:
short-duration cloud enhancement can exceed it in real observed surface GHI.

Original native model calendar and NOAA approximate solar vectors from P7B.3E
are inherited; this phase does not prove global physical realism or new EPW.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, random
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean

from p7b3c_conditional_solar import (
    SEASONS, build_library, load_original_station, project_energy, sha,
    generate as legacy_generate,
)
from p7b3e_multigcm_radiometric_closure import (
    MODELS, FROZEN_ALPHA, original_source, solar_vectors, cap_profile,
    source_dirs, reconstruct_components,
)

EPS = 1e-9
STRESS_YEARS = (2012, 2013, 2014)
SEEDS = (0, 1, 2)


def minimum_relaxed_cap(geometry, source_daily_ghi, tolerance=EPS):
    """Return minimal cap interpolation a_old + lambda*(TOA-a_old).

    Never exceed TOA in this conservative research screening model. Reject
    days incompatible with TOA rather than rescale original climate energy.
    """
    if len(geometry) != 24:
        raise ValueError('24 integrated source-hour solar vectors required')
    if not math.isfinite(source_daily_ghi) or source_daily_ghi < 0:
        raise ValueError('Invalid immutable daily GHI input')
    toa = [float(g[1]) for g in geometry]
    original_caps = cap_profile(geometry, .65)
    if any(not math.isfinite(t+c) or t<0 or c<0 or c>t+1e-12
           for t,c in zip(toa,original_caps)):
        raise ValueError('Incorrect TOA or old cap geometry')
    toa_daily = sum(toa)
    initial_daily = sum(original_caps)
    if source_daily_ghi > toa_daily + tolerance:
        raise ValueError('DAILY_GHI_EXCEEDS_CONSERVATIVE_TOA_BOUND')
    if source_daily_ghi <= initial_daily + 1e-12:
        return original_caps, 0., initial_daily, toa_daily
    # Analytic fraction is unique for the sum of affine hourly upper bounds.
    slack = toa_daily-initial_daily
    if slack <= 0:
        raise ValueError('NONPOSITIVE_CAP_RELAXATION_CAPACITY')
    # A 1e-9 kWh/m² summation margin is needed by the existing
    # bisection-based exact-energy projector. Without it, its finite
    # bracketing procedure can never attain a target exactly at the cap.
    # The margin is only numerical; the relaxation is minimal to 1e-9.
    numerical_margin = min(1e-9, max(0., toa_daily-source_daily_ghi))
    fraction = (source_daily_ghi+numerical_margin-initial_daily)/slack
    if fraction > 1.+1e-9:
        raise ValueError('DAILY_GHI_EXCEEDS_CONSERVATIVE_TOA_BOUND')
    fraction = min(1.,max(0.,fraction))
    caps=[base+fraction*(t-base) for t,base in zip(toa,original_caps)]
    if source_daily_ghi > sum(caps)+1e-10:
        raise ValueError('RELAXED_CAP_NOT_FEASIBLE')
    return caps, fraction, initial_daily, toa_daily


def prepare_daily(days,lat,lon,stress_years=STRESS_YEARS):
    """Pin same immutable source/day/geometry; keep diagnostics for all years."""
    prepared={}
    stats=Counter()
    relaxations=[]
    exceptions=[]
    example_rows=[]
    rejected=[]
    for day,energy in sorted(days.items()):
        g=solar_vectors(day,lat,lon)
        stats['historical_original_days']+=1
        if energy>sum(cap_profile(g,.65))+EPS:
            stats['original_frozen_cap_infeasible_days']+=1
        if energy>sum(v[1] for v in g)+EPS:
            stats['original_daily_exceeds_toa']+=1
        try:
            caps,lam,old_total,toa_total=minimum_relaxed_cap(g,energy)
        except ValueError as e:
            rejected.append({'date':day.isoformat(),'reason':str(e),
                             'original_energy_kwh_m2':energy})
            continue
        stats['conservative_repair_admitted_days']+=1
        if lam>0:
            stats['historical_days_requiring_relaxation']+=1
            relaxations.append(lam)
        if day.year in stress_years:
            clear=[v[2] for v in g]
            base=project_energy(clear,energy,caps)
            prepared[day]={'records':[(v[0],base[h],v[1],v[2]) for h,v in enumerate(g)],
                           'caps':caps,'fraction':lam,'source_energy':energy,
                           'old_cap_energy':old_total,'toa_day':toa_total}
            stats['stress_model_days']+=1
            if lam>0:
                stats['stress_days_repaired']+=1
                if len(example_rows)<12:
                    example_rows.append({'date':day.isoformat(),
                        'original_ghi_kwh_m2_day':energy,
                        'initial_cap_kwh_m2_day':old_total,
                        'relaxation_lambda':lam,
                        'toa_kwh_m2_day':toa_total})
    return prepared,stats,relaxations,rejected,example_rows


def generate_repaired(prepared,library,seed,alpha=FROZEN_ALPHA):
    """Frozen M2 sampler; only ceiling is replaced by precomputed repair.

    The copied logic is intentionally explicit so a feasible original day
    can be tested against immutable P7B.3C generate() byte-for-byte.
    """
    if not 0<=alpha<=1:
        raise ValueError('invalid alpha')
    result={};max_energy_error=0.;max_cap_error=0.
    for day,datum in prepared.items():
        records=datum['records']; caps=datum['caps']
        base=[v[1] for v in records]; clear=[v[3] for v in records]
        # Legacy M2 uses sum(base) as its target (not source float directly).
        # This preserves exact seeded outputs for every unchanged day.
        target=sum(base)
        if alpha==0:
            hourly=base
        else:
            pool=library[SEASONS[day.month]]
            if not pool:
                raise ValueError('Missing registered training season')
            kt=target/max(.1,sum(clear))
            candidates=sorted(pool,key=lambda a:(abs(a['kt']-kt),a['day']))[:15]
            hashed=int.from_bytes(hashlib.sha256(f'{seed}:{day}'.encode()).digest()[:8],'big')
            match=random.Random(hashed).choice(candidates)
            cloud=[max(0.,c*x) for c,x in zip(clear,match['ratios'])]
            raw=[(1-alpha)*b+alpha*v for b,v in zip(base,cloud)]
            hourly=project_energy(raw,target,caps)
        error=abs(sum(hourly)-datum['source_energy'])
        max_energy_error=max(max_energy_error,error)
        for (t,_,toa,_),cap,v in zip(records,caps,hourly):
            if not 0<=v<=cap+1e-9 or v>toa+1e-9:
                raise ValueError('Hourly GHI violates relaxed cap/TOA')
            max_cap_error=max(max_cap_error,max(0.,v-cap))
            result[t]=v
    return result,{'max_daily_energy_residual':max_energy_error,
                   'max_hourly_cap_residual':max_cap_error,
                   'complete_days':len(prepared),'complete_hours':len(result)}


def radiometric_audit(prepared,hourly):
    """Erbs GHI = DHI + coszen*DNI is algebraic only; no independent DHI."""
    max_error=0.;max_dni_toa_error=0.;totals=Counter()
    example=[]
    for day,datum in prepared.items():
        for dt,base,toa,clear in datum['records']:
            ghi=hourly[dt]
            ecc=1+.033*math.cos(2*math.pi*(dt.timetuple().tm_yday-3)/365.25)
            cos=max(0.,min(1.,toa/(1.361*ecc))) if toa else 0.
            dhi,dni,err=reconstruct_components(ghi,toa,cos)
            max_error=max(max_error,err)
            if cos>=.065:
                max_dni_toa_error=max(max_dni_toa_error,max(0.,dni-(toa/cos)))
            totals['GHI']+=ghi;totals['DHI']+=dhi;totals['DNI_normal']+=dni
            if day.year==2013 and len(example)<96:
                example.append({'model_hour':dt.isoformat(),
                   'GHI_M0_kwh_m2_h':base,'GHI_M2_repaired_kwh_m2_h':ghi,
                   'DHI_Erbs_kwh_m2_h':dhi,'DNI_Erbs_kwh_m2_normal_h':dni,
                   'TOA_horizontal_kwh_m2_h':toa,'relaxation_lambda':datum['fraction'],
                   'cap_hour_kwh_m2_h':datum['caps'][dt.hour]})
    return {'max_radiometric_identity_residual_kwh_m2_h':max_error,
            'max_dni_above_normal_toa_kwh_m2_h':max_dni_toa_error,
            'totals_kwh_m2':dict(totals)},example


def compute_model(model,days,lat,lon,library,seeds=SEEDS):
    prepared,counts,lambdas,rejected,examples=prepare_daily(days,lat,lon)
    if rejected:
        raise ValueError(f'Conservative TOA infeasible model-days {model}: {rejected[:2]}')
    if counts['stress_model_days'] != sum(day.year in STRESS_YEARS for day in days):
        raise ValueError('Lost one or more registered original stress days')
    baseline_input={d:v['records'] for d,v in prepared.items() if v['fraction']==0}
    for seed in seeds:
        if not baseline_input:break
        # Immutability test on days where old cap did not need repair:
        old,_=legacy_generate(baseline_input,library,FROZEN_ALPHA,seed)
        new,_=generate_repaired({d:prepared[d] for d in baseline_input},library,seed)
        if old!=new:
            raise ValueError('Frozen prior M2 changed on originally feasible day')
    runs={};samples=[]
    for seed in seeds:
        hours,diag=generate_repaired(prepared,library,seed)
        radi,example=radiometric_audit(prepared,hours)
        if diag['max_daily_energy_residual']>1e-9 or radi['max_radiometric_identity_residual_kwh_m2_h']>1e-10:
            raise ValueError('Repaired daily / component closure violation')
        runs[str(seed)]={**diag,**radi}
        if seed==0:
            samples=[{'model':model,**v} for v in example]
    return {'model':model,'original_historical_days':len(days),
       'original_native_calendar_days':dict(Counter(d.year for d in days)),
       'counts':dict(counts),
       'relaxation_lambda':{'mean_repaired_days':fmean(lambdas) if lambdas else 0.,
         'maximum':max(lambdas,default=0.),'number_of_repaired_days':len(lambdas)},
       'original_ghi_dropped_or_modified':False,
       'frozen_old_method_exact_on_unrepaired_days':True,
       'originals_infeasible_even_with_toa':len(rejected),
       'first_repaired_days':examples,
       'runs':runs},samples


def run(source_root,graz_original,out,seeds=SEEDS,models=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    dirs=source_dirs(source_root) if models is None else models
    training,counts=load_original_station(graz_original,'record_start',(2007,2008))
    lib=build_library(training)
    result=[];sources=[];sample=[]
    for name in MODELS:
        values,coords,source=original_source(dirs[name],name)
        model_output,rows=compute_model(name,values,*coords,lib,seeds=seeds)
        result.append(model_output);sources.append(source);sample.extend(rows)
        print('P7B3F',name,'model days',len(values),'repaired stress days',model_output['counts'].get('stress_days_repaired',0),'dropped',model_output['originals_infeasible_even_with_toa'],flush=True)
    with (out/'p7b3f_8gcm_repair_metrics.csv').open('w',newline='') as f:
        rows=[{'model':m['model'],'historical_days':m['original_historical_days'],
           'historical_frozen_cap_fail':m['counts'].get('original_frozen_cap_infeasible_days',0),
           'historical_repaired_days':m['counts'].get('historical_days_requiring_relaxation',0),
           'historical_toa_infeasible':m['counts'].get('original_daily_exceeds_toa',0),
           'stress_model_days':m['counts']['stress_model_days'],
           'stress_repaired_days':m['counts'].get('stress_days_repaired',0),
           'stress_valid_hours':m['runs']['0']['complete_hours'],
           'max_lambda':m['relaxation_lambda']['maximum'],
           'max_energy_residual':max(k['max_daily_energy_residual'] for k in m['runs'].values()),
           'max_radiometric_residual':max(k['max_radiometric_identity_residual_kwh_m2_h'] for k in m['runs'].values())}
          for m in result]
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    with (out/'p7b3f_hourly_seed0_2013_excerpt.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(sample[0]));writer.writeheader();writer.writerows(sample)
    audit={'stage':'IGE_P7B3F_MINIMAL_HARD_CAP_RELAXATION_WITH_EXACT_DAILY_GHI',
       'research_status':'ORIGINAL_SOURCE_RESEARCH_REPAIR','scientific_release':'NOT_YET_VALIDATED',
       'production_epw_ready':False,'n_models':len(result),'seeds':list(seeds),
       'source_Graz_qc_sha256':sha(graz_original),'source_model_sha256':sources,
       'initial_cap':'min(TOA,max(1.25*Haurwitz,0.65*TOA))',
       'repair':'caps=initial_cap+lambda*(TOA-initial_cap), lambda smallest feasible',
       'toa_is_conservative_hourly_screen_not_absolute_observed_GHI_limit':True,
       'short_duration_cloud_enhancement_may_exceed_toa_horizontal':True,
       'historical_native_calendar_not_converted_to_EPW':True,
       'ground_measured_DHI_DNI_qualified':False,
       'original_daily_gcm_source_energy_preserved':True,
       'multimodel':result,
       'limitations':['NOAA simplified zenith and 5-minute geometric integration, not SPA/NREL reference',
           'CF noleap GCM calendar must be mapped before EPW; this study does NOT resolve mapping',
           'TOA hard cap is a conservative modeling hypothesis, not observational universal law',
           'The 0.65 low-sun floor remains legacy on feasible days; minimal relaxation only restores compatibility',
           'No independent sensor DHI/DNI test and no hourly cloud-enhancement reference',
           'GCM ensemble values represent Graz grid, not multiple independent climates',
           'No full-year EPW nor building-demand simulation validation'],
       'derived_sha256':{p.name:sha(p) for p in out.glob('*.csv')}}
    (out/'p7b3f_repair_science_audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
    return audit

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',required=True)
    p.add_argument('--graz-original',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--seeds',type=int,default=3)
    a=p.parse_args()
    if not 1<=a.seeds<=20:raise ValueError('unregistered seed count')
    run(a.source_root,a.graz_original,a.out,seeds=tuple(range(a.seeds)))