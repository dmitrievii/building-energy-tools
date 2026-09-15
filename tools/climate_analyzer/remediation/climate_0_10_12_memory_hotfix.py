from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "tools/climate_analyzer/app.py"
CATALOG_RUNTIME = ROOT / "tools/climate_analyzer/epw_climate_analyzer/catalog_runtime.py"
CLIMATE_SOURCES = ROOT / "tools/climate_analyzer/epw_climate_analyzer/climate_sources.py"
LIVE_AUDIT = ROOT / "deployment/live_browser_audit.mjs"
TEST_PATH = ROOT / "tools/climate_analyzer/tests/test_climate_0_10_12_memory_hotfix.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, *, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_index] + replacement.rstrip() + "\n\n\n" + text[end_index:]


def patch_catalog_runtime() -> None:
    text = CATALOG_RUNTIME.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from urllib.parse import urlparse\n\nimport pandas as pd\n\nfrom .climate_sources import CATALOG_PATH, load_station_catalog\n",
        "import pandas as pd\n\nfrom .climate_sources import CATALOG_PATH\n",
        label="catalog-runtime-imports",
    )

    replacement = r'''RUNTIME_CATALOG_COLUMNS = [
    "station_id",
    "name",
    "country",
    "region",
    "source",
    "dataset",
    "latitude",
    "longitude",
    "elevation_m",
    "download_url",
]

_RUNTIME_STRING_DTYPES = {
    "station_id": "string",
    "name": "string",
    "country": "category",
    "region": "category",
    "source": "category",
    "dataset": "category",
    "download_url": "string",
}


def _read_promoted_runtime_catalog(path: Path) -> pd.DataFrame:
    """Read only columns required by the public runtime.

    The full reviewed CSV remains the auditable maintenance artifact. Runtime
    deliberately omits maintenance-only ``catalog_url`` and ``notes`` columns
    and does not re-run crawler normalization over an already promoted snapshot.
    Integrity is established by the manifest SHA before this function is called.
    """
    header = pd.read_csv(path, nrows=0)
    missing = [column for column in RUNTIME_CATALOG_COLUMNS if column not in header.columns]
    if missing:
        raise RuntimeError(
            "Bundled station catalog is missing runtime columns: " + ", ".join(missing)
        )

    catalog = pd.read_csv(
        path,
        usecols=RUNTIME_CATALOG_COLUMNS,
        dtype=_RUNTIME_STRING_DTYPES,
        low_memory=False,
    )

    for column in ("station_id", "name", "download_url"):
        catalog[column] = catalog[column].str.strip()
        if catalog[column].isna().any() or catalog[column].eq("").any():
            raise RuntimeError(f"Bundled station catalog contains empty {column} values.")

    for column in ("country", "region", "source", "dataset"):
        normalized = catalog[column].astype("string").fillna("").str.strip()
        catalog[column] = normalized.astype("category")

    for column in ("latitude", "longitude", "elevation_m"):
        catalog[column] = pd.to_numeric(catalog[column], errors="coerce")
    if catalog["latitude"].isna().any() or catalog["longitude"].isna().any():
        raise RuntimeError("Bundled station catalog contains invalid station coordinates.")
    if not catalog["latitude"].between(-90.0, 90.0).all():
        raise RuntimeError("Bundled station catalog contains latitude outside [-90, 90].")
    if not catalog["longitude"].between(-180.0, 180.0).all():
        raise RuntimeError("Bundled station catalog contains longitude outside [-180, 180].")

    approved = catalog["download_url"].str.match(
        r"^https://climate\.onebuilding\.org(?:/|$)", case=False, na=False
    )
    if not bool(approved.all()):
        bad_url = str(catalog.loc[~approved, "download_url"].iloc[0])
        raise RuntimeError(f"Bundled station catalog contains a non-approved download URL: {bad_url}")
    return catalog


def _add_manifest_runtime_columns(catalog: pd.DataFrame, manifest: StationCatalogManifest) -> None:
    """Attach low-cardinality provenance columns without duplicating string payloads."""
    values = {
        "catalog_version": manifest.catalog_version,
        "catalog_kind": manifest.catalog_kind,
        "catalog_generated_at_utc": manifest.generated_at_utc,
        "catalog_source_snapshot_date": manifest.source_snapshot_date,
        "catalog_sha256": manifest.csv_sha256,
        "catalog_provider": manifest.provider_name,
        "catalog_provider_sources_url": manifest.provider_sources_url,
    }
    for column, value in values.items():
        catalog[column] = pd.Series(value, index=catalog.index, dtype="category")


def load_production_station_catalog(
    catalog_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> pd.DataFrame:
    """Load the reviewed catalog snapshot with a bounded-memory runtime projection."""
    resolved_catalog = Path(catalog_path) if catalog_path is not None else CATALOG_PATH
    manifest = load_station_catalog_manifest(manifest_path)

    actual_sha = _sha256_file(resolved_catalog)
    if actual_sha != manifest.csv_sha256:
        raise RuntimeError(
            "Bundled station catalog integrity check failed: "
            f"manifest SHA-256={manifest.csv_sha256}, actual SHA-256={actual_sha}."
        )

    # The SHA-locked CSV has already passed crawler normalization and review.
    # Re-running the maintenance normalizer here created several simultaneous
    # 98k-row object DataFrames and was the main Community Cloud memory spike.
    catalog = _read_promoted_runtime_catalog(resolved_catalog)
    if len(catalog) != manifest.station_count:
        raise RuntimeError(
            "Bundled station catalog record-count check failed: "
            f"manifest={manifest.station_count}, runtime catalog={len(catalog)}."
        )

    _add_manifest_runtime_columns(catalog, manifest)
    return catalog
'''
    text = replace_between(
        text,
        "def load_production_station_catalog(\n",
        "def catalog_runtime_summary(",
        replacement,
        label="catalog-runtime-loader",
    )
    CATALOG_RUNTIME.write_text(text, encoding="utf-8")


def patch_climate_sources() -> None:
    text = CLIMATE_SOURCES.read_text(encoding="utf-8")
    replacement = r'''def filter_station_catalog(
    catalog: pd.DataFrame,
    search_text: str = "",
    countries: Iterable[str] | None = None,
    datasets: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Filter station catalog without copying the full snapshot on the no-filter path."""
    country_list = list(countries or [])
    dataset_list = list(datasets or [])
    token = search_text.strip().lower()

    # The default Find climate view is intentionally zero-copy. The production
    # catalog is a shared read-only cache resource; all filtered branches below
    # create their own DataFrame through boolean indexing/reset_index.
    if not country_list and not dataset_list and not token:
        return catalog

    df = catalog
    if country_list:
        df = df[df["country"].isin(country_list)]
    if dataset_list:
        df = df[df["dataset"].isin(dataset_list)]
    if token:
        searchable = (
            df["name"].astype("string").fillna("")
            + " "
            + df["country"].astype("string").fillna("")
            + " "
            + df.get("region", pd.Series("", index=df.index)).astype("string").fillna("")
            + " "
            + df.get("dataset", pd.Series("", index=df.index)).astype("string").fillna("")
            + " "
            + df.get("station_id", pd.Series("", index=df.index)).astype("string").fillna("")
        ).str.lower()
        df = df[searchable.str.contains(token, regex=False)]
    return df.reset_index(drop=True)
'''
    text = replace_between(
        text,
        "def filter_station_catalog(\n",
        "def nearest_station(",
        replacement,
        label="climate-source-filter",
    )
    CLIMATE_SOURCES.write_text(text, encoding="utf-8")


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "@st.cache_data(show_spinner=False)\ndef _cached_station_catalog_by_identity(catalog_version: str, catalog_sha256: str) -> pd.DataFrame:",
        "@st.cache_resource(show_spinner=False, max_entries=1)\ndef _cached_station_catalog_by_identity(catalog_version: str, catalog_sha256: str) -> pd.DataFrame:",
        label="catalog-cache-resource",
    )
    text = replace_once(
        text,
        "@st.cache_data(show_spinner=False)\ndef station_options_from_catalog(catalog: pd.DataFrame, limit: int = 10000) -> dict[str, str]:",
        "def station_options_from_catalog(catalog: pd.DataFrame, limit: int = 10000) -> dict[str, str]:",
        label="station-options-cache-removal",
    )

    grouped_replacement = r'''def _limited_distinct_text(values: pd.Series, limit: int) -> str:
    items = sorted({str(value).strip() for value in values.dropna().tolist() if str(value).strip()})
    return ", ".join(items[:limit])


def grouped_station_catalog(catalog: pd.DataFrame) -> pd.DataFrame:
    """Return one compact row per physical station without copying the full catalog."""
    if catalog.empty:
        return pd.DataFrame()

    lat_key = pd.to_numeric(catalog["latitude"], errors="coerce").round(4).rename("_lat_key")
    lon_key = pd.to_numeric(catalog["longitude"], errors="coerce").round(4).rename("_lon_key")
    country_key = catalog["country"].astype("string").fillna("").str.strip().str.lower().rename("_country_key")
    name_key = catalog["name"].astype("string").fillna("").str.strip().str.lower().rename("_name_key")
    valid = lat_key.notna() & lon_key.notna()
    if not bool(valid.any()):
        return pd.DataFrame()

    # Project only the seven columns needed for grouping. This bounds the
    # temporary table even when the reviewed catalog contains 98k climate rows.
    base = catalog.loc[
        valid,
        ["name", "country", "region", "dataset", "latitude", "longitude", "elevation_m"],
    ]
    grouped = base.groupby(
        [
            country_key.loc[valid],
            name_key.loc[valid],
            lat_key.loc[valid],
            lon_key.loc[valid],
        ],
        sort=False,
        observed=True,
        dropna=False,
    )
    summary = grouped.agg(
        name=("name", "first"),
        country=("country", "first"),
        region=("region", lambda values: _limited_distinct_text(values, 3)),
        dataset=("dataset", lambda values: _limited_distinct_text(values, 4)),
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
        elevation_m=("elevation_m", "first"),
        climate_count=("name", "size"),
    ).reset_index()

    summary["station_group_id"] = (
        summary["_country_key"].astype(str)
        + "|"
        + summary["_name_key"].astype(str)
        + "|"
        + summary["_lat_key"].map(lambda value: f"{float(value):.4f}")
        + "|"
        + summary["_lon_key"].map(lambda value: f"{float(value):.4f}")
    )
    return summary[
        [
            "station_group_id",
            "name",
            "country",
            "region",
            "dataset",
            "latitude",
            "longitude",
            "elevation_m",
            "climate_count",
            "_country_key",
            "_name_key",
            "_lat_key",
            "_lon_key",
        ]
    ]


def station_group_options_from_groups(groups: pd.DataFrame, limit: int = 10000) -> dict[str, str]:
    """Return manual-selector labels from an already grouped station table."""
    options: dict[str, str] = {}
    for _, row in groups.head(limit).iterrows():
        count = int(row.get("climate_count", 1))
        suffix = f" ({count} climates)" if count != 1 else " (1 climate)"
        region = f", {row.get('region', '')}" if str(row.get("region", "")).strip() else ""
        options[f"{row['name']} — {row['country']}{region}{suffix}"] = str(row["station_group_id"])
    return options


def station_group_options_from_catalog(catalog: pd.DataFrame, limit: int = 10000) -> dict[str, str]:
    """Compatibility wrapper for callers that have not already grouped the catalog."""
    return station_group_options_from_groups(grouped_station_catalog(catalog), limit=limit)
'''
    text = replace_between(
        text,
        "@st.cache_data(show_spinner=False)\ndef grouped_station_catalog(catalog: pd.DataFrame) -> pd.DataFrame:\n",
        "def climate_option_label(",
        grouped_replacement,
        label="grouped-catalog",
    )

    rows_replacement = r'''def catalog_rows_for_station_group(catalog: pd.DataFrame, station_group: object) -> pd.DataFrame:
    """Return climates for one station using coordinate-first bounded filtering."""
    if catalog.empty or station_group is None:
        return pd.DataFrame()

    if isinstance(station_group, pd.Series):
        group = station_group
    elif isinstance(station_group, dict):
        group = pd.Series(station_group)
    else:
        # Compatibility path for an old textual group id. It is not used by the
        # production UI; resolve it once through the compact grouped table.
        groups = grouped_station_catalog(catalog)
        matches = groups[groups["station_group_id"].astype(str) == str(station_group)]
        if matches.empty:
            return pd.DataFrame()
        group = matches.iloc[0]

    target_lat = float(group.get("_lat_key", round(float(group.get("latitude")), 4)))
    target_lon = float(group.get("_lon_key", round(float(group.get("longitude")), 4)))
    lat = pd.to_numeric(catalog["latitude"], errors="coerce").round(4)
    lon = pd.to_numeric(catalog["longitude"], errors="coerce").round(4)
    candidates = catalog.loc[lat.eq(target_lat) & lon.eq(target_lon)]
    if candidates.empty:
        return pd.DataFrame()

    target_name = str(group.get("_name_key", group.get("name", ""))).strip().lower()
    target_country = str(group.get("_country_key", group.get("country", ""))).strip().lower()
    names = candidates["name"].astype("string").fillna("").str.strip().str.lower()
    countries = candidates["country"].astype("string").fillna("").str.strip().str.lower()
    return candidates.loc[names.eq(target_name) & countries.eq(target_country)].copy()
'''
    text = replace_between(
        text,
        "def catalog_rows_for_station_group(catalog: pd.DataFrame, group_id: str) -> pd.DataFrame:\n",
        "def _map_state_center(",
        rows_replacement,
        label="catalog-rows-for-group",
    )

    text = replace_once(
        text,
        "selected_climates = catalog_rows_for_station_group(filtered_catalog, str(selected_group[\"station_group_id\"]))",
        "selected_climates = catalog_rows_for_station_group(filtered_catalog, selected_group)",
        label="selected-climates-call",
    )
    text = replace_once(
        text,
        "station_group_options = station_group_options_from_catalog(filtered_catalog, limit=10000)",
        "station_group_options = station_group_options_from_groups(station_groups_all, limit=10000)",
        label="manual-options-call",
    )
    APP.write_text(text, encoding="utf-8")


def patch_live_audit() -> None:
    text = LIVE_AUDIT.read_text(encoding="utf-8")
    needle = "for (const view of views) {\n  if (!runtimeMatchesExpected(view.runtime_build)) {"
    replacement = (
        "for (const view of views) {\n"
        "  if (view.resource_limit_visible) {\n"
        "    critical.push(`${view.name}: Streamlit resource-limit page detected.`);\n"
        "  }\n"
        "  if (!runtimeMatchesExpected(view.runtime_build)) {"
    )
    text = replace_once(text, needle, replacement, label="live-audit-resource-limit")
    LIVE_AUDIT.write_text(text, encoding="utf-8")


def write_tests() -> None:
    TEST_PATH.write_text(
        r'''from __future__ import annotations

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
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_catalog_runtime()
    patch_climate_sources()
    patch_app()
    patch_live_audit()
    write_tests()
    print("CLIMATE-0.10.12 memory hotfix patches applied")


if __name__ == "__main__":
    main()
