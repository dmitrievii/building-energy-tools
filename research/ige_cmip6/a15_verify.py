"""Offline A1.5 actual-app checks, immutable parent replay and UI products."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
R=ROOT/"research/ige_cmip6"
sys.path.insert(0,str(ROOT/"tools/climate_analyzer"))
from epw_climate_analyzer.engine_station_product import (load_station_year_product,CATALOG,
    BUNDLE_NAME,STATION_BUNDLE_SHA)
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
from a14_run import build as replay_A14
from a14_verify import bundle as A14_bundle
from u1_verify import PATTERNS

BASE="fb1b77a12a1dd525506d14ffc546988dbc39efb7"
CONTRACT="a15_ui_integration_contract_20261026.json"
APP_MODIFIED={"tools/climate_analyzer/epw_climate_analyzer/"+n for n in
    ("engine_analysis.py","engine_ui.py")}
LIVING={"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md",
    "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"}
CODE=[*sorted(APP_MODIFIED),"tools/climate_analyzer/epw_climate_analyzer/engine_station_product.py",
    "tools/climate_analyzer/epw_climate_analyzer/engine_psychrometrics.py",
    "tools/climate_analyzer/tests/test_ige_a15.py","research/ige_cmip6/a15_verify.py",
    ".github/workflows/ige-a1-5-local-year-ui-20261026.yml"]


def code_hashes():
    return {n:sha256((ROOT/n).read_bytes()).hexdigest() for n in CODE}


def contract():
    protocol=json.loads((R/CONTRACT).read_text())
    if (protocol["parent_commit"]!=BASE or protocol["snapshot_sha256"]!=STATION_BUNDLE_SHA
            or protocol["admitted_station_keys"]!=list(CATALOG)
            or protocol["existing_UI_files_allowed_to_change"]!=sorted(APP_MODIFIED)
            or protocol["new_weather_or_control_acquisition_allowed"] is not False):
        raise ValueError("A15_CONTRACT_CHANGED")
    return protocol


def protection():
    subprocess.run(["git","merge-base","--is-ancestor",BASE,"HEAD"],cwd=ROOT,check=True)
    for line in subprocess.check_output(["git","diff","--name-status",BASE],cwd=ROOT,text=True).splitlines():
        status,name=line.split("\t",1)
        if status!="A" and name not in APP_MODIFIED|LIVING:
            raise ValueError("A15_OLD_CORE_OR_SCIENTIFIC_RESULT_CHANGED:"+name)
    frozen=json.loads((R/"p9_3b3_iv1_integration_contract.json").read_text())["protected_sha256"]
    for name,digest in frozen.items():
        if sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError("A15_PROTECTED_RESEARCH_CHANGED:"+name)
    for name,digest in contract()["protected_parent_sha256"].items():
        if sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError("A15_PROTECTED_PARENT_CHANGED:"+name)
    if sha256((R/BUNDLE_NAME).read_bytes()).hexdigest()!=STATION_BUNDLE_SHA:raise ValueError("A15_ORIGINAL_SNAPSHOT_CHANGED")
    return {"parent_commit":BASE,"protected_P9_research_files_unchanged":len(frozen),
        "existing_scientific_results_original_core_A14_sources_and_EPWs_unchanged":True,
        "UI_files_modified":sorted(APP_MODIFIED),"app_entrypoint_byte_unchanged":True,
        "main_or_merge_used":False,"IV1_control_observations_opened":False}


def verify(output):
    import numpy as np
    import pandas as pd
    import streamlit
    output.mkdir(parents=True,exist_ok=False)
    guard=protection()
    suite=unittest.TestSuite()
    patterns=[*PATTERNS,*(('tools/climate_analyzer/tests',n) for n in
        ('test_ige_a1_stations.py','test_ige_a12_history.py','test_ige_a13_comparison.py',
            'test_ige_a14_station_year.py','test_ige_a15.py'))]
    for folder,pattern in patterns:suite.addTests(unittest.TestLoader().discover(str(ROOT/folder),pattern=pattern))
    start=time.monotonic();test=unittest.TextTestRunner(verbosity=1).run(suite)
    tests={"tests_run":test.testsRun,"failures":len(test.failures),"errors":len(test.errors),"skipped":len(test.skipped),
        "status":"PASS" if test.wasSuccessful() else "FAIL","wall_seconds":time.monotonic()-start,
        "python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,"streamlit":streamlit.__version__}
    write_exclusive(output/"tests.json",json_bytes(tests))
    if not test.wasSuccessful():raise RuntimeError("A15_TESTS_FAILED")
    # This is an original-source regression outside the UI loading service.
    # No old result is overwritten and no original target-body data is opened.
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ige-a15-parent-replay-") as temporary:
        parent_output=Path(temporary)/"year"
        replay_A14(parent_output)
        replay=A14_bundle(parent_output)
        if replay!=(R/BUNDLE_NAME).read_bytes():raise ValueError("A15_PARENT_YEAR_REPLAY_CHANGED")
    parent_replay={"byte_exact":True,"two_complete_years":True,"snapshot_sha256":sha256(replay).hexdigest(),
        "wall_seconds":time.monotonic()-start,"UI_service_performs_this_reconstruction":False}
    products={}
    for key in CATALOG:
        start=time.monotonic();p=load_station_year_product(key)
        folder=output/key.replace(":","_");folder.mkdir()
        for name in ("climate.epw","hourly.csv.gz","analysis_state.csv.gz","ui_report.json","source_references.json"):
            write_exclusive(folder/name,p.files[name])
        write_exclusive(folder/"complete_product.zip",p.archive)
        products[key]={"rows":len(p.dataset.data),"calendar_mode":p.dataset.temporal.calendar_mode,
            "EPW_sha256":sha256(p.files["climate.epw"]).hexdigest(),"UI_archive_sha256":sha256(p.archive).hexdigest(),
            "UI_archive_bytes":len(p.archive),"wall_seconds":time.monotonic()-start,
            "original_snapshot_product_sha256":p.report["original_snapshot_product_sha256"],
            "weather_provider_requests_this_run":p.report["weather_provider_requests_this_run"],
            "UI_connected":True,"production_ready":False}
    result={"schema":"IGE_A15_ACTUAL_UI_AND_SNAPSHOT_VERIFICATION_v1","tests":tests,"protection":guard,
        "parent_original_source_replay":parent_replay,"products":products,"code_sha256":code_hashes(),
        "contract_sha256":sha256((R/CONTRACT).read_bytes()).hexdigest(),
        "actual_app_entrypoint":"tools/climate_analyzer/app.py","UI_test_method":"streamlit.testing.v1.AppTest",
        "browser_visual_test_performed":False,"public_deployment_changed":False,
        "new_NASA_ERA5_station_or_control_acquisition":0,"UI_snapshot_values_modified":False,
        "independent_accuracy_qualified":False,"instantaneous_T_accuracy_qualified":False,
        "local_pressure_accuracy_qualified":False,"full_weather_cross_field_accuracy_qualified":False,
        "production_ready":False,"existing_Graz_historical_and_future_EPWs_unchanged":True}
    write_exclusive(output/"verification.json",json_bytes(result))
    print(json.dumps(result,indent=2));return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    with patch("socket.socket.connect",side_effect=RuntimeError("A15_OFFLINE_NO_NETWORK")), \
            patch("socket.socket.connect_ex",side_effect=RuntimeError("A15_OFFLINE_NO_NETWORK")):
        verify(args.out)
