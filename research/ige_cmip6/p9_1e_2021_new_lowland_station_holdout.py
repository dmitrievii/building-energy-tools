#!/usr/bin/env python3
"""IGE P9.1E 2021 six new geographic station holdouts, real 0.25 geopotential.

All 2021 temperatures withheld until geo-only sites and fixed methods frozen.
Original 2021 independent GeoSphere QC, native N320, regular ARCO geopotential,
Open-Meteo source ERA5 and independent SRTM. No target fit or model selection.
"""
import argparse
import datetime as dt
import json
import math
import statistics
import urllib.parse
from pathlib import Path

import p9_1a_global_historical_backbone as era
import p9_1b_geosphere_original_station_holdouts as station
import p9_1c_provider_altitude_2024_ablation as alt
import p9_1d_native_orography_dem as native
import p9_1d_independent_station_correction as fixed
import p9_1e_regular_grid_orography as mapping

PERIODS=(("winter_2021","2021-01-10","2021-01-16"),
         ("summer_2021","2021-07-10","2021-07-16"))
MIN_QC=120
METHODS=("L0_RAW","P0_PROVIDER","L1_NATIVE_N320_FIXED_LAPSE",
         "L2_REGULAR_025_FIXED_LAPSE","L3_REGULAR_025_BOUNDED_3C")


def fixed_predictions(raw,provider,z_station,z_native,z_regular):
    if len(raw)!=len(provider) or not raw:
        raise ValueError("P9E_DIVERGENT_WEATHER_HOURLY_SOURCE_COHORT")
    if not all(math.isfinite(v) for v in (z_station,z_native,z_regular)):
        raise ValueError("P9E_NONFINITE_SITE_OR_MODEL_OROGRAPHY")
    if max(abs(z_station-z_native),abs(z_station-z_regular))>6000:
        raise ValueError("P9E_UNPHYSICAL_OROGRAPHY_DIFFERENCE")
    native_correction=-.0065*(z_station-z_native)
    regular_correction=-.0065*(z_station-z_regular)
    bounded=max(-3.,min(3.,regular_correction))
    return {
        "L0_RAW":[float(x) for x in raw],
        "P0_PROVIDER":[float(x) for x in provider],
        "L1_NATIVE_N320_FIXED_LAPSE":[float(x)+native_correction for x in raw],
        "L2_REGULAR_025_FIXED_LAPSE":[float(x)+regular_correction for x in raw],
        "L3_REGULAR_025_BOUNDED_3C":[float(x)+bounded for x in raw],
    },{
        "z_site_minus_native_m":z_station-z_native,
        "z_site_minus_regular_025_m":z_station-z_regular,
        "native_fixed_correction_C":native_correction,
        "regular_fixed_correction_C":regular_correction,
        "bounded_regular_correction_C":bounded,
        "correction_parameters_chosen_after_target_observation":False,
        "OpenMeteo_arco_regridding_equivalence_proven":False,
    }


def run(mapping_json,out,record_blocked=False):
    geo=json.loads(Path(mapping_json).read_text())
    if not (geo.get("actual_original_ERA5_025_geopotential_values_read")
            and geo.get("same_selected_025_coordinate_as_source_verified")):
        raise ValueError("P9E_ORIGINAL_REGULAR_025_GRID_OROGRAPHY_NOT_VERIFIED")
    sources=geo["new_lowland_station_selection"]
    matched={str(q["id"]):q for q in geo["mapped_points"]}
    picked=[]
    for label in mapping.LOWLAND_TARGETS:
        record=sources[label]
        if "station_id" in record:
            id_=str(record["station_id"])
            if id_ not in matched:
                raise ValueError("P9E_REGISTERED_LOWLAND_SOURCE_NOT_IN_GEOMETRY")
            picked.append((label,record,matched[id_]))
    if len(picked)<4:raise ValueError("P9E_FEWER_THAN_4_ACTUAL_NEW_LOWLAND_SITES")
    demo=native.independent_dem([{
        "id":c["station_id"],"lat":c["station_lat"],"lon":c["station_lon"],
        "name":c["station_name"],"altitude_m":c["site_altitude_official_m"],
    } for _,c,_ in picked])
    dem={str(d["station_id"]):d for d in demo["sites"]}
    rows=[]
    source_obs=[]
    for season,start,end in PERIODS:
        ids=[str(c["station_id"]) for _,c,_ in picked]
        query=urllib.parse.urlencode({
            "station_ids":",".join(ids),"parameters":"tl,tl_flag",
            "start":start+"T00:00Z","end":end+"T23:00Z",
            "output_format":"geojson"})
        observed,osha=station.source_json(station.BASE+"?"+query)
        o=station.decode_observed(observed,set(map(int,ids)),start,end)
        source_obs.append({"period":season,"original_obs_SHA256":osha})
        for label,c,z in picked:
            sid=int(c["station_id"]);data=o[sid]
            item={
                "site":label,"station_id":sid,"station_name":c["station_name"],
                "season":season,
                "station_location_selected_before_hourly_observation":True,
                "official_station_elevation_m":c["site_altitude_official_m"],
                "independent_SRTM_site_elevation_m":dem[str(sid)]["SRTM_v3_90m_elevation_m"],
                "regular_025_grid_geopotential_height_m":z["regular_025_z_g0_height_m"],
                "native_N320_grid_geopotential_height_m":z["nearest_native_N320_z_g0_height_m"],
                "regular_ARCO_025_not_proven_OpenMeteo_internal_regridding":True,
                "original_QC_observation_SHA256":osha,
                "original_QC_observed_valid_hours":len(data),
            }
            if len(data)<MIN_QC:
                item["status"]="INSUFFICIENT_ORIGINAL_STATION_QC"
                rows.append(item)
                continue
            # Same weather source hour+site as 2021 selected grid,
            # repeated independently from 1-day original grid-cell probe.
            url=era.request_url(c["station_lat"],c["station_lon"],start,end)
            rawbytes=era.get_original_source(url)
            raw,values,metadata=era.parse_source(
                rawbytes,c["station_lat"],c["station_lon"],start,end)
            if (metadata["selected_cell_latitude"]!=z["regular_025_cell_lat"]
                    or (metadata["selected_cell_longitude"]%360)!=(z["regular_025_cell_lon"]%360)):
                raise ValueError("P9E_025_SELECTED_GRID_CENTER_CHANGED_BETWEEN_SOURCE_READS")
            downbytes=era.get_original_source(
                alt.altitude_url(url,c["site_altitude_official_m"]))
            adjusted,avals,ameta=era.parse_source(
                downbytes,c["station_lat"],c["station_lon"],start,end)
            if raw["hourly"]["time"]!=adjusted["hourly"]["time"]:
                raise ValueError("P9E_DOWNSCALE_CHANGED_TIME_SUPPORT")
            if not (era.statistics_and_coherence(values)["hard_QC_pass"]
                    and era.statistics_and_coherence(avals)["hard_QC_pass"]):
                raise ValueError("P9E_INVALID_ORIGINAL_ERA5_WEATHER_SOURCE")
            predictions,phys=fixed_predictions(
                values["temperature_2m"],avals["temperature_2m"],
                c["site_altitude_official_m"],
                z["nearest_native_N320_z_g0_height_m"],
                z["regular_025_z_g0_height_m"])
            score={
                k:fixed.score_pair(raw["hourly"]["time"],v,data,min_pairs=MIN_QC)
                for k,v in predictions.items()
            }
            if len({x["matched_original_QC_hours"] for x in score.values()})!=1:
                raise ValueError("P9E_MISMATCHED_QC_HOURS_ACROSS_METHODS")
            item.update({
                "status":"REAL_HOLDOUT_SCORED",
                "physical_corrections":phys,
                "original_ERA5_weather_source_SHA256":metadata["raw_original_response_sha256"],
                "original_provider_altitude_source_SHA256":ameta["raw_original_response_sha256"],
                "scores":score})
            rows.append(item)
            print("P9E_NEW_SITE_2021",json.dumps({
                "site":label,"season":season,"station":sid,"n":len(data),
                "mae_C":{k:round(v["MAE_C"],3) for k,v in score.items()},
                "native_delta_m":round(phys["z_site_minus_native_m"],1),
                "regular_delta_m":round(phys["z_site_minus_regular_025_m"],1),
            }),flush=True)
    eligible=[x for x in rows if x["status"]=="REAL_HOLDOUT_SCORED"]
    result={
        "phase":"IGE_P9_1E_2021_GEOGRAPHIC_NEW_LOWLAND_STATIONS_SOURCE_HOLDOUT",
        "original_regular_ARCO_geopotential_source_SHA256":geo["regular_source"][
            "digest_selected_original_grid_lat_lon_z_sha256"],
        "original_independent_SRTM_DEM_response_SHA256":demo["response_sha256"],
        "station_targets_preregistered":list(mapping.LOWLAND_TARGETS),
        "n_target_geographies":len(mapping.LOWLAND_TARGETS),
        "n_matched_original_station_geographies":len(picked),
        "n_predeclared_station_seasons":len(mapping.LOWLAND_TARGETS)*len(PERIODS),
        "n_original_station_seasons_scored":len(eligible),
        "original_E1_source_QC_qualification_pass":len(eligible)>=8,
        "initial_E1_frozen_cohort_any_substitution_performed":False,
        "n_original_QC_paired_hours":sum(
            x["scores"][METHODS[0]]["matched_original_QC_hours"] for x in eligible),
        "model_names_fixed_before_holdout":list(METHODS),
        "MAE_macro_by_method_C":{
            k:statistics.fmean(x["scores"][k]["MAE_C"] for x in eligible)
            if eligible else None for k in METHODS},
        "wins_vs_raw_count":{
            k:sum(x["scores"][k]["MAE_C"]<x["scores"][METHODS[0]]["MAE_C"]
                  for x in eligible) for k in METHODS},
        "original_GeoSphere_observation_responses":source_obs,
        "no_target_hourly_data_used_for_spatial_site_selection":True,
        "native_N320_and_ARCO_regular_processed_models_are_not_same_grid":True,
        "ARCO_OpenMeteo_same_internal_orography_algorithm_confirmed":False,
        "separate_independent_extra_Austria_station_skill_qualified":False,
        "production_epw_ready":False,
        "members":rows,
    }
    target=Path(out);target.mkdir(parents=True,exist_ok=True)
    (target/"p9_1e_new_lowland_2021_station_holdout.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print("P9E_2021_HOLDOUT",json.dumps({
        "n_geo":len(picked),"scored":len(eligible),"n_hours":result["n_original_QC_paired_hours"],
        "macro_mae_C":result["MAE_macro_by_method_C"],"production_ready":False}),flush=True)
    if len(eligible)<8 and not record_blocked:
        raise RuntimeError("P9E_FROZEN_NEW_SITE_ORIGINAL_HOLDOUT_INSUFFICIENT")
    return result

if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--mapping",required=True)
    cli.add_argument("--out",required=True)
    cli.add_argument("--record-blocked",action="store_true",
                     help="Scientific CI: retain prereg original source-QC blocked result; never mark qualified.")
    a=cli.parse_args()
    run(a.mapping,a.out,record_blocked=a.record_blocked)
