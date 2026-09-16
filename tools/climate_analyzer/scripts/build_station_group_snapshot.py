from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from epw_climate_analyzer.catalog_runtime import load_production_station_catalog, load_station_catalog_manifest


DATA_DIR = ROOT / "epw_climate_analyzer" / "data"
CSV_PATH = DATA_DIR / "station_groups.csv"
META_PATH = DATA_DIR / "station_groups.meta.json"


def main() -> None:
    # Reuse the production grouping implementation so the release-time snapshot
    # and the filtered runtime fallback cannot silently diverge.
    namespace = runpy.run_path(str(ROOT / "app.py"), run_name="station_group_snapshot_builder")
    namespace["_ensure_map_dependencies"]()
    grouped_station_catalog = namespace["grouped_station_catalog"]

    manifest = load_station_catalog_manifest()
    catalog = load_production_station_catalog()
    groups = grouped_station_catalog(catalog)
    groups.to_csv(CSV_PATH, index=False)
    payload = CSV_PATH.read_bytes()
    meta = {
        "schema_version": "1.0",
        "catalog_version": manifest.catalog_version,
        "catalog_sha256": manifest.csv_sha256,
        "station_group_count": int(len(groups)),
        "csv_sha256": sha256(payload).hexdigest(),
    }
    META_PATH.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"station groups: {len(groups):,}")
    print(f"snapshot bytes: {len(payload):,}")
    print(f"snapshot SHA-256: {meta['csv_sha256']}")


if __name__ == "__main__":
    main()
