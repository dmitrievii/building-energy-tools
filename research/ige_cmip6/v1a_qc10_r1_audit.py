"""Offline provenance and predictor-only R1 diagnostics, using revealed inputs.

No target observation packet or network client is used. AT QC10 is examined
as a separate exploratory product stratum; frozen V1 still requires QC22.
Diagnostic geometry/leave-one-donor-out scores do not certify target skill.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import subprocess
import zipfile

import numpy as np
import pandas as pd

from a1_prepare import metadata_sources
from v1_acquire import read_packet
from v1_prepare import R, ROOT, ADMISSION, REG, INPUTS, SEAL, WINDOWS
from v1_run import model_temperature, station_values
from v1_time_admission import decode_at
from epw_climate_analyzer.station_admission import admitted_reference
from epw_climate_analyzer.station_reconstruction import (
    T, distance_km, model_reference_operator, reconstruct_temperature)

BASE = "98f1c64905196d9f1215a273812cf269ff68ccb5"
INPUT_SHA = "687ec18f5d22c79478b47275d2cf29a8af9eebcdcdfb360b64b750248584f893"
DOCS = "v1a_document_sources_20261027.zip"
LIVING = {"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md",
          "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"}
QC = {0: ("unchecked_or_suspect", "unknown"),
      10: ("automatic", "unknown"), 11: ("automatic", "changed"),
      12: ("automatic", "original"), 20: ("manual", "unknown"),
      21: ("manual", "changed"), 22: ("manual", "original")}


def native_qc(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("V1A_BOOLEAN_IS_NOT_QC")
    if isinstance(value, str):
        if not value.strip().isdigit():
            raise ValueError("V1A_NONINTEGER_QC")
        value = int(value)
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not float(value).is_integer():
        raise ValueError("V1A_NONINTEGER_QC")
    result = int(value)
    if result not in QC:
        raise ValueError("V1A_UNDOCUMENTED_QC")
    return result


def qc_meaning(value):
    code = native_qc(value)
    return {"native_code": code, "verification": QC[code][0] if code is not None else "undefined",
            "originality": QC[code][1] if code is not None else "unknown",
            "specific_gap_fill_or_edit_identified": False,
            "unchanged_instrument_measurement_certified": code in (12, 22)}


def idw_weights(distances):
    distances = np.asarray(distances, dtype=float)
    if distances.ndim != 1 or not 2 <= len(distances) <= 3 or not np.isfinite(distances).all() or np.any((distances < 5) | (distances > 150)):
        raise ValueError("V1A_FIXED_R1_DISTANCE_DOMAIN")
    weights = distances ** -2
    return weights / weights.sum()


def squared_risk_identity(baseline_errors, corrections):
    """Retrospective identity, not a gate computable without target errors."""
    error, change = np.asarray(baseline_errors, dtype=float), np.asarray(corrections, dtype=float)
    if error.ndim != 1 or error.shape != change.shape or not len(error) or not np.isfinite(error).all() or not np.isfinite(change).all():
        raise ValueError("V1A_FINITE_PAIRED_ERRORS_REQUIRED")
    cross, energy = 2 * np.mean(error * change), np.mean(change ** 2)
    return {"twice_error_correction_cross_moment_K2": float(cross),
            "correction_energy_K2": float(energy), "delta_MSE_K2": float(cross + energy),
            "direct_delta_MSE_K2": float(np.mean((error + change) ** 2) - np.mean(error ** 2)),
            "target_errors_required": True, "MAE_benefit_implied": False}


def reported_geometry_features(target, donors, background):
    """Only reported-height proxies; no datum/terrain transfer certification."""
    ref = admitted_reference(target)
    other = [admitted_reference(d) for d in donors]
    weights = idw_weights([distance_km(ref, d) for d in other])
    lat = math.radians(ref.latitude)
    xy = np.array([[(d.longitude - ref.longitude) * math.cos(lat), d.latitude - ref.latitude] for d in other])
    # Local planar convex hull diagnostic; never used as an accuracy gate.
    if len(other) == 3:
        matrix = np.vstack([xy.T, np.ones(3)])
        if abs(np.linalg.det(matrix)) > 1e-12:
            barycentric = np.linalg.solve(matrix, np.array([0., 0., 1.]))
            inside = bool(np.all(barycentric >= -1e-10))
            horizontal = "inside_donor_triangle" if inside else "outside_donor_triangle"
        else:
            horizontal = "degenerate_donor_geometry"
    else:
        horizontal = "two_donor_segment_not_area_support"
    heights = [float(d["geometry"]["geospatial_z_as_reported_m"]) for d in [target, *donors]]
    proxies = []
    for d, reported_z in zip([target, *donors], heights):
        obj = background[d["station_key"]]
        height = obj.get("elevation")
        if isinstance(height, bool) or not isinstance(height, (float, int)) or not math.isfinite(height):
            raise ValueError("V1A_REPORTED_GRID_ELEVATION_REQUIRED")
        proxies.append(float(height) - reported_z)
    array_hashes = [sha256(json.dumps(background[d["station_key"]]["hourly"]["temperature_2m"],
        separators=(",", ":"), allow_nan=False).encode()).hexdigest() for d in [target, *donors]]
    return {"fixed_nominal_weights": weights.tolist(), "effective_weight_count": float(1 / (weights @ weights)),
        "effective_weight_count_is_independent_sample_size": False,
        "horizontal_geometry_diagnostic": horizontal,
        "reported_target_height_in_donor_range": min(heights[1:]) <= heights[0] <= max(heights[1:]),
        "target_reported_grid_minus_WMDR_or_DWD_z_m": proxies[0],
        "donor_reported_grid_minus_WMDR_or_DWD_z_m": proxies[1:],
        "weighted_proxy_mismatch_relative_target_m": float(weights @ np.array(proxies[1:]) - proxies[0]),
        "all_provider_grid_cell_coordinates": [[background[d["station_key"]]["latitude"], background[d["station_key"]]["longitude"]] for d in [target, *donors]],
        "unique_returned_cells_target_and_donors": len({(background[d["station_key"]]["latitude"], background[d["station_key"]]["longitude"]) for d in [target, *donors]}),
        "temperature_array_sha256_target_and_donors": array_hashes,
        "unique_temperature_arrays_target_and_donors": len(set(array_hashes)),
        "height_proxy_status": "REPORTED_ONLY_DATUM_AND_NATIVE_OROGRAPHY_NOT_VERIFIED",
        "sensor_AGL_added_to_reported_WMDR_z_again": False,
        "terrain_cause_proved": False, "accuracy_admission_implied": False}


def documents():
    raw = (R / DOCS).read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        expected = {n for n, row in manifest["sources"].items() if row["status"] == "ORIGINAL_BODY_RECEIVED"}
        if len(archive.namelist()) != len(expected) + 1 or set(archive.namelist()) != expected | {"manifest.json"}:
            raise ValueError("V1A_DOCUMENT_MEMBER_CENSUS")
        bodies = {n: archive.read(n) for n in expected}
        if any(sha256(body).hexdigest() != manifest["sources"][n]["sha256"] for n, body in bodies.items()):
            raise ValueError("V1A_DOCUMENT_HASH")
    required = {"AT_quality_indicators.pdf", "AT_data_quality.pdf", "AT_hourly_metadata.json", "AT_API_changelog.html", "OpenMeteo_archive_documentation.html"}
    if not required <= set(bodies) or manifest["new_station_measurement_requests"] != 0:
        raise ValueError("V1A_REQUIRED_METADATA_OR_NO_WEATHER_CONTRACT")
    metadata = json.loads(bodies["AT_hourly_metadata.json"])
    parameter = next(p for p in metadata["parameters"] if p["name"] == "tl_flag")
    if parameter["code_list_ref"] != "q21":
        raise ValueError("V1A_TL_FLAG_CODE_LIST")
    return bodies, manifest, {"packet_sha256": sha256(raw).hexdigest(), "packet_bytes": len(raw)}


def protected_files():
    changes = subprocess.check_output(["git", "diff", "--name-status", BASE], cwd=ROOT, text=True).splitlines()
    for line in changes:
        status, name = line.split("\t", 1)
        if status != "A" and name not in LIVING:
            raise ValueError("V1A_EXISTING_RESULT_OR_CODE_CHANGED:" + name)
    seal = json.loads((R / SEAL).read_text())
    for name, digest in seal["frozen_files_sha256"].items():
        if sha256((R / name).read_bytes()).hexdigest() != digest:
            raise ValueError("V1A_V1_SEAL_CHANGED:" + name)
    return {"parent": BASE, "V1_sealed_inputs_predictions_QC_gate_unchanged": True,
            "existing_files_modified_except_living_roadmaps": False}


def audit():
    guard = protected_files()
    doc, doc_manifest, doc_info = documents()
    old, _, _ = metadata_sources()
    old_meta = json.loads(old["AT_hourly_v2_metadata.json"])
    new_meta = json.loads(doc["AT_hourly_metadata.json"])
    if old_meta["code_lists"]["q21"] != new_meta["code_lists"]["q21"]:
        raise ValueError("V1A_Q21_CHANGED_REQUIRES_SEPARATE_REVIEW")
    bodies, manifest, storage = read_packet(R, INPUTS, phase="inputs")
    if storage["sha256"] != INPUT_SHA or any(row["role"] == "control" for row in manifest["sources"]):
        raise ValueError("V1A_FROZEN_PREDICTOR_ONLY_PACKET_REQUIRED")
    admission = json.loads((R / ADMISSION).read_text())
    rows, station = [], {}
    for source in manifest["sources"]:
        if source["kind"] != "station_temperature" or not source["station_key"].startswith("AT:"):
            continue
        raw = bodies[source["member"]]; obj = json.loads(raw); key = source["station_key"]
        if source["role"] != "donor" or len(obj["features"]) != 1:
            raise ValueError("V1A_AT_DONOR_ONLY")
        feature = obj["features"][0]
        if str(feature["properties"]["station"]) != key.split(":")[1]:
            raise ValueError("V1A_NATIVE_STATION_IDENTITY")
        params = feature["properties"]["parameters"]
        flags = [native_qc(q) for q in params["tl_flag"]["data"]]
        values = params["tl"]["data"]
        clock = pd.to_datetime(obj["timestamps"], utc=True)
        if not clock.equals(pd.date_range("2018-01-07T00:00Z", "2018-10-16T23:00Z", freq="h")) or len(flags) != len(values) or len(values) != len(clock):
            raise ValueError("V1A_ORIGINAL_AT_AXIS")
        decoded = decode_at(raw, admitted_reference(admission["records"][key]))
        decoded_flags = decoded.data["quality_flag__" + T].tolist()
        if decoded_flags != [str(q) for q in flags]:
            raise ValueError("V1A_DECODER_CHANGED_NATIVE_QC")
        expected_values = np.asarray(values, dtype=float)
        if not np.array_equal(expected_values, decoded.data[T].to_numpy(dtype=float), equal_nan=True) or decoded.source_sha256 != sha256(raw).hexdigest():
            raise ValueError("V1A_DECODER_CHANGED_SOURCE_VALUES_OR_SHA")
        rows.append({"station_key": key, "source_URL": source["url"], "original_body_sha256": source["sha256"],
            "bytes": len(raw), "rows": len(clock), "native_QC_counts": dict(Counter(str(q) for q in flags)),
            "JSON_native_flag_types": dict(Counter(type(q).__name__ for q in params["tl_flag"]["data"])),
            "finite_T_rows": int(np.isfinite(expected_values).sum()),
            "native_QC_preserved_after_decoder": True, "T_values_and_original_SHA_preserved": True,
            "V1_primary_QC22_accepted_hours": int(decoded.data["quality_accepted__" + T].sum()),
            "specific_processing_history_known": False})
        station[key] = decoded
    if {r["station_key"] for r in rows} != {"AT:20105", "AT:20220", "AT:20270", "AT:3702", "AT:3805", "AT:5625"}:
        raise ValueError("V1A_AT_SIX_DONOR_CENSUS")
    registration = json.loads((R / REG).read_text())
    model, bg_objects = {}, {}
    for spec in registration["inputs"]:
        if spec["kind"] == "model_background":
            model[spec["station_key"]], _ = model_temperature(bodies[spec["member"]], spec)
            bg_objects[spec["station_key"]] = json.loads(bodies[spec["member"]])
    groups = []
    for group in admission["groups"]:
        key, donor_keys = group["target_key"], group["donors"]
        target = admission["records"][key]; donors = [admission["records"][d] for d in donor_keys]
        geometry = reported_geometry_features(target, donors, bg_objects)
        # No target observation argument exists in this stage.
        observed, quality, backgrounds = {}, {}, {}
        for d in donor_keys:
            record = admission["records"][d]
            source = next(s for s in manifest["sources"] if s["station_key"] == d and s["role"] == "donor")
            observed[d], quality[d] = station_values(bodies[source["member"]], d, record,
                pd.Timestamp("2018-01-07", tz="UTC"), pd.Timestamp("2018-10-16T23:00Z"))
            if key.startswith("AT:"):
                # Explicit new exploratory mask; never assigned to old batches or V1.
                quality[d] = (station[d].data["quality_flag__" + T] == "10") & observed[d].notna()
        loo = []
        for window in WINDOWS:
            clock = pd.date_range(window["start_UTC"], window["end_UTC"], freq="h")
            for d in donor_keys:
                backgrounds[d] = model_reference_operator(model[d], clock, target["time_contract"]["operator"])
            if len(donor_keys) < 3:
                loo.append({"season": window["season"], "status": "NOT_ESTIMABLE_WITH_TWO_DONORS_WITHOUT_CHANGING_R1"})
                continue
            for held in donor_keys:
                others = [d for d in donor_keys if d != held]
                try:
                    pred, _ = reconstruct_temperature(admitted_reference(admission["records"][held]), backgrounds[held],
                        [admitted_reference(admission["records"][d]) for d in others], observed, backgrounds, quality)
                    truth = observed[held].reindex(clock).to_numpy(dtype=float)
                    e0 = backgrounds[held].to_numpy(dtype=float) - truth
                    e1 = pred.to_numpy(dtype=float) - truth
                    mask = quality[held].reindex(clock).fillna(False).to_numpy(dtype=bool) & np.isfinite(e0) & np.isfinite(e1)
                    row = {"season": window["season"], "pseudo_target_donor": held, "paired_hours": int(mask.sum()),
                        "status": "EXPLORATORY_REVEALED_DONOR_LOO", "minimum_pairs_for_case": 160,
                        "case_coverage_admitted": bool(mask.sum() >= 160),
                        "B0_MAE_K": float(np.abs(e0[mask]).mean()) if mask.any() else None,
                        "R1_MAE_K": float(np.abs(e1[mask]).mean()) if mask.any() else None}
                    row["delta_MAE_K"] = row["R1_MAE_K"] - row["B0_MAE_K"] if mask.any() else None
                    loo.append(row)
                except ValueError as error:
                    loo.append({"season": window["season"], "pseudo_target_donor": held, "status": "SOURCE_GEOMETRY_BLOCKED", "reason": str(error)})
        groups.append({"target_key": key, "donors": donor_keys, "geometry": geometry,
            "donor_LOO_diagnostics": loo,
            "AT_mask_if_used": "QC10_ONLY_EXPLORATORY_PROVIDER_PRODUCT_NOT_V1_QC22" if key.startswith("AT:") else None,
            "target_T_read": False, "transferability_or_target_skill_certified": False})
    return {"schema": "IGE_V1A_AT_QC10_PROVENANCE_AND_R1_DIAGNOSTICS_v1", "date": "2026-10-27",
        "protection": guard, "documentation": {**doc_info, "manifest": doc_manifest},
        "frozen_input_packet_sha256": storage["sha256"],
        "old_and_new_official_q21_equal": True, "tl_flag_code_list_ref": "q21",
        "QC10_meaning": qc_meaning(10), "AT_donor_originals": rows, "groups": groups,
        "AT_control_T_opened": False, "new_station_measurement_or_model_HTTP_requests": 0,
        "new_control_packet_read": False, "2018_status": "REVEALED_DIAGNOSTICS_NOT_NEW_HOLDOUT",
        "QC10_specific_edit_fill_fraction_identified": False,
        "R1_universal_accuracy_qualified": False, "R1_default_promotion_allowed": False,
        "physical_full_weather_qualified": False, "production_ready": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--out", type=Path, required=True)
    destination = parser.parse_args().out
    result = audit()
    with destination.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({"AT_donors": len(result["AT_donor_originals"]), "AT_rows": sum(r["rows"] for r in result["AT_donor_originals"]),
        "QC10_native": True, "AT_controls_opened": False, "production_ready": False}), flush=True)
