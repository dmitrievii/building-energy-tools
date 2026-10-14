#!/usr/bin/env python3
"""IGE P8.3E1/F1: source-qualified Swiss exposure and independent ERA5 wind residual trial.

Research only. No source hourly observations, derived hourly weather or DEM raster
are published. Frozen 2023 donor calibration; independent 2024 target holdout.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import datetime as dt
import hashlib
import json
import math
import statistics
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from p8_1e_swiss_external import decode_csv, fetch, haversine, parse_meta
from p8_2e_crossyear import ROOT, annual_hours
from p8_3a_wind_spatial import (
    CALM_MPS, circular_error_deg, interpolate, parse_wind_year, usable_wind,
    uv_to_wind_from, wind_from_to_uv,
)

TARGETS = ("BAS", "GRA", "MUB")
CANDIDATE_DONORS = ("ABO", "BER", "PAY", "DAV", "LUG", "GVE", "SIO", "SMA", "WYN", "ZER")
EXPOSURE_STATIONS = ("BAS", "CHD", "GRA", "MUB", "STG", "VIS", "PAY", "SIO")
TRAIN_YEAR = 2023
HOLDOUT_YEAR = 2024
N_DONORS = 4
MIN_MONTH_TRAIN = 400
MIN_HOLDOUT_FRACTION = .80
EXPOSURE_TERMS = {
    "valley_indication": ("valley", "vallée", "tal", "valle"),
    "ridge_or_summit_indication": ("ridge", "summit", "crest", "peak", "grate", "gipfel", "berg"),
    "urban_indication": ("urban", "city", "town", "built-up", "stadt", "städt"),
    "airport_indication": ("airport", "airfield", "aerodrome", "flugplatz", "flughafen"),
    "open_field_indication": ("open field", "open area", "grassland", "free field", "offenes feld"),
}
E1_SOURCES = [
    "https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations",
    "https://www.meteoswiss.admin.ch/weather/measurement-systems/land-based-stations/automatic-measurement-network/certification-of-monitoring-stations.html",
    "https://www.meteoswiss.admin.ch/dam/jcr%3A81a4d809-4f15-4532-9065-e46eb7fe5127/NationalClimateObservingSystem_GCOSSwitzerland-Small.pdf",
]
F1_SOURCES = ["https://open-meteo.com/en/docs/historical-weather-api"]


def exposure_clues(description):
    """Transparent text search, NOT a validated WMO siting/exposure class."""
    if not description or not description.strip():
        return ["missing_or_undocumented"]
    source = description.casefold()
    found = [key for key, words in EXPOSURE_TERMS.items() if any(w in source for w in words)]
    return found or ["description_present_no_recognized_clue"]


def classify_station_evidence(record, cols):
    def field(*names):
        for key in names:
            name = next((c for c in cols if c.casefold() == key.casefold()), None)
            if name and (record.get(name) or "").strip():
                return (record.get(name) or "").strip()
        return ""
    sid = field("station_abbr", "station", "abbreviation", "station_id")
    description = field("station_exposition_en", "station_exposition_de", "station_exposition_fr", "station_exposition_it")
    instrument = field("anemometer_height_m_agl", "wind_sensor_height_m_agl")
    roughness = field("roughness_length_z0_m")
    # Physically normalize ONLY from independently certified height AND roughness.
    # Numeric-looking values in arbitrary unverified source columns remain blocked.
    return {
        "site": sid,
        "station_exposition_description": description,
        "description_language_priority": "en > de > fr > it",
        "exposure_textual_clues": exposure_clues(description),
        "instrument_height_m_agl": None,
        "z0_m": None,
        "instrument_height_column_present": bool(instrument),
        "roughness_column_present": bool(roughness),
        "official_site_specific_height_documented": False,
        "official_site_specific_roughness_documented": False,
        "height_normalization_authorized": False,
        "exposure_wmo_class_verified": False,
    }


def e1_station_records(raw, station_ids=EXPOSURE_STATIONS):
    rows, cols = decode_csv(raw)
    by_station = {}
    for row in rows:
        classification = classify_station_evidence(row, cols)
        sid = classification["site"].upper()
        if sid in station_ids:
            if sid in by_station:
                raise ValueError("E1_DUPLICATE_STATION_" + sid)
            by_station[sid] = classification
    if set(station_ids) - by_station.keys():
        raise ValueError("E1_STATIONS_MISSING_" + ",".join(sorted(set(station_ids)-by_station.keys())))
    return [by_station[sid] for sid in station_ids], cols


def stage_e1():
    raw, sha = fetch(ROOT + "/ogd-smn_meta_stations.csv", max_bytes=1500000)
    stations, cols = e1_station_records(raw)
    metadata, _ = parse_meta(raw)
    for row in stations:
        row["station_elevation_masl"] = metadata[row["site"]]["hoehe_m"]
    return {
        "phase": "P8.3E1",
        "status": "TEXT_EXPOSURE_AUDITED__PHYSICAL_HEIGHT_CORRECTION_BLOCKED",
        "station_source_sha256": sha,
        "station_metadata_columns": list(cols),
        "source_documents": E1_SOURCES,
        "network_level_note": "MeteoSwiss documents standard 10 m surface wind measurement; this does NOT certify any sampled station's particular sensor mounting height.",
        "sites": stations,
        "height_normalization_authorized_for_sites": 0,
        "scientific_decision": "Keep all measured scalar wind unnormalized until station-specific height, z0, and validity of a neutral log law are evidenced.",
        "production_wind_authorized": False,
    }


def decode_era5_year(payload, year):
    """Explicit reanalysis, 10 m, GMT; reject non-annual axes and unit mismatches."""
    hourly = payload.get("hourly") or {}
    units = payload.get("hourly_units") or {}
    expected = annual_hours(year)
    if units.get("wind_speed_10m") != "m/s" or units.get("wind_direction_10m") not in ("°", "degrees", "degree"):
        raise ValueError("F1_ERA5_UNITS")
    times = hourly.get("time")
    speeds = hourly.get("wind_speed_10m")
    directions = hourly.get("wind_direction_10m")
    if not all(isinstance(v, list) for v in (times, speeds, directions)):
        raise ValueError("F1_ERA5_SCHEMA")
    if any(len(v) != len(expected) for v in (times, speeds, directions)):
        raise ValueError("F1_ERA5_ANNUAL_LENGTH")
    result = {}
    for pos, (stamp, speed, direction) in enumerate(zip(times, speeds, directions)):
        try:
            t = dt.datetime.fromisoformat(stamp)
        except (TypeError, ValueError) as exc:
            raise ValueError("F1_ERA5_TIMESTAMP") from exc
        if t != expected[pos]:
            raise ValueError("F1_ERA5_CLOCK_AXIS")
        if speed is None or direction is None:
            continue
        if not isinstance(speed, (int, float)) or not isinstance(direction, (int, float)):
            continue
        if not (math.isfinite(speed) and math.isfinite(direction) and speed >= 0 and 0 <= direction <= 360):
            continue
        result[t] = {"speed": float(speed), "direction": float(direction) % 360}
    if len(result) < math.ceil(.95 * len(expected)):
        raise ValueError("F1_ERA5_INCOMPLETE")
    return result


def era5_year(station, year):
    params = {
        "latitude": station["lat"], "longitude": station["lon"],
        "start_date": f"{year}-01-01", "end_date": f"{year}-12-31",
        "hourly": "wind_speed_10m,wind_direction_10m",
        "models": "era5", "wind_speed_unit": "ms", "timezone": "GMT",
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urlencode(params)
    errors = []
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "IGE-P8.3F1-independent-science"}), timeout=140) as response:
                body = response.read(9500000)
            payload = json.loads(body)
            return decode_era5_year(payload, year), hashlib.sha256(body).hexdigest()
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc)[:100])
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("ERA5_F1_SOURCE_FAILED " + station["station_id"] + " " + "; ".join(errors))


def station_year(site, year):
    raw, sha = fetch(
        f"{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_h_historical_2020-2029.csv",
        max_bytes=37000000,
    )
    return parse_wind_year(raw, site, year), sha


def valid_pair(obs, background):
    return usable_wind(obs) and usable_wind(background)


def monthly_residuals(obs, background, min_count=MIN_MONTH_TRAIN):
    """Monthly vector and scalar biases from TRAIN year alone, never from holdout."""
    groups = collections.defaultdict(list)
    for stamp, o in obs.items():
        g = background.get(stamp)
        if not valid_pair(o, g):
            continue
        ou, ov = wind_from_to_uv(o["speed"], o.get("direction"))
        gu, gv = wind_from_to_uv(g["speed"], g.get("direction"))
        groups[stamp.month].append((o["speed"] - g["speed"], ou - gu, ov - gv))
    out = {}
    for month in range(1, 13):
        pairs = groups.get(month, [])
        if len(pairs) < min_count:
            raise ValueError(f"F1_MONTH_TRAIN_COVERAGE_{month}_{len(pairs)}")
        out[month] = {
            "n": len(pairs),
            "scalar_bias_mps": statistics.mean(x[0] for x in pairs),
            "u_bias_mps": statistics.mean(x[1] for x in pairs),
            "v_bias_mps": statistics.mean(x[2] for x in pairs),
        }
    return out


def donor_weights(target, donor_meta, n=N_DONORS):
    if target["station_id"] in donor_meta:
        raise ValueError("F1_TARGET_LEAKAGE_IN_DONORS")
    distances = sorted(
        (float(haversine(target["lat"], target["lon"], x["lat"], x["lon"])), sid)
        for sid, x in donor_meta.items()
    )
    if len(distances) < n:
        raise ValueError("F1_INSUFFICIENT_QUALIFIED_DONORS")
    selected = distances[:n]
    unscaled = [1 / max(d, .25)**2 for d, _ in selected]
    norm = sum(unscaled)
    return [(sid, d, w / norm) for (d, sid), w in zip(selected, unscaled)]


def blended_residual(month, selected, donor_climatology):
    if any(sid not in donor_climatology for sid, _, _ in selected):
        raise ValueError("F1_MISSING_DONOR_CLIMATOLOGY")
    return {
        field: sum(w * donor_climatology[sid][month][field] for sid, _, w in selected)
        for field in ("scalar_bias_mps", "u_bias_mps", "v_bias_mps")
    }


def correct_era5(hour, correction):
    """Scalar speed uses scalar residual; wind-FROM direction uses vector residual."""
    if not usable_wind(hour):
        return None
    u, v = wind_from_to_uv(hour["speed"], hour.get("direction"))
    new_u = u + correction["u_bias_mps"]
    new_v = v + correction["v_bias_mps"]
    vector_speed, direction = uv_to_wind_from(new_u, new_v)
    scalar = max(0., hour["speed"] + correction["scalar_bias_mps"])
    # Direction is unresolved below scalar calm threshold and if vector cancels.
    return {
        "speed": scalar,
        "direction": direction if scalar >= CALM_MPS and vector_speed >= CALM_MPS else None,
    }


def metrics(rows):
    """All contenders scored over precisely identical target-observed hours."""
    if not rows:
        raise ValueError("F1_EMPTY_COMMON_SCORE")
    result = {"n_hours": len(rows)}
    noncalm = [r for r in rows if r["observed"]["speed"] >= CALM_MPS]
    result["n_reference_noncalm"] = len(noncalm)
    for name in ("era5", "era5_residual", "station_idw4"):
        error = [r[name]["speed"] - r["observed"]["speed"] for r in rows]
        result[name] = {
            "speed_mae_mps": statistics.mean(abs(x) for x in error),
            "speed_rmse_mps": math.sqrt(statistics.mean(x*x for x in error)),
            "speed_bias_mps": statistics.mean(error),
        }
        direction = [
            circular_error_deg(r[name].get("direction"), r["observed"]["direction"])
            if r[name].get("direction") is not None else None
            for r in noncalm
        ]
        resolved = [x for x in direction if x is not None]
        result[name]["direction_resolved_n"] = len(resolved)
        result[name]["direction_mae_deg"] = statistics.mean(resolved) if resolved else None
        result[name]["direction_fixed90_deg"] = (
            statistics.mean(x if x is not None else 90. for x in direction)
            if direction else None
        )
    result["residual_vs_era5_mae_delta_mps"] = (
        result["era5_residual"]["speed_mae_mps"] - result["era5"]["speed_mae_mps"]
    )
    result["residual_vs_station_idw4_mae_delta_mps"] = (
        result["era5_residual"]["speed_mae_mps"] - result["station_idw4"]["speed_mae_mps"]
    )
    return result


def evaluate_target(target, selected, climatologies, era5_2024, obs_2024, donor_obs_2024):
    hours = annual_hours(HOLDOUT_YEAR)
    raw_rows = []
    month_errors = collections.Counter()
    station_donors = [
        (distance, {"station_id": sid}) for sid, distance, _ in selected
    ]
    corr = {m: blended_residual(m, selected, climatologies) for m in range(1, 13)}
    for stamp in hours:
        target_observed = obs_2024.get(stamp)
        background = era5_2024.get(stamp)
        if not valid_pair(target_observed, background):
            continue
        corrected = correct_era5(background, corr[stamp.month])
        station = interpolate(station_donors, donor_obs_2024, stamp)
        if corrected is None or station is None:
            month_errors[stamp.month] += 1
            continue
        baseline = {"speed": station["scalar_speed"], "direction": station["vector_direction"]}
        # For common directional coverage, missing direction is explicitly penalized.
        raw_rows.append({
            "stamp": stamp,
            "observed": target_observed,
            "era5": background,
            "era5_residual": corrected,
            "station_idw4": baseline,
        })
    if len(raw_rows) < math.ceil(MIN_HOLDOUT_FRACTION * len(hours)):
        raise ValueError(f"F1_COMMON_HOLDOUT_COVERAGE_{target}_{len(raw_rows)}")
    full = metrics(raw_rows)
    seasons = {
        "DJF": (12,1,2), "MAM": (3,4,5),
        "JJA": (6,7,8), "SON": (9,10,11),
    }
    seasonal = {s: metrics([r for r in raw_rows if r["stamp"].month in months])
                for s, months in seasons.items()}
    return {
        "target": target, "total_holdout_calendar_hours": len(hours),
        "fraction_common": len(raw_rows)/len(hours), "all_year": full,
        "seasons": seasonal,
        "selected_donors": [{"id": sid, "distance_km": d, "weight": w} for sid,d,w in selected],
        "monthly_donor_missing_prediction_count": dict(month_errors),
    }


def stage_f1():
    metadata_raw, metadata_sha = fetch(ROOT + "/ogd-smn_meta_stations.csv", max_bytes=1500000)
    metadata, _ = parse_meta(metadata_raw)
    candidates = {sid: metadata[sid] for sid in CANDIDATE_DONORS if sid in metadata}
    targets = {sid: metadata[sid] for sid in TARGETS}
    climatologies, donor_history, source_digest, rejected = {}, {}, {}, {}
    holdout_donor_sha256 = {}
    for sid, station in candidates.items():
        try:
            obs_train, swiss_sha = station_year(sid, TRAIN_YEAR)
            era_train, era_sha = era5_year(station, TRAIN_YEAR)
            month = monthly_residuals(obs_train, era_train)
            climatologies[sid] = month
            source_digest[sid] = {"swiss_historical_sha256": swiss_sha, "era5_2023_sha256": era_sha}
        except Exception as exc:
            rejected[sid] = type(exc).__name__ + ": " + str(exc)[:180]
    if len(climatologies) < N_DONORS:
        raise ValueError("F1_FEWER_THAN_FOUR_CALIBRATED_DONORS " + str(rejected))
    # Donor holdout obs used ONLY for baseline contemporaneous station IDW, never residual training.
    for sid in climatologies:
        observed, sha = station_year(sid, HOLDOUT_YEAR)
        donor_history[sid] = observed
        holdout_donor_sha256[sid] = sha
    sites = []
    for sid, station in targets.items():
        if sid in climatologies:
            raise AssertionError("F1_TARGET_PRESENT_IN_TRAINING")
        era_test, era_sha = era5_year(station, HOLDOUT_YEAR)
        observed, swiss_sha = station_year(sid, HOLDOUT_YEAR)
        selected = donor_weights(station, {s: metadata[s] for s in climatologies})
        result = evaluate_target(sid, selected, climatologies, era_test, observed, donor_history)
        result["source_sha256"] = {"era5_2024": era_sha, "observed_2024": swiss_sha}
        sites.append(result)
    return {
        "phase": "P8.3F1",
        "status": "FULL_YEAR_BLIND_TARGET_VALIDATION_EXECUTED__RESEARCH_NOT_PRODUCTION",
        "train_year": TRAIN_YEAR, "blind_target_holdout_year": HOLDOUT_YEAR,
        "targets": list(TARGETS), "candidate_donors": list(CANDIDATE_DONORS),
        "selected_training_donors": sorted(climatologies),
        "failed_donor_sources": rejected,
        "sources": F1_SOURCES, "metadata_source_sha256": metadata_sha,
        "training_sha256": source_digest,
        "holdout_donor_observation_sha256": holdout_donor_sha256,
        "sites": sites,
        "clock_convention": "nominal identical UTC hours, fixed before holdout; no posthoc clock shift optimization",
        "background": "Open-Meteo archive models=era5 (10m, GMT), gateway not native ECMWF file",
        "method": "2023 monthwise scalar+u/v ERA5 error climatology from other stations, spatial distance-IDW4 interpolation, frozen over independent 2024",
        "baselines": ["uncorrected_era5", "P8.3A same-hour distance_idw4"],
        "warning": "P8.3D terrain_idw4 and independent different-geography validation remain open; station observations are hourly averages while Open-Meteo wind fields are nominal instant values.",
        "uses_target_training_meteorology": False,
        "uses_holdout_target_for_calibration": False,
        "production_wind_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=("E1", "F1"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = stage_e1() if args.phase == "E1" else stage_f1()
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    filename = dest / ("p8_3" + args.phase.lower() + "_aggregate_provenance.json")
    filename.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print("IGE_P8_3" + args.phase + "_RESEARCH",
          json.dumps({"status": result["status"], "sites": len(result["sites"])}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
