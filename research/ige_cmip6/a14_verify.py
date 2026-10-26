"""Offline A1.4 tests, immutable-source replay and explicit product gates."""
from __future__ import annotations
import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import subprocess
import time
import unittest
from unittest.mock import patch
import zipfile

from a14_prepare import ROOT,R,BASE,DATE,REGISTRATION,SOURCES,RESULTS,code_hashes,registered
from a14_run import build
from u1_verify import PATTERNS
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive

BUNDLE=f"a14_CH_2025_research_years_{DATE}.zip"


def protection():
    subprocess.run(["git","merge-base","--is-ancestor",BASE,"HEAD"],cwd=ROOT,check=True)
    allowed={"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md",
        "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"}
    for line in subprocess.check_output(["git","diff","--name-status",BASE],cwd=ROOT,text=True).splitlines():
        status,name=line.split("\t",1)
        if status!="A" and name not in allowed:raise ValueError("A14_OLD_CODE_OR_RESULTS_CHANGED:"+name)
    contract=json.loads((R/"p9_3b3_iv1_integration_contract.json").read_text())
    for name,digest in contract["protected_sha256"].items():
        if sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError("A14_PROTECTED_RESEARCH_CHANGED:"+name)
    return {"parent_commit":BASE,"protected_research_files_unchanged":len(contract["protected_sha256"]),
        "old_engine_UI_A1_protocols_sources_scores_and_existing_EPW_unchanged":True,
        "IV1_observations_opened":False,"main_or_merge_used":False}


def bundle(output):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if not path.is_file():continue
            info=zipfile.ZipInfo(path.relative_to(output).as_posix(),(2000,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,path.read_bytes())
    return stream.getvalue()


def verify(output,code_only=False):
    import numpy as np
    import pandas as pd
    import streamlit
    output.mkdir(parents=True,exist_ok=False)
    guard=protection();registered()
    patterns=[*PATTERNS,*(('tools/climate_analyzer/tests',n) for n in
        ('test_ige_a1_stations.py','test_ige_a12_history.py','test_ige_a13_comparison.py','test_ige_a14_station_year.py'))]
    suite=unittest.TestSuite()
    for folder,pattern in patterns:suite.addTests(unittest.TestLoader().discover(str(ROOT/folder),pattern=pattern))
    begin=time.monotonic();test=unittest.TextTestRunner(verbosity=1).run(suite)
    checked={"tests_run":test.testsRun,"failures":len(test.failures),"errors":len(test.errors),"skipped":len(test.skipped),
        "status":"PASS" if test.wasSuccessful() else "FAIL","wall_seconds":time.monotonic()-begin,
        "python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,"streamlit":streamlit.__version__}
    write_exclusive(output/"tests.json",json_bytes(checked))
    if not test.wasSuccessful():raise RuntimeError("A14_TESTS_FAILED")
    replay=None
    if not code_only:
        begin=time.monotonic();census=build(output/"years")
        raw=bundle(output/"years");write_exclusive(output/BUNDLE,raw)
        if json_bytes(census)!=(R/RESULTS).read_bytes() or raw!=(R/BUNDLE).read_bytes():
            raise ValueError("A14_REPLAY_NOT_BYTE_IDENTICAL")
        replay={"original_source_replay_byte_exact":True,"target_years":2,"records_per_year":8760,
            "bundle_sha256":sha256(raw).hexdigest(),"source_packet_sha256":sha256((R/SOURCES).read_bytes()).hexdigest(),
            "replay_wall_seconds":time.monotonic()-begin,
            "R1_admitted_hours":{k:v["temperature"]["R1_admitted_export_means"] for k,v in census["targets"].items()},
            "q_projection_hours":{k:v["q_projection_hours"] for k,v in census["targets"].items()}}
    receipt={"schema":"IGE_A14_OFFLINE_VERIFICATION_v1","tests":checked,"protection":guard,"replay":replay,
        "registration_sha256":sha256((R/REGISTRATION).read_bytes()).hexdigest(),"code_sha256":code_hashes(),
        "new_network_requests_during_verification":0,"physical_scope":"CONDITIONAL_T_P_Q_RH_ONLY",
        "independent_accuracy_qualified":False,"production_ready":False,"existing_UI_defaults_changed":False}
    write_exclusive(output/"verification.json",json_bytes(receipt));print(json.dumps(receipt,indent=2));return receipt


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--out",type=Path,required=True);p.add_argument("--code-only",action="store_true")
    a=p.parse_args()
    with patch("socket.socket.connect",side_effect=RuntimeError("A14_OFFLINE_NO_NETWORK")),patch("socket.socket.connect_ex",side_effect=RuntimeError("A14_OFFLINE_NO_NETWORK")):
        verify(a.out,a.code_only)
