#!/usr/bin/env python3
"""P9.2D original native CanESM5 2013 saturation vs daily T envelope audit.

Does not alter source climate, choose favorable donors, or claim native GCM
pressure (daily source archive does NOT provide native surface pressure).
For each native daily Tmean,Tmin,Tmax, idealized constant P and convex Buck
saturation curve, chord is an UPPER envelope of mean qsat for any T_h
within Tmin..Tmax with that same mean. Real 24h extrema and donor pressure
may be more restrictive. This distinguishes limitations under P hypotheses.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
from p9_2b_cmip6_daily_joint_regime_solver import sat_pa,EPS
import p7c3_ensemble as orig

REGISTERED_BLOCKED_2013_DATES=(
    "2013-02-14","2013-02-21","2013-07-09",
    "2013-11-19","2013-12-11","2013-12-15"
)
PRESSURE_HYPOTHESES_PA=(90000,92500,94000,95000,97000,100000,101325)

def qsat_constant_pressure(T,P):
    e=sat_pa(T)
    if e>=P:raise ValueError("P92D_PRESSURE_BELOW_SATURATION_VAPOR_PRESSURE")
    return EPS*e/(P-(1-EPS)*e)

def convex_temperature_envelope(day,pressure_pa):
    lo=float(day["tasmin_c"]);hi=float(day["tasmax_c"]);mu=float(day["tas_c"])
    if hi<=lo:
        if abs(mu-lo)<1e-8:return qsat_constant_pressure(lo,pressure_pa)
        raise ValueError("P92D_INVALID_NATIVE_T_MINMAX_MEAN")
    if not lo-1e-8<=mu<=hi+1e-8:
        raise ValueError("P92D_INVALID_NATIVE_T_MEAN_OUTSIDE_EXTREMA")
    # finite temperature-resolution monotone curvature sanity check;
    # do not label this a global formal proof of convexity.
    for k in range(1,100):
        t=lo+(hi-lo)*k/100; step=(hi-lo)/1000
        second=(qsat_constant_pressure(t+step,pressure_pa)
                -2*qsat_constant_pressure(t,pressure_pa)
                +qsat_constant_pressure(t-step,pressure_pa))
        if second < -1e-11:
            raise ValueError("P92D_BUCK_QSAT_CONVEXITY_HYPOTHESIS_FAILED")
    weight=(mu-lo)/(hi-lo)
    return (1-weight)*qsat_constant_pressure(lo,pressure_pa)+weight*qsat_constant_pressure(hi,pressure_pa)

def pressure_threshold_native_huss(day):
    q=float(day["huss"])
    lo,hi=50000.,120000.
    if q>convex_temperature_envelope(day,lo):
        return {"threshold_pa":None,"status":"ABOVE_ENVELOPE_EVEN_AT_50KPA"}
    if q<=convex_temperature_envelope(day,hi):
        return {"threshold_pa":None,"status":"BELOW_ENVELOPE_EVEN_AT_120KPA"}
    for _ in range(80):
        p=(lo+hi)/2
        if convex_temperature_envelope(day,p)>q:lo=p
        else:hi=p
    return {"threshold_pa":(lo+hi)/2,
            "status":"SOURCE_HUSS_BELOW_T_EXTREMAL_SATURATION_UP_TO_THIS_PRESSURE"}

def run(canonical_original_gcm_zip,out):
    rows,prov=orig.read_source(canonical_original_gcm_zip,"CanESM5",orig.HIST)
    expected=json.loads(Path("research/ige_cmip6/p7c3_expected_daily_source_shas.json").read_text())["source_sha256"]["CanESM5_historical-1995-2014"]
    if prov["daily_csv_sha256"]!=expected:
        raise ValueError("P92D_ENVELOPE_NATIVE_SOURCE_SHA_NOT_REGISTERED")
    days=[r for r in rows if r["date"].year==2013]
    if len(days)!=365:
        raise ValueError("P92D_ENVELOPE_2013_NATIVE_DAYS_NOT_365")
    cases={}
    for r in days:
        d=r["date"].isoformat()
        threshold=pressure_threshold_native_huss(r)
        if d in REGISTERED_BLOCKED_2013_DATES:
            cases[d]={"original_native_temperature_mean_C":r["tas_c"],
                "original_native_temperature_min_C":r["tasmin_c"],
                "original_native_temperature_max_C":r["tasmax_c"],
                "original_native_daily_huss_g_kg":float(r["huss"])*1000,
                "original_native_daily_hurs_pct":r["hurs"],
                "maximum_idealized_qsat_g_kg_by_hypothesized_pressure":{
                    str(p):convex_temperature_envelope(r,p)*1000 for p in PRESSURE_HYPOTHESES_PA},
                "hypothetical_upper_p_pa_for_constant_p_envelope":threshold["threshold_pa"],
                "pressure_status":threshold["status"]}
    if set(cases)!=set(REGISTERED_BLOCKED_2013_DATES):
        raise ValueError("P92D_ENVELOPE_FIXED_SIX_BLOCKS_NOT_REPRODUCED")
    fractions={}
    for p in PRESSURE_HYPOTHESES_PA:
        count=sum(float(r["huss"])>convex_temperature_envelope(r,p)+1e-12
                  for r in days)
        fractions[str(p)]={"n_native_original_days_huss_exceeds_chord_upper_cap":count,
              "of_total_native_days":365}
    obj={"stage":"P9_2D_ORIGINAL_GCM_DAILY_HUSS_T_EXTREMA_PHYSICAL_PRESSURE_SENSITIVITY",
      "original_gcm_source_native_SHA256":prov["daily_csv_sha256"],
      "native_daily_pressure_not_present_in_NASA_NEX_GDDP_source":True,
      "native_daily_time_definitions_may_differ_from_hourly_donor":True,
      "known_six_source_ERA5_donor_block_dates":list(REGISTERED_BLOCKED_2013_DATES),
      "source_source_ERA5_2019_2020_retrieval_not_repeated":True,
      "not_temperature_shape_fitting_not_pressure_calibration":True,
      "pressure_hypotheses_pa":list(PRESSURE_HYPOTHESES_PA),
      "convex_chord_is_upper_bound_at_fixed_hypothetical_constant_pressure_only":True,
      "temperature_curve_must_match_native_min_mean_max_before_applying":True,
      "n_original_native_2013_days":365,
      "counts_all_2013_by_hypothetical_constant_p":fractions,
      "source_original_six_blocked_days":cases,
      "source_q_is_never_clipped":True,"EPW_qualified":False}
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    (out/"p9_2d_CanESM5_2013_saturation_daily_pressure_envelope.json").write_text(
        json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print("P92D_PRESSURE_ENVELOPE_FINAL",json.dumps({
      "original_source_2013_days":len(days),"six_known_block_dates":len(cases),
      "days_above_cap_at_950hPa":fractions["95000"]["n_native_original_days_huss_exceeds_chord_upper_cap"],
      "days_above_cap_at_970hPa":fractions["97000"]["n_native_original_days_huss_exceeds_chord_upper_cap"],
      "days_above_cap_at_1000hPa":fractions["100000"]["n_native_original_days_huss_exceeds_chord_upper_cap"],
      "six_required_pressure_threshold_Pa":{k:round(v["hypothetical_upper_p_pa_for_constant_p_envelope"])
           if v["hypothetical_upper_p_pa_for_constant_p_envelope"] is not None else None
           for k,v in cases.items()}}),flush=True)
    return obj

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--source-zip",required=True)
    a.add_argument("--out",default="outputs/p92d-envelope")
    v=a.parse_args();run(Path(v.source_zip),Path(v.out))
