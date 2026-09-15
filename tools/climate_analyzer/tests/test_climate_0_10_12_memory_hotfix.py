from __future__ import annotations

import ast
from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.catalog_runtime import (
    RUNTIME_CATALOG_COLUMNS,
    load_production_station_catalog,
    load_station_catalog_manifest,
)
from epw_climate_analyzer.climate_sources import filter_station_catalog


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
CATALOG_RUNTIME_PATH = ROOT / "epw_climate_analyzer" / "catalog_runtime.py"
LIVE_AUDIT_PATH = ROOT.parents[1] / "deployment" / "live_browser_audit.mjs"


class CommunityCloudMemoryHotfixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_production_station_catalog()
        cls.manifest = load_station_catalog_manifest()

    def test_runtime_projection_preserves_full_catalog_identity(self) -> None:
        self.assertEqual(len(self.catalog), self.manifest.station_count)
        self.assertEqual(len(self.catalog), 98047)
        self.assertTrue(set(RUNTIME_CATALOG_COLUMNS).issubset(self.catalog.columns))
        self.assertNotIn("catalog_url", self.catalog.columns)
        self.assertNotIn("notes", self.catalog.columns)
        self.assertEqual(str(self.catalog["catalog_version"].iloc[0]), self.manifest.catalog_version)
        self.assertEqual(str(self.catalog["catalog_sha256"].iloc[0]), self.manifest.csv_sha256)

    def test_runtime_dataframe_memory_is_bounded(self) -> None:
        deep_bytes = int(self.catalog.memory_usage(index=True, deep=True).sum())
        print(f"runtime station catalog deep memory: {deep_bytes / 1024 / 1024:.1f} MiB")
        self.assertLess(deep_bytes, 128 * 1024 * 1024)

    def test_low_cardinality_columns_are_categorical(self) -> None:
        for column in (
            "country",
            "region",
            "source",
            "dataset",
            "catalog_version",
            "catalog_sha256",
        ):
            self.assertIsInstance(self.catalog[column].dtype, pd.CategoricalDtype)

    def test_no_filter_path_is_zero_copy(self) -> None:
        filtered = filter_station_catalog(self.catalog)
        self.assertIs(filtered, self.catalog)

    def test_large_catalog_uses_resource_cache_not_data_cache(self) -> None:
        app = APP_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "@st.cache_resource(show_spinner=False, max_entries=1)\n"
            "def _cached_station_catalog_by_identity",
            app,
        )
        self.assertNotIn(
            "@st.cache_data(show_spinner=False)\n"
            "def _cached_station_catalog_by_identity",
            app,
        )
        self.assertNotIn(
            "@st.cache_data(show_spinner=False)\n"
            "def grouped_station_catalog",
            app,
        )
        self.assertIn(
            "station_group_options_from_groups(station_groups_all, limit=10000)",
            app,
        )

    def test_production_loader_does_not_run_maintenance_normalizer(self) -> None:
        source = CATALOG_RUNTIME_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "load_production_station_catalog"
        )
        calls = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("load_station_catalog", calls)
        self.assertIn("_read_promoted_runtime_catalog", calls)

    def test_live_audit_reports_resource_limit_directly(self) -> None:
        audit = LIVE_AUDIT_PATH.read_text(encoding="utf-8")
        self.assertIn("Streamlit resource-limit page detected", audit)


if __name__ == "__main__":
    unittest.main()
