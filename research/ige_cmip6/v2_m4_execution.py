"""One registered control acquisition, original publication, frozen scoring.

No new predictor data, no estimator/QC/selection edits, no default promotion.
The score filenames retain the frozen 20261027 registration date.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
from unittest.mock import patch

import numpy as np
import pandas as pd

from v2_weather_registration import (ROOT, R, BRANCH, REG, INPUTS, CONTROLS, PREDICTIONS,
    LEDGER, SEAL, RESULTS, registered, admission, publication_gate)
from v2_weather_run import sources, score_predictions
from v2_weather_io import control_admission
from v2_m4_score_audit import audit_scores, paired_frame
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive

SEAL_COMMIT = "45dda3789542191346dba7d8a579fdd74c560894"
M3_HEAD = "e1a8a47f46a8cca51e936abb5f90429ffce04229"
CONTRACT = "v2_m4_execution_contract_20261028.json"
START = "v2_m4_control_acquisition_started_20261028.json"
SOURCE_MANIFEST = "v2_m4_control_manifest_20261028.json"
SOURCE_AUDIT = "v2_m4_control_source_audit_20261028.json"
SOURCE_ARTIFACT = "v2_m4_control_artifact_20261028.json"
PAIRS = "v2_weather_paired_temperatures_20261027.csv"
REPLAY = "v2_m4_actual_score_replay_20261028.json"
ARITHMETIC = "v2_m4_paired_arithmetic_audit_20261028.json"
EXECUTION = "v2_m4_actual_validation_20261028.json"
EXEC_FILES = ["research/ige_cmip6/v2_m4_execution.py", "research/ige_cmip6/v2_m4_score_audit.py",
              "tools/climate_analyzer/tests/test_ige_v2_m4.py", ".github/workflows/ige-v2-m4-controls-scores-20261028.yml"]


def digest(path): return sha256(path.read_bytes()).hexdigest()


def contract():
    c = json.loads((R / CONTRACT).read_text()); plan = registered()
    living = {"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md", "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"}
    for line in subprocess.check_output(["git", "diff", "--name-status", M3_HEAD], cwd=ROOT, text=True).splitlines():
        status, name = line.split("\t", 1)
        if status != "A" and name not in living: raise ValueError("M4_PRIOR_SCIENTIFIC_CODE_DATA_OR_RESULT_CHANGED:" + name)
    if c["execution_sha256"] != {n: digest(ROOT / n) for n in EXEC_FILES}: raise ValueError("M4_EXECUTION_CHANGED")
    if c["scientific_registration_sha256"] != digest(R / REG) or c["actual_prediction_seal_sha256"] != digest(R / SEAL):
        raise ValueError("M4_CHANGED_REGISTRATION_OR_ACTUAL_SEAL")
    if c["control_specs_sha256"] != sha256(json_bytes(plan["controls"])).hexdigest(): raise ValueError("M4_CHANGED_CONTROL_INVENTORY")
    if c["predecessor_manifest_sha256"] != digest(R / "v2_m3_input_manifest_20261027.json"):
        raise ValueError("M4_PRIOR_SOURCE_BUDGET_MANIFEST_CHANGED")
    ledger = json.loads((R / LEDGER).read_text()); gate = control_admission(plan, ledger)
    if c["sealed_source_admission"] != gate or gate != ledger["control_admission"]: raise ValueError("M4_CHANGED_SEALED_SOURCE_ADMISSION")
    if c["new_predictor_or_metadata_requests"] != 0: raise ValueError("M4_NEW_PREDICTORS_FORBIDDEN")
    return c, plan


def unstarted(directory):
    if any((directory / n).exists() for n in (START, CONTROLS + ".storage.json", RESULTS, PAIRS)) or any(directory.glob(CONTROLS + ".part*")):
        raise ValueError("M4_CONTROL_ACQUISITION_ALREADY_CLAIMED; recover saved bytes, no recapture")
    return True


def allowed_names(names):
    exact = {START, SOURCE_MANIFEST, SOURCE_AUDIT, SOURCE_ARTIFACT, RESULTS, PAIRS, REPLAY, ARITHMETIC, EXECUTION, CONTROLS + ".storage.json"}
    for n in names:
        if Path(n).name != n or "\\" in n or not (n in exact or re.fullmatch(re.escape(CONTROLS) + r"\.part\d{3}", n)):
            raise ValueError("M4_UNREGISTERED_PUBLICATION_NAME:" + n)


def artifact_manifest(output):
    m = {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file() and p.name != "artifact_member_manifest.json"}
    write_exclusive(output / "artifact_member_manifest.json", json_bytes(m)); return m


def publish_new(names, message):
    allowed_names(names)
    if os.environ.get("GITHUB_REF") != "refs/heads/" + BRANCH: raise ValueError("M4_RESEARCH_BRANCH_ONLY")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "ls-remote", "origin", "refs/heads/" + BRANCH], cwd=ROOT, text=True).split()[0] != head:
        raise ValueError("M4_BRANCH_CHANGED; preserve uploaded original artifact")
    for n in names:
        if subprocess.run(["git", "cat-file", "-e", head + ":research/ige_cmip6/" + n], cwd=ROOT, capture_output=True).returncode == 0:
            raise ValueError("M4_REFUSE_TO_OVERWRITE_EVIDENCE:" + n)
    paths = ["research/ige_cmip6/" + n for n in names]
    subprocess.run(["git", "add", "--", *paths], cwd=ROOT, check=True)
    changed = subprocess.check_output(["git", "diff", "--cached", "--name-status"], cwd=ROOT, text=True).splitlines()
    if set(changed) != {"A\t" + p for p in paths}: raise ValueError("M4_ONLY_EXPLICIT_NEW_EVIDENCE_ALLOWED")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", message + " [skip ci]"], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "HEAD:refs/heads/" + BRANCH], cwd=ROOT, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def start():
    c, plan = contract(); unstarted(R)
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1": raise ValueError("M4_NO_AUTOMATIC_CONTROL_REACQUISITION")
    gate = publication_gate(SEAL_COMMIT, predictions=True)
    row = {"schema": "IGE_V2_M4_PRECONTROL_ACQUISITION_CLAIM_v1", "CI_run": int(os.environ["GITHUB_RUN_ID"]),
        "precontrol_execution_commit": os.environ["GITHUB_SHA"], "execution_contract_sha256": digest(R / CONTRACT),
        "published_actual_prediction_gate": gate, "source_admission": c["sealed_source_admission"],
        "prior_HTTP_attempts": 129, "prior_body_bytes": 261328943, "new_control_attempts_at_claim": 0,
        "runner_UTC_untrusted": datetime.now(timezone.utc).isoformat(),
        "raw_whole_containers_become_revealed_including_unscored_years_and_fields": True}
    write_exclusive(R / START, json_bytes(row))
    return publish_new([START], "research(V2-M4): claim fixed control acquisition after published actual forecast seal")


def prepare_controls(source, output):
    c, plan = contract(); _, _, m, storage = sources(source, CONTROLS, "controls", plan)
    prior = json.loads((R / "v2_m3_input_manifest_20261027.json").read_text())
    if (m["cumulative_HTTP_attempts"] != prior["cumulative_HTTP_attempts"] + m["HTTP_attempts_phase"] or
            m["cumulative_body_bytes"] != prior["cumulative_body_bytes"] + m["body_bytes_phase"]):
        raise ValueError("M4_PRIOR_PLUS_CONTROL_BUDGET_CENSUS")
    output.mkdir(parents=True, exist_ok=False)
    for n in [CONTROLS + ".storage.json", *[p["name"] for p in storage["parts"]]]: write_exclusive(output / n, (source / n).read_bytes())
    write_exclusive(output / SOURCE_MANIFEST, json_bytes(m))
    counts = Counter(r["status"] for r in m["sources"])
    audit = {"schema": "IGE_V2_M4_ACTUAL_ORIGINAL_CONTROL_AUDIT_v1", "CI_run": int(os.environ.get("GITHUB_RUN_ID", "0")),
        "packet_sha256": storage["sha256"], "packet_bytes": storage["bytes"], "registered_control_assets": len(m["sources"]),
        "status_counts": dict(counts), "control_HTTP_attempts": m["HTTP_attempts_phase"], "control_body_bytes": m["body_bytes_phase"],
        "cumulative_weather_HTTP_attempts": m["cumulative_HTTP_attempts"], "cumulative_weather_body_bytes": m["cumulative_body_bytes"],
        "source_blocks": [{"id": r["spec"]["id"], "reason": r["reason"]} for r in m["sources"] if r["status"] != "ORIGINAL_BODY_RECEIVED"],
        "all_received_target_raw_containers_are_now_revealed": True, "scoring_QC_and_method_unchanged": True,
        "new_predictor_or_metadata_requests": 0, "old_AT_2018_and_IV1_2022_controls_opened": False}
    write_exclusive(output / SOURCE_AUDIT, json_bytes(audit)); artifact_manifest(output); return audit


def publish_controls(source):
    contract(); m = json.loads((source / "artifact_member_manifest.json").read_text()); allowed_names(m)
    for n, h in m.items():
        if digest(source / n) != h: raise ValueError("M4_CONTROL_ARTIFACT_MEMBER_CHANGED")
        write_exclusive(R / n, (source / n).read_bytes())
    receipt = {"schema": "IGE_V2_M4_ORIGINAL_CONTROL_ARTIFACT_v1", "CI_run": int(os.environ["GITHUB_RUN_ID"]),
        "artifact_id": int(os.environ["CONTROL_ARTIFACT_ID"]), "artifact_sha256_from_CI_upload": os.environ["CONTROL_ARTIFACT_DIGEST"],
        "member_sha256": m, "target_raw_bytes_are_revealed": True, "root_actual_download_verification_required_separately": True}
    write_exclusive(R / SOURCE_ARTIFACT, json_bytes(receipt))
    return publish_new([*m, SOURCE_ARTIFACT], "research(V2-M4): preserve all original control bytes before frozen scoring")


def same_score_json(live, saved):
    if isinstance(live, dict): return isinstance(saved, dict) and set(live) == set(saved) and all(same_score_json(v, saved[k]) for k, v in live.items())
    if isinstance(live, list): return isinstance(saved, list) and len(live) == len(saved) and all(same_score_json(a, b) for a, b in zip(live, saved))
    if isinstance(live, float): return isinstance(saved, float) and math.isclose(live, saved, rel_tol=0, abs_tol=1.1e-8)
    return type(live) is type(saved) and live == saved


def replay_scores(result_source, output):
    c, plan = contract(); publication_gate(SEAL_COMMIT, predictions=True)
    with patch.object(socket.socket, "connect", side_effect=AssertionError("M4_OFFLINE_SCORE_REPLAY_NETWORK_CALL")):
        bodies, reasons, _, _ = sources(R, CONTROLS, "controls", plan)
        ledger = json.loads((R / LEDGER).read_text())
        result, pairs = score_predictions((R / PREDICTIONS).read_bytes(), ledger, plan, admission(), bodies, reasons)
        saved = json.loads((result_source / RESULTS).read_text())
        if not same_score_json(result, saved): raise ValueError("M4_ACTUAL_SCORE_REPLAY_MISMATCH")
        raw = pd.DataFrame(pairs).to_csv(index=False, float_format="%.10f", lineterminator="\n").encode()
        live, old = paired_frame(raw), paired_frame((result_source / PAIRS).read_bytes())
        if list(live.columns) != list(old.columns) or live.shape != old.shape: raise ValueError("M4_PAIRED_REPLAY_CENSUS")
        for name in live:
            if pd.api.types.is_numeric_dtype(live[name]):
                if not np.allclose(live[name], old[name], rtol=0, atol=1.1e-10, equal_nan=True): raise ValueError("M4_PAIRED_NUMERIC_REPLAY_MISMATCH")
            elif not live[name].equals(old[name]): raise ValueError("M4_PAIRED_CATEGORY_REPLAY_MISMATCH")
        arithmetic_audit = audit_scores(saved, (result_source / PAIRS).read_bytes(), plan, ledger)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "IGE_V2_M4_FROZEN_SOURCE_SCORE_REPLAY_v1", "status": "PASS", "paired_hours": len(old),
        "all72_cases_replayed": len(result["cases"]) == 72, "new_weather_requests": 0,
        "same_frozen_algorithm_reinvoked_not_an_independent_estimator": True,
        "score_JSON_absolute_tolerance": 1.1e-8, "paired_CSV_absolute_tolerance": 1.1e-10,
        "independent_paired_arithmetic_aggregation_audit": arithmetic_audit, "production_ready": False}
    write_exclusive(output / REPLAY, json_bytes(receipt)); write_exclusive(output / ARITHMETIC, json_bytes(arithmetic_audit)); return receipt


def prepare_final(score_source, replay_dir, output):
    c, plan = contract(); publication_gate(SEAL_COMMIT, predictions=True)
    replay = json.loads((replay_dir / REPLAY).read_text())
    if replay["status"] != "PASS" or not replay["all72_cases_replayed"]: raise ValueError("M4_COMPLETE_ACTUAL_SCORE_REPLAY_REQUIRED")
    result = json.loads((score_source / RESULTS).read_text()); output.mkdir(parents=True, exist_ok=False)
    for n in (RESULTS, PAIRS): write_exclusive(output / n, (score_source / n).read_bytes())
    for n in (REPLAY, ARITHMETIC): write_exclusive(output / n, (replay_dir / n).read_bytes())
    receipt = {"schema": "IGE_V2_M4_ACTUAL_REGISTERED_HOLDOUT_EXECUTION_v1", "CI_run": int(os.environ.get("GITHUB_RUN_ID", "0")),
        "actual_prediction_seal_commit": SEAL_COMMIT, "actual_prediction_seal_sha256": digest(R / SEAL),
        "execution_contract_sha256": digest(R / CONTRACT), "original_control_publication_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "control_artifact": json.loads((R / SOURCE_ARTIFACT).read_text()), "paired_hours": result["paired_reference_hours"],
        "all72_cases_retained": result["all72_cases_retained"], "countries": result["countries"],
        "target_errors_are_now_revealed_and_cannot_be_relabelled_as_fresh": True,
        "station_year_or_QC_replacement": False, "scientific_code_QC_operators_estimator_objective_criteria_changed": False,
        "provider_spatial_QC_ERA5_assimilation_independence_certified": False,
        "original_sensor_accuracy_from_AT_QC10_qualified": False, "global_or_regional_accuracy_qualified": False,
        "R1_default_promoted": False, "production_ready": False}
    write_exclusive(output / EXECUTION, json_bytes(receipt)); artifact_manifest(output); return receipt


def publish_final(source):
    contract(); m = json.loads((source / "artifact_member_manifest.json").read_text()); allowed_names(m)
    for n, h in m.items():
        if digest(source / n) != h: raise ValueError("M4_RESULT_ARTIFACT_MEMBER_CHANGED")
        write_exclusive(R / n, (source / n).read_bytes())
    return publish_new(list(m), "research(V2-M4): preserve frozen target error scores, all blocks and actual replay")


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("phase", choices=("start", "prepare-controls", "publish-controls", "replay", "prepare-final", "publish-final"))
    p.add_argument("--source", type=Path); p.add_argument("--out", type=Path); p.add_argument("--replay-dir", type=Path)
    a = p.parse_args()
    if a.phase == "start": result = start()
    elif a.phase == "prepare-controls": result = prepare_controls(a.source, a.out)
    elif a.phase == "publish-controls": result = publish_controls(a.source)
    elif a.phase == "replay": result = replay_scores(a.source, a.out)
    elif a.phase == "prepare-final": result = prepare_final(a.source, a.replay_dir, a.out)
    else: result = publish_final(a.source)
    print(json.dumps(result), flush=True)
