"""Replay original metadata admission without HTTP and protect old science."""
from __future__ import annotations
import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import subprocess
import time
import unittest
import zipfile

from v2_cohort import BASE, ROOT, R, catalogs, discovery, json_bytes
from v2_metadata import (FRAME, ADMISSION, PACKET, PART_SIZE, metadata_url, validate_body,
    metadata_record, choose_targets, donor_candidates, COUNTRIES)
from epw_climate_analyzer.station_admission import admitted_reference
from epw_climate_analyzer.station_reconstruction import distance_km

LIVING = {"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md", "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"}


def protection():
    for line in subprocess.check_output(["git", "diff", "--name-status", BASE], cwd=ROOT, text=True).splitlines():
        status, path = line.split("\t", 1)
        if status != "A" and path not in LIVING:
            raise ValueError("V2_OLD_SCIENTIFIC_RESULT_CODE_OR_DESIGN_CHANGED:" + path)
    return {"parent_commit": BASE, "existing_scientific_files_unchanged": True, "new_weather_requests": 0}


def read_metadata_packet(directory):
    storage = json.loads((directory / (PACKET + ".storage.json")).read_text()); parts = []
    if storage["schema"] != "IGE_V2_METADATA_PACKET_PARTS_v1" or storage["packet_name"] != PACKET or not 1 <= len(storage["parts"]) <= 12:
        raise ValueError("V2_METADATA_STORAGE_SCHEMA")
    for i, row in enumerate(storage["parts"], 1):
        if row["name"] != PACKET + f".part{i:03d}" or not 0 < row["bytes"] <= PART_SIZE:
            raise ValueError("V2_METADATA_PART_CENSUS")
        raw = (directory / row["name"]).read_bytes()
        if len(raw) != row["bytes"] or sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("V2_METADATA_PART_HASH")
        parts.append(raw)
    raw = b"".join(parts)
    if len(raw) != storage["bytes"] or sha256(raw).hexdigest() != storage["sha256"]:
        raise ValueError("V2_METADATA_PACKET_HASH")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if len(archive.namelist()) != len(manifest["member_sha256"]) + 1 or set(archive.namelist()) != set(manifest["member_sha256"]) | {"manifest.json"}:
            raise ValueError("V2_METADATA_MEMBER_CENSUS")
        bodies = {n: archive.read(n) for n in manifest["member_sha256"]}
    if any(sha256(b).hexdigest() != manifest["member_sha256"][n] for n, b in bodies.items()):
        raise ValueError("V2_METADATA_MEMBER_HASH")
    if manifest["new_observation_or_model_requests"] != 0:
        raise ValueError("V2_METADATA_WEATHER_LEAKAGE")
    if not 0 <= manifest["new_HTTP_attempts"] <= 240 or sum(r["HTTP_attempts"] for r in manifest["sources"]) != manifest["new_HTTP_attempts"]:
        raise ValueError("V2_METADATA_ATTEMPT_BUDGET_OR_CENSUS")
    if sum(r["body_bytes_read"] for r in manifest["sources"]) != manifest["new_body_bytes"] or manifest["new_body_bytes"] > 50_000_001:
        raise ValueError("V2_METADATA_READ_BYTE_CENSUS")
    for row in manifest["sources"]:
        if not metadata_url(row["url"]): raise ValueError("V2_SOURCE_URL_NOT_METADATA")
        if row["status"] == "ORIGINAL_METADATA_RECEIVED":
            body = bodies[row["member"]]
            if sha256(body).hexdigest() != row["sha256"] or len(body) != row["bytes"]:
                raise ValueError("V2_SOURCE_BODY_RECEIPT_HASH")
            validate_body(row["url"], body)
    return bodies, manifest, storage


class ReplayCollector:
    def __init__(self, bodies, manifest):
        self.bodies = bodies; self.rows = {r["url"]: r for r in manifest["sources"]}
    def get(self, url):
        if url not in self.rows: raise ValueError("V2_METADATA_REPLAY_UNREGISTERED_URL")
        row = self.rows[url]
        if row["status"] != "ORIGINAL_METADATA_RECEIVED":
            raise ValueError("V2_METADATA_SOURCE_BLOCK:" + row["reason"])
        return self.bodies[row["member"]]


def replay(directory):
    bodies, manifest, storage = read_metadata_packet(directory)
    saved = json.loads((directory / ADMISSION).read_text())
    pool, _, _ = catalogs(); by_key = {s.key: s for s in pool}; collector = ReplayCollector(bodies, manifest)
    records = {k: metadata_record(by_key[k], collector) for k in saved["records"]}
    if records != saved["records"]: raise ValueError("V2_DATED_GEOMETRY_OR_ADMISSION_REPLAY")
    frame = json.loads((R / FRAME).read_text()); subset = [by_key[r["country"] + ":" + r["station_id"]] for r in frame["metadata_candidates"]]
    selected, strata, blocks = choose_targets(subset, records)
    if [s.key for s in selected] != saved["metadata_target_keys"] or strata != saved["height_rank_strata"]:
        raise ValueError("V2_TARGET_RANK_OR_SELECTION_REPLAY")
    groups = []
    for target in selected:
        candidates = donor_candidates(target, pool, selected); good = []
        for distance, donor in candidates:
            if donor.key not in records: raise ValueError("V2_DONOR_METADATA_CENSUS")
            if records[donor.key]["temperature_source_eligible"]:
                d = distance_km(admitted_reference(records[target.key]), admitted_reference(records[donor.key]))
                if 5 <= d <= 150: good.append(donor.key)
        chosen = good[:3]; ready = len(chosen) >= 2
        if not ready: blocks.append(target.key + ":FEWER_THAN_TWO_FIXED_METADATA_ADMITTED_DONORS")
        groups.append({"target_key": target.key, "target_name": target.name, "donors": chosen,
            "candidate_order": [s.key for _, s in candidates], "metadata_ready": ready})
    if groups != saved["groups"] or blocks != saved["source_blocks"] or saved["metadata_packet_sha256"] != storage["sha256"]:
        raise ValueError("V2_DONOR_SELECTION_OR_SOURCE_REPLAY")
    if any(saved[k] is not False for k in ("weather_acquisition_allowed", "actual_prediction_seal_published", "independent_accuracy_qualified", "production_ready")):
        raise ValueError("V2_METADATA_IS_NOT_ACCURACY_OR_UNBLINDING")
    return {"status": saved["status"], "metadata_targets": len(selected), "metadata_ready_cases": saved["metadata_ready_cases"],
        "source_blocks": blocks, "metadata_packet_sha256": storage["sha256"], "all_original_metadata_and_decisions_replayed": True,
        "new_metadata_attempts": manifest["new_HTTP_attempts"], "new_model_or_observation_requests": 0, "production_ready": False}


def verify(output, metadata_directory=None):
    output.mkdir(parents=True, exist_ok=False); start = time.monotonic(); guard = protection()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tools/climate_analyzer/tests"), pattern="test_ige_v2_metadata.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful(): raise RuntimeError("V2_METADATA_TEST_FAILURE")
    frame, exposure = discovery()
    if (R / FRAME).read_bytes() != json_bytes(frame) or (R / "v2_exposure_audit_20261027.json").read_bytes() != json_bytes(exposure):
        raise ValueError("V2_PREWEATHER_FRAME_OR_EXPOSURE_REPLAY")
    actual = replay(metadata_directory) if metadata_directory is not None else None
    receipt = {"schema": "IGE_V2_METADATA_ONLY_VERIFICATION_v1", "status": "PASS", "tests": result.testsRun,
        "protection": guard, "actual_metadata_source_replay": actual,
        "new_weather_or_target_QC_requests": 0, "new_hourly_validation_executed": False,
        "independent_accuracy_qualified": False, "production_ready": False, "wall_seconds": time.monotonic() - start}
    (output / "v2_metadata_verification.json").write_bytes(json_bytes(receipt)); print(json.dumps(receipt), flush=True)
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--out", type=Path, required=True); p.add_argument("--metadata-directory", type=Path)
    args = p.parse_args(); verify(args.out, args.metadata_directory)
