#!/usr/bin/env python3
"""IGE P9.3A: source-honest pressure-conditioned joint temperature/q reconstruction.

Native NEX-GDDP daily tas/tasmin/tasmax/huss/hurs lack native pressure ps.
Use original ERA5 donor's 24 fixed hourly pressure values as a provenance-
labelled proxy; NEVER optimize P to close huss. If needed, minimize smooth
temperature perturbation under exact native T moments and saturation-capacity.
Research-only: physical feasibility != GCM native source accuracy.
"""
from __future__ import annotations
import math,statistics,collections
from scipy.optimize import minimize
from p9_2a_joint_weather_regimes import check_vector
from p9_2b_cmip6_daily_joint_regime_solver import (
  source_hourly_mean_temperature,native_target,qsat,select_donor,new_day,
  InfeasibleDailyClimate)
from p9_2c_physical_donor_and_humidity import (
  candidates_for_target,humidity_reconcile)

VERSION="IGE_P9_3A_INDEPENDENT_PRESSURE_JOINT_T_Q_20261018_V1"
PRESSURE_MODE="ORIGINAL_OPENMETEO_ERA5_DONOR_PRESSURE_NOT_NATIVE_CANESM5_PS"
MAX_ADJUST_C=2.0
MIN_SLOPE_CAP_C_PER_H=6.0
MAX_REPAIR_CANDIDATES=8
NATIVE_T_TOL=1.e-6
Q_CAP_MARGIN=2.e-9 # kg/kg DAY-mean margin; numerical only
SAT_FACTOR=.999999999
SEED=7313

def _profile(source,target):
    native=native_target(target)
    base=source_hourly_mean_temperature(source,native)
    pressure=[v["surface_pressure"]*100 for v in source.vectors]
    if not all(30000<p<115000 and math.isfinite(p) for p in pressure):
        raise InfeasibleDailyClimate("P93A_HOURLY_SOURCE_PRESSURE_MISSING_OR_INVALID")
    return native,base,pressure

def saturation_deficit(source,target):
    native,T,P=_profile(source,target)
    max_mean=statistics.fmean(qsat(t,p)*SAT_FACTOR for t,p in zip(T,P))
    return native["huss"]-max_mean

def _verify_temperature(T,T0,native,pressure):
    if len(T)!=24 or any(not math.isfinite(x) for x in T):
        raise InfeasibleDailyClimate("P93A_T_REPAIR_NONFINITE")
    if (abs(statistics.fmean(T)-native["tas_c"])>NATIVE_T_TOL
         or abs(min(T)-native["tasmin_c"])>NATIVE_T_TOL
         or abs(max(T)-native["tasmax_c"])>NATIVE_T_TOL):
        raise InfeasibleDailyClimate("P93A_T_DAILY_MOMENTS_NOT_CLOSED")
    if any(abs(x-y)>MAX_ADJUST_C+1.e-5 for x,y in zip(T,T0)):
        raise InfeasibleDailyClimate("P93A_T_EXCEEDS_PRIOR_HOURLY_DEVIATION")
    slope_limit=max(MIN_SLOPE_CAP_C_PER_H,
                    max(abs(b-a) for a,b in zip(T0,T0[1:])))
    if any(abs(b-a)>slope_limit+1.e-5 for a,b in zip(T,T[1:])):
        raise InfeasibleDailyClimate("P93A_T_EXCEEDS_PRIOR_DIURNAL_SLOPE")
    return statistics.fmean(qsat(t,p)*SAT_FACTOR for t,p in zip(T,pressure))

def repair_temperature_profile(donor,target):
    """Return physically qualified T or reject WITHOUT adjusting original P.

    Native extrema fixed at positions inherited from donor, exact Tmean,
    capped deviation ±2C, bounded temporal gradients. One SLSQP solve only.
    """
    native,T0,P=_profile(donor,target)
    cap0=_verify_temperature(T0,T0,native,P)
    if cap0>=native["huss"]+Q_CAP_MARGIN:
        return T0,{"temperature_repaired":False,"T_max_abs_change_C":0.,
            "fixed_donor_pressure_Pa_mean":statistics.fmean(P),
            "donor_pressure_source":PRESSURE_MODE,
            "native_huss_mean_qsat_margin_kgkg":cap0-native["huss"],
            "solver_name":"BASELINE_SUFFICIENT_NO_OPTIMIZATION"}
    if cap0>=native["huss"]+1.e-11:
        return T0,{"temperature_repaired":False,"T_max_abs_change_C":0.,
            "fixed_donor_pressure_Pa_mean":statistics.fmean(P),
            "donor_pressure_source":PRESSURE_MODE,
            "native_huss_mean_qsat_margin_kgkg":cap0-native["huss"],
            "solver_name":"BASELINE_CLOSE_TO_SATURATION_NO_OPTIMIZATION"}
    # Pre-screen maximum achievable q capacity if every mutable hourly T
    # reaches its own upper bound (ignores native-mean), a necessary condition.
    low=native["tasmin_c"];high=native["tasmax_c"]
    lo_bounds=[max(low,t-MAX_ADJUST_C) for t in T0]
    hi_bounds=[min(high,t+MAX_ADJUST_C) for t in T0]
    max_possible=statistics.fmean(qsat(t,p)*SAT_FACTOR for t,p in zip(hi_bounds,P))
    if max_possible<native["huss"]-1.e-10:
        raise InfeasibleDailyClimate("P93A_FIXED_PRESSURE_T_PLUS2_UPPER_CAP_BELOW_NATIVE_HUSS")
    mi=min(range(24),key=lambda j:T0[j])
    ma=max(range(24),key=lambda j:T0[j])
    if mi==ma:raise InfeasibleDailyClimate("P93A_SOURCE_T_EXTREMA_NONUNIQUE")
    indices=[j for j in range(24) if j not in (mi,ma)]
    baseline=[T0[j] for j in indices]
    bounds=list(zip([lo_bounds[j] for j in indices],
                    [hi_bounds[j] for j in indices]))
    slope=max(MIN_SLOPE_CAP_C_PER_H,
              max(abs(b-a) for a,b in zip(T0,T0[1:])))
    def expand(y):
        T=list(T0)
        for j,v in zip(indices,y):T[j]=float(v)
        return T
    def obj(y):
        T=expand(y)
        e=[a-b for a,b in zip(T,T0)]
        return sum(x*x for x in e)+.25*sum((b-a)**2 for a,b in zip(e,e[1:]))
    def mean_con(y):return sum(expand(y))/24-native["tas_c"]
    def mass_con(y):
        T=expand(y)
        return 1000*(sum(qsat(t,p)*SAT_FACTOR for t,p in zip(T,P))/24-
                     (native["huss"]+Q_CAP_MARGIN))
    def slope_con(y):
        T=expand(y)
        return [slope-(b-a) for a,b in zip(T,T[1:])]+[
               slope+(b-a) for a,b in zip(T,T[1:])]
    solution=minimize(obj,baseline,method="SLSQP",bounds=bounds,
       constraints=[{"type":"eq","fun":mean_con},
                    {"type":"ineq","fun":mass_con},
                    {"type":"ineq","fun":slope_con}],
       options={"maxiter":180,"ftol":1.e-10,"disp":False})
    candidate=expand(solution.x)
    if not solution.success:
        raise InfeasibleDailyClimate("P93A_T_CONSTRAINED_SLSQP_DID_NOT_CONVERGE")
    cap=_verify_temperature(candidate,T0,native,P)
    if cap<native["huss"]+Q_CAP_MARGIN-1.e-9:
        raise InfeasibleDailyClimate("P93A_T_MORPH_DOES_NOT_SATISFY_HUSS_CAPACITY")
    return candidate,{"temperature_repaired":True,
        "T_max_abs_change_C":max(abs(a-b) for a,b in zip(candidate,T0)),
        "fixed_donor_pressure_Pa_mean":statistics.fmean(P),
        "donor_pressure_source":PRESSURE_MODE,
        "native_huss_mean_qsat_margin_kgkg":cap-native["huss"],
        "solver_name":"FIXED_PRESSURE_BOUND_T_SLSQP",
        "SLSQP_iterations":int(solution.nit)}

def _eligible(donors,t):
    mon=t["date"].month
    wet=native_target(t)["pr_mm_day"]>0
    for d in donors:
        if d.date.month==mon and ((sum(v["precipitation"] for v in d.vectors)>0)==wet):
            if d.date.year==t["date"].year:
                raise ValueError("P93A_DONOR_TARGET_YEAR_LEAK")
            yield d

def repair_candidate(donor,target,lat,lon):
    temp,diagnostic=repair_temperature_profile(donor,target)
    result,lw,info=new_day(target,donor,lat,lon,temperature_override=temp)
    reconciled,lw,humidity=humidity_reconcile(result,lw,target)
    return reconciled,lw,{**info,**humidity,**diagnostic,
       "native_GCM_pressure_ps_available":False,
       "temperature_morphed_under_external_fixed_hourly_pressure":True,
       "original_source_ERA5_pressure_unmodified":True}

def generate(targets,donors,lat,lon,seed=SEED):
    """Physically scoped source-reconstruction, full-day census preserved.

    First test full P9.2C baseline candidates; do not optimize if source
    pressure and donor T already satisfy source q. If entire baseline pool
    impossible, try eight source-deficit-ranked *independent donor* candidates
    with exact mean/min/max temperature minimal-morph numerical repair.
    """
    if not targets or not donors:raise ValueError("P93A_EMPTY_SOURCE")
    if any(d.date.year in {t["date"].year for t in targets} for d in donors):
        raise ValueError("P93A_SOURCE_DONOR_YEAR_LEAK")
    successful=[];blocked=[];prev=None
    for t in targets:
        norm=native_target(t)
        same=list(_eligible(donors,t))
        if not same:
            blocked.append({"date":t["date"].isoformat(),
                "reason":"P93A_NO_WET_DRY_SOURCE_REGIME","attempted_repairs":0})
            prev=None;continue
        # Always start with frozen previous version (no biased source tuning).
        okay,rejected=candidates_for_target(same,t,lat,lon)
        if okay:
            exact=[x for x in okay if x[4]["hurs_joint_status"]=="FEASIBLE_BOTH_Q_AND_RH"]
            use=exact if exact else okay
            chosen=select_donor([x[0] for x in use],{"date":t["date"],**norm},prev,seed)
            found=next(x for x in use if x[0] is chosen)
            d,day,lw,base,hum=found
            diag={**base,**hum,
                  "temperature_repaired":False,"T_max_abs_change_C":0.,
                  "fixed_donor_pressure_Pa_mean":statistics.fmean(
                      v["surface_pressure"]*100 for v in d.vectors),
                  "donor_pressure_source":PRESSURE_MODE,
                  "native_GCM_pressure_ps_available":False,
                  "selected_donor_date":d.date.isoformat(),
                  "n_eligible_baseline_source_donors":len(okay),
                  "attempted_repairs":0,
                  "temperature_morphed_under_external_fixed_hourly_pressure":True}
            successful.append((day,lw,diag));prev=day.vectors[-1];continue
        ranked=[]
        for d in same:
            try:
                deficit=saturation_deficit(d,t)
                ranked.append((deficit,d.date.isoformat(),d))
            except (ValueError,InfeasibleDailyClimate):
                continue
        ranked.sort(key=lambda x:(x[0],x[1]))
        attempt=ranked[:MAX_REPAIR_CANDIDATES]
        viable=[];errors=collections.Counter()
        for deficit,_,d in attempt:
            try:
                day,lw,info=repair_candidate(d,t,lat,lon)
                viable.append((d,day,lw,info))
            except (ValueError,InfeasibleDailyClimate) as exc:
                errors[str(exc).split(": ")[-1]]+=1
        if viable:
            exact=[x for x in viable if x[3]["hurs_joint_status"]=="FEASIBLE_BOTH_Q_AND_RH"]
            choose=exact if exact else viable
            donor=select_donor([x[0] for x in choose],
                               {"date":t["date"],**norm},prev,seed)
            d,day,lw,meta=next(x for x in choose if x[0] is donor)
            successful.append((day,lw,{**meta,"selected_donor_date":d.date.isoformat(),
                "n_eligible_baseline_source_donors":0,
                "attempted_repairs":len(attempt),
                "n_repaired_candidates_feasible":len(viable),
                "all_repair_attempt_errors":dict(errors)}))
            prev=day.vectors[-1]
        else:
            blocked.append({"date":t["date"].isoformat(),
              "reason":"P93A_FIXED_PRESSURE_OR_NATIVE_DAILY_CONSTRAINTS_UNRESOLVED",
              "n_available_wet_dry_donors":len(same),
              "n_original_baseline_source_rejections":dict(rejected),
              "attempted_repairs":len(attempt),
              "all_repair_attempt_errors":dict(errors),
              "no_pressure_optimization_or_native_huss_modification":True})
            prev=None
    return successful,blocked
