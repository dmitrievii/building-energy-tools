#!/usr/bin/env python3
"""P9.3B3 source-honest joint T/P/q/RH closure: exact convex water projection.

Cannot recover native downscaled CanESM5 ps from NASA NEX-GDDP-CMIP6.
Fixed, externally sourced original ERA5 pressure does not become GCM ps.
Physical feasibility at external donor pressure != future weather accuracy.

C1: unique minimum L2 q displacement with hourly q saturation bounds and
an exact prescribed native daily specific-humidity sum. KKT capped simplex.
C2: diagnostic ONLY if native q daily mass cannot fit at fixed T/P.
hurs is nonlinearly averaged; never silently impose it as a second hard
constraint. Conservative mathematically certified RH daily feasible bounds.
"""
from __future__ import annotations
import math,statistics
from p9_2b_cmip6_daily_joint_regime_solver import (
    EPS,sat_pa,q_of_e,e_of_q,qsat,dewpoint_of_q,
    native_target,source_hourly_mean_temperature,InfeasibleDailyClimate)
VERSION="IGE_P9_3B3_C1_WATER_MASS_PROJECT_C2_FAIL_CLOSED_LOG_V1"
PRESSURE_SOURCE="OPENMETEO_ERA5_ORIGINAL_DONOR_P_NOT_NEX_GCM_NATIVE_PS"
SAT_MARGIN=2e-9
MASS_TOL=1e-10  # daily mean q mass, kg/kg
RH_EXACT_TOL_PP=1e-6
N=24

def _bounded_allocation(box_lo,box_hi,total,coeff,largest=False):
    """Exact linear min/max via fill ordered free box capacity."""
    if not (len(box_lo)==len(box_hi)==len(coeff)==N):
        raise ValueError("P93B3_BAD_LINEAR_BOUND_DIMENSIONS")
    rest=total-sum(box_lo)
    if rest < -1e-11 or rest>sum(h-l for l,h in zip(box_lo,box_hi))+1e-11:
        raise ValueError("P93B3_LINEAR_RH_MASS_OUTSIDE_BOUNDS")
    out=list(box_lo)
    for idx in sorted(range(N),key=lambda i:(
       -coeff[i] if largest else coeff[i],i)):
        delta=min(max(0.,rest),box_hi[idx]-box_lo[idx])
        out[idx]+=delta
        rest-=delta
    if abs(rest)>1e-9:
        raise ValueError("P93B3_LINEAR_RH_BOUND_NOT_CONSERVED")
    return sum(a*b for a,b in zip(out,coeff))/N

def conservative_RH_bounds(T,p,lo,hi,total):
    """Rigorous (sometimes loose) outer enclosure of achievable daily mean RH.

    Since e(q)=p*q/(eps+(1-eps)*q) is concave monotone on q>=0,
    RH(q)/q coefficient at hi is a LOWER bound, at lo an UPPER
    bound. Linear mass allocation gives a necessary enclosure, not
    a sufficient existence certificate for a desired daily hurs.
    """
    if not (len(T)==len(p)==len(lo)==len(hi)==N):
        raise ValueError("P93B3_RH_BOUND_DIMENSION")
    lower_coef=[100*P/(sat_pa(t)*(EPS+(1-EPS)*qh))
                for t,P,qh in zip(T,p,hi)]
    upper_coef=[100*P/(sat_pa(t)*(EPS+(1-EPS)*ql))
                for t,P,ql in zip(T,p,lo)]
    low=_bounded_allocation(lo,hi,total,lower_coef,largest=False)
    high=_bounded_allocation(lo,hi,total,upper_coef,largest=True)
    if not (-1e-8<=low<=high+1e-7 and high<=105):
        raise ValueError("P93B3_RH_OUTER_BOUND_INVALID")
    return max(0.,low),min(100.,high)

def _project_mass(q0,lo,hi,total):
    """KKT Euclidean projection: q_h=clip(q0_h+lambda,lo_h,hi_h)."""
    if total<sum(lo)-1e-11 or total>sum(hi)+1e-11:
        raise ValueError("P93B3_C1_TOTAL_OUTSIDE_PHYSICAL_INTERVAL")
    if abs(total-sum(lo))<=1e-12:return list(lo)
    if abs(total-sum(hi))<=1e-12:return list(hi)
    left=min(a-b for a,b in zip(lo,q0))
    right=max(a-b for a,b in zip(hi,q0))
    def projected_shift(lam):
        return [min(h,max(l,q+lam)) for q,l,h in zip(q0,lo,hi)]
    for _ in range(160):
        mid=(left+right)/2
        if sum(projected_shift(mid))<total:left=mid
        else:right=mid
    result=projected_shift((left+right)/2)
    if abs(sum(result)-total)>N*MASS_TOL:
        raise ValueError("P93B3_C1_Q_PROJECTION_MASS_NOT_EXACT")
    return result

def project_state(temperature_C,pressure_Pa,original_donor_q,
                  native_huss,native_hurs,pressure_source=PRESSURE_SOURCE):
    """Physically project one original 24h profile at FIXED external p and T.

    Result hourly states ONLY on C1 exact native q mass success. C2 for
    infeasible mass is a counterfactual diagnostic, never an accepted day.
    """
    T=[float(x) for x in temperature_C]
    P=[float(x) for x in pressure_Pa]
    q0=[float(x) for x in original_donor_q]
    if any(len(x)!=N for x in (T,P,q0)):
        raise ValueError("P93B3_EXPECT_24_HOURLY_T_P_Q")
    if not isinstance(pressure_source,str) or not pressure_source.strip():
        raise ValueError("P93B3_PRESSURE_ORIGINAL_PROVENANCE_REQUIRED")
    if (not all(math.isfinite(v) for values in (T,P,q0) for v in values)
      or any(not -90<t<65 for t in T)
      or any(not 30000<P0<115000 for P0 in P)
      or any(not 0<=q<.1 for q in q0)
      or not math.isfinite(native_huss) or not 0<native_huss<.1
      or not math.isfinite(native_hurs) or not 0<=native_hurs<=100):
        raise ValueError("P93B3_ORIGINAL_PHYSICAL_INPUT_DOMAIN")
    lo=[q_of_e(sat_pa(-90.)*1.0000001,p) for p in P]
    hi=[qsat(t,p)*(1-SAT_MARGIN) for t,p in zip(T,P)]
    if any(a>=b for a,b in zip(lo,hi)):
        raise ValueError("P93B3_AT_FIXED_T_P_NO_VALID_Q_BOUNDS")
    target_total=N*native_huss
    low_total=sum(lo);high_total=sum(hi)
    ledger={
       "source_pressure":pressure_source,
       "source_pressure_fixed_24h":True,
       "native_NEX_GCM_ps_does_not_exist":True,
       "native_huss_target_kgkg":native_huss,
       "native_hurs_target_percent":native_hurs,
       "original_ERA5_donor_huss_mean_kgkg":statistics.fmean(q0),
       "hourly_temperature_unchanged":True,
       "hourly_pressure_unchanged":True,
       "physical_water_mass_capacity_daily_mean_kgkg":high_total/N,
       "physical_water_mass_minimum_daily_mean_kgkg":low_total/N,
       "saturation_convention":"Buck_1981_1996_over_liquid_original_P92B",
       "saturation_over_ice_temperature_below_zero_not_qualified":any(t<0 for t in T),
       "C2_if_infeasible_is_DIAGNOSTIC_ONLY":True,
       "NEVER_export_EPWs_from_C2_diagnostic":True}
    if target_total>high_total+N*MASS_TOL or target_total<low_total-N*MASS_TOL:
        status=("NATIVE_HUSS_ABOVE_FIXED_T_P_SATURATION_CAPACITY" if
             target_total>high_total else "NATIVE_HUSS_BELOW_FIXED_T_P_NUMERICAL_FLOOR")
        boundary_total=high_total if target_total>high_total else low_total
        ledger.update({
           "status":"C2_FAIL_CLOSED_DIAGNOSTIC_ONLY",
           "reason":status,
           "native_huss_unavoidable_absolute_daily_mean_correction_kgkg":
                  abs(target_total-boundary_total)/N,
           "native_huss_unavoidable_signed_daily_mean_deficit_kgkg":
                  (target_total-boundary_total)/N,
           "hypothetical_boundary_q_mean_kgkg":boundary_total/N,
           "native_daily_huss_if_boundary_used_would_be_violated":True,
           "C1_hard_native_water_mass_conserved":False,
           "hourly_physically_accepted":False})
        return {"status":"C2_FAIL_CLOSED_DIAGNOSTIC_ONLY",
           "hourly":None,"ledger":ledger}
    if target_total>high_total:target_total=high_total
    if target_total<low_total:target_total=low_total
    q=_project_mass(q0,lo,hi,target_total)
    q_mean=statistics.fmean(q)
    if abs(q_mean-native_huss)>MASS_TOL:
        raise ValueError("P93B3_NATIVE_Q_MASS_FAILED_A_POSTERIORI")
    rh=[];dew=[];vapor=[]
    for temp,p,x in zip(T,P,q):
        e=e_of_q(x,p)
        R=100*e/sat_pa(temp)
        dp=dewpoint_of_q(x,p,temp)
        if not (0<=R<=100+1e-7 and dp<=temp+1e-7 and x<=qsat(temp,p)+1e-12):
            raise ValueError("P93B3_C1_HOURLY_SUPERSATURATION")
        rh.append(R);dew.append(dp);vapor.append(e)
    rh_avg=statistics.fmean(rh)
    rh_lo,rh_hi=conservative_RH_bounds(T,P,lo,hi,N*native_huss)
    if not rh_lo-1e-6<=rh_avg<=rh_hi+1e-6:
        raise ValueError("P93B3_RH_CERTIFIED_ENCLOSURE_BROKEN")
    outside=native_hurs<rh_lo-1e-6 or native_hurs>rh_hi+1e-6
    rh_residual=rh_avg-native_hurs
    rh_state=("EXACT_AT_CONVEX_PROJECTED_Q_STATE" if abs(rh_residual)<=RH_EXACT_TOL_PP
              else "NATIVE_HURS_PROVEN_INCOMPATIBLE_OUTER_RH_BOUND" if outside
              else "NONZERO_HURS_RESIDUAL_JOINT_FEASIBILITY_NOT_PROVEN")
    ledger.update({
        "status":"C1_HARD_T_P_HUSS_PHYSICALLY_CLOSED",
        "C1_hard_native_water_mass_conserved":True,
        "hourly_physically_accepted":True,
        "reconstructed_huss_daily_mean_kgkg":q_mean,
        "native_huss_residual_kgkg":q_mean-native_huss,
        "reconstructed_hurs_daily_mean_percent":rh_avg,
        "native_hurs_residual_percentage_points":rh_residual,
        "native_hurs_joint_status":rh_state,
        "native_hurs_proven_outside_conservative_bound":outside,
        "native_hurs_conservative_daily_lower_bound_percent":rh_lo,
        "native_hurs_conservative_daily_upper_bound_percent":rh_hi,
        "native_daily_hurs_is_NOT_an_imposed_hard_constraint":True,
        "original_donor_q_to_projected_q_L2_kgkg":
          math.sqrt(sum((a-b)**2 for a,b in zip(q,q0))),
        "original_donor_q_to_projected_q_mean_signed_kgkg":
          statistics.fmean(a-b for a,b in zip(q,q0)),
        "max_hourly_q_adjustment_kgkg":max(abs(a-b) for a,b in zip(q,q0)),
        "minimum_hourly_relative_humidity_percent":min(rh),
        "maximum_hourly_relative_humidity_percent":max(rh),
        "source_T_and_P_morph_hours":0
        })
    return {"status":"C1_HARD_T_P_HUSS_PHYSICALLY_CLOSED",
       "hourly":{"temperature_C":T,"pressure_Pa":P,"specific_humidity_kgkg":q,
                 "relative_humidity_percent":rh,"dewpoint_C":dew,
                 "water_vapour_partial_pressure_Pa":vapor},
       "ledger":ledger}

def reconstruct_day(target,original_donor):
    """Deterministic original weather pressure donor one-day T/q reconstruction."""
    native=native_target(target)
    if original_donor.date.year==target["date"].year:
        raise ValueError("P93B3_GCM_TARGET_YEAR_DONOR_LEAK")
    if original_donor.date.month!=target["date"].month:
        raise ValueError("P93B3_MONTH_MISMATCH")
    donor_wet=sum(v["precipitation"] for v in original_donor.vectors)>0
    if donor_wet!=(native["pr_mm_day"]>0):
        raise ValueError("P93B3_WET_DRY_SOURCE_REGIME_MISMATCH")
    T=source_hourly_mean_temperature(original_donor,native)
    P=[x["surface_pressure"]*100 for x in original_donor.vectors]
    baseline_q=[q_of_e(sat_pa(x["dew_point_2m"]),p)
                for x,p in zip(original_donor.vectors,P)]
    proj=project_state(T,P,baseline_q,native["huss"],native["hurs"])
    proj["ledger"].update({
       "target_original_date":target["date"].isoformat(),
       "donor_original_date":original_donor.date.isoformat(),
       "donor_original_weather_sha256":original_donor.original_sha256,
       "native_daily_tmean_C":native["tas_c"],
       "native_daily_tmin_C":native["tasmin_c"],
       "native_daily_tmax_C":native["tasmax_c"],
       "original_native_wet_day":native["pr_mm_day"]>0,
       "temperature_mean_exact":abs(statistics.fmean(T)-native["tas_c"])<1e-6,
       "temperature_min_exact":abs(min(T)-native["tasmin_c"])<1e-6,
       "temperature_max_exact":abs(max(T)-native["tasmax_c"])<1e-6,
       "source_CanESM5_ps_original_absent":True})
    return proj
