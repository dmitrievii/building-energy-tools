#!/usr/bin/env python3
"""IGE P8.4A2 2024-01 original 10-min -> 1h wind aggregation audit.

Source measurements are transient; export *only* aggregate metrics / SHA256.
Never equate instantaneous ERA5 hourly validity-time wind with 1h observations.
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
import statistics
from pathlib import Path
from urllib.parse import urlencode

from p8_1e_swiss_external import decode_csv, fetch, parse_meta
from p8_2e_crossyear import ROOT
from p8_3a_wind_spatial import CALM_MPS, circular_error_deg, uv_to_wind_from, wind_from_to_uv
from p8_4a1_source_semantics import (
    YEAR, MONTH, HOURS, GEO_BASE, GEO_QC, read_json, geo_metadata_audit,
    january_hours, swiss_post2018_hourly_reference_stamps,
)

SWISS_SITES = ("BAS", "GRA", "MUB")
GEO_SITES = (16400, 16412)
TEN_SPEED, TEN_DIRECTION = "fkl010z0", "dkl010z0"
HOUR_SPEED, HOUR_DIRECTION = "fkl010h0", "dkl010h0"
MAX_T_BYTES = 180_000_000
MIN_FRACTION = .85
REQUIRED_HOURS = tuple(january_hours()[1:])  # 743 complete Jan-only 10-min windows
HOUR_TO_TEN = {t:swiss_post2018_hourly_reference_stamps(t) for t in REQUIRED_HOURS}


def utc_ten_axis():
    start=dt.datetime(YEAR,MONTH,1,0,0)
    return tuple(start+dt.timedelta(minutes=10*i) for i in range(HOURS*6))


def parse_datetime_utc(text):
    try:
        return dt.datetime.strptime(text,"%d.%m.%Y %H:%M")
    except (ValueError,TypeError) as exc:
        raise ValueError("A2_INVALID_SWISS_UTC_TIMESTAMP") from exc


def source_field_semantics(raw):
    rows,columns=decode_csv(raw)
    parameters=(TEN_SPEED,TEN_DIRECTION,HOUR_SPEED,HOUR_DIRECTION)
    found={}
    for name in parameters:
        matches=[r for r in rows if name in r.values()]
        if len(matches)!=1:
            # Original metadata is wide; do not silently accept a guessed source code.
            raise ValueError("A2_OFFICIAL_PARAMETER_METADATA_MISSING_OR_AMBIGUOUS_"+name)
        found[name]={k:v for k,v in matches[0].items() if v and len(str(v))<350}
    return found


def parse_swiss_tenminute(raw,site):
    """Bound memory by retaining only January 2024 records, not the full decade."""
    try:
        txt=raw.decode("utf-8-sig","strict")
    except UnicodeDecodeError:
        txt=raw.decode("cp1252","strict")
    reader=csv.DictReader(io.StringIO(txt),delimiter=";")
    required={"station_abbr","reference_timestamp",TEN_SPEED,TEN_DIRECTION}
    if not required.issubset(reader.fieldnames or ()):
        raise ValueError("A2_SWISS_10MIN_SCHEMA_MISSING_"+str(reader.fieldnames))
    stamps=set(utc_ten_axis())
    result={}
    for row in reader:
        if (row.get("station_abbr") or "").strip().upper()!=site:
            continue
        stamp_str=row.get("reference_timestamp") or ""
        if len(stamp_str)<16 or stamp_str[3:10]!="01.2024":
            continue
        stamp=parse_datetime_utc(stamp_str)
        if stamp not in stamps:
            continue
        if stamp in result:
            raise ValueError("A2_SWISS_DUPLICATE_TEN_MINUTE_"+site)
        def num(key,hi):
            try:
                x=float(row[key])
                return x if math.isfinite(x) and 0<=x<=hi else None
            except (TypeError,ValueError):
                return None
        speed=num(TEN_SPEED,90)
        direction=num(TEN_DIRECTION,360)
        result[stamp]={"speed":speed,"direction":direction%360 if direction is not None else None}
    if len(result)<.95*len(stamps):
        raise ValueError("A2_SWISS_MISSING_MOST_TENMINUTE_ROWS_"+site)
    return result


def canonical_from_components(u,v):
    """Meteorological FROM angle on [0,360), independent of unit scale.

    Caller alone determines whether the resultant is physically resolved.
    """
    d=math.degrees(math.atan2(-u,-v))%360.
    return 0. if math.isclose(d,360.,abs_tol=1e-10) else d


def aggregate_six(samples):
    """Six 10min end stamps, no fills and no fabricated calm direction."""
    if len(samples)!=6:
        raise ValueError("A2_EXACTLY_SIX_SOURCE_SAMPLES_REQUIRED")
    if any(x is None or x.get("speed") is None for x in samples):
        return None
    values=[float(x["speed"]) for x in samples]
    if any(not math.isfinite(x) or x<0 for x in values):
        raise ValueError("A2_INVALID_SOURCE_WIND_SPEED")
    scalar=statistics.mean(values)
    to_u=to_v=unit_u=unit_v=0.
    n_direction=0
    for row in samples:
        speed=float(row["speed"])
        if speed<CALM_MPS:
            continue
        direction=row.get("direction")
        if direction is None or not math.isfinite(float(direction)):
            return {"scalar_speed":scalar,"vector_speed":None,
                    "weighted_direction":None,"unit_direction":None,
                    "direction_qualified":False}
        direction=float(direction)%360.
        u,v=wind_from_to_uv(speed,direction)
        to_u+=u
        to_v+=v
        theta=math.radians(direction)
        unit_u-=math.sin(theta)
        unit_v-=math.cos(theta)
        n_direction+=1
    vec_speed=math.hypot(to_u/6,to_v/6)
    if vec_speed>scalar+1e-8:
        raise AssertionError("A2_VECTOR_GREATER_THAN_SCALAR")
    weighted=canonical_from_components(to_u,to_v) if vec_speed>=CALM_MPS else None
    unit_magnitude=math.hypot(unit_u,unit_v)/max(n_direction,1)
    unit=canonical_from_components(unit_u,unit_v) if n_direction and unit_magnitude>=.15 else None
    return {"scalar_speed":scalar,"vector_speed":vec_speed,
            "weighted_direction":weighted,"unit_direction":unit,
            "direction_qualified":n_direction>0}


def matched_hourly(ten,hourly,site):
    """Strict common original clock. 743 hours, never compare arbitrary dates."""
    rows=[]
    for stamp in REQUIRED_HOURS:
        obs=hourly.get(stamp)
        values=[ten.get(t) for t in HOUR_TO_TEN[stamp]]
        est=aggregate_six(values)
        if est is None or obs is None or obs.get("speed") is None:
            continue
        rows.append({"stamp":stamp,"actual":obs,"estimate":est})
    if len(rows)<math.ceil(MIN_FRACTION*len(REQUIRED_HOURS)):
        raise ValueError("A2_TOO_FEW_SOURCE_COMPLETE_SIX_SAMPLE_HOURS_"+site+"_"+str(len(rows)))
    return rows


def basic_errors(differences):
    return {
        "n":len(differences),
        "mae":statistics.mean(abs(x) for x in differences) if differences else None,
        "bias":statistics.mean(differences) if differences else None,
        "rmse":math.sqrt(statistics.mean(x*x for x in differences)) if differences else None,
    }


def summarize(rows,reference_semantics):
    if not rows:
        raise ValueError("A2_NO_MATCHED_ROWS")
    scalar=[r["estimate"]["scalar_speed"]-r["actual"]["speed"] for r in rows]
    vectors=[r for r in rows if r["estimate"]["vector_speed"] is not None]
    both_speed={
        "scalar":basic_errors([r["estimate"]["scalar_speed"]-r["actual"]["speed"] for r in vectors]),
        "vector":basic_errors([r["estimate"]["vector_speed"]-r["actual"]["speed"] for r in vectors]),
    }
    gaps=[r["estimate"]["scalar_speed"]-r["estimate"]["vector_speed"] for r in vectors]
    if any(v< -1e-7 for v in gaps):
        raise AssertionError("A2_JENSEN_BOUND_VIOLATION")
    noncalm=[r for r in rows if r["actual"]["speed"]>=CALM_MPS
             and r["actual"].get("direction") is not None]
    common=[
        r for r in noncalm
        if all(r["estimate"][k] is not None for k in ("weighted_direction","unit_direction"))
    ]
    angular={}
    for name in ("weighted_direction","unit_direction"):
        available=[
            r for r in noncalm if r["estimate"][name] is not None
        ]
        angular[name]={
            "n_resolved":len(available),
            "coverage_vs_reference_noncalm":len(available)/len(noncalm) if noncalm else None,
            "mae_deg_on_strict_both_resolved":(
                statistics.mean(circular_error_deg(r["estimate"][name],r["actual"]["direction"])
                                for r in common) if common else None),
            "n_strict_both_resolved":len(common),
        }
    return {
        "reference_semantics":reference_semantics,
        "n_possible_complete_january_hourly_windows":len(REQUIRED_HOURS),
        "n_original_matched_hourly_values":len(rows),
        "matched_fraction":len(rows)/len(REQUIRED_HOURS),
        "scalar_speed_error_mps":basic_errors(scalar),
        "fair_same_hour_scalar_vs_vector_speed_error_mps":both_speed,
        "n_all_direction_defined_for_jensen":len(gaps),
        "scalar_minus_vector_mps":{
            "mean":statistics.mean(gaps) if gaps else None,
            "maximum":max(gaps) if gaps else None,
            "nonnegative_verified":True,
        },
        "reference_noncalm_with_direction":len(noncalm),
        "direction_candidates":angular,
        "source_resolution": "Original 10-minute end-of-window records → hourly six-way candidate",
        "source_raw_samples_published":False,
    }


def swiss_source_audit():
    meta,meta_sha=fetch(ROOT+"/ogd-smn_meta_parameters.csv",max_bytes=3_000_000)
    declared=source_field_semantics(meta)
    reports=[]
    for site in SWISS_SITES:
        ten_url=f"{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_t_historical_2020-2029.csv"
        raw,sha=fetch(ten_url,max_bytes=MAX_T_BYTES)
        ten=parse_swiss_tenminute(raw,site)
        del raw
        # Keep provider's original hourly wind decoder unchanged.
        from p8_3e1_f1_wind_qualification import station_year
        hourly,hsha=station_year(site,YEAR)
        rows=matched_hourly(ten,hourly,site)
        summary=summarize(rows,"fkl010h0 original scalar hourly mean m/s")
        summary.update({
            "station":site,"provider":"MeteoSwiss",
            "ten_minute_original_sha256":sha,"hourly_original_sha256":hsha,
            "ten_minute_full_january_rows":len(ten),
            "parameters":{"ten_speed":TEN_SPEED,"ten_direction":TEN_DIRECTION,
                          "hour_speed":HOUR_SPEED,"hour_direction":HOUR_DIRECTION},
            "individual_original_qc_flags_available":False,
            "source_timestamp_semantics":"2018+ six ten-minute end-stamps through reference hourly UTC",
            "hourly_aggregation_official_algorithm_proven":False,
        })
        reports.append(summary)
    return {"original_parameter_metadata_sha256":meta_sha,
            "parameters_official_source_rows":declared,"stations":reports,
            "n_sites":len(reports)}


def geo_tenminute_source(station,source_meta):
    """Optional original 10min provider; fail *site* evidence rather than fake closure."""
    raw,_=source_meta
    info=geo_metadata_audit(raw,station_id=station)
    query={
        "parameters":"ff,ff_flag,dd,dd_flag",
        "station_ids":str(station),
        "start":"2024-01-01T00:00","end":"2024-01-31T23:50",
        "output_format":"geojson",
    }
    api="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-10min"
    obj,sha=read_json(api+"?"+urlencode(query),cap=16_000_000)
    stamps=obj.get("timestamps")
    axis=utc_ten_axis()
    if not isinstance(stamps,list) or len(stamps)!=len(axis):
        raise ValueError("A2_GEO_TEN_MINUTE_FULL_MONTH_CLOCK_UNAVAILABLE")
    for k,(text,expected) in enumerate(zip(stamps,axis)):
        try:
            t=dt.datetime.fromisoformat(str(text).replace("Z","+00:00"))
        except (ValueError,TypeError) as exc:
            raise ValueError("A2_GEO_INVALID_TEN_TIMESTAMP") from exc
        if t.utcoffset()!=dt.timedelta(0) or t.replace(tzinfo=None)!=expected:
            raise ValueError("A2_GEO_TEN_MINUTE_UTC_AXIS_SHIFT")
    features=obj.get("features") or []
    if len(features)!=1:
        raise ValueError("A2_GEO_10MIN_FEATURE_COUNT")
    p=features[0].get("properties") or {}
    sid=p.get("station")
    sid=int(sid.get("id") if isinstance(sid,dict) else sid)
    if sid!=station:
        raise ValueError("A2_GEO_STATION_IDENTITY_CHANGED")
    params=p.get("parameters") or {}
    for name in ("ff","dd","ff_flag","dd_flag"):
        if len((params.get(name) or {}).get("data") or [])!=len(axis):
            raise ValueError("A2_GEO_TEN_MINUTE_PARAMETER_AXIS_"+name)
    for name in ("ff","dd"):
        if params[name].get("unit")!=info["parameter_definitions"][name]["units"]:
            raise ValueError("A2_GEO_10MIN_HOUR_UNIT_MISMATCH")
    result={}
    qc=collections.Counter()
    n_approved=0
    for i,t in enumerate(axis):
        v=params["ff"]["data"][i]
        a=params["dd"]["data"][i]
        speed_flag=params["ff_flag"]["data"][i]
        direction_flag=params["dd_flag"]["data"][i]
        qc[(str(speed_flag),str(direction_flag))]+=1
        physical_speed=isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=90
        physical_direction=isinstance(a,(int,float)) and math.isfinite(a) and 0<=a<=360
        valid=physical_speed and int(speed_flag) in GEO_QC if speed_flag is not None else False
        valid_dir=physical_direction and int(direction_flag) in GEO_QC if direction_flag is not None else False
        if valid and (v<CALM_MPS or valid_dir):
            n_approved+=1
        result[t]={"speed":float(v) if valid else None,
                   "direction":float(a)%360 if valid_dir else None}
    return result,{"original_10min_sha256":sha,"n_qc_approved_wind_10min":n_approved,
                   "n_10min":len(axis),
                   "quality_flag_pairs":{str(k):v for k,v in qc.items()},
                   "original_qc_joint_coverage":n_approved/len(axis)}


def geo_hourly_source(station):
    query={
        "parameters":"ff,ff_flag,dd,dd_flag","station_ids":str(station),
        "start":"2024-01-01T00:00","end":"2024-01-31T23:00",
        "output_format":"geojson"
    }
    obj,sha=read_json(GEO_BASE+"?"+urlencode(query),cap=8_000_000)
    hours=january_hours()
    stamps=obj.get("timestamps")
    if not isinstance(stamps,list) or len(stamps)!=len(hours):
        raise ValueError("A2_GEO_HOUR_AXIS_INCOMPLETE")
    if len(obj.get("features") or [])!=1:
        raise ValueError("A2_GEO_HOUR_FEATURE_COUNT")
    p=obj["features"][0].get("properties") or {}
    obj_id=p.get("station")
    if int(obj_id.get("id") if isinstance(obj_id,dict) else obj_id)!=station:
        raise ValueError("A2_GEO_HOUR_IDENTITY_MISMATCH")
    pars=p.get("parameters") or {}
    for n in ("ff","dd","ff_flag","dd_flag"):
        if len((pars.get(n) or {}).get("data") or [])!=len(hours):
            raise ValueError("A2_GEO_HOUR_FIELD_MISSING")
    out={}
    for i,(tstring,stamp) in enumerate(zip(stamps,hours)):
        actual=dt.datetime.fromisoformat(str(tstring).replace("Z","+00:00"))
        if actual.utcoffset()!=dt.timedelta(0) or actual.replace(tzinfo=None)!=stamp:
            raise ValueError("A2_GEO_HOUR_UTC_AXIS")
        v=pars["ff"]["data"][i]
        a=pars["dd"]["data"][i]
        fs=pars["ff_flag"]["data"][i]
        fd=pars["dd_flag"]["data"][i]
        valid=(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=90 and
               fs is not None and int(fs) in GEO_QC)
        valid_dir=(isinstance(a,(int,float)) and math.isfinite(a) and 0<=a<=360
                   and fd is not None and int(fd) in GEO_QC)
        out[stamp]={"speed":float(v) if valid else None,
                    "direction":float(a)%360 if valid_dir else None}
    return out,sha


def geosphere_source_audit():
    meta=read_json(GEO_BASE+"/metadata",cap=10_000_000)
    reports=[]
    for station in GEO_SITES:
        report={"site":station,"provider":"GeoSphere Austria",
                "status":"NOT_QUALIFIED",
                "official_hourly_ff_semantics":"vectorial hourly speed mean",
                "ten_minute_aggregation_source_semantics":"PENDING_INDEPENDENT_SOURCE_PROOF",
                "original_hourly_vs_10minute_equivalence_proven":False}
        try:
            ten,provenance=geo_tenminute_source(station,meta)
            h,hsha=geo_hourly_source(station)
            rows=matched_hourly(ten,h,str(station))
            report.update(summarize(rows,"GeoSphere original ff vectorial hourly mean m/s"))
            report.update(provenance)
            report["hourly_original_sha256"]=hsha
            report["status"]="RESEARCH_NUMERICAL_RECONSTRUCTION_PASS"
        except Exception as exc:
            report["status"]="SOURCE_OR_QC_BLOCKED"
            report["blocker"]=type(exc).__name__+": "+str(exc)[:230]
        reports.append(report)
    return {"station_records":reports,"n_stations":len(reports),
            "accepted_site_count":sum(r["status"]=="RESEARCH_NUMERICAL_RECONSTRUCTION_PASS" for r in reports),
            "source_10min_dataset":"klima-v2-10min",
            "global_hourly_equivalence_not_yet_proven":True}


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--out",required=True)
    args=cli.parse_args()
    swiss=swiss_source_audit()
    geo=geosphere_source_audit()
    result={
        "stage":"P8.4A2","status":"ORIGINAL_TEN_MINUTE_TO_HOURLY_RESEARCH_AUDIT_EXECUTED",
        "sites_swiss":swiss,"sites_geosphere":geo,
        "swiss_scalar_hour_reconstructed":True,
        "swiss_official_direction_operator_identified":False,
        "geosphere_official_10min_operator_proven":False,
        "era5_hourly_is_instantaneous_not_source_equivalent_mean":True,
        "era5_equivalent_temporal_support_proven":False,
        "wind_anemometer_height_roughness_verified":False,
        "a_complete":False,"b_complete":False,"c_complete":False,"d_complete":False,
        "production_epw_ready":False,
        "original_hourly_and_tenminute_rows_published":False,
    }
    p=Path(args.out)
    p.mkdir(parents=True,exist_ok=True)
    (p/"ige_p8_4a2_temporal_aggregation_aggregates.json").write_text(
        json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("IGE_P8_4A2",json.dumps({
        "status":result["status"],
        "swiss_sites":len(swiss["stations"]),
        "geo_site_supported":geo["accepted_site_count"],
        "swiss_speed_mae":{x["station"]:x["scalar_speed_error_mps"]["mae"] for x in swiss["stations"]},
        "era5_temporal_support_equivalent":False
    },sort_keys=True),flush=True)


if __name__=="__main__":
    main()
