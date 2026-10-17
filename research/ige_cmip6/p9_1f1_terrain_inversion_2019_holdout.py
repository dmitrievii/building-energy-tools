#!/usr/bin/env python3
"""IGE P9.1F1: no-target-fitting terrain + source-conditioned cold-air pool guard.

Uses a real independent SRTM 5km+12km radial ring, real original GeoSphere QC,
fixed original ERA5 weather, separately sourced ARCO ERA5 regular z/g, and
frozen physically motivated candidate rules. 2019 observations are ONLY scored.
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
import urllib.parse
from pathlib import Path

import numpy as np
import p9_1a_global_historical_backbone as era
import p9_1b_geosphere_original_station_holdouts as station
import p9_1c_provider_altitude_2024_ablation as alt
import p9_1d_native_orography_dem as original_dem
import p9_1e_regular_grid_orography as regular

IDS=(105,56,145,48,15,22,39,196,14305)
PERIODS=(("winter_2019","2019-01-10","2019-01-16"),
         ("summer_2019","2019-07-10","2019-07-16"),
         ("autumn_2019","2019-10-10","2019-10-16"))
MIN_QC=120
METHODS=("L0_RAW","P0_PROVIDER","L1_REGULAR_LAPSE",
         "L2_TERRAIN_NIGHT_GUARD","L3_TERRAIN_NIGHT_COLDPOOL")
RING_KM=(5.,12.)
RING_DIRECTIONS_DEG=(0.,45.,90.,135.,180.,225.,270.,315.)
LAPSE_COEFF=-.0065
MIN_GRID_STATION_DZ_M=150.
MIN_12KM_TERRAIN_P75_RELIEF_M=120.
MAX_NIGHT_GHI_W_M2=10.
MAX_WIND_MS=2.5
MAX_CLOUD_PERCENT=60.
FIXED_COLDPOOL_PERTURBATION_C=-1.


def sites_from_original_meta(meta):
    catalog={int(s["id"]):s for s in meta["stations"]}
    out=[]
    for sid in IDS:
        s=catalog.get(sid)
        if not s:raise ValueError("P9F1_FROZEN_REGISTERED_SITE_MISSING_"+str(sid))
        o={"id":sid,"name":s["name"],"lat":float(s["lat"]),
           "lon":float(s["lon"]),"altitude_m":float(s["altitude"])}
        if not (-90<=o["lat"]<=90 and -180<=o["lon"]<=180
                and -500<=o["altitude_m"]<=6500):
            raise ValueError("P9F1_ORIGINAL_STATION_GEO_INVALID")
        out.append(o)
    return out


def ring_coordinates(lat,lon,km,bearing):
    """Geodesic great-circle point with distance km and direction from north."""
    rad=math.radians(bearing);phi1=math.radians(lat);lam1=math.radians(lon)
    angular=km/era.EARTH_KM
    phi2=math.asin(math.sin(phi1)*math.cos(angular)
                  +math.cos(phi1)*math.sin(angular)*math.cos(rad))
    lam2=lam1+math.atan2(math.sin(rad)*math.sin(angular)*math.cos(phi1),
                         math.cos(angular)-math.sin(phi1)*math.sin(phi2))
    return math.degrees(phi2),((math.degrees(lam2)+180.)%360.)-180.


def terrain_source_points(sites):
    requests=[];sub={}
    for s in sites:
        sid=s["id"];keys=[]
        for tag,radius,bearing in [("center",0.,0.)]+[
                (f"{int(radius)}km_{int(bearing)}",radius,bearing)
                for radius in RING_KM for bearing in RING_DIRECTIONS_DEG]:
            lat,lon=(s["lat"],s["lon"]) if not radius else ring_coordinates(
                s["lat"],s["lon"],radius,bearing)
            key=f"{sid}_{tag}"
            requests.append({"id":key,"name":key,"lat":lat,"lon":lon,
                             "altitude_m":s["altitude_m"]})
            keys.append(key)
        sub[sid]=keys
    if len(requests)!=17*len(sites):
        raise ValueError("P9F1_TERRAIN_EXACT_17_POINT_SOURCE_REQUIREMENT")
    return requests,sub


def independent_dem_rings(sites):
    points,labels=terrain_source_points(sites)
    result={};sources=[]
    # OpenTopoData API has per-request point count/rate limits;
    # finite 34-point requests, one independent original response SHA each.
    for k in range(0,len(points),34):
        block=points[k:k+34]
        response=original_dem.independent_dem(block)
        sources.append({"station_source_ids":[p["id"] for p in block],
                        "original_independent_SRTM_provider_SHA256":
                            response["response_sha256"]})
        for entry in response["sites"]:
            key=entry["station_id"]
            if key in result:raise ValueError("P9F1_DUPLICATE_TERRAIN_SOURCE_POINT")
            result[key]=float(entry["SRTM_v3_90m_elevation_m"])
        if k+34<len(points):time.sleep(1.2)
    profile={}
    for station_info in sites:
        sid=station_info["id"];names=labels[sid]
        if any(k not in result for k in names):
            raise ValueError("P9F1_DEM_RING_OR_CENTER_SOURCE_MISSING")
        center=result[names[0]]
        near=[result[k] for k in names[1:9]]
        far=[result[k] for k in names[9:17]]
        high=float(np.percentile(far,75))
        relief=high-center
        profile[sid]={
            "original_srtm90m_site_m":center,
            "site_official_minus_SRTM_m":station_info["altitude_m"]-center,
            "ring5km_m":near,
            "ring12km_m":far,
            "ring12km_p75_height_m":high,
            "ring12km_p75_relief_m":relief,
            "ring12km_uphill_fraction":sum(z>center+50 for z in far)/8,
            "terrain_inferred_valley_susceptibility_only_not_inversion_detection":True,
            "SRTM_original_raster_tile_binaries_not_independently_checked":True,
            "source_station_QC_temperature_was_never_used_to_derive_terrain":True,
        }
    return profile,sources


def make_fixed_predictions(raw,provider,wind,cloud,ghi,times,
                           station_z,regular_z,terrain_relief):
    n=len(raw)
    if not n or any(len(x)!=n for x in (provider,wind,cloud,ghi,times)):
        raise ValueError("P9F1_HOURLY_SOURCE_VARIABLE_TIMELINES_NOT_ALIGNED")
    if not all(math.isfinite(v) for v in (station_z,regular_z,terrain_relief)):
        raise ValueError("P9F1_NONFINITE_GRID_OR_TERRAIN_HEIGHT")
    dz=station_z-regular_z
    if abs(dz)>6500:raise ValueError("P9F1_MODEL_TO_STATION_HEIGHT_DELTA_INVALID")
    lapse=LAPSE_COEFF*dz
    valley=bool(dz<=-MIN_GRID_STATION_DZ_M
                and terrain_relief>=MIN_12KM_TERRAIN_P75_RELIEF_M)
    predictions={k:[] for k in METHODS};flags=[]
    for i in range(n):
        t=float(raw[i]);down=float(provider[i])
        w=float(wind[i]);c=float(cloud[i]);solar=float(ghi[i])
        if not all(map(math.isfinite,(t,down,w,c,solar))):
            raise ValueError("P9F1_NONFINITE_SOURCE_WEATHER")
        stamp=dt.datetime.strptime(times[i],"%Y-%m-%dT%H:%M")
        is_dark=(solar<=MAX_NIGHT_GHI_W_M2)
        cold=(stamp.month in (10,11,12,1,2,3))
        guarded=(valley and cold and is_dark
                 and w<MAX_WIND_MS and c<MAX_CLOUD_PERCENT)
        flags.append(guarded)
        values={
            "L0_RAW":t,
            "P0_PROVIDER":down,
            "L1_REGULAR_LAPSE":t+lapse,
            "L2_TERRAIN_NIGHT_GUARD":t if guarded else t+lapse,
            "L3_TERRAIN_NIGHT_COLDPOOL":
                t+FIXED_COLDPOOL_PERTURBATION_C if guarded else t+lapse,
        }
        for k,value in values.items():
            if not -100<value<75:
                raise ValueError("P9F1_PHYSICS_RESULT_OUT_OF_ALLOWED_DOMAIN")
            predictions[k].append(value)
    return predictions,flags,{
        "station_minus_ERA5_regular_grid_geopotential_height_m":dz,
        "fixed_lapse_adjustment_C":lapse,
        "terrain_12km_p75_relief_m":terrain_relief,
        "predeclared_valley_geometry_susceptible":valley,
        "ERA5_source_guarded_hour_count":sum(flags),
        "ERA5_source_guarded_hour_fraction":sum(flags)/n,
        "all_predictors_from_reanalysis_or_original_DEM_not_station_temperature":True,
        "not_collocated_measured_temperature_inversion":True,
        "source_regular_ARCO_model_height_not_proven_exact_OpenMeteo_internal_grid_height":True,
    }


def score_qualified(obs_byhour,times,pred,flags):
    samples=[(float(obs_byhour[t]),float(p),bool(flag)) for t,p,flag in zip(
        times,pred,flags) if t in obs_byhour]
    if len(samples)<MIN_QC:
        raise ValueError("P9F1_TOO_FEW_QUALIFIED_OBS_FOR_SCORING")
    err=[prediction-observed for observed,prediction,_ in samples]
    guarded=[p-o for o,p,flag in samples if flag]
    return {
        "n_original_QC_observation_matched":len(samples),
        "MAE_C":statistics.fmean(abs(e) for e in err),
        "RMSE_C":math.sqrt(statistics.fmean(e*e for e in err)),
        "bias_C":statistics.fmean(err),
        "n_original_QC_guarded_hours":len(guarded),
        "guarded_MAE_C":statistics.fmean(abs(e) for e in guarded) if guarded else None,
        "unguarded_MAE_C":statistics.fmean(
            abs(p-o) for o,p,g in samples if not g) if len(guarded)<len(samples) else None,
    }


def run(out):
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    meta,msha=station.source_json(station.BASE+"/metadata")
    sites=sites_from_original_meta(meta)
    # Freeze full original independent DEM terrain classification and
    # reanalysis-source grid/orography BEFORE fetching observed 2019 temperatures.
    terrain,terrain_shas=independent_dem_rings(sites)
    selected_points=regular.collect_grid_centers(sites)
    reg=regular.read_real_regular_z(selected_points)
    regular_grid={int(p["source_id"]):p for p in reg["points"]}
    freeze={
        "phase":"P9_1F1_FROZEN_GEOGRAPHIC_AND_TERRAIN_INPUTS_PRE_OBSERVATION",
        "site_IDs":list(IDS),"periods":PERIODS,
        "original_GeoSphere_metadata_SHA256":msha,
        "original_SRTM_DEM_source_response_SHA256":terrain_shas,
        "ERA5_ARCO_regular_geopotential_source_SHA256":
            reg["digest_selected_original_grid_lat_lon_z_sha256"],
        "terrain_by_station":terrain,
        "real_regular_z_by_station":regular_grid,
        "physically_conditional_parameters_registered_before_observed_2019":True,
        "production_epw_ready":False}
    (root/"p9_1f1_frozen_pre2019_terrain_geopotential.json").write_text(
        json.dumps(freeze,indent=2,ensure_ascii=False)+"\n")
    print("P9F1_SOURCE_TERRAIN_FROZEN",json.dumps({
        "stations":len(terrain),"ARCO_regular_heights":len(regular_grid),
        "candidates":list(METHODS)}),flush=True)
    original=[]
    for season,start,end in PERIODS:
        q=urllib.parse.urlencode({
            "station_ids":",".join(str(x) for x in IDS),
            "parameters":"tl,tl_flag",
            "start":start+"T00:00Z","end":end+"T23:00Z","output_format":"geojson"})
        real,osha=station.source_json(station.BASE+"?"+q)
        observations=station.decode_observed(real,set(IDS),start,end)
        for s in sites:
            sid=s["id"]
            row={
                "station":s["name"],"station_id":sid,"season":season,
                "source_original_GeoSphere_QC_SHA256":osha,
                "station_official_height_m":s["altitude_m"],
                "original_SRTM_12km_p75_relief_m":terrain[sid]["ring12km_p75_relief_m"],
                "ERA5_ARCO_regular_selected_cell_height_m":regular_grid[sid][
                    "ARCO_025_original_model_height_m"],
                "n_original_QC_station_hours_available":len(observations[sid]),
                "source_geographical_originals_selected_without_2019_target_temperature":True,
            }
            if len(observations[sid])<MIN_QC:
                row["source_QC_status"]="ORIGINAL_STATION_QC_INSUFFICIENT"
                original.append(row)
                continue
            url=era.request_url(s["lat"],s["lon"],start,end)
            raw_bytes=era.get_original_source(url)
            native_weather,values,rm=era.parse_source(
                raw_bytes,s["lat"],s["lon"],start,end)
            co=regular_grid[sid]
            if (abs(rm["selected_cell_latitude"]-co["original_ARCO_lat"])>1e-4
                or abs((rm["selected_cell_longitude"]-
                        co["original_ARCO_lon"]+180)%360-180)>1e-4):
                raise ValueError("P9F1_OROGRAPHY_NOT_AT_ACTUAL_SELECTED_ERA5_WEATHER_CELL")
            down_bytes=era.get_original_source(alt.altitude_url(url,s["altitude_m"]))
            down,modified,pm=era.parse_source(
                down_bytes,s["lat"],s["lon"],start,end)
            if native_weather["hourly"]["time"]!=down["hourly"]["time"]:
                raise ValueError("P9F1_PROVIDER_DOWNSCALE_TIMELINE_MISMATCH")
            if not (era.statistics_and_coherence(values)["hard_QC_pass"]
                    and era.statistics_and_coherence(modified)["hard_QC_pass"]):
                raise ValueError("P9F1_INVALID_REAL_ORIGINAL_ERA5_SOURCE_QC")
            model,flags,phys=make_fixed_predictions(
                values["temperature_2m"],modified["temperature_2m"],
                values["wind_speed_10m"],values["cloud_cover"],
                values["shortwave_radiation"],native_weather["hourly"]["time"],
                s["altitude_m"],co["ARCO_025_original_model_height_m"],
                terrain[sid]["ring12km_p75_relief_m"])
            scored={k:score_qualified(
                observations[sid],native_weather["hourly"]["time"],v,flags)
                for k,v in model.items()}
            if len({v["n_original_QC_observation_matched"] for v in scored.values()})!=1:
                raise ValueError("P9F1_SCIENTIFIC_QC_COHORT_DIFFERS_ACROSS_MODELS")
            row.update({
                "source_QC_status":"REAL_OBSERVATIONAL_HOLDOUT_SCORED",
                "source_original_ERA5_weather_SHA256":rm["raw_original_response_sha256"],
                "source_original_ERA5_provider_downscale_SHA256":
                    pm["raw_original_response_sha256"],
                "source_conditioned_regime":{
                    **phys,
                    "n_original_QC_guarded_hours":
                        scored["L0_RAW"]["n_original_QC_guarded_hours"],
                },
                "by_method":scored,
            })
            original.append(row)
            print("P9F1_2019",json.dumps({
                "station":s["name"],"id":sid,"period":season,
                "n_QC":len(observations[sid]),
                "n_risk":row["source_conditioned_regime"]["n_original_QC_guarded_hours"],
                "mae_C":{k:round(x["MAE_C"],3) for k,x in scored.items()},
            }),flush=True)
    if len(original)!=len(IDS)*len(PERIODS):
        raise ValueError("P9F1_PREDECLARED_COMPLETE_SOURCE_CENSUS_MISSING")
    eligible=[x for x in original if x["source_QC_status"]=="REAL_OBSERVATIONAL_HOLDOUT_SCORED"]
    result={
        "phase":"IGE_P9_1F1_PHYSICALLY_CONDITIONED_TERRAIN_INVERSION_GUARD_2019",
        "n_predeclared_original_stations":len(IDS),
        "n_predeclared_station_seasons":len(IDS)*len(PERIODS),
        "n_QC_qualified_station_seasons":len(eligible),
        "n_original_QC_paired_hours":sum(
            x["by_method"]["L0_RAW"]["n_original_QC_observation_matched"]
            for x in eligible),
        "n_source_conditioned_regime_hours":sum(
            x["source_conditioned_regime"]["n_original_QC_guarded_hours"]
            for x in eligible),
        "original_ERA5_ARCO_regular_geopotential_source_hash":freeze[
            "ERA5_ARCO_regular_geopotential_source_SHA256"],
        "original_independent_SRTM_source_hashes":terrain_shas,
        "method_names_registered_before_all_2019_stations":list(METHODS),
        "method_2019_equal_station_season_macro_MAE_C":{
            k:statistics.fmean(x["by_method"][k]["MAE_C"] for x in eligible)
            if eligible else None for k in METHODS},
        "2019_winter_station_macro_MAE_C":{
            k:statistics.fmean(x["by_method"][k]["MAE_C"] for x in eligible
                               if x["season"]=="winter_2019")
            if any(x["season"]=="winter_2019" for x in eligible)
            else None for k in METHODS},
        "method_cases_improved_vs_L1_regular_lapse":{
            k:sum(x["by_method"][k]["MAE_C"]<
                  x["by_method"]["L1_REGULAR_LAPSE"]["MAE_C"] for x in eligible)
            for k in METHODS},
        "method_worst_harm_vs_RAW_C":{
            k:max((x["by_method"][k]["MAE_C"]-
                   x["by_method"]["L0_RAW"]["MAE_C"] for x in eligible),
                  default=None) for k in METHODS},
        "inversion_status":"SOURCE_CONDITIONED_COLD_POOL_SUSCEPTIBILITY_ONLY_NOT_MEASURED_INVERSION",
        "meteorological_source_and_station_temporal_support_exactly_equated":False,
        "google_ARCO_open_meteo_same_regrid_processing_independently_proven":False,
        "worldwide_new_region_weather_skill_qualified":False,
        "no_target_station_observation_fitted_to_physical_hyperparameters":True,
        "production_epw_ready":False,"members":original}
    (root/"p9_1f1_2019_original_station_physically_conditioned_result.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print("P9F1_SCIENTIFIC_RESULT",json.dumps({
        "qualified":len(eligible),"registered":len(original),
        "hours":result["n_original_QC_paired_hours"],
        "source_guard_QC_hours":result["n_source_conditioned_regime_hours"],
        "macro_mae_C":result["method_2019_equal_station_season_macro_MAE_C"],
        "ready":False}),flush=True)
    if len(eligible)<18 or not any(x["station_id"]==48
                                 and x["season"]=="winter_2019"
                                 for x in eligible):
        raise RuntimeError("P9F1_NOT_ENOUGH_2019_REAL_QC_VALIDATION")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",required=True)
    run(p.parse_args().out)
