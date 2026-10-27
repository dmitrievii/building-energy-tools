"""V2 fixed R1 prediction, actual seal, and separate held-out scoring.

2019 primary reference operators only. No target argument in prediction and
no CH inverse/endpoints. Code/QC/scoring are published before predictor data.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

from v2_weather_registration import (R, REG, ADMISSION, INPUTS, CONTROLS, PREDICTIONS, LEDGER, SEAL, RESULTS,
    WINDOWS, registered, admission, publication_gate)
from v2_weather_io import read_packet, control_admission, allowed_spec
from v1_time_admission import selected_swiss, selected_dwd, decode_at, bind
from epw_climate_analyzer.station_admission import admitted_reference
from epw_climate_analyzer.station_reconstruction import (T, StationReference, distance_km,
    model_reference_operator, reconstruct_temperature)
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive


def sources(directory, name, phase, plan):
    members, manifest, storage = read_packet(directory, name, phase)
    if manifest["registration_sha256"] != sha256((R / REG).read_bytes()).hexdigest() or [r["spec"] for r in manifest["sources"]] != plan[phase]:
        raise ValueError("V2_SOURCE_REGISTRATION_OR_INVENTORY_CHANGED")
    attempts = [n for r in manifest["sources"] for n in r["attempts"]]
    if (sum(n["body_bytes_read"] for n in attempts) != manifest["body_bytes_phase"] or
            sum(bool(n["HTTP_attempted"]) for n in attempts) != manifest["HTTP_attempts_phase"]):
        raise ValueError("V2_SOURCE_ATTEMPT_BYTE_CENSUS")
    if (not 0 <= manifest["cumulative_HTTP_attempts"] <= plan["budget"]["HTTP_attempts_inputs_plus_controls_max"] or
            not 0 <= manifest["cumulative_body_bytes"] <= plan["budget"]["body_bytes_all_attempts_inputs_plus_controls_max"] or
            phase == "inputs" and (manifest["cumulative_HTTP_attempts"] != manifest["HTTP_attempts_phase"] or manifest["cumulative_body_bytes"] != manifest["body_bytes_phase"])):
        raise ValueError("V2_SOURCE_GLOBAL_BUDGET_OR_CENSUS")
    if set(members) != {n["member"] for n in attempts if n.get("member")}:
        raise ValueError("V2_UNREGISTERED_RESPONSE_MEMBER")
    if phase == "inputs" and manifest["control_bodies_opened"]:
        raise ValueError("V2_CONTROL_IN_INPUT_PACKET")
    bodies = {}; reasons = {}
    for row in manifest["sources"]:
        s = row["spec"]
        if len(row["attempts"]) > 3 or any(n["number"] != i for i, n in enumerate(row["attempts"], 1)):
            raise ValueError("V2_ASSET_ATTEMPT_CENSUS")
        if row["attempts"]:
            allowed_spec(s, phase, plan)
        for n in row["attempts"]:
            if n.get("member"):
                raw = members[n["member"]]
                if len(raw) != n["bytes"] or sha256(raw).hexdigest() != n["sha256"]:
                    raise ValueError("V2_RESPONSE_RECEIPT_CHANGED")
        if row["status"] == "ORIGINAL_BODY_RECEIVED":
            n = row["attempts"][-1]
            if n["status"] != row["status"] or n["member"] != row["original_member"]:
                raise ValueError("V2_ORIGINAL_RESPONSE_SELECTION_CHANGED")
            bodies[s["id"]] = members[row["original_member"]]
        else:
            reasons[s["id"]] = row["reason"]
    return bodies, reasons, manifest, storage


def model_temperature(raw, spec):
    obj = json.loads(raw)
    if obj.get("utc_offset_seconds") != 0 or obj.get("hourly_units", {}).get("temperature_2m") != "°C":
        raise ValueError("V2_BACKGROUND_UTC_OR_CELSIUS")
    h = obj["hourly"]; clock = pd.to_datetime(h["time"], utc=True)
    if not clock.equals(pd.date_range("2019-01-01", periods=8760, freq="h", tz="UTC")):
        raise ValueError("V2_BACKGROUND_2019_CALENDAR_CHANGED")
    values = h["temperature_2m"]
    if len(values) != 8760 or any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)) for v in values):
        raise ValueError("V2_BACKGROUND_NONNUMERIC_OR_NONFINITE")
    c = spec["station_key"][:2]; p = spec["parameters"]
    req = StationReference(c, "request", "request", float(p["latitude"]), float(p["longitude"]), 0., "0" * 64)
    grid = StationReference(c, "grid", "grid", float(obj["latitude"]), float(obj["longitude"]), 0., "0" * 64)
    separation = distance_km(req, grid)
    if separation > 50:
        raise ValueError("V2_BACKGROUND_RETURNED_CELL_OVER_50KM")
    s = pd.Series(np.asarray(values, dtype=float), index=clock, name=T)
    s = s.where(s.between(-80, 65)); s.attrs["unit"] = "°C"
    return s, {"returned_xy": [grid.latitude, grid.longitude], "requested_xy": [req.latitude, req.longitude],
        "grid_separation_km": separation, "reported_provider_height_unverified_m": obj.get("elevation"),
        "native_orography_and_height_datum_qualified": False, "array_sha256": sha256(json_bytes(values)).hexdigest(),
        "missing_or_out_of_domain_hours": int(s.isna().sum())}


def dwd_product(raw, sid):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [n for n in archive.namelist() if n.startswith("produkt_zehn_min_tu_")]
        if len(names) != 1 or Path(names[0]).name != names[0] or not names[0].endswith("_" + sid + ".txt"):
            raise ValueError("V2_DE_PRODUCT_IDENTITY_OR_CENSUS")
        if archive.getinfo(names[0]).file_size > 150_000_000:
            raise ValueError("V2_DE_UNCOMPRESSED_PRODUCT_BUDGET")
        return archive.read(names[0])


def station_values(raw, key, record, first, last):
    c, sid = key.split(":"); ref = admitted_reference(record)
    if first < pd.Timestamp(record["reference_first_UTC"]) or last > pd.Timestamp(record["reference_last_UTC"]):
        raise ValueError("V2_STATION_REQUEST_OUTSIDE_DATED_GEOMETRY")
    if c == "CH":
        v, q = selected_swiss(raw, sid, first, last)
        flags = pd.Series("PUBLISHED_NO_ROW_QC", index=v.index)
    elif c == "DE":
        batch = selected_dwd(dwd_product(raw, sid), ref, first, last)
        if batch is None:
            clock = pd.DatetimeIndex([], tz="UTC")
            v = pd.Series([], index=clock, dtype=float); q = pd.Series([], index=clock, dtype=bool)
            flags = pd.Series([], index=clock, dtype=str)
        else:
            v, q = bind(batch, record, provider_field="TT_10")
            flags = batch.data["quality_flag__" + T].copy()
    else:
        batch = decode_at(raw, ref)
        v, _ = bind(batch, record, provider_field="tl")
        flags = batch.data["quality_flag__" + T].copy()
        # New V2 product stratum only: old V1 QC22 decoder/code never modified.
        q = flags.eq("10") & v.between(-80, 65)
    v = v.loc[first:last].copy(); q = q.reindex(v.index).fillna(False).astype(bool)
    flags = flags.reindex(v.index)
    v.attrs.update(unit="°C", reference_operator=record["time_contract"]["operator"])
    return v, q, flags


def metrics(error):
    x = np.asarray(error, dtype=float)
    if not np.isfinite(x).all():
        raise ValueError("V2_NONFINITE_ERROR")
    return {"n": len(x), "MAE_K": float(np.abs(x).mean()) if len(x) else None,
        "RMSE_K": float(np.sqrt(np.mean(x * x))) if len(x) else None,
        "bias_K": float(x.mean()) if len(x) else None,
        "centred_RMSE_K": float(np.sqrt(np.mean((x - x.mean()) ** 2))) if len(x) else None}


def delta_summary(pairs):
    if not pairs:
        return {"B0": metrics([]), "R1": metrics([]), "delta_MAE_K": None}
    a = np.concatenate([x for x, y in pairs]); b = np.concatenate([y for x, y in pairs])
    return {"B0": metrics(a), "R1": metrics(b), "delta_MAE_K": float(np.abs(b).mean() - np.abs(a).mean()) if len(a) else None}


def make_predictions(plan, a, bodies, source_blocks):
    models, observed, quality, flags, diagnostics = {}, {}, {}, {}, {}
    first = pd.Timestamp(WINDOWS[0]["start_UTC"]); last = pd.Timestamp(WINDOWS[-1]["end_UTC"])
    for spec in plan["inputs"]:
        key, name = spec["station_key"], spec["id"]
        if name not in bodies:
            diagnostics[name] = {"status": "SOURCE_BLOCKED", "reason": source_blocks.get(name, "NO_ORIGINAL")}; continue
        try:
            if spec["kind"] == "model_background":
                models[key], diagnostics[name] = model_temperature(bodies[name], spec)
            else:
                if key in plan["target_keys"]:
                    raise ValueError("V2_TARGET_IN_PREDICTORS")
                observed[key], quality[key], flags[key] = station_values(bodies[name], key, a["records"][key], first, last)
        except (ValueError, KeyError, TypeError, zipfile.BadZipFile, UnicodeError) as exc:
            diagnostics[name] = {"status": "SOURCE_BLOCKED", "reason": type(exc).__name__ + ":" + str(exc)[:200]}
    frames, cases, loo = [], [], []
    for group in plan["groups"]:
        key = group["target_key"]; op = a["records"][key]["time_contract"]["operator"]
        for window in WINDOWS:
            clock = pd.date_range(window["start_UTC"], window["end_UTC"], freq="h")
            nan = lambda: pd.Series(np.nan, index=clock, dtype=float)
            baseline = model_reference_operator(models[key], clock, op) if key in models else nan()
            baseline.attrs.update(unit="°C", reference_operator=op)
            refs, obs, bg, qc = [], {}, {}, {}
            f = pd.DataFrame({"target_key": key, "country": key[:2], "season": window["season"],
                "reference_time_UTC": clock.strftime("%Y-%m-%dT%H:%M:%SZ"), "operator": op, "B0_C": baseline.to_numpy()})
            native_counts = {}
            for slot, d in enumerate(group["donors"], 1):
                refs.append(admitted_reference(a["records"][d]))
                obs[d] = observed.get(d, nan()).reindex(clock).copy()
                bg[d] = model_reference_operator(models[d], clock, op) if d in models else nan()
                qc[d] = quality.get(d, pd.Series(False, index=clock)).reindex(clock).fillna(False).astype(bool)
                for s in (obs[d], bg[d]): s.attrs.update(unit="°C", reference_operator=op)
                native = flags.get(d, pd.Series("NO_SOURCE", index=clock)).reindex(clock).fillna("MISSING_ROW")
                native_counts[d] = {str(code): int(n) for code, n in native.value_counts(dropna=False).items()}
                f["donor_" + str(slot)] = d
                f["donor_primary_accepted_" + str(slot)] = qc[d].to_numpy()
            estimate, weights = reconstruct_temperature(admitted_reference(a["records"][key]), baseline, refs, obs, bg, qc)
            f["R1_C"] = estimate.to_numpy(); f["R1_predicted"] = weights.candidate_admitted.to_numpy()
            f["accepted_donor_count"] = weights.accepted_donor_count.to_numpy()
            f["effective_weight_count"] = 0.
            squares = np.zeros(168)
            for slot, d in enumerate(group["donors"], 1):
                f["weight_" + str(slot)] = weights["weight__" + d].to_numpy(); squares += f["weight_" + str(slot)].to_numpy() ** 2
            f["effective_weight_count"] = np.divide(1., squares, out=np.zeros(168), where=squares > 0)
            f["status"] = np.where(f.R1_predicted, "PREDICTED", "INPUT_QC_OR_SOURCE_BLOCKED")
            reasons = {s["id"]: diagnostics[s["id"]] for s in plan["inputs"]
                       if s["station_key"] in [key, *group["donors"]] and diagnostics.get(s["id"], {}).get("status") == "SOURCE_BLOCKED"}
            paired = np.isfinite(f.B0_C) & np.isfinite(f.R1_C) & f.R1_predicted
            cases.append({"target_key": key, "country": key[:2], "season": window["season"], "requested_hours": 168,
                "frozen_donors": group["donors"], "B0_hours": int(np.isfinite(f.B0_C).sum()),
                "R1_hours": int(f.R1_predicted.sum()), "finite_paired_forecast_hours": int(paired.sum()),
                "native_donor_QC_counts": native_counts, "source_blocks": reasons, "control_values_read": False})
            # Donor-only diagnostic. The original three-donor/min-two rule stays
            # unchanged, including its distance/identity domain for each LOO fit.
            if len(refs) == 3:
                for held in refs:
                    other = [r for r in refs if r.key != held.key]
                    diagnostic = {"target_group": key, "held_donor": held.key, "season": window["season"], "accuracy_gate": False}
                    try:
                        pred, _ = reconstruct_temperature(held, bg[held.key], other, obs, bg, qc)
                        mask = qc[held.key] & obs[held.key].notna() & pred.notna() & bg[held.key].notna()
                        diagnostic.update(status="DONOR_ONLY_DESCRIPTIVE", **delta_summary([
                            ((bg[held.key] - obs[held.key])[mask].to_numpy(), (pred - obs[held.key])[mask].to_numpy())]))
                    except ValueError as exc:
                        diagnostic.update(status="LOO_NOT_IN_FROZEN_GEOMETRY_DOMAIN", reason=str(exc))
                    loo.append(diagnostic)
            frames.append(f)
    frame = pd.concat(frames, ignore_index=True)
    if len(frame) != 12096 or len(cases) != 72 or frame.duplicated(["target_key", "reference_time_UTC"]).any():
        raise ValueError("V2_ACTUAL_PREDICTION_CENSUS")
    cell_groups, array_groups = {}, {}
    for s in plan["inputs"]:
        d = diagnostics.get(s["id"], {})
        if "returned_xy" in d:
            cell_groups.setdefault(str(d["returned_xy"]), []).append(s["station_key"])
            array_groups.setdefault(d["array_sha256"], []).append(s["station_key"])
    geometry = {g["target_key"]: {d: {"distance_km": distance_km(admitted_reference(a["records"][g["target_key"]]), admitted_reference(a["records"][d])),
                  "nominal_height_delta_m_unverified_datum": a["records"][d]["frozen_station"]["nominal_site_elevation_m"] - a["records"][g["target_key"]]["frozen_station"]["nominal_site_elevation_m"]} for d in g["donors"]} for g in plan["groups"]}
    ledger = {"schema": "IGE_V2_ACTUAL_PRECONTROL_LEDGER_v1", "cases": cases, "requested_reference_hours": 12096,
        "predicted_R1_hours": int(frame.R1_predicted.sum()), "source_diagnostics": diagnostics, "geometry_proxies": geometry,
        "shared_returned_cells": cell_groups, "identical_model_arrays": array_groups,
        "effective_weight_count_is_not_independent_sample_size": True, "donor_only_LOO": loo,
        "control_observation_input": False, "all72_cases_retained": True}
    ledger["control_admission"] = control_admission(plan, ledger)
    raw = frame.to_csv(index=False, float_format="%.10f", na_rep="", lineterminator="\n").encode()
    return raw, ledger


def predict(output, commit):
    plan = registered(); gate = publication_gate(commit)
    bodies, reasons, m, storage = sources(R, INPUTS, "inputs", plan)
    raw, ledger = make_predictions(plan, admission(), bodies, reasons)
    output.mkdir(parents=True, exist_ok=False)
    write_exclusive(output / PREDICTIONS, raw); write_exclusive(output / LEDGER, json_bytes(ledger))
    frozen = {PREDICTIONS: sha256(raw).hexdigest(), LEDGER: sha256(json_bytes(ledger)).hexdigest()}
    for name in [INPUTS + ".storage.json", *[p["name"] for p in storage["parts"]]]:
        frozen[name] = sha256((R / name).read_bytes()).hexdigest()
    seal = {"schema": "IGE_V2_ACTUAL_PRECONTROL_PREDICTION_SEAL_v1", "publication_gate": gate,
        "created_UTC_runner_clock_untrusted": datetime.now(timezone.utc).isoformat(),
        "registration_sha256": sha256((R / REG).read_bytes()).hexdigest(), "code_sha256": plan["code_sha256"],
        "frozen_files_sha256": frozen, "original_input_packet_sha256": storage["sha256"],
        "control_bodies_opened": False, "control_admission": ledger["control_admission"],
        "all72_cases_and12096_rows_retained": True, "predicted_R1_hours": ledger["predicted_R1_hours"],
        "independent_accuracy_qualified": False, "production_ready": False}
    write_exclusive(output / SEAL, json_bytes(seal))
    return seal


def load_predictions(raw, plan):
    f = pd.read_csv(io.BytesIO(raw)); f["reference_time_UTC"] = pd.to_datetime(f.reference_time_UTC, utc=True)
    if len(f) != 12096 or set(f.target_key) != set(plan["target_keys"]) or f.R1_predicted.dtype != bool or f.duplicated(["target_key", "reference_time_UTC"]).any():
        raise ValueError("V2_PREDICTION_CENSUS_OR_SCHEMA")
    for k in plan["target_keys"]:
        for w in WINDOWS:
            part = f[(f.target_key == k) & (f.season == w["season"])]
            if not pd.DatetimeIndex(part.reference_time_UTC).equals(pd.date_range(w["start_UTC"], w["end_UTC"], freq="h")):
                raise ValueError("V2_PREDICTION_CASE_CLOCK")
    if not (np.isfinite(f.R1_C) == f.R1_predicted).all() or not np.isfinite(f.loc[f.R1_predicted, "B0_C"]).all():
        raise ValueError("V2_PREDICTED_FLAG_OR_BASELINE_MISMATCH")
    return f


def country_summary(country, cases, errors):
    selected = [c for c in cases if c["country"] == country]
    good = [c for c in selected if c["paired_hours"] >= 160]
    admitted = delta_summary([errors[(c["target_key"], c["season"])] for c in good])
    stations = {k: delta_summary([errors[(c["target_key"], c["season"])] for c in good if c["target_key"] == k]) for k in sorted({c["target_key"] for c in selected})}
    changes = [v["delta_MAE_K"] for v in stations.values() if v["delta_MAE_K"] is not None]
    uniform = len(good) == 24 and admitted["delta_MAE_K"] is not None and admitted["delta_MAE_K"] < 0 and len(stations) == 6 and len(changes) == 6 and max(changes) <= 0
    result = {"admitted_cases": len(good), "registered_cases": 24, "admitted_pairs": admitted,
        "all_available_pairs_descriptive": delta_summary([errors[(c["target_key"], c["season"])] for c in selected]),
        "stations_admitted_pairs": stations, "worst_station_delta_MAE_K": max(changes) if changes else None,
        "within_pilot_uniform_observed_benefit": uniform, "regional_or_population_accuracy_qualified": False,
        "resampling_descriptive_only": None}
    if len(good) == 24:
        blocks = [delta_summary([errors[(c["target_key"], c["season"])] for c in good if c["season"] == w["season"]]) for w in WINDOWS]
        n = np.array([b["B0"]["n"] for b in blocks]); sums = np.array([b["delta_MAE_K"] * b["B0"]["n"] for b in blocks])
        rng = np.random.Generator(np.random.PCG64(20261027)); draw = rng.integers(0, 4, size=(10000, 4))
        deltas = sums[draw].sum(axis=1) / n[draw].sum(axis=1)
        result["resampling_descriptive_only"] = {"lower_K": float(np.quantile(deltas, .025)), "upper_K": float(np.quantile(deltas, .975)),
            "draws": 10000, "PCG64_seed": 20261027, "blocks": 4, "all6_stations_synchronous": True, "population_CI_or_p_value": False}
    return result


def score_predictions(raw, ledger, plan, a, bodies, source_blocks):
    f = load_predictions(raw, plan)
    if control_admission(plan, ledger) != ledger["control_admission"]:
        raise ValueError("V2_SEALED_CONTROL_ADMISSION_CHANGED")
    cases, errors, pairs = [], {}, []
    for case in ledger["cases"]:
        k, season = case["target_key"], case["season"]; w = next(w for w in WINDOWS if w["season"] == season)
        p = f[(f.target_key == k) & (f.season == season)]
        if int((np.isfinite(p.B0_C) & np.isfinite(p.R1_C) & p.R1_predicted).sum()) != case["finite_paired_forecast_hours"]:
            raise ValueError("V2_SEALED_LEDGER_FORECAST_COUNT_MISMATCH")
        clock = pd.DatetimeIndex(p.reference_time_UTC); empty = np.array([], dtype=float)
        e0 = e1 = empty
        result = {"target_key": k, "country": k[:2], "season": season, "requested_hours": 168,
            "forecast_hours": case["finite_paired_forecast_hours"], "paired_hours": 0, "reference_primary_QC_hours": 0,
            "status": "SOURCE_BLOCKED", "source_blocks": dict(case["source_blocks"]),
            "B0_all_reference": metrics([]), "reference_native_QC_counts": {}}
        try:
            name = "control_" + k.replace(":", "_")
            if not ledger["control_admission"][k]["open"] or name not in bodies:
                raise ValueError(source_blocks.get(name, "CONTROL_NOT_OPENED_OR_NOT_RECEIVED"))
            v, q, flags = station_values(bodies[name], k, a["records"][k], clock[0], clock[-1])
            v = v.reindex(clock).to_numpy(); ok = q.reindex(clock).fillna(False).to_numpy(dtype=bool) & np.isfinite(v)
            b0 = p.B0_C.to_numpy(); r1 = p.R1_C.to_numpy()
            common = ok & np.isfinite(b0) & np.isfinite(r1) & p.R1_predicted.to_numpy()
            e0, e1 = b0[common] - v[common], r1[common] - v[common]
            result.update(paired_hours=int(common.sum()), reference_primary_QC_hours=int(ok.sum()),
                status="ADMITTED_PILOT_CASE" if common.sum() >= 160 else "PARTIAL_DESCRIPTIVE_ONLY",
                B0_all_reference=metrics(b0[ok & np.isfinite(b0)] - v[ok & np.isfinite(b0)]),
                reference_native_QC_counts={str(code): int(n) for code, n in flags.reindex(clock).fillna("MISSING_ROW").value_counts(dropna=False).items()})
            for j in np.flatnonzero(common):
                pairs.append({"target_key": k, "country": k[:2], "season": season, "time_UTC": clock[j].isoformat(),
                    "observed_C": float(v[j]), "B0_C": float(b0[j]), "R1_C": float(r1[j])})
        except (ValueError, KeyError, TypeError, zipfile.BadZipFile, UnicodeError) as exc:
            result["source_blocks"]["control"] = type(exc).__name__ + ":" + str(exc)[:240]
        result.update(delta_summary([(e0, e1)])); errors[(k, season)] = (e0, e1); cases.append(result)
    countries = {c: country_summary(c, cases, errors) for c in ("AT", "DE", "CH")}
    return {"schema": "IGE_V2_2019_REGISTERED_PRIMARY_REFERENCE_RESULTS_v1", "cases": cases, "countries": countries,
        "requested_reference_hours": 12096, "paired_reference_hours": sum(c["paired_hours"] for c in cases),
        "all72_cases_retained": True, "AT_estimand": "QC10 published provider product; originality unknown",
        "upstream_QC_assimilation_independence_certified": False, "production_ready": False,
        "automatic_R1_default_promotion": False}, pairs


def score(output, commit):
    plan = registered(); publication_gate(commit, predictions=True)
    bodies, reasons, _, _ = sources(R, CONTROLS, "controls", plan)
    result, pairs = score_predictions((R / PREDICTIONS).read_bytes(), json.loads((R / LEDGER).read_text()), plan, admission(), bodies, reasons)
    output.mkdir(parents=True, exist_ok=False)
    write_exclusive(output / RESULTS, json_bytes(result))
    write_exclusive(output / "v2_weather_paired_temperatures_20261027.csv", pd.DataFrame(pairs).to_csv(index=False, float_format="%.10f", lineterminator="\n").encode())
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--phase", choices=("predict", "score"), required=True)
    p.add_argument("--out", type=Path, required=True); p.add_argument("--published-commit", required=True)
    args = p.parse_args(); (predict if args.phase == "predict" else score)(args.out, args.published_commit)
