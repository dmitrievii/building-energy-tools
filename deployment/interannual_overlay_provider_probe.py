from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from epw_climate_analyzer import geosphere


OUTPUT = Path("artifacts/interannual-overlay/hourly-provider.json")
RESOURCE_ID = "klima-v2-1h"
STATION_ID = "105"
START = pd.Timestamp("2024-12-30T00:00:00Z")
END = pd.Timestamp("2025-01-02T23:00:00Z")


def main() -> int:
    metadata = geosphere.fetch_metadata(resource_id=RESOURCE_ID, timeout_s=45)
    stations = geosphere.parse_stations(metadata)
    station = next((item for item in stations if str(item.station_id) == STATION_ID), None)
    if station is None:
        raise RuntimeError(f"Station {STATION_ID} is unavailable in {RESOURCE_ID} metadata.")

    dataset = geosphere.fetch_station_dataset(
        station=station,
        start=START,
        end=END,
        resource_id=RESOURCE_ID,
        metadata=metadata,
        canonical_variables=("dry_bulb_temperature_c",),
        timeout_s=60,
    )
    values = pd.to_numeric(dataset.data["dry_bulb_temperature_c"], errors="coerce")
    years = sorted({int(year) for year in dataset.data.index.year[values.notna()]})
    if years != [2024, 2025]:
        raise RuntimeError(f"Expected observations in real years 2024 and 2025, got {years}.")
    if int(values.notna().sum()) < 96:
        raise RuntimeError("Hourly interannual fixture has insufficient valid temperature observations.")

    report = {
        "success": True,
        "resource_id": RESOURCE_ID,
        "station_id": station.station_id,
        "station_name": station.name,
        "ui_start_date": START.date().isoformat(),
        "ui_end_date": END.date().isoformat(),
        "years": years,
        "valid_temperature_records": int(values.notna().sum()),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
