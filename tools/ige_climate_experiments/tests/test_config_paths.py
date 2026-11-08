"""Windows configuration diagnostics and dependency-free preflight checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ige_local.common import InputError, load_config, read_config_json, read_json, write_json
from ige_auto.config import load as load_auto


class ConfigPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="IGE User Folder Климат ")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.database = self.base/"Database"
        self.database.mkdir()
        (self.database/"source.txt").write_text("immutable test input", encoding="utf-8")
        self.configs = []
        for name, folder, runner, loader in (
            ("config_E0_E10.json", "IGE_Climate_Experiments_E0_E10_v0_1_0", "ige_experiments.py", load_config),
            ("config_auto_regression.json", "IGE_Automatic_Regression_v0_1_0", "ige_regression.py", load_auto),
        ):
            path = self.base/folder/name
            write_json(path, read_json(ROOT/name))
            self.configs.append((path, runner, loader))

    def cli(self, runner, path, command="check-config"):
        env = {**os.environ, "PYTHONUTF8": "1"}
        # -S removes third-party site packages. Preflight must not import NumPy.
        return subprocess.run([sys.executable, "-S", str(ROOT/runner), command, "--config", str(path)],
                              cwd=self.base, env=env, capture_output=True, encoding="utf-8", timeout=30)

    def test_both_sibling_layouts_resolve_same_database(self):
        for path, runner, loader in self.configs:
            with self.subTest(runner=runner):
                result = loader(path)
                self.assertEqual(Path(result["database"]), self.database)
                self.assertFalse(Path(result["results"]).exists())

    def test_absolute_forward_slash_paths_are_valid(self):
        for path, runner, loader in self.configs:
            with self.subTest(runner=runner):
                c = read_json(path); c["database"] = self.database.as_posix(); write_json(path, c)
                self.assertEqual(Path(loader(path)["database"]), self.database)

    def test_invalid_windows_escape_names_config_and_location(self):
        for path, runner, loader in self.configs:
            with self.subTest(runner=runner):
                raw = path.read_text(encoding="utf-8").replace("../Database", r"E:\User Folder\Climate\Database")
                path.write_text(raw, encoding="utf-8")
                before = path.read_bytes()
                with self.assertRaises(InputError) as error:
                    loader(path)
                message = str(error.exception)
                self.assertIn(str(path), message)
                self.assertIn("line 3", message)
                self.assertIn("column", message)
                self.assertIn("../Database", message)
                self.assertEqual(path.read_bytes(), before)

    def test_legal_json_escapes_cannot_silently_change_paths(self):
        path = self.base/"control.json"
        for field in ("database", "results"):
            for escaped in (r"C:\temp\new", r"C:\reports", r"C:\backup"):
                with self.subTest(field=field, path=escaped):
                    other = '"database":"../Database","results":"./results"'
                    raw = '{'+other+'}'
                    old = '"'+field+'":"'+("../Database" if field == "database" else "./results")+'"'
                    raw = raw.replace(old, '"'+field+'":"'+escaped+'"')
                    path.write_text(raw, encoding="utf-8")
                    with self.assertRaisesRegex(InputError, "control character"):
                        read_config_json(path)

    def test_correctly_doubled_windows_backslashes_are_preserved(self):
        path = self.base/"correctly_escaped.json"
        value = {"database": r"E:\User Folder\Климат\Database", "results": r"E:\Other\results"}
        write_json(path, value)
        self.assertEqual(read_config_json(path), value)

    def test_preflight_works_without_site_packages_and_writes_nothing(self):
        for path, runner, _ in self.configs:
            with self.subTest(runner=runner):
                before = {str(p): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
                result = self.cli(runner, path)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                report = json.loads(result.stdout)
                self.assertTrue(report["configuration_valid"])
                self.assertEqual(Path(report["database"]), self.database)
                after = {str(p): p.read_bytes() for p in self.base.rglob("*") if p.is_file()}
                self.assertEqual(before, after)
                self.assertFalse(Path(report["results"]).exists())

    def test_bad_config_run_fails_before_dependencies_or_results(self):
        for path, runner, _ in self.configs:
            with self.subTest(runner=runner):
                path.write_text(path.read_text(encoding="utf-8").replace("../Database", r"E:\User Folder\Database"), encoding="utf-8")
                result = self.cli(runner, path, "run")
                self.assertEqual(result.returncode, 2)
                self.assertIn("Invalid JSON configuration", result.stdout)
                self.assertNotIn("Dependency unavailable", result.stdout)
                self.assertFalse((path.parent/"results").exists())
                self.assertFalse((path.parent/"regression_results").exists())

    def test_missing_comma_is_reported_without_changing_file(self):
        path, _, loader = self.configs[0]
        path.write_text(path.read_text(encoding="utf-8").replace('"../Database",', '"../Database"'), encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaisesRegex(InputError, "Keep a comma"):
            loader(path)
        self.assertEqual(path.read_bytes(), before)

    def test_utf8_bom_remains_supported(self):
        path, _, loader = self.configs[0]
        path.write_bytes(b"\xef\xbb\xbf"+path.read_bytes())
        self.assertEqual(Path(loader(path)["database"]), self.database)

    def test_native_data_json_reader_is_not_relaxed(self):
        path = self.base/"invalid_native_plan.json"
        path.write_text(r'{"database":"E:\User Folder"}', encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            read_json(path)


if __name__ == "__main__":
    unittest.main()
