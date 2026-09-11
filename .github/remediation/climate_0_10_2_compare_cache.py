from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_PATH = ROOT / "tools" / "climate_analyzer" / "app.py"
TEST_PATH = ROOT / "tools" / "climate_analyzer" / "tests" / "test_global_catalog_map_contract.py"


def patch_app() -> None:
    app = APP_PATH.read_text(encoding="utf-8")

    cache_start_marker = '@st.cache_data(show_spinner=False)\ndef cached_station_catalog('
    cache_end_marker = '\n\n@st.cache_data(show_spinner=False)\ndef station_options_from_catalog'
    cache_start = app.find(cache_start_marker)
    cache_end = app.find(cache_end_marker, cache_start)
    if cache_start < 0 or cache_end < 0:
        raise RuntimeError("Expected CLIMATE-0.10.1 cache function boundaries not found; refusing blind patch")

    new_cache = '''@st.cache_data(show_spinner=False)
def _cached_station_catalog_by_identity(catalog_version: str, catalog_sha256: str) -> pd.DataFrame:
    """Load one reviewed catalog snapshot under an immutable cache identity."""
    catalog = load_production_station_catalog()
    if catalog.empty:
        return catalog

    actual_version = str(catalog["catalog_version"].iloc[0])
    actual_sha256 = str(catalog["catalog_sha256"].iloc[0])
    if actual_version != catalog_version or actual_sha256 != catalog_sha256:
        raise RuntimeError(
            "Station catalog cache identity mismatch: "
            f"expected {catalog_version}/{catalog_sha256}, "
            f"loaded {actual_version}/{actual_sha256}."
        )
    return catalog


def cached_station_catalog() -> pd.DataFrame:
    """Return the current reviewed catalog through a call-site-safe public API.

    The public helper is intentionally uncached and has no cache-key arguments.
    It reads the current manifest on every rerun and delegates to the internal
    cached function keyed by catalog version and byte-level SHA. This preserves
    stale-cache protection across redeploys without leaking cache mechanics into
    Find climate, Compare climates, or future UI call-sites.
    """
    manifest = load_station_catalog_manifest()
    return _cached_station_catalog_by_identity(manifest.catalog_version, manifest.csv_sha256)
'''
    app = app[:cache_start] + new_cache + app[cache_end:]

    old_find = '''    try:
        manifest = load_station_catalog_manifest()
        catalog = cached_station_catalog(manifest.catalog_version, manifest.csv_sha256)
    except Exception as exc:
'''
    new_find = '''    try:
        catalog = cached_station_catalog()
    except Exception as exc:
'''
    if old_find not in app:
        raise RuntimeError("Expected Find climate explicit-identity call not found; refusing blind patch")
    app = app.replace(old_find, new_find, 1)

    tree = ast.parse(app)
    public_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "cached_station_catalog"
    ]
    if len(public_calls) < 2:
        raise RuntimeError(f"Expected at least two catalog call-sites, found {len(public_calls)}")
    if any(node.args or node.keywords for node in public_calls):
        raise RuntimeError("A cached_station_catalog call-site still exposes cache identity arguments")

    APP_PATH.write_text(app, encoding="utf-8")


def patch_tests() -> None:
    tests = TEST_PATH.read_text(encoding="utf-8")
    if "import ast\n" not in tests:
        tests = tests.replace("import hashlib\n", "import ast\nimport hashlib\n", 1)

    start_marker = "    def test_station_catalog_cache_is_bound_to_manifest_identity(self) -> None:\n"
    end_marker = "    def test_global_map_default_capacity_covers_snapshot(self) -> None:\n"
    start = tests.find(start_marker)
    end = tests.find(end_marker, start)
    if start < 0 or end < 0:
        raise RuntimeError("Expected cache regression-test boundaries not found; refusing blind patch")

    replacement = '''    def test_station_catalog_cache_is_bound_to_manifest_identity(self) -> None:
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

'''
    tests = tests[:start] + replacement + tests[end:]
    TEST_PATH.write_text(tests, encoding="utf-8")


if __name__ == "__main__":
    patch_app()
    patch_tests()
    print("CLIMATE-0.10.2 compare-catalog cache remediation applied")
