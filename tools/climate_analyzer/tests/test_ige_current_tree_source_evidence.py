"""Regression for exact frozen evidence versus reviewed current-tree compatibility."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location(
    "ige_cloud_source_evidence",ROOT/"deployment"/"verify_ige_cloud_candidate.py")
gate=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class SourceEvidenceTests(unittest.TestCase):
    def test_frozen_and_current_source_contracts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            path=Path("manifest.json")
            old={"app.py":b"old application","weather.zip":b"frozen observations"}
            manifest=json.dumps({"source_sha256":{
                name:hashlib.sha256(value).hexdigest() for name,value in old.items()
            }}).encode()
            for name,value in old.items():(root/name).write_bytes(value)
            (root/path).write_bytes(manifest)
            frozen={**old,str(path):manifest}
            with patch.object(gate,"ROOT",root), \
                 patch.object(gate,"FROZEN_F1_CONTRACT",path), \
                 patch.object(gate,"CURRENT_COMPATIBILITY_PATHS",frozenset({"app.py"})), \
                 patch.object(gate,"_git_bytes",side_effect=lambda commit,p:frozen[str(p)]), \
                 patch.object(gate.subprocess,"check_output",return_value="current-commit\n"):
                _,exact=gate.source_evidence(path)
                self.assertEqual(exact["mode"],"FROZEN_EXACT_CANDIDATE")
                self.assertEqual(exact["reviewed_changed_paths"],[])
                (root/"app.py").write_bytes(b"new application")
                with self.assertRaisesRegex(AssertionError,"Unreviewed source change"):
                    gate.source_evidence(path)
                _,current=gate.source_evidence(path,current_tree=True)
                self.assertEqual(current["mode"],"CURRENT_TREE_OFFLINE_COMPATIBILITY")
                self.assertEqual(current["unchanged_current_entries"],1)
                self.assertEqual([v["path"] for v in current["reviewed_changed_paths"]],["app.py"])
                self.assertEqual(current["current_sha256"]["app.py"],hashlib.sha256(b"new application").hexdigest())
                self.assertEqual((root/path).read_bytes(),manifest)
                (root/"weather.zip").write_bytes(b"changed observations")
                with self.assertRaisesRegex(AssertionError,"Unreviewed source change: weather.zip"):
                    gate.source_evidence(path,current_tree=True)
                (root/"weather.zip").write_bytes(old["weather.zip"])
                frozen["app.py"]=b"tampered historical release"
                with self.assertRaisesRegex(AssertionError,"Historical release evidence mismatch"):
                    gate.source_evidence(path,current_tree=True)
                frozen["app.py"]=old["app.py"]
                (root/path).write_bytes(manifest+b" ")
                with self.assertRaisesRegex(AssertionError,"Frozen release manifest changed"):
                    gate.source_evidence(path,current_tree=True)


if __name__=="__main__":
    unittest.main()
