#!/usr/bin/env python3
"""Find and validate a small live GeoSphere precipitation/snow smoke fixture.

This is intentionally a provider-backed deployment probe, not a unit test. It
uses the production GeoSphere adapter and writes one candidate station plus the
same default 30-day UI interval that the public app will use after selecting the
station. No provider values are frozen into the repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from epw_climate_analyzer.geosphere import (
    GeoSphereStation,
    fetch_metadata,
    fetch_station_dataset,
    parse_stations,
    supported_parameter_mapping,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame
from epw_climate_analyzer.precipitation import (
    annual_precipitation_indices,
    snow_season_indices,
)

REQUIRED_CANONICAL = (
    "liquid_precipitation_depth_mm",
    "precipitation_duration_min",
    "snow_depth_cm",
)
PREFERRED_STATION_IDS = ("11240",)  # Graz/Universitaet in the existing integration fixture.
MAX_STATIONS_TO_PROBE = 10
PROBE_DAYS = 3


def _parse_date(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _ui_interval(station: GeoSphereStation) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Mirror the public GeoSphere source page's default date-range logic."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    valid_from = _parse_date(station.valid_from) or pd.Timestamp("1900-01-01", tz="UTC")
    valid_to = _parse_date(station.valid_to) or today
    end_day = min(valid_to.normalize(), today)
    if end_day < valid_from.normalize():
        raise ValueError("station validity does not overlap the historical UI interval")
    start_day = max(valid_from.normalize(), end_day - pd.Timedelta(days=30))
    return start_day, end_day + pd.Timedelta(hours=23, minutes=50)


def _candidate_order(stations: Iterable[GeoSphereStation]) -> list[GeoSphereStation]:
    stations = list(stations)
    by_id = {station.station_id: station for station in stations}
    ordered: list[GeoSphereStation] = []
    for station_id in PREFERRED_STATION_IDS:
        if station_id in by_id:
            ordered.append(by_id[station_id])

    preferred_names = ("graz", "wien", "salzburg", "innsbruck", "klagenfurt", "linz")
    for needle in preferred_names:
        for station in stations:
            if station in ordered:
                continue
            if needle in station.name.casefold():
                ordered.append(station)
                break

    remaining = [station for station in stations if station not in ordered]
    remaining.sort(
        key=lambda station: (
            station.is_active is not True,
            -(_parse_date(station.valid_to).value if _parse_date(station.valid_to) is not None else 0),
            station.name.casefold(),
        )
    )
    ordered.extend(remaining)
    return ordered[:MAX_STATIONS_TO_PROBE]


def _numeric_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        column: int(pd.to_numeric(frame.get(column), errors="coerce").notna().sum())
        if column in frame.columns
        else 0
        for column in REQUIRED_CANONICAL
    }


def find_fixture(timeout_s: int) -> dict[str, object]:
    metadata = fetch_metadata(timeout_s=timeout_s)
    supported = supported_parameter_mapping(metadata)
    provider_names = {spec.canonical_name: provider for provider, spec in supported.items()}
    missing_resource = [column for column in REQUIRED_CANONICAL if column not in provider_names]
    if missing_resource:
        raise RuntimeError(
            "GeoSphere resource metadata no longer expose required smoke quantities: "
            + ", ".join(missing_resource)
        )

    failures: list[str] = []
    for station in _candidate_order(parse_stations(metadata)):
        try:
            ui_start, ui_end = _ui_interval(station)
            probe_end = ui_end
            probe_start = max(ui_start, probe_end.normalize() - pd.Timedelta(days=PROBE_DAYS - 1))
            dataset = fetch_station_dataset(
                station=station,
                start=probe_start,
                end=probe_end,
                metadata=metadata,
                canonical_variables=REQUIRED_CANONICAL,
                timeout_s=timeout_s,
            )
            native_counts = _numeric_counts(dataset.data)
            if any(count <= 0 for count in native_counts.values()):
                raise RuntimeError(f"native coverage insufficient: {native_counts}")

            hourly = prepare_historical_analysis_frame(dataset)
            hourly_counts = _numeric_counts(hourly)
            if any(count <= 0 for count in hourly_counts.values()):
                raise RuntimeError(f"strict hourly coverage insufficient: {hourly_counts}")

            precip = annual_precipitation_indices(hourly)
            snow = snow_season_indices(dataset.data)
            if precip.empty:
                raise RuntimeError("annual precipitation indices are empty")
            if snow.empty:
                raise RuntimeError("snow-season indices are empty")

            return {
                "schema": "climate-analyzer-geosphere-precip-snow-smoke-v1",
                "station_id": station.station_id,
                "station_name": station.name,
                "state": station.state,
                "ui_start_date": ui_start.date().isoformat(),
                "ui_end_date": ui_end.date().isoformat(),
                "probe_start": probe_start.isoformat(),
                "probe_end": probe_end.isoformat(),
                "native_interval_minutes": 10,
                "required_provider_parameters": [provider_names[column] for column in REQUIRED_CANONICAL],
                "required_canonical_variables": list(REQUIRED_CANONICAL),
                "native_valid_records": native_counts,
                "hourly_valid_records": hourly_counts,
                "precipitation_index_rows": int(len(precip)),
                "snow_season_rows": int(len(snow)),
            }
        except Exception as exc:  # live-provider candidate selection; keep diagnostics for evidence
            failures.append(f"{station.station_id} {station.name}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "No GeoSphere smoke candidate exposed usable rr/rrm/sh in the recent default interval. "
        + " | ".join(failures)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/geosphere-precip-snow-smoke/provider-fixture.json")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    fixture = find_fixture(timeout_s=args.timeout)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(fixture, indent=2, sort_keys=True))
    print(f"Provider probe PASS: {fixture['station_name']} (ID {fixture['station_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
