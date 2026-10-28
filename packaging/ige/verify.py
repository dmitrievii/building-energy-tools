"""I2 combined application acceptance and offline four-product export."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / 'tools/climate_analyzer', ROOT / 'research/ige_cmip6'):
    sys.path.insert(0, str(path))
import ige

# These are acquisition/preregistration experiments, not application routes.
# Their historical Git-ancestry gates belong to the preserved research CI.
# A user installation must work from a shallow clone or a source archive.
CAMPAIGN_TESTS = {'test_ige_v1.py', 'test_ige_v1a.py', 'test_ige_v2_metadata.py',
                  'test_ige_v2_weather.py', 'test_ige_v2_m3_execution.py', 'test_ige_v2_m4.py'}
HISTORICAL_AUDIT_CLASSES = {'test_ige_a12_history.ExposureAuditTests'}
HISTORICAL_GIT_TESTS = {
    'test_e2e_integration_audit.ReplayBoundaryControls.test_prior_result_directory_is_never_overwritten'
}
PLATFORM_FIXTURE_TESTS = {
    'test_e2e_integration_audit.ReplayBoundaryControls.test_duplicate_and_traversing_archive_names_rejected'
}


@contextmanager
def offline():
    with patch.object(socket.socket, 'connect', side_effect=RuntimeError('I2_OFFLINE_WEATHER_NETWORK_FORBIDDEN')), \
         patch.object(socket.socket, 'connect_ex', side_effect=RuntimeError('I2_OFFLINE_WEATHER_NETWORK_FORBIDDEN')):
        yield


def cases(suite):
    for child in suite:
        if isinstance(child, unittest.TestSuite):
            yield from cases(child)
        else:
            yield child


def combined_suite():
    from i1_a0_verify import TESTS
    suite = unittest.TestSuite()
    paths = [('tools/climate_analyzer/tests', p.name)
             for p in sorted((ROOT / 'tools/climate_analyzer/tests').glob('test_*.py'))
             if p.name not in CAMPAIGN_TESTS]
    paths += [
             *[(f, p) for f, p in TESTS if f == 'research/ige_cmip6'],
             ('research/ige_cmip6', 'test_p9_3b3_thermodynamics.py'),
             ('packaging/ige/tests', 'test_i2_*.py')]
    seen = set()
    for folder, pattern in paths:
        loaded = unittest.TestLoader().discover(str(ROOT / folder), pattern=pattern)
        for case in cases(loaded):
            if case.id().rsplit('.', 1)[0] in HISTORICAL_AUDIT_CLASSES:
                continue
            if case.id() in HISTORICAL_GIT_TESTS | PLATFORM_FIXTURE_TESTS:
                continue
            if case.id() not in seen:
                seen.add(case.id())
                suite.addTest(case)
    return suite


def run_tests(output):
    with offline(), (output / 'tests.log').open('w', encoding='utf-8') as log:
        suite = combined_suite()
        started = time.monotonic()
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    receipt = {'unique_tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
               'skipped': len(result.skipped), 'wall_seconds': time.monotonic() - started,
               'status': 'PASS' if result.wasSuccessful() else 'FAIL',
               'failed_test_ids': [t.id() for t, _ in result.failures + result.errors],
               'research_acquisition_campaign_modules_outside_application_scope': sorted(CAMPAIGN_TESTS),
               'historical_Git_audit_classes_checked_via_frozen_receipt': sorted(HISTORICAL_AUDIT_CLASSES),
               'historical_Git_wrapper_tests_replaced_by_I2_runtime_checks': sorted(HISTORICAL_GIT_TESTS),
               'legacy_platform_fixture_tests_replaced_by_portable_fixture': sorted(PLATFORM_FIXTURE_TESTS)}
    (output / 'tests.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt), flush=True)
    if not result.wasSuccessful():
        raise RuntimeError('Combined application checks failed; see ' + str(output / 'tests.log'))
    return receipt


def export_examples(output):
    from epw_climate_analyzer.engine_application import (pilot_historical_request, run_historical_product,
                                                       run_future_pilot_product)
    from epw_climate_analyzer.engine_station_product import load_station_year_product
    expected = ige.verify_baseline()['example_EPW_sha256']
    products = {}
    with offline():
        runs = [('graz-historical-2023', lambda: run_historical_product(pilot_historical_request())),
                ('graz-future-ssp245-2040-2059', run_future_pilot_product),
                ('basel-historical-2025', lambda: load_station_year_product('CH:BAS')),
                ('altdorf-historical-2025', lambda: load_station_year_product('CH:ALT'))]
        for key, run in runs:
            print('Building ' + key, flush=True)
            product = run()
            epw = product.files['climate.epw']
            if sha256(epw).hexdigest() != expected[key] or len(product.dataset.data) != 8760:
                raise ValueError('Frozen example EPW or annual census changed: ' + key)
            if product.report['weather_provider_requests_this_run'] != 0 or product.report['production_ready']:
                raise ValueError('Unexpected example source or scientific status: ' + key)
            with zipfile.ZipFile(io.BytesIO(product.archive)) as z:
                if set(z.namelist()) != set(product.files) or len(z.namelist()) != len(product.files):
                    raise ValueError('Complete download member census changed')
                for name, data in product.files.items():
                    if z.read(name) != data:
                        raise ValueError('Complete download differs from UI file: ' + name)
            folder = output / key
            folder.mkdir()
            hashes = {}
            for name, data in product.files.items():
                path = folder / name
                if not path.resolve().is_relative_to(folder.resolve()):
                    raise ValueError('Invalid product file path')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                hashes[name] = sha256(data).hexdigest()
            (folder / 'complete-product.zip').write_bytes(product.archive)
            products[key] = {'records': len(product.dataset.data), 'calendar_mode': product.dataset.temporal.calendar_mode,
                             'EPW_sha256': sha256(epw).hexdigest(), 'file_sha256': hashes,
                             'complete_download_sha256': sha256(product.archive).hexdigest(),
                             'production_ready': False, 'weather_requests': 0}
    return products


def server_smoke(output):
    # Only loopback is used here. This is a real Streamlit process, separate
    # from AppTest; it does not open a weather-provider session or a browser.
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    url = 'http://127.0.0.1:' + str(port)
    with (output / 'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(ige.streamlit_command(port), cwd=ROOT, env=ige.child_environment(),
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        started = time.monotonic()
        try:
            while time.monotonic() - started < 45:
                if process.poll() is not None:
                    raise RuntimeError('Streamlit exited before becoming healthy; see server.log')
                try:
                    with urllib.request.urlopen(url + '/_stcore/health', timeout=2) as response:
                        health = response.read().decode()
                        if response.status != 200 or health.strip() != 'ok':
                            raise ValueError('Unexpected Streamlit health response')
                    with urllib.request.urlopen(url, timeout=2) as response:
                        page = response.read().decode()
                        if response.status != 200 or '<html' not in page.lower():
                            raise ValueError('Streamlit page unavailable')
                    return {'status': 'PASS', 'address': '127.0.0.1', 'HTTP_health': 200,
                            'HTTP_page': 200, 'startup_seconds': time.monotonic() - started,
                            'real_browser_visual_test': False}
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    time.sleep(.25)
            raise TimeoutError('Streamlit did not become healthy within 45 seconds')
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def verify(command, output):
    output.mkdir(parents=True, exist_ok=False)
    try:
        environment = ige.doctor()
        tests = run_tests(output) if command == 'check' else None
        products = export_examples(output)
        server = server_smoke(output) if command == 'check' else None
        receipt = {'schema': 'IGE_I2_REPRODUCIBLE_APPLICATION_v1', 'status': 'PASS',
                   'mode': command, 'environment': environment, 'tests': tests, 'products': products,
                   'actual_Streamlit_server': server, 'new_weather_provider_requests': 0,
                   'saved_CH_products_are_loaded_not_regenerated': True,
                   'scientific_methods_or_old_results_changed': False,
                   'independent_accuracy_qualified_by_this_check': False,
                   'EnergyPlus_run': False, 'production_ready': False}
        (output / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print('PASS. Four complete EPW/CSV/report downloads are in: ' + str(output), flush=True)
        return receipt
    except Exception as error:
        (output / 'failure.json').write_text(json.dumps({'status': 'FAIL', 'error': str(error)}, indent=2) + '\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'examples'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    verify(args.command, args.out)
