"""Immutable physical-station snapshot for the Climate.OneBuilding world map.

The full reviewed catalog stores one row per climate file.  Map geometry is much
smaller and changes only when that reviewed catalog snapshot changes, so runtime
sessions load a pre-grouped physical-station table instead of recomputing the
98k-row grouping on every map render.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent / "data"
SNAPSHOT_PATH = DATA_DIR / "station_groups.csv"
MANIFEST_PATH = DATA_DIR / "station_groups.meta.json"
REQUIRED_COLUMNS = (
    "station_group_id",
    "name",
    "country",
    "region",
    "dataset",
    "latitude",
    "longitude",
    "elevation_m",
    "climate_count",
)


@dataclass(frozen=True)
class StationGroupSnapshotManifest:
    schema_version: str
    catalog_version: str
    catalog_sha256: str
    station_group_count: int
    csv_sha256: str


def load_station_group_snapshot_manifest(path: Path = MANIFEST_PATH) -> StationGroupSnapshotManifest:
    """Read the immutable station-group snapshot identity."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return StationGroupSnapshotManifest(
        schema_version=str(raw["schema_version"]),
        catalog_version=str(raw["catalog_version"]),
        catalog_sha256=str(raw["catalog_sha256"]),
        station_group_count=int(raw["station_group_count"]),
        csv_sha256=str(raw["csv_sha256"]),
    )


def load_station_group_snapshot(
    expected_catalog_version: str,
    expected_catalog_sha256: str,
    *,
    csv_path: Path = SNAPSHOT_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> pd.DataFrame:
    """Load and integrity-check pre-grouped physical stations for one catalog identity."""
    manifest = load_station_group_snapshot_manifest(manifest_path)
    if manifest.schema_version != "1.0":
        raise RuntimeError(f"Unsupported station-group snapshot schema: {manifest.schema_version}")
    if manifest.catalog_version != str(expected_catalog_version):
        raise RuntimeError(
            "Station-group snapshot catalog version mismatch: "
            f"expected {expected_catalog_version}, got {manifest.catalog_version}."
        )
    if manifest.catalog_sha256 != str(expected_catalog_sha256):
        raise RuntimeError("Station-group snapshot is not bound to the active reviewed catalog SHA-256.")

    payload = csv_path.read_bytes()
    actual_sha = sha256(payload).hexdigest()
    if actual_sha != manifest.csv_sha256:
        raise RuntimeError("Station-group snapshot byte-level SHA-256 validation failed.")

    frame = pd.read_csv(BytesIO(payload))
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"Station-group snapshot is missing columns: {', '.join(missing)}")
    if len(frame) != manifest.station_group_count:
        raise RuntimeError(
            "Station-group snapshot row count mismatch: "
            f"expected {manifest.station_group_count:,}, got {len(frame):,}."
        )
    if frame["station_group_id"].astype(str).duplicated().any():
        raise RuntimeError("Station-group snapshot contains duplicate physical station IDs.")
    return frame.loc[:, list(REQUIRED_COLUMNS)]
