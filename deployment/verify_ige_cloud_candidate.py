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


def verify(output):
    output.mkdir(parents=True,exist_ok=False)
    contract=json.loads((ROOT/'deployment/ige-cloud-candidate-20261028.json').read_text())
    for path,expected in contract['copied_sha256'].items():
        assert sha256((ROOT/path).read_bytes()).hexdigest()==expected,path
    versions={}
    for line in (ROOT/'tools/climate_analyzer/requirements-cloud-constraints.txt').read_text().splitlines():
        if '==' in line and not line.startswith('#'):
            name,version=line.split('==');versions[name.lower().replace('_','-')]=version
    installed={d.metadata['Name'].lower().replace('_','-'):d.version for d in metadata.distributions()}
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
             'copied_I2_files_unchanged':len(contract['copied_sha256']),'installed_versions':installed,
             'actual_root_Streamlit_launch_healthy':True,'weather_provider_requests':0,
             'test_process_peak_RSS_MiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
             'peak_is_test_process_not_a_multiuser_cloud_load_test':True,
             'actual_Community_Cloud_build_or_live_deployment_verified':False,
             'publication_status_changed':False,'independent_accuracy_qualified':False,'production_ready':False}
    (output/'verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True,type=Path)
    verify(parser.parse_args().out)
