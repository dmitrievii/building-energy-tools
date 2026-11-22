import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from epw_climate_analyzer import persistent_app_runtime as r

class PersistentAppTests(unittest.TestCase):
    def test_code_module_is_reused_and_source_changes_fail_closed(self):
        with tempfile.TemporaryDirectory() as d, patch.object(r,"_MODULE",None),patch.object(r,"_TOKEN",None),patch.dict("sys.modules"):
            p=Path(d)/"app.py"
            p.write_text("def calculate(x):\n    return x+1\n")
            a=r.load_app(p)
            b=r.load_app(p)
            self.assertIs(a,b)
            self.assertIs(a.calculate,b.calculate)
            self.assertEqual(b.calculate(5),6)
            p.write_text("def calculate(x):\n    return x+100\n")
            with self.assertRaisesRegex(RuntimeError,"source changed"):
                r.load_app(p)
    def test_persistent_candidate_does_not_default_on(self):
        with patch.dict("os.environ",{},clear=True):
            self.assertFalse(r.status()["enabled"])
