from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from epw_climate_analyzer.geosphere import (
    fetch_metadata,
    fetch_station_dataset,
    parse_stations,
    supported_parameter_mapping,
)

OUT = Path("artifacts/geosphere-provider")
TARGET_START = pd.Timestamp("2025-01-15T12:00:00Z")
TARGET_END = pd.Timestamp("2025-01-15T13:00:00Z")


def _covers(station, when: pd.Timestamp) -> bool:
    start = pd.to_datetime(station.valid_from, utc=True, errors="coerce")
    end = pd.to_datetime(station.valid_to, utc=True, errors="coerce")
    return (pd.isna(start) or start <= when) and (pd.isna(end) or end >= when)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metadata = fetch_metadata(timeout_s=60)
    supported = supported_parameter_mapping(metadata)
    if "tl" not in supported:
        raise SystemExit("Live metadata no longer expose strictly validated air temperature parameter 'tl'.")

    stations = parse_stations(metadata)
    if len(stations) < 100:
        raise SystemExit(f"Unexpectedly small live GeoSphere station catalog: {len(stations)}")

    valid = [station for station in stations if _covers(station, TARGET_START)]
    valid.sort(key=lambda station: ("graz" not in station.name.lower(), station.name.lower(), station.station_id))
    if not valid:
        raise SystemExit("No station validity interval covers the bounded smoke-test timestamp.")

    failures: list[str] = []
    selected = None
    dataset = None
    for station in valid[:8]:
        try:
            candidate = fetch_station_dataset(
                station=station,
                start=TARGET_START,
                end=TARGET_END,
                metadata=metadata,
                canonical_variables=("dry_bulb_temperature_c",),
                timeout_s=60,
            )
            series = pd.to_numeric(candidate.data["dry_bulb_temperature_c"], errors="coerce")
            if candidate.data.empty or series.notna().sum() == 0:
                raise ValueError("temperature series contains no measured values")
            selected = station
            dataset = candidate
            break
        except Exception as exc:
            failures.append(f"{station.station_id} {station.name}: {exc}")

    if selected is None or dataset is None:
        raise SystemExit("No bounded candidate station produced measured temperature data. " + " | ".join(failures))

    index = dataset.data.index
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None or str(index.tz) != "UTC":
        raise SystemExit(f"Historical canonical index is not explicit UTC: {index.tz}")
    if dataset.temporal.native_interval_minutes != 10:
        raise SystemExit(f"Unexpected canonical native interval: {dataset.temporal.native_interval_minutes}")
    if dataset.temporal.calendar_mode != "historical":
        raise SystemExit(f"Unexpected calendar mode: {dataset.temporal.calendar_mode}")
    if dataset.provenance.provider != "GeoSphere Austria":
        raise SystemExit(f"Unexpected provider provenance: {dataset.provenance.provider}")
    if not dataset.provenance.source_reference.startswith("https://dataset.api.hub.geosphere.at/v1/"):
        raise SystemExit("Canonical provenance does not retain the exact official Dataset API request URL.")

    if len(index) > 1:
        deltas = index.to_series().diff().dropna().dt.total_seconds().div(60.0)
        if not deltas.map(lambda value: value > 0 and value % 10 == 0).all():
            raise SystemExit(f"Observed timestamps violate 10-minute cadence multiples: {deltas.tolist()}")

    evidence = {
        "status": "PASS",
        "metadata_station_count": len(stations),
        "strictly_supported_provider_parameters": sorted(supported),
        "station": {
            "id": selected.station_id,
            "name": selected.name,
            "state": selected.state,
            "latitude": selected.latitude,
            "longitude": selected.longitude,
            "elevation_m": selected.elevation_m,
        },
        "requested_utc": [TARGET_START.isoformat(), TARGET_END.isoformat()],
        "records": len(dataset.data),
        "measured_temperature_records": int(dataset.data["dry_bulb_temperature_c"].notna().sum()),
        "first_timestamp": dataset.data.index.min().isoformat(),
        "last_timestamp": dataset.data.index.max().isoformat(),
        "native_interval_minutes": dataset.temporal.native_interval_minutes,
        "calendar_mode": dataset.temporal.calendar_mode,
        "provider": dataset.provenance.provider,
        "request_reference": dataset.provenance.source_reference,
        "candidate_failures_before_success": failures,
    }
    (OUT / "api-smoke.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(evidence, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
