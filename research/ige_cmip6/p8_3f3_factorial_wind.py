#!/usr/bin/env python3
"""IGE P8.3F3 preregistered 2^5 ERA5 wind-factor ablation; original-source 2022/2025.

Original hourly SwissMetNet and ERA5 gateway inputs stay private inside CI.
No station-target observations ever enter calibration or predictor construction.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import statistics
from pathlib import Path

import numpy as np

from p8_1e_swiss_external import decode_csv, fetch, haversine, parse_meta
from p8_2e_crossyear import ROOT, annual_hours
from p8_3a_wind_spatial import CALM_MPS, circular_error_deg, interpolate, usable_wind
from p8_3d_wind_terrain_donors import choose_donors
from p8_3e1_f1_wind_qualification import (
    TRAIN_YEAR, CANDIDATE_DONORS, era5_year, monthly_residuals, correct_era5,
)
from p8_3f2_physical_era5 import (
    exposure_category, load_swiss_year, altitude_and_exposure_weights,
    MIN_FRACTION, BOOTSTRAP_DAYS, BOOTSTRAP_REPS, BOOTSTRAP_SEED,
)

TARGETS = ("MOE", "MAS", "NEU", "GUT", "FRU", "BOL")
TEST_YEARS = (2022, 2025)
METHODS = tuple("S%d_W%d_H%d_T%d_E%d" % bits
                for bits in itertools.product((0, 1), repeat=5))
BASELINES = ("era5", "observed_distance_idw4", "observed_altitude_idw4_restricted_pool")
ALL_METHODS = BASELINES + METHODS
F1 = "S0_W0_H0_T0_E0"
F2_ALT = "S1_W1_H1_T1_E0"
F2_EXP = "S1_W1_H1_T1_E1"
PRIMARY = (F1, F2_ALT, F2_EXP)
SEASON_MONTHS = {"DJF":(12,1,2), "MAM":(3,4,5), "JJA":(6,7,8), "SON":(9,10,11)}
FACTOR_NAMES = ("selection", "altitude_weight", "shrink", "taper", "exposure")
MIN_TRAIN_MONTH_HOURS = 400


def factors(name):
    if name not in METHODS:
        raise ValueError("F3_UNKNOWN_FACTOR_VARIANT")
    return tuple(int(part[1:]) for part in name.split("_"))


def source_exposure_map(raw, metadata):
    rows, cols = decode_csv(raw)
    idcol = next((c for c in cols if c.lower() == "station_abbr"), None)
    if idcol is None:
        raise ValueError("F3_STATION_ABBR_MISSING")
    by_site = {}
    for row in rows:
        sid = (row.get(idcol) or "").strip().upper()
        if sid not in metadata:
            continue
        if sid in by_site:
            raise ValueError("F3_DUPLICATE_STATION_EXPOSURE_" + sid)
        desc = ""
        for name in ("station_exposition_en", "station_exposition_de",
                     "station_exposition_fr", "station_exposition_it"):
            col = next((c for c in cols if c.lower() == name), None)
            if col and (row.get(col) or "").strip():
                desc = row[col].strip()
                break
        by_site[sid] = {"description":desc, "category":exposure_category(desc)}
    if not set(TARGETS).issubset(by_site):
        raise ValueError("F3_TARGET_EXPOSURE_UNAVAILABLE")
    return by_site


def select_four(target, metadata, calibrated, mode):
    if target["station_id"] in calibrated:
        raise AssertionError("F3_TARGET_STATION_IN_CALIBRATION")
    if mode == 0:
        distances = sorted(
            (float(haversine(target["lat"], target["lon"],
                             metadata[sid]["lat"], metadata[sid]["lon"])), sid)
            for sid in calibrated
        )
        if len(distances) < 4:
            raise ValueError("F3_TOO_FEW_QUALIFIED_DONORS")
        return [(dist, metadata[sid]) for dist, sid in distances[:4]]
    if mode == 1:
        return choose_donors(target, metadata, set(calibrated), {}, "altitude_idw4")
    raise ValueError("F3_UNKNOWN_SELECTOR")


def variant_weights(target, selected, exposures, name):
    _, altitude, _, _, exposure = factors(name)
    if altitude:
        return altitude_and_exposure_weights(target, selected, exposures, bool(exposure))
    # Exposure is an independent factor also when altitude-weighting is OFF.
    target_category = exposures.get(target["station_id"], {}).get("category", "unclassified")
    raw = []
    for distance, donor in selected:
        sid = donor["station_id"]
        if sid == target["station_id"]:
            raise AssertionError("F3_TARGET_STATION_AS_DONOR")
        weight = 1/max(distance, .25)**2
        category = exposures.get(sid, {}).get("category", "unclassified")
        if (exposure and target_category != "unclassified"
                and category != "unclassified" and category != target_category):
            weight *= .5
        raw.append((sid, float(distance), weight))
    total = sum(weight for _, _, weight in raw)
    if total <= 0 or not math.isfinite(total):
        raise ValueError("F3_INVALID_WEIGHTS")
    return [(sid, distance, weight/total) for sid, distance, weight in raw]


def residual_plan(target, metadata, calibrated, exposures):
    """Build every factor variant using metadata and training residuals only."""
    if target["station_id"] in calibrated:
        raise AssertionError("F3_TARGET_LEAKED_IN_TRAINING")
    selectors = {mode:select_four(target, metadata, calibrated, mode) for mode in (0,1)}
    plan = {}
    from p8_3e1_f1_wind_qualification import blended_residual
    for name in METHODS:
        selection, altitude, shrink, taper, exposure = factors(name)
        weights = variant_weights(target, selectors[selection], exposures, name)
        correction = {month:blended_residual(month, weights, calibrated)
                      for month in range(1,13)}
        plan[name] = {"weights":weights, "monthly":correction,
                      "amplitude":.5 if shrink else 1.,
                      "taper":bool(taper)}
    return plan, selectors


def corrected_prediction(hour, correction, plan):
    if not usable_wind(hour):
        return None
    factor = plan["amplitude"] * (
        min(1.,hour["speed"]/2.) if plan["taper"] else 1.)
    return correct_era5(
        hour, {key:value*factor for key,value in correction.items()})


def donor_interpolation(selected, measured, time):
    series = {s["station_id"]: measured[s["station_id"]] for _,s in selected}
    p = interpolate(selected, series, time)
    if p is None:
        return None
    return {"speed":float(p["scalar_speed"]), "direction":p["vector_direction"]}


def predictions_for_year(target, meta, qualified, exposure, measured, background, year):
    plan, selectors = residual_plan(target, meta, qualified, exposure)
    prediction = {}
    for stamp in annual_hours(year):
        base = background.get(stamp)
        if not usable_wind(base):
            continue
        a = donor_interpolation(selectors[0], measured, stamp)
        b = donor_interpolation(selectors[1], measured, stamp)
        if a is None or b is None:
            continue
        p = {"era5":base, "observed_distance_idw4":a,
             "observed_altitude_idw4_restricted_pool":b}
        for name in METHODS:
            p[name] = corrected_prediction(
                base, plan[name]["monthly"][stamp.month], plan[name])
        prediction[stamp] = p
    selections = {
        str(mode):[s["station_id"] for _,s in selectors[mode]] for mode in (0,1)
    }
    # Only small metadata-derived coefficients, never per-hour source data.
    return prediction, selections


def paired_rows(predicted, original_target, year, target):
    rows = []
    for stamp,p in sorted(predicted.items()):
        observed = original_target.get(stamp)
        if not usable_wind(observed):
            continue
        if any(p.get(name) is None for name in ALL_METHODS):
            continue
        rows.append((stamp, observed, p))
    total = len(annual_hours(year))
    if len(rows) < math.ceil(MIN_FRACTION*total):
        raise ValueError("F3_INSUFFICIENT_COMMON_HOURS_%s_%s_%s" % (target, year, len(rows)))
    return rows


def score(rows):
    if not rows:
        raise ValueError("F3_NO_SCORE_HOURS")
    noncalm = [(ref,p) for _,ref,p in rows if ref["speed"] >= CALM_MPS]
    result = {"n_hours":len(rows), "n_reference_noncalm":len(noncalm)}
    for name in ALL_METHODS:
        diffs = [pred[name]["speed"]-ref["speed"] for _,ref,pred in rows]
        direction = [
            circular_error_deg(p[name].get("direction"),ref["direction"])
            if p[name].get("direction") is not None else None
            for ref,p in noncalm
        ]
        emitted = [x for x in direction if x is not None]
        result[name] = {
            "speed_mae_mps":statistics.mean(abs(x) for x in diffs),
            "speed_rmse_mps":math.sqrt(statistics.mean(x*x for x in diffs)),
            "speed_bias_mps":statistics.mean(diffs),
            "direction_resolved_n":len(emitted),
            "direction_conditional_mae_deg":statistics.mean(emitted) if emitted else None,
            "direction_fixed90_deg":statistics.mean(x if x is not None else 90.
                                                      for x in direction) if direction else None,
        }
    return result


def factor_contrasts(scores):
    """Balanced 2^5 marginal MAE effects and two prespecified interactions."""
    y = {name:scores[name]["speed_mae_mps"] for name in METHODS}
    result = {}
    for i, label in enumerate(FACTOR_NAMES):
        plus = [y[n] for n in METHODS if factors(n)[i] == 1]
        minus = [y[n] for n in METHODS if factors(n)[i] == 0]
        result[label] = statistics.mean(plus)-statistics.mean(minus)
    interaction = {}
    for a,b in ((2,3),(1,4)):
        means = {}
        for i in (0,1):
            for j in (0,1):
                means[(i,j)] = statistics.mean(
                    y[n] for n in METHODS if factors(n)[a]==i and factors(n)[b]==j)
        interaction[FACTOR_NAMES[a]+"_x_"+FACTOR_NAMES[b]] = (
            means[(1,1)]-means[(1,0)]-means[(0,1)]+means[(0,0)])
    return {"factor_main_effect_on_speed_mae_mps":result,
            "factor_interaction_on_speed_mae_mps":interaction}


def bootstrap(rows, year, site, reps=BOOTSTRAP_REPS):
    """Sample only actual contiguous 7-day blocks from timestamp-aligned errors."""
    block = BOOTSTRAP_DAYS*24
    n = len(rows)
    if n < block:
        raise ValueError("F3_BOOTSTRAP_TOO_FEW_HOURS")
    starts = [i for i in range(n-block+1)
              if (rows[i+block-1][0]-rows[i][0]).total_seconds() == (block-1)*3600]
    if not starts:
        raise ValueError("F3_NO_CONTIGUOUS_SEVEN_DAY_SOURCE_BLOCK")
    names = PRIMARY
    diffs = np.array([[abs(p[name]["speed"]-obs["speed"])-abs(p["era5"]["speed"]-obs["speed"])
                       for name in names] for _,obs,p in rows],dtype=float)
    selected = np.random.default_rng(BOOTSTRAP_SEED+year+TARGETS.index(site))
    nblocks = math.ceil(n/block)
    sampled = np.empty((reps,len(names)),dtype=float)
    starts = np.array(starts)
    for k in range(reps):
        indices = np.concatenate(
            [np.arange(start,start+block) for start in selected.choice(
                starts,size=nblocks,replace=True)])[:n]
        sampled[k] = diffs[indices].mean(axis=0)
    return {name:{
        "delta_mae_vs_era5_mps":float(diffs[:,i].mean()),
        "interval_95pct_mps":[float(v) for v in np.quantile(sampled[:,i],[.025,.975])],
        "replicates":reps,
        "contiguous_window_count":len(starts),
    } for i,name in enumerate(names)}


def run(year,out):
    if year not in TEST_YEARS:
        raise ValueError("F3_TEST_YEAR_NOT_PREREGISTERED")
    raw_meta, sha_meta = fetch(ROOT+"/ogd-smn_meta_stations.csv",max_bytes=1500000)
    meta, _ = parse_meta(raw_meta)
    exposure = source_exposure_map(raw_meta,meta)
    required = set(TARGETS)|set(CANDIDATE_DONORS)
    if not required.issubset(meta):
        raise ValueError("F3_REQUIRED_STATIONS_MISSING")
    source_cache, qualified, qualification_errors = {},{},{}
    digests = {}
    for sid in CANDIDATE_DONORS:
        try:
            original, sha = load_swiss_year(sid, TRAIN_YEAR, source_cache)
            era5, sha_era5 = era5_year(meta[sid],TRAIN_YEAR)
            qualified[sid] = monthly_residuals(
                original,era5,min_count=MIN_TRAIN_MONTH_HOURS)
            digests[sid] = {"swiss_2023_sha256":sha,"era5_2023_sha256":sha_era5}
        except Exception as exc:
            qualification_errors[sid] = type(exc).__name__+": "+str(exc)[:160]
    if len(qualified)<4:
        raise ValueError("F3_TOO_FEW_TRAIN_DONORS "+str(qualification_errors))
    observed,obs_hash={},{}
    for sid in sorted(set(qualified)|set(TARGETS)):
        series,sha=load_swiss_year(sid,year,source_cache)
        observed[sid]=series
        obs_hash[sid]=sha
    result_sites=[]
    for target_id in TARGETS:
        original_era,era_hash=era5_year(meta[target_id],year)
        predictions,selections=predictions_for_year(
            meta[target_id],meta,qualified,exposure,observed,original_era,year)
        paired=paired_rows(predictions,observed[target_id],year,target_id)
        full=score(paired)
        record={
            "id":target_id,"year":year,"n_expected_hours":len(annual_hours(year)),
            "matched_fraction":len(paired)/len(annual_hours(year)),
            "era5_sha256":era_hash,
            "source_observation_sha256":obs_hash[target_id],
            "exposure_category":exposure[target_id]["category"],
            "selectors":selections,"all_year":full,
            "seasons":{season:score([row for row in paired if row[0].month in months])
                       for season,months in SEASON_MONTHS.items()},
            "ablation":factor_contrasts(full),
            "paired_bootstrap":bootstrap(paired,year,target_id),
        }
        result_sites.append(record)
    pooled={
        method:{
            "macro_equal_site_mae_mps":statistics.mean(
                record["all_year"][method]["speed_mae_mps"] for record in result_sites),
            "micro_matched_hour_mae_mps":sum(
                record["all_year"][method]["speed_mae_mps"]*record["all_year"]["n_hours"]
                for record in result_sites)/sum(record["all_year"]["n_hours"]
                                                for record in result_sites),
            "n_sites_better_than_era5":sum(
                record["all_year"][method]["speed_mae_mps"] <
                record["all_year"]["era5"]["speed_mae_mps"]
                for record in result_sites)
        } for method in ALL_METHODS
    }
    return {
        "phase":"IGE_P8_3F3",
        "status":"FULL_YEAR_SOURCE_BACKED_FACTORIAL_2022_OR_2025_RESEARCH",
        "test_year":year,"calibration_year":TRAIN_YEAR,
        "sites":result_sites,"site_count":len(result_sites),
        "factors":list(FACTOR_NAMES),"variant_count":len(METHODS),
        "f1_variant":F1,"f2_altitude_variant":F2_ALT,"f2_exposure_variant":F2_EXP,
        "source_meta_sha256":sha_meta,
        "donor_calibration_sha256":digests,
        "test_year_original_observation_sha256":obs_hash,
        "rejected_training_donors":qualification_errors,
        "qualified_2023_donors":sorted(qualified),
        "metrics_pooled":pooled,
        "methodology_limitations":[
            "2022 test precedes 2023 fit, but uses no 2022 target to train or tune.",
            "2025 has previously been studied, though these six target identities were not F2 targets.",
            "All altitude penalties, residual amplitude and exposure classes are fixed heuristics, not fluid physics.",
            "No measured anemometer height or upstream z0; no vertical profile correction.",
            "Station IDW controls use contemporaneous donor measurements, unlike ERA5-only variants.",
            "Altitude baseline uses restricted qualified donor pool, NOT original full 2024 P8.3D census.",
            "Fixed same-nominal-hour sample; ERA5 vs station temporal integration remains unresolved.",
            "Per-site bootstrap does not establish interregional model superiority.",
        ],
        "original_hourly_data_exported":False,
        "production_epw_ready":False,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--year",type=int,required=True)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    result=run(args.year,args.out)
    p=Path(args.out);p.mkdir(parents=True,exist_ok=True)
    (p/("p8_3f3_factorial_"+str(args.year)+"_aggregate.json")).write_text(
        json.dumps(result,indent=2,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
    print("IGE_P8_3F3_SCIENCE",json.dumps({
        "year":args.year,"sites":len(result["sites"]),
        "variants":result["variant_count"],
        "raw_era5_macro":result["metrics_pooled"]["era5"]["macro_equal_site_mae_mps"],
        "f1_macro":result["metrics_pooled"][F1]["macro_equal_site_mae_mps"],
        "f2_alt_macro":result["metrics_pooled"][F2_ALT]["macro_equal_site_mae_mps"],
    },sort_keys=True),flush=True)


if __name__=="__main__":
    main()
