from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from epw_climate_analyzer.catalog_runtime import (
    CATALOG_MANIFEST_PATH,
    catalog_runtime_summary,
    load_production_station_catalog,
    load_station_catalog_manifest,
    station_provenance_text,
)
from epw_climate_analyzer.climate_sources import CATALOG_PATH


class CatalogProvenanceTests(unittest.TestCase):
    def test_manifest_binds_exact_catalog_bytes_and_count(self) -> None:
        manifest = load_station_catalog_manifest()
        catalog = load_production_station_catalog()
        self.assertEqual(len(catalog), manifest.station_count)
        self.assertEqual(set(catalog["catalog_version"]), {manifest.catalog_version})
        self.assertEqual(set(catalog["catalog_sha256"]), {manifest.csv_sha256})
        self.assertFalse(manifest.epw_files_bundled)

    def test_bootstrap_catalog_is_explicitly_not_claimed_global(self) -> None:
        manifest = load_station_catalog_manifest()
        if manifest.catalog_kind == "curated_bootstrap":
            self.assertIn("not global", manifest.coverage.lower())

    def test_promoted_download_urls_are_https_onebuilding_only(self) -> None:
        catalog = load_production_station_catalog()
        for url in catalog["download_url"].astype(str):
            parsed = urlparse(url)
            self.assertEqual(parsed.scheme.lower(), "https")
            self.assertEqual((parsed.hostname or "").rstrip(".").lower(), "climate.onebuilding.org")

    def test_catalog_integrity_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            altered = Path(temp_dir) / "station_catalog.csv"
            altered.write_bytes(CATALOG_PATH.read_bytes() + b"\n")
            with self.assertRaisesRegex(RuntimeError, "integrity check failed"):
                load_production_station_catalog(altered, CATALOG_MANIFEST_PATH)

    def test_repository_does_not_bundle_epw_payloads_in_catalog_data_directory(self) -> None:
        data_dir = CATALOG_PATH.parent
        self.assertEqual(list(data_dir.glob("*.epw")), [])
        self.assertEqual(list(data_dir.glob("*.EPW")), [])

    def test_runtime_summary_and_station_provenance_include_catalog_version(self) -> None:
        catalog = load_production_station_catalog()
        manifest = load_station_catalog_manifest()
        self.assertIn(manifest.catalog_version, catalog_runtime_summary(catalog))
        station = catalog.iloc[0]
        text = station_provenance_text(station, str(station["download_url"]), "weather.zip")
        self.assertIn(f"catalog={manifest.catalog_version}", text)
        self.assertIn(f"station_id={station['station_id']}", text)
        self.assertIn("archive=weather.zip", text)


if __name__ == "__main__":
    unittest.main()
