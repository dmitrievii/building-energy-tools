#!/usr/bin/env python3
"""P9.2C physical feasibility screening and simultaneous q/RH/daylight closure.

A prospective algorithm rule; donor selection uses only original daily forcing
and historical hourly analogues, NEVER station validation residuals.
"""
from __future__ import annotations
import dataclasses,datetime as dt,math,statistics
from p9_2a_joint_weather_regimes import Day,check_vector
from p9_2b_cmip6_daily_joint_regime_solver import (
    SIGMA,EPS,InfeasibleDailyClimate,DAY_FIELDS,native_target,
    select_donor,new_day,sat_pa,qsat,q_of_e,e_of_q,dewpoint_of_q,
)
from p9_2b_original_source_humidity_solar_cause_audit import witness_humidity

METHOD="P9.2C_PHYSICALLY_FEASIBLE_DONORS_20261018_V1"
HARD_TOL=1e-6
RH_TOL_PP=1e-5

def _high_q(T,P,Q,caps):
    """Concave RH maximum under water-mass and pointwise saturation."""
    def allocate(lam):
        v=[]
        for t,p,cap in zip(T,P,caps):
            A=100*p*EPS/sat_pa(t)
            v.append(max(0.,min(cap,(math.sqrt(A/lam)-EPS)/(1-EPS))))
        return v
    a,b=1e-10,1e12
    for _ in range(180):
        m=math.sqrt(a*b)
        if sum(allocate(m))>Q:a=m
        else:b=m
    result=allocate(math.sqrt(a*b))
    if abs(sum(result)-Q)>1e-7:
        raise InfeasibleDailyClimate("P92C_KKT_WATER_MASS_NUMERICAL_FAILURE")
    return result

def _low_witness(T,P,Q,caps):
    """Feasible low-RH witness, NOT a proven global RH minimum."""
    result=[0.]*24
    remaining=Q
    for i in sorted(range(24),key=lambda k:caps[k],reverse=True):
        add=min(caps[i],remaining)
        result[i]=add
        remaining-=add
    if remaining>1e-7:
        raise InfeasibleDailyClimate("P92C_LOW_RH_WITNESS_WATER_MASS_ERROR")
    return result

def humidity_reconcile(day,lw,target):
    """Keep exact native huss and T while solving attainable daily mean hurs.

    Never alters daily native forcing; marks unattainable RH, no >100% clamp.
    Recompute longwave partition because sky proxy depends on hourly RH.
    """
    fields=native_target(target)
    vectors=[dict(x) for x in day.vectors]
    T=[x["temperature_2m"] for x in vectors]
    P=[x["surface_pressure"]*100 for x in vectors]
    cap=[qsat(t,p)*.999999999 for t,p in zip(T,P)]
    Q=24*fields["huss"]
    if Q>sum(cap)+1e-8:
        raise InfeasibleDailyClimate("P92C_DONOR_HUSS_SATURATION_CAPACITY_BLOCK")
    base=[q_of_e(sat_pa(x["dew_point_2m"]),p) for x,p in zip(vectors,P)]
    if abs(sum(base)-Q)>1e-7:
        raise InfeasibleDailyClimate("P92C_ORIGINAL_SOLVER_Q_MASS_NOT_CLOSED")
    def rh(q):return statistics.fmean(100*e_of_q(x,p)/sat_pa(t) for x,p,t in zip(q,P,T))
    before=rh(base)
    high=_high_q(T,P,Q,cap)
    low=_low_witness(T,P,Q,cap)
    upper=rh(high);lower=rh(low)
    desired=fields["hurs"]
    category="FEASIBLE_BOTH_Q_AND_RH"
    selected=base
    if desired>upper+RH_TOL_PP:
        category="RH_ABOVE_PROVED_PHYSICAL_MAX_FOR_THIS_DONOR"
    elif desired<lower-RH_TOL_PP:
        category="RH_BELOW_LOW_FEASIBLE_WITNESS_UNCLASSIFIED"
    elif abs(before-desired)>RH_TOL_PP:
        endpoint=high if desired>before else low
        end_rh=rh(endpoint)
        if not (min(before,end_rh)-RH_TOL_PP<=desired<=max(before,end_rh)+RH_TOL_PP):
            category="RH_FEASIBILITY_WITNESSED_BUT_MIXTURE_BRACKET_UNAVAILABLE"
        else:
            lo,hi=0.,1.
            for _ in range(100):
                mid=(lo+hi)/2
                q=[(1-mid)*a+mid*b for a,b in zip(base,endpoint)]
                val=rh(q)
                if (val<desired)==(before<desired):lo=mid
                else:hi=mid
            alpha=(lo+hi)/2
            selected=[(1-alpha)*a+alpha*b for a,b in zip(base,endpoint)]
            if any(x<=0 for x in selected):
                category="RH_CLOSE_TO_ZERO_Q_LIMIT_KEEP_NATIVE_Q_HARD"
                selected=base
    if selected is not base:
        if abs(sum(selected)-Q)>1e-7 or any(q>c+1e-10 or q<=0 for q,c in zip(selected,cap)):
            raise InfeasibleDailyClimate("P92C_Q_CONSERVATION_OR_SATURATION_NUMERICAL")
        for i,(x,p,t) in enumerate(zip(selected,P,T)):
            vectors[i]["relative_humidity_2m"]=100*e_of_q(x,p)/sat_pa(t)
            vectors[i]["dew_point_2m"]=dewpoint_of_q(x,p,t)
            check_vector(vectors[i])
    # Longwave regenerated with same physical hourly emissivity formula as B.
    eps0=[min(1.1,max(.4,.60+.0025*v["relative_humidity_2m"]+
                           .0015*v["cloud_cover"])) for v in vectors]
    emitted=[SIGMA*(x+273.15)**4 for x in T]
    lw_target=fields["rlds_kwh_m2_day"]*1000
    fac=lw_target/sum(a*b for a,b in zip(eps0,emitted))
    emiss=[fac*e for e in eps0]
    if any(e<.30 or e>1.4 for e in emiss):
        raise InfeasibleDailyClimate("P92C_POST_RH_LONGWAVE_SKY_EMISSIVITY_BLOCK")
    new_lw=[e*x for e,x in zip(emiss,emitted)]
    achieved=rh(selected)
    if abs(statistics.fmean(selected)-fields["huss"])>HARD_TOL:
        raise InfeasibleDailyClimate("P92C_POST_RH_HUSS_NOT_CONSERVED")
    if abs(sum(new_lw)/1000-fields["rlds_kwh_m2_day"])>HARD_TOL:
        raise InfeasibleDailyClimate("P92C_POST_RH_LONGWAVE_NOT_CONSERVED")
    return Day(day.date,tuple(vectors),day.original_sha256),new_lw,{
        "source_daily_hurs_target_pp":desired,
        "original_B_hurs_residual_pp":before-desired,
        "P92C_hurs_residual_pp":achieved-desired,
        "hurs_joint_status":category,
        "hurs_physical_upper_KKT_pp":upper,
        "hurs_low_feasible_witness_pp":lower,
        "huss_native_hard_closed":True,
        "qmax_and_qmin_reuse_original_source_t_p":True,
        "LW_recomputed_after_relative_humidity_adjustment":True,
    }

def candidates_for_target(donors,target,latitude,longitude):
    """Pre-screen all original candidates by hard source physics (no station)."""
    norm=native_target(target)
    same_class=lambda d:((sum(v["precipitation"] for v in d.vectors)>0)
                         ==(norm["pr_mm_day"]>0))
    allowed=[];blocked={}
    for d in donors:
        if d.date.month!=target["date"].month or not same_class(d):
            continue
        if d.date.year==target["date"].year:
            raise ValueError("P92C_TARGET_YEAR_DONOR_LEAK")
        try:
            generated,lw,info=new_day(target,d,latitude,longitude)
            adjusted,lw2,moist=humidity_reconcile(generated,lw,target)
            allowed.append((d,adjusted,lw2,info,moist))
        except (InfeasibleDailyClimate,ValueError) as exc:
            k=str(exc).split(": ")[-1]
            blocked[k]=blocked.get(k,0)+1
    return allowed,blocked

def generate(targets,donors,latitude,longitude,seed=7313):
    if not targets or not donors:
        raise ValueError("P92C_EMPTY_TARGETS_OR_DONOR_SOURCE")
    if any(d.date.year in {t["date"].year for t in targets} for d in donors):
        raise ValueError("P92C_TARGET_YEAR_DONOR_LEAK")
    out=[];blocked=[];prev=None
    for t in targets:
        physical,rejected=candidates_for_target(donors,t,latitude,longitude)
        if not physical:
            blocked.append({"date":t["date"].isoformat(),
                            "status":"NO_PHYSICALLY_ADMISSIBLE_SOURCE_DONOR",
                            "candidate_rejection_codes":rejected})
            prev=None
            continue
        exact=[c for c in physical if c[4]["hurs_joint_status"]=="FEASIBLE_BOTH_Q_AND_RH"]
        eligible=exact if exact else physical
        chosen=select_donor([x[0] for x in eligible],
                            {"date":t["date"],**native_target(t)},prev,seed)
        candidate=next(x for x in eligible if x[0] is chosen)
        donor,day,lw,info,moist=candidate
        out.append((day,lw,{
            **info,**moist,"selected_donor_date":donor.date.isoformat(),
            "n_physically_admissible_donors":len(physical),
            "n_joint_q_RH_feasible_donors":len(exact),
            "n_candidates_rejected_by_gate":sum(rejected.values()),
            "candidate_rejection_codes":rejected,
            "no_observed_station_measurements_used_in_selection":True}))
        prev=day.vectors[-1]
    return out,blocked
