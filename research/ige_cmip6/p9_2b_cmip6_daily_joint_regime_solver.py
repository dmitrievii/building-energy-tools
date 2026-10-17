#!/usr/bin/env python3
"""IGE P9.2B: strictly daily-CMIP6 constrained donor-preserving joint hourly weather.

One research pilot; no fitted coefficients or observed station accuracy claims.
Original P9.2A 24h ERA5 source joints supply weather shapes, while daily
NASA NEX-GDDP-CMIP6 supplies hard conservation constraints. Cannot create
credible hourly clouds or local site weather with only daily CMIP6 input.
"""
from __future__ import annotations
import datetime as dt
import math
import random
import statistics
from dataclasses import dataclass
from p9_2a_joint_weather_regimes import Day,check_vector,seam_cost
from p9_1h23_physical_inversion_candidate import solar_altitude_degrees

ALGORITHM="IGE_P9_2B_GCM_JOINT_DAILY_CONSTRAINTS_FROZEN_V1"
EPS=.62198
SIGMA=5.670374419e-8
DAY_FIELDS=("tas_c","tasmin_c","tasmax_c","hurs","huss",
            "pr_mm_day","rsds_kwh_m2_day","rlds_kwh_m2_day","sfcWind")
DAILY_TOLERANCE=1e-6

class InfeasibleDailyClimate(ValueError):
    """Observed donor + GCM target cannot satisfy requested physical hard constraints."""

def sat_pa(t):
    if not -105<t<80:
        raise InfeasibleDailyClimate("P92B_INVALID_T_SATURATION_C")
    return 611.21*math.exp((18.678-t/234.5)*t/(257.14+t))

def q_of_e(e,p):
    return EPS*e/(p-(1-EPS)*e)

def e_of_q(q,p):
    return q*p/(EPS+(1-EPS)*q)

def qsat(t,p):
    e=sat_pa(t)
    if e>=p:
        raise InfeasibleDailyClimate("P92B_SATURATION_PRESSURE_ABOVE_TOTAL")
    return q_of_e(e,p)

def dewpoint_of_q(q,p,t):
    e=e_of_q(q,p)
    if e>sat_pa(t)*(1+1e-8):
        raise InfeasibleDailyClimate("P92B_DERIVED_SUPERSATURATION")
    if e<=0:raise InfeasibleDailyClimate("P92B_ZERO_WATER_VAPOR")
    lo,hi=-104.,t
    for _ in range(75):
        m=(lo+hi)/2
        if sat_pa(m)<e:lo=m
        else:hi=m
    return (lo+hi)/2

def native_target(t):
    if not isinstance(t,dict) or not set(DAY_FIELDS)<=set(t):
        raise InfeasibleDailyClimate("P92B_MISSING_NATIVE_CMIP6_DAILY_VARIABLE")
    if not isinstance(t.get("date"),dt.date):
        raise InfeasibleDailyClimate("P92B_INVALID_NATIVE_DATE")
    try: vals={k:float(t[k]) for k in DAY_FIELDS}
    except (TypeError,ValueError) as exc:
        raise InfeasibleDailyClimate("P92B_NONNUMERIC_DAILY_SOURCE") from exc
    if not all(math.isfinite(x) for x in vals.values()):
        raise InfeasibleDailyClimate("P92B_NONFINITE_NATIVE_SOURCE")
    if not (-90<vals["tasmin_c"]<=vals["tas_c"]<=vals["tasmax_c"]<65):
        raise InfeasibleDailyClimate("P92B_SOURCE_T_MIN_MEAN_MAX_BAD")
    if not (0<=vals["hurs"]<=100 and 0<vals["huss"]<.1
            and 0<=vals["pr_mm_day"]<500 and 0<=vals["rsds_kwh_m2_day"]<20
            and 0<vals["rlds_kwh_m2_day"]<30 and 0<=vals["sfcWind"]<90):
        raise InfeasibleDailyClimate("P92B_NATIVE_SOURCE_FIELDS_OUT_OF_RANGE")
    return vals

def source_hourly_mean_temperature(donor,target):
    lo=target["tasmin_c"];hi=target["tasmax_c"];mean=target["tas_c"]
    values=[float(x["temperature_2m"]) for x in donor.vectors]
    mi=min(values);ma=max(values)
    if hi-lo<1e-10:
        if abs(mean-lo)>1e-8:raise InfeasibleDailyClimate("P92B_FLAT_TARGET_T_NOT_COHERENT")
        return [mean]*24
    if ma-mi<1e-8:
        raise InfeasibleDailyClimate("P92B_DONOR_FLAT_T_EXTREMA_NOT_ADAPTABLE")
    base=[(x-mi)/(ma-mi) for x in values]
    targetfrac=(mean-lo)/(hi-lo)
    maxp=sum(x>0 for x in base)/24
    minp=sum(x>=1-1e-12 for x in base)/24
    if not minp-1e-8<=targetfrac<=maxp+1e-8:
        raise InfeasibleDailyClimate("P92B_SOURCE_T_MEAN_EXTREMA_SHAPE_NOT_FEASIBLE")
    left,right=1e-10,1e10
    for _ in range(150):
        m=math.sqrt(left*right)
        achieved=statistics.fmean(x**m for x in base)
        if achieved>targetfrac:left=m
        else:right=m
    power=math.sqrt(left*right)
    x=[lo+(hi-lo)*(v**power) for v in base]
    if abs(statistics.fmean(x)-mean)>DAILY_TOLERANCE or abs(min(x)-lo)>DAILY_TOLERANCE or abs(max(x)-hi)>DAILY_TOLERANCE:
        raise InfeasibleDailyClimate("P92B_T_DAILY_EXACT_MOMENTS_NOT_CONSERVED")
    return x

def select_donor(donors,target,previous_last,seed):
    cand=[d for d in donors if d.date.month==target["date"].month
          and ((sum(v["precipitation"] for v in d.vectors)>0)==(target["pr_mm_day"]>0))]
    if not cand:
        raise InfeasibleDailyClimate("P92B_NO_ORIGINAL_DONOR_IN_PRESCRIBED_WET_DRY_REGIME")
    if any(d.date.year==target["date"].year for d in cand):
        raise InfeasibleDailyClimate("P92B_GCM_TARGET_YEAR_DONOR_LEAK")
    choices=[]
    for d in cand:
        source_t=statistics.fmean(v["temperature_2m"] for v in d.vectors)
        source_solar=sum(v["shortwave_radiation"] for v in d.vectors)/1000
        source_rain=sum(v["precipitation"] for v in d.vectors)
        source_wind=statistics.fmean(v["wind_speed_10m"] for v in d.vectors)
        source_rh=statistics.fmean(v["relative_humidity_2m"] for v in d.vectors)
        loss=(abs(source_t-target["tas_c"])/10
              +abs(source_solar-target["rsds_kwh_m2_day"])/3
              +abs(source_wind-target["sfcWind"])/7
              +abs(source_rh-target["hurs"])/45
              +(abs(math.log((source_rain+.3)/(target["pr_mm_day"]+.3))) if target["pr_mm_day"]>0 else 0))
        if previous_last is not None:
            loss+=.20*seam_cost(previous_last,d.vectors[0])
        choices.append(loss)
    rng=random.Random(f"P9.2B|{seed}|{target['date'].isoformat()}")
    weights=[math.exp(-min(35.,loss)) for loss in choices]
    threshold=rng.random()*sum(weights)
    for d,w in zip(cand,weights):
        threshold-=w
        if threshold<=0:return d
    return cand[-1]

def distribute_exact(original,capacities,target_total):
    if len(original)!=24 or len(capacities)!=24 or target_total<0:
        raise InfeasibleDailyClimate("P92B_MALFORMED_DAILY_DISTRIBUTION")
    if target_total>sum(capacities)+1e-8:
        raise InfeasibleDailyClimate("P92B_DAILY_TOTAL_EXCEEDS_PHYSICAL_HOURLY_CAPACITY")
    if target_total<=1e-13:return [0.]*24
    if sum(original)<=0:
        raise InfeasibleDailyClimate("P92B_ORIGINAL_DONOR_LACKS_REQUIRED_DAILY_PROFILE")
    weighted=[max(0.,x) for x in original]
    lo,hi=0.,1.
    def mass(scale):return sum(min(c,w*scale) for w,c in zip(weighted,capacities))
    while mass(hi)<target_total-1e-10:
        hi*=2
        if hi>1e15:raise InfeasibleDailyClimate("P92B_DONOR_WEIGHTS_CANNOT_FILL_CAPACITY")
    for _ in range(140):
        middle=(lo+hi)/2
        if mass(middle)<target_total:lo=middle
        else:hi=middle
    result=[min(c,w*hi) for w,c in zip(weighted,capacities)]
    if abs(sum(result)-target_total)>1e-7:
        raise InfeasibleDailyClimate("P92B_DAILY_TOTAL_NOT_CLOSED")
    return result

def geometry(targetdate,lat,lon):
    alts=[]
    for h in range(24):
        date=dt.datetime(targetdate.year,targetdate.month,targetdate.day,h,30,
                         tzinfo=dt.timezone.utc)
        alt=solar_altitude_degrees(date,lat,lon)
        alts.append(max(0.,math.sin(math.radians(alt))))
    return alts

def new_day(target_day,donor,latitude,longitude,temperature_override=None):
    src=native_target(target_day)
    for w in donor.vectors:check_vector(w)
    t=source_hourly_mean_temperature(donor,src)
    if temperature_override is not None:
        # Research-only P9.3A extension; original P9.2B behavior is unchanged.
        # Pressure is never an adjustable optimization variable.
        if len(temperature_override)!=24 or not all(
              isinstance(v,(int,float)) and math.isfinite(v) for v in temperature_override):
            raise InfeasibleDailyClimate("P93A_INVALID_CONSTRAINED_TEMPERATURE_PROFILE")
        t=[float(v) for v in temperature_override]
        if not (abs(statistics.fmean(t)-src["tas_c"])<=1e-6
                and abs(min(t)-src["tasmin_c"])<=1e-6
                and abs(max(t)-src["tasmax_c"])<=1e-6):
            raise InfeasibleDailyClimate("P93A_OVERRIDE_DAILY_NATIVE_T_MEAN_MIN_MAX_NOT_CONSERVED")
    p=[float(v["surface_pressure"])*100 for v in donor.vectors]
    if not all(30000<pi<115000 for pi in p):
        raise InfeasibleDailyClimate("P92B_DONOR_SURFACE_PRESSURE")
    # Native specific humidity hard constraint; disaggregate from genuine
    # donor dewpoint/moisture shape, saturation-restricted at morphed T.
    original_q=[q_of_e(sat_pa(v["dew_point_2m"]),pi)
                for v,pi in zip(donor.vectors,p)]
    caps=[qsat(ti,pi)*.999999999 for ti,pi in zip(t,p)]
    # Distinguish the thermodynamic saturation-capacity gate from solar
    # energy/donor-hour geometry. This is a diagnostic/source-safety repair:
    # no physical constants, donor selection or generated values change.
    if 24*src["huss"]>sum(caps)+1e-8:
        raise InfeasibleDailyClimate("P92B_HUSS_EXCEEDS_SELECTED_DONOR_T_P_SATURATION_CAPACITY")
    q=distribute_exact(original_q,caps,24*src["huss"])
    rh=[100*e_of_q(qi,pi)/sat_pa(ti) for qi,pi,ti in zip(q,p,t)]
    td=[dewpoint_of_q(qi,pi,ti) for qi,pi,ti in zip(q,p,t)]
    if not all(0<=v<=100+1e-6 for v in rh):
        raise InfeasibleDailyClimate("P92B_PHYSICAL_HUMIDITY_CLOSURE_BAD")
    # Original all-hour total > 0 is obligatory for a wet daily native GCM
    # total. No generated rain in an originally clear/dry weather vector.
    rain_total=sum(v["precipitation"] for v in donor.vectors)
    if src["pr_mm_day"]>0 and rain_total<=0:
        raise InfeasibleDailyClimate("P92B_WET_NATIVE_TARGET_NO_WET_DONOR")
    rains=([src["pr_mm_day"]*v["precipitation"]/rain_total for v in donor.vectors]
           if src["pr_mm_day"]>0 else [0.]*24)
    speed=[float(v["wind_speed_10m"]) for v in donor.vectors]
    mean_wind=statistics.fmean(speed)
    if mean_wind<=0 and src["sfcWind"]>0:
        raise InfeasibleDailyClimate("P92B_ZERO_WIND_DONOR_CANNOT_SCALE")
    winds=[(x*src["sfcWind"]/mean_wind if mean_wind>0 else 0.) for x in speed]
    if any(w>90 for w in winds):
        raise InfeasibleDailyClimate("P92B_SCALED_WIND_NONPHYSICAL")
    solarcos=geometry(target_day["date"],latitude,longitude)
    caps_solar=[1450.*z for z in solarcos]
    raw_ghi=[max(0.,v["shortwave_radiation"]) if z>0 else 0.
             for v,z in zip(donor.vectors,solarcos)]
    # A current donor may have zero radiation weights during some daylight
    # hours. This is donor-profile support, NOT proof that source GCM GHI
    # violates the extraterrestrial TOA bound for another feasible donor.
    supported_capacity=sum(c for c,w in zip(caps_solar,raw_ghi) if w>0)
    if src["rsds_kwh_m2_day"]*1000>supported_capacity+1e-8:
        raise InfeasibleDailyClimate("P92B_GHI_EXCEEDS_SELECTED_DONOR_HOUR_SUPPORT_CAPACITY")
    ghi=distribute_exact(raw_ghi,caps_solar,src["rsds_kwh_m2_day"]*1000)
    direct=[];diffuse=[];dni=[]
    for a,v,z in zip(ghi,donor.vectors,solarcos):
        if a<=0 or z<=0:direct.append(0.);diffuse.append(0.);dni.append(0.);continue
        original_ghi=v["shortwave_radiation"]
        frac=(v["diffuse_radiation"]/original_ghi) if original_ghi>1.e-7 else 1.
        frac=min(1.,max(0.,frac))
        beam=min(a*(1-frac),1400.*z)
        direct.append(beam);diffuse.append(a-beam);dni.append(beam/z)
    # LW from physically bounded effective-sky-emissivity proxy with
    # authentic GCM daily downwelling LW constraint (not measured hourly LW).
    eps0=[min(1.1,max(.4,.60+.0025*rh_i+.0015*v["cloud_cover"]))
          for rh_i,v in zip(rh,donor.vectors)]
    emitted=[SIGMA*(x+273.15)**4 for x in t]
    target_lw_total=src["rlds_kwh_m2_day"]*1000
    eps_scale=target_lw_total/sum(e*sky for e,sky in zip(eps0,emitted))
    emissivities=[e*eps_scale for e in eps0]
    if any(e<.30 or e>1.4 for e in emissivities):
        raise InfeasibleDailyClimate("P92B_GCM_LONGWAVE_INCOMPATIBLE_WITH_BOUNDED_SKY_PROXY")
    lw=[e*rad for e,rad in zip(emissivities,emitted)]
    outputs=[]
    for k in range(24):
        w=dict(donor.vectors[k])
        w.update({"temperature_2m":t[k],"dew_point_2m":td[k],
                  "relative_humidity_2m":min(100.,rh[k]),
                  "precipitation":rains[k],"shortwave_radiation":ghi[k],
                  "direct_radiation":direct[k],"diffuse_radiation":diffuse[k],
                  "direct_normal_irradiance":dni[k],"wind_speed_10m":winds[k]})
        check_vector(w)
        if abs(w["shortwave_radiation"]-w["diffuse_radiation"]-w["direct_radiation"])>1e-7:
            raise InfeasibleDailyClimate("P92B_SHORTWAVE_PARTITION_BROKEN")
        outputs.append(w)
    checks={"tas_c":statistics.fmean(t),"tasmin_c":min(t),"tasmax_c":max(t),
            "pr_mm_day":sum(rains),"rsds_kwh_m2_day":sum(ghi)/1000,
            "rlds_kwh_m2_day":sum(lw)/1000,
            "sfcWind":statistics.fmean(winds),"huss":statistics.fmean(q),
            "hurs":statistics.fmean(rh)}
    residual={f:checks[f]-src[f] for f in checks}
    for f in DAY_FIELDS:
        if f=="hurs":continue  # incompatible GCM native huss, RH under constrained T
        if abs(residual[f])>DAILY_TOLERANCE:
            raise InfeasibleDailyClimate("P92B_ORIGINAL_DAILY_CONSERVATION_FAILED_"+f)
    features={
        "donor_original_date":donor.date.isoformat(),
        "donor_original_http_sha256":donor.original_sha256,
        "target_date":target_day["date"].isoformat(),
        "n_original_donor_hours":24,
        "rainy_hours":sum(x["precipitation"]>0 for x in outputs),
        "cloudy_hours":sum(x["cloud_cover"]>=70 for x in outputs),
        "native_daily_hurs_soft_closure_pp":residual["hurs"],
        "native_daily_q_hard_constraint_closed":True,
        "native_daily_longwave_proxy_only":True,
        "original_hourly_cloud_fraction_unmodified":True,
        "solar_energy_exact_radiation_partition_derived":True,
        "temperature_donor_hour_order_preserved":True,
        "source_ERA5_hourly_pressure_and_wind_direction_not_future_projected":True,
        "daily_native_source_residuals":residual}
    return Day(target_day["date"],tuple(outputs),donor.original_sha256),lw,features

def generate(targets,donors,latitude,longitude,seed=7313):
    if not targets or not donors:
        raise ValueError("P92B_NO_AUTHENTIC_ORIGINAL_SOURCE")
    if any(d.date.year in {t["date"].year for t in targets} for d in donors):
        raise ValueError("P92B_DONOR_AND_NATIVE_GCM_TARGET_YEAR_OVERLAP")
    successful=[];blocked=[];prev=None
    for target in targets:
        try:
            src=native_target(target)
            donor=select_donor(donors,{"date":target["date"],**src},prev,seed)
            result,lw,meta=new_day(target,donor,latitude,longitude)
            successful.append((result,lw,meta))
            prev=result.vectors[-1]
        except (InfeasibleDailyClimate,ValueError) as exc:
            blocked.append({"target_date":target.get("date").isoformat(),
                            "reason":f"{type(exc).__name__}: {exc}"})
            # Continuity not validated across any blocked day
            prev=None
    return successful,blocked

def summarize(successes,blocked,total):
    if len(successes)+len(blocked)!=total:
        raise ValueError("P92B_ORIGINAL_DAILY_CASE_COUNT_MISMATCH")
    names=("tas_c","tasmin_c","tasmax_c","pr_mm_day","rsds_kwh_m2_day",
           "rlds_kwh_m2_day","sfcWind","huss")
    maxres={k:max((abs(meta["daily_native_source_residuals"][k])
                   for _,_,meta in successes),default=None) for k in names}
    return {"n_original_daily_targets":total,"n_conserved":len(successes),
            "n_physically_blocked":len(blocked),
            "blocking_reasons":blocked,
            "max_abs_daily_hard_residual_by_variable":maxres,
            "hurs_soft_mean_abs_mismatch_pp":(
                 statistics.fmean(abs(x[2]["native_daily_hurs_soft_closure_pp"])
                                  for x in successes) if successes else None),
            "hurs_soft_max_abs_mismatch_pp":(
                 max(abs(x[2]["native_daily_hurs_soft_closure_pp"])
                     for x in successes) if successes else None),
            "n_days_hurs_mismatch_gt_10pp":sum(
                abs(x[2]["native_daily_hurs_soft_closure_pp"])>10 for x in successes),
            "native_daily_source_huss_hurs_not_automatically_equivalent":True,
            "not_future_station_validation":True,
            "not_EPW_production_qualified":True}
