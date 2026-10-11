#!/usr/bin/env python3
"""P7B: independent deterministic seeded 365-day -> 8760-hour CMIP6 synthesis.

Input: frozen original NASA NEX-GDDP-CMIP6 CanESM5 historical joint DAILY
1995–2014 source. Pilot: 2013 nonleap synthetic model calendar, not actual
2013 observed weather. Explicitly conserve native daily temperature
mean/min/max, hurs, surface wind, precipitation depth, GHI and downwelling LW.
Derived hourly DHI and DNI use transparent Erbs clearness partition and NOAA
solar position; no independent measured DNI. Pressure hydrostatic site proxy;
wind direction unavailable (EPW missing sentinel). Research only.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,random
from collections import Counter
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
from statistics import fmean
from p6_3e_hourly_solar_components_arad import solar_cos_zenith
from p6_2d_solar_methods_benchmark import checksum
from p6_3c_precip_semantics_daily_alignment import save_union

STATION_LAT=46.875
STATION_LON=15.375
GRID_ELEVATION_PROXY_M=366.
YEAR=2013
TZ_CET=timezone(timedelta(hours=1))
P_SEALEVEL=101325.
P_PROXY=P_SEALEVEL*(1-2.25577e-5*GRID_ELEVATION_PROXY_M)**5.25588
SOLAR_CONSTANT_WM2=1361.
NONLEAP_HOURS=8760
QC_SCIENCE_STATUS="SYNTHETIC_HOURLY_DAILY_CONSERVATION_ONLY_NOT_OBSERVED_CLIMATE"
NEEDED=("year","month","day","date","scenario","model","tas_c","tasmin_c",
        "tasmax_c","hurs","huss","pr_mm_day","rsds_kwh_m2_day",
        "rlds_kwh_m2_day","sfcWind")

def load_source(folder,year):
    src=folder/"joint_daily_raw.csv"
    prov=folder/"source_provenance.json"
    qa=folder/"quality_report.json"
    if not all(x.is_file() for x in (src,prov,qa)):
        raise FileNotFoundError("Frozen original CanESM5 source archive incomplete")
    m=json.loads(prov.read_text(encoding="utf8"))
    q=json.loads(qa.read_text(encoding="utf8"))
    digest=checksum(src)
    if not (m["csv_sha256"]["joint_daily_raw.csv"]==digest
         and q["csv_sha256"]["joint_daily_raw.csv"]==digest
         and m["model"]=="CanESM5"
         and m["window"]=="historical-1995-2014"
         and q["calendar"]=="noleap"
         and q["days"]==7300 and m["source_count"]==180):
        raise ValueError("NEX original daily source SHA/calendar/model/provenance mismatch")
    with src.open("r",encoding="utf8",newline="") as f:
        reader=csv.DictReader(f)
        if not set(NEEDED)<=set(reader.fieldnames or []):
            raise ValueError("CMIP6 daily required variables missing")
        data=[r for r in reader if int(r["year"])==year]
    if len(data)!=365 or not all(r["date"]==(date(year,1,1)+timedelta(days=i)).isoformat()
                                for i,r in enumerate(data)):
        raise ValueError("P7B 2013 daily source requires 365 consecutive noleap days")
    for r in data:
        for k in NEEDED[6:]:
            v=float(r[k])
            if not math.isfinite(v):raise ValueError("Source nonfinite field "+k)
        if not float(r["tasmin_c"])<=float(r["tas_c"])<=float(r["tasmax_c"]):
            raise ValueError("Daily temperature source physically inconsistent")
        if not 0<float(r["hurs"])<=100:
            raise ValueError("Daily source RH out of physical range")
        if any(float(r[k])<0 for k in
               ("pr_mm_day","rsds_kwh_m2_day","rlds_kwh_m2_day","sfcWind")):
            raise ValueError("Daily source negative accumulation")
        if r["model"]!="CanESM5" or r["scenario"]!="historical":
            raise ValueError("Daily model/scenario identity drift")
    return data,{"model":"CanESM5","source_window":"historical-1995-2014",
         "calendar":"noleap","year":year,"daily_csv_sha256":digest,
         "source_metadata_sha256":checksum(prov),
         "quality_report_sha256":checksum(qa),
         "original_model_grid":q["grid"]}

def point_weather(hour,lat=STATION_LAT,lon=STATION_LON):
    """One-hour midpoint solar position for a fixed-local-CET EPW hour."""
    utc=hour.astimezone(timezone.utc)
    cz=max(0.,solar_cos_zenith(utc,lat,lon))
    doy=utc.timetuple().tm_yday
    eccentricity=1+0.033*math.cos(2*math.pi*(doy-3)/365.)
    toa=SOLAR_CONSTANT_WM2*eccentricity*cz
    return cz,toa

def diffuse_fraction_erbs(kt):
    """Published Erbs-style hourly GHI diffuse-ratio approximation; not measured."""
    if kt<=.22:return max(0.,min(1.,1-.09*kt))
    if kt<=.80:
        return max(0.,min(1.,.9511-.1604*kt+4.388*kt**2
            -16.638*kt**3+12.336*kt**4))
    return .165

def temperature_curve(tavg,tmin,tmax):
    if not (tmin<=tavg<=tmax):raise ValueError("Temperature daily range inconsistent")
    # Smooth 24h cosine with minimum 03:00 and maximum 15:00 LST;
    # source CanESM5 provides tas mean at (tasmax+tasmin)/2 within ~1e-4 K.
    if abs(tavg-(tmax+tmin)/2)>1e-3:
        raise ValueError("Pilot symmetric temperature profile cannot preserve source daily mean and extrema")
    amplitude=(tmax-tmin)/2
    vals=[tavg+amplitude*math.cos(2*math.pi*(h-15)/24) for h in range(24)]
    if max(abs(fmean(vals)-tavg),abs(max(vals)-tmax),abs(min(vals)-tmin))>1e-8:
        raise ValueError("Temperature generator did not exactly preserve daily source")
    return vals

def wind_curve(mean,seed,day):
    rng=random.Random(f"{seed}|wind|{day.isoformat()}")
    inertia=0.
    raw=[]
    for h in range(24):
        inertia=.85*inertia+math.sqrt(1-.85**2)*rng.gauss(0,1)
        raw.append(max(.1,1+.16*math.cos(2*math.pi*(h-14)/24)+.13*inertia))
    normal=fmean(raw)
    vals=[mean*v/normal for v in raw]
    if abs(fmean(vals)-mean)>1e-9 or any(v<0 for v in vals):
        raise ValueError("Daily mean wind generator does not conserve")
    return vals

def rain_curve(total,seed,day):
    if total<0:raise ValueError("Negative CMIP6 rain")
    if total==0:return [0.]*24
    # A seeded multi-hour wet event preserves original daily total exactly.
    rng=random.Random(f"{seed}|rain|{day.isoformat()}")
    number=min(12,max(2,int(round(2+total/3))))
    selected=rng.sample(range(24),number)
    weights=[rng.gammavariate(1.5,1) for _ in selected]
    output=[0.]*24
    for h,w in zip(selected,weights):output[h]=total*w/sum(weights)
    output[selected[-1]]+=total-sum(output)
    if min(output)<-1e-9 or abs(sum(output)-total)>1e-8:
        raise ValueError("Rain daily conservation mismatch")
    return output

def solar_curve(day_energy,local_date):
    """Daily source shortwave -> astronomical hour shape and estimated partition.

    Source day/solar-time relation is a hypothesis, not a measured timing.
    Preserve full model daily horizontal irradiation; no clipping.
    """
    hours=[datetime(local_date.year,local_date.month,local_date.day,h,
                   tzinfo=TZ_CET) for h in range(24)]
    geometry=[point_weather(h) for h in hours]
    weights=[cosz**1.15 for cosz,_ in geometry]
    if sum(weights)<=0 and day_energy>0:
        raise ValueError("Positive daylight shortwave under all-night solar geometry")
    ghi=[day_energy*1000*w/sum(weights) if sum(weights)>0 else 0.
         for w in weights]
    dhi=[];dni=[];review=[]
    for gh,(cz,toa) in zip(ghi,geometry):
        if gh==0 or cz<=0:
            dhi.append(0.);dni.append(0.);review.append(False)
            continue
        kt=gh/toa if toa>1e-5 else 99.
        fd=diffuse_fraction_erbs(kt)
        beam=(gh*(1-fd)/cz)
        # Enforce a transparent normal-irradiance bound by allocating
        # excess power into the diffuse component without touching GHI.
        direct=min(max(0,beam),1350.)
        diffuse=gh-direct*cz
        if diffuse<0 and abs(diffuse)<1e-8:diffuse=0.
        if diffuse<0 or diffuse>gh+1e-7:
            raise ValueError("Derived shortwave partition fails GHI=DHI+DNI*cosz")
        dhi.append(diffuse);dni.append(direct)
        review.append(kt>1.02 or beam>1350.)
    if abs(sum(ghi)/1000-day_energy)>1e-8:
        raise ValueError("Daily source GHI not conserved")
    return list(zip(ghi,dni,dhi,review,geometry))

def dewpoint(t,rh):
    if not (-70<t<70 and 0<rh<=100):
        raise ValueError("Unphysical hourly T/RH input")
    a=17.625;b=243.04
    gamma=math.log(rh/100)+a*t/(b+t)
    return b*gamma/(a-gamma)

def q_from_t_rh(t,rh,p):
    es=611.2*math.exp(17.67*t/(t+243.5))
    e=rh*es/100
    return .622*e/(p-.378*e)

def synthesize_day(r,seed):
    d=date.fromisoformat(r["date"])
    temp=temperature_curve(*(float(r[k]) for k in
        ("tas_c","tasmin_c","tasmax_c")))
    rh=float(r["hurs"])
    spd=wind_curve(float(r["sfcWind"]),seed,d)
    rain=rain_curve(float(r["pr_mm_day"]),seed,d)
    solar=solar_curve(float(r["rsds_kwh_m2_day"]),d)
    lw=float(r["rlds_kwh_m2_day"])*1000/24
    generated=[]
    for h in range(24):
        gh,dn,dh,review,(cz,toa)=solar[h]
        td=dewpoint(temp[h],rh)
        local=datetime(d.year,d.month,d.day,h,tzinfo=TZ_CET)
        generated.append({
          "local_hour":local,"date":d.isoformat(),
          "hour":h,"T_C":temp[h],"RH_pct":rh,"dewpoint_C":td,
          "wind_ms":spd[h],"rain_mm":rain[h],
          "ghi_Wh":gh,"dni_Wh":dn,"dhi_Wh":dh,
          "sky_lw_Wh":lw,"pressure_pa":P_PROXY,
          "solar_coszen":cz,"toa_horizontal_Wh":toa,
          "solar_partition_review":review,
          "hourly_wind_direction_source":"UNAVAILABLE",
          "hourly_pressure_source":"STANDARD_ATMOSPHERE_ELEVATION_PROXY",
          "hourly_solar_partition_source":"ERBS_ESTIMATED_NOT_OBSERVED_DHI_DNI",
          "hourly_precipitation_source":"STOCHASTIC_DAILY_CONSERVING",
          "observational_validation_status":"SYNTHETIC_GCM_NOT_DATE_MATCHED_TO_GROUND"})
    check={
      "tas_c":fmean(x["T_C"] for x in generated),
      "tasmin_c":min(x["T_C"] for x in generated),
      "tasmax_c":max(x["T_C"] for x in generated),
      "hurs":fmean(x["RH_pct"] for x in generated),
      "sfcWind":fmean(x["wind_ms"] for x in generated),
      "pr_mm_day":sum(x["rain_mm"] for x in generated),
      "rsds_kwh_m2_day":sum(x["ghi_Wh"] for x in generated)/1000,
      "rlds_kwh_m2_day":sum(x["sky_lw_Wh"] for x in generated)/1000}
    diffs={name:check[name]-float(r[name]) for name in check}
    if max(abs(x) for x in diffs.values())>1e-7:
        raise ValueError("Hourly generation failed native daily conservation")
    qhour=fmean(q_from_t_rh(x["T_C"],rh,P_PROXY) for x in generated)
    return generated,{"date":d.isoformat(),
           "model":r["model"],"scenario":r["scenario"],
           "source_original_specific_humidity_huss":float(r["huss"]),
           "derived_mean_hourly_specific_humidity":qhour,
           "derived_minus_source_huss":qhour-float(r["huss"]),
           "huss_independent_constraint_closed":False,
           "solar_partition_review_hours":sum(x["solar_partition_review"] for x in generated),
           **{"residual_"+k:v for k,v in diffs.items()}}

def epw_rows(hours):
    data=[]
    for x in hours:
        t=x["local_hour"]
        row=[t.year,t.month,t.day,t.hour+1,60,"?9"*22,
             round(x["T_C"],3),round(x["dewpoint_C"],3),
             round(x["RH_pct"],3),round(x["pressure_pa"],1),
             9999,9999,round(x["sky_lw_Wh"],3),
             round(x["ghi_Wh"],3),round(x["dni_Wh"],3),round(x["dhi_Wh"],3),
             999999,999999,999999,9999,
             999,round(x["wind_ms"],3),
             99,99,9999,99999,9,"999999999",999,.999,999,99,999,
             round(x["rain_mm"],3),1 if x["rain_mm"]>0 else 0]
        if len(row)!=35:raise ValueError("EPW field count")
        data.append(row)
    return data

def write_epw(path,records):
    if len(records)!=NONLEAP_HOURS:raise ValueError("P7B 2013 requires 8760 hours")
    header=[
        ["LOCATION","Graz-CMIP6-grid","Styria","AUT","IGE_P7B_RESEARCH",
         "999999",STATION_LAT,STATION_LON,1,GRID_ELEVATION_PROXY_M],
        ["DESIGN CONDITIONS",0],["TYPICAL/EXTREME PERIODS",0],
        ["GROUND TEMPERATURES",0],
        ["HOLIDAYS/DAYLIGHT SAVINGS","No",0,0,0],
        ["COMMENTS 1","SYNTHETIC CanESM5 2013 daily-to-hourly; not observed; NOT future climate or TMY"],
        ["COMMENTS 2","Daily conserved; wind direction missing; pressure altitude proxy; Erbs inferred DNI/DHI; RESEARCH ONLY"],
        ["DATA PERIODS",1,1,"P7B CanESM5 synthetic calendar","Tuesday","1/1","12/31"]]
    with path.open("w",encoding="utf8",newline="") as f:
        w=csv.writer(f,lineterminator="\n");w.writerows(header);w.writerows(epw_rows(records))
    with path.open("r",encoding="utf8",newline="") as f:
        parsed=list(csv.reader(f))
    if len(parsed)!=NONLEAP_HOURS+8 or any(len(r)!=35 for r in parsed[8:]):
        raise ValueError("EPW readback invalid")
    for i,r in enumerate(parsed[8:]):
        exp=datetime(2013,1,1,tzinfo=TZ_CET)+timedelta(hours=i)
        if list(map(int,r[:5]))!=[2013,exp.month,exp.day,exp.hour+1,60]:
            raise ValueError("Invalid continuous EPW local standard time calendar")
    return checksum(path)

def reference_epw_stats(path):
    if not path.is_file():return None
    with path.open("r",encoding="utf8",newline="") as f:rows=list(csv.reader(f))
    if len(rows)!=8768 or not all(len(r)==35 for r in rows[8:]):
        raise ValueError("P7A original benchmark EPW is not valid")
    # Model year and calendar year do NOT have matched weather events:
    # compare distributional monthly statistics and mean hourly climate only.
    accum={}
    for month in range(1,13):
        rr=[r for r in rows[8:] if int(r[1])==month]
        accum[month]={"T_C_mean":fmean(float(r[6]) for r in rr),
                      "RH_pct_mean":fmean(float(r[8]) for r in rr),
                      "GHI_kwh_m2_month":sum(float(r[13]) for r in rr)/1000,
                      "wind_ms_mean":fmean(float(r[21]) for r in rr)}
    return accum

def run(source_dir,out,year=YEAR,seed=7313,reference=None):
    if year!=YEAR:raise ValueError("P7B initial pilot explicitly 2013 only")
    out.mkdir(parents=True,exist_ok=True)
    days,source=load_source(source_dir,year)
    allhours=[];closure=[]
    for d in days:
        h,check=synthesize_day(d,seed)
        allhours.extend(h);closure.append(check)
    if len(allhours)!=NONLEAP_HOURS:raise ValueError("Generated hour count not 8760")
    epw=out/"Graz_2013_CanESM5_P7B_SYNTHETIC_DAILY_TO_HOURLY_RESEARCH.epw"
    sha_epw=write_epw(epw,allhours)
    hourly=[]
    for r in allhours:
        d=dict(r)
        d["local_hour"]=r["local_hour"].isoformat()
        hourly.append(d)
    original_hourly_sha=save_union(out/"p7b_hourly_synthetic_weather.csv",hourly)
    original_closure_sha=save_union(out/"p7b_daily_native_conservation.csv",closure)
    rows=[];comparison=reference_epw_stats(reference) if reference else None
    for m in range(1,13):
        h=[r for r in allhours if r["local_hour"].month==m]
        sim={"T_C_mean":fmean(x["T_C"] for x in h),
             "RH_pct_mean":fmean(x["RH_pct"] for x in h),
             "GHI_kwh_m2_month":sum(x["ghi_Wh"] for x in h)/1000,
             "wind_ms_mean":fmean(x["wind_ms"] for x in h)}
        for var,v in sim.items():
            reference_value=comparison[m][var] if comparison is not None else None
            rows.append({"month":m,"variable":var,"synthetic_value":v,
                 "real_hourly_2013_baseline_value":reference_value,
                 "model_minus_baseline":v-reference_value if reference_value is not None else None,
                 "comparison_type":"UNPAIRED_MONTHLY_DISTRIBUTIONS_NOT_SYNCHRONOUS_DAILY_WEATHER"})
    compare_sha=save_union(out/"p7b_monthly_unpaired_reference_comparison.csv",rows)
    solar_review=sum(x["solar_partition_review"] for x in allhours)
    huss_mismatch=max(abs(x["derived_minus_source_huss"]) for x in closure)
    results={
       "stage":"IGE_P7B_DAILY_TO_HOURLY_CMIP6_CANESM5_HISTORICAL_PILOT",
       "technical_status":"DAILY_CONSERVATION_AND_8760_EPW_FORMAT_PASS",
       "scientific_status":QC_SCIENCE_STATUS,
       "epw_production_ready":False,
       "input":source,"output_year":YEAR,"seed":seed,
       "source_calendar":"CanESM5 noleap model calendar",
       "hourly_synthesized":len(allhours),
       "native_daily_rows":len(days),
       "max_abs_native_daily_residual":max(abs(v) for r in closure for k,v in r.items()
                                              if k.startswith("residual_")),
       "maximum_unclosed_huss_kg_kg":huss_mismatch,
       "huss_constraint_closed":False,
       "solar_physical_partition_review_hours":solar_review,
       "solar_component_method":"NOAA approximate solar geometry + Erbs hourly diffuse fraction, derived DNI not independently observed",
       "temperature_method":"24-hour cosine extrema at 03 and 15 CET; CanESM5 native Tmean is min/max midpoint",
       "wind_method":"daily-mean-conserving seeded persistent Gaussian pattern, no measured wind direction",
       "pressure_method":"hydrostatic STANDARD ATMOSPHERE proxy at 366m, not CMIP6 daily pressure",
       "reference_analysis":"UNPAIRED month-level distributions, not model/observed date-paired weather",
       "hashes":{
          epw.name:sha_epw,
          "p7b_hourly_synthetic_weather.csv":original_hourly_sha,
          "p7b_daily_native_conservation.csv":original_closure_sha,
          "p7b_monthly_unpaired_reference_comparison.csv":compare_sha},
       "limits":[
          "First implementation is deterministic daily-conserving disaggregation, not calibrated multivariate hourly weather.",
          "Historical CMIP6 2013 model daily weather must not be paired day-by-day with actual Graz observed 2013 dates.",
          "Only 2013 original CanESM5 noleap pilot; not future SSP and not eight-GCM ensemble or Meteonorm equivalent.",
          "Mean daily hurs conserved using flat intra-day RH; original daily specific humidity huss not simultaneously conserved and quantified explicitly.",
          "Wind direction missing EPW 999; pressure is hydrostatic altitude proxy and may limit EnergyPlus runnable-ness.",
          "Rain intra-day location seeded, arbitrary event shape, no calibrated hourly frequency/duration.",
          "Erbs DHI/DNI are model estimates; solar hour-angle simplification, DNI 1350 cap, review outlier counters.",
          "Original NEX source rsds is already NASA BCSD corrected; P6 M1/M2/M3 station adjustment not silently applied.",
          "Neither source-format validity nor daily conservation guarantees local hourly physical skill or future building-energy accuracy."]}
    (out/"p7b_science_audit.json").write_text(
       json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("P7B DAILY SYNTHESIS",results["technical_status"],
          "hours",len(allhours),"max residual",results["max_abs_native_daily_residual"],
          "huss mismatch",huss_mismatch,"solar review",solar_review,flush=True)
    return results

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--daily-frozen",type=Path,required=True)
    a.add_argument("--out",type=Path,required=True)
    a.add_argument("--reference-epw",type=Path)
    a.add_argument("--seed",type=int,default=7313)
    p=a.parse_args()
    run(p.daily_frozen,p.out,seed=p.seed,reference=p.reference_epw)
