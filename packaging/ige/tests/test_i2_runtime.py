from __future__ import annotations

from hashlib import sha256
from importlib import util
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import io
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import ige

spec = util.spec_from_file_location('ige_i2_verify', ROOT / 'packaging/ige/verify.py')
verify = util.module_from_spec(spec)
spec.loader.exec_module(verify)


class RuntimeContractTests(unittest.TestCase):
    def test_pinned_locks_have_hashes_and_no_editable_or_floating_requirement(self):
        versions = ige.locked_versions()
        self.assertGreater(len(versions), 40)
        for filename in ('bootstrap.lock', 'requirements.lock'):
            active = False
            hashes = 0
            for line in (ige.PACKAGE / filename).read_text().splitlines():
                if not line.strip() or line.startswith('#'):
                    continue
                if not line.startswith(' '):
                    if active:
                        self.assertGreater(hashes, 0)
                    self.assertRegex(line, r'^[A-Za-z0-9_.-]+==[^\s]+')
                    active, hashes = True, 0
                else:
                    self.assertRegex(line.strip(), r'^--hash=sha256:[0-9a-f]{64}')
                    hashes += 1
            self.assertGreater(hashes, 0)

    def test_child_environment_removes_injected_import_paths_and_preserves_user_home(self):
        with patch.dict('os.environ', {'PYTHONPATH':'injected', 'PYTHONHOME':'injected', 'HOME':'retained'}):
            env = ige.child_environment()
        self.assertNotIn('PYTHONPATH', env)
        self.assertNotIn('PYTHONHOME', env)
        self.assertEqual(env['HOME'], 'retained')
        self.assertEqual(env['PYTHONNOUSERSITE'], '1')

    def test_doctor_detects_version_drift_before_importing_application(self):
        dist = SimpleNamespace(metadata={'Name':'numpy'}, version='2.0.0')
        with patch.object(ige, 'locked_versions', return_value={'numpy':'1.26.4'}), \
             patch.object(ige.metadata, 'distributions', return_value=[dist]):
            with self.assertRaisesRegex(ValueError, 'Environment differs'):
                ige.doctor()

    def test_doctor_rejects_extra_packages_that_can_change_optional_import_behavior(self):
        distributions = [SimpleNamespace(metadata={'Name':n},version=v)
                         for n,v in [('numpy','1.26.4'),('numba','99.0')]]
        with patch.object(ige, 'locked_versions', return_value={'numpy':'1.26.4'}), \
             patch.object(ige.metadata, 'distributions', return_value=distributions):
            with self.assertRaisesRegex(ValueError, 'unexpected_packages'):
                ige.doctor()

    def test_baseline_detects_corruption_and_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'source').write_bytes(b'original')
            (root/'baseline.json').write_text(json.dumps({'files_sha256':{'source':sha256(b'original').hexdigest()}}))
            with patch.object(ige,'ROOT',root), patch.object(ige,'PACKAGE',root):
                ige.verify_baseline()
                (root/'source').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'changed'):ige.verify_baseline()
                (root/'source').unlink()
                with self.assertRaisesRegex(ValueError,'missing'):ige.verify_baseline()

    def test_baseline_rejects_path_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'baseline.json').write_text(json.dumps({'files_sha256':{'../outside':'0'*64}}))
            with patch.object(ige,'ROOT',root), patch.object(ige,'PACKAGE',root):
                with self.assertRaisesRegex(ValueError,'missing'):ige.verify_baseline()

    def test_setup_never_takes_over_unmarked_existing_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(ige,'ENV',root), patch.object(ige,'MARKER',root/'absent'), \
                 patch.object(ige.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'without an IGE marker'):ige.setup()
                run.assert_not_called()

    def test_server_command_uses_actual_entrypoint_and_loopback(self):
        command = ige.streamlit_command(8512)
        self.assertEqual(command[:3],[sys.executable,'-m','streamlit'])
        self.assertIn(str(ROOT/'tools/climate_analyzer/app.py'),command)
        self.assertIn('--server.address=127.0.0.1',command)
        self.assertIn('--server.port=8512',command)

    def test_default_runs_have_different_paths_and_do_not_write_old_results(self):
        first, second = ige.default_output('check'), ige.default_output('check')
        self.assertNotEqual(first,second)
        self.assertTrue(first.is_relative_to(ROOT/'.epw_climate_analyzer/ige-runs'))

    def test_weather_sockets_are_forbidden_inside_offline_context(self):
        with verify.offline(), socket.socket() as s:
            with self.assertRaisesRegex(RuntimeError,'I2_OFFLINE'):
                s.connect(('127.0.0.1',9))
            with self.assertRaisesRegex(RuntimeError,'I2_OFFLINE'):
                s.connect_ex(('127.0.0.1',9))

    def test_server_is_terminated_on_failed_startup(self):
        process=Mock()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(verify.subprocess,'Popen',return_value=process), \
             patch.object(verify.time,'monotonic',side_effect=[0,46]):
            with self.assertRaises(TimeoutError):verify.server_smoke(Path(directory))
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileExistsError):verify.verify('examples',Path(directory))

    def test_frozen_exposure_receipt_preserves_historical_limits_without_Git_history(self):
        name='research/ige_cmip6/a12_exposure_audit_20261025.json'
        manifest=ige.verify_baseline()
        self.assertIn(name,manifest['files_sha256'])
        audit=json.loads((ROOT/name).read_text(encoding='utf-8'))
        self.assertFalse(audit['strict_blindness_certified'])
        self.assertFalse(audit['independent_accuracy_qualified'])
        self.assertFalse(audit['IV1_2022_values_opened'])
        for key in ('CH:BAS','CH:ALT'):
            self.assertFalse(audit['targets'][key]['raw_byte_unseen_claim_allowed'])
            self.assertFalse(audit['targets'][key]['temperature_2025_prediction_errors_or_fitting_demonstrated'])

    def test_legacy_archive_reader_rejects_real_unsafe_headers_on_both_platforms(self):
        import e2e_integration_audit as audit
        for names in (('../escape.txt',),('/absolute.txt',),('a\\b',),('same.txt','same.txt')):
            raw=io.BytesIO()
            with warnings.catch_warnings(),zipfile.ZipFile(raw,'w') as archive:
                warnings.simplefilter('ignore',UserWarning)
                for name in names:
                    # ZipInfo(name) normalizes backslashes on Windows. Set the
                    # actual header afterward so the adversarial input is real.
                    info=zipfile.ZipInfo('placeholder');info.filename=name
                    archive.writestr(info,b'ARTIFICIAL')
            with self.assertRaisesRegex(ValueError,'UNSAFE_OR_DUPLICATED'):
                audit.zip_bodies(raw.getvalue())


if __name__=='__main__':unittest.main()
