"""Run the real-browser acceptance server and client in one network namespace."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--chrome-path', default='/usr/bin/google-chrome')
    p.add_argument('--node', default='node')
    a = p.parse_args(); out = a.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT/'tools/climate_analyzer'))
    from epw_climate_analyzer.engine_application import run_historical_product, pilot_historical_request
    inputs = out/'inputs'; inputs.mkdir(exist_ok=True)
    bg = run_historical_product(pilot_historical_request())
    (inputs/'base_Graz_2023.epw').write_bytes(bg.files['climate.epw'])
    with zipfile.ZipFile(ROOT/'research/ige_cmip6/s1_grid_epw_original_inputs_20261028.zip') as archive:
        for name in archive.namelist():
            if name.endswith('.epw'):
                if Path(name).name != name: raise ValueError('Unsafe donor fixture path')
                (inputs/name).write_bytes(archive.read(name))
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0)); port = reserve.getsockname()[1]
    env = dict(os.environ, PYTHONPATH=str(ROOT/'tools/climate_analyzer')+os.pathsep+str(ROOT/'research/ige_cmip6'),
        OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', TARGET_URL=f'http://127.0.0.1:{port}/',
        IGE_VISUAL_OUT=str(out), CHROME_PATH=a.chrome_path)
    with (out/'streamlit.log').open('w') as log:
        server = subprocess.Popen([sys.executable,'-m','streamlit','run',str(ROOT/'deployment/ige_workspace_visual_harness.py'),
            '--server.address','127.0.0.1','--server.port',str(port),'--server.fileWatcherType','none'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if server.poll() is not None: raise RuntimeError('Streamlit exited: see streamlit.log')
                try:
                    with urllib.request.urlopen(env['TARGET_URL']+'_stcore/health',timeout=1) as response:
                        if response.status == 200: break
                except OSError: pass
                time.sleep(.2)
            else: raise RuntimeError('Streamlit startup timeout')
            subprocess.run([a.node,str(ROOT/'deployment/ige_workspace_browser_acceptance.mjs')],cwd=ROOT,env=env,check=True)
            subprocess.run([sys.executable,str(ROOT/'deployment/verify_ige_workspace_downloads.py'),'--out',str(out)],cwd=ROOT,env=env,check=True)
        finally:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill();server.wait(timeout=5)


if __name__ == '__main__': main()
