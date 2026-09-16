from __future__ import annotations

import json
from pathlib import Path
import unittest

from epw_climate_analyzer.catalog_runtime import load_station_catalog_manifest
from epw_climate_analyzer.station_group_snapshot import (
    MANIFEST_PATH,
    SNAPSHOT_PATH,
    load_station_group_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


class OneBuildingMapCacheContractTests(unittest.TestCase):
    def test_snapshot_is_bound_to_current_reviewed_catalog(self) -> None:
        catalog_manifest = load_station_catalog_manifest()
        snapshot_meta = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(snapshot_meta["catalog_version"], catalog_manifest.catalog_version)
        self.assertEqual(snapshot_meta["catalog_sha256"], catalog_manifest.csv_sha256)
        self.assertGreater(snapshot_meta["station_group_count"], 20_000)
        self.assertTrue(SNAPSHOT_PATH.exists())

        groups = load_station_group_snapshot(catalog_manifest.catalog_version, catalog_manifest.csv_sha256)
        self.assertEqual(len(groups), snapshot_meta["station_group_count"])
        self.assertFalse(groups["station_group_id"].astype(str).duplicated().any())

    def test_world_map_uses_snapshot_and_cached_folium_resource(self) -> None:
        app = APP_PATH.read_text(encoding="utf-8")
        self.assertIn("def _cached_station_group_snapshot(", app)
        self.assertIn("def _cached_grouped_station_catalog(", app)
        self.assertIn("def _cached_station_map_resource(", app)
        self.assertIn("def _cached_station_group_options(", app)
        self.assertIn("uses_full_catalog_snapshot", app)
        self.assertIn("_cached_station_group_snapshot(catalog_version, catalog_sha256)", app)
        self.assertIn("_cached_station_map_resource(", app)
        self.assertIn("filtered_catalog = catalog", app)

    def test_snapshot_loader_is_lazy_map_dependency(self) -> None:
        app = APP_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "from epw_climate_analyzer.station_group_snapshot import load_station_group_snapshot",
            app,
        )
        self.assertIn("global load_station_group_snapshot", app)


if __name__ == "__main__":
    unittest.main()
