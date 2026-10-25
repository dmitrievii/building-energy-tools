"""Reproduce I1/A0 from original frozen provider responses, without weather I/O.

This runs source/calendar/regression tests and assembles a real background year.
It does not access stations or award independent scientific qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/climate_analyzer"))
from epw_climate_analyzer.engine import HistoricalRequest, run_historical
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive

BASE = "5481a74dabb9acf40dd745d0006d0a9bc1cea4aa"
SOURCE_SHA = "2575be295bc41be68ac56940524a76c5ef9f9b5010a83f20b6eec21c49dce273"
EPW_SHA = "acf8e7d82be69de5fa19f76c599143559d477aa01cdb7c56414fc23c93796635"
TESTS = [
    ("tools/climate_analyzer/tests", "test_ige_engine.py"),
    ("tools/climate_analyzer/tests", "test_canonical_climate_model.py"),
    ("research/ige_cmip6", "test_e2e_integration_audit.py"),
    ("research/ige_cmip6", "test_p7c1_epw_morphing.py"),
    ("research/ige_cmip6", "test_p7c1b_humidity_closure.py"),
    ("research/ige_cmip6", "test_p9_1a_global_historical_backbone.py"),
    ("research/ige_cmip6", "test_p9_2d_annual_cet_epw_export.py"),
]


def protected_sources() -> dict:
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT, check=True)
    contract_path = "research/ige_cmip6/p9_3b3_iv1_integration_contract.json"
    contract_bytes = (ROOT / contract_path).read_bytes()
    original = subprocess.check_output(["git", "show", BASE + ":" + contract_path], cwd=ROOT)
    assert original == contract_bytes, "I1_A0_PROTECTION_CONTRACT_CHANGED"
    contract = json.loads(contract_bytes)
    for name, expected in contract["protected_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError("I1_A0_PROTECTED_RESEARCH_FILE_CHANGED_" + name)
    changed = subprocess.check_output(["git", "diff", "--name-only", BASE, "--", "tools/climate_analyzer"], cwd=ROOT, text=True).splitlines()
    assert all(p.startswith("tools/climate_analyzer/epw_climate_analyzer/engine/") or
        p in ("tools/climate_analyzer/tests/test_ige_engine.py", "tools/climate_analyzer/tests/test_ige_bm1.py") for p in changed), "I1_A0_EXISTING_APP_FILE_CHANGED"
    return {"ancestor": BASE, "protected_files_unchanged": len(contract["protected_sha256"]),
        "IV1_station_values_opened": False, "main_modified_or_merged": False}


def verify(output: Path) -> dict:
    import numpy as np
    import pandas as pd
    output.mkdir(parents=True, exist_ok=False)
    guard = protected_sources()
    suite = unittest.TestSuite()
    for folder, pattern in TESTS:
        suite.addTests(unittest.TestLoader().discover(str(ROOT / folder), pattern=pattern))
    start = time.perf_counter()
    checked = unittest.TextTestRunner(verbosity=1).run(suite)
    tests = {"tests_run": checked.testsRun, "failures": len(checked.failures), "errors": len(checked.errors),
        "skipped": len(checked.skipped), "status": "PASS" if checked.wasSuccessful() else "FAIL",
        "wall_seconds": time.perf_counter() - start, "patterns": TESTS,
        "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}
    write_exclusive(output / "tests.json", json_bytes(tests))
    if not checked.wasSuccessful():
        raise RuntimeError("I1_A0_TESTS_FAILED")
    request = HistoricalRequest(47.0707, 15.4395, 2023, 60, label="Graz")
    result = run_historical(request, output / "annual",
        source_bundle=ROOT / "research/ige_cmip6/i1_a0_graz2023_original_sources_20261025.zip",
        source_bundle_sha256=SOURCE_SHA)
    manifest = json.loads((output / "annual/manifest.json").read_text())
    assert len(result.data) == 8760 and manifest["EPW"]["fields_per_record"] == 35
    assert manifest["EPW"]["sha256"] == EPW_SHA
    assert manifest["weather_provider_requests_this_run"] == 0
    assert manifest["EPW"]["provider_T_Td_RH_quantization_interval_failures"] == 0
    assert manifest["canonical_adapter"]["calendar_mode"] == "historical"
    assert manifest["canonical_adapter"]["first"] == "2023-01-01T00:00:00+01:00"
    assert manifest["canonical_adapter"]["last"] == "2023-12-31T23:00:00+01:00"
    assert manifest["independent_station_accuracy_qualified"] is False
    assert manifest["production_ready"] is False
    assert manifest["IV1_station_observations_opened"] is False
    # Independent source-address check for every output hour, not just a
    # writer/readback comparison against its own in-memory values.
    import zipfile
    with zipfile.ZipFile(output / "annual/sources.zip") as archive:
        met = json.loads(archive.read("open_meteo.json"))
        power = json.loads(archive.read("nasa_power.json"))
    met_rows = {t: i for i, t in enumerate(met["hourly"]["time"])}
    lw = power["properties"]["parameter"]["ALLSKY_SFC_LW_DWN"]
    for index, (begin, end) in enumerate(zip(request.utc_starts, request.utc_ends)):
        mi = met_rows[end.strftime("%Y-%m-%dT%H:%M")]
        assert result.data["dry_bulb_temperature_c"].iloc[index] == met["hourly"]["temperature_2m"][mi]
        assert result.data["atmospheric_station_pressure_pa"].iloc[index] == 100 * met["hourly"]["surface_pressure"][mi]
        assert result.data["liquid_precipitation_depth_mm"].iloc[index] == met["hourly"]["rain"][mi]
        assert result.data["global_horizontal_radiation_wh_m2"].iloc[index] == met["hourly"]["shortwave_radiation"][mi]
        assert result.data["horizontal_infrared_radiation_intensity_wh_m2"].iloc[index] == lw[begin.strftime("%Y%m%d%H")]
    receipt = {"status": "I1_A0_SOURCE_YEAR_AND_REGRESSION_CHECKS_PASS_NOT_INDEPENDENT_QUALIFICATION",
        "tests": tests, "protection": guard, "source_bundle_sha256": SOURCE_SHA, "EPW_sha256": EPW_SHA,
        "records": 8760, "source_support_addresses_independently_checked_hours": 8760,
        "weather_provider_requests_this_verification": 0, "production_ready": False,
        "independent_accuracy": "NOT_RUN", "EnergyPlus_simulation": "NOT_RUN",
        "UI_connected": False, "local_station_reconstruction_complete": False,
        "annual_manifest_sha256": hashlib.sha256((output / "annual/manifest.json").read_bytes()).hexdigest()}
    write_exclusive(output / "verification.json", json_bytes(receipt))
    print(json.dumps(receipt, indent=2))
    return receipt


if __name__ == "__main__":
    from unittest.mock import patch
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    with patch("socket.socket.connect", side_effect=RuntimeError("I1_A0_VERIFICATION_NETWORK_FORBIDDEN")), \
            patch("socket.socket.connect_ex", side_effect=RuntimeError("I1_A0_VERIFICATION_NETWORK_FORBIDDEN")):
        verify(parser.parse_args().out)
