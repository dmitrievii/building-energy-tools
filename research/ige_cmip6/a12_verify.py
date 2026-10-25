"""A1.2 offline source preflight plus the 210 existing core/UI/A1 checks."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools/climate_analyzer"))
from a12_prepare_history import prepare, PROTOCOL_SHA, PACKET, PACKET_SHA
from a12_exposure_audit import audit
from a1_prepare import prepare as old_prepare
from u1_verify import PATTERNS
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
from epw_climate_analyzer.engine_application import run_historical_product, run_future_pilot_product, pilot_historical_request

BASE = "ae6f4ae406fd1adf72eaf4da23d898e1d54059ff"
CORE_FILES = {"tools/climate_analyzer/epw_climate_analyzer/station_admission.py", "tools/climate_analyzer/tests/test_ige_a12_history.py"}
IMPLEMENTATION = CORE_FILES | {"research/ige_cmip6/"+n for n in (
    "a12_acquire_history.py", "a12_metadata_zip.py", "a12_prepare_history.py", "a12_exposure_audit.py", "a12_verify.py")}
ROADMAPS = {"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md", "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"}


def protection():
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT, check=True)
    # Every already-tracked file stays unchanged, except the two living roadmap
    # files. New A1.2 code/results cannot overwrite a previous experiment.
    changes = subprocess.check_output(["git", "diff", "--name-status", BASE], cwd=ROOT, text=True).splitlines()
    for line in changes:
        status, name = line.split("\t", 1)
        if status != "A" and name not in ROADMAPS: raise ValueError("A12_OLD_TRACKED_FILE_CHANGED:"+name)
    app_changes = subprocess.check_output(["git", "diff", "--name-only", BASE, "--", "tools/climate_analyzer"], cwd=ROOT, text=True).splitlines()
    if not set(app_changes) <= CORE_FILES: raise ValueError("A12_EXISTING_CORE_UI_OR_TEST_CHANGED")
    contract = json.loads((ROOT/"research/ige_cmip6/p9_3b3_iv1_integration_contract.json").read_text())
    for name, expected in contract["protected_sha256"].items():
        if sha256((ROOT/name).read_bytes()).hexdigest() != expected: raise ValueError("A12_PROTECTED_RESEARCH_CHANGED:"+name)
    protocol, admission = old_prepare()
    for filename, value in (("a1_1_protocol_20261025.json", protocol), ("a1_1_admission_20261025.json", admission)):
        if (ROOT/"research/ige_cmip6"/filename).read_bytes() != json_bytes(value): raise ValueError("A12_A1_1_REPLAY_CHANGED")
    return {"base": BASE, "protected_research_files_unchanged": len(contract["protected_sha256"]),
        "A1_1_protocol_and_metadata_replay_byte_unchanged": True, "existing_core_UI_and_defaults_byte_unchanged": True,
        "IV1_observations_opened": False}


def prediction_plan(admission, exposure):
    ready = [c for c in admission["cases"] if c["strict_T2m_metadata_ready"]]
    targets = sorted({c["target_key"] for c in ready})
    donors = sorted({s for c in ready for s in c["metadata_admitted_donors"]})
    return {"schema": "IGE_A12_PREDICTION_PREFLIGHT_v1", "frozen_protocol_sha256": PROTOCOL_SHA,
        "all_24_frozen_cases_retained_in_ledger": True,
        "metadata_ready_targets": targets, "metadata_ready_donor_sources": donors,
        "max_distinct_background_source_points_for_this_subset": len(set(targets+donors)),
        "source_byte_exposure_class": "PREVIOUSLY_REVEALED_CONTAINERS; no strict untouched-source claim",
        "new_observation_or_background_requests_made": 0, "predictions_or_actual_prediction_seal_created": False,
        "strict_independent_validation_authorized_by_this_preflight": False,
        "independent_accuracy_qualified": exposure["independent_accuracy_qualified"],
        "next_steps_in_order": [
            "Retain blocked AT/DE/height cases; do not reselect donors, dates or QC after errors",
            "Acquire only admitted donor T/QC and background inputs under frozen 24-asset/200MB limits; log original hashes and all failures",
            "Generate frozen R1/B0 predictions without target-observation input; retain NaNs and all 24 case rows",
            "Publish actual prediction files plus immutable input/code/operator/QC hashes before opening target T",
            "Only after that seal, read target T and score matching times as exposed-source research evaluation, not independent certification",
            "A new independent qualification needs a separate prospective registered cohort/exposure check; no replacement of this frozen cohort"],
        "full_year_local_weather_or_EPW_promotion_allowed": False}


def verify(output):
    import numpy as np
    import pandas as pd
    import streamlit
    output.mkdir(parents=True, exist_ok=False)
    guard = protection(); admission, exposure = prepare(), audit()
    plan = prediction_plan(admission, exposure)
    for filename, value in (("a12_history_admission_20261025.json", admission),
            ("a12_exposure_audit_20261025.json", exposure), ("a12_prediction_preflight_20261025.json", plan)):
        raw = json_bytes(value)
        if (ROOT/"research/ige_cmip6"/filename).read_bytes() != raw: raise ValueError("A12_SAVED_REPLAY_DIFFERS:"+filename)
        write_exclusive(output/filename, raw)
    suite = unittest.TestSuite()
    patterns = [*PATTERNS, ("tools/climate_analyzer/tests", "test_ige_a1_stations.py"),
        ("tools/climate_analyzer/tests", "test_ige_a12_history.py")]
    for folder, pattern in patterns: suite.addTests(unittest.TestLoader().discover(str(ROOT/folder), pattern=pattern))
    start = time.monotonic(); result = unittest.TextTestRunner(verbosity=1).run(suite)
    tests = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "status": "PASS" if result.wasSuccessful() else "FAIL", "wall_seconds": time.monotonic()-start, "patterns": patterns,
        "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "streamlit": streamlit.__version__}
    write_exclusive(output/"tests.json", json_bytes(tests))
    if not result.wasSuccessful(): raise RuntimeError("A12_TESTS_FAILED")
    product_hashes = {}
    for kind, run in (("historical", lambda: run_historical_product(pilot_historical_request())), ("future", run_future_pilot_product)):
        product = run(); product_hashes[kind] = sha256(product.files["climate.epw"]).hexdigest()
    assert product_hashes == {"historical": "acf8e7d82be69de5fa19f76c599143559d477aa01cdb7c56414fc23c93796635",
        "future": "fc00e09811498c368965785ee8873bc4ca1cd01761eaebb19c759faebd0e3c28"}
    receipt = {"schema": "IGE_A12_VERIFICATION_v1", "status": "SOURCE_ADMISSION_AND_EXPOSURE_AUDIT_PASS_WITH_EXPLICIT_SCIENTIFIC_BLOCKS",
        "tests": tests, "protection": guard, "counts": admission["counts"], "old_product_EPW_sha256": product_hashes,
        "history_packet_sha256": PACKET_SHA, "history_packet_file": PACKET,
        "frozen_protocol_sha256": PROTOCOL_SHA, "actual_prediction_seal_created": False,
        "new_target_temperature_or_weather_observation_requests": 0, "new_ERA5_requests": 0,
        "station_observation_tests_are_synthetic": True, "strict_blindness_certified": False,
        "independent_accuracy_qualified": False, "physical_full_weather_qualified": False, "production_ready": False,
        "quality_axes": admission["quality_axes"], "implementation_sha256": {n: sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(IMPLEMENTATION)}}
    write_exclusive(output/"verification.json", json_bytes(receipt))
    print(json.dumps(receipt, indent=2)); return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--out", type=Path, required=True)
    with patch("socket.socket.connect", side_effect=RuntimeError("A12_OFFLINE_NO_NETWORK")), \
            patch("socket.socket.connect_ex", side_effect=RuntimeError("A12_OFFLINE_NO_NETWORK")):
        verify(parser.parse_args().out)
