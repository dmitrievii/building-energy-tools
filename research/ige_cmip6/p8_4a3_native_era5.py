#!/usr/bin/env python3
"""IGE P8.4A3: native ERA5 u/v vs Open-Meteo gateway, January 2024, research.

Modes are separate for source independence: gateway (full month), arco (4
timestamps independent Google ARCO regridded ERA5 grid). Original source
records remain in ephemeral CI RAM; only aggregate measures are exported.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path
from urllib.parse import urlencode

from p8_1e_swiss_external import fetch,parse_meta,haversine
from p8_2e_crossyear import ROOT
from p8_3a_wind_spatial import CALM_MPS,circular_error_deg,usable_wind,wind_from_to_uv
from p8_3e1_f1_wind_qualification import station_year
from p8_4a1_source_semantics import (
    YEAR,MONTH,SWISS,january_hours,normalize_era5_january,read_json,
)

ARCO_URL="gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
ARCO_COMPONENTS=("10m_u_component_of_wind","10m_v_component_of_wind")
ARCO_UTC_HOURS=("2024-01-15T00:00:00","2024-01-15T06:00:00",
                "2024-01-15T12:00:00","2024-01-15T18:00:00")
MODES=("default_terrain","nearest_no_downscaling")
MIN_HOURS=700


def meteorological_from_uv(u,v):
    if not all(math.isfinite(x) for x in (u,v)):
        raise ValueError("A3_INVALID_VECTOR")
    speed=math.hypot(u,v)
    if speed<CALM_MPS:
        return {"speed":speed,"direction":None}
    angle=math.degrees(math.atan2(-u,-v))%360.
    if math.isclose(angle,360.,abs_tol=1e-9):
        angle=0.
    return {"speed":speed,"direction":angle}


def uv_from_wind(row):
    if row is None:
        return None
    s=row.get("speed")
    if s is None or not math.isfinite(s) or s<0:
        return None
    if s<CALM_MPS:
        return (0.,0.)  # calm vector as stated QC convention
    d=row.get("direction")
    if d is None or not math.isfinite(d):
        return None
    return wind_from_to_uv(s,d)


def endpoint_proxies(previous,current):
    """Only two-point time quadrature proxies, not real subhourly ERA5 means."""
    if not all(usable_wind(row) for row in (previous,current)):
        return None
    a=uv_from_wind(previous);b=uv_from_wind(current)
    if a is None or b is None:
        return None
    scalar=.5*(previous["speed"]+current["speed"])
    u=.5*(a[0]+b[0]);v=.5*(a[1]+b[1])
    vector=meteorological_from_uv(u,v)
    if vector["speed"]>scalar+1e-10:
        raise AssertionError("A3_TRIANGLE_INEQUALITY")
    return {"endpoint_scalar":scalar,"endpoint_vector":vector["speed"],
            "endpoint_vector_direction":vector["direction"],
            "original_valid_time":"instantaneous_two_endpoint_proxy_NOT_hourly_mean"}


def signed_clock_metrics(paired,method):
    errors=[(p[method]["speed"]-p["reference"]["speed"]) for p in paired]
    if not errors:
        raise ValueError("A3_EMPTY_SCORE")
    dirs=[
        circular_error_deg(p[method]["direction"],p["reference"]["direction"])
        for p in paired if (p["reference"]["speed"]>=CALM_MPS
                            and p[method]["speed"]>=CALM_MPS
                            and p["reference"]["direction"] is not None
                            and p[method]["direction"] is not None)
    ]
    n_ref=sum(p["reference"]["speed"]>=CALM_MPS
              and p["reference"].get("direction") is not None for p in paired)
    return {
        "n_speed_pairs":len(errors),
        "mae_mps":statistics.mean(map(abs,errors)),
        "rmse_mps":math.sqrt(statistics.mean(x*x for x in errors)),
        "bias_mps":statistics.mean(errors),
        "direction_paired_noncalm_n":len(dirs),
        "direction_conditional_mae_deg":statistics.mean(dirs) if dirs else None,
        "direction_coverage_reference_noncalm":len(dirs)/n_ref if n_ref else None,
    }


def gateway_params(station,mode):
    if mode not in MODES:
        raise ValueError("A3_UNKNOWN_GATEWAY_MODE")
    p={
        "latitude":station["lat"],"longitude":station["lon"],
        "start_date":"2024-01-01","end_date":"2024-01-31",
        "hourly":"wind_speed_10m,wind_direction_10m",
        "models":"era5","wind_speed_unit":"ms","timezone":"GMT",
    }
    if mode=="nearest_no_downscaling":
        p.update({"cell_selection":"nearest","elevation":"nan"})
    return p


def one_gateway(station,mode):
    query=gateway_params(station,mode)
    src="https://archive-api.open-meteo.com/v1/archive?"+urlencode(query)
    obj,sha=read_json(src)
    hourly,meta=normalize_era5_january(obj)
    if len(hourly)!=744:
        raise ValueError("A3_GATEWAY_MISSING_HOURS")
    if mode=="nearest_no_downscaling" and (
        query["cell_selection"]!="nearest" or query["elevation"]!="nan"):
        raise AssertionError("A3_GATEWAY_CONTROL_IS_NOT_RAW_CONTROL")
    meta["reported_elevation_m_is_validated_era5_geopotential"]=False
    meta["setting"]=mode
    meta["model"]="era5"
    return hourly,meta,sha


def paired_gateway_metrics(observed,predictions):
    """All methods share strictly identical reference and model UTC hour indices."""
    common=[
        t for t in january_hours()
        if usable_wind(observed.get(t))
        and all(usable_wind(predictions[name].get(t)) for name in MODES)
    ]
    if len(common)<MIN_HOURS:
        raise ValueError("A3_INSUFFICIENT_GATEWAY_COMMON_HOURS")
    paired=[
        {"reference":observed[t],
         **{mode:predictions[mode][t] for mode in MODES}}
        for t in common
    ]
    compare={m:signed_clock_metrics(paired,m) for m in MODES}
    interior=[t for t in common if t.hour!=0 or t.day!=1]
    # Endpoint t-1 must exist in same January sequence; not merely adjacent in
    # compressed usable array, and not a shift optimizing model skill.
    end_times=[
        t for t in interior
        if all(usable_wind(predictions[m].get(t-dt.timedelta(hours=1)))
               for m in MODES)
    ]
    if len(end_times)<MIN_HOURS-1:
        raise ValueError("A3_INSUFFICIENT_ENDPOINT_PROXY_HOURS")
    endpoints={}
    for mode in MODES:
        scores=[]
        for t in end_times:
            p=endpoint_proxies(predictions[mode][t-dt.timedelta(hours=1)],
                               predictions[mode][t])
            if p is None:
                raise ValueError("A3_ENDPOINT_VECTOR_UNRESOLVED")
            scores.append({
                "reference":observed[t],
                "instantaneous":predictions[mode][t],
                "trap_scalar":{"speed":p["endpoint_scalar"],
                               "direction":p["endpoint_vector_direction"]},
                "trap_vector":{"speed":p["endpoint_vector"],
                               "direction":p["endpoint_vector_direction"]},
            })
        endpoints[mode]={
            k:signed_clock_metrics(scores,k) for k in
            ("instantaneous","trap_scalar","trap_vector")
        }
        endpoints[mode]["n_strict_same_interior_UTC_hours"]=len(end_times)
        endpoints[mode]["meaning"]="TWO_ENDPOINT_QUADRATURE_PROXY_NOT_PROVEN_HOURLY_MEAN"
    return {"n_common_744h_baseline":len(common),
            "gateway_modes_same_reference_hours":compare,
            "two_endpoint_quadrature_sensitivity":endpoints,
            "no_clock_shift_selected":True}


def gateway_audit():
    raw,meta_sha=fetch(ROOT+"/ogd-smn_meta_stations.csv",max_bytes=1_500_000)
    stations,_=parse_meta(raw)
    out=[]
    for sid in SWISS:
        target=stations[sid]
        reference,reference_sha=station_year(sid,YEAR)
        preds,metadata,gateway_sha={},{},{}
        for mode in MODES:
            data,meta,sha=one_gateway(target,mode)
            preds[mode]=data
            metadata[mode]=meta
            gateway_sha[mode]=sha
        metrics=paired_gateway_metrics(reference,preds)
        grid_details={}
        for m,meta in metadata.items():
            grid_details[m]={
                **meta,
                "returned_center_offset_km_from_station":haversine(
                    target["lat"],target["lon"],meta["latitude"],meta["longitude"]),
            }
        out.append({"site":sid,
                    "station_reference_sha256":reference_sha,
                    "requested_WGS84_latlon":[target["lat"],target["lon"]],
                    "ground_elevation_masl":target["hoehe_m"],
                    "gateway_original_response_sha256":gateway_sha,
                    "gateway_grid":grid_details,
                    "metrics":metrics})
    return {
        "stage":"P8.4A3_gateway",
        "status":"ORIGINAL_ERA5_GATEWAY_SENSITIVITY_COMPLETED",
        "source_metadata_sha256":meta_sha,
        "requested_year":YEAR,"month":MONTH,
        "sites":out,"n_sites":len(out),
        "gateway_can_be_claimed_native_ECMWF":False,
        "era5_is_instantaneous_valid_time":True,
        "two_point_proxy_is_hourly_mean":False,
        "station_is_scalar_hourly_mean":True,
        "source_temporal_support_equivalent":False,
        "production_epw_ready":False,
        "original_hourly_arrays_exported":False,
    }


def angular_longitude(a,b):
    return abs(((float(a)-float(b)+180.)%360.)-180.)


def same_regular_grid_cell(native,gw,tol=.025):
    return (abs(native["latitude"]-gw["latitude"])<=tol
            and angular_longitude(native["longitude"],gw["longitude"])<=tol)


def independent_arco_audit():
    """Public independent ERA5 actual vector *fields* on 0.25-degree ARCO grid.

    The stored archive is regridded 0.25°, not the original T639 native model
    horizontal grid. Four sampled UTC times intentionally bound remote cost.
    """
    import xarray as xr
    ds=xr.open_zarr(
        ARCO_URL,chunks=None,
        storage_options={"token":"anon"},
        consolidated=True,
    )
    try:
        for v in ARCO_COMPONENTS:
            if v not in ds:
                raise ValueError("A3_ARCO_MISSING_ERA5_NATIVE_UV_"+v)
            unit=str(ds[v].attrs.get("units","")).replace(" ","").lower()
            if unit not in ("ms**-1","ms-1","m/s","ms^-1"):
                raise ValueError("A3_ARCO_WRONG_WIND_VECTOR_UNITS_"+unit)
        time_values=[dt.datetime.fromisoformat(s) for s in ARCO_UTC_HOURS]
        before=ds.attrs.get("valid_time_start")
        after=ds.attrs.get("valid_time_stop")
        if before is None or after is None:
            raise ValueError("A3_ARCO_VALIDITY_METADATA_MISSING")
        station_blob,station_sha=fetch(ROOT+"/ogd-smn_meta_stations.csv",max_bytes=1_500_000)
        stations,_=parse_meta(station_blob)
        results=[]
        for site in SWISS:
            target=stations[site]
            gw, gwcell,gw_sha=one_gateway(target,"nearest_no_downscaling")
            values=[]
            selected_grid=None
            for when in time_values:
                sample={}
                for component,name in zip(ARCO_COMPONENTS,("u","v")):
                    point=ds[component].sel(
                        time=when,latitude=target["lat"],
                        longitude=target["lon"],method="nearest")
                    lat=float(point["latitude"].values)
                    lon=float(point["longitude"].values)
                    if selected_grid is None:
                        selected_grid={"latitude":lat,"longitude":lon}
                    if (abs(lat-selected_grid["latitude"])>1e-9
                            or angular_longitude(lon,selected_grid["longitude"])>1e-9):
                        raise ValueError("A3_ARCO_CHANGED_CELL")
                    sample[name]=float(point.values)
                if not all(math.isfinite(v) for v in sample.values()):
                    raise ValueError("A3_ARCO_NONFINITE_NATIVE_VECTOR")
                modeled=meteorological_from_uv(sample["u"],sample["v"])
                t=when
                predicted=gw.get(t)
                if not usable_wind(predicted):
                    raise ValueError("A3_GATEWAY_MISSING_NATIVE_SAMPLE_TIME")
                values.append({"native_vector":sample,"native_wind":modeled,
                               "gateway":predicted})
            if selected_grid is None:
                raise ValueError("A3_ARCO_NO_SELECTED_GRID")
            identical=same_regular_grid_cell(selected_grid,gwcell)
            statistics_out=None
            if identical:
                u_diff=[];v_diff=[];s_diff=[];dir_diff=[]
                for row in values:
                    gx=uv_from_wind(row["gateway"])
                    if gx is None:
                        raise ValueError("A3_GATEWAY_UV_UNDEFINED")
                    u_diff.append(gx[0]-row["native_vector"]["u"])
                    v_diff.append(gx[1]-row["native_vector"]["v"])
                    s_diff.append(row["gateway"]["speed"]-row["native_wind"]["speed"])
                    da=row["native_wind"]["direction"]
                    db=row["gateway"]["direction"]
                    if da is not None and db is not None:
                        dir_diff.append(circular_error_deg(da,db))
                statistics_out={
                    "native_gateway_u_rmse_mps":math.sqrt(statistics.mean(x*x for x in u_diff)),
                    "native_gateway_v_rmse_mps":math.sqrt(statistics.mean(x*x for x in v_diff)),
                    "native_gateway_speed_mae_mps":statistics.mean(abs(x) for x in s_diff),
                    "native_gateway_direction_mae_deg":statistics.mean(dir_diff) if dir_diff else None,
                    "n_same_cell_original_points":len(values),
                }
            results.append({
                "site":site,
                "native_ARCO_025deg_cell_center":selected_grid,
                "gateway_selected_cell_center":{
                    "latitude":gwcell["latitude"],"longitude":gwcell["longitude"]},
                "both_sources_same_cell_center":identical,
                "no_cross_grid_skill_claim":not identical,
                "original_sampled_hour_count":len(values),
                "native_to_gateway_differences_if_same_grid":statistics_out,
                "gateway_control_original_sha256":gw_sha,
            })
        return {
            "stage":"P8.4A3_independent_ARCO",
            "status":"INDEPENDENT_ARCO_ERA5_COMPONENT_SPOTCHECK_EXECUTED",
            "arco_data_kind":"original_ERA5_uv_fields_REGRIDDED_025deg_NOT_native_T639",
            "original_ARCO_path":ARCO_URL,
            "source_valid_time_start":str(before),
            "source_valid_time_stop":str(after),
            "data_source_station_metadata_sha256":station_sha,
            "sample_hours_UTC":list(ARCO_UTC_HOURS),
            "sites":results,
            "n_same_cell_sites":sum(x["both_sources_same_cell_center"] for x in results),
            "original_ARCO_components_exported":False,
            "no_full_month_native_validation":True,
            "temporal_equivalence_to_hourly_station_mean":False,
            "production_epw_ready":False,
        }
    finally:
        ds.close()


def write_artifact(out,name,result):
    p=Path(out);p.mkdir(parents=True,exist_ok=True)
    (p/name).write_text(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")


def main():
    a=argparse.ArgumentParser()
    a.add_argument("--mode",required=True,choices=("gateway","arco"))
    a.add_argument("--out",required=True)
    arg=a.parse_args()
    if arg.mode=="gateway":
        result=gateway_audit()
        write_artifact(arg.out,"p8_4a3_gateway_era5_2024_aggregates.json",result)
        print("IGE_P8_4A3_GATEWAY",json.dumps({
            "status":result["status"],"sites":len(result["sites"]),
            "native_ARCO_validated":False,"production_epw_ready":False}),flush=True)
    else:
        try:
            result=independent_arco_audit()
        except Exception as exc:
            # Source incompatibility is a scientifically important result. Do
            # not conceal it or substitute the Open-Meteo gateway as "native".
            result={
                "stage":"P8.4A3_independent_ARCO",
                "status":"INDEPENDENT_ARCO_NATIVE_COMPONENT_SPOTCHECK_BLOCKED",
                "blocker_kind":type(exc).__name__,
                "blocker_message":str(exc)[:400],
                "arco_dataset":ARCO_URL,
                "independent_component_values_validated":False,
                "source_temporal_equivalence_proven":False,
                "production_epw_ready":False,
                "source_original_data_exported":False,
            }
        write_artifact(arg.out,"p8_4a3_arco_native_components_2024_aggregates.json",result)
        print("IGE_P8_4A3_ARCO",json.dumps({
            "status":result["status"],"independent_component_values_validated":
            result["status"]=="INDEPENDENT_ARCO_ERA5_COMPONENT_SPOTCHECK_EXECUTED",
            "blocker":result.get("blocker_message")}),flush=True)


if __name__=="__main__":
    main()
