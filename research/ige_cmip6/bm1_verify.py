"""Offline common-core verification and two real-source annual product routes.

No station observations, no new weather acquisition, no independent accuracy
qualification. All original source packets are SHA pinned and retained.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/climate_analyzer"))
from epw_climate_analyzer.engine import HistoricalRequest, FutureRequest, run_historical, run_future
from epw_climate_analyzer.engine.future import PATTERN_SOURCE_SHA
from epw_climate_analyzer.engine.model_sources import SEMANTICS_VERSION
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
from i1_a0_verify import protected_sources, TESTS

RESEARCH = ROOT / "research/ige_cmip6"
HISTORICAL_SHA = "acf8e7d82be69de5fa19f76c599143559d477aa01cdb7c56414fc23c93796635"


def verify(output: Path) -> dict:
    import numpy as np
    import pandas as pd
    output.mkdir(parents=True, exist_ok=False)
    protection = protected_sources()
    suite = unittest.TestSuite()
    patterns = [*TESTS, ("tools/climate_analyzer/tests", "test_ige_bm1.py"),
        ("research/ige_cmip6", "test_p9_3b3_thermodynamics.py")]
    for folder, pattern in patterns:
        suite.addTests(unittest.TestLoader().discover(str(ROOT / folder), pattern=pattern))
    clock = time.monotonic()
    checked = unittest.TextTestRunner(verbosity=1).run(suite)
    tests = {"tests_run": checked.testsRun, "failures": len(checked.failures), "errors": len(checked.errors),
        "skipped": len(checked.skipped), "status": "PASS" if checked.wasSuccessful() else "FAIL",
        "wall_seconds": time.monotonic()-clock, "patterns": patterns, "python": platform.python_version(),
        "numpy": np.__version__, "pandas": pd.__version__}
    write_exclusive(output / "tests.json", json_bytes(tests))
    if not checked.wasSuccessful(): raise RuntimeError("BM1_TESTS_FAILED")
    hrequest = HistoricalRequest(47.0707, 15.4395, 2023, 60, label="Graz")
    source = RESEARCH / "i1_a0_graz2023_original_sources_20261025.zip"
    historical = run_historical(hrequest, output / "historical", source_bundle=source, source_bundle_sha256=PATTERN_SOURCE_SHA)
    hmanifest = json.loads((output / "historical/manifest.json").read_text())
    assert hmanifest["EPW"]["sha256"] == HISTORICAL_SHA
    future_request = FutureRequest(HISTORICAL_SHA, "CanESM5", "r1i1p1f1", "ssp245", (2002, 2014),
        (2040, 2059), SEMANTICS_VERSION, 2023)
    future = run_future(hrequest, future_request, pattern_sources=source,
        reference_sources=RESEARCH / "bm1_reference_sources_2002_2014_20261025.zip",
        nex_sources=RESEARCH / "e2e_original_replay_inputs_20261025.zip",
        protocol=RESEARCH / "bm1_protocol_20261025.json", output=output / "future")
    fmanifest = json.loads((output / "future/manifest.json").read_text())
    assert len(historical.data) == len(future.data) == 8760
    assert historical.to_canonical().temporal.calendar_mode == "historical"
    assert future.to_canonical().temporal.calendar_mode == "climatology"
    assert hmanifest["weather_provider_requests_this_run"] == fmanifest["weather_provider_requests_this_run"] == 0
    assert not fmanifest["production_ready"] and not fmanifest["IV1_station_observations_opened"]
    assert fmanifest["signal_readback"]["sidecar_readback"]["status"] == "SAVED_SIDECAR_CLOCK_Q_AND_TOTAL_PRECIPITATION_PASS"
    expected = RESEARCH / "bm1_verified_local_20261025.json"
    if expected.is_file():
        proof = json.loads(expected.read_text())
        assert proof["historical_EPW_sha256"] == hmanifest["EPW"]["sha256"]
        assert proof["future_EPW_sha256"] == fmanifest["EPW"]["sha256"]
    receipt = {"schema": "IGE_BM1_VERIFICATION_v1", "status": "TWO_ANNUAL_ROUTES_AND_CONDITIONAL_PHYSICS_PASS_NOT_QUALIFIED",
        "tests": tests, "protection": protection, "historical_EPW_sha256": hmanifest["EPW"]["sha256"],
        "future_EPW_sha256": fmanifest["EPW"]["sha256"], "historical_records": 8760, "future_records": 8760,
        "reference_original_hours": fmanifest["diagnostics"]["reference"]["full_original_hours"],
        "reference_estimator_hours": fmanifest["diagnostics"]["reference"]["noleap_estimator_total_hours"],
        "climate_reference_window": [2002, 2014], "future_climate_window": [2040, 2059], "pattern_year": 2023,
        "source_packets": fmanifest["source_packets"], "weather_provider_requests_this_verification": 0,
        "NASA_hurs_signal_enforced": False, "independent_station_accuracy_qualified": False,
        "production_ready": False, "UI_connected": False, "actual_EnergyPlus_simulation_run": False,
        "IV1_station_observations_opened": False,
        "future_manifest_sha256": hashlib.sha256((output / "future/manifest.json").read_bytes()).hexdigest()}
    write_exclusive(output / "verification.json", json_bytes(receipt))
    print(json.dumps(receipt, indent=2))
    return receipt


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--out", type=Path, required=True)
    with patch("socket.socket.connect", side_effect=RuntimeError("BM1_VERIFICATION_NETWORK_FORBIDDEN")), \
            patch("socket.socket.connect_ex", side_effect=RuntimeError("BM1_VERIFICATION_NETWORK_FORBIDDEN")):
        verify(p.parse_args().out)
