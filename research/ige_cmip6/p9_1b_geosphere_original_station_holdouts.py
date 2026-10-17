#!/usr/bin/env python3
"""P9.1B independent original GeoSphere Austria QC station x ERA5 grid holdout.

3 PREDECLARED sites, two seasons. Source: actual GeoSphere 1h QC station
observations vs untouched ERA5 model grid temperature via P9.1A. This is not
global validation and not a geometrically proven altitude adjustment.
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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import p9_1a_global_historical_backbone as era5

BASE="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h"
IDS=(30,39,196)
PERIODS=(("winter_2023","2023-01-10","2023-01-16"),
         ("summer_2023","2023-07-10","2023-07-16"))
GOOD_FLAGS=frozenset((10,11,12,20,21,22))
MIN_PAIRS=120
LIMIT_BYTES=14*1024*1024


def source_json(url):
    u=urllib.parse.urlsplit(url)
    if u.scheme!="https" or u.hostname!="dataset.api.hub.geosphere.at":
        raise ValueError("P9_1B_ORIGINAL_GEOSPHERE_HOST_NOT_ALLOWED")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                url,headers={"User-Agent":"IGE-P9.1B-independent-QC-station-holdout",
                             "Accept":"application/json"}),timeout=90) as fp:
                raw=fp.read(LIMIT_BYTES+1)
            if len(raw)>LIMIT_BYTES:raise ValueError("P9_1B_GEOSPHERE_TOO_LARGE")
            return json.loads(raw),hashlib.sha256(raw).hexdigest()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==3:raise
        except (urllib.error.URLError,ConnectionError,TimeoutError):
            if attempt==3:raise
        time.sleep(min(8,2**(attempt+1)))
    raise RuntimeError("P9_1B_GEOSPHERE_NO_SILENT_FALLBACK")


def extract_metadata(meta):
    all_stations={int(x["id"]):x for x in meta["stations"]}
    all_parameters={p["name"]:p for p in meta["parameters"]}
    if all_parameters.get("tl",{}).get("unit") not in ("°C","degC"):
        raise ValueError("P9_1B_TL_UNIT_OR_PARAMETER_MISSING")
    if "tl_flag" not in all_parameters:
        raise ValueError("P9_1B_QUALIFIED_TL_QC_FLAG_NOT_AVAILABLE")
    selected={}
    for station in IDS:
        if station not in all_stations:
            raise ValueError("P9_1B_REGISTERED_STATION_MISSING_"+str(station))
        s=all_stations[station]
        selected[station]={
            "id":station,"name":s.get("name"),
            "lat":float(s["lat"]),"lon":float(s["lon"]),
            "altitude_m":float(s["altitude"]),
        }
        if not (-90<=selected[station]["lat"]<=90
                and -180<=selected[station]["lon"]<=180
                and -500<=selected[station]["altitude_m"]<=6000):
            raise ValueError("P9_1B_STATION_METADATA_COORD_OR_ELEVATION")
    return selected


def decode_observed(obs,station_ids,start,end):
    first=dt.datetime.fromisoformat(start+"T00:00+00:00")
    n=((dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days+1)*24
    stamps=[]
    for item in obs.get("timestamps",[]):
        source=dt.datetime.fromisoformat(str(item).replace("Z","+00:00"))
        if source.utcoffset() is None:
            raise ValueError("P9_1B_NO_OBSERVED_UTC_OFFSET")
        stamps.append(source.astimezone(dt.timezone.utc))
    expected=[first+dt.timedelta(hours=i) for i in range(n)]
    if stamps!=expected:
        raise ValueError("P9_1B_OBSERVED_UTC_AXIS_GAP_SHIFT_OR_DUPLICATE")
    out={}
    for f in obs.get("features",[]):
        props=f["properties"];ss=props["station"]
        sid=int(ss["id"] if isinstance(ss,dict) else ss)
        if sid not in station_ids or sid in out:
            raise ValueError("P9_1B_UNREQUESTED_OR_DUPLICATED_STATION")
        params=props.get("parameters",{})
        item=params.get("tl");flag=params.get("tl_flag")
        if item is None or item.get("unit") not in ("°C","degC"):
            raise ValueError("P9_1B_SOURCE_TL_RECORD_MISSING")
        if flag is None or not isinstance(flag.get("data"),list):
            raise ValueError("P9_1B_NO_SOURCE_TEMPERATURE_QC")
        vals=item.get("data");flags=flag["data"]
        if len(vals)!=n or len(flags)!=n:
            raise ValueError("P9_1B_OBSERVED_TL_OR_QC_AXIS_INCOMPLETE")
        mapped={}
        for stamp,value,q in zip(stamps,vals,flags):
            if value is None or q not in GOOD_FLAGS:continue
            v=float(value)
            if not math.isfinite(v) or not -90<v<65:
                raise ValueError("P9_1B_ORIGINAL_OBSERVATION_OUT_OF_DOMAIN")
            mapped[stamp.strftime("%Y-%m-%dT%H:%M")]=v
        out[sid]=mapped
    if set(out)!=set(station_ids):
        raise ValueError("P9_1B_ORIGINAL_OBSERVED_STATION_INCOMPLETE")
    return out


def compare_era5_model_to_station(model,obs,minimum=MIN_PAIRS):
    times=model["hourly"]["time"];forecast=model["hourly"]["temperature_2m"]
    paired=[(float(v),obs[t]) for t,v in zip(times,forecast) if t in obs and v is not None]
    if len(paired)<minimum:
        raise ValueError("P9_1B_NOT_ENOUGH_REAL_QC_PAIRED_HOURS")
    errors=[v-u for v,u in paired]
    return {
        "QC_accepted_matched_hours":len(errors),
        "temperature_raw_grid_vs_station_MAE_C":statistics.fmean(map(abs,errors)),
        "temperature_raw_grid_vs_station_RMSE_C":math.sqrt(statistics.fmean(e*e for e in errors)),
        "temperature_raw_grid_vs_station_bias_C":statistics.fmean(errors),
        "fraction_model_warmer_than_station":sum(e>0 for e in errors)/len(errors),
        "independent_observed_reference_source":"GeoSphere Austria klima-v2-1h original QC tl",
        "no_target_station_values_used_in_prediction":True,
        "model_and_station_temporal_support_not_independently_equated":True,
        "lapse_orography_correction_applied":False,
    }


def run(out):
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    metadata,metasha=source_json(BASE+"/metadata")
    sites=extract_metadata(metadata)
    compiled=[];source=[]
    for season,start,end in PERIODS:
        params=urllib.parse.urlencode({
            "station_ids":",".join(str(s) for s in IDS),
            "parameters":"tl,tl_flag","start":start+"T00:00Z",
            "end":end+"T23:00Z","output_format":"geojson",
        })
        observed_url=BASE+"?"+params
        actual,actualsha=source_json(observed_url)
        observations=decode_observed(actual,set(IDS),start,end)
        for sid in IDS:
            site=sites[sid]
            url=era5.request_url(site["lat"],site["lon"],start,end)
            raw=era5.get_original_source(url)
            era,arr,grid=era5.parse_source(
                raw,site["lat"],site["lon"],start,end)
            source_QC=era5.statistics_and_coherence(arr)
            if not source_QC["hard_QC_pass"]:
                raise ValueError("P9_1B_ORIGINAL_ERA5_SOURCE_PHYSICS_NOT_QUALIFIED")
            scores=compare_era5_model_to_station(era,observations[sid])
            compiled.append({
                "station_id":sid,"station_name":site["name"],
                "season":season,"station_elevation_m":site["altitude_m"],
                "ERA5_selected_grid_center_lat":grid["selected_cell_latitude"],
                "ERA5_selected_grid_center_lon":grid["selected_cell_longitude"],
                "station_to_ERA5_grid_center_distance_km":
                    grid["selected_cell_distance_km"],
                "station_elevation_minus_ERA5_grid_height_m":None,
                "ERA5_grid_height_original_verified":False,
                "original_GeoSphere_QC_response_sha256":actualsha,
                "original_ERA5_provider_response_sha256":grid["raw_original_response_sha256"],
                **scores,
            })
            print("IGE_P9_1B_STATION",json.dumps({
                "site":site["name"],"id":sid,"season":season,
                "MAE_C":round(scores["temperature_raw_grid_vs_station_MAE_C"],3),
                "paired":scores["QC_accepted_matched_hours"],
                "grid_km":round(grid["selected_cell_distance_km"],2),
            }),flush=True)
        source.append({"season":season,"GeoSphere_original_response_sha256":actualsha,
                       "original_provider_API_request":observed_url,
                       "n_station_IDs":len(IDS)})
    if len(compiled)!=len(IDS)*len(PERIODS):
        raise ValueError("P9_1B_SITE_SEASON_CENSUS_NOT_COMPLETE")
    agg={
        "phase":"IGE_P9_1B_INDEPENDENT_3_STATION_2_SEASON_HOURLY_SOURCES",
        "site_station_metadata_sha256":metasha,
        "n_real_station_season_holdouts":len(compiled),
        "all_station_season_original_QC_pairs_pass":True,
        "n_total_qualified_station_hour_pairs":sum(
            r["QC_accepted_matched_hours"] for r in compiled),
        "observed_source_responses":source,
        "results":compiled,
        "no_station_data_used_for_grid_prediction":True,
        "source_provider":era5.SOURCE_SCOPE,
        "arbitrary_global_station_skill_qualified":False,
        "ERA5_native_orography_independently_verified":False,
        "EPW_generator_production_ready":False,
    }
    (root/"ige_p9_1b_real_geosphere_ERA5_station_holdouts.json").write_text(
        json.dumps(agg,indent=2,ensure_ascii=False)+"\n")
    print("IGE_P9_1B",json.dumps({
        "paired_site_seasons":len(compiled),
        "qualified_original_hour_pairs":agg["n_total_qualified_station_hour_pairs"],
        "median_raw_grid_temp_MAE_C":statistics.median(
            r["temperature_raw_grid_vs_station_MAE_C"] for r in compiled),
        "production_ready":False,
    }),flush=True)
    return agg


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--out",required=True)
    run(a.parse_args().out)
