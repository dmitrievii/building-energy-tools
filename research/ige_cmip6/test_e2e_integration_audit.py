"""I/O and provenance guard tests; meteorological calculations are unchanged."""
import io
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

import e2e_integration_audit as audit


class ReplayBoundaryControls(unittest.TestCase):
    def test_changed_source_packet_cannot_be_admitted(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); packet = root/'changed.zip'
            packet.write_bytes(b'UNREGISTERED_ARTIFICIAL_PACKET')
            with self.assertRaisesRegex(ValueError, 'ORIGINAL_REPLAY_PACKET_CHANGED'):
                audit.original_inputs(packet, root/'out')
            self.assertFalse((root/'out').exists())

    def test_prior_result_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); old = root/'existing'; old.mkdir()
            proof = old/'proof.txt'; proof.write_bytes(b'ORIGINAL_RESULT')
            with self.assertRaisesRegex(FileExistsError, 'NO_OVERWRITE'):
                audit.audit(root/'not_opened.zip', old)
            self.assertEqual(proof.read_bytes(), b'ORIGINAL_RESULT')

    def test_duplicate_and_traversing_archive_names_rejected(self):
        for names in (('../escape.txt',), ('/absolute.txt',), ('a\\b',), ('same.txt', 'same.txt')):
            raw = io.BytesIO()
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(raw, 'w') as archive:
                    for name in names:
                        archive.writestr(name, b'ARTIFICIAL')
            with self.assertRaisesRegex(ValueError, 'UNSAFE_OR_DUPLICATED'):
                audit.zip_bodies(raw.getvalue())

    def test_expanded_archive_budget_is_enforced_before_read(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('bounded.bin', b'0'*1024)
        with self.assertRaisesRegex(ValueError, 'ARCHIVE_BUDGET'):
            audit.zip_bodies(raw.getvalue(), limit=1023)


if __name__ == '__main__':
    unittest.main()
