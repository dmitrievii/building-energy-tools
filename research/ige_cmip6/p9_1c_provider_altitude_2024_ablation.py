#!/usr/bin/env python3
"""P9.1C: original 2024 heldout ERA5-grid vs provider-altitude correction.

Do NOT infer universal best lapse or native orography from this 3-site,
different-year pilot; source observed station altitude is geometry, never
calibrated from withheld hourly temperatures.
"""
import argparse
import datetime as dt
import json
import statistics
import urllib.parse
from pathlib import Path
import p9_1a_global_historical_backbone as era
import p9_1b_geosphere_original_station_holdouts as station

PERIODS=(("winter_2024","2024-01-10","2024-01-16"),
         ("summer_2024","2024-07-10","2024-07-16"))


def altitude_url(baseurl,altitude_m):
    u=urllib.parse.urlsplit(baseurl)
    q=urllib.parse.parse_qs(u.query,keep_blank_values=True)
    if q.get("models")!=["era5"] or q.get("elevation")!=["nan"]:
        raise ValueError("P9_1C_UNEXPECTED_RAW_MODEL_OR_ELEVATION_REQUEST")
    if not -500<=altitude_m<=6000:
        raise ValueError("P9_1C_INVALID_AUTHENTIC_SITE_ALTITUDE")
    q["elevation"]=[f"{altitude_m:.2f}"]
    return urllib.parse.urlunsplit((u.scheme,u.netloc,u.path,
                                   urllib.parse.urlencode(q,doseq=True),""))


def score_pair(original_obs,grid_obj,site_obj):
    a=station.compare_era5_model_to_station(grid_obj,original_obs)
    b=station.compare_era5_model_to_station(site_obj,original_obs)
    if a["QC_accepted_matched_hours"]!=b["QC_accepted_matched_hours"]:
        raise ValueError("P9_1C_NOT_IDENTICAL_HOURLY_HOLDOUT_SAMPLE")
    return {
        "n_original_observed_UTC_hour_pairs":a["QC_accepted_matched_hours"],
        "raw_grid_MAE_C":a["temperature_raw_grid_vs_station_MAE_C"],
        "provider_site_altitude_adjusted_MAE_C":b["temperature_raw_grid_vs_station_MAE_C"],
        "raw_grid_RMSE_C":a["temperature_raw_grid_vs_station_RMSE_C"],
        "provider_site_altitude_adjusted_RMSE_C":b["temperature_raw_grid_vs_station_RMSE_C"],
        "raw_grid_bias_C":a["temperature_raw_grid_vs_station_bias_C"],
        "provider_site_altitude_adjusted_bias_C":b["temperature_raw_grid_vs_station_bias_C"],
        "MAE_change_site_adjusted_minus_grid_C":
            b["temperature_raw_grid_vs_station_MAE_C"]-a["temperature_raw_grid_vs_station_MAE_C"],
        "site_altitude_correction_is_provider_black_box_not_own_physics":True,
    }


def run(out):
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    meta,meta_sha=station.source_json(station.BASE+"/metadata")
    sites=station.extract_metadata(meta)
    findings=[]
    for season,start,end in PERIODS:
        q=urllib.parse.urlencode({
            "parameters":"tl,tl_flag",
            "station_ids":",".join(str(s) for s in station.IDS),
            "start":start+"T00:00Z","end":end+"T23:00Z",
            "output_format":"geojson",
        })
        observed,observed_sha=station.source_json(station.BASE+"?"+q)
        station_data=station.decode_observed(observed,set(station.IDS),start,end)
        for sid in station.IDS:
            loc=sites[sid]
            url=era.request_url(loc["lat"],loc["lon"],start,end)
            raw_source=era.get_original_source(url)
            raw,source_vars,source_meta=era.parse_source(
                raw_source,loc["lat"],loc["lon"],start,end)
            alt_url=altitude_url(url,loc["altitude_m"])
            adjusted_source=era.get_original_source(alt_url)
            adjusted,alt_vars,alt_meta=era.parse_source(
                adjusted_source,loc["lat"],loc["lon"],start,end)
            if (not era.statistics_and_coherence(source_vars)["hard_QC_pass"]
                    or not era.statistics_and_coherence(alt_vars)["hard_QC_pass"]):
                raise ValueError("P9_1C_SOURCE_PHYSICS_INVALID_OR_DOWNSCALING_INCOMPLETE")
            r=score_pair(station_data[sid],raw,adjusted)
            r.update({
                "station_id":sid,"station":loc["name"],"season":season,
                "original_QC_station_altitude_m":loc["altitude_m"],
                "original_QC_station_lat":loc["lat"],
                "original_QC_station_lon":loc["lon"],
                "grid_nearest_location_changed_by_height_correction":(
                    source_meta["selected_cell_latitude"]!=alt_meta["selected_cell_latitude"]
                    or source_meta["selected_cell_longitude"]!=alt_meta["selected_cell_longitude"]),
                "raw_grid_cell_km":source_meta["selected_cell_distance_km"],
                "source_raw_grid_sha256":source_meta["raw_original_response_sha256"],
                "source_provider_adjusted_sha256":alt_meta["raw_original_response_sha256"],
                "original_GeoSphere_QC_observation_SHA256":observed_sha,
            })
            findings.append(r)
            print("IGE_P9_1C_SITE",json.dumps({
                "station":loc["name"],"period":season,
                "raw_MAE_C":round(r["raw_grid_MAE_C"],3),
                "provider_altitude_MAE_C":round(r["provider_site_altitude_adjusted_MAE_C"],3),
                "delta_MAE_C":round(r["MAE_change_site_adjusted_minus_grid_C"],3),
                "n_QC":r["n_original_observed_UTC_hour_pairs"],
            }),flush=True)
    if len(findings)!=6:raise ValueError("P9_1C_UNEXPECTED_STATION_PERIOD_CENSUS")
    result={
        "phase":"IGE_P9_1C_ORIGINAL_2024_STATION_ALTITUDE_ABLATION",
        "study_registered_after_original_2023_station_results":True,
        "2024_observation_year_temporally_independent_from_P9_1B":True,
        "original_meta_SHA256":meta_sha,
        "site_seasons":len(findings),
        "mean_paired_site_ERA5_grid_MAE_C":statistics.fmean(r["raw_grid_MAE_C"] for r in findings),
        "mean_paired_site_provider_altitude_MAE_C":
            statistics.fmean(r["provider_site_altitude_adjusted_MAE_C"] for r in findings),
        "number_site_seasons_provider_altitude_improved":sum(
            r["MAE_change_site_adjusted_minus_grid_C"]<0 for r in findings),
        "source_reanalysis_is_not_original_CDS_native":True,
        "no_tuning_to_test_site_target_observed_temperature":True,
        "site_elevation_is_provider_metadata_not_model_native_grid_orography":True,
        "does_NOT_qualify_site_lapse_as_global_correction":True,
        "native_global_terrain_model_implemented":False,
        "production_epw_ready":False,
        "member_metrics":findings,
    }
    (root/"ige_p9_1c_independent_2024_original_station_elevation_ablation.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print("IGE_P9_1C",json.dumps({
        "n_site_seasons":len(findings),
        "raw_MAE_C":result["mean_paired_site_ERA5_grid_MAE_C"],
        "site_altitude_MAE_C":result["mean_paired_site_provider_altitude_MAE_C"],
        "improved_sites":result["number_site_seasons_provider_altitude_improved"],
        "production_ready":False,
    }),flush=True)
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",required=True)
    run(p.parse_args().out)
