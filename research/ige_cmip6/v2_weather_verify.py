"""V2-M2 offline verification. Unit results are not measured climate skill."""
from __future__ import annotations
import argparse
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import socket
import subprocess
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from v2_weather_registration import (BASE, ROOT, R, REG, INPUTS, PREDICTIONS, LEDGER, registered, admission)
from v2_weather_run import sources, make_predictions, load_predictions
from v2_verify_metadata import replay as metadata_replay
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive

LIVING = {"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md",
          "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"}


def same_derived_json(live, saved):
    """Portable recomputation only; originals and published seals stay hash exact."""
    if isinstance(live, dict):
        return isinstance(saved, dict) and set(live) == set(saved) and all(same_derived_json(v, saved[k]) for k, v in live.items())
    if isinstance(live, list):
        return isinstance(saved, list) and len(live) == len(saved) and all(same_derived_json(a, b) for a, b in zip(live, saved))
    if isinstance(live, float):
        return isinstance(saved, float) and math.isclose(live, saved, rel_tol=0, abs_tol=1.1e-10)
    return type(live) is type(saved) and live == saved


def protection():
    for row in subprocess.check_output(["git", "diff", "--name-status", BASE], cwd=ROOT, text=True).splitlines():
        status, path = row.split("\t", 1)
        if status != "A" and path not in LIVING:
            raise ValueError("V2_PRIOR_SCIENTIFIC_CODE_OR_RESULT_CHANGED:" + path)
    return {"parent_commit": BASE, "old_scientific_code_protocols_results_unchanged": True}


def replay_predictions(directory, plan):
    bodies, blocks, manifest, storage = sources(directory, INPUTS, "inputs", plan)
    raw, ledger = make_predictions(plan, admission(), bodies, blocks)
    if not same_derived_json(ledger, json.loads((directory / LEDGER).read_text())):
        raise ValueError("V2_ACTUAL_LEDGER_REPLAY_DIFFERENCE")
    live = load_predictions(raw, plan); saved = load_predictions((directory / PREDICTIONS).read_bytes(), plan)
    if list(live.columns) != list(saved.columns):
        raise ValueError("V2_PREDICTION_COLUMNS_CHANGED")
    for col in live:
        if pd.api.types.is_numeric_dtype(live[col]) and live[col].dtype != bool:
            if not np.allclose(live[col], saved[col], rtol=0, atol=1.1e-10, equal_nan=True):
                raise ValueError("V2_NUMERIC_REPLAY_DIFFERENCE:" + col)
        elif not live[col].fillna("").equals(saved[col].fillna("")):
            raise ValueError("V2_CATEGORICAL_REPLAY_DIFFERENCE:" + col)
    return {"all72_cases_and12096_rows_replayed": True, "R1_forecast_hours": ledger["predicted_R1_hours"],
            "input_original_packet_sha256": storage["sha256"], "original_HTTP_attempts": manifest["cumulative_HTTP_attempts"],
            "original_body_bytes": manifest["cumulative_body_bytes"], "new_requests_in_this_replay": 0}


def verify(output, source_directory=None):
    output.mkdir(parents=True, exist_ok=False); start = time.monotonic()
    guard = protection(); plan = registered()
    suite = unittest.TestSuite()
    patterns = ("test_ige_a1_stations.py", "test_ige_v1.py", "test_ige_v2_metadata.py", "test_ige_v2_weather.py")
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tools/climate_analyzer/tests"), pattern=pattern))
    with patch.object(socket.socket, "connect", side_effect=AssertionError("V2_OFFLINE_VERIFICATION_NETWORK_CALL")):
        tests = unittest.TextTestRunner(verbosity=1).run(suite)
        if not tests.wasSuccessful(): raise RuntimeError("V2_WEATHER_OFFLINE_TEST_FAILURE")
        old_metadata = metadata_replay(R)
        prediction = replay_predictions(source_directory, plan) if source_directory else None
    receipt = {"schema": "IGE_V2_EXECUTABLE_WEATHER_VERIFICATION_v1", "status": "PASS", "tests": tests.testsRun,
        "test_patterns": patterns, "protection": guard, "registration_sha256": sha256((R / REG).read_bytes()).hexdigest(),
        "M1_metadata_source_replay": old_metadata, "actual_prediction_replay": prediction,
        "registered_targets": 18, "registered_cases": 72, "requested_reference_hours": 12096,
        "source_inventory": plan["source_inventory"], "new_model_observation_or_target_QC_requests": 0,
        "actual_predictor_weather_acquired_by_this_verifier": False,
        "independent_accuracy_measured_by_this_verification": False, "production_ready": False,
        "wall_seconds": time.monotonic() - start, "runtime": {"pandas": pd.__version__, "numpy": np.__version__}}
    write_exclusive(output / "v2_weather_verification.json", json_bytes(receipt))
    print(json.dumps(receipt), flush=True)
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--out", type=Path, required=True); p.add_argument("--source-directory", type=Path)
    args = p.parse_args(); verify(args.out, args.source_directory)
