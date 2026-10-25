"""Offline U1 acceptance: real Streamlit routes, old regressions and two EPWs.

No original engine equation/exporter or archived scientific result is changed.
The UI is exercised by Streamlit AppTest, not by an external browser/deployment.
"""
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
sys.path.insert(0, str(ROOT / "tools/climate_analyzer"))
from epw_climate_analyzer.engine_application import run_historical_product, run_future_pilot_product, pilot_historical_request
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
from i1_a0_verify import TESTS

BASE = "c4f98b31259cee086d046246dabd77815a051b12"
PATTERNS = [*TESTS,
    ("tools/climate_analyzer/tests", "test_ige_bm1.py"),
    ("research/ige_cmip6", "test_p9_3b3_thermodynamics.py"),
    ("tools/climate_analyzer/tests", "test_ige_u1.py"),
    ("tools/climate_analyzer/tests", "test_startup_dependency_contract.py"),
    ("tools/climate_analyzer/tests", "test_source_neutral_ui_0_7_4.py"),
    ("tools/climate_analyzer/tests", "test_historical_psychrometric_physical_closure.py"),
    ("tools/climate_analyzer/tests", "test_source_parity_streamlit_rerun_reset_0_7_5_5.py")]
APP_FILES = {"tools/climate_analyzer/app.py", *["tools/climate_analyzer/epw_climate_analyzer/" + p
    for p in ("engine_analysis.py", "engine_application.py", "engine_ui.py")], "tools/climate_analyzer/tests/test_ige_u1.py"}


def protection() -> dict:
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT, check=True)
    contract_name = "research/ige_cmip6/p9_3b3_iv1_integration_contract.json"
    contract_bytes = (ROOT / contract_name).read_bytes()
    assert subprocess.check_output(["git", "show", BASE + ":" + contract_name], cwd=ROOT) == contract_bytes
    contract = json.loads(contract_bytes)
    for name, expected in contract["protected_sha256"].items():
        assert sha256((ROOT/name).read_bytes()).hexdigest() == expected, "U1_PROTECTED_RESEARCH_CHANGED_" + name
    changed = subprocess.check_output(["git", "diff", "--name-only", BASE, "--", "tools/climate_analyzer"], cwd=ROOT, text=True).splitlines()
    assert set(changed).issubset(APP_FILES), "U1_APP_CHANGE_OUTSIDE_ADMITTED_SCOPE"
    for path in sorted((ROOT/"tools/climate_analyzer/epw_climate_analyzer/engine").glob("*.py")):
        name = path.relative_to(ROOT).as_posix()
        assert path.read_bytes() == subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT), "U1_ORIGINAL_ENGINE_CHANGED_" + name
    return {"base": BASE, "protected_research_files_unchanged": len(contract["protected_sha256"]),
        "original_I1_A0_B_M1_engine_byte_unchanged": True, "IV1_station_values_opened": False}


def verify(output: Path) -> dict:
    import numpy as np
    import pandas as pd
    import streamlit
    output.mkdir(parents=True, exist_ok=False)
    guard = protection()
    suite = unittest.TestSuite()
    for folder, pattern in PATTERNS:
        suite.addTests(unittest.TestLoader().discover(str(ROOT/folder), pattern=pattern))
    clock = time.monotonic()
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    checked = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "status": "PASS" if result.wasSuccessful() else "FAIL",
        "wall_seconds": time.monotonic()-clock, "patterns": PATTERNS,
        "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "streamlit": streamlit.__version__}
    write_exclusive(output/"tests.json", json_bytes(checked))
    if not result.wasSuccessful(): raise RuntimeError("U1_TESTS_FAILED")
    products = {}
    for mode, run in (("historical", lambda: run_historical_product(pilot_historical_request())), ("future", run_future_pilot_product)):
        clock = time.monotonic(); product = run()
        write_exclusive(output/(mode + "_complete_product.zip"), product.archive)
        write_exclusive(output/(mode + "_ui_report.json"), product.files["ui_report.json"])
        products[mode] = {"records": len(product.dataset.data), "calendar_mode": product.dataset.temporal.calendar_mode,
            "EPW_sha256": sha256(product.files["climate.epw"]).hexdigest(), "zip_sha256": sha256(product.archive).hexdigest(),
            "zip_bytes": len(product.archive), "wall_seconds": time.monotonic()-clock,
            "UI_connected": True, "weather_provider_requests_this_run": product.report["weather_provider_requests_this_run"],
            "quality": product.report["quality"], "production_ready": False}
    receipt = {"schema": "IGE_U1_VERIFICATION_v1", "status": "UI_ROUTES_AND_PHASE_ADAPTER_PASS_RESEARCH_SCOPE",
        "tests": checked, "protection": guard, "products": products,
        "UI_actual_entrypoint_tested": "tools/climate_analyzer/app.py",
        "UI_test_method": "streamlit.testing.v1.AppTest including runtime patch installation",
        "new_weather_provider_requests": 0, "new_NASA_ERA5_station_acquisition": 0,
        "live_provider_transport_in_UI_independently_exercised": False,
        "live_request_form_and_failure_path_tested_with_stubs": True,
        "browser_visual_test_performed": False, "public_deployment_changed": False,
        "NASA_hurs_signal_enforced": False, "independent_station_accuracy_qualified": False,
        "production_ready": False, "actual_EnergyPlus_simulation_run": False, "IV1_station_values_opened": False,
        "implementation_sha256": {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in [*(ROOT/name for name in sorted(APP_FILES)), Path(__file__)]}}
    write_exclusive(output/"verification.json", json_bytes(receipt))
    print(json.dumps(receipt, indent=2))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--out", type=Path, required=True)
    with patch("socket.socket.connect", side_effect=RuntimeError("U1_OFFLINE_VERIFICATION_NETWORK_FORBIDDEN")), \
            patch("socket.socket.connect_ex", side_effect=RuntimeError("U1_OFFLINE_VERIFICATION_NETWORK_FORBIDDEN")):
        verify(parser.parse_args().out)
