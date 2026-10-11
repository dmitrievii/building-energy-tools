#!/usr/bin/env python3
"""IGE P7B.1: bounded moisture feasibility and unpaired multi-year GHI validation.

No historical GCM day is the observed weather event on the same calendar
date. Preserve original P7B EPW and frozen sources byte for byte. Produce
transparent psychrometric *diagnostics*, not unapproved repaired EPW.
"""
from __future__ import annotations
import argparse,csv,json,math
from collections import defaultdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from statistics import fmean,median
from p6_2d_solar_methods_benchmark import checksum
from p6_3c_precip_semantics_daily_alignment import save_union
from p7b_daily_to_hourly_cmip6_pilot import q_from_t_rh,dewpoint,P_PROXY

MODEL_YEARS=range(2005,2015)
TARGET_YEAR=2013
LATENCY_NOTE="UNPAIRED_SAME_SEASON_DISTRIBUTIONS_NOT_SAME_DAY_WEATHER"
RH_SHAPE_CAP_PP=25.0
QA_TOL=1e-9
NASA_SITE="graz_station30"
NASA_SOURCE="p6_3e_native_hourly_ghi_dni_dhi_toa_physical_diagnostics.csv"

def read_csv(path):
    with path.open("r",newline="",encoding="utf8") as inp:
        return list(csv.DictReader(inp))

def original_model_daily(root):
    src=root/"joint_daily_raw.csv"
    meta=root/"source_provenance.json"
    qa=root/"quality_report.json"
    if not all(p.is_file() for p in (src,meta,qa)):
        raise FileNotFoundError("Frozen original NEX-GDDP-CMIP6 daily archive incomplete")
    prov=json.loads(meta.read_text(encoding="utf8"))
    check=json.loads(qa.read_text(encoding="utf8"))
    digest=checksum(src)
    if (prov["csv_sha256"]["joint_daily_raw.csv"]!=digest or
        check["csv_sha256"]["joint_daily_raw.csv"]!=digest or
        prov["model"]!="CanESM5" or
        prov["window"]!="historical-1995-2014" or
        check["calendar"]!="noleap" or
        check["days"]!=7300):
        raise ValueError("Original daily model SHA/model/calendar contract failed")
    rows=read_csv(src)
    selected=[r for r in rows if int(r["year"]) in MODEL_YEARS]
    annual_counts={y:sum(int(r["year"])==y for r in selected)
                   for y in MODEL_YEARS}
    if any(n!=365 for n in annual_counts.values()):
        raise ValueError("Expected 365 original noleap GCM daily data/year")
    return selected,digest

def original_p7b_hourly(root):
    report=root/"p7b_science_audit.json"
    src=root/"p7b_hourly_synthetic_weather.csv"
    if not report.is_file() or not src.is_file():
        raise FileNotFoundError("Frozen original P7B 2013 synthetic source missing")
    original=json.loads(report.read_text(encoding="utf8"))
    if (original["epw_production_ready"] is not False or
        original["technical_status"]!="DAILY_CONSERVATION_AND_8760_EPW_FORMAT_PASS" or
        checksum(src)!=original["hashes"][src.name] or
        original["hourly_synthesized"]!=8760):
        raise ValueError("P7B accepted source original provenance/sha mismatch")
    rows=read_csv(src)
    if len(rows)!=8760:raise ValueError("Missing accepted P7B original hourly samples")
    groups=defaultdict(list)
    for r in rows:
        if int(r["hour"]) not in range(24):
            raise ValueError("P7B original hourly local-hour field corrupted")
        groups[r["date"]].append(r)
    for day in groups:
        r=sorted(groups[day],key=lambda a:int(a["hour"]))
        if len(r)!=24 or [int(x["hour"]) for x in r]!=list(range(24)):
            raise ValueError("Original synthetic daily hour support missing/duplicate")
        groups[day]=r
    if len(groups)!=365:raise ValueError("Original P7B day count not 365")
    return groups,checksum(src),original

def original_nasa_p6e(root):
    report=root/"p6_3e_hourly_solar_components_arad_science_audit.json"
    data=root/NASA_SOURCE
    if not report.is_file() or not data.is_file():
        raise FileNotFoundError("Frozen P6.3E original NASA hourly data not supplied")
    qa=json.loads(report.read_text(encoding="utf8"))
    if (checksum(data)!=qa["output_file_sha256"][data.name] or
        qa["production_epw_ready"] is not False):
        raise ValueError("NASA POWER frozen original GHI source SHA/status mismatch")
    by_year=defaultdict(list)
    count=0
    with data.open("r",newline="",encoding="utf8") as inp:
        for r in csv.DictReader(inp):
            if r["site"]!=NASA_SITE:continue
            t=datetime.fromisoformat(r["timestamp_utc_start"].replace("Z","+00:00"))
            if t.tzinfo is None or t.utcoffset()!=timedelta(0):
                raise ValueError("NASA hourly source not original UTC")
            if t.year not in MODEL_YEARS:continue
            if r["valid"]!="True" or r["is_satellite_not_observed_ground"]!="True":
                raise ValueError("NASA POWER source falsely labelled station measurement")
            ghi=float(r["GHI_kwh_m2_hour"])
            if not math.isfinite(ghi) or ghi<0:
                raise ValueError("NASA original hourly GHI invalid")
            by_year[t.year].append((t.month,ghi))
            count+=1
    for y in MODEL_YEARS:
        expected=(366 if y in (2008,2012) else 365)*24
        if len(by_year[y])!=expected:
            raise ValueError(f"NASA original hourly {y} incomplete")
    return by_year,checksum(data),count

def original_geosphere_daily(root):
    """Independent actual station daily observed GHI, q21-approved.

    Do NOT confuse with NASA POWER gridded satellite/reanalysis original.
    Preserve official GeoSphere 23 UTC previous-to-23 UTC labelled day.
    """
    filename="p6_3d_power_vs_geosphere_daily_2005_2014_two_utc_windows.csv"
    source=root/filename
    report=root/"p6_3d_hourly_independent_validation_science_audit.json"
    if not source.is_file() or not report.is_file():
        raise FileNotFoundError("Frozen original P6.3D station daily GHI reference absent")
    qa=json.loads(report.read_text(encoding="utf8"))
    if checksum(source)!=qa["output_sha256"][filename] or \
       qa["production_epw_ready"] is not False:
        raise ValueError("Official original GeoSphere daily station source SHA/status mismatch")
    by_year=defaultdict(list)
    unique=set()
    for row in read_csv(source):
        if row["site"]!=NASA_SITE or row["window"]!="geosphere_23_23UTC":
            continue
        if row["valid_day"]!="True":raise ValueError("Official station GHI day not valid")
        day=date.fromisoformat(row["date"])
        if day.year not in MODEL_YEARS:continue
        if day in unique:raise ValueError("Duplicate original GeoSphere solar day")
        unique.add(day)
        val=float(row["official_ghi_kwh_m2_day"])
        if not math.isfinite(val) or val<0:
            raise ValueError("Original station daily solar measured energy not usable")
        by_year[day.year].append((day.month,val))
    for y in MODEL_YEARS:
        expected=366 if y in (2008,2012) else 365
        if len(by_year[y])!=expected:
            raise ValueError(f"Official GeoSphere daily station year {y} incomplete")
    return by_year,checksum(source)

def stationary_observed_solar_climatology(model,station):
    """Unpaired GCM 365-day climatology vs actual GeoSphere station days."""
    gcm=defaultdict(list)
    for row in model:
        y=int(row["year"])
        if y in MODEL_YEARS:
            gcm[y].append((int(row["month"]),float(row["rsds_kwh_m2_day"])))
    annual=[]
    for y in MODEL_YEARS:
        model_energy=sum(v for _,v in gcm[y])
        station_energy=sum(v for _,v in station[y])
        norm_station=station_energy*365/len(station[y])
        annual.append({"year_for_distribution_not_date_paired":y,
                       "native_model_days":len(gcm[y]),
                       "observed_station_days":len(station[y]),
                       "model_annual_kwh_m2":model_energy,
                       "original_geosphere_annual_365day_normalized_kwh_m2":norm_station,
                       "comparison":"UNPAIRED_CALENDAR_YEAR_DISTRIBUTIONS_NO_GCM_OBSERVATION_EVENT_MATCH"})
    months=[]
    for m in range(1,13):
        a=[v for y in MODEL_YEARS for mm,v in gcm[y] if mm==m]
        b=[v for y in MODEL_YEARS for mm,v in station[y] if mm==m]
        if not a or not b:raise ValueError("No station/model source climatological month")
        avgmodel=fmean(a);avgstation=fmean(b)
        months.append({"month":m,"model_native_days":len(a),
                      "geosphere_original_station_days":len(b),
                      "model_mean_daily_ghi_kwh_m2":avgmodel,
                      "geosphere_station_mean_daily_ghi_kwh_m2":avgstation,
                      "model_minus_station_pct":100*(avgmodel/avgstation-1)
                          if avgstation else None,
                      "source":"GEOSPHERE_OBSERVED_STATION_GHI_OFFICIAL_DAILY_QC",
                      "comparison":"UNPAIRED_TEN_YEAR_MONTH_CLIMATOLOGY"})
    ref=fmean(x["original_geosphere_annual_365day_normalized_kwh_m2"] for x in annual)
    mod=fmean(x["model_annual_kwh_m2"] for x in annual)
    return annual,months,{
       "model_10y_mean_annual_kwh_m2":mod,
       "station_observed_10y_mean_365day_normalized_kwh_m2":ref,
       "model_minus_station_pct":100*(mod/ref-1)}

def moisture_daily_candidate(t_series,mean_rh,source_huss,p=P_PROXY,cap_pp=RH_SHAPE_CAP_PP):
    """Pre-registered smooth RH family with exactly conserved mean RH.

    RH(t) = meanRH + b * (Tmean-T(t))/(half T range), |b|<=25pp and RH in [0,100].
    Find b by monotonic bisection when native q is reachable; otherwise choose
    constrained boundary and REPORT remaining source humidity inconsistency.
    Never change native hurs, huss, or temperatures.
    """
    if len(t_series)!=24 or any(not math.isfinite(t) for t in t_series):
        raise ValueError("Full finite 24-hour original P7B temperature series required")
    if not (0<mean_rh<=100) or not (0<source_huss<.1):
        raise ValueError("Invalid original model moisture constraints")
    tbar=fmean(t_series)
    halfspan=(max(t_series)-min(t_series))/2
    weights=[(tbar-t)/halfspan if halfspan>1e-9 else 0. for t in t_series]
    # Exact zero mean for numerical preservation of mean source hurs.
    wm=fmean(weights)
    weights=[x-wm for x in weights]
    maxw=max(abs(x) for x in weights)
    limit=min(cap_pp,mean_rh/maxw,(100-mean_rh)/maxw) if maxw>1e-12 else 0.
    def calc(b):
        rh=[mean_rh+b*w for w in weights]
        if any(v<-.00000001 or v>100.00000001 for v in rh):
            raise ValueError("Moisture RH family outside physically allowed bounds")
        qbar=fmean(q_from_t_rh(t,v,p) for t,v in zip(t_series,rh))
        return qbar,rh
    baseline,_=calc(0.)
    endpoints=[(-limit,*calc(-limit)),(0.,*calc(0.)),(limit,*calc(limit))]
    minq=min(x[1] for x in endpoints)
    maxq=max(x[1] for x in endpoints)
    feasible=minq-QA_TOL<=source_huss<=maxq+QA_TOL
    nearest=min(endpoints,key=lambda x:abs(x[1]-source_huss))
    if feasible:
        left,right=(-limit,limit)
        # q decreases as b increases (more RH at cooler hours).
        vleft=calc(left)[0]
        vright=calc(right)[0]
        if vleft<vright:
            for _ in range(70):
                mid=(left+right)/2
                if calc(mid)[0]<source_huss:left=mid
                else:right=mid
        else:
            for _ in range(70):
                mid=(left+right)/2
                if calc(mid)[0]>source_huss:left=mid
                else:right=mid
        b=(left+right)/2
        qbar,rh=calc(b)
    else:
        b,qbar,rh=nearest
    if abs(fmean(rh)-mean_rh)>1e-9:
        raise ValueError("Candidate hourly RH did not preserve source daily hurs")
    if any(r<0 or r>100 for r in rh):
        raise ValueError("Humidity physical bound failure")
    td=[dewpoint(t,rr) for t,rr in zip(t_series,rh)]
    if any(x>t+1e-7 for x,t in zip(td,t_series)):
        raise ValueError("Moisture saturation closure violated")
    return rh,td,{"status":("JOINT_CLOSED_WITHIN_25PP_RH_FAMILY"
                        if feasible and abs(qbar-source_huss)<QA_TOL else
                        "NOT_CLOSED_WITHIN_25PP_RH_FAMILY"),
         "source_hurs_daily_mean":mean_rh,
         "source_huss_daily_mean_kg_kg":source_huss,
         "original_constant_rh_q_daily_mean_kg_kg":baseline,
         "candidate_derived_q_daily_mean_kg_kg":qbar,
         "candidate_minus_original_huss_kg_kg":qbar-source_huss,
         "relative_humidity_min_pct":min(rh),
         "relative_humidity_max_pct":max(rh),
         "rh_shape_coefficient_pp":b,
         "allowed_huss_range_in_predefined_family_min":minq,
         "allowed_huss_range_in_predefined_family_max":maxq,
         "min_temperature_c":min(t_series),
         "max_temperature_c":max(t_series),
         "mean_temperature_c":tbar}

def evaluate_moisture(model,original_hourly):
    native={r["date"]:r for r in model if r["year"]==str(TARGET_YEAR)}
    if len(native)!=365 or len(original_hourly)!=365:
        raise ValueError("P7B.1 2013 source cross-product day missing")
    days=[];hours=[]
    for day in sorted(native):
        hourly=original_hourly[day]
        t=[float(x["T_C"]) for x in hourly]
        src=native[day]
        rh,td,status=moisture_daily_candidate(t,float(src["hurs"]),float(src["huss"]),
                                               p=float(hourly[0]["pressure_pa"]))
        status["date"]=day
        days.append(status)
        for x,r,hdew in zip(hourly,rh,td):
            hours.append({"date":day,"hour":int(x["hour"]),
              "source_original_T_c":float(x["T_C"]),
              "source_original_hourly_RH_pct":float(x["RH_pct"]),
              "moisture_candidate_RH_pct":r,
              "moisture_candidate_dewpoint_c":hdew,
              "moisture_candidate_source_status":status["status"],
              "original_native_source_huss":float(src["huss"]),
              "no_production_weather_replacement":True})
    return days,hours

def annual_solar_distribution(model,reference):
    """Compare 10-year climatological statistics, NOT daily/year event matching."""
    m=defaultdict(list)
    for x in model:
        if int(x["year"]) not in MODEL_YEARS:continue
        year=int(x["year"])
        v=float(x["rsds_kwh_m2_day"])
        if not math.isfinite(v) or v<0:raise ValueError("NEX-GDDP original source solar invalid")
        m[year].append((int(x["month"]),v))
    annual=[];monthly=[]
    for year in MODEL_YEARS:
        g=m[year]
        n=reference[year]
        if len(g)!=365 or len(n) not in (8760,8784):
            raise ValueError("Required ten-year original solar source absent")
        mg=sum(v for _,v in g)
        ng=sum(v for _,v in n)
        normal_nasa=ng*365/(len(n)/24)
        annual.append({"year_identifier_not_event_matched":year,
                       "original_cmip6_days":365,"nasa_original_hours":len(n),
                       "model_annual_native_kwh_m2":mg,
                       "nasa_annual_365day_normalized_kwh_m2":normal_nasa,
                       "comparison":"UNPAIRED_YEAR_DISTRIBUTION_NOT_DAILY_WEATHER"})
    for month in range(1,13):
        a=[v for year in MODEL_YEARS for mth,v in m[year] if mth==month]
        b=[v for year in MODEL_YEARS for mth,v in reference[year] if mth==month]
        if not a or not b:raise ValueError("Missing monthly model/reference solar")
        model_avg=fmean(a);nasa_avg=fmean(b)
        monthly.append({"month":month,"model_days":len(a),
              "nasa_original_hourly_records":len(b),
              "original_model_daily_ghi_avg_kwh_m2":model_avg,
              "nasa_hourly_source_daily_ghi_mean_kwh_m2":nasa_avg*24,
              "model_minus_nasa_pct":100*(model_avg/(nasa_avg*24)-1)
                      if nasa_avg else None,
              "comparison":"UNPAIRED_CALENDAR_MONTH_CLIMATOLOGICAL_2005_2014"})
    model_clim=fmean(x["model_annual_native_kwh_m2"] for x in annual)
    nasa_clim=fmean(x["nasa_annual_365day_normalized_kwh_m2"] for x in annual)
    return annual,monthly,{"model_10y_mean_annual_kwh_m2":model_clim,
         "nasa_10y_mean_annual_365day_normalized_kwh_m2":nasa_clim,
         "model_minus_nasa_10y_climatological_pct":100*(model_clim/nasa_clim-1)}

def run(model_root,p7b_root,nasa_root,station_root,out):
    out.mkdir(parents=True,exist_ok=True)
    model,modelsha=original_model_daily(model_root)
    hourly,rawsha,original=original_p7b_hourly(p7b_root)
    nasa,nasasha,nasacount=original_nasa_p6e(nasa_root)
    station,stationsha=original_geosphere_daily(station_root)
    moist,moist_hour=evaluate_moisture(model,hourly)
    solar,monthly,clim=annual_solar_distribution(model,nasa)
    station_annual,station_monthly,station_clim=stationary_observed_solar_climatology(model,station)
    closed=sum(x["status"]=="JOINT_CLOSED_WITHIN_25PP_RH_FAMILY" for x in moist)
    rest=max(abs(x["candidate_minus_original_huss_kg_kg"]) for x in moist)
    outputs={
      "p7b1_native_moisture_feasibility_by_day.csv":moist,
      "p7b1_provisional_hourly_rh_candidate_not_epw.csv":moist_hour,
      "p7b1_10yr_unpaired_solar_annual_distribution.csv":solar,
      "p7b1_10yr_unpaired_solar_monthly_climatology.csv":monthly,
      "p7b1_10yr_ground_observed_geosphere_annual_distribution.csv":station_annual,
      "p7b1_10yr_ground_observed_geosphere_monthly_climatology.csv":station_monthly}
    files={name:save_union(out/name,rows) for name,rows in outputs.items()}
    audit={"stage":"IGE_P7B1_MOISTURE_FEASIBILITY_AND_MULTYEAR_SOLAR_VALIDATION",
       "technical_status":"P7B1_ORIGINAL_SOURCE_DIAGNOSTICS_COMPLETE",
       "scientific_status":"RESEARCH_ONLY_PSYCHROMETRIC_CONSTRAINT_GAP_QUANTIFIED",
       "production_epw_ready":False,
       "input_original_model_daily_sha256":modelsha,
       "input_original_p7b_2013_hourly_sha256":rawsha,
       "input_original_nasa_p6e_hourly_sha256":nasasha,
       "input_original_geosphere_station_daily_sha256":stationsha,
       "input_p7b_reference_original_epw_sha256":original["hashes"][
           "Graz_2013_CanESM5_P7B_SYNTHETIC_DAILY_TO_HOURLY_RESEARCH.epw"],
       "original_hourly_nasa_source_records":nasacount,
       "humidity_2013_daily_days":len(moist),
       "humidity_days_closed_in_registered_family":closed,
       "humidity_days_not_closed_in_registered_family":len(moist)-closed,
       "humidity_original_source_annual_hurs_always_conserved":True,
       "humidity_family_abs_coefficient_pp_max":RH_SHAPE_CAP_PP,
       "humidity_new_max_unclosed_source_huss_kg_kg":rest,
       "humidity_original_p7b_max_unclosed_source_huss_kg_kg":
           original["maximum_unclosed_huss_kg_kg"],
       "humidity_daily_huss_joint_constraint_closed_for_every_day":closed==len(moist),
       "provisional_moisture_candidate_epw_written":False,
       "solar_10y_historical_climatology":clim,
       "solar_10y_original_ground_observed_station_climatology":station_clim,
       "solar_model_and_observed_dates_event_matched":False,
       "solar_reference_source":"NASA POWER 2005–2014 original satellite/reanalysis grid, NOT station observation",
       "solar_model_source":"NASA NEX-GDDP-CMIP6 original BCSD daily CanESM5, not same dates as actual observations",
       "solar_time_support":"Annual normalized 365-day energies / unpaired monthly 10-year daily climatology; 2008/2012 NASA leap days retained and normalized for annual energy",
       "output_sha256":files,
       "limitations":[
          "Registered RH family is an exact-conservation test of daily mean hurs and constrained cosinusoidal shape, NOT a proof of global thermodynamic incompatibility.",
          "Other 24-hour RH shapes and source pressure may improve achievable original huss; no instrumental/source correction made.",
          "When native q is outside family feasible range, closest bounded candidate is diagnostic only and all original source data remain unchanged.",
          "This phase does NOT replace accepted P7B hourly/EPW or assert an improved EPW.",
          "Historical model event dates are NOT matched to NASA station/grid dates; only multi-year seasonal distribution is evidence.",
          "NASA ten-year model/gridded climatology is NOT ground observed; a second independent original GeoSphere station GHI source is reported separately.",
          "GeoSphere station daily GHI is quality screened and observed, but source solar day is previous-day 23 UTC to labelled-day 23 UTC; unpaired monthly/annual comparisons only.",
          "Ten-year historical climatology does not validate future projections or building-energy simulation skill.",
          "No wind/precipitation diurnal calibration, future SSP or other 7 CMIP6 models in this diagnostic." ]}
    (out/"p7b1_science_audit.json").write_text(
        json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("P7B.1",audit["technical_status"],"source humidity fit",
          closed,"/",len(moist),"max remaining huss",rest,
          "10y solar pct vs NASA",clim["model_minus_nasa_10y_climatological_pct"],
          "vs station",station_clim["model_minus_station_pct"],
          "EPW production",False,flush=True)
    return audit

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--model-original",type=Path,required=True)
    ap.add_argument("--p7b-original",type=Path,required=True)
    ap.add_argument("--nasa-original",type=Path,required=True)
    ap.add_argument("--geosphere-daily",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    x=ap.parse_args()
    run(x.model_original,x.p7b_original,x.nasa_original,x.geosphere_daily,x.out)
