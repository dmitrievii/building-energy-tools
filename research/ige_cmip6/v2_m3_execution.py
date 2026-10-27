"""V2-M3 orchestration only. Frozen M2 scientific code is never edited.

Start/source/prediction publication is append-only on the registered research
branch. This runner has no controls acquisition or target scoring command.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from v2_weather_registration import (ROOT, R, BRANCH, REG, INPUTS, CONTROLS, PREDICTIONS,
    LEDGER, SEAL, registered, publication_gate)
from v2_weather_run import sources, load_predictions
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive

REG_COMMIT = "b357b22c1d20bea9c29e3f01bd6a1b629b2a00b8"
M2_HEAD = "791de09dedd25b59aa3be837724b05a84d28e8d5"
CONTRACT = "v2_m3_execution_contract_20261027.json"
START = "v2_m3_acquisition_started_20261027.json"
SOURCE_MANIFEST = "v2_m3_input_manifest_20261027.json"
SOURCE_AUDIT = "v2_m3_input_audit_20261027.json"
SOURCE_ARTIFACT = "v2_m3_input_artifact_20261027.json"
EXECUTION = "v2_m3_precontrol_execution_20261027.json"
REPLAY = "v2_m3_actual_replay_20261027.json"
EXEC_FILES = ["research/ige_cmip6/v2_m3_execution.py",
              "tools/climate_analyzer/tests/test_ige_v2_m3_execution.py",
              ".github/workflows/ige-v2-m3-predictors-seal-20261027.yml"]


def digest(path): return sha256(path.read_bytes()).hexdigest()


def contract():
    c = json.loads((R / CONTRACT).read_text()); plan = registered()
    if c["scientific_registration_commit"] != REG_COMMIT or c["scientific_registration_sha256"] != digest(R / REG):
        raise ValueError("M3_FROZEN_SCIENTIFIC_REGISTRATION_CHANGED")
    if c["execution_sha256"] != {p: digest(ROOT / p) for p in EXEC_FILES}:
        raise ValueError("M3_EXECUTION_NOT_AS_PUBLISHED")
    if c["input_specs_sha256"] != sha256(json_bytes(plan["inputs"])).hexdigest() or c["controls_requested_by_this_stage"] != 0:
        raise ValueError("M3_INVENTORY_CHANGED_OR_CONTROL_PHASE_FORBIDDEN")
    return c, plan


def state(directory):
    if any(directory.glob(CONTROLS + "*")):
        raise ValueError("M3_NEW_CONTROL_BYTES_PRESENT")
    exists = {n: (directory / n).exists() for n in (START, INPUTS + ".storage.json", PREDICTIONS, LEDGER, SEAL)}
    if any(exists.values()) or any(directory.glob(INPUTS + ".part*")):
        raise ValueError("M3_ACQUISITION_ALREADY_CLAIMED_OR_DATA_PRESENT; reuse originals offline, never recapture")
    return "UNSTARTED"


def artifact_manifest(directory):
    files = {p.name: digest(p) for p in sorted(directory.iterdir()) if p.is_file() and p.name != "artifact_member_manifest.json"}
    write_exclusive(directory / "artifact_member_manifest.json", json_bytes(files))
    return files


def new_names_allowed(names):
    exact = {START, SOURCE_MANIFEST, SOURCE_AUDIT, SOURCE_ARTIFACT, EXECUTION, REPLAY,
             PREDICTIONS, LEDGER, SEAL, INPUTS + ".storage.json"}
    for n in names:
        if Path(n).name != n or "\\" in n or not (n in exact or re.fullmatch(re.escape(INPUTS) + r"\.part\d{3}", n)):
            raise ValueError("M3_UNREGISTERED_PUBLICATION_FILE:" + n)


def publish_new(names, message):
    new_names_allowed(names)
    if os.environ.get("GITHUB_REF") != "refs/heads/" + BRANCH:
        raise ValueError("M3_PUBLICATION_RESEARCH_BRANCH_ONLY")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    remote = subprocess.check_output(["git", "ls-remote", "origin", "refs/heads/" + BRANCH], cwd=ROOT, text=True).split()[0]
    if remote != head: raise ValueError("M3_RESEARCH_BRANCH_CHANGED; originals stay in uploaded artifact")
    for n in names:
        if subprocess.run(["git", "cat-file", "-e", head + ":research/ige_cmip6/" + n], cwd=ROOT, capture_output=True).returncode == 0:
            raise ValueError("M3_REFUSE_TO_OVERWRITE_PUBLISHED_EVIDENCE:" + n)
    paths = ["research/ige_cmip6/" + n for n in names]
    subprocess.run(["git", "add", "--", *paths], cwd=ROOT, check=True)
    changed = subprocess.check_output(["git", "diff", "--cached", "--name-status"], cwd=ROOT, text=True).splitlines()
    if set(changed) != {"A\t" + p for p in paths}: raise ValueError("M3_ONLY_NEW_EXPLICIT_FILES_MAY_BE_PUBLISHED")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", message + " [skip ci]"], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "HEAD:refs/heads/" + BRANCH], cwd=ROOT, check=True)
    result = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "ls-remote", "origin", "refs/heads/" + BRANCH], cwd=ROOT, text=True).split()[0] != result:
        raise ValueError("M3_PUBLICATION_REMOTE_VERIFICATION_FAILED")
    return result


def start():
    c, plan = contract(); state(R)
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("M3_AUTOMATIC_REACQUISITION_ON_RERUN_FORBIDDEN")
    gate = publication_gate(REG_COMMIT)
    row = {"schema": "IGE_V2_M3_PREWEATHER_ACQUISITION_CLAIM_v1", "CI_run": int(os.environ["GITHUB_RUN_ID"]),
        "preweather_execution_commit": os.environ["GITHUB_SHA"], "execution_contract_sha256": digest(R / CONTRACT),
        "scientific_registration_gate": gate, "budget": plan["budget"], "new_weather_attempts_at_claim": 0,
        "target_control_requests_authorized": 0, "runner_UTC_clock_untrusted": datetime.now(timezone.utc).isoformat(),
        "repeat_policy": "no second acquisition; recover retained originals or explicitly preregister bounded source recovery"}
    write_exclusive(R / START, json_bytes(row))
    return publish_new([START], "research(V2-M3): claim one predictor acquisition before any weather I/O")


def prepare_inputs(source, output):
    c, plan = contract()
    _, _, m, storage = sources(source, INPUTS, "inputs", plan)
    if m["control_bodies_opened"] or m["cumulative_HTTP_attempts"] > 222 or m["cumulative_body_bytes"] > 1_658_000_000:
        raise ValueError("M3_INPUT_PHASE_OR_RESERVED_CONTROL_BUDGET_CHANGED")
    output.mkdir(parents=True, exist_ok=False)
    names = [INPUTS + ".storage.json", *[p["name"] for p in storage["parts"]]]
    for n in names: write_exclusive(output / n, (source / n).read_bytes())
    write_exclusive(output / SOURCE_MANIFEST, json_bytes(m))
    counts = Counter((r["spec"]["role"], r["status"]) for r in m["sources"])
    audit = {"schema": "IGE_V2_M3_ACTUAL_PREDICTOR_SOURCE_AUDIT_v1", "CI_run": int(os.environ.get("GITHUB_RUN_ID", "0")),
        "registration_sha256": digest(R / REG), "packet_sha256": storage["sha256"], "packet_bytes": storage["bytes"],
        "phase_HTTP_attempts": m["HTTP_attempts_phase"], "phase_body_bytes": m["body_bytes_phase"],
        "roles_status_counts": {role + ":" + status: n for (role, status), n in counts.items()},
        "all_registered_input_assets_retained": len(m["sources"]),
        "source_blocks": [{"id": r["spec"]["id"], "station_key": r["spec"]["station_key"], "reason": r["reason"]}
                          for r in m["sources"] if r["status"] != "ORIGINAL_BODY_RECEIVED"],
        "control_requests": 0, "raw_whole_containers_count_as_exposure": True, "production_ready": False}
    write_exclusive(output / SOURCE_AUDIT, json_bytes(audit)); artifact_manifest(output)
    return audit


def publish_inputs(source):
    contract()
    manifest = json.loads((source / "artifact_member_manifest.json").read_text())
    new_names_allowed(manifest)
    for n, h in manifest.items():
        if digest(source / n) != h: raise ValueError("M3_INPUT_ARTIFACT_MEMBER_CHANGED")
        write_exclusive(R / n, (source / n).read_bytes())
    receipt = {"schema": "IGE_V2_M3_INPUT_ARTIFACT_PUBLICATION_v1", "CI_run": int(os.environ["GITHUB_RUN_ID"]),
        "artifact_id": int(os.environ["SOURCE_ARTIFACT_ID"]), "artifact_sha256_from_CI_upload": os.environ["SOURCE_ARTIFACT_DIGEST"],
        "member_sha256": manifest, "target_controls_opened": False,
        "root_download_verification_required_separately": True}
    write_exclusive(R / SOURCE_ARTIFACT, json_bytes(receipt))
    return publish_new([*manifest, SOURCE_ARTIFACT], "research(V2-M3): preserve original predictor bodies and all source blocks")


def stage_predictions(source):
    contract()
    for n in (PREDICTIONS, LEDGER, SEAL): write_exclusive(R / n, (source / n).read_bytes())


def prepare_final(replay_dir, output):
    c, plan = contract()
    seal = json.loads((R / SEAL).read_text()); ledger = json.loads((R / LEDGER).read_text())
    if seal["control_bodies_opened"] is not False or seal["code_sha256"] != plan["code_sha256"] or any(R.glob(CONTROLS + "*")):
        raise ValueError("M3_NOT_AN_UNMODIFIED_PRECONTROL_SEAL")
    for n, h in seal["frozen_files_sha256"].items():
        if digest(R / n) != h: raise ValueError("M3_CHANGED_SEALED_FILE:" + n)
    verification = json.loads((replay_dir / "v2_weather_verification.json").read_text())
    if verification["status"] != "PASS" or not verification["actual_prediction_replay"]["all72_cases_and12096_rows_replayed"]:
        raise ValueError("M3_ACTUAL_REPLAY_REQUIRED")
    f = load_predictions((R / PREDICTIONS).read_bytes(), plan)
    per_country = {country: {"registered_cases": 24,
        "predicted_R1_hours": sum(x["R1_hours"] for x in ledger["cases"] if x["country"] == country),
        "cases_with_160_paired_forecasts": sum(x["finite_paired_forecast_hours"] >= 160 for x in ledger["cases"] if x["country"] == country),
        "control_targets_source_admitted": sum(v["open"] for k, v in ledger["control_admission"].items() if k.startswith(country))}
        for country in ("AT", "DE", "CH")}
    row = {"schema": "IGE_V2_M3_ACTUAL_PRECONTROL_EXECUTION_v1", "CI_run": int(os.environ.get("GITHUB_RUN_ID", "0")),
        "scientific_registration_commit": REG_COMMIT, "scientific_registration_sha256": digest(R / REG),
        "execution_contract_sha256": digest(R / CONTRACT), "source_publication_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_artifact": json.loads((R / SOURCE_ARTIFACT).read_text()),
        "original_packet_sha256": seal["original_input_packet_sha256"], "actual_seal_sha256": digest(R / SEAL),
        "actual_prediction_rows": len(f), "all72_cases_retained": len(ledger["cases"]) == 72,
        "R1_forecast_hours": int(f.R1_predicted.sum()), "countries": per_country,
        "control_targets_source_admission": ledger["control_admission"], "actual_source_replay": verification["actual_prediction_replay"],
        "scientific_code_QC_operator_objective_or_selection_changed": False,
        "target_observation_or_target_QC_requests": 0, "old_AT_2018_and_IV1_2022_controls_unopened": True,
        "independent_target_accuracy_measured": False, "R1_default_promoted": False, "production_ready": False}
    output.mkdir(parents=True, exist_ok=False)
    for n in (PREDICTIONS, LEDGER, SEAL): write_exclusive(output / n, (R / n).read_bytes())
    write_exclusive(output / REPLAY, (replay_dir / "v2_weather_verification.json").read_bytes())
    write_exclusive(output / EXECUTION, json_bytes(row)); artifact_manifest(output)
    return row


def publish_final(source):
    contract()
    manifest = json.loads((source / "artifact_member_manifest.json").read_text()); new_names_allowed(manifest)
    for n, h in manifest.items():
        if digest(source / n) != h: raise ValueError("M3_PREDICTION_ARTIFACT_MEMBER_CHANGED")
        if n in (PREDICTIONS, LEDGER, SEAL):
            if digest(R / n) != h: raise ValueError("M3_STAGED_PREDICTIONS_CHANGED")
        else: write_exclusive(R / n, (source / n).read_bytes())
    return publish_new(list(manifest), "research(V2-M3): publish actual predictions, weights, NaNs, replay and precontrol seal")


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("phase", choices=("start", "prepare-inputs", "publish-inputs", "stage-predictions", "prepare-final", "publish-final"))
    p.add_argument("--source", type=Path); p.add_argument("--out", type=Path)
    args = p.parse_args()
    if args.phase == "start": result = start()
    elif args.phase == "prepare-inputs": result = prepare_inputs(args.source, args.out)
    elif args.phase == "publish-inputs": result = publish_inputs(args.source)
    elif args.phase == "stage-predictions": result = stage_predictions(args.source)
    elif args.phase == "prepare-final": result = prepare_final(args.source, args.out)
    else: result = publish_final(args.source)
    print(json.dumps(result), flush=True)
