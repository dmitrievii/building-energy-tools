#!/usr/bin/env python3
"""IGE P8.4A1 — original-source wind time/aggregation and QC evidence, research only.

A1 documents *different* temporal support; numeric ±1 h checks are sensitivity,
NOT a time-shift selector, resampling fix or proof of station clock semantics.
All original provider hourly data remains ephemeral in CI.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import statistics
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from p8_1e_swiss_external import fetch, parse_meta
from p8_2e_crossyear import ROOT
from p8_3a_wind_spatial import CALM_MPS, circular_error_deg, usable_wind, wind_from_to_uv
from p8_3e_h_wind_source_screens import decode_wind_parameter_metadata
from p8_3e1_f1_wind_qualification import station_year
from p7b5_wind_coherence import BASE as GEO_BASE, QC as GEO_QC

YEAR, MONTH = 2024, 1
SWISS = ("BAS", "GRA", "MUB")
GEO_STATION = 30
HOURS = 31*24
SHIFTS = (-1,0,1)
OFFICIAL_DOCUMENTS = {
    "meteoswiss_station": "https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations",
    "geosphere_hourly": "https://data.hub.geosphere.at/en/dataset/klima-v2-1h",
    "ecmwf_validity": "https://confluence.ecmwf.int/pages/viewpage.action?pageId=111151514",
    "openmeteo_hourly": "https://open-meteo.com/en/docs/historical-weather-api",
}


def read_json(url, cap=14_000_000, retries=3):
    """Bounded, strict fetch with identical source bytes digested for provenance."""
    errors=[]
    for k in range(retries):
        try:
            if not url.startswith("https://"):
                raise ValueError("A1_REFUSE_INSECURE_SOURCE")
            with urlopen(Request(url,headers={
                    "User-Agent":"IGE-P8.4A1-source-physical-closure-research",
                    "Accept":"application/json",
            }),timeout=125) as f:
                if f.status!=200:
                    raise ValueError("A1_HTTP_NON_200")
                raw=f.read(cap+1)
            if not raw or len(raw)>cap:
                raise ValueError("A1_SOURCE_EMPTY_OR_OVERSIZE")
            return json.loads(raw),hashlib.sha256(raw).hexdigest()
        except Exception as exc:
            errors.append(type(exc).__name__+": "+str(exc)[:130])
            if k+1<retries:
                time.sleep(k+1)
    raise RuntimeError("A1_SOURCE_UNAVAILABLE "+url.split("?")[0]+" :: "+str(errors))


def january_hours():
    begin=dt.datetime(YEAR,MONTH,1)
    return tuple(begin+dt.timedelta(hours=h) for h in range(HOURS))


def swiss_post2018_hourly_reference_stamps(timestamp):
    """Six 10-min end stamps forming MeteoSwiss h reference time, 2018+.

    Official: https://opendatadocs.meteoswiss.ch/general/download
    Example hourly 16:00 UTC -> 15:10,15:20,...,16:00.
    Pre-2018 SYNOP window is different and deliberately not normalized.
    """
    if not isinstance(timestamp,dt.datetime) or timestamp.tzinfo is not None:
        raise ValueError("A1_SWISS_EXPECT_UTC_NAIVE_REFERENCE_TIMESTAMP")
    if timestamp.year < 2018:
        raise ValueError("A1_SWISS_PRE2018_SYNOPTIC_INTERVAL_DIFFERENT")
    if timestamp.minute!=0 or timestamp.second or timestamp.microsecond:
        raise ValueError("A1_SWISS_HOURLY_REFERENCE_NOT_ON_HOUR")
    return tuple(timestamp-dt.timedelta(minutes=50-10*i) for i in range(6))


def normalize_era5_january(payload):
    """Strict 744h GMT axis; source is an Open-Meteo ERA5 *gateway* output."""
    units=payload.get("hourly_units") or {}
    if units.get("wind_speed_10m")!="m/s" or units.get("wind_direction_10m") not in ("°","degrees","degree"):
        raise ValueError("A1_ERA5_GATEWAY_UNIT_CHANGED")
    if payload.get("utc_offset_seconds")!=0 or payload.get("timezone") not in ("GMT","UTC"):
        raise ValueError("A1_ERA5_NOT_GMT")
    hourly=payload.get("hourly") or {}
    arr=[hourly.get(k) for k in ("time","wind_speed_10m","wind_direction_10m")]
    if any(not isinstance(v,list) or len(v)!=HOURS for v in arr):
        raise ValueError("A1_ERA5_GATEWAY_744_HOURS_REQUIRED")
    output={}
    for expected,(stamp,speed,direction) in zip(january_hours(),zip(*arr)):
        try:
            actual=dt.datetime.fromisoformat(stamp)
        except (TypeError,ValueError) as exc:
            raise ValueError("A1_BAD_ERA5_TIMESTAMP") from exc
        if actual!=expected:
            raise ValueError("A1_ERA5_DUPLICATE_GAP_OR_TIMEZONE_SHIFT")
        if (isinstance(speed,(int,float)) and isinstance(direction,(int,float))
                and math.isfinite(speed) and math.isfinite(direction)
                and 0<=speed<=90 and 0<=direction<=360):
            output[expected]={"speed":float(speed),"direction":float(direction)%360}
    if len(output)<.95*HOURS:
        raise ValueError("A1_ERA5_UNACCEPTABLY_SPARSE")
    grid={}
    for key in ("latitude","longitude","elevation","generationtime_ms"):
        value=payload.get(key)
        if value is not None and (not isinstance(value,(int,float)) or not math.isfinite(value)):
            raise ValueError("A1_ERA5_INVALID_GRID_METADATA")
        grid[key]=value
    if any(grid[k] is None for k in ("latitude","longitude","elevation")):
        raise ValueError("A1_ERA5_GRID_PROVENANCE_ABSENT")
    return output,grid


def common_clock_sensitivity(observations,background):
    """Predeclared shifts share *exactly* the same 742 interior hours."""
    stamps=january_hours()[1:-1]
    report={}
    for shift in SHIFTS:
        delta=dt.timedelta(hours=shift)
        speed_errors=[]; vector_losses=[]; angular=[]
        target_hours=0
        for t in stamps:
            observed=observations.get(t)
            era=background.get(t+delta)
            if not (usable_wind(observed) and usable_wind(era)):
                continue
            target_hours+=1
            speed_errors.append(era["speed"]-observed["speed"])
            if observed["speed"]>=CALM_MPS and era["speed"]>=CALM_MPS:
                angular.append(circular_error_deg(
                    era.get("direction"),observed.get("direction")))
                ou,ov=wind_from_to_uv(observed["speed"],observed["direction"])
                eu,ev=wind_from_to_uv(era["speed"],era["direction"])
                vector_losses.append((eu-ou)**2+(ev-ov)**2)
        if target_hours<700:
            raise ValueError("A1_INSUFFICIENT_SWISS_ERA5_CLOCK_PAIRS")
        report[str(shift)]={
            "label":{ -1:"ERA5_PREVIOUS_HOUR",0:"SAME_TIMESTAMP",1:"ERA5_NEXT_HOUR"}[shift],
            "n_speed_pairs":target_hours,
            "n_vector_direction_pairs":len(vector_losses),
            "scalar_speed_mae_mps":statistics.mean(abs(x) for x in speed_errors),
            "scalar_speed_bias_mps":statistics.mean(speed_errors),
            "direction_mae_deg_on_both_noncalm":statistics.mean(angular) if angular else None,
            "vector_east_north_rmse_mps":math.sqrt(statistics.mean(vector_losses)) if vector_losses else None,
        }
    # Ensure that apparent alignment differences do not come from changing N.
    if len(set(x["n_speed_pairs"] for x in report.values()))!=1:
        raise ValueError("A1_CLOCK_COMPARISON_DENOMINATOR_CHANGED")
    return report


def swiss_hourly():
    meta,meta_hash=fetch(ROOT+"/ogd-smn_meta_stations.csv",max_bytes=1_500_000)
    stations,_=parse_meta(meta)
    params,param_sha=fetch(ROOT+"/ogd-smn_meta_parameters.csv",max_bytes=3_000_000)
    matched,codec=decode_wind_parameter_metadata(params)
    if not all(any(field in " ".join(str(v) for v in r.values()).lower()
                       for r in matched) for field in ("fkl010h0","dkl010h0")):
        raise ValueError("A1_REQUIRED_OFFICIAL_WIND_PARAMETER_NOT_FOUND")
    result=[]
    for site in SWISS:
        wx,station_sha=station_year(site,YEAR)
        january={t:row for t,row in wx.items() if t in set(january_hours())}
        if len(january)<.95*HOURS:
            raise ValueError("A1_SWISS_JANUARY_AXIS_INCOMPLETE_"+site)
        if sum(usable_wind(r) for r in january.values())<.95*HOURS:
            raise ValueError("A1_SWISS_JANUARY_WIND_COVERAGE_"+site)
        if site not in stations:
            raise ValueError("A1_SWISS_STATION_IDENTITY_MISSING")
        station=stations[site]
        args={
            "latitude":station["lat"],"longitude":station["lon"],
            "start_date":"2024-01-01","end_date":"2024-01-31",
            "hourly":"wind_speed_10m,wind_direction_10m",
            "models":"era5","wind_speed_unit":"ms","timezone":"GMT",
        }
        obj,sha=read_json("https://archive-api.open-meteo.com/v1/archive?"+urlencode(args))
        grid,position=normalize_era5_january(obj)
        report=common_clock_sensitivity(january,grid)
        result.append({
            "site":site,"station_lat":station["lat"],"station_lon":station["lon"],
            "station_elevation_masl":station["hoehe_m"],
            "station_original_sha256":station_sha,
            "era5_gateway_response_sha256":sha,
            "gateway_request_model":"era5",
            "gateway_grid_cell_metadata":position,
            "gateway_elevation_downscaling_status":"UNVERIFIED_DEFAULT_ADJUSTMENT",
            "nominal_hour_difference_hypotheses":report,
            "clock_hypothesis_selected":None,
            "identical_temporal_support_proven":False,
        })
    return {
        "station_metadata_sha256":meta_hash,
        "wind_parameter_metadata_sha256":param_sha,
        "wind_parameter_metadata_encoding":codec,
        "matched_original_parameter_metadata":matched,
        "sampling_year":YEAR,"month":MONTH,
        "source_time_basis":"UTC",
        "swiss_h_hourly_reference_is_end_of_aggregation_interval":True,
        "swiss_post2018_official_aggregation_reference_10min_stamps":["15:10","15:20","15:30","15:40","15:50","16:00"],
        "swiss_post2018_reference_example_utc":"16:00",
        "swiss_pre2018_synop_reference_interval_different":True,
        "swiss_interval_reference_source":"https://opendatadocs.meteoswiss.ch/general/download",
        "observation_measurement":"Swiss original scalar hourly mean speed and hourly mean wind direction",
        "model_measurement":"ERA5 10m model instantaneous valid-time output via Open-Meteo",
        "comparison_shared_interior_hours":HOURS-2,
        "sites":result,
        "swiss_individual_observation_qc":"NOT_VERIFIED",
    }


def geo_metadata_audit(source):
    """Check original QC coding; do not mistake generic 1h metadata for ff/dd semantics."""
    params={p["name"]:p for p in source.get("parameters",[])
            if isinstance(p,dict) and isinstance(p.get("name"),str)}
    for key in ("ff","ff_flag","dd","dd_flag"):
        if key not in params:
            raise ValueError("A1_GEO_WIND_PARAMETER_MISSING_"+key)
    def unit(key):
        return str(params[key].get("unit") or "")
    if unit("ff")!="m/s" or unit("dd") not in ("°","deg","degrees"):
        raise ValueError("A1_GEO_WIND_UNIT_DRIFT")
    station={int(s["id"]):s for s in source.get("stations",[])
             if isinstance(s,dict) and s.get("id") is not None}
    if GEO_STATION not in station:
        raise ValueError("A1_GEO_STATION_30_MISSING")
    list_q21=source.get("code_lists",{}).get("q21",[])
    legend={int(q["key"]):str(q.get("value","")) for q in list_q21
            if isinstance(q,dict) and q.get("key") is not None}
    if not GEO_QC.issubset(legend) or 0 not in legend:
        raise ValueError("A1_GEO_Q21_CODES_UNAVAILABLE")
    if "ungeprüft" not in legend[0].lower():
        raise ValueError("A1_GEO_UNVERIFIED_QC_SEMANTIC_CHANGED")
    columns={}
    for k in ("ff","dd"):
        p=params[k]
        columns[k]={"units":p.get("unit"),
                    "source_parameter_metadata":{name:value for name,value in p.items()
                         if name in ("name","unit","desc","description","time","aggregation","long_name")},
                    "has_source_quality_flag":True}
    return {"station_id":GEO_STATION,"station_name":station[GEO_STATION].get("name"),
            "parameter_definitions":columns,"qc_flag_legend":legend,
            "unknown_flag_codes_accepted":False,
            "hourly_interval_semantics_verification":"FIELD_SPECIFIC_PENDING"}


def geosphere_january():
    raw,metasha=read_json(GEO_BASE+"/metadata",cap=10_000_000)
    meta=geo_metadata_audit(raw)
    args={
        "parameters":"ff,ff_flag,dd,dd_flag","station_ids":str(GEO_STATION),
        "start":"2024-01-01T00:00","end":"2024-01-31T23:00",
        "output_format":"geojson",
    }
    obj,sha=read_json(GEO_BASE+"?"+urlencode(args),cap=10_000_000)
    timestamps=obj.get("timestamps")
    if not isinstance(timestamps,list) or len(timestamps)!=HOURS:
        raise ValueError("A1_GEO_744_HOUR_AXIS_REQUIRED")
    for stamp,expected in zip(timestamps,january_hours()):
        try:
            timestamp=dt.datetime.fromisoformat(str(stamp).replace("Z","+00:00"))
        except (ValueError,TypeError) as exc:
            raise ValueError("A1_GEO_INVALID_UTC_TIMESTAMP") from exc
        if timestamp.utcoffset()!=dt.timedelta(0) or timestamp.replace(tzinfo=None)!=expected:
            raise ValueError("A1_GEO_BAD_UTC_AXIS")
    features=obj.get("features") or []
    if len(features)!=1:
        raise ValueError("A1_GEO_AMBIGUOUS_STATION")
    properties=features[0].get("properties") or {}
    identity=properties.get("station")
    sid=int(identity.get("id") if isinstance(identity,dict) else identity)
    if sid!=GEO_STATION:
        raise ValueError("A1_GEO_STATION_IDENTITY_DRIFT")
    pars=properties.get("parameters") or {}
    for k in ("ff","ff_flag","dd","dd_flag"):
        if len((pars.get(k) or {}).get("data") or [])!=HOURS:
            raise ValueError("A1_GEO_BAD_HOURLY_PARAMETER_"+k)
    for k in ("ff","dd"):
        if pars[k].get("unit")!=meta["parameter_definitions"][k]["units"]:
            raise ValueError("A1_GEO_PARAMETER_UNIT_MISMATCH")
    counts={k:collections.Counter() for k in ("ff","dd")}
    valid={k:0 for k in counts}
    joint_valid=0
    calm=0
    for i in range(HOURS):
        approved={}
        for k in ("ff","dd"):
            value=pars[k]["data"][i]
            flag=pars[k+"_flag"]["data"][i]
            try:
                code=int(flag) if flag is not None else None
            except (ValueError,TypeError):
                code=None
            counts[k][str(code)]+=1
            if code not in meta["qc_flag_legend"] and code is not None:
                raise ValueError("A1_GEO_UNKNOWN_QUALITY_FLAG_"+str(code))
            number=isinstance(value,(int,float)) and math.isfinite(value)
            physical=(0<=value<=60 if k=="ff" else 0<=value<=360) if number else False
            approved[k]=code in GEO_QC and physical
            if approved[k]:
                valid[k]+=1
        if approved["ff"] and approved["dd"]:
            joint_valid+=1
        if approved["ff"] and pars["ff"]["data"][i]<CALM_MPS:
            calm+=1
    # Audit evidence must survive a FAILED QC coverage gate. The 85% threshold
    # stays immutable; a source-inadequate station blocks physical promotion,
    # not the preservation of original provider flag distributions.
    qc_coverage_qualified = valid["ff"]>=.85*HOURS
    meta.update({
        "dataset":"klima-v2-1h","year":YEAR,"month":MONTH,
        "metadata_sha256":metasha,"original_data_sha256":sha,
        "expected_UTC_hours":HOURS,
        "quality_flag_counts":{k:dict(c) for k,c in counts.items()},
        "approved_flag_codes":sorted(GEO_QC),
        "n_qc_approved_speed":valid["ff"],
        "wind_speed_qc_coverage_fraction":valid["ff"]/HOURS,
        "wind_speed_qc_qualification_minimum_fraction":.85,
        "wind_speed_qc_coverage_gate_passed":qc_coverage_qualified,
        "physical_qc_usage_authorized":qc_coverage_qualified,
        "qc_coverage_failure_reason":None if qc_coverage_qualified else "A1_GEO_TOO_FEW_QC_APPROVED_SPEED_HOURS",
        "n_qc_approved_direction":valid["dd"],
        "n_qc_approved_both":joint_valid,
        "n_qc_approved_calm_hours":calm,
        "record_start_or_end":"NOT_PROVEN",
        "coordinate_height_instrument":"NOT_EXTRACTED_AS_VALIDATED_MAST_HEIGHT",
    })
    return meta


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--out",required=True)
    args=cli.parse_args()
    swiss=swiss_hourly()
    geo=geosphere_january()
    summary={
        "phase":"IGE_P8_4A1","status":("ORIGINAL_SOURCE_SEMANTICS_AND_QC_PILOT_COMPLETED"
                 if geo["wind_speed_qc_coverage_gate_passed"]
                 else "ORIGINAL_SOURCE_QC_CENSUS_COMPLETED__GEO_WIND_GATE_BLOCKED"),
        "sources":OFFICIAL_DOCUMENTS,
        "swiss_vs_era5":swiss,"geosphere":geo,
        "hourly_temporal_support_identical":False,
        "time_shift_identified_as_correct":False,
        "anemometer_height_and_roughness_qualified":False,
        "source_semantics_validated_partial":True,
        "geosphere_wind_original_qc_gate_passed":geo["wind_speed_qc_coverage_gate_passed"],
        "a_physical_closure_complete":False,
        "b_historical_spatial_reconstruction_complete":False,
        "c_future_synthesis_complete":False,
        "d_epw_integrated_validation_complete":False,
        "production_epw_ready":False,
        "original_hourly_data_exported":False,
    }
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    (out/"ige_p8_4a1_source_semantics_aggregates.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")
    print("IGE_P8_4A1",json.dumps({
        "status":summary["status"],"swiss_sites":len(swiss["sites"]),
        "geosphere_qc_hour_count":geo["n_qc_approved_speed"],
        "geosphere_qc_gate_passed":geo["wind_speed_qc_coverage_gate_passed"],
        "geosphere_flag_counts":geo["quality_flag_counts"],
        "physical_closure":False,
    }),flush=True)


if __name__=="__main__":
    main()
