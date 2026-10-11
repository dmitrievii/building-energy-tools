#!/usr/bin/env python3
"""IGE P6.3D independent hourly solar reference vs QC daily Graz observations.

External NASA POWER hourly surface GHI is a NASA gridded satellite/reanalysis
product (not a ground station observation or a second measured hourly series).
The POWER API explicitly returns UTC hour START timestamps. The first/last
year is 2005/2014, and the first boundary requires 2004-12-31 23 UTC.

Official GeoSphere daily cglo_j: [23 UTC previous date, 23 UTC label date).
Official GeoSphere hourly cglo q21=0: "ungeprüfte Daten" (UNVERIFIED).
No unverified hour can be promoted to QC-accepted observational reference.
Original 2005-2014 GCM day is never paired with observed weather dates.
No calibration, resampling, infill, EPW output, or production code here.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,time
from collections import Counter,defaultdict
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

from p6_2d_solar_methods_benchmark import csvread,checksum
from p6_3a_solar_joint_coherence import corr_vectors
from p6_3c_precip_semantics_daily_alignment import save_union

BASE="https://power.larc.nasa.gov/api/temporal/hourly/point"
SITES={
    "graz_station30":{"latitude":47.08,"longitude":15.45,
                      "meaning":"reference station vicinity, not equal to NASA product grid center"},
    "nasa_gcm_cell":{"latitude":46.875,"longitude":15.375,
                     "meaning":"NASA NEX-GDDP reference cell center, satellite/reanalysis footprint differs"},
}
PARAM=("ALLSKY_SFC_SW_DWN","T2M")
PERIODS=((2004,2006),(2006,2008),(2008,2010),(2010,2012),(2012,2014))
DAYS=3652
START=datetime(2004,12,31,23,tzinfo=timezone.utc)
END=datetime(2015,1,1,0,tzinfo=timezone.utc)
OBS_FIRST=date(2005,1,1);OBS_END=date(2014,12,31)
RAW_POWER_KIND="NASA_POWER_GRID_SATELLITE_REANALYSIS_NOT_STATION_OBSERVATION"
MIN_DAILY_COMPLETENESS=.95
MAX_ALLOWED_GHI_KWH_H=1.5
SEASONS={"ANNUAL":set(range(1,13)),"DJF":{12,1,2},
         "MAM":{3,4,5},"JJA":{6,7,8},"SON":{9,10,11}}
WINDOWS=("geosphere_23_23UTC","utc_midnight_00_24UTC")

def source_contract(geosphere_meta,p6c_hourly):
    q21={x.get("key"):x.get("value") for x in geosphere_meta.get("code_lists",{}).get("q21",[])}
    if q21.get(0)!="ungeprüfte Daten":
        raise ValueError("Official GeoSphere q21=0 is not confirmed unchecked")
    accepted={10,11,12,20,21,22}
    if any(k not in q21 for k in accepted):
        raise ValueError("GeoSphere official verified q21 codes changed")
    if p6c_hourly.get("hourly_solar_flag_approved")!=0 or \
       p6c_hourly.get("hourly_solar_unverified")!=87648:
        raise ValueError("Frozen original P6.3C 2005-14 hourly solar q21 findings changed")
    if p6c_hourly.get("hourly_counts_total")!=87648:
        raise ValueError("Frozen GeoSphere native hourly UTC coverage incorrect")
    return {"q21_zero_meaning":q21[0],"qc_accepted_codes":sorted(accepted),
            "native_geosphere_hourly_records":87648,
            "original_hourly_solar_approved_count":0,
            "original_hourly_solar_unverified_count":87648,
            "scientific_prohibition":"0 independently q21-approved GeoSphere hourly solar records; NEVER infer observed hourly GHI from these unchecked sources"}

def http_json(url,limit=28000000):
    failures=[]
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={
                "Accept":"application/json",
                "User-Agent":"IGE-P6.3D-hourly-GHI-source-audit-2026"}),timeout=120) as res:
                original=res.read(limit+1)
                if res.status!=200 or len(original)>limit:
                    raise RuntimeError("Unexpected provider HTTP status or payload length")
                data=json.loads(original)
                if not isinstance(data,dict):
                    raise ValueError("NASA POWER original response must be a JSON object")
                messages=data.get("messages",[])
                if isinstance(messages,dict):
                    errors=messages.get("error") or messages.get("errors") or []
                    if isinstance(errors,str):errors=[errors]
                elif isinstance(messages,list):
                    errors=[message for message in messages
                        if (isinstance(message,dict) and
                            str(message.get("level",message.get("type",""))).lower()
                            in ("error","fatal")) or
                           (isinstance(message,str) and
                            message.strip().lower().startswith(("error:","fatal:")))]
                elif messages in (None,""):
                    errors=[]
                else:
                    raise ValueError("Unexpected NASA POWER messages metadata type")
                if errors:
                    raise ValueError("NASA POWER provider error message: "+str(errors)[:2000])
                return original,data
        except (HTTPError,URLError,OSError,ValueError,RuntimeError,TimeoutError) as exc:
            failures.append(str(exc))
            if isinstance(exc,HTTPError) and exc.code in (400,401,403,404,422):
                break
            if attempt<2:time.sleep(2**attempt)
    raise RuntimeError("POWER hourly original source not available; NO silent fallback: "+str(failures))

def energy_hourly_kwh(v,unit):
    """NASA POWER field metadata controls units. One hourly average W/m² -> kWh/m²."""
    unit=str(unit).lower().replace(" ","").replace("²","^2")
    if not math.isfinite(float(v)) or float(v)<0:
        raise ValueError("POWER valid solar irradiance must be finite non-negative")
    if unit in ("w/m^2","w/m2","wh/m^2","wh/m2","w-hr/m^2",
                "w-hr/m2"):
        out=float(v)/1000.
    elif unit in ("kw-hr/m^2","kw-hr/m2","kwh/m^2","kwh/m2",
                  "kwh/m^2/hour","kw-hr/m^2/hr"):
        out=float(v)
    else:
        raise ValueError("Unknown NASA POWER hourly solar radiation unit: "+unit)
    if out>MAX_ALLOWED_GHI_KWH_H:
        raise ValueError("Physically implausible hourly GHI from NASA POWER")
    return out

def validate_power_response(payload,site,startyear,endyear):
    header=payload.get("header",{})
    if header.get("time_standard")!="UTC":
        raise ValueError("POWER returned non-UTC time standard")
    if header.get("start") not in (f"{startyear}1231",f"{startyear}0101") \
       or header.get("end")!=f"{endyear}1231":
        raise ValueError("POWER returned unexpected requested time span")
    source=payload.get("parameters",{})
    if not set(PARAM)<=set(source) or any("units" not in source[k] for k in PARAM):
        raise ValueError("Missing hourly POWER original physical units")
    field=payload.get("properties",{}).get("parameter",{})
    if not set(PARAM)<=set(field):raise ValueError("Missing original POWER fields")
    solar=field[PARAM[0]]
    temp=field[PARAM[1]]
    if not isinstance(solar,dict) or not isinstance(temp,dict) or set(solar)!=set(temp):
        raise ValueError("NASA POWER hourly solar/met time axes inconsistent")
    requested_start=date(startyear,12,31)
    expected=[(requested_start+timedelta(days=i)).strftime("%Y%m%d")
              for i in range((date(endyear,12,31)-requested_start).days+1)]
    times={d+f"{h:02d}" for d in expected for h in range(24)}
    if set(solar)!=times:
        raise ValueError(f"NASA POWER hourly UTC calendar incomplete: {len(solar)}/{len(times)}")
    if source[PARAM[1]]["units"] not in ("C","°C","degC"):
        raise ValueError("POWER hourly original air-temperature unit drift")
    geometry=payload.get("geometry",{}).get("coordinates")
    if geometry is None or len(geometry)<2:
        raise ValueError("NASA POWER gridded source coordinates missing")
    # POWER point geometry represents requested location, not the native
    # CERES satellite grid; exact grid attribution remains metadata dependent.
    if abs(float(geometry[0])-site["longitude"])>1.0 or \
       abs(float(geometry[1])-site["latitude"])>1.0:
        raise ValueError("POWER returned unrelated location")
    fill=float(header.get("fill_value",-999))
    parsed={}
    solar_unit=source[PARAM[0]]["units"]
    for key in sorted(times):
        raw=solar[key];thermal=temp[key]
        if raw is None or thermal is None or float(raw)==fill or float(thermal)==fill:
            parsed[key]={"ghi_hour_kwh_m2":None,"air_temperature_c":None,
                         "valid":False}
        else:
            en=energy_hourly_kwh(float(raw),solar_unit)
            t=float(thermal)
            if not math.isfinite(t) or not -75<=t<=65:
                raise ValueError("NASA POWER hourly temperature outside expected range")
            parsed[key]={"ghi_hour_kwh_m2":en,"air_temperature_c":t,"valid":True}
    return parsed,{"original_units":{k:source[k]["units"] for k in PARAM},
                   "source_header":header,"provider_geometry":geometry,
                   "provider_data_types":payload.get("header",{}).get("sources"),
                   "hourly_records":len(parsed),
                   "hourly_missing":sum(not v["valid"] for v in parsed.values())}

def fetch_site(site_name,output):
    site=SITES[site_name]
    combined={};prov=[]
    for first,last in PERIODS:
        url=BASE+"?"+urlencode({"parameters":",".join(PARAM),"community":"RE",
                     "longitude":site["longitude"],"latitude":site["latitude"],
                     "start":f"{first}1231","end":f"{last}1231",
                     "format":"JSON","time-standard":"UTC"})
        blob,payload=http_json(url)
        path=output/f"power_hourly_original_{site_name}_{first}1231_{last}1231.json"
        path.write_bytes(blob)
        parsed,meta=validate_power_response(payload,site,first,last)
        dup=0
        for key,row in parsed.items():
            if key in combined:
                dup+=1
                original=combined[key]
                if original!=row:raise ValueError("POWER overlapping two-year source changed within request")
            else:combined[key]=row
        prov.append({"site":site_name,"block":f"{first}-{last}",
                     "provider_request":url,
                     "raw_json_file":path.name,
                     "raw_json_sha256":hashlib.sha256(blob).hexdigest(),
                     "overlap_hour_count":dup,**meta})
        print("P6.3D NASA POWER",site_name,first,last,"hours",len(parsed),
              "missing",meta["hourly_missing"],flush=True)
    expected={(
        datetime(2004,12,31,tzinfo=timezone.utc)+timedelta(hours=i)
        ).strftime("%Y%m%d%H")
        for i in range((datetime(2015,1,1,tzinfo=timezone.utc)
                        -datetime(2004,12,31,tzinfo=timezone.utc)).days*24)}
    # Source includes exactly UTC noon/late 2004-12-31 through 2014-12-31,
    # with known one-date buffer before the observational 2005 start.
    if set(combined)!=expected:
        raise ValueError(f"Unexpected NASA POWER UTC 2004-12-31–2014-12-31 timeline {len(combined)}/{len(expected)}")
    return combined,prov

def load_station_daily(p6c_root):
    data=csvread(p6c_root/"p6_3c_rain_daily_sites"/"p6_3c_station30_precipitation_reinterpreted.csv")
    if len(data)!=DAYS:raise ValueError("Frozen official station daily QC incomplete")
    index={}
    for r in data:
        d=date.fromisoformat(r["date"])
        if d<OBS_FIRST or d>OBS_END or r["station_id"]!="30" or r["date"] in index:
            raise ValueError("Original official daily GHI date/station mismatch")
        v=float(r["ghi_kwh_m2_day"])
        if not math.isfinite(v) or not 0<=v<15:
            raise ValueError("Previous accepted GeoSphere original daily GHI corrupted")
        index[r["date"]]=v
    if len(index)!=DAYS:raise ValueError("Accepted station solar dates missing")
    return index

def hourly_sum(data,day,window):
    if window not in WINDOWS:raise ValueError("Unsupported observed solar UTC integration window")
    first=(datetime.combine(day,datetime.min.time(),tzinfo=timezone.utc)
           -timedelta(hours=1) if window=="geosphere_23_23UTC"
           else datetime.combine(day,datetime.min.time(),tzinfo=timezone.utc))
    hours=[(first+timedelta(hours=i)).strftime("%Y%m%d%H") for i in range(24)]
    if any(hour not in data for hour in hours):
        raise ValueError("POWER hourly UTC boundary source coverage incomplete")
    src=[data[hour] for hour in hours]
    valid=all(r["valid"] for r in src)
    return (sum(r["ghi_hour_kwh_m2"] for r in src) if valid else None,
            fmean(r["air_temperature_c"] for r in src) if valid else None,
            valid)

def metrics(raw,season,window,site):
    scores=[r for r in raw if r["season"]==season and r["window"]==window
            and r["site"]==site]
    enough=[r for r in scores if r["valid_day"]]
    obs=[r["official_ghi_kwh_m2_day"] for r in enough]
    pred=[r["power_ghi_kwh_m2_day"] for r in enough]
    if not scores:raise ValueError("Expected daily solar validation sample missing")
    n=len(enough);coverage=n/len(scores)
    original=sum(r["official_ghi_kwh_m2_day"] for r in scores)
    predicted=sum(pred)
    return {"site":site,"season":season,"window":window,
       "source_type":RAW_POWER_KIND,"observed_days":len(scores),
       "complete_power_hourly_days":n,"coverage":coverage,
       "mean_bias_kwh_m2_day":fmean(p-o for p,o in zip(pred,obs)) if n else None,
       "mean_absolute_error_kwh_m2_day":fmean(abs(p-o) for p,o in zip(pred,obs)) if n else None,
       "daily_pearson_r":corr_vectors(pred,obs) if n>=30 else None,
       "observed_period_energy_kwh_m2":original,
       "power_valid_days_energy_kwh_m2":predicted,
       "paired_subset_ratio":predicted/sum(obs) if n and sum(obs)>0 else None,
       "coverage_status":"COMPLETE_OR_NEAR_COMPLETE_REFERENCE" if coverage>=MIN_DAILY_COMPLETENESS
                         else "INSUFFICIENT_PROVIDER_COVERAGE",
       "qualified_as_accepted_hourly_station_measurement":False}

def run(geosphere_original,p6c_frozen,out):
    out.mkdir(parents=True,exist_ok=True)
    metadata_file=geosphere_original/"geosphere_station30_daily_metadata_original.json"
    p6c_file=p6c_frozen/"p6_3c_hourly_seam"/"p6_3c_hourly_original_qc_report.json"
    origin=json.loads(metadata_file.read_text(encoding="utf8"))
    original_hourly=json.loads(p6c_file.read_text(encoding="utf8"))
    contract=source_contract(origin,original_hourly)
    station=load_station_daily(p6c_frozen)
    originals={p.name:checksum(p) for p in (metadata_file,p6c_file,
        p6c_frozen/"p6_3c_rain_daily_sites"/"p6_3c_station30_precipitation_reinterpreted.csv")}
    daily=[];provenance=[]
    for name in SITES:
        original,source=fetch_site(name,out)
        provenance.extend(source)
        for label,obs in sorted(station.items()):
            d=date.fromisoformat(label)
            for window in WINDOWS:
                value,temp,valid=hourly_sum(original,d,window)
                daily.append({"site":name,"date":label,"year":d.year,
                    "month":d.month,"season":"not_assigned",
                    "window":window,"valid_day":bool(valid),
                    "official_ghi_kwh_m2_day":obs,
                    "power_ghi_kwh_m2_day":value,
                    "power_temperature_c_hour_mean":temp,
                    "power_minus_official_kwh_m2_day":value-obs if valid else None,
                    "geosphere_hourly_q21_verified":False,
                    "power_is_station_observation":False})
    if len(daily)!=len(SITES)*DAYS*len(WINDOWS):
        raise ValueError("Incomplete 2-site × 2-window 10-year study")
    performance=[]
    for site in SITES:
        for window in WINDOWS:
            for season,months in SEASONS.items():
                selected=[{**r,"season":season} for r in daily
                          if r["site"]==site and r["window"]==window
                          and r["month"] in months]
                performance.append(metrics(selected,season,window,site))
    evidence=all(r["coverage_status"]=="COMPLETE_OR_NEAR_COMPLETE_REFERENCE" for r in performance)
    csvs={
        "p6_3d_power_vs_geosphere_daily_2005_2014_two_utc_windows.csv":daily,
        "p6_3d_hourly_external_reference_seasonal_metrics.csv":performance,
        "p6_3d_power_original_hourly_source_provenance.csv":provenance}
    hashes={n:save_union(out/n,r) for n,r in csvs.items()}
    comparisons={r["site"]:{w:next(x for x in performance
                if x["site"]==r["site"] and x["window"]==w and x["season"]=="ANNUAL")
                for w in WINDOWS} for r in performance}
    report={"stage":"IGE_P6_3D_OFFICIAL_Q21_HOURLY_INDEPENDENT_SATELLITE_REFERENCE",
       "technical_status":"PASS_ORIGINAL_PROVENANCE_HOURLY_UTC_SOURCE_AUDIT" if evidence
                          else "INSUFFICIENT_EXTERNAL_HOURLY_COVERAGE",
       "scientific_status":"NO_VALIDATED_GROUND_HOURLY_GHI_AND_NO_EPW_PRODUCTION",
       "geosphere_q21_contract":contract,
       "geosphere_original_sha256":originals,
       "external_source_type":RAW_POWER_KIND,
       "power_time_standard":"UTC; hour timestamp is start of hour",
       "power_locations":SITES,
       "source_period":"2005-2014, plus 2004-12-31 UTC overlap buffer",
       "reference_daily_geo_window":"[23 UTC previous date, 23 UTC labelled date)",
       "original_source_evidence":provenance,
       "seasonal_daily_metrics":performance,
       "comparison_windows_annual":comparisons,
       "output_sha256":hashes,
       "production_epw_ready":False,
       "allowed_research_next_steps":[
          "Acquire independently q21-checked hourly ground GHI data or obtain formal source QA certification from GeoSphere",
          "Study CERES SYN1deg satellite pixel/temporal support against Graz topographic station representativeness",
          "Investigate station vs satellite solar daily and hourly uncertainty including subdaily cloud and direct/diffuse",
          "Only then design conditional physically bounded hourly EPW weather disaggregation and multivariate closure"],
       "scientific_limits":[
          "GeoSphere q21=0 is unverified data. All 87,648 original hourly cglo records are unverified and cannot become station ground truth through arithmetic matching daily GHI.",
          "NASA POWER hourly GHI is gridded satellite/reanalysis data, not a q21-verified ground measurement and may share upstream sources with climate model or NASA products.",
          "There is no independent observed, certified hourly GHI source established for Graz by this experiment.",
          "GeoSphere official cglo_j is accepted calibrated DAILY energy, not independent from original provider unchecked hourly cglo.",
          "External NASA POWER UTC and station 23:00-to-23:00 day boundaries require explicit one-day-offset source coverage; neither window is silently chosen to optimize fit.",
          "No hourly weather generation, inverse QDM or direct/diffuse synthesis, no future hourly EPW, no main merge.",
          "The analysis does not establish independent physical closure of temperature, humidity, atmospheric LW or precipitation.",
       ]}
    (out/"p6_3d_hourly_independent_validation_science_audit.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P6.3D",report["technical_status"],
          "GEOSPHERE_VALIDATED_HOURLY",contract["original_hourly_solar_approved_count"],
          "NASA_POWER_GRIDDDED_DAILY_PAIRS",
          sum(r["complete_power_hourly_days"] for r in performance if
              r["season"]=="ANNUAL"),
          "EPW_READY",report["production_epw_ready"],flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--geosphere-original",type=Path,required=True)
    p.add_argument("--p6c-frozen",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    run(a.geosphere_original,a.p6c_frozen,a.out)
