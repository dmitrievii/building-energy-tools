#!/usr/bin/env python3
"""Post-hoc DIAGNOSTIC ONLY for 15 known 2014 source blocks, not new model tuning.

Compute a provable upper bound on sum(qsat(T_h,P_h)) under original donor
hourly fixed P, native Tmin/Tmax/mean, frozen P9.3A ±2C/hour deviation and
hourly slope restriction. qsat(T,P) convex on tested donor temperature
intervals; its chord between feasible hourly lower and upper bounds is a
pointwise upper bound, and maximizing chords under linear constraints is
a linear program. Thus if source huss exceeds the LP upper, no solver
can rescue that donor WITHOUT changing prescribed assumptions. The reverse
does NOT prove feasibility. No pressure fitting or temperature optimization.
"""
from __future__ import annotations
import argparse,collections,datetime as dt,json,math
from pathlib import Path
from scipy.optimize import linprog

from p9_3a_original_canesm5_2014_year_pressure_temperature_q import (
    native_2014,EXPECTED_ERA5_CANONICAL_SHA)
from p9_2d_original_canesm5_2013_annual_source_epw_pilot import original_era5_year,DONOR_LAT,DONOR_LON
from p9_3a_pressure_temperature_q_joint import (
    _profile,_eligible,SAT_FACTOR,MAX_ADJUST_C,MIN_SLOPE_CAP_C_PER_H)
from p9_2b_cmip6_daily_joint_regime_solver import qsat
# If code branch lacks a separate alias, use the declared canonical SHA.

KNOWN_BLOCKED_2014=(
    "2014-01-31","2014-02-09","2014-02-10","2014-04-19",
    "2014-04-20","2014-04-22","2014-05-07","2014-05-13",
    "2014-05-15","2014-05-16","2014-06-11","2014-06-12",
    "2014-06-15","2014-12-02","2014-12-16")
TOL=1e-10

def chord_upper_q_mean(donor,target):
    """Strictly conditional LP upper envelope; not fitted daily weather."""
    native,T0,P=_profile(donor,target)
    lo=native["tasmin_c"];hi=native["tasmax_c"]
    low=[max(lo,t-MAX_ADJUST_C) for t in T0]
    upper=[min(hi,t+MAX_ADJUST_C) for t in T0]
    mi=min(range(24),key=lambda j:T0[j])
    ma=max(range(24),key=lambda j:T0[j])
    low[mi]=upper[mi]=T0[mi]
    low[ma]=upper[ma]=T0[ma]
    coefficients=[];const=[]
    for l,u,p in zip(low,upper,P):
        if l>u+1e-8:raise ValueError("P93A_ENVELOPE_LP_HOURLY_BOUNDS_INVALID")
        if abs(u-l)<1e-9:
            coefficients.append(0.)
            const.append(qsat(l,p)*SAT_FACTOR)
            continue
        f_l=qsat(l,p)*SAT_FACTOR
        f_u=qsat(u,p)*SAT_FACTOR
        slope=(f_u-f_l)/(u-l)
        coefficients.append(slope)
        const.append(f_l-slope*l)
        # Numerically test the necessary convex-chord inequality at fixed P
        for k in range(1,9):
            t=l+(u-l)*k/9
            if qsat(t,p)*SAT_FACTOR>slope*t+const[-1]+1e-11:
                raise ValueError("P93A_SATURATION_FUNCTION_NONCONVEX_INTERVAL")
    delta=max(MIN_SLOPE_CAP_C_PER_H,
              max(abs(b-a) for a,b in zip(T0,T0[1:])))
    A=[];B=[]
    for i in range(23):
        row=[0.]*24;row[i]=-1.;row[i+1]=1.
        A.append(row);B.append(delta)
        A.append([-x for x in row]);B.append(delta)
    p=linprog(c=[-x for x in coefficients],
       A_ub=A,b_ub=B,A_eq=[[1.]*24],b_eq=[24*native["tas_c"]],
       bounds=list(zip(low,upper)),method="highs")
    if not p.success:
        return {"status":"LP_BOUND_NOT_ESTABLISHED","reason":str(p.message)[:120]}
    lp_upper=(sum(c*t for c,t in zip(coefficients,p.x))+sum(const))/24
    baseline=sum(qsat(t,p_h)*SAT_FACTOR for t,p_h in zip(T0,P))/24
    if lp_upper<baseline-1e-9:
        raise ValueError("P93A_UPPER_CAPACITY_ENVELOPE_BELOW_ACTUAL_T_SHAPE")
    return {"status":"CERTIFIED_UPPER_BOUND_UNDER_FIXED_DONOR_PRESSURE",
       "native_daily_huss_kgkg":native["huss"],
       "baseline_mean_qsat_kgkg":baseline,
       "LP_upper_mean_qsat_kgkg":lp_upper,
       "huss_exceeds_proved_LP_temperature_pressure_capacity":native["huss"]>lp_upper+TOL,
       "LP_upper_deficit_g_kg":(native["huss"]-lp_upper)*1000,
       "assumed_original_hourly_P_is_fixed":True,
       "T_hourly_native_min_mean_max_and_2C_bound_fixed":True}

def run(gcm_source,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    native,provenance=native_2014(gcm_source)
    selected={x["date"].isoformat():x for x in native if
              x["date"].isoformat() in KNOWN_BLOCKED_2014}
    if len(selected)!=15:
        raise ValueError("P93A_POSTHOC_DIAG_NATIVE_SOURCE_DATES_NOT_15")
    donors=[];original=[]
    for yr in (2019,2020):
        d,prov=original_era5_year(yr)
        if prov["canonical_source_weather_sha256"]!=EXPECTED_ERA5_CANONICAL_SHA[yr]:
            raise ValueError("P93A_POSTHOC_CANONICAL_ERA5_SOURCE_DRIFT")
        donors.extend(d);original.append(prov)
    result={"phase":"P93A_2014_FROZEN_FAILURE_RETROSPECTIVE_CHORD_LP_PRESSURE_DIAG",
      "retrospective_after_original_2014_observation_not_independent_validation":True,
      "NO_weather_generator_retraining_or_parameter_selection":True,
      "registered_native_gcm_source_SHA256":provenance["daily_csv_sha256"],
      "source_external_ERA5_hourly_canonical_SHA256":[x["canonical_source_weather_sha256"] for x in original],
      "native_GCM_pressure_field_NOT_AVAILABLE":True,
      "n_original_2014_source_blocked_days":15,
      "assumed_method_limits":{"hourly_adjust_C":MAX_ADJUST_C,
                                "fixed_hourly_pressure":"ERA5_original",
                                "temperature_mean_min_max":"native_NEX_CMIP6",
                                "mean_specific_humidity":"native_NEX_CMIP6"},
      "blocked_days":[],"production_epw_ready":False}
    total_cert=0;total_possible=0;total_numeric=0
    for d in KNOWN_BLOCKED_2014:
        day=selected[d]
        eligible=list(_eligible(donors,day))
        certificates=[chord_upper_q_mean(donor,day) for donor in eligible]
        n_cert=sum(x.get("huss_exceeds_proved_LP_temperature_pressure_capacity") is True
                   for x in certificates)
        n_unresolved=sum(x.get("huss_exceeds_proved_LP_temperature_pressure_capacity") is False
                         for x in certificates)
        n_notest=sum(x["status"]!="CERTIFIED_UPPER_BOUND_UNDER_FIXED_DONOR_PRESSURE"
                     for x in certificates)
        m={"date":d,"original_native_huss_kgkg":float(day["huss"]),
           "n_native_monthly_same_wet_dry_donors":len(eligible),
           "n_donors_proved_upper_bound_insufficient":n_cert,
           "n_donors_upper_bound_not_proving_impossible":n_unresolved,
           "n_donors_lp_numerically_unresolved":n_notest,
           "native_huss_minus_best_any_donor_capacity_bound_min_gkg":(
               min(x["LP_upper_deficit_g_kg"] for x in certificates
                   if x["status"]=="CERTIFIED_UPPER_BOUND_UNDER_FIXED_DONOR_PRESSURE")
               if n_cert+n_unresolved else None),
           "cannot_classify_all_original_physical_pressure_sources_as_impossible":True}
        result["blocked_days"].append(m)
        total_cert+=n_cert;total_possible+=n_unresolved;total_numeric+=n_notest
        print("P93A_LP_SOURCE_BOUND",json.dumps({
            "date":d,"original_donors":len(eligible),
            "LP_proves_T_plus2_fixed_P_q_impossible":n_cert,
            "LP_does_not_prove":n_unresolved,
            "LP_unresolved":n_notest}),flush=True)
    result["total_original_donor_cases_proved_impossible_under_fixed_source_P_and_T_bounds"]=total_cert
    result["total_donor_cases_not_proved_impossible"]=total_possible
    result["total_donor_cases_numeric_LP_unresolved"]=total_numeric
    result["n_days_all_donors_proved_impossible"]=sum(
        a["n_native_monthly_same_wet_dry_donors"]>0
        and a["n_native_monthly_same_wet_dry_donors"]==a["n_donors_proved_upper_bound_insufficient"]
        for a in result["blocked_days"])
    result["n_days_any_donor_not_proved_impossible"]=sum(
        a["n_donors_upper_bound_not_proving_impossible"]>0 for a in result["blocked_days"])
    (out/"p9_3a_2014_retrospective_fixed_pressure_T_capacity_LP_diagnosis.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("P93A_POSTHOC_DIAGNOSTIC_FINAL",json.dumps({
       "blocked_original_dates":15,
       "all_donors_proved_infeasible_days":result["n_days_all_donors_proved_impossible"],
       "some_donor_not_proved_infeasible_days":result["n_days_any_donor_not_proved_impossible"],
       "donor_tests_certified_infeasible":total_cert,
       "donor_tests_unresolved_possible":total_possible,
       "donor_tests_numeric_unknown":total_numeric}),flush=True)
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--original-canesm5-registered-zip",required=True)
    p.add_argument("--out",default="outputs/p93a-2014-posthoc")
    o=p.parse_args();run(Path(o.original_canesm5_registered_zip),Path(o.out))
