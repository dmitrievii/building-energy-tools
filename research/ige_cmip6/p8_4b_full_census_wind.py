#!/usr/bin/env python3
"""IGE P8.4B: ALL official SwissMetNet station IDs screened for 2022/2025 wind.

Historical same-hour station-donor hindcast ONLY; never future wind or EPW.
Original 2020-2029 provider CSVs stay in CI RAM. Export ONLY aggregated
scores, donor choices, provenance hashes and provider availability metadata.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

from p8_1e_swiss_external import fetch,parse_meta,haversine
from p8_2e_crossyear import ROOT,annual_hours
from p8_3a_wind_spatial import CALM_MPS,usable_wind,wind_coverage,number,circular_error_deg
from p8_3d_wind_terrain_donors import (
    DONORS,MIN_WIND_YEAR,MIN_TARGET,METHODS,DEM_ZOOM,
    metadata_dem_features,choose_donors,score_site,summarize,
)
from p8_1c_dem import TileCache

YEARS=(2022,2025)
TARGETS=("AIG","THU","INT","RAG","ZER","VIT")
GEOGRAPHY={
    "AIG":"western_valley","THU":"bernese_lowland","INT":"alpine_valley",
    "RAG":"rhein_valley","ZER":"high_alpine","VIT":"lake_valley",
}
BUFFER_KM=25.0
STATION_MIN_COUNT=150
QUALIFIED_MIN_COUNT=65
CENSUS_THREADS=8
MIN_SITE_YEAR_FRACTION=.80
MIN_DONOR_YEAR_FRACTION=.90
SEED=20261017
BOOTSTRAP_REPS=400
BOOTSTRAP_DAYS=7
SPEED_BINS=((0.,.5,"calm"),(.5,2.,"weak"),(2.,5.,"moderate"),(5.,float("inf"),"strong"))
SEASONS={12:"DJF",1:"DJF",2:"DJF",3:"MAM",4:"MAM",5:"MAM",6:"JJA",7:"JJA",8:"JJA",9:"SON",10:"SON",11:"SON"}
BASE_METHODS=("distance_idw4","altitude_idw4","terrain_idw4")
EVALUATED_METHODS=BASE_METHODS+tuple("buffer25_"+m for m in BASE_METHODS)


def parse_original_two_years(raw,sid):
    """One-pass semicolon original OGD parser; preserve old fkl/dkl semantics.

    Duplicate original timestamps are errors. For memory bounds discard
    everything other than two frozen years while parsing the full-decade CSV.
    """
    try:
        source=raw.decode("utf-8-sig","strict")
    except UnicodeDecodeError as exc:
        raise ValueError("B_SOURCE_WIND_CSV_NOT_UTF8_"+sid) from exc
    lines=csv.DictReader(io.StringIO(source),delimiter=";")
    required={"station_abbr","reference_timestamp","fkl010h0","dkl010h0"}
    if not required.issubset(lines.fieldnames or []):
        raise ValueError("B_ORIGINAL_WIND_COLUMNS_MISSING_"+sid)
    flag_columns=[
        f for f in lines.fieldnames if f.lower() in (
            "fkl010h0_flag","dkl010h0_flag","fkl010h0_qc","dkl010h0_qc")]
    out={year:{} for year in YEARS}
    for row in lines:
        if (row.get("station_abbr") or "").strip().upper()!=sid:
            continue
        stamp=row.get("reference_timestamp") or ""
        if len(stamp)<16:
            continue
        if stamp[6:10] not in ("2022","2025"):
            continue
        try:
            t=dt.datetime.strptime(stamp,"%d.%m.%Y %H:%M")
        except ValueError:
            raise ValueError("B_BAD_SELECTED_YEAR_REFERENCE_TIMESTAMP_"+sid)
        if t.year not in YEARS or t.minute!=0:
            raise ValueError("B_HOURLY_TIMESTAMP_MISALIGNED_"+sid)
        if t in out[t.year]:
            raise ValueError("B_DUPLICATED_WIND_SOURCE_HOUR_"+sid)
        speed=number(row["fkl010h0"],0.,90.)
        azimuth=number(row["dkl010h0"],0.,360.)
        out[t.year][t]={"speed":speed,"direction":azimuth%360 if azimuth is not None else None}
    return out,flag_columns


def original_station(sid):
    url=f"{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_2020-2029.csv"
    raw,sha=fetch(url,max_bytes=40_000_000)
    series,flags=parse_original_two_years(raw,sid)
    del raw
    census={"site":sid,"download_ok":True,"original_sha256":sha,
            "individual_qc_flag_columns":flags,
            "per_hour_qc_qualified":False}
    coverage={}
    for year in YEARS:
        hours=annual_hours(year)
        counts=wind_coverage(series[year],hours)
        coverage[year]={"site":sid,"year":year,**counts,
                        "annual_wind_qualified":counts["usable_wind_hours"]>=math.ceil(MIN_DONOR_YEAR_FRACTION*len(hours))}
    return sid,series,census,coverage


def full_catalog_census(meta):
    """All metadata IDs attempted, no nearest-station discovery shortcut."""
    ids=tuple(sorted(meta))
    if len(ids)<STATION_MIN_COUNT:
        raise ValueError("B_FULL_CATALOG_HAS_TOO_FEW_STATIONS_"+str(len(ids)))
    observations={year:{} for year in YEARS}
    source=[]
    coverage=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=CENSUS_THREADS) as pool:
        futures={pool.submit(original_station,sid):sid for sid in ids}
        for future in concurrent.futures.as_completed(futures):
            sid=futures[future]
            try:
                _,series,record,counts=future.result()
                source.append(record)
                for year in YEARS:
                    observations[year][sid]=series[year]
                    coverage.append(counts[year])
            except Exception as exc:
                source.append({"site":sid,"download_ok":False,
                               "original_sha256":None,
                               "error":type(exc).__name__+": "+str(exc)[:250],
                               "per_hour_qc_qualified":False})
                for year in YEARS:
                    coverage.append({"site":sid,"year":year,"usable_wind_hours":0,
                                     "speed_hours":0,"annual_wind_qualified":False})
    source.sort(key=lambda x:x["site"])
    coverage.sort(key=lambda x:(x["year"],x["site"]))
    if len(source)!=len(ids) or {r["site"] for r in source}!=set(ids):
        raise AssertionError("B_CATALOG_IDS_NOT_EXHAUSTIVELY_ATTEMPTED")
    qualified={}
    for year in YEARS:
        qualified[year]={
            r["site"] for r in coverage if r["year"]==year
            and r["annual_wind_qualified"]
        }
        if len(qualified[year])<QUALIFIED_MIN_COUNT:
            raise ValueError("B_FULL_CENSUS_TOO_FEW_QUALIFIED_DONORS_"+str(year))
        if not set(TARGETS).issubset(observations[year]):
            raise ValueError("B_PREDECLARED_TARGET_DATA_UNAVAILABLE_"+str(year))
        if not set(TARGETS).issubset(qualified[year]):
            raise ValueError("B_PREDECLARED_TARGET_NOT_WIND_QUALIFIED_"+str(year))
    return observations,qualified,source,coverage


def qualified_donor_ids(metadata,qualified,all_targets=TARGETS):
    """Global target-site withholding prevents cross-target leakage."""
    return set(qualified)&set(metadata)-set(all_targets)


def apply_region_buffer(target,metadata,donors,radius_km=BUFFER_KM):
    if target["station_id"] in donors:
        raise AssertionError("B_SELF_TARGET_DONOR_LEAK")
    return {
        sid for sid in donors
        if haversine(target["lat"],target["lon"],
                     metadata[sid]["lat"],metadata[sid]["lon"])>=radius_km
    }


def selected_methods(target,metadata,donors,features):
    if target["station_id"] in donors:
        raise AssertionError("B_TARGET_USED_TO_SELECT_DONORS")
    blocked=apply_region_buffer(target,metadata,donors)
    result={}
    for method in BASE_METHODS:
        result[method]=choose_donors(target,metadata,donors,features,method)
        result["buffer25_"+method]=choose_donors(
            target,metadata,blocked,features,method)
    for name,selection in result.items():
        if len(selection)!=DONORS:
            raise ValueError("B_FOUR_DONOR_CONTRACT_FAILED")
        for distance,station in selection:
            sid=station["station_id"]
            if sid in TARGETS:
                raise AssertionError("B_CROSS_TARGET_OBSERVATION_LEAK")
            if name.startswith("buffer25_") and distance<BUFFER_KM-1e-7:
                raise AssertionError("B_GEOGRAPHIC_EXCLUSION_FAILED")
    return result


def common_hour_predictions(site,year,hours,selections,weather):
    """Strict seven-predictor? Here frozen SIX 4-donor models share one clock."""
    predicted={
        name:score_site(site,hours,donors,weather)
        for name,donors in selections.items()
    }
    common=set(hours)
    for series in predicted.values():
        common.intersection_update(series)
    if len(common)<math.ceil(MIN_SITE_YEAR_FRACTION*len(hours)):
        raise ValueError("B_CROSS_SELECTOR_HOURLY_COVERAGE_FAILED_"+site+"_"+str(year))
    if not common:
        raise ValueError("B_NO_MATCHED_HOURS")
    return predicted,tuple(sorted(common))


def paired_effects(predicted,hours,method="altitude_idw4",reference="distance_idw4"):
    if method not in predicted or reference not in predicted:
        raise ValueError("B_NOT_COMPARABLE")
    return tuple((
        t,abs(predicted[method][t]["scalar"]-predicted[method][t]["reference_speed"])
         -abs(predicted[reference][t]["scalar"]-predicted[reference][t]["reference_speed"])
    ) for t in hours)


def paired_7day_bootstrap(pairs,year,site,reps=BOOTSTRAP_REPS):
    """Block-resample seven consecutive CALENDAR days, preserving paired gaps."""
    if reps<10:
        raise ValueError("B_TOO_FEW_BLOCK_REPETITIONS")
    days=(dt.date(year,1,1)+dt.timedelta(days=i) for i in range(365))
    order=tuple(days)
    daily={day:[0.,0] for day in order}
    for stamp,difference in pairs:
        if stamp.date() not in daily:
            raise ValueError("B_EFFECT_TIME_OUTSIDE_TEST_YEAR")
        daily[stamp.date()][0]+=difference
        daily[stamp.date()][1]+=1
    anchors=tuple(range(365-BOOTSTRAP_DAYS+1))
    windows=[]
    for anchor in anchors:
        sums=[daily[order[j]] for j in range(anchor,anchor+BOOTSTRAP_DAYS)]
        windows.append((sum(s for s,n in sums),sum(n for s,n in sums)))
    if not all(n>=7*24*.75 for s,n in windows):
        # A few missing observations are allowable; retain their real counts.
        # Reject a bootstrap with almost no genuinely contiguous observed days.
        eligible=[w for w in windows if w[1]>=7*24*.75]
    else:
        eligible=windows
    if len(eligible)<180:
        raise ValueError("B_TOO_FEW_SEVEN_DAY_CONTIGUOUS_CALENDAR_BLOCKS")
    seed=int.from_bytes(hashlib.sha256(
        f"IGE:P8.4B:{SEED}:{year}:{site}".encode()).digest()[:8],"big")
    rng=random.Random(seed)
    estimate=sum(v for t,v in pairs)/len(pairs)
    samples=[]
    for _ in range(reps):
        picked=[eligible[rng.randrange(len(eligible))]
                for _ in range(math.ceil(365/BOOTSTRAP_DAYS))]
        denom=sum(n for s,n in picked)
        if denom<365*24*.50:
            raise ValueError("B_BOOTSTRAP_MISSING_TOO_MANY_REAL_HOURS")
        samples.append(sum(s for s,n in picked)/denom)
    samples.sort()
    return {"n_paired_hourly_effects":len(pairs),
            "estimated_delta_MAE_mps":estimate,
            "block_calendar_days":BOOTSTRAP_DAYS,
            "bootstrap_reps":reps,
            "CI95_low_mps":samples[int(.025*(reps-1))],
            "CI95_high_mps":samples[int(.975*(reps-1))],
            "negative_is_improved":True,
            "site_year_independent_effect":True}


def score_extended(site,year,hours,predicted):
    """Only strict matched clock, no unequal-method denominators."""
    scores=[]
    common_ref_nonc=[t for t in hours if predicted[EVALUATED_METHODS[0]][t]["reference_direction"] is not None]
    strict_vectors={
        kind:tuple(t for t in common_ref_nonc if all(
            predicted[method][t][kind] is not None for method in EVALUATED_METHODS))
        for kind in ("vector_direction","unit_direction")
    }
    for method in EVALUATED_METHODS:
        rows=predicted[method]
        general=summarize(rows,site,method,strict_common=hours)
        diff=[rows[t]["scalar"]-rows[t]["reference_speed"] for t in hours]
        general.update({
            "year":year,"geographic_group":GEOGRAPHY[site],
            "RMSE_speed_mps":math.sqrt(statistics.mean(x*x for x in diff)),
            "n_original_UTC_hourly_match":len(hours),
            "n_reference_noncalm":len(common_ref_nonc),
            "score_type":"retrospective_same_hour_spatial_interpolation",
        })
        for kind,paired in strict_vectors.items():
            angles=[circular_error_deg(rows[t][kind],rows[t]["reference_direction"]) for t in paired]
            general[kind+"_all_six_method_strict_paired_n"]=len(angles)
            general[kind+"_all_six_method_strict_paired_MAE_deg"]=statistics.mean(angles) if angles else None
        scores.append(general)
    strata=[]
    by_group=defaultdict(list)
    for t in hours:
        v=predicted[EVALUATED_METHODS[0]][t]["reference_speed"]
        for lo,hi,name in SPEED_BINS:
            if lo<=v<hi:
                speedgroup=name
                break
        else:
            raise ValueError("B_INVALID_REFERENCE_SPEED")
        by_group[("season",SEASONS[t.month])].append(t)
        by_group[("speed_bin",speedgroup)].append(t)
    for method in EVALUATED_METHODS:
        for (group_type,group),subset in sorted(by_group.items()):
            if not subset:continue
            rows=predicted[method]
            errors=[rows[t]["scalar"]-rows[t]["reference_speed"] for t in subset]
            nc=[t for t in subset if rows[t]["reference_direction"] is not None]
            valid=[t for t in nc if rows[t]["unit_direction"] is not None]
            strata.append({
                "site":site,"year":year,"method":method,
                "group_type":group_type,"group":group,"n":len(subset),
                "speed_MAE_mps":statistics.mean(abs(x) for x in errors),
                "speed_bias_mps":statistics.mean(errors),
                "unit_azimuth_coverage":len(valid)/len(nc) if nc else None,
                "unit_azimuth_emitted_MAE_deg":(
                    statistics.mean(circular_error_deg(rows[t]["unit_direction"],rows[t]["reference_direction"])
                                    for t in valid) if valid else None),
            })
    return scores,strata


def site_year_results(year,site,metadata,features,qualified,observations):
    hours=annual_hours(year)
    donors=qualified_donor_ids(metadata,qualified)
    target=metadata[site]
    choices=selected_methods(target,metadata,donors,features)
    predicted,common=common_hour_predictions(site,year,hours,choices,observations)
    scored,strata=score_extended(site,year,common,predicted)
    bootstrap=paired_7day_bootstrap(paired_effects(predicted,common),year,site)
    return {
        "site":site,"year":year,"group":GEOGRAPHY[site],
        "scores":scored,"strata":strata,"bootstrap_altitude_vs_distance":bootstrap,
        "donor_selections":{
            name:[{"id":row["station_id"],"distance_km":float(dist),
                   "elevation_masl":float(row["hoehe_m"])}
                  for dist,row in choices[name]]
            for name in EVALUATED_METHODS
        },
        "pairwise_selection_diffs":{
            "altitude_vs_distance_set_changed":(
                set(x["station_id"] for _,x in choices["altitude_idw4"])!=
                set(x["station_id"] for _,x in choices["distance_idw4"])),
            "terrain_vs_altitude_set_changed":(
                set(x["station_id"] for _,x in choices["terrain_idw4"])!=
                set(x["station_id"] for _,x in choices["altitude_idw4"])),
            "buffer_altitude_vs_distance_set_changed":(
                set(x["station_id"] for _,x in choices["buffer25_altitude_idw4"])!=
                set(x["station_id"] for _,x in choices["buffer25_distance_idw4"])),
        },
    }


def summarize_year(year,sites):
    by_method=defaultdict(list)
    for record in sites:
        for score in record["scores"]:
            by_method[score["method"]].append(score["scalar_speed_MAE_mps"])
    means={m:statistics.mean(series) for m,series in by_method.items()}
    if len(means)!=len(EVALUATED_METHODS) or any(len(v)!=len(TARGETS) for v in by_method.values()):
        raise ValueError("B_MISSING_SIX_SITE_EVALUATION")
    return {
        "year":year,"n_target_sites":len(sites),
        "equal_site_mean_speed_MAE_mps":means,
        "altitude_minus_distance_MAE_mps":means["altitude_idw4"]-means["distance_idw4"],
        "buffer25_altitude_minus_distance_MAE_mps":means["buffer25_altitude_idw4"]-means["buffer25_distance_idw4"],
        "altitude_better_site_count":sum(
            next(x for x in s["scores"] if x["method"]=="altitude_idw4")["scalar_speed_MAE_mps"]<
            next(x for x in s["scores"] if x["method"]=="distance_idw4")["scalar_speed_MAE_mps"]
            for s in sites),
        "status":"RESEARCH_DIAGNOSTIC_NOT_PRODUCTION",
    }


def run(out):
    folder=Path(out);folder.mkdir(parents=True,exist_ok=True)
    raw,meta_sha=fetch(ROOT+"/ogd-smn_meta_stations.csv",max_bytes=1_500_000)
    metadata,_=parse_meta(raw)
    if not set(TARGETS).issubset(metadata):
        raise ValueError("B_FROZEN_TARGET_IDS_MISSING_METADATA")
    observations,qualified,source,coverage=full_catalog_census(metadata)
    # Physical DEM computed ONCE across full union of year-qualified candidates.
    feature_sites={sid:metadata[sid] for sid in sorted(
        qualified[YEARS[0]]|qualified[YEARS[1]]|set(TARGETS))}
    dem_cache=TileCache(folder/"_private_dem_tiles",zoom=DEM_ZOOM)
    features=metadata_dem_features(feature_sites,dem_cache)
    sites=[]
    for year in YEARS:
        for target in TARGETS:
            results=site_year_results(
                year,target,metadata,features,qualified[year],observations[year])
            sites.append(results)
    annual=[summarize_year(y,[site for site in sites if site["year"]==y]) for y in YEARS]
    result={
        "phase":"P8.4B",
        "status":"ORIGINAL_FULL_CENSUS_RETROSPECTIVE_WIND_RECONSTRUCTION_COMPLETED",
        "source":"MeteoSwiss OGD SwissMetNet hourly original 2020-2029",
        "metadata_sha256":meta_sha,
        "catalog_count":len(metadata),
        "full_catalog_attempt_count":len(source),
        "all_source_catalog_ids_attempted":len(source)==len(metadata),
        "donor_qualification_usable_fraction":MIN_DONOR_YEAR_FRACTION,
        "site_match_min_fraction":MIN_SITE_YEAR_FRACTION,
        "target_station_ids":list(TARGETS),"test_years":list(YEARS),
        "target_excluded_globally":True,
        "region_block_radius_km":BUFFER_KM,
        "model_parameters_preserved_from":"P8.3D exact frozen ranking/P8.3A scalar IDW4 + P8.3B unit direction",
        "n_qualified_donors_by_year":{str(year):len(qualified[year]-set(TARGETS)) for year in YEARS},
        "source_files":source,
        "annual_station_coverage":coverage,
        "dem_original_tile_sha256":dict(dem_cache.sha),
        "dem_station_feature_count":len(features),
        "sites":sites,
        "annual_equal_site_scores":annual,
        "source_per_record_qc_verified":False,
        "source_contemporaneous_donors":True,
        "historical_hindcast_not_future_wind":True,
        "potential_prior_donor_use_of_target_stations":True,
        "raw_station_10min_and_hourly_values_published":False,
        "original_dem_tiles_published":False,
        "future_wind_validated":False,
        "production_epw_ready":False,
    }
    (folder/"p8_4b_full_census_2022_2025_aggregates.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
    print("IGE_P8_4B",json.dumps({
        "status":result["status"],
        "catalog":len(metadata),"attempted":len(source),
        "qualified":result["n_qualified_donors_by_year"],
        "annual_equal_site_scores":annual,
        "scientific_gate":"PENDING_REVIEW",
        "production_epw_ready":False,
    },ensure_ascii=False),flush=True)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    run(args.out)
