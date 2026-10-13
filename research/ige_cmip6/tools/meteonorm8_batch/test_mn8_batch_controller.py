"""Unit tests for IGE Meteonorm 8 batch orchestrator; synthetic inputs only."""
import csv
import datetime
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("mn8_batch_controller.py")
spec = importlib.util.spec_from_file_location("mn8_batch_controller", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fake_epw(path, *, lat=46.983, lon=15.45, elev=342, duplicate=False):
    head = [["LOCATION", "Graz", "-", "AUT", "SYNTHETIC", "00000",
             str(lat), str(lon), "1", str(elev)]]
    head.extend([["COMMENTS 1"]] * 7)
    rows = []
    for day in range(365):
        date = datetime.date(2005, 1, 1) + datetime.timedelta(days=day)
        for hour in range(1, 25):
            data = ["2005", str(date.month), str(date.day), str(hour), "60", "SYNTHETIC",
                    "12", "5", "63", "97000", "0", "0", "300", "0", "0", "0",
                    "0", "0", "0", "9999", "180", "2", "5", "4", "9999", "99999",
                    "9", "999999999", "10", "0.15", "0", "0", "0.2", "0", "99"]
            rows.append(data)
    if duplicate:
        rows[-1] = rows[-2].copy()
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(head + rows)


class BatchContracts(unittest.TestCase):
    def test_valid_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.epw"
            fake_epw(p)
            result = mod.verify_epw(p)
            self.assertEqual(result["hour_count"], 8760)
            self.assertEqual(result["field_count"], 35)
            self.assertFalse(result["has_qc_flags"])

    def test_duplicate_hour_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.epw"
            fake_epw(p, duplicate=True)
            with self.assertRaisesRegex(ValueError, "Repeated"):
                mod.verify_epw(p)

    def test_header_site_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.epw"
            fake_epw(p, lat=37.53, lon=22.41)
            info = mod.verify_epw(p)
            self.assertEqual(mod.match_site(info, mod.DEFAULT_SITES, 0.025)["id"], "tripoli_greece")
            self.assertNotEqual(mod.match_site(info, mod.DEFAULT_SITES, 0.025)["id"], "graz")

    def test_baseline_site_match(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.epw"
            fake_epw(p)
            self.assertEqual(mod.match_site(mod.verify_epw(p), mod.DEFAULT_SITES, 0.025)["id"], "graz")

    def test_project_fails_closed_without_export(self):
        with tempfile.TemporaryDirectory() as td:
            mod.create_project(Path(td) / "pilot")
            self.assertEqual(mod.verify_project(Path(td) / "pilot"), 2)
            report = json.loads((Path(td) / "pilot" / "verification_report.json").read_text())
            self.assertFalse(report["complete"])
            self.assertEqual(report["n_expected"], 60)

    def test_documented_import_layout(self):
        with tempfile.TemporaryDirectory() as td:
            mod.create_project(Path(td) / "pilot")
            directory = Path(td) / "pilot" / "batch_input"
            p = directory / "pilot_one_graz_tabs.txt"
            payload = p.read_bytes()
            self.assertTrue(payload.isascii())
            self.assertIn(b"\r\n", payload)
            lines = payload.decode("ascii").splitlines()
            self.assertEqual(lines[0], "Formattyp = 22")
            self.assertEqual(lines[1], "Save = hour")
            self.assertEqual(lines[2].split("\t"),
                             ["name", "longitude", "latitude", "altitude"])
            self.assertEqual(lines[3].split("\t"),
                             ["IGE_Graz", "15.450000", "46.983000", "342"])
            self.assertEqual(len(lines), 4)
            self.assertNotIn("situation", payload.decode("ascii"))
            five = (directory / "locations_5_tabs.txt").read_text(encoding="ascii")
            self.assertEqual(len(five.splitlines()), 3 + len(mod.DEFAULT_SITES))
            self.assertEqual(five.splitlines()[2], lines[2])
            fallback = (directory / "locations_5_semicolon.csv").read_text(encoding="ascii")
            self.assertEqual(fallback.splitlines()[2].split(";"),
                             ["name", "longitude", "latitude", "altitude"])

    def test_native_user_defined_import_matches_installed_mn82_example(self):
        with tempfile.TemporaryDirectory() as td:
            mod.create_project(Path(td) / "pilot")
            d = Path(td) / "pilot" / "batch_input"
            one = (d / "native_user_defined_one_graz.csv").read_bytes()
            five = (d / "native_user_defined_five_sites.csv").read_bytes()
            self.assertTrue(one.startswith(b"\xef\xbb\xbfname;latitude;longitude\r\n"))
            self.assertIn(b'"IGE_Graz";46.983000;15.450000\r\n', one)
            self.assertEqual(len(one.decode("utf-8-sig").splitlines()), 3)
            self.assertEqual(len(five.decode("utf-8-sig").splitlines()), 7)
            self.assertNotIn(b"Formattyp", one)
            self.assertNotIn(b"altitude", one)
            self.assertNotIn(b"Save = hour", one)

    def test_regenerated_import_files_replace_old_layout(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "pilot"
            mod.create_project(folder)
            inp = folder / "batch_input" / "locations_format22.csv"
            inp.write_text("INVALID OLD DATA", encoding="utf-8")
            mod.create_project(folder)
            now = inp.read_text(encoding="ascii")
            self.assertTrue(now.startswith("Formattyp = 22\nSave = hour\n"))
            self.assertIn("name;longitude;latitude;altitude",now)
            self.assertNotIn("situation",now)

    def test_id_validation(self):
        config = {"sites": [dict(mod.DEFAULT_SITES[0], id="unsafe path/hi")],
                  "scenarios": ["contemporary"], "seeds": [1]}
        with self.assertRaises(ValueError):
            mod.valid_config(config)

    def test_seed_range_validation(self):
        config = {"sites": mod.DEFAULT_SITES, "scenarios": ["contemporary"], "seeds": [100]}
        with self.assertRaises(ValueError):
            mod.valid_config(config)

    def test_no_overwrite_of_user_config(self):
        with tempfile.TemporaryDirectory() as td:
            pilot = Path(td) / "pilot"
            mod.create_project(pilot)
            p = pilot / "project_config.json"
            original = p.read_bytes()
            mod.create_project(pilot)
            self.assertEqual(original, p.read_bytes())

    def test_incomplete_epw_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.epw"
            p.write_text("LOCATION,Graz\n")
            with self.assertRaises(ValueError):
                mod.verify_epw(p)

    def test_qc_only_flags_does_not_mutate_provider(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.epw"
            fake_epw(p)
            s0 = mod.sha256(p)
            mod.verify_epw(p)
            self.assertEqual(s0, mod.sha256(p))

    def test_no_claim_of_future_climate_validation(self):
        with tempfile.TemporaryDirectory() as td:
            pilot = Path(td) / "pilot"
            mod.create_project(pilot)
            mod.verify_project(pilot)
            report = json.loads((pilot / "verification_report.json").read_text())
            self.assertFalse(report["meteorological_benchmark_validated"])


if __name__ == "__main__":
    unittest.main()
