#!/usr/bin/env python3
"""IGE P9.1G original 2019 DWD outside-Austria spatial validation and ERA5 ARCO pressure pilot.

No site/method fitting; 4 DWD new sites, 2 periods, full original hourly ERA5
baselines and a PREDECLARED 00/12UTC subset of pressure vertical source values.
Unobserved pressure hours are NEVER filled or used as hourly predictions.
"""
from __future__ import annotations
import argparse,hashlib,json,math,statistics
from pathlib import Path
import p9_1a_global_historical_backbone as era
import p9_1c_provider_altitude_2024_ablation as provider
import p9_1e_regular_grid_orography as regular
import p9_1g_dwd_original_2019_observations as dwd
import p9_1g_era5_pressure_stability as pressure

METHODS=("L0_RAW_GRID","P0_PROVIDER_ALTITUDE","L1_REGULAR_FIXED_0065",
         "L2_PRESSURE_TRUE_T_INVERSION_GUARD",
         "L3_PRESSURE_THETA_STABILITY_GUARD")
MIN_ORIGINAL_QC_HOURS=120


def scores(real_obs,series,available_timestamps,minimum=1):
    vals=[(float(real_obs[t]),float(series[t])) for t in available_timestamps
          if t in real_obs and t in series]
    if len(vals)<minimum:return None
    diffs=[pred-actual for actual,pred in vals]
    return {"n_qualified_original_DWD_QC10_hours":len(vals),
            "MAE_C":statistics.fmean(map(abs,diffs)),
            "RMSE_C":math.sqrt(statistics.fmean(d*d for d in diffs)),
            "bias_C":statistics.fmean(diffs)}


def run(out,accepted_QN_levels=dwd.QC_FINAL):
    if frozenset(accepted_QN_levels) not in (frozenset((3,)),frozenset((10,))):
        raise ValueError("P9G_UNREGISTERED_ORIGINAL_DWD_QUALITY_LEVEL")
    G2_SOURCE_QN3=frozenset(accepted_QN_levels)==frozenset((3,))
    folder=Path(out);folder.mkdir(parents=True,exist_ok=True)
    stations,original_observed,metadata=dwd.retrieve_all(accepted_QN_levels)
    sites=[stations[sid] for sid in dwd.STATION_IDS]
    weather={};cells=[];n_original=0
    # Freeze weather grid centers & real z before pressure + observed 2019 scoring.
    for s in sites:
        p=s["id"]
        url=era.request_url(s["lat"],s["lon"],"2019-01-10","2019-01-10")
        original_bytes=era.get_original_source(url)
        _,_,m=era.parse_source(original_bytes,s["lat"],s["lon"],
                               "2019-01-10","2019-01-10")
        cells.append({"id":str(p),"lat":s["lat"],"lon":s["lon"],
                      "grid_lat":m["selected_cell_latitude"],
                      "grid_lon":m["selected_cell_longitude"]})
    reg=regular.read_real_regular_z(cells)
    indexed={int(x["source_id"]):x for x in reg["points"]}
    spatial={s["id"]:{
        "lat":indexed[s["id"]]["original_ARCO_lat"],
        "lon":indexed[s["id"]]["original_ARCO_lon"],
        "model_height_m":indexed[s["id"]]["ARCO_025_original_model_height_m"]
    } for s in sites}
    # Persist immutably prereg original source site/meta and model heights.
    geometry={
        "phase":"IGE_P9_1G_INDEPENDENT_DWD_GEOGRAPHY_BEFORE_RESULT_EVALUATION",
        "frozen_DWD_Germany_site_IDs":list(dwd.STATION_IDS),
        "source_original_DWD_2019_station_metadata":metadata,
        "frozen_original_DWD_station_geography":sites,
        "original_ARCO_ERA5_geopotential_selected_cell_checksum":
            reg["digest_selected_original_grid_lat_lon_z_sha256"],
        "frozen_regular_ERA5_surface_heights":spatial,
        "pressure_subsample_UTC_hours":[0,12],
        "target_station_temperature_never_used_for_model_source_selection":True,
        "production_epw_ready":False}
    (folder/"p9_1g_original_DWD_and_ERA5_geometry_pre_eval.json").write_text(
        json.dumps(geometry,indent=2,ensure_ascii=False)+"\n")

    for s in sites:
        sid=s["id"]
        weather[sid]={}
        for season,start,end in dwd.SEASONS:
            url=era.request_url(s["lat"],s["lon"],start,end)
            rawbytes=era.get_original_source(url)
            wx,features,m=era.parse_source(rawbytes,s["lat"],s["lon"],start,end)
            if (abs(m["selected_cell_latitude"]-spatial[sid]["lat"])>1e-4
                 or abs((m["selected_cell_longitude"]-
                         spatial[sid]["lon"]+180)%360-180)>1e-4):
                raise ValueError("P9G_OROGRAPHY_NOT_AT_ACTUAL_2019_WEATHER_SOURCE_CELL")
            downbytes=era.get_original_source(
                provider.altitude_url(url,s["altitude_m"]))
            down,adjusted_features,downmeta=era.parse_source(
                downbytes,s["lat"],s["lon"],start,end)
            if wx["hourly"]["time"]!=down["hourly"]["time"]:
                raise ValueError("P9G_DWD_ORIGINAL_PROVIDER_HOUR_SUPPORT_DIFFERENT")
            if not(era.statistics_and_coherence(features)["hard_QC_pass"]
                   and era.statistics_and_coherence(adjusted_features)["hard_QC_pass"]):
                raise ValueError("P9G_REAL_ORIGINAL_ERA5_METEOROLOGY_PHYSICAL_QC_FAILED")
            times=wx["hourly"]["time"];dheight=s["altitude_m"]-spatial[sid]["model_height_m"]
            coeff=-.0065*dheight
            weather[sid][season]={
                "times":times,
                "raw":dict(zip(times,features["temperature_2m"])),
                "provider":dict(zip(times,adjusted_features["temperature_2m"])),
                "regular_lapse":dict(zip(times,(
                    x+coeff for x in features["temperature_2m"]))),
                "wind":dict(zip(times,features["wind_speed_10m"])),
                "cloud":dict(zip(times,features["cloud_cover"])),
                "ghi":dict(zip(times,features["shortwave_radiation"])),
                "source_original_ERA5_SHA":m["raw_original_response_sha256"],
                "source_original_provider_SHA":downmeta["raw_original_response_sha256"],
                "fixed_model_height_delta_m":dheight,
            }
    # Persist authentic international observation baseline before attempting
    # expensive pressure-level retrieval, never falsify later partial completion.
    baseline_rows=[]
    for item in sites:
        sid=item["id"]
        for season,_,_ in dwd.SEASONS:
            w=weather[sid][season]
            obs=original_observed[sid]["hourly_QC_accepted_TT_TU_for_scoring_PRIVATE"][season]
            results={
                METHODS[0]:scores(obs,w["raw"],w["times"],MIN_ORIGINAL_QC_HOURS),
                METHODS[1]:scores(obs,w["provider"],w["times"],MIN_ORIGINAL_QC_HOURS),
                METHODS[2]:scores(obs,w["regular_lapse"],w["times"],MIN_ORIGINAL_QC_HOURS),
            }
            baseline_rows.append({
                "station_id":sid,"site":item["name"],"season":season,
                "DWD_original_QN9_source_histogram":
                    original_observed[sid]["original_QC_histograms"][season],
                "DWD_original_zip_SHA256":
                    original_observed[sid]["source_zip_original_SHA256"],
                "ERA5_weather_source_SHA256":w["source_original_ERA5_SHA"],
                "ERA5_regular_selected_grid_height_m":spatial[sid]["model_height_m"],
                "registered_untuned_method_original_QC_results":results,
            })
    baseline={"phase":"P9G_INDEPENDENT_NEW_GERMANY_DWD_SOURCE_AND_ERA5_BASELINE",
              "n_registered_site_seasons":8,
              "n_original_2019_DWD_site_seasons_QC10_qualified":
                  sum(all(v is not None for v in x["registered_untuned_method_original_QC_results"].values())
                      for x in baseline_rows),
              "original_DWD_source_archives_pinned":metadata,
              "source_DWD_hourly_raw_temperature_not_uploaded":True,
              "pressure_level_ERA5_stability_verified_at_this_stage":False,
              "source_DWD_QN_level_G2_auto_checked_not_fully_completed":G2_SOURCE_QN3,
              "P9G1_strict_QN10_original_scientific_gate_stays_blocked":G2_SOURCE_QN3,
              "production_epw_ready":False,
              "members":baseline_rows}
    (folder/"p9_1g_germany_original_DWD_hourly_baseline_only.json").write_text(
        json.dumps(baseline,indent=2,ensure_ascii=False)+"\n")
    print("P9G_NEW_GERMANY_BASELINE_SOURCE",json.dumps({
        "n":len(baseline_rows),
        "QC_qualified":baseline["n_original_2019_DWD_site_seasons_QC10_qualified"],
        "source_pressure_level_qualified":False}),flush=True)

    # Read actual source pressure levels independent of target DWD temperature.
    profiles,profile_meta=pressure.read_original_ERA5_pressure_subsample(
        sites,spatial,dwd.SEASONS)
    members=[]
    for s in sites:
        sid=s["id"]
        for season,start,end in dwd.SEASONS:
            w=weather[sid][season]
            data=original_observed[sid]["hourly_QC_accepted_TT_TU_for_scoring_PRIVATE"][season]
            timestamps=w["times"]
            rawbase=scores(data,w["raw"],timestamps,MIN_ORIGINAL_QC_HOURS)
            providerbase=scores(data,w["provider"],timestamps,MIN_ORIGINAL_QC_HOURS)
            lapsebase=scores(data,w["regular_lapse"],timestamps,MIN_ORIGINAL_QC_HOURS)
            psub=profiles[sid][season]
            subset=list(pressure.hours_for_season(start,end))
            if set(subset)-set(timestamps):
                raise ValueError("P9G_PRESSURE_TIME_SUBSET_NOT_IN_WEATHER_ERA5_TIME_SUPPORT")
            candidate_t={k:{} for k in METHODS}
            source_risk_hours=0
            source_theta_guard_hours=0
            source_resolved_free_air_temperature_inversion_hours=0
            source_pressure_valid=0
            for stamp in subset:
                values=psub[stamp]
                if values["status"]=="TWO_VALID_ABOVE_REGULAR_ERA5_SURFACE_LEVELS":
                    source_pressure_valid+=1
                    source_resolved_free_air_temperature_inversion_hours+=int(
                        values["resolved_free_air_temperature_inversion"])
                wxrisk=bool(w["fixed_model_height_delta_m"]<=-150.)
                risk_T=pressure.fixed_potential_temperature_stability_guard(
                    wxrisk,w["ghi"][stamp],w["wind"][stamp],w["cloud"][stamp],
                    values,"T_UPPER_WARM")
                risk_TH=pressure.fixed_potential_temperature_stability_guard(
                    wxrisk,w["ghi"][stamp],w["wind"][stamp],w["cloud"][stamp],
                    values,"THETA_STABLE")
                source_risk_hours+=risk_T
                source_theta_guard_hours+=risk_TH
                candidate_t[METHODS[0]][stamp]=w["raw"][stamp]
                candidate_t[METHODS[1]][stamp]=w["provider"][stamp]
                candidate_t[METHODS[2]][stamp]=w["regular_lapse"][stamp]
                candidate_t[METHODS[3]][stamp]=(
                    w["raw"][stamp] if risk_T else w["regular_lapse"][stamp])
                candidate_t[METHODS[4]][stamp]=(
                    w["raw"][stamp] if risk_TH else w["regular_lapse"][stamp])
            source_QC_counts={
                method:scores(data,candidate_t[method],subset)
                for method in METHODS
            }
            row={
                "id":sid,"site":s["name"],"season":season,
                "independent_Germany_DWD_original_archive_not_Austrian_GeoSphere":True,
                "n_original_DWD_QC10_observed_hours":len(data),
                "original_DWD_zip_sha256":original_observed[sid]["source_zip_original_SHA256"],
                "original_DWD_QN_9_histogram":original_observed[sid][
                    "original_QC_histograms"][season],
                "source_weather_ERA5_original_SHA256":w["source_original_ERA5_SHA"],
                "source_provider_downscaled_original_SHA256":w["source_original_provider_SHA"],
                "regular_ERA5_surface_z_m":spatial[sid]["model_height_m"],
                "official_DWD_station_altitude_m":s["altitude_m"],
                "station_minus_regular_grid_height_m":w["fixed_model_height_delta_m"],
                "n_source_pressure_times_expected":len(subset),
                "n_source_pressure_profiles_above_ground":source_pressure_valid,
                "n_source_T_vertical_inversion_guard_hours":source_risk_hours,
                "n_source_theta_stability_guard_hours":source_theta_guard_hours,
                "n_source_resolved_T_warm_over_cold_free_air_hours":
                    source_resolved_free_air_temperature_inversion_hours,
                "source_DWD_original_quality_accepted_QN_levels":
                    sorted(accepted_QN_levels),
                "source_DWD_QN3_not_QN10_when_exploratory":G2_SOURCE_QN3,
                "full_168h_original_DWD_QC_baseline_metrics":{
                    METHODS[0]:rawbase,METHODS[1]:providerbase,METHODS[2]:lapsebase,
                },
                "pressure_SUBSAMPLE_14h_original_DWD_QC_metrics":source_QC_counts,
                "pressure_levels_do_not_resolve_true_site_layer_stability":True,
                "no_ERA5_vertical_pressure_missing_hours_inferred":True,
                "source_DWD_station_hourly_values_not_published":True,
            }
            members.append(row)
            print("P9G_INDEPENDENT_DWD",json.dumps({
                "station":s["name"],"season":season,
                "original_DWD_accepted_QN":sorted(accepted_QN_levels),
                "original_QN_accepted_hours":len(data),
                "full_hour_baselines":{
                    k:round(v["MAE_C"],3) if v else None
                    for k,v in row["full_168h_original_DWD_QC_baseline_metrics"].items()},
                "source_above_ground_pressure":source_pressure_valid,
                "14h_source_T_inversion_guarded":source_risk_hours,
            }),flush=True)
    eligible=[m for m in members
              if all(v is not None for v in m["full_168h_original_DWD_QC_baseline_metrics"].values())]
    means={method:statistics.fmean(
                x["full_168h_original_DWD_QC_baseline_metrics"][method]["MAE_C"]
                for x in eligible) if eligible else None
           for method in METHODS[:3]}
    pilot={method:statistics.fmean(
        x["pressure_SUBSAMPLE_14h_original_DWD_QC_metrics"][method]["MAE_C"]
        for x in members if x["pressure_SUBSAMPLE_14h_original_DWD_QC_metrics"][method])
        for method in METHODS}
    summary={
        "phase":"IGE_P9_1G_ERA5_3D_VERTICAL_STABILITY_GERMANY_DWD_2019_ORIGINAL_HOLDOUT",
        "n_predeclared_new_region_DWD_sites":4,
        "P9G2_exploratory_DWD_QN3_automatically_checked_not_QN10_fully_complete":G2_SOURCE_QN3,
        "P9G1_QN10_strict_source_qualification_stays_blocked_in_G2":G2_SOURCE_QN3,
        "n_predeclared_DWD_site_seasons":8,
        "n_full_hour_DWD_QC10_qualified_seasons":len(eligible),
        "n_original_DWD_qual_hour_pairs":sum(
            x["full_168h_original_DWD_QC_baseline_metrics"][METHODS[0]][
              "n_qualified_original_DWD_QC10_hours"] for x in eligible),
        "n_ERA5_pressure_original_2019_source_times":sum(
            x["n_source_pressure_times_expected"] for x in members),
        "n_ERA5_pressure_original_above_grid_profiles":sum(
            x["n_source_pressure_profiles_above_ground"] for x in members),
        "source_original_ARCO_pressure_provenance":profile_meta,
        "n_source_theta_stability_guard_hours":sum(
            x["n_source_theta_stability_guard_hours"] for x in members),
        "n_source_free_air_T_warm_over_cold_profiles":sum(
            x["n_source_resolved_T_warm_over_cold_free_air_hours"] for x in members),
        "original_DWD_source_quality_QN_levels":sorted(accepted_QN_levels),
        "original_DWD_source_directory_and_station_metadata_SHA":metadata,
        "original_regular_ARCO_ERA5_surface_geopotential_SHA":
            reg["digest_selected_original_grid_lat_lon_z_sha256"],
        "full_hour_regional_macro_MAE_C":means,
        "pressure_subsample_regional_macro_MAE_C":pilot,
        "insufficient_pressure_subsample_to_calibrate_or_qualify_hourly_inversion_model":True,
        "DWD_independent_region_Germany_is_not_multi_continent_generalization":True,
        "ERA5_25km_pressure_stability_not_local_measured_temperature_inversion":True,
        "model_parameters_and_sites_frozen_before_2019_DWD_observations":True,
        "global_arbitrary_location_weather_skill_qualified":False,
        "production_epw_ready":False,
        "members":members,
    }
    (folder/("p9_1g2_DWD_QN3_2019_ARCO_pressure_exploratory.json"
             if G2_SOURCE_QN3 else
             "p9_1g_2019_real_DWD_ERA5_ARCO_vertical_holdout_results.json")).write_text(
        json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    print("P9G_ORIGINAL_SOURCE_SUMMARY",json.dumps({
        "qualified":len(eligible),"total":8,
        "original_QC_hours":summary["n_original_DWD_qual_hour_pairs"],
        "source_pressure_times":summary["n_ERA5_pressure_original_2019_source_times"],
        "theta_guard_hours":summary["n_source_theta_stability_guard_hours"],
        "free_air_true_T_inversion_profiles":summary["n_source_free_air_T_warm_over_cold_profiles"],
        "full_macro_mae_C":means,
        "subsample_macro_mae_C":pilot,"production":False}),flush=True)
    if len(eligible)<6:
        raise RuntimeError("P9G_NOT_ENOUGH_GENUINE_GERMANY_DWD_ORIGINAL_QC_HOLDS")
    return summary


if __name__=="__main__":
    cli=argparse.ArgumentParser();cli.add_argument("--out",required=True)
    cli.add_argument("--exploratory-DWD-QN3",action="store_true",
                     help="Separate registered G2 historical auto-checked QN=3, NOT original strict QN10.")
    args=cli.parse_args()
    run(args.out,frozenset((3,)) if args.exploratory_DWD_QN3 else dwd.QC_FINAL)
