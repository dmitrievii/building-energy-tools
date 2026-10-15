#!/usr/bin/env python3
"""IGE P8.3F2: preregistered conservative ERA5 wind corrections, 2025 source test.

Research only: no original station observations or hourly predictions published.
F2 hypotheses are heuristic physical conditioning, not validated orographic flow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

import numpy as np

from p8_1e_swiss_external import decode_csv, fetch, haversine, parse_meta
from p8_2e_crossyear import ROOT, annual_hours
from p8_3a_wind_spatial import (
    CALM_MPS, circular_error_deg, interpolate, parse_wind_year, usable_wind,
)
from p8_3d_wind_terrain_donors import choose_donors
from p8_3e1_f1_wind_qualification import (
    CANDIDATE_DONORS, TRAIN_YEAR, era5_year, monthly_residuals, donor_weights,
    blended_residual, correct_era5,
)

YEAR = 2025
TARGETS = ("BAS", "CHD", "GRA", "MUB", "STG", "VIS")
FROZEN_2024_P8D_ALTITUDE = {
    "BAS": ("MOE", "RUE", "DEM", "GOE"),
    "CHD": ("CDM", "MAS", "ORO", "BOL"),
    "GRA": ("MAS", "PAY", "PLF", "MUB"),
    "MUB": ("BER", "CRM", "NEU", "GRE"),
    "STG": ("BIZ", "ARH", "OBR", "GUT"),
    "VIS": ("FRU", "BLA", "SIM", "ABO"),
}
METHODS = (
    "era5", "f1_residual", "f2_altitude_shrunk", "f2_exposure_shrunk",
    "f1_distance_idw4", "p8d_frozen_altitude_idw4",
)
CORRECTED = ("f1_residual", "f2_altitude_shrunk", "f2_exposure_shrunk")
SHRINK = 0.5
CALM_TAPER_MPS = 2.0
ALT_PENALTY_SCALE_M = 500.0
EXPOSURE_MISMATCH_MULTIPLIER = 0.5
MIN_FRACTION = 0.8
BOOTSTRAP_DAYS = 7
BOOTSTRAP_REPS = 300
BOOTSTRAP_SEED = 20261015


def exposure_category(description):
    """Textual topographic hints, never a WMO exposure class or roughness value."""
    d = " ".join((description or "").lower().split())
    if d in ("plain", "plains"):
        return "plain"
    if d.startswith("height (") and "above valley" in d:
        return "elevated_above_valley"
    if "oriented slope" in d or d.endswith(" slope"):
        return "slope"
    return "unclassified"


def station_exposures(raw, metadata):
    rows, cols = decode_csv(raw)
    names = ("station_exposition_en", "station_exposition_de",
             "station_exposition_fr", "station_exposition_it")
    col_id = next((c for c in cols if c.casefold() == "station_abbr"), None)
    if col_id is None:
        raise ValueError("F2_NO_STATION_ABBREVIATION_COLUMN")
    result = {}
    for row in rows:
        sid = (row.get(col_id) or "").strip().upper()
        if sid not in metadata:
            continue
        if sid in result:
            raise ValueError("F2_DUPLICATE_EXPOSURE_" + sid)
        description = ""
        for name in names:
            col = next((c for c in cols if c.casefold() == name), None)
            if col and (row.get(col) or "").strip():
                description = row[col].strip()
                break
        result[sid] = {"category": exposure_category(description),
                       "description": description}
    if not set(TARGETS).issubset(result):
        raise ValueError("F2_MISSING_EXPOSURE_TARGET")
    return result


def altitude_and_exposure_weights(target, donors, exposures, conditioned):
    """P8.3D altitude selector, then physically plausible mismatch attenuation.

    Altitude and exposure are proxies only. All returned weights are nonnegative;
    weights do NOT represent measured aerodynamic transfer functions.
    """
    target_id = target["station_id"]
    if any(s["station_id"] == target_id for _, s in donors):
        raise AssertionError("F2_TARGET_LEAK_IN_RESIDUAL_DONORS")
    target_class = exposures.get(target_id, {}).get("category", "unclassified")
    weighted = []
    for distance, donor in donors:
        sid = donor["station_id"]
        dz = abs(float(target["hoehe_m"]) - float(donor["hoehe_m"]))
        value = math.exp(-dz / ALT_PENALTY_SCALE_M) / max(float(distance), .25)**2
        donor_class = exposures.get(sid, {}).get("category", "unclassified")
        if (conditioned and target_class != "unclassified"
                and donor_class != "unclassified" and donor_class != target_class):
            value *= EXPOSURE_MISMATCH_MULTIPLIER
        weighted.append((sid, float(distance), value))
    total = sum(w for _, _, w in weighted)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("F2_INVALID_DONOR_WEIGHTS")
    return [(sid, dist, w/total) for sid, dist, w in weighted]


def physical_correction(hour, month, donor_weights_with_names, climatologies):
    """Conservative representativeness factor; speed-dependent at calm conditions."""
    if not usable_wind(hour):
        return None
    corrections = blended_residual(month, donor_weights_with_names, climatologies)
    factor = SHRINK * min(1., hour["speed"] / CALM_TAPER_MPS)
    return correct_era5(hour, {key: value * factor for key, value in corrections.items()})


def frozen_selection(target, metadata):
    ids = FROZEN_2024_P8D_ALTITUDE[target["station_id"]]
    if len(set(ids)) != 4 or target["station_id"] in ids:
        raise ValueError("F2_FROZEN_DONOR_LIST_INVALID")
    if any(sid not in metadata for sid in ids):
        raise ValueError("F2_FROZEN_DONOR_METADATA_MISSING")
    return [(float(haversine(target["lat"], target["lon"],
                            metadata[sid]["lat"], metadata[sid]["lon"])), metadata[sid])
            for sid in ids]


def load_swiss_year(site, year, cache):
    """Fetch one station file once; keep its original bytes ephemeral in CI."""
    if site not in cache:
        raw, sha = fetch(
            f"{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_h_historical_2020-2029.csv",
            max_bytes=37000000)
        cache[site] = (raw, sha)
    raw, sha = cache[site]
    return parse_wind_year(raw, site, year), sha


def external_donor_predictions(donors, original_2025, timestamp):
    obs = {s["station_id"]: original_2025[s["station_id"]] for _, s in donors}
    p = interpolate(donors, obs, timestamp)
    if p is None:
        return None
    return {"speed": float(p["scalar_speed"]), "direction": p["vector_direction"]}


def build_predictions(target, metadata, exposures, calibrations, original_2025, background_2025):
    """No target observed data enter predictions; same-year DONOR wind only for baselines."""
    sid = target["station_id"]
    if sid in calibrations:
        raise AssertionError("F2_TARGET_LEAK_IN_TRAINING")
    qualified = {key for key in calibrations}
    f1 = donor_weights(target, {d: metadata[d] for d in qualified})
    alt = choose_donors(target, metadata, qualified, {}, "altitude_idw4")
    alt_weights = altitude_and_exposure_weights(target, alt, exposures, conditioned=False)
    exp_weights = altitude_and_exposure_weights(target, alt, exposures, conditioned=True)
    distance_donors = [(distance, metadata[donor]) for donor, distance, _ in f1]
    frozen = frozen_selection(target, metadata)
    corrections_f1 = {m: blended_residual(m, f1, calibrations) for m in range(1, 13)}
    hours = annual_hours(YEAR)
    predicted = {}
    for timestamp in hours:
        era = background_2025.get(timestamp)
        if not usable_wind(era):
            continue
        a = external_donor_predictions(distance_donors, original_2025, timestamp)
        b = external_donor_predictions(frozen, original_2025, timestamp)
        # Strict common denominator; missing donor-only prediction not filled.
        if a is None or b is None:
            continue
        predicted[timestamp] = {
            "era5": era,
            "f1_residual": correct_era5(era, corrections_f1[timestamp.month]),
            "f2_altitude_shrunk": physical_correction(
                era, timestamp.month, alt_weights, calibrations),
            "f2_exposure_shrunk": physical_correction(
                era, timestamp.month, exp_weights, calibrations),
            "f1_distance_idw4": a,
            "p8d_frozen_altitude_idw4": b,
        }
    selection = {
        "f1_distance_calibration_donors": [sid for sid, _, _ in f1],
        "f2_altitude_calibration_donors": [s["station_id"] for _, s in alt],
        "f2_altitude_weights": alt_weights,
        "f2_exposure_weights": exp_weights,
        "p8d_frozen_2024_altitude_donors": list(FROZEN_2024_P8D_ALTITUDE[sid]),
        "target_exposure_category": exposures[sid]["category"],
        "target_exposure_description": exposures[sid]["description"],
    }
    return predicted, selection


def paired_site_rows(predicted, observed, site):
    scored = []
    for stamp, p in sorted(predicted.items()):
        reference = observed.get(stamp)
        if not usable_wind(reference):
            continue
        if any(v is None for v in p.values()):
            continue
        scored.append((stamp, reference, p))
    if len(scored) < math.ceil(MIN_FRACTION * len(annual_hours(YEAR))):
        raise ValueError(f"F2_INSUFFICIENT_COMMON_SITE_HOURS_{site}_{len(scored)}")
    return scored


def summarize(rows):
    if not rows:
        raise ValueError("F2_EMPTY_SCORE_SET")
    result = {"n_hours": len(rows)}
    nc = [(ref, pred) for _, ref, pred in rows if ref["speed"] >= CALM_MPS]
    result["n_reference_noncalm"] = len(nc)
    for method in METHODS:
        diffs = [p[method]["speed"] - ref["speed"] for _, ref, p in rows]
        resolved = [
            circular_error_deg(pred[method].get("direction"), ref["direction"])
            if pred[method].get("direction") is not None else None
            for ref, pred in nc
        ]
        eligible = [v for v in resolved if v is not None]
        result[method] = {
            "speed_mae_mps": statistics.mean(map(abs, diffs)),
            "speed_rmse_mps": math.sqrt(statistics.mean(v*v for v in diffs)),
            "speed_bias_mps": statistics.mean(diffs),
            "direction_n_resolved": len(eligible),
            "direction_mae_resolved_deg": statistics.mean(eligible) if eligible else None,
            "direction_fixed90_deg": (
                statistics.mean(v if v is not None else 90. for v in resolved)
                if resolved else None),
        }
    for name in METHODS[1:]:
        result[name]["delta_mae_vs_era5_mps"] = (
            result[name]["speed_mae_mps"]-result["era5"]["speed_mae_mps"])
        result[name]["delta_mae_vs_f1_residual_mps"] = (
            result[name]["speed_mae_mps"]-result["f1_residual"]["speed_mae_mps"])
    return result


def moving_block_delta_ci(rows, reps=BOOTSTRAP_REPS, seed=BOOTSTRAP_SEED, days=BOOTSTRAP_DAYS):
    """Deterministic paired error differences, preserving local 7-day serial blocks."""
    if len(rows) < 7*24:
        raise ValueError("F2_SHORT_BOOTSTRAP_SERIES")
    n = len(rows)
    loss = np.array([[abs(p[k]["speed"] - ref["speed"]) for k in METHODS]
                    for _, ref, p in rows], dtype=float)
    diff = loss[:, 1:] - loss[:, :1]
    rng = np.random.default_rng(seed)
    block = days*24
    starts = np.arange(n-block+1)
    repeat = math.ceil(n/block)
    sampled = np.empty((reps, len(METHODS)-1), dtype=float)
    for b in range(reps):
        chosen = rng.choice(starts, size=repeat, replace=True)
        indices = np.concatenate([np.arange(t, t+block) for t in chosen])[:n]
        sampled[b, :] = np.mean(diff[indices], axis=0)
    return {method: {
        "delta_mae_vs_era5_observed_mps": float(np.mean(diff[:, i])),
        "block_bootstrap_95pct_interval_mps": [float(v) for v in np.quantile(sampled[:, i], [.025,.975])],
        "favors_variant_if_both_bounds_negative": bool(np.quantile(sampled[:, i], .975) < 0),
    } for i, method in enumerate(METHODS[1:])}


def phase_f2():
    raw_meta, sha_meta = fetch(ROOT + "/ogd-smn_meta_stations.csv", max_bytes=1500000)
    metadata, _ = parse_meta(raw_meta)
    exposure = station_exposures(raw_meta, metadata)
    missing = set(TARGETS) | set(CANDIDATE_DONORS)
    missing -= metadata.keys()
    if missing:
        raise ValueError("F2_METADATA_STATIONS_MISSING_" + ",".join(sorted(missing)))
    source_cache = {}
    qualified, training_sha, training_reject = {}, {}, {}
    for sid in CANDIDATE_DONORS:
        try:
            station_obs, swiss_sha = load_swiss_year(sid, TRAIN_YEAR, source_cache)
            grid, grid_sha = era5_year(metadata[sid], TRAIN_YEAR)
            qualified[sid] = monthly_residuals(station_obs, grid)
            training_sha[sid] = {"station_sha256": swiss_sha,
                                 "era5_sha256": grid_sha}
        except Exception as exc:
            training_reject[sid] = type(exc).__name__ + ": " + str(exc)[:160]
    if len(qualified) < 4:
        raise ValueError("F2_FEWER_THAN_FOUR_TRAINING_DONORS_" + str(training_reject))
    # Exact frozen P8.3D selected sets: no post-2025 selection based on target observations.
    required_2025 = set(qualified) | set(TARGETS)
    for sites in FROZEN_2024_P8D_ALTITUDE.values():
        required_2025.update(sites)
    observed_2025, swiss_sha_2025 = {}, {}
    for sid in sorted(required_2025):
        obs, sha = load_swiss_year(sid, YEAR, source_cache)
        observed_2025[sid] = obs
        swiss_sha_2025[sid] = sha
    result_sites = []
    for tid in TARGETS:
        grid, grid_sha = era5_year(metadata[tid], YEAR)
        predictions, selection = build_predictions(
            metadata[tid], metadata, exposure, qualified, observed_2025, grid)
        paired = paired_site_rows(predictions, observed_2025[tid], tid)
        seasons = {"DJF": (12,1,2), "MAM": (3,4,5),
                   "JJA": (6,7,8), "SON": (9,10,11)}
        record = {
            "site": tid, "n_calendar_hours": len(annual_hours(YEAR)),
            "full_year": summarize(paired),
            "seasons": {label: summarize([v for v in paired if v[0].month in months])
                        for label, months in seasons.items()},
            "bootstrap": moving_block_delta_ci(paired, seed=BOOTSTRAP_SEED + TARGETS.index(tid)),
            "selection": selection,
            "era5_2025_sha256": grid_sha,
            "matched_fraction": len(paired) / len(annual_hours(YEAR)),
        }
        result_sites.append(record)
    macro = {method: statistics.mean(s["full_year"][method]["speed_mae_mps"] for s in result_sites)
             for method in METHODS}
    micro = {
        method: sum(s["full_year"][method]["speed_mae_mps"]*s["full_year"]["n_hours"]
                    for s in result_sites) / sum(s["full_year"]["n_hours"] for s in result_sites)
        for method in METHODS
    }
    improvements = {
        method: {"n_sites_beating_era5": sum(
            s["full_year"][method]["speed_mae_mps"] < s["full_year"]["era5"]["speed_mae_mps"]
            for s in result_sites),
            "macro_mae_delta_vs_era5_mps": macro[method]-macro["era5"]}
        for method in METHODS[1:]
    }
    return {
        "phase": "P8.3F2",
        "status": "ORIGINAL_2025_INDEPENDENT_TARGET_BENCHMARK_COMPLETE_RESEARCH_ONLY",
        "train_year": TRAIN_YEAR, "test_year": YEAR,
        "targets": list(TARGETS),
        "months_source_rule": "2023 month-conditioned 2023 station minus ERA5 wind scalar+TO-vector residual",
        "era5_source": "Open-Meteo archive explicitly models=era5; hourly GMT; 10m",
        "source_meta_sha256": sha_meta,
        "source_training_sha256": training_sha,
        "source_2025_station_sha256": swiss_sha_2025,
        "rejected_training_donors": training_reject,
        "training_donors": sorted(qualified),
        "frozen_p8d_selection_artifact": {
            "workflow_run": 38639636205,
            "artifact_id": 11930026508,
            "selection_file": "p8_3d_wind_selected_donors.csv",
            "frozen_selection_year": 2024,
        },
        "scientific_limitations": [
            "Anemometer height and z0 not verified; no log-profile correction.",
            "Exposure categories are descriptive text proxies, not WMO class.",
            "Station IDW baselines use observed contemporaneous 2025 donors, not ERA5-only information.",
            "P8.3D donors are frozen from 2024 prior-year selection, not re-screened 2025.",
            "Limited Swiss six-target research, same sites have been studied in earlier phases.",
            "ERA5 10m nominal hourly sample may differ in averaging interval from measured station hourly wind.",
            "Seven-day bootstrap is descriptive conditional on site/year, not cross-climate generalization."
        ],
        "macro_equal_site_speed_mae_mps": macro,
        "micro_hour_weighted_speed_mae_mps": micro,
        "improvement_counts": improvements,
        "site_results": result_sites,
        "production_epw_ready": False,
        "raw_hourly_data_published": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = phase_f2()
    p = Path(args.out)
    p.mkdir(parents=True, exist_ok=True)
    (p / "p8_3f2_source_science_aggregates.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print("IGE_P8_3F2_RESEARCH", json.dumps({
        "status": result["status"], "sites": len(result["site_results"]),
        "macro_speed_mae": result["macro_equal_site_speed_mae_mps"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
