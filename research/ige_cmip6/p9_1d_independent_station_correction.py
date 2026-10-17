#!/usr/bin/env python3
"""P9.1D held-out 2022 original GeoSphere observations vs fixed physical lapse variants.

Uses native N320 ERA5 z/9.80665 as a PROXY only; not independently verified as
the exact Open-Meteo 0.25 cell elevation. All corrections remain nonproduction.
Frozen methods selected before 2022 observations and never fit on target data.
"""
from __future__ import annotations
import argparse,datetime as dt,json,math,statistics,urllib.parse
from pathlib import Path
import p9_1a_global_historical_backbone as era
import p9_1b_geosphere_original_station_holdouts as station
import p9_1c_provider_altitude_2024_ablation as alt

PERIODS=(("winter_2022","2022-01-10","2022-01-16"),
         ("summer_2022","2022-07-10","2022-07-16"))
LAPSE_K_M=-.0065
MAX_CORR_C=3.0
INVERSION_ELEV_DIFFERENCE_M=150.
CALM_INVERSION_WIND_MS=3.
CLEAR_INVERSION_CLOUD_PERCENT=50.
MIN_QC_HOURS=120
METHODS=("L0_RAW_ERA5_GRID","P0_PROVIDER_SITE_ELEVATION",
         "L1_ERA5_N320_FIXED_LAPSE_PROXY","L2_BOUNDED_FIXED_LAPSE_PROXY",
         "L3_CONDITIONED_NIGHT_VALLEY_GUARD_PROXY")

def score_pair(times,predictions,observations):
    if not times or len(times)!=len(predictions):
        raise ValueError("P9D_TARGET_PREDICTION_HOURLY_SAMPLE_MISMATCH")
    sample=[(float(p),float(observations[t])) for t,p in zip(times,predictions)
            if t in observations and p is not None]
    if len(sample)<MIN_QC_HOURS:
        raise ValueError("P9D_INSUFFICIENT_ORIGINAL_QC_OBSERVED_PAIRS")
    differences=[p-o for p,o in sample]
    return {
        "matched_original_QC_hours":len(sample),
        "MAE_C":statistics.fmean(abs(x) for x in differences),
        "RMSE_C":math.sqrt(statistics.fmean(x*x for x in differences)),
        "bias_C":statistics.fmean(differences),
        "mean_station_temperature_C":statistics.fmean(o for _,o in sample),
        "any_observed_station_temperature_in_ERA5_prediction":False,
    }

def physically_fixed_candidates(raw_temp,adjusted_temp,winds,clouds,
                                utc_hours,station_alt_m,native_height_m,
                                season):
    n=len(raw_temp)
    if len(adjusted_temp)!=n or len(winds)!=n or len(clouds)!=n or len(utc_hours)!=n:
        raise ValueError("P9D_CANDIDATE_VARIABLE_TIME_MISMATCH")
    dz=station_alt_m-native_height_m
    if not math.isfinite(dz) or abs(dz)>6000:
        raise ValueError("P9D_NATIVE_GRID_Z_DELTA_INVALID")
    free_adjust=LAPSE_K_M*dz
    bounded=min(MAX_CORR_C,max(-MAX_CORR_C,free_adjust))
    results={k:[] for k in METHODS}
    guarded=0
    for temp,provider,wind,cloud,hour in zip(raw_temp,adjusted_temp,
                                               winds,clouds,utc_hours):
        values=(float(temp),float(provider),float(wind),float(cloud))
        if not all(map(math.isfinite,values)):
            raise ValueError("P9D_SOURCE_VARIABLE_NONFINITE")
        if not (0<=wind<100 and 0<=cloud<=100 and 0<=hour<=23):
            raise ValueError("P9D_SOURCE_HOUR_WIND_CLOUD_INVALID")
        inversion_guard=(season.startswith("winter")
                         and dz<-INVERSION_ELEV_DIFFERENCE_M
                         and (hour>=21 or hour<=4)
                         and wind<CALM_INVERSION_WIND_MS
                         and cloud<CLEAR_INVERSION_CLOUD_PERCENT)
        if inversion_guard:guarded+=1
        d={
            METHODS[0]:temp,
            METHODS[1]:provider,
            METHODS[2]:temp+free_adjust,
            METHODS[3]:temp+bounded,
            METHODS[4]:temp+(0. if inversion_guard else bounded),
        }
        for k,v in d.items():
            if not -120<v<90:
                raise ValueError("P9D_LAPSE_CANDIDATE_UNPHYSICAL_SOURCE_POINT")
            results[k].append(v)
    return results,{
        "station_minus_native_N320_height_m":dz,
        "raw_fixed_6p5_K_per_km_correction_C":free_adjust,
        "bounded_correction_C":bounded,
        "guarded_hours":guarded,
        "native_N320_not_guaranteed_OpenMeteo_cell_height":True,
        "fixed_coefficients_no_station_target_fitting":True,
    }

def run(terrain_json,out):
    terrain=json.loads(Path(terrain_json).read_text())
    if not (terrain.get("genuinely_read_original_native_N320_geopotential")
            and terrain.get("independently_queried_DEM")
            and len(terrain.get("sites",[]))==3):
        raise ValueError("P9D_NATIVE_GRID_AND_DEM_AUTHENTIC_SOURCE_NOT_AVAILABLE")
    geo={x["station_id"]:x for x in terrain["sites"]}
    meta,metasha=station.source_json(station.BASE+"/metadata")
    sites=station.extract_metadata(meta)
    outrows=[];src=[]
    for label,start,end in PERIODS:
        query=urllib.parse.urlencode({
            "station_ids":",".join(map(str,station.IDS)),
            "parameters":"tl,tl_flag",
            "start":start+"T00:00Z","end":end+"T23:00Z",
            "output_format":"geojson"})
        obsdata,obs_sha=station.source_json(station.BASE+"?"+query)
        actual=station.decode_observed(obsdata,set(station.IDS),start,end)
        for sid in station.IDS:
            s=sites[sid];z=geo[sid]
            url=era.request_url(s["lat"],s["lon"],start,end)
            orig=era.get_original_source(url)
            raw,fields,rawmeta=era.parse_source(orig,s["lat"],s["lon"],start,end)
            alturl=alt.altitude_url(url,s["altitude_m"])
            altered=era.get_original_source(alturl)
            provider,afields,pmeta=era.parse_source(altered,s["lat"],s["lon"],start,end)
            if not (era.statistics_and_coherence(fields)["hard_QC_pass"]
                    and era.statistics_and_coherence(afields)["hard_QC_pass"]):
                raise ValueError("P9D_ORIGINAL_ERA5_HOURLY_SOURCE_INVALID")
            if raw["hourly"]["time"]!=provider["hourly"]["time"]:
                raise ValueError("P9D_DIFFERENT_SOURCE_TIMELINES")
            if (rawmeta["selected_cell_latitude"]!=pmeta["selected_cell_latitude"]
                    or rawmeta["selected_cell_longitude"]!=pmeta["selected_cell_longitude"]):
                raise ValueError("P9D_PROVIDER_ALT_CORRECTION_CHANGED_ERA5_MODEL_CELL")
            timeline=raw["hourly"]["time"]
            methods,modelmeta=physically_fixed_candidates(
                fields["temperature_2m"],afields["temperature_2m"],
                fields["wind_speed_10m"],fields["cloud_cover"],
                [int(t[11:13]) for t in timeline],
                s["altitude_m"],z["native_z_div_g0_height_m"],label)
            member={"station_id":sid,"station":s["name"],"period":label,
              "source_ERA5_original_grid_sha":rawmeta["raw_original_response_sha256"],
              "source_OpenMeteo_original_provider_height_sha":pmeta["raw_original_response_sha256"],
              "source_original_GeoSphere_QC_sha":obs_sha,
              "source_native_ERA5_N320_z_m":z["native_z_div_g0_height_m"],
              "independent_SRTM_DEM_m":z["SRTM_v3_90m_elevation_m"],
              "true_station_elevation_m":s["altitude_m"],
              "exact_OpenMeteo_0p25_grid_orography_independently_verified":False,
              "N320_to_model_0p25_mapping_unverified":True,
              **modelmeta,
              "per_method":{key:score_pair(timeline,series,actual[sid])
                            for key,series in methods.items()},
            }
            counts={v["matched_original_QC_hours"] for v in member["per_method"].values()}
            if len(counts)!=1:
                raise ValueError("P9D_MISMATCHED_PHYSICAL_HOLDOUT_HOURS")
            outrows.append(member)
            print("P9D_2022_SOURCE_HOLDOUT",json.dumps({
                "station":s["name"],"season":label,"n":next(iter(counts)),
                "MAE_C":{key:round(val["MAE_C"],3)
                         for key,val in member["per_method"].items()},
                "dz_m":round(modelmeta["station_minus_native_N320_height_m"],1),
                "inversion_guard_hours":modelmeta["guarded_hours"],
            }),flush=True)
        src.append({"period":label,"GeoSphere_QC_SHA256":obs_sha})
    if len(outrows)!=6:raise ValueError("P9D_MISSING_EXPECTED_STATION_SEASON_HOLDOUT")
    baseline=[m["per_method"][METHODS[0]]["MAE_C"] for m in outrows]
    r={
        "phase":"IGE_P9_1D_2022_NATIVE_GRID_HEIGHT_PHYSICAL_ABLATION_PILOT",
        "methods_predeclared":list(METHODS),
        "source_native_grid_ERA5_z_sha256":terrain["native_grid"][
            "native_N320_array_values_sha256"],
        "independent_SRTM_original_provider_sha256":terrain["DEM"]["response_sha256"],
        "metadata_original_SHA256":metasha,
        "original_obs_source_time_blocks":src,
        "n_site_seasons":len(outrows),
        "n_paired_qualified_hours":sum(
            m["per_method"][METHODS[0]]["matched_original_QC_hours"]
            for m in outrows),
        "macro_site_season_RAW_MAE_C":statistics.fmean(baseline),
        "macro_MAE_by_frozen_method_C":{
            key:statistics.fmean(m["per_method"][key]["MAE_C"] for m in outrows)
            for key in METHODS},
        "site_seasons_improved_vs_raw_by_method":{
            key:sum(m["per_method"][key]["MAE_C"]<
                    m["per_method"][METHODS[0]]["MAE_C"] for m in outrows)
            for key in METHODS},
        "weather_source_and_native_grid_heights_not_exactly_same_cell":True,
        "native_0p25_cell_geopotential_height_not_validated":True,
        "no_new_spatial_station_holdouts":True,
        "no_target_observation_fitting":True,
        "ERA5_weather_forecast_true_temporal_support_vs_station_not_equated":True,
        "site_spatial_method_qualified_for_global_production":False,
        "production_epw_ready":False,
        "members":outrows}
    o=Path(out);o.mkdir(parents=True,exist_ok=True)
    (o/"p9_1d_2022_native_height_source_conditioned_holdout.json").write_text(
        json.dumps(r,indent=2,ensure_ascii=False)+"\n")
    print("P9D_2022_HOLDOUT_SUMMARY",json.dumps({
        "macro_MAE_by_method":r["macro_MAE_by_frozen_method_C"],
        "n_paired":r["n_paired_qualified_hours"],
        "production_ready":False}),flush=True)
    return r

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--terrain-json",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args();run(a.terrain_json,a.out)
