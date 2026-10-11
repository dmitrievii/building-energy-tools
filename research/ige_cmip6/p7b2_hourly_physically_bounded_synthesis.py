#!/usr/bin/env python3
"""IGE P7B.2: model-day 2013 calibrated-source synthetic hourly EPW prototype.

- No observational event-date pairing, no alteration of frozen P7B outputs.
- Pre-registered GeoSphere daily GHI climatological calibration 2005-2009;
  2010-2011 excluded for documented ten-minute/daily disagreements,
  2012-2014 independent, unpaired climatological holdout.
- Moisture hierarchy: attempt both source daily mean hurs + huss at fixed
  hydrostatic pressure; if infeasible, preserve huss, report hurs mismatch;
  if beyond saturation, preserve physical RH<=100 and report huss shortfall.
- Source daily GHI explicitly changed by calibration; NEW corrected GHI
  target conserved by hourly partition (not false original-GCM conservation).
Research only; neither future SSP EPW nor calibrated hourly skill.
"""
from __future__ import annotations
import argparse,csv,json,math
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from statistics import fmean
from p6_2d_solar_methods_benchmark import checksum
from p6_3c_precip_semantics_daily_alignment import save_union
from p7b1_moisture_solar_feasibility import (
    original_model_daily,original_p7b_hourly,original_geosphere_daily,
    P_PROXY, MODEL_YEARS, q_from_t_rh,dewpoint)
from p7b_daily_to_hourly_cmip6_pilot import (
    solar_curve,epw_rows,NONLEAP_HOURS,TZ_CET,STATION_LAT,STATION_LON,
    GRID_ELEVATION_PROXY_M)

TRAIN_YEARS=(2005,2006,2007,2008,2009)
EXCLUDED_SOURCE_CONFLICT_YEARS=(2010,2011)
HOLDOUT_YEARS=(2012,2013,2014)
ALL_SOURCE_YEARS=TRAIN_YEARS+EXCLUDED_SOURCE_CONFLICT_YEARS+HOLDOUT_YEARS
TARGET_YEAR=2013
RH_MIN=1.0
RH_MAX=100.0
SHAPE_LEVELS=(10.,20.,30.,40.,60.,80.,100.)
Q_TOL=1.e-9
HURS_TOL=1.e-8
SOLAR_FACTOR_BOUNDS=(.45,1.2)
MODEL_NAME="CanESM5"
SYNTHETIC_FILENAME="Graz_2013_CanESM5_P7B2_HISTORICAL_BIASCORRECTED_SYNTHETIC_RESEARCH.epw"

def specific_humidity_of_profile(t,rh,pressure):
    return fmean(q_from_t_rh(x,r,pressure) for x,r in zip(t,rh))

def filled_rh_ordered(temps,mean_rh,amplitude,reverse):
    """Spread humidity to warm or cold hours while preserving exact mean RH.

    Greedy extrema are a transparent *reachable family*, not proof of
    all possible physical profiles; no source values are modified.
    """
    if len(temps)!=24 or not (RH_MIN<=mean_rh<=RH_MAX):
        raise ValueError("Invalid source diurnal humidity support")
    low=max(RH_MIN,mean_rh-amplitude)
    high=min(RH_MAX,mean_rh+amplitude)
    vals=[low]*24
    remain=24*(mean_rh-low)
    for i in sorted(range(24),key=lambda k:temps[k],reverse=reverse):
        amount=min(high-low,remain)
        vals[i]+=amount
        remain-=amount
    if abs(remain)>1.e-8 or abs(fmean(vals)-mean_rh)>1.e-8:
        raise ValueError("Daily source RH mean not preserved by humidity boundary")
    return vals

def blend_to_q(temps,mid_rh,edge_rh,desired_q,pressure):
    q0=specific_humidity_of_profile(temps,mid_rh,pressure)
    qedge=specific_humidity_of_profile(temps,edge_rh,pressure)
    if not min(q0,qedge)-Q_TOL<=desired_q<=max(q0,qedge)+Q_TOL:
        return None
    if abs(qedge-q0)<Q_TOL:
        return mid_rh if abs(q0-desired_q)<Q_TOL else None
    left,right=0.,1.
    for _ in range(55):
        a=(left+right)/2
        trial=[x+(y-x)*a for x,y in zip(mid_rh,edge_rh)]
        q=specific_humidity_of_profile(temps,trial,pressure)
        if (q<desired_q)==(q0<qedge):
            left=a
        else:right=a
    alpha=(left+right)/2
    return [x+(y-x)*alpha for x,y in zip(mid_rh,edge_rh)]

def solve_moisture(temps,mean_rh,target_q,pressure=P_PROXY):
    """Return fully physical hourly RH, with source hierarchy separately tagged."""
    if (len(temps)!=24 or any(not math.isfinite(t) or not -70<t<70
                             for t in temps) or
        not RH_MIN<=mean_rh<=RH_MAX or
        not math.isfinite(target_q) or not 0<target_q<.1 or
        not 70000<pressure<110000):
        raise ValueError("Original daily moisture constraints unavailable/unphysical")
    flat=[mean_rh]*24
    qflat=specific_humidity_of_profile(temps,flat,pressure)
    solution=None
    used_amp=None
    for amp in SHAPE_LEVELS:
        edges=[filled_rh_ordered(temps,mean_rh,amp,False),
               filled_rh_ordered(temps,mean_rh,amp,True)]
        for edge in edges:
            candidate=blend_to_q(temps,flat,edge,target_q,pressure)
            if candidate is not None and abs(
                    specific_humidity_of_profile(temps,candidate,pressure)-target_q
                 )<Q_TOL:
                solution=candidate;used_amp=amp
                break
        if solution is not None:break
    if solution is not None:
        status="JOINT_HURS_HUSS_CLOSED_BOUNDED_HOURLY_RH"
    else:
        # Original daily means incompatible within registered RH profiles.
        # Preserve source huss if physically feasible at this pressure,
        # explicitly relax original daily mean hurs. Constant RH is
        # defensible as a flat *research proxy* but not hourly calibration.
        qmin=specific_humidity_of_profile(temps,[RH_MIN]*24,pressure)
        qmax=specific_humidity_of_profile(temps,[RH_MAX]*24,pressure)
        if qmin-Q_TOL<=target_q<=qmax+Q_TOL:
            lo,hi=RH_MIN,RH_MAX
            for _ in range(65):
                mid=(lo+hi)/2
                q=specific_humidity_of_profile(temps,[mid]*24,pressure)
                if q<target_q:lo=mid
                else:hi=mid
            solution=[(lo+hi)/2]*24
            status="HUSS_PRIORITIZED_HURS_RELAXED_CONSTANT_RH_PROXY"
        else:
            solution=[RH_MAX if target_q>qmax else RH_MIN]*24
            status="SOURCE_HUSS_UNACHIEVABLE_AT_PRESSURE_WITH_SATURATION_BOUND"
    for rh in solution:
        if not RH_MIN-1e-8<=rh<=RH_MAX+1e-8:
            raise ValueError("Computed physically impossible RH")
    dps=[dewpoint(t,rh) for t,rh in zip(temps,solution)]
    if any(td>t+1e-7 for td,t in zip(dps,temps)):
        raise ValueError("Candidate dewpoint exceeds dry bulb")
    recovered_q=specific_humidity_of_profile(temps,solution,pressure)
    recovered_rh=fmean(solution)
    return solution,dps,{
       "status":status,
       "source_hurs_pct":mean_rh,
       "reconstructed_hurs_pct":recovered_rh,
       "reconstructed_minus_source_hurs_pp":recovered_rh-mean_rh,
       "source_huss_kg_kg":target_q,
       "reconstructed_huss_kg_kg":recovered_q,
       "reconstructed_minus_source_huss_kg_kg":recovered_q-target_q,
       "native_original_constant_rh_huss_kg_kg":qflat,
       "registered_rh_amplitude_pp":used_amp,
       "hourly_rh_min_pct":min(solution),
       "hourly_rh_max_pct":max(solution),
       "max_consecutive_hour_rh_change_pp":
           max(abs(a-b) for a,b in zip(solution[:-1],solution[1:])),
       "source_pressure_used_pa":pressure,
       "pressure_measured_in_original_model":False,
       "daily_huss_conserved":abs(recovered_q-target_q)<Q_TOL,
       "daily_hurs_conserved":abs(recovered_rh-mean_rh)<HURS_TOL,
       "physically_bounded":True}

def model_ghi_days_by_year_month(model):
    result=defaultdict(list)
    for r in model:
        y=int(r["year"])
        if y in ALL_SOURCE_YEARS:
            v=float(r["rsds_kwh_m2_day"])
            if v<0 or not math.isfinite(v):raise ValueError("Invalid model daily original GHI")
            result[(y,int(r["month"]))].append(v)
    if any(sum(len(result[(y,m)]) for m in range(1,13))!=365
           for y in ALL_SOURCE_YEARS):
        raise ValueError("Original noleap CMIP6 daily 10-year completeness missing")
    return result

def observed_ghi_days_by_year_month(station):
    result=defaultdict(list)
    for year,seq in station.items():
        for month,v in seq:result[(year,month)].append(v)
    return result

def monthly_factors(model,station):
    """Train only 2005–09; quarantine 2010–11; holdout 2012–14."""
    sm=model_ghi_days_by_year_month(model)
    so=observed_ghi_days_by_year_month(station)
    factors=[];lookup={}
    for m in range(1,13):
        a=[v for y in TRAIN_YEARS for v in sm[(y,m)]]
        b=[v for y in TRAIN_YEARS for v in so[(y,m)]]
        source_avg=fmean(a);measured_avg=fmean(b)
        f=measured_avg/source_avg
        if not SOLAR_FACTOR_BOUNDS[0]<=f<=SOLAR_FACTOR_BOUNDS[1]:
            raise ValueError(f"Observed/model monthly GHI calibration factor {m} outside preregistered physically reviewable range")
        lookup[m]=f
        factors.append({"month":m,"train_years":"2005-2009",
            "source":"GeoSphere Graz original daily ground-observed GHI vs CanESM5 daily NASA NEX BCSD",
            "original_model_mean_daily_ghi_kwh_m2":source_avg,
            "original_station_mean_daily_ghi_kwh_m2":measured_avg,
            "observed_to_model_factor":f,
            "train_total_original_source_days":len(a),
            "train_total_original_station_days":len(b),
            "2010_2011_excluded_source_daily_10min_mismatch":True,
            "holdout_2012_2014_excluded_from_fit":True,
            "future_SSP_validated":False})
    return lookup,factors,sm,so

def holdout_climatology(factors,sm,so):
    stats=[];raw_error=[];corr_error=[]
    for m in range(1,13):
        a=[v for y in HOLDOUT_YEARS for v in sm[(y,m)]]
        b=[v for y in HOLDOUT_YEARS for v in so[(y,m)]]
        av=fmean(a);bv=fmean(b);cv=av*factors[m]
        raw_error.append(av-bv)
        corr_error.append(cv-bv)
        stats.append({"month":m,
             "model_holdout_days":len(a),"station_holdout_days":len(b),
             "original_model_unpaired_mean_daily_kwh_m2":av,
             "station_ground_observed_holdout_mean_daily_kwh_m2":bv,
             "corrected_model_holdout_mean_daily_kwh_m2":cv,
             "before_model_minus_observed_pct":100*(av/bv-1),
             "after_model_minus_observed_pct":100*(cv/bv-1),
             "calibration_years":"2005-2009",
             "holdout_years":"2012-2014",
             "validation_metric":"UNPAIRED_MONTH_CLIMATOLOGY_NOT_DAY_MATCHED"})
    summary={
        "unpaired_monthly_climatology_bias_mae_before_kwh_m2_day":
            fmean(abs(x) for x in raw_error),
        "unpaired_monthly_climatology_bias_mae_after_kwh_m2_day":
            fmean(abs(x) for x in corr_error),
        "unpaired_monthly_climatology_rmse_before_kwh_m2_day":
            math.sqrt(fmean(x*x for x in raw_error)),
        "unpaired_monthly_climatology_rmse_after_kwh_m2_day":
            math.sqrt(fmean(x*x for x in corr_error)),
        "heldout_annual_365day_normalized_model_unadjusted_kwh_m2":
            fmean(sum(sum(sm[(y,m)]) for m in range(1,13)) for y in HOLDOUT_YEARS),
        "heldout_annual_365day_normalized_model_corrected_kwh_m2":
            fmean(sum(sum(sm[(y,m)])*factors[m] for m in range(1,13))
                  for y in HOLDOUT_YEARS),
        "heldout_annual_365day_normalized_station_observed_kwh_m2":
            fmean(sum(sum(so[(y,m)]) for m in range(1,13))*365/
                  sum(len(so[(y,m)]) for m in range(1,13)) for y in HOLDOUT_YEARS)}
    summary["holdout_annual_pct_before"]=100*(
        summary["heldout_annual_365day_normalized_model_unadjusted_kwh_m2"]/
        summary["heldout_annual_365day_normalized_station_observed_kwh_m2"]-1)
    summary["holdout_annual_pct_after"]=100*(
        summary["heldout_annual_365day_normalized_model_corrected_kwh_m2"]/
        summary["heldout_annual_365day_normalized_station_observed_kwh_m2"]-1)
    return stats,summary

def write_epw(path,hours):
    if len(hours)!=NONLEAP_HOURS:
        raise ValueError("P7B.2 EPW must have 8760 hours")
    header=[
      ["LOCATION","Graz CMIP6 grid corrected to GeoSphere","Styria","AUT",
       "IGE_P7B2_RESEARCH_ONLY","999999",STATION_LAT,STATION_LON,1,GRID_ELEVATION_PROXY_M],
      ["DESIGN CONDITIONS",0],["TYPICAL/EXTREME PERIODS",0],
      ["GROUND TEMPERATURES",0],
      ["HOLIDAYS/DAYLIGHT SAVINGS","No",0,0,0],
      ["COMMENTS 1","Synthetic CanESM5 2013 model weather, corrected GHI via 2005-2009 station climatology; NOT measured 2013"],
      ["COMMENTS 2","huss prioritized with explicit RH tradeoffs; pressure proxy; no wind direction; research only; see science audit"],
      ["DATA PERIODS",1,1,"P7B2 unpaired GCM historical model calendar","Tuesday","1/1","12/31"]]
    with path.open("w",encoding="utf8",newline="") as f:
        writer=csv.writer(f,lineterminator="\n")
        writer.writerows(header)
        writer.writerows(epw_rows(hours))
    with path.open("r",encoding="utf8",newline="") as f:
        read=list(csv.reader(f))
    if len(read)!=8768 or any(len(r)!=35 for r in read[8:]):
        raise ValueError("P7B.2 EPW read-back 8 headers / 8760 ×35 rows failed")
    for i,row in enumerate(read[8:]):
        target=datetime(TARGET_YEAR,1,1,tzinfo=TZ_CET)+timedelta(hours=i)
        if list(map(int,row[:5]))!=[TARGET_YEAR,target.month,target.day,target.hour+1,60]:
            raise ValueError("EPW fixed CET source time/calendar invalid")
    return checksum(path)

def generate(model,basehours,lookup):
    native={r["date"]:r for r in model if int(r["year"])==TARGET_YEAR}
    if len(native)!=365 or len(basehours)!=365:
        raise ValueError("P7B.2 original synthetic and model daily support incomplete")
    months=[];hours=[];closure=[];states=Counter()
    for day in sorted(native):
        raw=basehours[day]
        daily=native[day]
        temp=[float(r["T_C"]) for r in raw]
        meanRH=float(daily["hurs"]);qtarget=float(daily["huss"])
        pressure=float(raw[0]["pressure_pa"])
        rh,td,diag=solve_moisture(temp,meanRH,qtarget,pressure)
        localdate=datetime.fromisoformat(day).date()
        original_g=float(daily["rsds_kwh_m2_day"])
        factor=lookup[int(daily["month"])]
        corrected_g=original_g*factor
        solar=solar_curve(corrected_g,localdate)
        records=[]
        for i,source in enumerate(raw):
            gh,dn,dh,review,_=solar[i]
            r={k:float(source[k]) for k in ("T_C","wind_ms","rain_mm",
                    "sky_lw_Wh","pressure_pa","solar_coszen","toa_horizontal_Wh")}
            r.update({
               "local_hour":datetime(localdate.year,localdate.month,
                                     localdate.day,i,tzinfo=TZ_CET),
               "date":day,"hour":i,
               "RH_pct":rh[i],"dewpoint_C":td[i],
               "ghi_Wh":gh,"dni_Wh":dn,"dhi_Wh":dh,
               "solar_partition_review":review,
               "humidity_source_status":diag["status"],
               "wind_direction_source":"UNAVAILABLE_NOT_MEASURED",
               "pressure_source":"STANDARD_ATMOSPHERE_ELEVATION_PROXY_NOT_OBSERVED",
               "solar_source":"GCM_ORIGINAL_DAILY_RSDS_MONTH_BIAS_FACTOR_GEOSPHERE_GROUND_GHI",
               "solar_original_daily_factor":factor,
               "DNI_DHI_are_measured":False,
               "calibrated_station_solar_source_dates":"2005-2009_ONLY",
               "2020plus_scenario_generated":False})
            if not (rh[i]>0 and rh[i]<=100 and td[i]<=r["T_C"]+1e-7):
                raise ValueError("Invalid generated humidity physical state")
            records.append(r);hours.append(r)
        states[diag["status"]]+=1
        new_solar=sum(r["ghi_Wh"] for r in records)/1000
        new_lw=sum(r["sky_lw_Wh"] for r in records)/1000
        native_rain=sum(r["rain_mm"] for r in records)
        if max(abs(new_solar-corrected_g),
               abs(new_lw-float(daily["rlds_kwh_m2_day"])),
               abs(native_rain-float(daily["pr_mm_day"])))>1e-7:
            raise ValueError("Regenerated GHI energy, rain or longwave source day not conserved")
        if max(abs(max(temp)-float(daily["tasmax_c"])),
               abs(min(temp)-float(daily["tasmin_c"])),
               abs(fmean(temp)-float(daily["tas_c"])))>1e-7:
            raise ValueError("Regenerated source native T mean/extrema changed")
        if any(abs(r["ghi_Wh"]-r["dhi_Wh"]-
                   r["dni_Wh"]*max(0,r["solar_coszen"]))>1e-6 for r in records):
            raise ValueError("Hourly DNI+DHI-GHI closure failed")
        closure.append({**diag,
             "date":day,"month":int(daily["month"]),
             "original_can_esm5_native_GHI_kwh_m2_day":original_g,
             "calibrated_GHI_kwh_m2_day":corrected_g,
             "solar_calibration_factor":factor,
             "deliberate_GHI_source_change_kwh_m2_day":corrected_g-original_g,
             "hourly_reconstructed_GHI_kwh_m2_day":new_solar,
             "calibrated_GHI_day_error":new_solar-corrected_g,
             "native_rain_day_error":native_rain-float(daily["pr_mm_day"]),
             "native_lw_day_error":new_lw-float(daily["rlds_kwh_m2_day"]),
             "solar_component_review_hours":sum(r["solar_partition_review"] for r in records),
             "temperature_extrema_mean_preserved":True,
             "native_wind_daily_mean_preserved":True,
             "calibration_excludes_model_2013_and_geosphere_2013":True})
    if len(hours)!=NONLEAP_HOURS:raise ValueError("Missing generated 2013 hourly support")
    return hours,closure,states

def run(model_root,p7b_root,station_root,out):
    out.mkdir(parents=True,exist_ok=True)
    model,modelsha=original_model_daily(model_root)
    basehours,base_sha,base_audit=original_p7b_hourly(p7b_root)
    station,station_sha=original_geosphere_daily(station_root)
    factors,factor_rows,sm,so=monthly_factors(model,station)
    holdout,holdout_summary=holdout_climatology(factors,sm,so)
    hours,days,states=generate(model,basehours,factors)
    epw=out/SYNTHETIC_FILENAME
    epwsha=write_epw(epw,hours)
    rows=[]
    for x in hours:
        r=dict(x)
        r["local_hour"]=x["local_hour"].isoformat()
        rows.append(r)
    outputs={
      "p7b2_2013_synthetic_hourly_physics_and_sources.csv":rows,
      "p7b2_2013_native_daily_source_and_constraint_tradeoffs.csv":days,
      "p7b2_ground_observed_monthly_GHI_training_factors.csv":factor_rows,
      "p7b2_ground_observed_2012_2014_holdout_months.csv":holdout}
    hashes={p:save_union(out/p,arr) for p,arr in outputs.items()}
    hashes[epw.name]=epwsha
    dailyq=[abs(x["reconstructed_minus_source_huss_kg_kg"]) for x in days]
    dailyrh=[abs(x["reconstructed_minus_source_hurs_pp"]) for x in days]
    status="JOINT_DAILY_SOURCE_MOISTURE_NOT_FEASIBLE_ALL_DAYS"
    audit={
      "stage":"IGE_P7B2_PHYSICALLY_BOUNDED_RESEARCH_HOURLY_SYNTHESIS",
      "technical_status":"HOURLY_PHYSICS_AND_HOLDOUT_GHI_EPW_FORMAT_PASS",
      "scientific_status":status,
      "epw_production_ready":False,
      "source_gcm_model":"CanESM5",
      "historical_model_calendar_year":TARGET_YEAR,
      "is_real_observed_calendar_2013_weather":False,
      "future_SSP_projection_generated":False,
      "source_model_original_daily_sha256":modelsha,
      "source_p7b_original_hourly_sha256":base_sha,
      "source_geosphere_observed_ground_daily_GHI_sha256":station_sha,
      "source_p7b_parent_EPWSHA256":base_audit["hashes"][
        "Graz_2013_CanESM5_P7B_SYNTHETIC_DAILY_TO_HOURLY_RESEARCH.epw"],
      "original_source_can_esm5_rsds_already_NASA_BCSD_corrected":True,
      "additional_monthly_bias_calibration_applied":True,
      "solar_bias_calibration_train_years":list(TRAIN_YEARS),
      "solar_source_conflict_exclusion_years":list(EXCLUDED_SOURCE_CONFLICT_YEARS),
      "solar_unpaired_holdout_years":list(HOLDOUT_YEARS),
      "solar_holdout_metrics":holdout_summary,
      "solar_model_event_dates_not_compared_to_observed_events":True,
      "output_EPWhours":len(hours),
      "original_daily_model_days":len(days),
      "daily_humidity_source_status_counts":dict(states),
      "days_both_source_hurs_and_huss_closed":states["JOINT_HURS_HUSS_CLOSED_BOUNDED_HOURLY_RH"],
      "days_source_huss_closed_hurs_relaxed":states["HUSS_PRIORITIZED_HURS_RELAXED_CONSTANT_RH_PROXY"],
      "days_source_huss_not_feasible_at_fixed_pressure":states["SOURCE_HUSS_UNACHIEVABLE_AT_PRESSURE_WITH_SATURATION_BOUND"],
      "max_abs_daily_huss_source_residual_kg_kg":max(dailyq),
      "max_abs_daily_hurs_source_residual_pp":max(dailyrh),
      "all_8760_hourly_RH_within_1_to_100_and_dewpoint_le_T":True,
      "calibrated_daily_GHI_conserved_each_day":True,
      "original_source_daily_GHI_deliberately_not_conserved":True,
      "original_native_daily_T_wind_precip_LW_conserved":True,
      "hourly_GHI_DHI_DNI_energy_closure":True,
      "DHI_DNI_are_derived_Erbs_not_measured":True,
      "pressure_source":"fixed standard atmosphere 366m, not measured or GCM source",
      "wind_direction_source":"EPW 999 missing; no provider hourly direction",
      "original_P7B_hourly_weather_modified_in_place":False,
      "output_sha256":hashes,
      "limitations":[
         "Historical 2005–2009 ground GHI monthly calibration is 5 training years only, with 2010–2011 excluded for original solar source-resolution mismatch, heldout 2012–2014.",
         "NEX-GDDP-CMIP6 original rsds already bias corrected by NASA BCSD; additional local calibration is explicitly applied, requires multi-model and future-change-signal validation to avoid excessive/double correction.",
         "RH and huss are incompatible on a subset of native model days at fixed pressure. HUSS is prioritized where possible while source hurs is relaxed; high huss beyond all-hour saturation remains unclosed and flagged. Original observations are not falsely changed.",
         "Humidity profiles are bounded and cross-variable coherent but NOT verified against observed hourly RH persistence or wind/rain/cloud copulas.",
         "Original daily GHI is deliberately modified by the monthly calibration. The CALIBRATED, not raw CMIP6 daily GHI target is conserved exactly.",
         "Erbs solar diffuse/direct split based on coarse solar geometry is not independently measured DHI/DNI.",
         "Pressure original source absent, fixed hydrostatic estimate; wind direction missing marker 999; source observed wind/rain timing not modeled.",
         "2013 CMIP6 model days are independent weather realization from real 2013 observed events; only climatological holdout comparisons are valid.",
         "EPW parsed and structural checks pass; EnergyPlus actual simulation has not run; NOT approved for building energy use or future climate production." ]}
    (out/"p7b2_science_audit.json").write_text(
        json.dumps(audit,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P7B2",audit["technical_status"],len(hours),"hours","states",dict(states),
       "max_huss_residual",max(dailyq),"holdout_GHI_orig_pct",
       holdout_summary["holdout_annual_pct_before"],
       "holdout_GHI_calibrated_pct",holdout_summary["holdout_annual_pct_after"],
       "EPW_PRODUCTION_READY",False,flush=True)
    return audit

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--model-original",type=Path,required=True)
    p.add_argument("--p7b-original",type=Path,required=True)
    p.add_argument("--geosphere-daily",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    run(a.model_original,a.p7b_original,a.geosphere_daily,a.out)
