#!/usr/bin/env python3
"""P9.2B one independent frozen-input physics diagnostic, without changing solver.

Exact original CMIP6 archives, existing P9.2B donor selection and 2019/20
ERA5 hours. Explicitly distinguish vapor saturation bound vs solar donor
support. Diagnose whether 2013/2050 daily RH can coexist with native q and
given morphed T/p, using provably feasible RH witness profiles, not tuning.
"""
from __future__ import annotations
import argparse
import json
import math
import statistics
from pathlib import Path

import p9_2b_original_nasa_cmip6_graz_real_source_pilot as pilot
from p9_2b_cmip6_daily_joint_regime_solver import (
    native_target,select_donor,source_hourly_mean_temperature,qsat,sat_pa,
    e_of_q,distribute_exact,geometry,new_day,InfeasibleDailyClimate,EPS)
SHA_ONLY=True

def rh_from_q(q,t,p):
    return 100*e_of_q(q,p)/sat_pa(t)

def witness_humidity(qdaily,T,P):
    capacities=[qsat(t,p)*.999999999 for t,p in zip(T,P)]
    Q=24*qdaily
    if Q>sum(capacities)+1e-9:
        return {"huss_possible":False,
                "mean_qsat_capacity":statistics.fmean(capacities),
                "required_mean_huss":qdaily}
    # Feasible low RH witness: saturate warm, high qsat hours first,
    # entirely within q<=q_sat, maintaining native daily mean q.
    low=[0.]*24
    remaining=Q
    for i in sorted(range(24),key=lambda k:capacities[k],reverse=True):
        a=min(capacities[i],remaining)
        low[i]=a
        remaining-=a
    if remaining>1e-8:raise ValueError("P92B_DIAG_LOW_ALLOCATION_NOT_CONSERVED")
    # Exact global maximum for mean RH because RH(q)=Aq/(eps+bq)
    # is increasing and strictly concave: KKT marginal utility water filling.
    def maximum_distribution(lam):
        vals=[]
        for i in range(24):
            A=100*P[i]*EPS/sat_pa(T[i])
            qi=(math.sqrt(A/lam)-EPS)/(1-EPS)
            vals.append(max(0.,min(capacities[i],qi)))
        return vals
    lo,hi=1e-10,1e12
    for _ in range(170):
        mid=math.sqrt(lo*hi)
        if sum(maximum_distribution(mid))>Q:lo=mid
        else:hi=mid
    upper=maximum_distribution(math.sqrt(lo*hi))
    if abs(sum(upper)-Q)>1e-6:raise ValueError("P92B_DIAG_RH_MAX_NOT_Q_CONSERVING")
    min_witness=statistics.fmean(rh_from_q(q,t,p) for q,t,p in zip(low,T,P))
    max_RH=statistics.fmean(rh_from_q(q,t,p) for q,t,p in zip(upper,T,P))
    return {"huss_possible":True,"required_mean_huss":qdaily,
            "mean_qsat_capacity":statistics.fmean(capacities),
            "low_RH_feasible_witness_pp":min_witness,
            "max_RH_proved_KKT_pp":max_RH,
            "low_and_high_are_both_feasible_q_conserving_profiles":True}

def one(target,donor,lat,lon):
    src=native_target(target)
    t=source_hourly_mean_temperature(donor,src)
    p=[v["surface_pressure"]*100 for v in donor.vectors]
    hum=witness_humidity(src["huss"],t,p)
    z=geometry(target["date"],lat,lon)
    weights=[max(0.,v["shortwave_radiation"]) if zi>0 else 0
             for v,zi in zip(donor.vectors,z)]
    cap=[1450*zi for zi in z]
    supported=sum(ci for ci,wi in zip(cap,weights) if wi>0)/1000
    full=sum(cap)/1000
    q_block=(not hum["huss_possible"])
    solar_block=src["rsds_kwh_m2_day"]>supported+1e-8
    result={"target_date":target["date"].isoformat(),
        "selected_original_donor_date":donor.date.isoformat(),
        "original_ERA5_donor_source_SHA256":donor.original_sha256,
        "source_daily_huss_kgkg":src["huss"],
        "source_daily_hurs_pct":src["hurs"],
        "source_daily_GHI_kWh_m2":src["rsds_kwh_m2_day"],
        "capacity_q_mean_kgkg":hum["mean_qsat_capacity"],
        "native_huss_exceeds_physically_available_saturation_capacity":q_block,
        "solar_total_exceeds_donor_hour_support_capacity":solar_block,
        "solar_donor_supported_cap_kWh_m2":supported,
        "solar_unconstrained_daylight_cap_kWh_m2":full,
        "identical_source_temperature_shape_and_same_donor_as_P92B":True,
        "humidity_RH_feasibility":hum,
        "source_daily_RH_exceeds_max_physical_RH":(
            (src["hurs"]>hum["max_RH_proved_KKT_pp"]+1e-7)
            if hum["huss_possible"] else None),
        "source_daily_RH_attainable_between_two_q_conserving_feasible_witnesses":(
            (hum["low_RH_feasible_witness_pp"]-1e-7<=src["hurs"]<=hum["max_RH_proved_KKT_pp"]+1e-7)
            if hum["huss_possible"] else None)}
    try:
        generated,lw,metadata=new_day(target,donor,lat,lon)
        result["existing_unmodified_solver_status"]="CONSERVATION_PASS"
        result["source_daily_RH_residual_from_unmodified_solver_pp"]=metadata["native_daily_hurs_soft_closure_pp"]
        return result,generated.vectors[-1]
    except InfeasibleDailyClimate as e:
        result["existing_unmodified_solver_status"]="BLOCKED"
        result["existing_unmodified_solver_block_code"]=str(e)
        return result,None

def run(directory,out):
    files=pilot.read_cmip6(directory)
    sources={}
    for season,from_,until in pilot.SEASONS:
        pool=[];shas=[]
        for y in pilot.TRAINING_DONOR_YEARS:
            days,meta=pilot.original_days(pilot.SITE[2],pilot.SITE[3],y,season,from_,until)
            pool.extend(days)
            shas.append(meta["raw_original_response_sha256"] if "raw_original_response_sha256" in meta else meta["original_provider_http_SHA256"])
        sources[season]={"pool":pool,"sha":shas}
    data=[]
    for scenario,window,y in pilot.SCENARIOS:
        for season,from_,until in pilot.SEASONS:
            m=1 if season=="January" else 7
            targets=[d for d in files[scenario]["rows"] if d["date"].month==m]
            prev=None
            for target in targets:
                try:
                    src=native_target(target)
                    donor=select_donor(sources[season]["pool"],{"date":target["date"],**src},prev,pilot.SEED)
                    d,last=one(target,donor,pilot.SITE[2],pilot.SITE[3])
                    d["scenario"]=scenario;d["season"]=season
                    data.append(d)
                    prev=last
                    if target["date"].isoformat()=="2013-07-10":
                        print("P92B_CAUSE_ORIGINAL_REJECTED_DAY",json.dumps(d),flush=True)
                except Exception as e:
                    print("P92B_DIAGNOSTIC_UNEXPECTED",scenario,season,target["date"].isoformat(),str(e),flush=True)
                    raise
    if len(data)!=28:
        raise ValueError("P92B_AUDIT_REGISTERED_DAYS_NOT_28")
    eligible=[x for x in data if x["existing_unmodified_solver_status"]=="CONSERVATION_PASS"]
    blocked=[x for x in data if x["existing_unmodified_solver_status"]=="BLOCKED"]
    if len(eligible)!=27 or len(blocked)!=1 or blocked[0]["target_date"]!="2013-07-10":
        raise ValueError("P92B_DIAGNOSTIC_NOT_REPRODUCING_PRIOR_FROZEN_SOURCE_RUN")
    summary={"phase":"P9_2B_FROZEN_28_DAY_Q_SAT_SOLAR_RH_FEASIBILITY_DIAGNOSTIC",
       "reproduced_prior_unmodified_solver_27_pass_1_block":True,
       "n_original_CMIP6_days":len(data),
       "n_solver_pass":len(eligible),"n_solver_blocked":len(blocked),
       "rejected_day":blocked[0],
       "n_rh_target_outside_attainable_physical_max":sum(
          x["source_daily_RH_exceeds_max_physical_RH"] is True for x in data),
       "n_native_RH_inside_explicit_witness_pair":sum(
          x["source_daily_RH_attainable_between_two_q_conserving_feasible_witnesses"] is True for x in data),
       "n_q_over_saturation_capacity":sum(
          x["native_huss_exceeds_physically_available_saturation_capacity"] for x in data),
       "n_solar_over_donor_supported_hour_capacity":sum(
          x["solar_total_exceeds_donor_hour_support_capacity"] for x in data),
       "n_success_with_abs_RH_mismatch_over_5pp":sum(
          abs(x["source_daily_RH_residual_from_unmodified_solver_pp"])>5 for x in eligible),
       "yearly_summary":[],
       "source_old_model_algorithm_intentionally_unchanged":True,
       "not_climatological_station_skill":True,"production_epw_ready":False}
    for scenario in ("historical","ssp245"):
        subset=[x for x in data if x["scenario"]==scenario]
        summary["yearly_summary"].append({"scenario":scenario,
          "n_days":len(subset),
          "n_rh_two_feasible_witness_brackets":sum(
              x["source_daily_RH_attainable_between_two_q_conserving_feasible_witnesses"] is True for x in subset),
          "n_physically_impossible_daily_hurs_upper_bound":sum(
              x["source_daily_RH_exceeds_max_physical_RH"] is True for x in subset)})
    # Restrict output to diagnostics/actual source result, no hourly original
    # ERA5 weather or original 28x native CMIP6 daily vector dump.
    out.mkdir(parents=True,exist_ok=True)
    (out/"p9_2b_source_frozen_28_day_humidity_solar_diagnostic.json").write_text(
       json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print("P92B_CAUSE_AUDIT_FINAL",json.dumps({
       "blocked_day":blocked[0]["target_date"],
       "huss_over_qsat":blocked[0]["native_huss_exceeds_physically_available_saturation_capacity"],
       "solar_over_donor_support":blocked[0]["solar_total_exceeds_donor_hour_support_capacity"],
       "RH_target_above_true_physical_max_n":summary["n_rh_target_outside_attainable_physical_max"],
       "RH_witness_physically_feasible_n":summary["n_native_RH_inside_explicit_witness_pair"],
       "RH_mismatch_over_5pp_n":summary["n_success_with_abs_RH_mismatch_over_5pp"]}),flush=True)
    return summary

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--canonical-archive-dir",default="inputs/p9_2b_original_CMIP6")
    p.add_argument("--out",default="outputs/p92b-diagnostic")
    args=p.parse_args();run(Path(args.canonical_archive_dir),Path(args.out))
