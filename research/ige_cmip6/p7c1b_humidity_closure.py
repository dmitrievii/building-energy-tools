#!/usr/bin/env python3
"""IGE P7C.1B: conservative MONTHLY specific-humidity closure for P7C.1 EPW.

The source EPW daily/hourly patterns are not climate forecasts. A monthly GCM
huss ratio supplies only a monthly target: do NOT promise exact daily q.
Constrained L2 projection by month minimizes sum((q_i-qtarget_i)^2) with
1 <= RH <= 100% and the monthly target sum(q_i)=sum(qtarget_i).
No new pressure/temperature/wind/solar data, no artificial measured wind.

No actual user Graz Contemporary EPW is included in these research artifacts.
The historic P7B4 base is SYNTHETIC; passing the CI does NOT close the
'real contemporary EPW' requirement.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, re, statistics
from collections import defaultdict
from pathlib import Path
from p7c1_epw_morphing import (
    read_epw, write_epw, write_csv, sha, WINDOWS,
    q_from_rh, rh_from_q, dewpoint_from_rh
)

BASE_SHA='2e45abbcba52c49e51e3811676ba37167bc8700f697e13032ee103ff8f3f7012'
SENTINEL='ORIGINAL_CONTEMPORARY_FILE_NOT_SUPPLIED'
RH_FLOOR=1.0
RH_CEILING=100.0
Q_TOL=1e-9


def minimum_adjustment_projection(target,lower,upper,tol=1e-10):
    """Euclidean projection onto a box intersected with an affine sum hyperplane.

    KKT solution: q[i] = clip(target[i] + lambda, lower[i], upper[i]);
    lambda is globally shared within the month. Conserves the supplied sum.
    """
    if not target or len(target)!=len(lower) or len(target)!=len(upper):
        raise ValueError('Wrong humidity allocation dimensions')
    for t,lo,hi in zip(target,lower,upper):
        if not all(map(math.isfinite,(t,lo,hi))) or not 0<=lo<=hi<.2 or not 0<=t<.2:
            raise ValueError('Invalid bounded moisture data')
    target_total=math.fsum(target)
    if target_total < math.fsum(lower)-tol or target_total>math.fsum(upper)+tol:
        raise ValueError('Monthly humidity target outside physically attainable bounds')
    if abs(target_total-math.fsum(lower))<=tol:return list(lower)
    if abs(target_total-math.fsum(upper))<=tol:return list(upper)
    low=min(lo-t for t,lo in zip(target,lower))-1e-8
    high=max(hi-t for t,hi in zip(target,upper))+1e-8
    for _ in range(90):
        mid=(low+high)/2
        amount=math.fsum(max(lo,min(hi,t+mid)) for t,lo,hi in zip(target,lower,upper))
        if amount < target_total:low=mid
        else:high=mid
    lam=(low+high)/2
    out=[max(lo,min(hi,t+lam)) for t,lo,hi in zip(target,lower,upper)]
    if abs(math.fsum(out)-target_total)>max(tol,1e-11*len(out)):
        raise ValueError('Water-filling monthly sum residual')
    return out


def load_monthly_ratios(path):
    with Path(path).open(newline='',encoding='utf8') as f:
        rows=list(csv.DictReader(f))
    if len(rows)!=12 or set(int(r['month']) for r in rows)!=set(range(1,13)):
        raise ValueError('Requires exactly twelve original GCM monthly change signals')
    signal={int(r['month']):float(r['specific_humidity_ratio']) for r in rows}
    if any(not math.isfinite(r) or not .35<=r<=2.5 for r in signal.values()):
        raise ValueError('Humidity ratio outside P7C.1 registered source range')
    return signal


def check_baseline_provenance(baseline, provenance, require_authentic=False):
    _,_,meta=read_epw(baseline)
    if require_authentic:
        if not provenance:raise ValueError('Original contemporary EPW provenance is required; no synthetic substitution')
        p=json.loads(Path(provenance).read_text(encoding='utf8'))
        required=('original_filename','provider','source_description','sha256','user_authorized_research_use')
        if any(not p.get(k) for k in required) or not p['user_authorized_research_use']:
            raise ValueError('Incomplete contemporary source provenance')
        if p['sha256']!=meta['baseline_epw_sha256'] or Path(p['original_filename']).name!=Path(baseline).name:
            raise ValueError('Original contemporary EPW SHA/name provenance mismatch')
        if 'P7B' in str(Path(baseline).name) or 'P7B' in p['original_filename']:
            raise ValueError('Synthetic historical P7B cannot claim authentic Contemporary baseline')
        return {'source_status':'AUTHENTIC_USER_SUPPLIED_EPW_SOURCE_HASH_CONFIRMED',
                'source_metadata_verified':True,
                'source_represents_observed_real_calendar_weather':False,
                'source_hash':meta['baseline_epw_sha256'],'source_info':p}
    if meta['baseline_epw_sha256']!=BASE_SHA:
        raise ValueError('The preflight requires the pinned original P7B4 synthetic EPW, no silent replacement')
    return {'source_status':'P7B4_SYNTHETIC_HISTORICAL_RESEARCH_PREFLIGHT_NOT_REAL_CONTEMPORARY',
            'source_metadata_verified':True,'source_represents_observed_real_calendar_weather':False,
            'source_hash':meta['baseline_epw_sha256']}


def hourly_redistribution(base_rows, morphed_rows, ratios):
    if len(base_rows)!=8760 or len(morphed_rows)!=8760:
        raise ValueError('Full EPW hourly input missing')
    new=[r.copy() for r in morphed_rows]
    by_month=defaultdict(list)
    tval=[];initial_saturated=[];prior_q=[];target_q=[];lower=[];upper=[];ps=[]
    for i,(b,r) in enumerate(zip(base_rows,morphed_rows)):
        if b[:5]!=r[:5]:raise ValueError('Original/morphed hour identity lost')
        m=int(r[1]);T=float(r[6]);p=float(r[9]);t0=float(b[6]);rh0=float(b[8]);
        q0=q_from_rh(t0,rh0,p);qt=q0*ratios[m]
        lo=q_from_rh(T,RH_FLOOR,p);hi=q_from_rh(T,RH_CEILING,p)
        prior_q.append(q_from_rh(T,float(r[8]),p));tval.append(T);ps.append(p)
        target_q.append(qt);lower.append(lo);upper.append(hi)
        initial_saturated.append(qt>hi+1e-12);by_month[m].append(i)
    out_q=[None]*8760;months=[]
    for m in range(1,13):
        inds=by_month[m]
        if not inds:raise ValueError('Missing morph month')
        proposed=[target_q[i] for i in inds];lo=[lower[i] for i in inds];hi=[upper[i] for i in inds]
        solved=minimum_adjustment_projection(proposed,lo,hi)
        for i,x in zip(inds,solved):out_q[i]=x
        months.append({'month':m,'hours':len(inds),'target_monthly_mean_q_kg_kg':math.fsum(proposed)/len(inds),
            'projected_monthly_mean_q_kg_kg':math.fsum(solved)/len(inds),
            'prior_P7C1_monthly_mean_q_kg_kg':math.fsum(prior_q[i] for i in inds)/len(inds),
            'raw_saturation_hours':sum(initial_saturated[i] for i in inds),
            'after_saturation_hours':sum(abs(v-h)<1e-9 for v,h in zip(solved,hi)),
            'hourly_abs_q_redistribution_sum_kg_kg':math.fsum(abs(v-t) for v,t in zip(solved,proposed)),
            'max_hourly_abs_q_adjustment_kg_kg':max(abs(v-t) for v,t in zip(solved,proposed)),
            'target_excess_over_saturation_capacity_ratio':math.fsum(proposed)/math.fsum(hi),
            'monthly_q_closure_abs_kg_kg':abs(math.fsum(proposed)-math.fsum(solved))/len(inds)})
    rh_old=[float(r[8]) for r in morphed_rows];rh_new=[];daily=[];sat_hours=0
    for i,(r,q) in enumerate(zip(new,out_q)):
        T=tval[i];p=ps[i]
        rh=rh_from_q(T,q,p)
        if not RH_FLOOR-1e-5<=rh<=RH_CEILING+1e-5:
            raise ValueError('Projected RH violated physical bounds')
        rh=max(RH_FLOOR,min(RH_CEILING,rh))
        dp=dewpoint_from_rh(T,rh)
        if dp>T+1e-8:raise ValueError('Projected dew point above dry bulb')
        r[7]=f'{dp:.8f}';r[8]=f'{rh:.8f}';rh_new.append(rh)
        sat_hours+=abs(rh-100)<1e-6
    for i in range(0,8760,24):
        ins=list(range(i,i+24));day=(new[i][0],new[i][1],new[i][2]);
        daily.append({'date':'-'.join(map(lambda z:f'{int(z):02d}',day)),
          'target_daily_mean_q_kg_kg':math.fsum(target_q[k] for k in ins)/24,
          'adjusted_daily_mean_q_kg_kg':math.fsum(out_q[k] for k in ins)/24,
          'daily_q_mean_delta_kg_kg':math.fsum(out_q[k]-target_q[k] for k in ins)/24,
          'raw_saturation_hours':sum(initial_saturated[k] for k in ins),
          'adjusted_RH_100_hours':sum(abs(rh_new[k]-100)<1e-6 for k in ins),
          'max_RH_adjustment_pp':max(abs(rh_new[k]-rh_old[k]) for k in ins)})
    other_changed=sum(r[ix]!=old[ix] for r,old in zip(new,morphed_rows) for ix in range(35) if ix not in (7,8))
    if other_changed:raise ValueError('Non-humidity field changed during humidity closure')
    total_month_err=max(row['monthly_q_closure_abs_kg_kg'] for row in months)
    if total_month_err>Q_TOL:raise ValueError('Monthly specific humidity not conserved')
    jumps=sum(abs(a-b)>20 for a,b in zip(rh_new[:-1],rh_new[1:]))
    jumps_prev=sum(abs(a-b)>20 for a,b in zip(rh_old[:-1],rh_old[1:]))
    info={'monthly_q_closed':True,'max_month_q_mean_residual_kg_kg':total_month_err,
          'monthly_q_targets_are_GCM_climatological_not_daily_model_event_targets':True,
          'daily_q_targets_not_enforced':True,
          'raw_saturation_hours':sum(initial_saturated),'after_RH_100_hours':sat_hours,
          'RH_above_100_hours':sum(float(r[8])>100.00001 for r in new),
          'max_absolute_hourly_RH_adjustment_pp':max(abs(a-b) for a,b in zip(rh_new,rh_old)),
          'max_daily_mean_q_reallocation_kg_kg':max(abs(r['daily_q_mean_delta_kg_kg']) for r in daily),
          'new_RH_jump_above_20pp_hours':jumps,'old_RH_jump_above_20pp_hours':jumps_prev,
          'new_RH_max_adjacent_jump_pp':max(abs(a-b) for a,b in zip(rh_new[:-1],rh_new[1:])),
          'mean_target_hourly_q_kg_kg':math.fsum(target_q)/8760,
          'mean_adjusted_hourly_q_kg_kg':math.fsum(out_q)/8760,
          'mean_prior_hourly_q_kg_kg':math.fsum(prior_q)/8760,
          'source_wind_direction_changed':False,
          'humidity_validation_independent_observations':False,
          'minimum_L2_adjustment_q_bounded_monthly_in_kg_kg':True}
    return new,months,daily,info


def read_source_manifest(path):
    o=json.loads(Path(path).read_text(encoding='utf8'))
    if o.get('stage')!='IGE_P7C1_EPW_BASED_FUTURE_MORPHING' or o.get('production_epw_ready') is not False:
        raise ValueError('Wrong original P7C1 science audit')
    if sorted(o['results'])!=sorted(WINDOWS):raise ValueError('Missing scenario in audited source')
    return o


def run(original_base,p7c1_dir,out, real_baseline=None, provenance=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    parent=read_source_manifest(Path(p7c1_dir)/'p7c1_source_science_audit.json')
    authentic=real_baseline is not None
    baseline=real_baseline if authentic else original_base
    source_info=check_baseline_provenance(baseline,provenance,require_authentic=authentic)
    headers,source,meta=read_epw(baseline)
    if authentic:
        # A morphed file from a different EPW MUST NEVER be used: caller must
        # first regenerate P7C1 with this exact authentic baseline.
        if parent['baseline']['baseline_epw_sha256']!=sha(baseline):
            raise ValueError('P7C1 scenarios were not regenerated from the authentic Contemporary EPW baseline')
    else:
        if parent['baseline']['baseline_epw_sha256']!=BASE_SHA:
            raise ValueError('Original synthetic baseline P7C1 parent source mismatch')
    overall={'stage':'IGE_P7C1B_REAL_BASELINE_AND_HUMIDITY_CLOSURE',
       'status':'RESEARCH_HUMIDITY_MONTHLY_CONSERVATION_SCIENTIFIC_LIMITATIONS_OPEN',
       'real_contemporary_EPWs_generated':authentic,
       'authentic_user_original_contemporary_source_verified':authentic,
       'research_only':True,'production_epw_ready':False,
       'original_p7c1_audit_sha256':sha(Path(p7c1_dir)/'p7c1_source_science_audit.json'),
       'baseline_source':source_info,'source_hour_count':8760,
       'no_event_day_matching':True,'mode':'authentic_user_supplied' if authentic else 'synthetic_P7B4_preflight',
       'limitations':['Authentic user-provided Graz Contemporary EPW was NOT accessible in this execution; real-baseline closeout is blocked' if not authentic else 'User-supplied original EPW may represent Meteonorm synthetic typical-year weather, not directly measured actual-year observations',
         'Monthly GCM huss-ratio conservation is algorithmic; original GCM and EPW are not temporally paired',
         'Monthly L2 q projection can alter individual days, hour-hour persistence, and RH dynamics; this is not measured validation',
         'Original GCM surface pressure not available; use baseline EPW pressure',
         'No external EnergyPlus simulation or independent future observational validation',
         'Other P7C1 radiation/wind/rain/cloud constraints remain unchanged'],
       'results':{}}
    for window in WINDOWS:
        stem=f'Graz_CanESM5_{window}_EPW_MORPH_P7C1_RESEARCH_ONLY'
        original=Path(p7c1_dir)/(stem+'.epw');mfile=Path(p7c1_dir)/(stem+'_monthly_delta.csv')
        srcsha=parent['results'][window]['files_sha256']
        for p in (original,mfile):
            if sha(p)!=srcsha[p.name]:raise ValueError('P7C1 parent source SHA mismatch: '+p.name)
        h,rows,_=read_epw(original)
        ratios=load_monthly_ratios(mfile)
        adjusted,monthly,daily,info=hourly_redistribution(source,rows,ratios)
        hh=[line.copy() for line in h]
        hh[5]=['COMMENTS 1','P7C1B research: GCM huss monthly mean conserved by bounded minimal-q projection; not real future weather']
        hh[6]=['COMMENTS 2','RH/dewpoint-only adjustment vs P7C1. Preserve baseline wind direction and all other fields. See month/day QC; research only']
        basename=f'Graz_CanESM5_{window}_P7C1B_HUMIDITY_CLOSED_RESEARCH_ONLY'
        epw=out/(basename+'.epw');month_csv=out/(basename+'_humidity_monthly.csv');day_csv=out/(basename+'_humidity_daily.csv')
        write_epw(epw,hh,adjusted)
        rh,rv,_=read_epw(epw)
        if any(rv[i][ix]!=rows[i][ix] for i in range(8760) for ix in range(35) if ix not in (7,8)):
            raise ValueError('EPW readback changed unrelated weather fields')
        write_csv(month_csv,monthly);write_csv(day_csv,daily)
        overall['results'][window]={'humidity':info,'per_month':monthly,
           'output_files_sha256':{x.name:sha(x) for x in (epw,month_csv,day_csv)},
           'original_p7c1_file_sha256':srcsha[original.name],
           'original_monthly_signal_sha256':srcsha[mfile.name]}
        print(f'P7C1B {window} q_closed={info["monthly_q_closed"]} clip_before={info["raw_saturation_hours"]} clip_after={info["after_RH_100_hours"]} RH_jumps>20={info["new_RH_jump_above_20pp_hours"]}',flush=True)
    overall['total_file_count']=len(list(out.glob('*')))+1
    (out/'p7c1b_humidity_science_audit.json').write_text(json.dumps(overall,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    return overall


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--original-p7b4-baseline',required=True)
    ap.add_argument('--p7c1-source',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--real-contemporary-epw')
    ap.add_argument('--real-baseline-provenance')
    o=ap.parse_args()
    run(o.original_p7b4_baseline,o.p7c1_source,o.out,o.real_contemporary_epw,o.real_baseline_provenance)
if __name__=='__main__':main()