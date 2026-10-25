"""Offline A1.3 checks and replay; code-only mode never needs control weather."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import time
import unittest
from unittest.mock import patch

from a13_prepare import ROOT, R, BASE, registered, code_hashes, SEAL, INPUTS, CONTROLS, PREDICTIONS, LEDGER, RESULTS
from a13_acquire import assert_seal_code
from a13_run import make_predictions, score
from u1_verify import PATTERNS
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive


def protection():
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT, check=True)
    allowed = {"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md", "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"}
    for line in subprocess.check_output(["git", "diff", "--name-status", BASE], cwd=ROOT, text=True).splitlines():
        status, name = line.split("\t", 1)
        if status != "A" and name not in allowed: raise ValueError("A13_OLD_RESULTS_OR_CODE_CHANGED:"+name)
    contract = json.loads((R/"p9_3b3_iv1_integration_contract.json").read_text())
    for name, digest in contract["protected_sha256"].items():
        if sha256((ROOT/name).read_bytes()).hexdigest() != digest: raise ValueError("A13_PROTECTED_RESEARCH_CHANGED:"+name)
    return {"base": BASE, "protected_research_files_unchanged": len(contract["protected_sha256"]),
        "A1_1_A1_2_results_and_frozen_protocols_unchanged": True, "existing_UI_engine_and_default_EPW_unchanged": True,
        "IV1_observations_opened": False}


def verify(output, *, code_only=False):
    import numpy as np
    import pandas as pd
    import streamlit
    output.mkdir(parents=True, exist_ok=False)
    guard = protection(); plan = registered()
    suite = unittest.TestSuite(); patterns = [*PATTERNS,
        ("tools/climate_analyzer/tests", "test_ige_a1_stations.py"),
        ("tools/climate_analyzer/tests", "test_ige_a12_history.py"),
        ("tools/climate_analyzer/tests", "test_ige_a13_comparison.py")]
    for folder, pattern in patterns: suite.addTests(unittest.TestLoader().discover(str(ROOT/folder), pattern=pattern))
    begin = time.monotonic(); result = unittest.TextTestRunner(verbosity=1).run(suite)
    tests = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "status": "PASS" if result.wasSuccessful() else "FAIL", "wall_seconds": time.monotonic()-begin,
        "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "streamlit": streamlit.__version__, "patterns": patterns}
    write_exclusive(output/"tests.json", json_bytes(tests))
    if not result.wasSuccessful(): raise RuntimeError("A13_TESTS_FAILED")
    replay = None
    if not code_only:
        seal_raw = (R/SEAL).read_bytes(); seal = json.loads(seal_raw); assert_seal_code(seal)
        for name, digest in seal["frozen_files_sha256"].items():
            if sha256((R/name).read_bytes()).hexdigest() != digest: raise ValueError("A13_FROZEN_FILE_CHANGED:"+name)
        prediction, ledger, inputs = make_predictions(R/INPUTS)
        if prediction != (R/PREDICTIONS).read_bytes() or json_bytes(ledger) != (R/LEDGER).read_bytes(): raise ValueError("A13_PREDICTION_REPLAY_CHANGED")
        comparison = score(R/CONTROLS, output/"comparison_replay")
        if json_bytes(comparison) != (R/RESULTS).read_bytes(): raise ValueError("A13_FROZEN_SCORES_CHANGED")
        write_exclusive(output/PREDICTIONS, prediction); write_exclusive(output/LEDGER, json_bytes(ledger)); write_exclusive(output/SEAL, seal_raw)
        replay = {"counts": comparison["counts"], "pooled_CH": comparison["pooled_CH"], "per_target": comparison["per_target"],
            "input_packet_sha256": sha256((R/INPUTS).read_bytes()).hexdigest(), "control_packet_sha256": sha256((R/CONTROLS).read_bytes()).hexdigest(),
            "prediction_seal_sha256": sha256(seal_raw).hexdigest(), "published_seal_commit": comparison["published_seal_commit"],
            "predictions_all_24_cases_and_scores_replayed_byte_exact": True, "code_and_workflow_unchanged_since_precontrol_seal": True,
            "decoded_weather_body_bytes_inputs_plus_controls": comparison["acquisition_decoded_body_bytes_cumulative"]}
    receipt = {"schema": "IGE_A13_OFFLINE_VERIFICATION_v1", "mode": "SYNTHETIC_AND_LEGACY_CHECKS_NO_NEW_WEATHER_READ" if code_only else "EXPOSED_SOURCE_PREDICTION_AND_SCORE_REPLAY",
        "tests": tests, "protection": guard, "replay": replay, "code_sha256": code_hashes(),
        "registration_sha256": sha256(json_bytes(plan)).hexdigest(), "new_network_requests_in_verification": 0,
        "strict_independent_accuracy_qualified": False, "full_weather_physical_closure_qualified": False,
        "production_ready": False, "existing_UI_defaults_changed": False}
    write_exclusive(output/"verification.json", json_bytes(receipt)); print(json.dumps(receipt, indent=2)); return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--out", type=Path, required=True); parser.add_argument("--code-only", action="store_true")
    args = parser.parse_args()
    with patch("socket.socket.connect", side_effect=RuntimeError("A13_OFFLINE_NO_NETWORK")), patch("socket.socket.connect_ex", side_effect=RuntimeError("A13_OFFLINE_NO_NETWORK")):
        verify(args.out, code_only=args.code_only)
