"""Verify the small public research-beta backport with Cloud's dependency file."""
from pathlib import Path
from hashlib import sha256
from importlib import metadata
import json
import os
import resource
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools/climate_analyzer'),str(ROOT/'research/ige_cmip6')]


# Historical release evidence and current compatibility are separate.
FROZEN_F1_RELEASE = "eb4e14d84b2e372feeba73713b18d21cde7f2207"
FROZEN_F1_CONTRACT = Path("deployment/ige-f1-two-hour-candidate-20261104.json")
# Explicit code-path differences identified by comparing the original release
# with the current branch. Frozen weather, calibration and evidence files
# continue to require exact identity. Future additions require explicit review.
CURRENT_COMPATIBILITY_PATHS = frozenset({
    ".github/workflows/ige-cloud-release-candidate-20261028.yml",
    "deployment/verify_ige_cloud_candidate.py",
    "tools/climate_analyzer/app.py",
    "tools/climate_analyzer/epw_climate_analyzer/charts.py",
    # R2.18: engine hourly plot only; explicitly reviewed semantic line colour.
    "tools/climate_analyzer/epw_climate_analyzer/engine_ui.py",
    "tools/climate_analyzer/epw_climate_analyzer/geosphere.py",
    "tools/climate_analyzer/epw_climate_analyzer/station_year_ui.py",
    "tools/climate_analyzer/tests/test_ige_h1_station_year_ui.py",
    # R2.19 HF1: drive the new grouped UI widgets in the retained route
    # regressions; frozen physical products, assertions and evidence remain.
    "tools/climate_analyzer/tests/test_ige_a15.py",
    "tools/climate_analyzer/tests/test_ige_f1_selected_future_ui.py",
    "tools/climate_analyzer/tests/test_ige_u1.py",
    "tools/climate_analyzer/tests/test_ige_workspace_ux.py",
})


def _git_bytes(commit, path):
    return subprocess.check_output(["git","show",f"{commit}:{path}"],cwd=ROOT)


def source_evidence(contract_path, *, current_tree=False):
    contract_bytes=(ROOT/contract_path).read_bytes()
    contract=json.loads(contract_bytes)
    expected_sources=contract.get('source_sha256',contract.get('copied_sha256',{}))
    assert expected_sources,'Missing source manifest'
    if current_tree:
        assert Path(contract_path)==FROZEN_F1_CONTRACT,"Current regression requires the frozen F1 contract"
        assert _git_bytes(FROZEN_F1_RELEASE,contract_path)==contract_bytes,"Frozen release manifest changed"
    current={}
    changes=[]
    for path,expected in expected_sources.items():
        if current_tree:
            original=sha256(_git_bytes(FROZEN_F1_RELEASE,path)).hexdigest()
            assert original==expected,f"Historical release evidence mismatch: {path}"
        actual=sha256((ROOT/path).read_bytes()).hexdigest()
        current[path]=actual
        if actual!=expected:
            assert current_tree and path in CURRENT_COMPATIBILITY_PATHS,f"Unreviewed source change: {path}"
            changes.append({"path":path,"historical_sha256":expected,"current_sha256":actual})
    return contract,{
        "mode":"CURRENT_TREE_OFFLINE_COMPATIBILITY" if current_tree else "FROZEN_EXACT_CANDIDATE",
        "historical_release_commit":FROZEN_F1_RELEASE if current_tree else None,
        "historical_manifest_sha256":sha256(contract_bytes).hexdigest(),
        "manifest_entries":len(expected_sources),
        "unchanged_current_entries":len(expected_sources)-len(changes),
        "reviewed_changed_paths":changes,
        "current_sha256":current,
        "current_git_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "new_independent_accuracy_validation":False,
    }


def verify(output, contract_path, *, current_tree=False):
    output.mkdir(parents=True,exist_ok=False)
    contract,evidence=source_evidence(contract_path,current_tree=current_tree)
    (output/"source-evidence.json").write_text(json.dumps(evidence,indent=2)+"\n")
    expected_sources=evidence["current_sha256"]
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    versions={}
    for line in (ROOT/'tools/climate_analyzer/requirements-cloud-constraints.txt').read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):
            continue
        requirement=Requirement(line)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        name=canonicalize_name(requirement.name)
        specs=list(requirement.specifier)
        assert len(specs)==1 and specs[0].operator=='==' and '*' not in specs[0].version, (name,line)
        assert name not in versions, ("Multiple active pins",name)
        versions[name]=specs[0].version
    installed={canonicalize_name(d.metadata['Name']):d.version for d in metadata.distributions()}
    for name,version in versions.items():
        if name in installed:assert installed[name]==version,(name,version,installed[name])
    subprocess.run([sys.executable,'-m','pip','check'],cwd=ROOT,check=True)
    started=time.monotonic()
    with patch('socket.socket.connect',side_effect=RuntimeError('CLOUD_PREFLIGHT_OFFLINE')), \
         patch('socket.socket.connect_ex',side_effect=RuntimeError('CLOUD_PREFLIGHT_OFFLINE')), \
         (output/'tests.log').open('w',encoding='utf-8') as log:
        suite=unittest.TestLoader().discover(str(ROOT/'tools/climate_analyzer/tests'),pattern='test_*.py')
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    tests={'count':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
           'skips':len(result.skipped),'seconds':time.monotonic()-started}
    (output/'tests.json').write_text(json.dumps(tests,indent=2)+'\n')
    if not result.wasSuccessful():
        # Surface the exact failing test and traceback in the workflow log;
        # keep the complete offline regression log as the archived evidence.
        for case,traceback in result.failures+result.errors:
            print(f"CLOUD REGRESSION FAILURE: {case}\n{traceback}",flush=True)
    assert result.wasSuccessful(),'See tests.log'
    from epw_climate_analyzer.engine_application import run_historical_product,pilot_historical_request,run_future_pilot_product
    from epw_climate_analyzer.engine_station_product import load_station_year_product
    products={}
    with patch('socket.socket.connect',side_effect=RuntimeError('CLOUD_PREFLIGHT_OFFLINE')), \
         patch('socket.socket.connect_ex',side_effect=RuntimeError('CLOUD_PREFLIGHT_OFFLINE')):
        for name,run in [('graz-historical',lambda:run_historical_product(pilot_historical_request())),
                         ('graz-future',run_future_pilot_product),
                         ('basel-2025',lambda:load_station_year_product('CH:BAS')),
                         ('altdorf-2025',lambda:load_station_year_product('CH:ALT'))]:
            product=run();assert len(product.dataset.data)==8760
            assert product.report['weather_provider_requests_this_run']==0
            (output/(name+'.zip')).write_bytes(product.archive)
            products[name]={'rows':8760,'EPW_sha256':sha256(product.files['climate.epw']).hexdigest(),
                            'archive_sha256':sha256(product.archive).hexdigest(),'bytes':len(product.archive)}
        from epw_climate_analyzer.geosphere_station_year import run_station_year
        from epw_climate_analyzer.engine.station_epw_admission import StationYearRequest
        source_contract=json.loads((ROOT/'research/ige_cmip6/h1_graz16412_2023_source_contract_20261028.json').read_bytes())
        source_packet=(ROOT/'research/ige_cmip6'/source_contract['source_packet']).read_bytes()
        annual=run_station_year(StationYearRequest(**source_contract['request']),source_packet=source_packet,
                               expected_sha256=source_contract['source_packet_sha256'])
        assert annual.report['status']==source_contract['expected_status']
        assert 'climate.epw' not in annual.files
        annual_counts={row['field']:row['numeric_hours'] for row in annual.report['fields']}
        for field,count in source_contract['expected_numeric_hours'].items():assert annual_counts[field]==count,field
        (output/'h1-graz16412-2023-admission.zip').write_bytes(annual.archive)
        annual_summary={'status':annual.report['status'],'source_rows':annual.report['source_rows'],
                        'expected_hours':annual.report['expected_hours'],'numeric_hours':annual_counts,
                        'source_packet_sha256':source_contract['source_packet_sha256'],
                        'EPW_absence_correctly_enforced':True,'offline_replay':True,'new_independent_validation':False}
        from s1_replay_audit import replay_s1_examples
        point_summary=replay_s1_examples(output)
        from f1_replay_audit import replay_f1_example
        _,future_summary=replay_f1_example(output)
        if contract.get('real_station_development_pilot_implemented'):
            from at_station_usability_replay import replay_at_station_pilot
            at_station_summary=replay_at_station_pilot(output)
            (output/'at-real-station-usability.json').write_text(json.dumps(at_station_summary,indent=2)+'\n')
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    with (output/'server.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'-m','streamlit','run',str(ROOT/'tools/climate_analyzer/app.py'),
                                  '--server.address=127.0.0.1','--server.port='+str(port)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        try:
            ready=False;started=time.monotonic()
            while time.monotonic()-started<45:
                assert process.poll() is None,'Streamlit stopped'
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/_stcore/health',timeout=2) as response:
                        assert response.status==200 and response.read().strip()==b'ok';ready=True;break
                except (urllib.error.URLError,TimeoutError):time.sleep(.25)
            assert ready,'Streamlit health timeout'
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    receipt={'schema':'IGE_CLOUD_RESEARCH_BETA_PREFLIGHT_v1','status':'PASS','tests':tests,'products':products,
             'verified_source_files':len(expected_sources),'preflight_contract':str(contract_path),
             'qualification_scope':evidence['mode'],
             'historical_release_manifest_preserved':True,
             'changed_source_files':evidence['reviewed_changed_paths'],
             'saved_examples_are_offline_regressions_not_public_city_choices':True,'installed_versions':installed,
             'actual_root_Streamlit_launch_healthy':True,'weather_provider_requests':0,'H1_original_year_replay':annual_summary,
             'S1_retained_integration_examples':point_summary,
             'F1_selected_base_future_example':future_summary,
             'test_process_peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
             'peak_is_test_process_not_a_multiuser_cloud_load_test':True,
             'actual_Community_Cloud_build_or_live_deployment_verified':False,
             'publication_status_changed':False,'independent_accuracy_qualified':False,'production_ready':False}
    (output/'verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--contract',type=Path,default=Path('deployment/ige-f1-candidate-20261029.json'))
    parser.add_argument('--current-tree-regression',action='store_true',help='Verify the immutable historical release and replay current reviewed code separately.')
    args=parser.parse_args()
    verify(args.out,args.contract,current_tree=args.current_tree_regression)
