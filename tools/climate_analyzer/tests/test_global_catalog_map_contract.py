from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.climate_sources import _infer_metadata_from_url


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
DATA_DIR = ROOT / "epw_climate_analyzer" / "data"
CATALOG_PATH = DATA_DIR / "station_catalog.csv"
MANIFEST_PATH = DATA_DIR / "station_catalog.meta.json"


class GlobalCatalogMapContractTests(unittest.TestCase):
    def test_leaflet_owns_pan_and_zoom(self) -> None:
        app = APP_PATH.read_text(encoding="utf-8")
        self.assertIn('returned_objects=["last_object_clicked_tooltip"]', app)
        self.assertNotIn('returned_objects=["last_object_clicked_tooltip", "center", "zoom", "bounds"]', app)
        self.assertNotIn("update_station_map_view_state(map_state)", app)
        self.assertIn("station_map_view_epoch", app)
        self.assertIn("climate_onebuilding_selectable_cluster_map_", app)

    def test_station_catalog_cache_is_bound_to_manifest_identity(self) -> None:
        app = APP_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "def _cached_station_catalog_by_identity(catalog_version: str, catalog_sha256: str)",
            app,
        )
        self.assertIn("def cached_station_catalog() -> pd.DataFrame:", app)
        self.assertIn("manifest = load_station_catalog_manifest()", app)
        self.assertIn(
            "return _cached_station_catalog_by_identity(manifest.catalog_version, manifest.csv_sha256)",
            app,
        )

        tree = ast.parse(app)
        public_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "cached_station_catalog"
        ]
        self.assertGreaterEqual(len(public_calls), 2)
        self.assertTrue(all(not node.args and not node.keywords for node in public_calls))

    def test_global_map_default_capacity_covers_snapshot(self) -> None:
        app = APP_PATH.read_text(encoding="utf-8")
        self.assertIn('station_selectable_cluster_limit", 50000', app)
        self.assertIn("max_value=100000", app)

        catalog = pd.read_csv(CATALOG_PATH, usecols=["name", "country", "latitude", "longitude"])
        catalog["latitude"] = pd.to_numeric(catalog["latitude"], errors="coerce").round(4)
        catalog["longitude"] = pd.to_numeric(catalog["longitude"], errors="coerce").round(4)
        groups = catalog.dropna(subset=["latitude", "longitude"]).drop_duplicates(
            subset=["country", "name", "latitude", "longitude"]
        )
        self.assertLessEqual(len(groups), 50000)

    def test_global_snapshot_has_complete_logical_coverage(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        csv_bytes = CATALOG_PATH.read_bytes()
        evidence = manifest["build_evidence"]

        self.assertEqual(manifest["catalog_kind"], "generated_provider_snapshot")
        self.assertGreater(manifest["station_count"], 20000)
        self.assertEqual(len(evidence["regions"]), 7)
        self.assertEqual(evidence["failed_catalogs"], 0)
        self.assertEqual(
            evidence.get("source_file_failures", 0),
            evidence.get("recovered_source_file_failures", 0),
        )
        self.assertEqual(hashlib.sha256(csv_bytes).hexdigest(), manifest["csv_sha256"])

    def test_country_metadata_is_country_level(self) -> None:
        countries = set(pd.read_csv(CATALOG_PATH, usecols=["country"])["country"].dropna().astype(str))
        self.assertLessEqual(len(countries), 300)
        for known_bad_subdivision in ("AB_Alberta", "TX_Texas", "NSW_New_South_Wales"):
            self.assertNotIn(known_bad_subdivision, countries)

    def test_url_fallback_prefers_three_letter_country_code_from_filename(self) -> None:
        examples = {
            "https://climate.onebuilding.org/x/CAN/AB_Alberta/CAN_AB_Calgary.Intl.AP_718770_CWEC.zip": "CAN",
            "https://climate.onebuilding.org/x/USA/TX_Texas/USA_TX_Austin-Bergstrom.Intl.AP_722540_TMYx.zip": "USA",
            "https://climate.onebuilding.org/x/AUS/NSW_New_South_Wales/AUS_NSW_Sydney.Observatory.Hill_947680_RMY.zip": "AUS",
        }
        for url, expected in examples.items():
            with self.subTest(url=url):
                metadata = _infer_metadata_from_url(pd.Series({"download_url": url}))
                self.assertEqual(metadata["country"], expected)


if __name__ == "__main__":
    unittest.main()
