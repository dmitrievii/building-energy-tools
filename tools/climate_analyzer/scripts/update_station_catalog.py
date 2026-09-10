"""Build a reviewable Climate.OneBuilding station-catalog candidate.

This is a maintenance command, not a public-app code path. It crawls selected
Climate.OneBuilding WMO-region catalog pages using the existing parser, writes a
normalized CSV snapshot into the repository working tree, and emits a provenance
manifest whose SHA-256 binds the metadata to that exact CSV.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from epw_climate_analyzer.climate_sources import (
    ONEBUILDING_REGION_OPTIONS,
    build_onebuilding_station_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "epw_climate_analyzer" / "data" / "station_catalog.csv"
DEFAULT_MANIFEST = ROOT / "epw_climate_analyzer" / "data" / "station_catalog.meta.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_regions(raw: str) -> tuple[list[str], list[str]]:
    value = raw.strip()
    if not value or value.lower() == "all":
        names = list(ONEBUILDING_REGION_OPTIONS)
    else:
        requested = [item.strip() for item in value.split(",") if item.strip()]
        unknown = [item for item in requested if item not in ONEBUILDING_REGION_OPTIONS]
        if unknown:
            allowed = ", ".join(ONEBUILDING_REGION_OPTIONS)
            raise ValueError(f"Unknown WMO region name(s): {', '.join(unknown)}. Allowed values: {allowed}, all")
        names = requested
    return names, [ONEBUILDING_REGION_OPTIONS[name] for name in names]


def write_manifest(
    path: Path,
    *,
    catalog_path: Path,
    regions: list[str],
    station_count: int,
    xlsx_count: int,
    kml_count: int,
    failed_count: int,
) -> dict[str, object]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0)
    digest = sha256_file(catalog_path)
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "catalog_version": f"onebuilding-{generated_at:%Y%m%d}-{digest[:12]}",
        "catalog_kind": "generated_provider_snapshot",
        "generated_at_utc": generated_at.isoformat().replace("+00:00", "Z"),
        "source_snapshot_date": generated_at.date().isoformat(),
        "station_count": int(station_count),
        "coverage": f"Generated from selected Climate.OneBuilding WMO regions: {', '.join(regions)}.",
        "csv_sha256": digest,
        "build_evidence": {
            "regions": regions,
            "xlsx_catalogs_parsed": int(xlsx_count),
            "kml_catalogs_parsed": int(kml_count),
            "failed_catalogs": int(failed_count),
        },
        "provider": {
            "name": "Climate.OneBuilding",
            "home_url": "https://climate.onebuilding.org/",
            "sources_url": "https://climate.onebuilding.org/sources/default.html",
            "news_url": "https://climate.onebuilding.org/news/default.html",
            "citation": "Lawrie, Linda K.; Crawley, Drury B. 2026. Development of Global Typical Meteorological Years (TMYx). Climate.OneBuilding.Org (paper in progress).",
        },
        "distribution_policy": {
            "bundled_content": "Normalized station metadata and provider download URLs only.",
            "epw_files_bundled": False,
            "note": "Building Energy Tools does not assert a blanket redistribution license for upstream climate files. EPW payloads are fetched on demand from the provider and are not committed to this repository. Dataset-specific source and citation information remains the responsibility of the upstream provider/source dataset.",
        },
        "maintenance": {
            "script": "scripts/update_station_catalog.py",
            "workflow": ".github/workflows/update-climate-catalog.yml",
            "promotion_model": "Generate candidate catalog and manifest, validate them, review the diff, then merge through a normal pull request.",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regions",
        default="Europe",
        help="Comma-separated exact region names from ONEBUILDING_REGION_OPTIONS, or 'all'. Default: Europe.",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow promotion candidate generation even when one or more upstream catalog files fail to parse.",
    )
    args = parser.parse_args()

    region_names, region_pages = parse_regions(args.regions)
    report = build_onebuilding_station_catalog(
        progress_callback=print,
        timeout_s=args.timeout,
        region_pages=region_pages,
    )

    if report.station_count <= 0:
        raise RuntimeError("Catalog build produced zero station records; refusing to replace the bundled catalog.")
    if report.failed_catalog_count and not args.allow_partial:
        raise RuntimeError(
            f"Catalog build had {report.failed_catalog_count} failed upstream catalog(s); "
            "refusing to create a promotion candidate without --allow-partial."
        )

    args.catalog.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report.cache_path, args.catalog)
    manifest = write_manifest(
        args.manifest,
        catalog_path=args.catalog,
        regions=region_names,
        station_count=report.station_count,
        xlsx_count=report.xlsx_catalog_count,
        kml_count=report.kml_catalog_count,
        failed_count=report.failed_catalog_count,
    )

    print(f"Catalog:  {args.catalog}")
    print(f"Manifest: {args.manifest}")
    print(f"Version:  {manifest['catalog_version']}")
    print(f"Stations: {report.station_count}")
    print(f"SHA-256:  {manifest['csv_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
