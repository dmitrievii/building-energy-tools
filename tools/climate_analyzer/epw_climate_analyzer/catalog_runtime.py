"""Versioned station-catalog loading and provenance helpers.

The public application must not rebuild Climate.OneBuilding catalogs during a
user session. Runtime reads a bundled, reviewed CSV snapshot and verifies it
against a colocated machine-readable manifest before exposing station records.
Catalog crawling remains a maintenance concern handled by the update script.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import pandas as pd

from .climate_sources import CATALOG_PATH


CATALOG_MANIFEST_PATH = CATALOG_PATH.with_name("station_catalog.meta.json")


@dataclass(frozen=True)
class StationCatalogManifest:
    """Validated metadata describing the bundled station-catalog snapshot."""

    schema_version: str
    catalog_version: str
    catalog_kind: str
    generated_at_utc: str
    source_snapshot_date: str
    station_count: int
    coverage: str
    csv_sha256: str
    provider_name: str
    provider_home_url: str
    provider_sources_url: str
    provider_news_url: str
    provider_citation: str
    epw_files_bundled: bool
    distribution_note: str
    build_evidence: dict[str, object] | None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_station_catalog_manifest(path: str | Path | None = None) -> StationCatalogManifest:
    """Read and validate the bundled catalog manifest."""
    manifest_path = Path(path) if path is not None else CATALOG_MANIFEST_PATH
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    provider = payload.get("provider") or {}
    policy = payload.get("distribution_policy") or {}
    build_evidence = payload.get("build_evidence")
    required = {
        "schema_version",
        "catalog_version",
        "catalog_kind",
        "generated_at_utc",
        "source_snapshot_date",
        "station_count",
        "coverage",
        "csv_sha256",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"Station catalog manifest is missing required fields: {', '.join(missing)}")

    sha = str(payload["csv_sha256"]).strip().lower()
    if len(sha) != 64 or any(character not in "0123456789abcdef" for character in sha):
        raise ValueError("Station catalog manifest contains an invalid csv_sha256 value.")
    if build_evidence is not None and not isinstance(build_evidence, dict):
        raise ValueError("Station catalog manifest build_evidence must be an object when present.")

    return StationCatalogManifest(
        schema_version=str(payload["schema_version"]),
        catalog_version=str(payload["catalog_version"]),
        catalog_kind=str(payload["catalog_kind"]),
        generated_at_utc=str(payload["generated_at_utc"]),
        source_snapshot_date=str(payload["source_snapshot_date"]),
        station_count=int(payload["station_count"]),
        coverage=str(payload["coverage"]),
        csv_sha256=sha,
        provider_name=str(provider.get("name", "Climate.OneBuilding")),
        provider_home_url=str(provider.get("home_url", "https://climate.onebuilding.org/")),
        provider_sources_url=str(provider.get("sources_url", "")),
        provider_news_url=str(provider.get("news_url", "")),
        provider_citation=str(provider.get("citation", "")),
        epw_files_bundled=bool(policy.get("epw_files_bundled", False)),
        distribution_note=str(policy.get("note", "")),
        build_evidence=dict(build_evidence) if isinstance(build_evidence, dict) else None,
    )


RUNTIME_CATALOG_COLUMNS = [
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


def catalog_runtime_summary(catalog: pd.DataFrame | None = None) -> str:
    """Return a concise public-facing description of the active catalog asset."""
    manifest = load_station_catalog_manifest()
    count = len(catalog) if catalog is not None else manifest.station_count
    return (
        f"Versioned station catalog: {manifest.catalog_version} · {count:,} records · "
        f"source snapshot {manifest.source_snapshot_date}. {manifest.coverage}"
    )


def station_provenance_text(station: pd.Series, final_download_url: str, archive_name: str | None = None) -> str:
    """Return an auditable provenance string for a selected online EPW."""
    parts = [
        "Climate.OneBuilding",
        f"catalog={station.get('catalog_version', 'unknown')}",
        f"station_id={station.get('station_id', '')}",
        f"dataset={station.get('dataset', '')}",
        f"station={station.get('name', '')}",
        f"country={station.get('country', '')}",
        f"retrieved={final_download_url}",
    ]
    if archive_name:
        parts.append(f"archive={archive_name}")
    return " | ".join(parts)
