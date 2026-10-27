"""Replay the frozen V1 regression plus the separate V1A source/math audit."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time
import unittest

from v1a_qc10_r1_audit import R, ROOT, audit
from v1_verify import verify as verify_v1
from v1_control_admission import verify as verify_old_gate


def verify(output: Path, *, parent=True):
    output.mkdir(parents=True, exist_ok=False); start = time.monotonic()
    old = verify_v1(output / "frozen_V1", "results") if parent else None
    gate = verify_old_gate(output / "old_QC22_gate")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tools/climate_analyzer/tests"), pattern="test_ige_v1a.py")
    tests = unittest.TextTestRunner(verbosity=1).run(suite)
    if not tests.wasSuccessful():
        raise RuntimeError("V1A_TEST_FAILURE")
    result = audit()
    saved = json.loads((R / "v1a_qc10_r1_diagnostics_20261027.json").read_text())
    from v1_verify import numeric_json_equal
    if not numeric_json_equal(saved, result, tolerance=1e-12):
        raise ValueError("V1A_ACTUAL_ORIGINAL_SOURCE_AUDIT_REPLAY_DIFFERENT")
    receipt = {"schema": "IGE_V1A_OFFLINE_SOURCE_AND_REGRESSION_VERIFICATION_v1",
        "parent_V1_tests": old["total_tests"] if old else 0, "old_QC22_gate_tests": gate["tests_run"],
        "new_V1A_tests": tests.testsRun, "total_tests": (old["total_tests"] if old else 0) + gate["tests_run"] + tests.testsRun,
        "status": "PASS", "wall_seconds": time.monotonic() - start,
        "new_station_measurement_or_model_HTTP_requests": 0, "AT_control_T_unopened": True,
        "documentation_packet_sha256": result["documentation"]["packet_sha256"],
        "diagnostics_saved_original_source_replay_equal": True,
        "diagnostics_numerical_replay_tolerance": 1e-12,
        "diagnostics_sha256": sha256((R / "v1a_qc10_r1_diagnostics_20261027.json").read_bytes()).hexdigest(),
        "new_validation_design_sha256": sha256((R / "v1a_next_validation_design_20261027.json").read_bytes()).hexdigest(),
        "new_2019_validation_executed": False, "R1_default_promotion": False,
        "independent_accuracy_or_full_weather_qualification": False, "production_ready": False}
    (output / "v1a_verification.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    (output / "v1a_qc10_r1_diagnostics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(receipt), flush=True)
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--without-parent", action="store_true"); args = p.parse_args()
    verify(args.out, parent=not args.without_parent)
