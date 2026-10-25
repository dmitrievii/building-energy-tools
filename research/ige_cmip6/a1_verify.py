"""A1.1 offline acceptance plus all 180 U1/core regressions.

Metadata is real; adapter observation records and residual tests are synthetic.
This command cannot grant independent skill, reveal IV1 or change UI defaults.
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

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools/climate_analyzer"))
from a1_prepare import prepare,PACKETS
from u1_verify import PATTERNS
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive

BASE="8d9456e1085ff33827fdb7304922b3ff2639ea9b"
APP_ALLOWED={"tools/climate_analyzer/epw_climate_analyzer/station_reconstruction.py", "tools/climate_analyzer/tests/test_ige_a1_stations.py"}


def protection():
    subprocess.run(["git","merge-base","--is-ancestor",BASE,"HEAD"],cwd=ROOT,check=True)
    contract_name="research/ige_cmip6/p9_3b3_iv1_integration_contract.json"
    raw=(ROOT/contract_name).read_bytes()
    assert raw==subprocess.check_output(["git","show",BASE+":"+contract_name],cwd=ROOT)
    contract=json.loads(raw)
    for name,digest in contract["protected_sha256"].items():assert sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    changed=subprocess.check_output(["git","diff","--name-only",BASE,"--","tools/climate_analyzer"],cwd=ROOT,text=True).splitlines()
    assert set(changed)<=APP_ALLOWED,"A1_EXISTING_ENGINE_OR_UI_CHANGED"
    # New files outside git's diff are also explicitly scoped in the workflow.
    return {"base":BASE,"protected_research_files_unchanged":len(contract["protected_sha256"]),
        "original_engine_UI_and_existing_tests_changed":False,"IV1_observations_opened":False}


def verify(output):
    import numpy as np
    import pandas as pd
    import streamlit
    output.mkdir(parents=True,exist_ok=False);guard=protection()
    protocol,admission=prepare()
    expected=ROOT/"research/ige_cmip6/a1_1_protocol_20261025.json"
    assert json_bytes(protocol)==expected.read_bytes(),"A1_REGISTERED_PROTOCOL_CHANGED"
    assert json_bytes(admission)==(ROOT/"research/ige_cmip6/a1_1_admission_20261025.json").read_bytes()
    write_exclusive(output/"registered_protocol.json",json_bytes(protocol))
    write_exclusive(output/"source_admission.json",json_bytes(admission))
    suite=unittest.TestSuite()
    patterns=[*PATTERNS,("tools/climate_analyzer/tests","test_ige_a1_stations.py")]
    for folder,pattern in patterns:suite.addTests(unittest.TestLoader().discover(str(ROOT/folder),pattern=pattern))
    clock=time.monotonic();result=unittest.TextTestRunner(verbosity=1).run(suite)
    tests={"tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),
        "status":"PASS" if result.wasSuccessful() else "FAIL","wall_seconds":time.monotonic()-clock,
        "python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,"streamlit":streamlit.__version__,"patterns":patterns}
    write_exclusive(output/"tests.json",json_bytes(tests))
    if not result.wasSuccessful():raise RuntimeError("A1_TESTS_FAILED")
    receipt={"schema":"IGE_A1_1_VERIFICATION_v1","status":"STATION_ADAPTERS_AND_METADATA_PREPARATION_PASS_NOT_VALIDATION_READY",
        "tests":tests,"protection":guard,"protocol_sha256":sha256(expected.read_bytes()).hexdigest(),
        "source_packets_sha256":PACKETS,"catalog_counts":admission["eligible_nominal_catalog_stations"],
        "targets":6,"donor_slots":18,"planned_target_reference_hours":4032,
        "fully_admitted_target_cells":0,"new_station_observation_or_weather_requests":0,"new_measured_values_read":0,
        "station_adapter_and_residual_observation_tests_use_synthetic_values":True,
        "old_180_U1_core_regressions_including_actual_years_executed":True,
        "new_2025_cohort_certified_strictly_blind":False,"independent_station_accuracy_qualified":False,
        "temperature_candidate_is_a_full_weather_or_EPW_product":False,"UI_defaults_changed":False,
        "production_ready":False,"IV1_station_observations_opened":False,
        "implementation_sha256":{name:sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(APP_ALLOWED|{
            "research/ige_cmip6/a1_prepare.py","research/ige_cmip6/a1_verify.py","research/ige_cmip6/a1_acquire_metadata.py"})}}
    write_exclusive(output/"verification.json",json_bytes(receipt));print(json.dumps(receipt,indent=2))
    return receipt


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",type=Path,required=True)
    with patch("socket.socket.connect",side_effect=RuntimeError("A1_OFFLINE_VERIFICATION_NO_NETWORK")), \
            patch("socket.socket.connect_ex",side_effect=RuntimeError("A1_OFFLINE_VERIFICATION_NO_NETWORK")):
        verify(parser.parse_args().out)
