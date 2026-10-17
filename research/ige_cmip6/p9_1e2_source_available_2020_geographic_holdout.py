#!/usr/bin/env python3
"""P9.1E2: 2021 station SOURCE QC availability only, frozen 2020 observation holdout.

Explicit exploratory follow-up after E1 failed 5/6 station source coverage.
Never call E2 a confirmation of original E1 geographic station registration.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
import statistics
import urllib.parse
from pathlib import Path

import p9_1a_global_historical_backbone as era
import p9_1b_geosphere_original_station_holdouts as obs
import p9_1d_native_orography_dem as native
import p9_1c_provider_altitude_2024_ablation as adjusted
import p9_1e_regular_grid_orography as regular
import p9_1e_2021_new_lowland_station_holdout as candidate

QC_WINDOWS=(("2021_QC_winter","2021-01-10","2021-01-16"),
            ("2021_QC_summer","2021-07-10","2021-07-16"))
INDEPENDENT_2020_HOLDOUT=(("2020_holdout_winter","2020-01-10","2020-01-16"),
                          ("2020_holdout_summer","2020-07-10","2020-07-16"))
MAX_SOURCE_CANDIDATES_PER_TARGET=12
MAX_STATION_DISTANCE_KM=35.
MIN_COVERAGE=120


def freeze_geography_only_candidates(metadata):
    catalog=metadata.get("stations",[])
    result={}
    for label,(lat,lon) in regular.LOWLAND_TARGETS.items():
        options=[]
        for info in catalog:
            try:
                sid=int(info["id"])
                alt=float(info["altitude"])
                y=float(info["lat"]);x=float(info["lon"])
            except (TypeError,ValueError,KeyError):
                continue
            if sid in regular.EXCLUDED_PREVIOUS_SITE_IDS:continue
            distance=era.haversine(lat,lon,y,x)
            if distance<=MAX_STATION_DISTANCE_KM and -500<=alt<=6000:
                options.append({"id":sid,"name":info.get("name"),"lat":y,
                                "lon":x,"altitude_m":alt,"distance_km":distance})
        options.sort(key=lambda x:(x["distance_km"],x["id"]))
        result[label]=options[:MAX_SOURCE_CANDIDATES_PER_TARGET]
    return result


def read_original_qc_eligibility(data,requested_ids,start,end):
    """Use only source existence and QC-accepted count; NOT temperature values."""
    n=(dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days*24+24
    times=data.get("timestamps",[])
    expected=[(dt.datetime.fromisoformat(start+"T00:00+00:00")+
               dt.timedelta(hours=i)) for i in range(n)]
    parsed=[dt.datetime.fromisoformat(str(t).replace("Z","+00:00"))
            for t in times]
    if parsed!=expected:
        raise ValueError("P9E2_ORIGINAL_GEOSPHERE_QC_TIME_AXIS_INVALID")
    counts={sid:0 for sid in requested_ids}
    for feature in data.get("features",[]):
        props=feature.get("properties",{})
        sid_source=props.get("station")
        sid=int(sid_source["id"] if isinstance(sid_source,dict) else sid_source)
        if sid not in counts:raise ValueError("P9E2_UNREGISTERED_SOURCE_STATION")
        params=props.get("parameters",{})
        tmp=params.get("tl",{}).get("data")
        flags=params.get("tl_flag",{}).get("data")
        if tmp is None or flags is None:
            continue
        if len(tmp)!=n or len(flags)!=n:
            raise ValueError("P9E2_INCOMPLETE_QC_OR_VALUE_PROVIDER_SERIES")
        # Temperatures ONLY used to check presence/finite; not consumed as values
        # until 2020 holdout, years disjoint.
        counts[sid]=sum(
            x is not None and isinstance(x,(float,int))
            and math.isfinite(x) and v in obs.GOOD_FLAGS
            for x,v in zip(tmp,flags))
    return counts


def fetch_availability(candidates):
    all_ids=sorted({s["id"] for choices in candidates.values() for s in choices})
    if not all_ids:raise ValueError("P9E2_NO_CANDIDATE_STATION_IN_35KM")
    counts={s:[] for s in all_ids}
    response_sha=[]
    # GeoSphere may limit station_ids. Batches frozen by ascending numeric IDs
    # and deterministic maximum 20 stations per original source request.
    for _,start,end in QC_WINDOWS:
        for base in range(0,len(all_ids),20):
            chunk=all_ids[base:base+20]
            params=urllib.parse.urlencode({
                "station_ids":",".join(map(str,chunk)),
                "parameters":"tl,tl_flag",
                "start":start+"T00:00Z","end":end+"T23:00Z",
                "output_format":"geojson"})
            src,sha=obs.source_json(obs.BASE+"?"+params)
            count=read_original_qc_eligibility(src,set(chunk),start,end)
            for k,v in count.items():counts[k].append(v)
            response_sha.append({"period":start+"/"+end,
                                 "batch_station_IDs":chunk,
                                 "original_source_SHA256":sha})
    if not all(len(v)==2 for v in counts.values()):
        raise ValueError("P9E2_SOURCE_QC_ELIGIBILITY_MATRIX_INCOMPLETE")
    frozen={}
    used=set()
    for label,options in candidates.items():
        eligible=[x for x in options if x["id"] not in used and
                  min(counts[x["id"]])>=MIN_COVERAGE]
        if not eligible:
            frozen[label]={"status":"SOURCE_QC_NO_STATION_TWO_2021_SEASONS",
                           "candidate_source_coverage":[
                               {"station_id":x["id"],"QC_counts_2021":counts[x["id"]]}
                               for x in options]}
            continue
        best=eligible[0];used.add(best["id"])
        frozen[label]={"status":"QC_ELIGIBLE_WITHOUT_USING_TARGET_MODEL_ERROR",
                       **best,"QC_observation_counts_2021":counts[best["id"]]}
    return frozen,response_sha


def run(out):
    directory=Path(out);directory.mkdir(parents=True,exist_ok=True)
    metadata,msha=obs.source_json(obs.BASE+"/metadata")
    candidates=freeze_geography_only_candidates(metadata)
    source_cohort,sha=fetch_availability(candidates)
    selected=[{"id":v["id"],"name":v["name"],"lat":v["lat"],"lon":v["lon"],
               "altitude_m":v["altitude_m"]}
              for v in source_cohort.values() if "id" in v]
    # Emit source eligibility and choice BEFORE any 2020 weather observations.
    frozen={
        "phase":"P9_1E2_ORIGINAL_2021_SOURCE_QC_ELIGIBILITY_FROZEN_BEFORE_2020",
        "E1_original_2021_six_station_holdout_failed_source_coverage":True,
        "source_original_station_metadata_sha256":msha,
        "original_2021_QC_availability_source_SHA256":sha,
        "source_selected_station_only_by_geography_and_2021_QC_counts":True,
        "never_selection_using_2020_target_observations":True,
        "six_geo_targets_with_candidates":{k:[x["id"] for x in v]
                                           for k,v in candidates.items()},
        "frozen_station_cohort":source_cohort,
        "production_epw_ready":False}
    (directory/"p9_1e2_2021_source_eligibility_pre_holdout.json").write_text(
        json.dumps(frozen,indent=2,ensure_ascii=False)+"\n")
    if len(selected)<4:
        raise RuntimeError("P9E2_FEWER_THAN_FOUR_QC_READY_STATION_GEOGRAPHIES")
    sites=[{"id":str(v["id"]),"lat":v["lat"],"lon":v["lon"]}
           for v in selected]
    cells=regular.collect_grid_centers(sites)
    grid=regular.read_real_regular_z(cells)
    native_geo=native.actual_native_geo(selected)
    dem=native.independent_dem(selected)
    reg_lookup={str(p["source_id"]):p for p in grid["points"]}
    native_lookup={str(p["station_id"]):p for p in native_geo["sites"]}
    dem_lookup={str(p["station_id"]):p for p in dem["sites"]}
    temp2020=[]
    for season,start,end in INDEPENDENT_2020_HOLDOUT:
        params=urllib.parse.urlencode({
            "station_ids":",".join(str(p["id"]) for p in selected),
            "parameters":"tl,tl_flag",
            "start":start+"T00:00Z","end":end+"T23:00Z",
            "output_format":"geojson"})
        original_obs,osha=obs.source_json(obs.BASE+"?"+params)
        station_obs=obs.decode_observed(original_obs,set(p["id"] for p in selected),start,end)
        for v in selected:
            sid=v["id"];key=str(sid)
            base={"station_id":sid,"station":v["name"],"period":season,
                  "original_2020_QC_observation_SHA256":osha,
                  "source_2021_station_eligibility_only_not_2020_skill":True,
                  "n_2020_original_QC_available":len(station_obs[sid]),
                  "regular_025_height_m":reg_lookup[key]["ARCO_025_original_model_height_m"],
                  "native_N320_height_m":native_lookup[key]["native_z_div_g0_height_m"],
                  "source_independent_SRTM_height_m":dem_lookup[key]["SRTM_v3_90m_elevation_m"]}
            if len(station_obs[sid])<MIN_COVERAGE:
                base["status"]="2020_UNSEEN_STATION_SOURCE_QC_INCOMPLETE"
                temp2020.append(base)
                continue
            url=era.request_url(v["lat"],v["lon"],start,end)
            rawb=era.get_original_source(url)
            raw,values,rm=era.parse_source(rawb,v["lat"],v["lon"],start,end)
            reg=reg_lookup[key]
            if (abs(rm["selected_cell_latitude"]-reg["original_ARCO_lat"])>1e-4
                    or abs((rm["selected_cell_longitude"]-
                            reg["original_ARCO_lon"]+180)%360-180)>1e-4):
                raise ValueError("P9E2_2020_WEATHER_SOURCE_CELL_DIFFERS_FROM_OROGRAPHY")
            downb=era.get_original_source(adjusted.altitude_url(url,v["altitude_m"]))
            down,adjustedvalues,dm=era.parse_source(downb,v["lat"],v["lon"],start,end)
            if raw["hourly"]["time"]!=down["hourly"]["time"]:
                raise ValueError("P9E2_ERA5_ORIGINAL_AND_PROVIDER_DOWN_SAME_TIME_REQUIRED")
            if not (era.statistics_and_coherence(values)["hard_QC_pass"]
                    and era.statistics_and_coherence(adjustedvalues)["hard_QC_pass"]):
                raise ValueError("P9E2_SOURCE_ERA5_VARIABLE_PHYSICAL_QC_BLOCK")
            predictions,physical=candidate.fixed_predictions(
                values["temperature_2m"],adjustedvalues["temperature_2m"],
                v["altitude_m"],native_lookup[key]["native_z_div_g0_height_m"],
                reg["ARCO_025_original_model_height_m"])
            score={method:fixed_score(raw["hourly"]["time"],series,station_obs[sid])
                   for method,series in predictions.items()}
            if len({x["matched_original_QC_hours"] for x in score.values()})!=1:
                raise ValueError("P9E2_METHOD_QC_SAMPLES_NOT_IDENTICAL")
            base.update({"status":"2020_NEW_GEOGRAPHY_TRUE_QC_SCORED",
                         "2020_original_weather_SHA256":rm["raw_original_response_sha256"],
                         "2020_downscaled_source_SHA256":dm["raw_original_response_sha256"],
                         "physical_corrections":physical,"scores":score})
            temp2020.append(base)
            print("P9E2_2020",json.dumps({
                "site_id":sid,"station":v["name"],"period":season,
                "n":len(station_obs[sid]),
                "mae":{k:round(v["MAE_C"],3) for k,v in score.items()},
            }),flush=True)
    valid=[x for x in temp2020 if x["status"]=="2020_NEW_GEOGRAPHY_TRUE_QC_SCORED"]
    result={
        "phase":"IGE_P9_1E2_EXPLORATORY_SOURCE_ELIGIBILITY_2021_INDEPENDENT_QC_2020_HOLDOUT",
        "original_2021_station_source_eligibility_frozen_before_2020":True,
        "E1_failed_original_holdout_source_completeness_remains_failed":True,
        "n_six_geographic_targets":6,
        "n_2021_source_eligible_stations":len(selected),
        "n_2020_real_original_station_seasons_scored":len(valid),
        "n_2020_original_paired_QC_hours":sum(
            x["scores"]["L0_RAW"]["matched_original_QC_hours"] for x in valid),
        "macro_2020_MAE_C_by_untuned_method":{
            method:statistics.fmean(x["scores"][method]["MAE_C"] for x in valid)
            if valid else None for method in candidate.METHODS},
        "wins_vs_raw":{
            method:sum(x["scores"][method]["MAE_C"]<x["scores"]["L0_RAW"]["MAE_C"]
                       for x in valid) for method in candidate.METHODS},
        "ARCO_grid_SHA":grid["digest_selected_original_grid_lat_lon_z_sha256"],
        "native_grid_SHA":native_geo["native_N320_array_values_sha256"],
        "independent_SRTM_original_provider_SHA":dem["response_sha256"],
        "station_selection_based_only_on_original_geography_and_2021_QC_availability":True,
        "this_followup_exploratory_not_confirmatory_original_E1":True,
        "native_vs_regular_exact_ERA5_provider_equivalence_unproven":True,
        "global_site_skill_validated":False,
        "production_epw_ready":False,
        "results":temp2020}
    (directory/"p9_1e2_separate_2020_original_lowland_holdout.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print("P9E2_2020_HOLDOUT",json.dumps({
        "eligible":len(selected),"scored":len(valid),
        "original_QC_hours":result["n_2020_original_paired_QC_hours"],
        "macro_MAE_C":result["macro_2020_MAE_C_by_untuned_method"],
        "production_ready":False}),flush=True)
    if len(valid)<8:
        raise RuntimeError("P9E2_NEW_INDEPENDENT_2020_STATION_SOURCE_QC_NOT_ENOUGH")
    return result


def fixed_score(times,prediction,observed):
    import p9_1d_independent_station_correction as earlier
    return earlier.score_pair(times,prediction,observed,min_pairs=MIN_COVERAGE)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",required=True)
    run(p.parse_args().out)
