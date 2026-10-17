#!/usr/bin/env python3
"""P9.1D2: Six independent NEW Alpine sites, same fixed weather correction methods.

Site IDs preregistered in docs/IGE_P9_1D2_NEW_ALPINE_STATIONS_2022_PRE_REGISTERED_RU.md.
Only 2022 original QC obs. 0.25 Open-Meteo cell z is not known from N320 z.
"""
import argparse,datetime as dt,json,statistics,urllib.parse
from pathlib import Path
import p9_1d_native_orography_dem as original
import p9_1d_independent_station_correction as fixed
import p9_1a_global_historical_backbone as era
import p9_1b_geosphere_original_station_holdouts as station
import p9_1c_provider_altitude_2024_ablation as alt

IDS=(119,14305,28,17005,66,184)
MINIMUM=96

def full_station_metadata(metadata):
    catalog={int(s["id"]):s for s in metadata["stations"]}
    found=[]
    for sid in IDS:
        s=catalog.get(sid)
        if s is None:
            raise ValueError("P9D2_PRE_REGISTERED_GEOSPHERE_STATION_ID_MISSING_"+str(sid))
        found.append({"id":sid,"name":s["name"],"lat":float(s["lat"]),
                      "lon":float(s["lon"]),"altitude_m":float(s["altitude"])})
    return found

def read_observed_record(data,ids,start,end):
    return station.decode_observed(data,set(ids),start,end)

def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    meta,msha=station.source_json(station.BASE+"/metadata")
    sites=full_station_metadata(meta)
    dem=original.independent_dem(sites)
    native=original.actual_native_geo(sites)
    byid={p["station_id"]:p for p in native["sites"]}
    demby={p["station_id"]:p for p in dem["sites"]}
    comparisons=[];source_obs=[]
    for season,start,end in fixed.PERIODS:
        params=urllib.parse.urlencode({
            "station_ids":",".join(str(x) for x in IDS),
            "parameters":"tl,tl_flag","start":start+"T00:00Z",
            "end":end+"T23:00Z","output_format":"geojson"})
        source,obsha=station.source_json(station.BASE+"?"+params)
        observations=read_observed_record(source,IDS,start,end)
        for s in sites:
            sid=s["id"]
            nobs=len(observations[sid])
            row={
                "station":s["name"],"station_id":sid,"period":season,
                "registered_original_station_elevation_m":s["altitude_m"],
                "SRTM_v3_90m_site_elevation_m":demby[sid]["SRTM_v3_90m_elevation_m"],
                "ERA5_native_N320_nearest_height_m":byid[sid]["native_z_div_g0_height_m"],
                "source_original_QC_observation_SHA256":obsha,
                "source_N320_nearest_station_km":byid[sid]["nearest_native_N320_km"],
                "source_NATIVE_N320_does_not_match_OpenMeteo_0p25_cell":True,
                "available_original_QC_hours":nobs,
            }
            if nobs<MINIMUM:
                row["status"]="SOURCE_INCOMPLETE_QC_LT_96"
                comparisons.append(row)
                print("P9D2_SOURCE_INCOMPLETE",json.dumps({
                    "station_id":sid,"season":season,"n_QC":nobs}),flush=True)
                continue
            u=era.request_url(s["lat"],s["lon"],start,end)
            ori=era.get_original_source(u)
            raw,fields,metadata=era.parse_source(ori,s["lat"],s["lon"],start,end)
            down=era.get_original_source(alt.altitude_url(u,s["altitude_m"]))
            adjusted,afields,downmeta=era.parse_source(
                down,s["lat"],s["lon"],start,end)
            if not (era.statistics_and_coherence(fields)["hard_QC_pass"]
                    and era.statistics_and_coherence(afields)["hard_QC_pass"]):
                raise ValueError("P9D2_SOURCE_ORIGINAL_HOURLY_WEATHER_FAILED_QC")
            ts=raw["hourly"]["time"]
            if ts!=adjusted["hourly"]["time"]:
                raise ValueError("P9D2_PROVIDER_HOURS_MISMATCH")
            methods,physical=fixed.physically_fixed_candidates(
                fields["temperature_2m"],afields["temperature_2m"],
                fields["wind_speed_10m"],fields["cloud_cover"],
                [int(t[11:13]) for t in ts],
                s["altitude_m"],byid[sid]["native_z_div_g0_height_m"],season)
            scores={k:fixed.score_pair(ts,v,observations[sid],min_pairs=MINIMUM)
                    for k,v in methods.items()}
            counts={x["matched_original_QC_hours"] for x in scores.values()}
            if len(counts)!=1:
                raise ValueError("P9D2_UNEQUAL_STATION_COMPARISON_HOURS")
            row.update({
                "status":"VERIFIED_REAL_SOURCE_SCORE",
                "N320_expected_lapse_height_delta_m":physical[
                    "station_minus_native_N320_height_m"],
                "inversion_guard_hours":physical["guarded_hours"],
                "original_ERA5_weather_source_SHA256":metadata["raw_original_response_sha256"],
                "original_provider_downscaled_source_SHA256":downmeta["raw_original_response_sha256"],
                "scores":scores,
            })
            comparisons.append(row)
            print("P9D2_NEW_SITE",json.dumps({
                "station":s["name"],"season":season,"n":next(iter(counts)),
                "raw_MAE_C":round(scores[fixed.METHODS[0]]["MAE_C"],3),
                "provider_MAE_C":round(scores[fixed.METHODS[1]]["MAE_C"],3),
                "simple_lapse_MAE_C":round(scores[fixed.METHODS[2]]["MAE_C"],3),
                "bounded_MAE_C":round(scores[fixed.METHODS[3]]["MAE_C"],3),
                "guarded_MAE_C":round(scores[fixed.METHODS[4]]["MAE_C"],3),
            }),flush=True)
        source_obs.append({"season":season,"original_GeoSphere_SHA256":obsha})
    eligible=[r for r in comparisons if r["status"]=="VERIFIED_REAL_SOURCE_SCORE"]
    if len(comparisons)!=12:
        raise ValueError("P9D2_PRE_REGISTERED_ALL_12_STATION_PERIODS_MISSING")
    aggregate={
        "phase":"IGE_P9_1D2_INDEPENDENT_SIX_NEW_ALPINE_STATIONS_2022",
        "source_original_station_metadata_SHA256":msha,
        "original_native_ERA5_N320_geopotential_sha256":native["native_N320_array_values_sha256"],
        "original_independent_SRTM_DEM_provider_sha256":dem["response_sha256"],
        "n_predeclared_stations":6,"n_predeclared_station_seasons":12,
        "n_eligible_site_seasons":len(eligible),
        "n_station_seasons_ineligible_original_QC":12-len(eligible),
        "n_true_independent_QC_matched_hours":sum(
            x["scores"][fixed.METHODS[0]]["matched_original_QC_hours"] for x in eligible),
        "source_original_observation_response":source_obs,
        "predeclared_fixed_model_methods":list(fixed.METHODS),
        "macro_site_season_MAE_by_method":{
            k:statistics.fmean(x["scores"][k]["MAE_C"] for x in eligible) if eligible else None
            for k in fixed.METHODS},
        "site_seasons_better_than_raw_by_method":{
            k:sum(x["scores"][k]["MAE_C"]<x["scores"][fixed.METHODS[0]]["MAE_C"]
                  for x in eligible) for k in fixed.METHODS},
        "all_scientific_holdouts_predeclared_not_chosen_for_improvement":True,
        "exact_0p25_OpenMeteo_cell_grid_elevation_verified":False,
        "native_grib_CDS_original_file_bytes_verified":False,
        "arbitrary_global_site_skill_qualified":False,
        "production_epw_ready":False,"members":comparisons}
    (out/"p9_1d2_six_new_alpine_sites_2022_source_holdouts.json").write_text(
        json.dumps(aggregate,indent=2,ensure_ascii=False)+"\n")
    print("P9D2_INDEPENDENT_NEW_SITES",json.dumps({
        "scored":len(eligible),"expected":12,
        "n_original_QC_hours":aggregate["n_true_independent_QC_matched_hours"],
        "macro_MAE_C":aggregate["macro_site_season_MAE_by_method"],
        "production_ready":False}),flush=True)
    if len(eligible)<8:raise RuntimeError("P9D2_ORIGINAL_NEW_SITE_HOLDOUT_NOT_SUFFICIENT")
    return aggregate

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",required=True)
    run(p.parse_args().out)
