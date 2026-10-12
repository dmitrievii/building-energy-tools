#!/usr/bin/env python3
"""IGE P7C.1C: research hourly moisture coherence under exact monthly q targets.

Use an authentic, SHA-pinned source EPW and four previously source-gated P7C.1B
research EPWs. Optimize q (g/kg) with physical q limits, monthly conservation,
reference-event-aware RH jump penalty, and soft daily target preference.
Only RH/dewpoint of P7C.1B may change. No claim of independent validation.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from pathlib import Path
from collections import defaultdict
import numpy as np
from p7c1_epw_morphing import read_epw,write_epw,sha,WINDOWS, q_from_rh,rh_from_q,dewpoint_from_rh
from p7c1b_humidity_closure import load_monthly_ratios

EPSILON=0.62198  # must match P7C.1 source psychrometric epsilon exactly
RH_MIN=1.0
RH_MAX=100.0

def saturation_vapor_pressure_pa(t):
    # Formula used in parent P7C.1 q_from_rh; must verify strict numerical parity.
    # use q_from_rh(T,100,pressure) to reconstruct e_s via q inverse.
    p=101325.
    q=q_from_rh(float(t),100.,p)
    return (q*p)/(EPSILON+(1-EPSILON)*q)

def arrays_for_moisture(baseline,prior,ratios):
    if len(baseline)!=len(prior) or len(prior)!=8760:
        raise ValueError('Expected aligned complete 8760h EPW series')
    if any(a[:5]!=b[:5] for a,b in zip(baseline,prior)):
        raise ValueError('Calendar identity mismatch')
    month=np.array([int(r[1]) for r in prior]); t=np.array([float(r[6]) for r in prior]);
    p=np.array([float(r[9]) for r in prior]); base_t=np.array([float(r[6]) for r in baseline]);
    base_rh=np.array([float(r[8]) for r in baseline]); ref=base_rh.copy()
    if any(not (0 < x < 110000) for x in p):raise ValueError('Unphysical EPW pressure')
    if any(not RH_MIN<=x<=RH_MAX for x in base_rh):raise ValueError('Invalid original measured/source EPW RH')
    tar=np.array([1000.*q_from_rh(tb,rh,pr)*ratios[int(m)] for tb,rh,pr,m in zip(base_t,base_rh,p,month)])
    lower=np.array([1000.*q_from_rh(tt,RH_MIN,pp) for tt,pp in zip(t,p)])
    upper=np.array([1000.*q_from_rh(tt,RH_MAX,pp) for tt,pp in zip(t,p)])
    prior_g=np.array([1000.*q_from_rh(tt,float(r[8]),pp) for tt,r,pp in zip(t,prior,p)])
    # IMPORTANT: original P7C.1B prior must independently conserve exact q monthly.
    for m in range(1,13):
        sel=month==m
        if abs(np.mean(prior_g[sel])-np.mean(tar[sel]))>5e-7:
            raise ValueError('P7C.1B parent EPW monthly q target mismatch')
    return month,t,p,ref,tar,lower,upper,prior_g

def project_monthly(v,lower,upper,month,totals):
    """Exact Euclidean projection onto monthly box plus sum. All values g/kg."""
    out=np.zeros_like(v)
    for m in range(1,13):
        ids=np.flatnonzero(month==m)
        if ids.size==0:raise ValueError('Missing month')
        x=v[ids]; lo=lower[ids];hi=upper[ids];total=totals[m]
        if total < np.sum(lo)-1e-8 or total > np.sum(hi)+1e-8:raise ValueError('Impossible month humidity target')
        left=np.min(lo-x)-1.;right=np.max(hi-x)+1.
        for _ in range(53):
            mid=(left+right)*.5
            if np.clip(x+mid,lo,hi).sum()<total:left=mid
            else:right=mid
        vv=np.clip(x+(left+right)*.5,lo,hi)
        if abs(vv.sum()-total)>1e-7:raise ValueError('Monthly q projection drift')
        out[ids]=vv
    return out

def rh_v_and_derivative(v,t,p,es=None):
    """RH(q), d RH / d (g/kg); vectorized exact thermodynamic inversion."""
    if es is None:es=np.array([saturation_vapor_pressure_pa(tt) for tt in t])
    q=v/1000.
    den=EPSILON+(1-EPSILON)*q
    rh=100.*p*q/(es*den)
    der=(.1*p*EPSILON)/(es*den**2)  # 100/1000
    return rh,der

def objective_gradient(v,target,t,p,es,ref_diff,limit,prior,day_weight=2.5,jump_weight=1.5):
    # q distance in (g/kg)². Deviations from registered native unbounded target.
    residual=v-target
    f=.5*np.dot(residual,residual); g=residual.copy()
    # prefer conserving native-day q where feasible, without imposing physically infeasible daily equality
    daily=residual.reshape(365,24).mean(axis=1)
    f+=.5*day_weight*24*np.dot(daily,daily)
    g+=day_weight*np.repeat(daily,24)
    rh,drh=rh_v_and_derivative(v,t,p,es)
    dd=np.diff(rh)
    # Only penalize sharp jumps beyond reference-aware thresholds; no universal physical prohibition.
    excess=np.maximum(np.abs(dd)-limit,0.)
    f+=.5*jump_weight*np.dot(excess,excess)
    deriv=jump_weight*excess*np.sign(dd)
    grh=np.empty_like(rh);grh[0]=-deriv[0];grh[-1]=deriv[-1];grh[1:-1]=deriv[:-1]-deriv[1:]
    g+=grh*drh
    return f,g,rh

def minimize_humidity(target,lower,upper,month,t,p,ref,prior, iterations=600,day_weight=2.5,jump_weight=8.0):
    if not(len(target)==len(lower)==len(upper)==len(month)==len(t)==len(p)==len(ref)==len(prior)==8760):
        raise ValueError('Bad array lengths')
    for x in (target,lower,upper,t,p,ref,prior):
        if np.any(~np.isfinite(x)):raise ValueError('Nonfinite source')
    if np.any(lower>upper) or np.any(target<0) or not np.all((month>=1)&(month<=12)):
        raise ValueError('Invalid input bounds')
    totals={m:float(np.sum(target[month==m])) for m in range(1,13)}
    origdiff=np.diff(ref)
    # 20pp is a SCREENING DIAGNOSTIC, never a law of atmospheric dynamics.
    # 19.5pp is a soft guard margin for events <=20pp in the source reference.
    # Existing >20pp events retain their original reference magnitude (+1pp tolerance).
    threshold=np.where(np.abs(origdiff)>20.,np.abs(origdiff)+1.,19.5)
    es=np.array([saturation_vapor_pressure_pa(tt) for tt in t])
    x=project_monthly(prior,lower,upper,month,totals)
    f,g,_=objective_gradient(x,target,t,p,es,origdiff,threshold,prior,day_weight,jump_weight)
    objective_old=f
    gamma=0.003  # safeguarded projected descent step initialized conservatively
    accepted=0
    for k in range(iterations):
        _,g,_=objective_gradient(x,target,t,p,es,origdiff,threshold,prior,day_weight,jump_weight)
        step=gamma
        # Backtracking ensures monotone objective on the convex feasible domain.
        for _ in range(18):
            y=project_monthly(x-step*g,lower,upper,month,totals)
            fy,_,_=objective_gradient(y,target,t,p,es,origdiff,threshold,prior,day_weight,jump_weight)
            if fy<=f+1e-9:break
            step*=0.5
        else:break
        delta=float(np.max(np.abs(y-x)))
        x=y;f=fy;accepted+=1
        # Adapt gently to curvature, no unsafe acceleration.
        gamma=min(.02,step*1.05)
        if delta<5e-8:break
    rh,_=rh_v_and_derivative(x,t,p,es)
    if np.any(rh<0.99999) or np.any(rh>100.00001):raise ValueError('Optimization violated RH')
    if any(abs(np.sum(x[month==m])-totals[m])>1e-6 for m in range(1,13)):
        raise ValueError('Monthly conservation lost')
    return x,{'iterations_accepted':accepted,'objective_before':objective_old,'objective_after':f,
              'decrease':objective_old-f,'jump_threshold_reference_aware':True,
              'soft_day_weight':day_weight,'jump_weight':jump_weight,'converged_by_delta':delta<5e-8 if accepted else False,
              'reference_max_RH_jump':float(max(abs(np.diff(ref))))}

def evaluate_epw(baseline,prior,solution,target,month,t,p,ref):
    rh=np.array([rh_from_q(float(tt),float(v)/1000.,float(pp)) for tt,v,pp in zip(t,solution,p)])
    new=[r.copy() for r in prior]
    for r,tt,rh_i in zip(new,t,rh):
        if rh_i<1-1e-7 or rh_i>100+1e-7:raise ValueError('RH out of bounds')
        bounded=max(RH_MIN,min(RH_MAX,float(rh_i)))
        r[8]=f'{bounded:.8f}';r[7]=f'{dewpoint_from_rh(float(tt),bounded):.8f}'
    for old,r in zip(prior,new):
        if any(a!=b for j,(a,b) in enumerate(zip(old,r)) if j not in (7,8)):
            raise ValueError('Non-humidity field changed')
    orig_rh=np.array([float(r[8]) for r in prior]);base_diff=np.abs(np.diff(ref));a=np.abs(np.diff(orig_rh));b=np.abs(np.diff(rh));
    count=lambda arr: int(np.sum(arr>20.000001))
    added=lambda arr:int(np.sum((arr>20.000001)&(base_diff<=20.000001)))
    def daily_stats(vals):
        return {'max_daily_q_mean_error_g_kg':float(np.max(abs((vals-target).reshape(365,24).mean(axis=1)))),
                'mean_absolute_daily_q_mean_error_g_kg':float(np.mean(abs((vals-target).reshape(365,24).mean(axis=1))))}
    diag={'reference_gt20':count(base_diff),'parent_gt20':count(a),'final_gt20':count(b),
          'parent_introduced_gt20':added(a),'final_introduced_gt20':added(b),
          'parent_max_jump_pp':float(max(a)),'final_max_jump_pp':float(max(b)),
          'parent_max_new_jump_pp':float(max(a[base_diff<=20])),'final_max_new_jump_pp':float(max(b[base_diff<=20])),
          'parent_RH_100_hours':int(np.sum(np.abs(orig_rh-100.)<1e-6)),
          'final_RH_100_hours':int(np.sum(np.abs(rh-100.)<1e-6)),
          'parent_daily':daily_stats(np.array([1000*q_from_rh(float(r[6]),float(r[8]),float(r[9])) for r in prior])),
          'final_daily':daily_stats(solution),
          'max_RH_change_vs_parent_pp':float(np.max(abs(rh-orig_rh)))}
    return new,diag

def generate(baseline_epw,original_p7c1_dir,parent_p7c1b_dir,out, provenance):
    baseline_epw=Path(baseline_epw);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    p7c1=Path(original_p7c1_dir);parent=Path(parent_p7c1b_dir)
    origprovenance=json.loads(Path(provenance).read_text());
    if sha(baseline_epw)!=origprovenance['sha256'] or origprovenance.get('provider','').lower().find('meteonorm')<0:
        raise ValueError('Baseline provenance mismatch')
    bheaders,base,_=read_epw(baseline_epw)
    old_audit=json.loads((parent/'p7c1b_humidity_science_audit.json').read_text());
    if not old_audit.get('real_contemporary_EPWs_generated') or old_audit.get('production_epw_ready') is not False:
        raise ValueError('Not a verified authentic P7C1B parent')
    if old_audit['baseline_source']['source_hash']!=sha(baseline_epw):
        raise ValueError('Wrong authentic baseline')
    source_p7c1=json.loads((p7c1/'p7c1_source_science_audit.json').read_text())
    if source_p7c1['baseline']['baseline_epw_sha256']!=sha(baseline_epw):raise ValueError('P7C1 parent mismatched')
    results={}; manifest={}
    for win in WINDOWS:
        stem=f'Graz_CanESM5_{win}'
        path=parent/(stem+'_P7C1B_HUMIDITY_CLOSED_RESEARCH_ONLY.epw')
        if sha(path)!=old_audit['results'][win]['output_files_sha256'][path.name]:raise ValueError('P7C1B SHA mismatch')
        h,prior,_=read_epw(path)
        ratio_file=p7c1/(stem+'_EPW_MORPH_P7C1_RESEARCH_ONLY_monthly_delta.csv')
        if sha(ratio_file)!=source_p7c1['results'][win]['files_sha256'][ratio_file.name]:raise ValueError('Monthly source SHA mismatch')
        ratios=load_monthly_ratios(ratio_file)
        month,t,p,ref,target,lo,hi,preq=arrays_for_moisture(base,prior,ratios)
        sol,solver=minimize_humidity(target,lo,hi,month,t,p,ref,preq)
        outrows,diag=evaluate_epw(base,prior,sol,target,month,t,p,ref)
        newheaders=[list(x) for x in h]
        newheaders[5]=['COMMENTS 1','IGE P7C1C authentic Meteonorm baseline: bounded monthly-q RH temporal coherence, research only']
        newheaders[6]=['COMMENTS 2','Only RH/dewpoint changed relative P7C1B; original Meteonorm files NOT included; audit applies']
        result=out/(stem+'_P7C1C_HOURLY_HUMIDITY_COHERENT_RESEARCH_ONLY.epw')
        write_epw(result,newheaders,outrows)
        _,rt,_=read_epw(result)
        if any(rt[i][j]!=prior[i][j] for i in range(8760) for j in range(35) if j not in (7,8)):
            raise ValueError('Serialized EPW other fields changed')
        if any(not (RH_MIN-1e-6<=float(r[8])<=RH_MAX+1e-6)
               or float(r[7])>float(r[6])+1e-5 for r in rt):
            raise ValueError('Serialized RH or dew-point physics violated')
        if diag['final_introduced_gt20']>diag['parent_introduced_gt20']:
            raise ValueError('Research humidity coherence regressed newly introduced RH events')
        months=[]
        for m in range(1,13):
            ids=np.flatnonzero(month==m)
            reconstructed=np.array([1000*q_from_rh(float(rt[i][6]),float(rt[i][8]),float(rt[i][9])) for i in ids]);
            monthly_err=float(abs(np.mean(reconstructed)-np.mean(target[ids])))
            if monthly_err>1e-7:raise ValueError('Serialized monthly mass drift')
            months.append({'month':m,'target_q_g_kg':float(np.mean(target[ids])),
                           'new_q_g_kg':float(np.mean(reconstructed)),
                           'q_closure_error_g_kg':monthly_err})
        info={'scenario':win,'sha256':sha(result),'optimization':solver,'diagnostics':diag,
              'months':months, 'max_monthly_q_serialized_residual_g_kg':max(m['q_closure_error_g_kg'] for m in months)}
        results[win]=info;manifest[result.name]=sha(result)
        print('P7C1C',win,'introduced jumps',diag['parent_introduced_gt20'],'=>',diag['final_introduced_gt20'],
              'max jump',round(diag['parent_max_jump_pp'],3),'->',round(diag['final_max_jump_pp'],3),flush=True)
    audit={'stage':'IGE_P7C1C_HOURLY_HUMIDITY_COHERENCE',
       'status':'ORIGINAL_METEONORM_BASED_LOCAL_RESEARCH_VALIDATION',
       'production_epw_ready':False,'no_EnergyPlus_run':True,'no_independent_humidity_validation':True,
       'original_meteonorm_hourly_data_in_GitHub':False,'baseline_sha256':sha(baseline_epw),
       'source_p7c1_sha256':sha(p7c1/'p7c1_source_science_audit.json'),
       'parent_p7c1b_sha256':sha(parent/'p7c1b_humidity_science_audit.json'),
       'method':'nonlinear RH reference-aware jump penalty plus q squared fidelity/day preference, projected descent; exact monthly box+sum. No global-convex-optimum claim',
       'reference_jump_20pp_is_DIAGNOSTIC_NOT_PHYSICAL_LAW':True,
       'independent_external_climate_validation':False,'results':results,'output_sha256':manifest}
    outaudit=out/'p7c1c_science_audit.json';outaudit.write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
    return audit

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--baseline',required=True);ap.add_argument('--p7c1',required=True);ap.add_argument('--p7c1b',required=True);ap.add_argument('--provenance',required=True);ap.add_argument('--out',required=True)
    a=ap.parse_args();generate(a.baseline,a.p7c1,a.p7c1b,a.out,a.provenance)