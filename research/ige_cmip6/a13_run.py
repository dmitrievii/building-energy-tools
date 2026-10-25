"""Fixed A1.3 predictor and paired scoring; controls never enter prediction."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import math
import re
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from a13_prepare import ROOT, R, registered, parent_inputs, code_hashes, INPUTS, SEAL, PREDICTIONS, LEDGER, RESULTS, REGISTRATION
from a13_acquire import packet, assert_seal_code
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
from epw_climate_analyzer.station_admission import admitted_reference, admit_temperature
from epw_climate_analyzer.station_reconstruction import StationReference, decode_meteoswiss_hourly, model_reference_operator, reconstruct_temperature, distance_km, T

OPERATOR = "mean_six_10min_nominal_nodes"
QSTRATUM = "CH_PUBLISHED_HISTORICAL_NO_PER_ROW_QC_NOT_DWD_QN10_EQUIVALENT"


def clock_for(case, protocol):
    w = next(w for w in protocol["windows"] if w["season"] == case["season"])
    return pd.date_range(w["start_UTC"], periods=168, freq="h", tz="UTC")


def selected_temperature_csv(raw, sid, protocol):
    """Extract original T strings only after station/time/window selection.

    Full original assets are retained separately. This three-column CSV is a
    derived source subset, never mislabelled the full original asset SHA.
    """
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="strict")), delimiter=";")
    required = {"station_abbr", "reference_timestamp", "tre200h0"}
    if not required <= set(reader.fieldnames or []): raise ValueError("A13_SWISS_TEMPERATURE_SOURCE_SCHEMA")
    if len(set(reader.fieldnames)) != len(reader.fieldnames): raise ValueError("A13_DUPLICATE_SOURCE_COLUMNS")
    if any("tre200h0"+s in reader.fieldnames for s in ("_flag", "_qc")): raise ValueError("A13_UNDOCUMENTED_ROW_QC")
    windows = {w["season"]: (pd.Timestamp(w["start_UTC"], tz="UTC"), pd.Timestamp(w["end_UTC"], tz="UTC")+pd.Timedelta(hours=23)) for w in protocol["windows"]}
    selected = {s: [] for s in windows}; seen = set(); previous = None
    for row in reader:
        if None in row: raise ValueError("A13_SOURCE_EXTRA_COLUMNS")
        if (row["station_abbr"] or "").strip().upper() != sid: raise ValueError("A13_CROSS_STATION_SOURCE_ROW")
        stamp = (row["reference_timestamp"] or "").strip()
        # Historical decade containers may contain other years. No numeric
        # temperature is extracted from them or from unselected 2025 dates.
        if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", stamp): raise ValueError("A13_SOURCE_REFERENCE_FORMAT")
        if stamp[6:10] != "2025": continue
        when = pd.to_datetime(stamp, format="%d.%m.%Y %H:%M", utc=True)
        if when.minute: raise ValueError("A13_NON_HOURLY_SOURCE_REFERENCE")
        season = next((s for s,(a,b) in windows.items() if a <= when <= b), None)
        if season is None: continue
        if when in seen or (previous is not None and when < previous): raise ValueError("A13_DUPLICATE_OR_REORDERED_SELECTED_SOURCE")
        seen.add(when); previous = when
        selected[season].append([sid, stamp, row["tre200h0"]])
    result = {}
    for season, rows in selected.items():
        stream = io.StringIO(newline=""); writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(["station_abbr", "reference_timestamp", "tre200h0"]); writer.writerows(rows)
        result[season] = stream.getvalue().encode()
    return result


def bound_temperature(subset, row):
    if len(subset.splitlines()) == 1: return None
    frozen = row["frozen_station"]
    station = StationReference(**{k: frozen[k] for k in StationReference.__dataclass_fields__})
    return admit_temperature(decode_meteoswiss_hourly(subset, station), row)


def model_temperature(raw, spec):
    obj = json.loads(raw)
    if obj.get("utc_offset_seconds") != 0: raise ValueError("A13_NON_UTC_MODEL_RESPONSE")
    if obj.get("hourly_units", {}).get("temperature_2m") != "°C": raise ValueError("A13_MODEL_UNIT_NOT_CELSIUS")
    hourly = obj["hourly"]
    clock = pd.to_datetime(hourly["time"], utc=True)
    expected = pd.date_range("2025-01-01", periods=8760, freq="h", tz="UTC")
    if not clock.equals(expected): raise ValueError("A13_MODEL_ANNUAL_CLOCK_CHANGED")
    values = hourly["temperature_2m"]
    if len(values) != len(clock) or any(v is not None and (isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)) for v in values):
        raise ValueError("A13_MODEL_VALUE_AXIS_OR_TYPE")
    lat, lon = float(obj["latitude"]), float(obj["longitude"])
    if not math.isfinite(lat+lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180: raise ValueError("A13_MODEL_RESPONSE_COORDINATES")
    req = spec["parameters"]
    point = StationReference("CH", "request", "request", float(req["latitude"]), float(req["longitude"]), 0., "0"*64)
    grid = StationReference("CH", "grid", "grid", lat, lon, 0., "0"*64)
    separation = distance_km(point, grid)
    if separation > 50: raise ValueError("A13_RESPONSE_GRID_MORE_THAN_50KM_AWAY")
    result = pd.Series(np.asarray(values, dtype=float), index=clock, name=T); result.attrs["unit"] = "°C"
    result = result.where(result.between(-80., 65.)); result.attrs["unit"] = "°C"
    return result, {"requested_xy": [point.latitude, point.longitude], "returned_provider_grid_xy": [lat, lon],
        "distance_km": separation, "provider_elevation_unverified": obj.get("elevation"),
        "model_request": "era5", "elevation_request": "nan", "cell_selection": "nearest",
        "native_ERA5_orography_verified": False, "missing_or_outside_A1_domain_hours": int(result.isna().sum())}


def checked_sources(path, phase, *, expected_sha=None):
    bodies, manifest = packet(path, expected_sha=expected_sha, expected_phase=phase)
    plan = registered(); expected = {s["id"]: s for s in plan[phase]}
    if manifest["registration_sha256"] != sha256((R/REGISTRATION).read_bytes()).hexdigest(): raise ValueError("A13_SOURCE_REGISTRATION_HASH")
    if len(manifest["sources"]) != len(expected) or {r["id"] for r in manifest["sources"]} != set(expected): raise ValueError("A13_SOURCE_PHASE_CENSUS")
    if set(bodies) != {r["member"] for r in manifest["sources"] if r["status"] == "ORIGINAL_BODY_RECEIVED"}:
        raise ValueError("A13_UNREGISTERED_BODY_IN_SOURCE_PACKET")
    for row in manifest["sources"]:
        spec = expected[row["id"]]
        if any(row[k] != spec[k] for k in ("id", "station_key", "kind", "role", "url", "member")): raise ValueError("A13_SOURCE_CONTRACT_CHANGED")
        if row["status"] == "ORIGINAL_BODY_RECEIVED":
            raw = bodies[row["member"]]
            if len(raw) != row["bytes"] or sha256(raw).hexdigest() != row["sha256"]: raise ValueError("A13_ORIGINAL_SOURCE_RECEIPT_HASH")
    if phase == "inputs" and manifest["control_bodies_opened_this_phase"] is not False: raise ValueError("A13_CONTROL_IN_PREDICTOR_PACKET")
    return bodies, manifest


def make_predictions(input_path):
    plan = registered(); protocol, admission = parent_inputs()
    bodies, manifest = checked_sources(input_path, "inputs")
    models, donors, source_diagnostics = {}, {}, {}
    for spec, receipt in zip(plan["inputs"], manifest["sources"]):
        # IDs are checked as a set above; do not rely on the receipt order.
        receipt = next(r for r in manifest["sources"] if r["id"] == spec["id"])
        key = spec["station_key"]
        if receipt["status"] != "ORIGINAL_BODY_RECEIVED":
            source_diagnostics[spec["id"]] = {"status": "SOURCE_BLOCKED", "reason": "ORIGINAL_BODY_NOT_RECEIVED"}; continue
        raw = bodies[spec["member"]]
        if spec["kind"] == "model_background":
            models[key], proof = model_temperature(raw, spec); source_diagnostics[spec["id"]] = proof
        else:
            if key in {s["station_key"] for s in plan["controls"]}: raise ValueError("A13_TARGET_OBSERVATIONS_IN_PREDICTION")
            subsets = selected_temperature_csv(raw, key.split(":")[1], protocol)
            donors[key] = {season: bound_temperature(body, admission["station_windows"][key][season]) for season, body in subsets.items()}
            source_diagnostics[spec["id"]] = {"original_body_sha256": sha256(raw).hexdigest(),
                "derived_subset_sha256": {s: sha256(b).hexdigest() for s,b in subsets.items()},
                "selected_observation_rows": {s: len(b.splitlines())-1 for s,b in subsets.items()}}
    frames, cases = [], []
    for case in admission["cases"]:
        key, season = case["target_key"], case["season"]; clock = clock_for(case, protocol)
        frame = pd.DataFrame({"target_key": key, "season": season, "reference_time_UTC": clock.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "B0_C": np.nan, "R1_C": np.nan, "proposed_delta_K": np.nan, "accepted_donor_count": 0,
            "prediction_admitted": False, "status": "SOURCE_BLOCKED"})
        for i, donor in enumerate(case["frozen_donor_slots"], 1): frame["donor_"+str(i)] = donor; frame["weight_"+str(i)] = 0.
        reasons = list(case["source_block_reasons"])
        if case["strict_T2m_metadata_ready"]:
            trow = admission["station_windows"][key][season]
            if key not in models: reasons.append("TARGET_BACKGROUND_SOURCE_BLOCKED")
            else:
                baseline = model_reference_operator(models[key], clock, OPERATOR); frame["B0_C"] = baseline.to_numpy()
                references, observed, background, quality = [], {}, {}, {}
                for donor in case["metadata_admitted_donors"]:
                    row = admission["station_windows"][donor][season]; ref = admitted_reference(row)
                    references.append(ref); bound = donors.get(donor, {}).get(season)
                    values = bound.values if bound else pd.Series(np.nan, index=clock)
                    values.attrs.update({"unit": "°C", "reference_operator": OPERATOR})
                    observed[donor] = values
                    background[donor] = (model_reference_operator(models[donor], clock, OPERATOR) if donor in models else values*float("nan"))
                    background[donor].attrs.update({"unit": "°C", "reference_operator": OPERATOR})
                    quality[donor] = bound.quality_accepted if bound else pd.Series(False, index=clock)
                    if bound is None or donor not in models: reasons.append("DONOR_INPUT_SOURCE_BLOCKED:"+donor)
                estimate, ledger = reconstruct_temperature(admitted_reference(trow), baseline, references, observed, background, quality)
                frame["R1_C"] = estimate.to_numpy(); frame["proposed_delta_K"] = ledger["proposed_delta_K"].to_numpy()
                frame["accepted_donor_count"] = ledger["accepted_donor_count"].to_numpy()
                frame["prediction_admitted"] = ledger["candidate_admitted"].to_numpy()
                frame["status"] = np.where(frame["prediction_admitted"], "PREDICTED", "INPUT_QC_OR_COVERAGE_BLOCKED")
                for i, donor in enumerate(case["frozen_donor_slots"], 1):
                    if "weight__"+donor in ledger: frame["weight_"+str(i)] = ledger["weight__"+donor].to_numpy()
        cases.append({**case, "source_block_reasons_at_prediction": reasons,
            "actual_B0_reference_hours": int(frame["B0_C"].notna().sum()), "actual_R1_reference_hours": int(frame["prediction_admitted"].sum()),
            "ERA5_or_donor_weather_acquired": key in models,
            "predictions_created_or_sealed": bool(frame["B0_C"].notna().any()),
            "prediction_ledger_entry_created": True,
            "donor_QC_and_coverage_evaluated": case["strict_T2m_metadata_ready"] and key in models,
            "control_observations_used": False})
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    raw = combined.to_csv(index=False, float_format="%.10f", na_rep="", lineterminator="\n").encode()
    ledger = {"schema": "IGE_A13_24_CASE_PREDICTION_LEDGER_v1", "cases": cases, "source_diagnostics": source_diagnostics,
        "all_24_cases_retained": True, "requested_reference_hours": 4032,
        "actual_R1_predicted_hours": int(combined["prediction_admitted"].sum()), "target_observation_input": False}
    return raw, ledger, manifest


def predict(input_path, output):
    output.mkdir(parents=True, exist_ok=False)
    raw, ledger, acquisition = make_predictions(input_path)
    write_exclusive(output/PREDICTIONS, raw); write_exclusive(output/LEDGER, json_bytes(ledger))
    seal = {"schema": "IGE_A13_ACTUAL_PREDICTION_SEAL_v1", "created_UTC": datetime.now(timezone.utc).isoformat(),
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "registration_sha256": sha256((R/REGISTRATION).read_bytes()).hexdigest(), "code_sha256": code_hashes(),
        "frozen_files_sha256": {INPUTS: sha256(Path(input_path).read_bytes()).hexdigest(), PREDICTIONS: sha256(raw).hexdigest(), LEDGER: sha256(json_bytes(ledger)).hexdigest()},
        "control_observation_bodies_opened": False, "target_observations_used_as_predictors": False,
        "prediction_rows": 4032, "actual_R1_predicted_hours": ledger["actual_R1_predicted_hours"],
        "parent_exposure_class": "PREVIOUSLY_REVEALED_SOURCE_CONTAINERS_NOT_STRICTLY_BLIND",
        "independent_accuracy_qualified": False, "production_ready": False}
    write_exclusive(output/SEAL, json_bytes(seal)); print(json.dumps({k:v for k,v in seal.items() if k != "code_sha256"}, indent=2))
    return seal


def load_predictions(raw):
    frame = pd.read_csv(io.BytesIO(raw), dtype={"prediction_admitted": str})
    if not frame["prediction_admitted"].isin(["True", "False"]).all(): raise ValueError("A13_PREDICTION_BOOLEAN_FORMAT")
    frame["prediction_admitted"] = frame["prediction_admitted"].map({"True": True, "False": False})
    frame["reference_time_UTC"] = pd.to_datetime(frame["reference_time_UTC"], utc=True)
    if len(frame) != 4032 or frame.duplicated(["target_key", "reference_time_UTC"]).any(): raise ValueError("A13_FROZEN_PREDICTION_CENSUS")
    return frame


def metrics(error):
    error = np.asarray(error, dtype=float)
    if not np.isfinite(error).all(): raise ValueError("A13_NONFINITE_SCORED_ERROR")
    return {"n": len(error), "MAE_K": float(np.abs(error).mean()) if len(error) else None,
        "RMSE_K": float(np.sqrt(np.mean(error**2))) if len(error) else None, "bias_K": float(error.mean()) if len(error) else None}


def block_comparison(blocks):
    nonempty = [(a,b) for a,b in blocks if len(a)]
    if not nonempty: return {"B0": metrics([]), "R1": metrics([]), "delta_MAE_K": None, "complete_blocks": 0, "bootstrap_95pct": None}
    b0 = np.concatenate([a for a,b in nonempty]); r1 = np.concatenate([b for a,b in nonempty])
    result = {"B0": metrics(b0), "R1": metrics(r1), "delta_MAE_K": float(np.abs(r1).mean()-np.abs(b0).mean()), "complete_blocks": len(nonempty), "bootstrap_95pct": None}
    if len(nonempty) >= 2:
        sizes = np.array([len(a) for a,b in nonempty]); changes = np.array([np.abs(b).sum()-np.abs(a).sum() for a,b in nonempty])
        rng = np.random.Generator(np.random.PCG64(20261025)); draws = rng.integers(0, len(nonempty), size=(10000, len(nonempty)))
        delta = changes[draws].sum(axis=1)/sizes[draws].sum(axis=1)
        lo, hi = np.quantile(delta, [.025, .975], method="linear")
        result["bootstrap_95pct"] = {"lower_K": float(lo), "upper_K": float(hi), "draws": 10000, "seed": 20261025,
            "unit": "whole target-season 7-day blocks; limited eight CH blocks, dependence between stations not eliminated"}
    return result


def compare(prediction_raw, ledger, control_path):
    protocol, admission = parent_inputs(); bodies, acquisition = checked_sources(control_path, "controls")
    predictions = load_predictions(prediction_raw)
    controls = {}
    for row in acquisition["sources"]:
        if row["status"] != "ORIGINAL_BODY_RECEIVED": continue
        controls[row["station_key"]] = selected_temperature_csv(bodies[row["member"]], row["station_key"].split(":")[1], protocol)
    cases, pairs, blocks = [], [], []
    per_target = {s["station_key"]: [] for s in registered()["controls"]}
    for case in ledger["cases"]:
        key, season = case["target_key"], case["season"]
        clock = clock_for(case, protocol); p = predictions[(predictions.target_key == key) & (predictions.season == season)]
        if len(p) != 168 or not pd.DatetimeIndex(p.reference_time_UTC).equals(clock): raise ValueError("A13_PREDICTION_CASE_CLOCK_CHANGED")
        result = {"target_key": key, "season": season, "quality_stratum": QSTRATUM if key.startswith("CH:") else "SOURCE_BLOCKED",
            "requested_hours": 168, "predicted_hours": int(p.prediction_admitted.sum()), "observed_primary_QC_hours": 0,
            "source_block_reasons": list(case["source_block_reasons_at_prediction"]), "status": "SOURCE_BLOCKED",
            "B0_all_reference": metrics([]), "B0_paired": metrics([]), "R1_paired": metrics([]), "delta_MAE_K": None}
        if key in controls and case["strict_T2m_metadata_ready"]:
            bound = bound_temperature(controls[key][season], admission["station_windows"][key][season])
            if bound is not None:
                observed = bound.values.reindex(clock).to_numpy(dtype=float); quality = bound.quality_accepted.reindex(clock).fillna(False).to_numpy(dtype=bool)
                b0, r1 = p.B0_C.to_numpy(), p.R1_C.to_numpy()
                target_ok = quality & np.isfinite(observed)
                baseline_ok = target_ok & np.isfinite(b0)
                common = baseline_ok & p.prediction_admitted.to_numpy(dtype=bool) & np.isfinite(r1)
                error0, error1 = b0[common]-observed[common], r1[common]-observed[common]
                result.update({"status": "SCORED_EXPOSED_SOURCE" if common.any() else "NO_MATCHED_QC_HOURS",
                    "observed_primary_QC_hours": int(target_ok.sum()), "B0_all_reference": metrics(b0[baseline_ok]-observed[baseline_ok]),
                    "B0_paired": metrics(error0), "R1_paired": metrics(error1),
                    "delta_MAE_K": float(np.abs(error1).mean()-np.abs(error0).mean()) if common.any() else None})
                blocks.append((error0, error1)); per_target[key].append((error0, error1))
                for i in np.flatnonzero(common): pairs.append({"target_key": key, "season": season, "reference_time_UTC": clock[i].isoformat(),
                    "observed_C": float(observed[i]), "B0_C": float(b0[i]), "R1_C": float(r1[i])})
            else: result["source_block_reasons"].append("NO_CONTROL_ROWS_IN_FROZEN_REFERENCE_WINDOW")
        elif case["strict_T2m_metadata_ready"]: result["source_block_reasons"].append("CONTROL_ORIGINAL_SOURCE_NOT_RECEIVED")
        cases.append(result)
    return {"schema": "IGE_A13_REVEALED_SOURCE_TEMPERATURE_COMPARISON_v1",
        "status": "EXPOSED_SOURCE_RESEARCH_COMPARISON_NOT_INDEPENDENT_QUALIFICATION", "cases": cases,
        "pooled_CH": block_comparison(blocks), "per_target": {k: block_comparison(v) for k,v in per_target.items()},
        "counts": {"frozen_cases": len(cases), "source_blocked_cases": sum(r["status"] == "SOURCE_BLOCKED" for r in cases),
            "scored_cases": sum(r["status"] == "SCORED_EXPOSED_SOURCE" for r in cases), "paired_hours": len(pairs)},
        "source_byte_blind": False, "target_T_2025_before_this_stage_fitting_or_errors_demonstrated": False,
        "target_T_opened_only_after_published_prediction_seal": True, "independent_accuracy_qualified": False,
        "full_weather_physical_closure_qualified": False, "production_ready": False, "UI_or_EPW_defaults_changed": False,
        "IV1_observations_opened": False, "AT_DE_measurements_opened": False}, pairs


def score(control_path, output):
    output.mkdir(parents=True, exist_ok=False)
    seal = json.loads((R/SEAL).read_text()); assert_seal_code(seal)
    raw = (R/PREDICTIONS).read_bytes(); ledger_raw = (R/LEDGER).read_bytes()
    if any(sha256(b).hexdigest() != seal["frozen_files_sha256"][n] for n,b in ((PREDICTIONS, raw), (LEDGER, ledger_raw))): raise ValueError("A13_SEALED_PREDICTIONS_CHANGED")
    _, control_manifest = checked_sources(control_path, "controls")
    gate = control_manifest["published_seal_gate"]
    if gate is None or gate["seal_sha256"] != sha256((R/SEAL).read_bytes()).hexdigest(): raise ValueError("A13_CONTROL_PACKET_NOT_BOUND_TO_PUBLISHED_SEAL")
    result, pairs = compare(raw, json.loads(ledger_raw), control_path)
    result.update({"prediction_seal_sha256": gate["seal_sha256"], "published_seal_commit": gate["commit"],
        "control_packet_sha256": sha256(Path(control_path).read_bytes()).hexdigest(),
        "predictor_packet_sha256": seal["frozen_files_sha256"][INPUTS], "code_commit": seal["code_commit"],
        "acquisition_decoded_body_bytes_cumulative": control_manifest["decoded_body_bytes_read_all_attempts"]})
    write_exclusive(output/RESULTS, json_bytes(result))
    write_exclusive(output/"a13_paired_temperatures_20261025.csv", pd.DataFrame(pairs).to_csv(index=False, float_format="%.10f", lineterminator="\n").encode())
    print(json.dumps({"counts": result["counts"], "pooled_CH": result["pooled_CH"], "per_target": result["per_target"]}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("mode", choices=("predict", "score"))
    parser.add_argument("--sources", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); (predict if args.mode == "predict" else score)(args.sources, args.out)
