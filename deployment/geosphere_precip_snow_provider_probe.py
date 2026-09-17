#!/usr/bin/env python3
"""Find and validate a live GeoSphere precipitation/snow smoke fixture.

This is intentionally a provider-backed deployment probe, not a unit test. It
uses the production GeoSphere adapter to locate a short historical winter
interval with real ``rr``, ``rrm`` and ``sh`` observations. No provider values
are frozen into the repository.
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
from epw_climate_analyzer.precipitation import annual_precipitation_indices, snow_season_indices

REQUIRED_CANONICAL = (
    "liquid_precipitation_depth_mm",
    "precipitation_duration_min",
    "snow_depth_cm",
)
HOURLY_REQUIRED_CANONICAL = (
    "liquid_precipitation_depth_mm",
    "precipitation_duration_min",
)
PREFERRED_STATION_NAMES = (
    "Graz Universität",
    "Wien Hohe Warte",
    "Salzburg Flughafen",
    "Innsbruck Universität",
    "Klagenfurt Flughafen",
)
MAX_STATIONS_TO_PROBE = 16
MAX_TOTAL_INTERVAL_ATTEMPTS = 32
WINTER_WINDOW_DAYS = 7
WINTER_YEARS_BACK = 3


def _parse_date(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _validity_bounds(station: GeoSphereStation) -> tuple[pd.Timestamp, pd.Timestamp]:
    today = pd.Timestamp.now(tz="UTC").normalize()
    parsed_start = _parse_date(station.valid_from)
    parsed_end = _parse_date(station.valid_to)
    start = parsed_start.normalize() if parsed_start is not None else pd.Timestamp("1900-01-01", tz="UTC")
    end = min(parsed_end.normalize() if parsed_end is not None else today, today)
    if end < start:
        raise ValueError("station validity does not overlap historical dates")
    return start, end


def _winter_intervals(station: GeoSphereStation) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return recent short winter windows inside the station validity range."""
    valid_start, valid_end = _validity_bounds(station)
    latest_year = int(valid_end.year)
    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    # January/February are tried first because they are both recent and likely
    # to expose numeric snow-depth observations at stations that measure sh.
    candidates: list[pd.Timestamp] = []
    for year in range(latest_year, latest_year - WINTER_YEARS_BACK - 1, -1):
        for month, day in ((1, 15), (2, 10)):
            candidates.append(pd.Timestamp(year=year, month=month, day=day, tz="UTC"))
        # December belongs to the preceding part of the same cold season.
        candidates.append(pd.Timestamp(year=year - 1, month=12, day=10, tz="UTC"))

    for start in candidates:
        end = start + pd.Timedelta(days=WINTER_WINDOW_DAYS - 1, hours=23, minutes=50)
        if start < valid_start or end > valid_end:
            continue
        pair = (start, end)
        if pair not in windows:
            windows.append(pair)
    return windows


def _candidate_order(stations: Iterable[GeoSphereStation]) -> list[GeoSphereStation]:
    stations = list(stations)
    ordered: list[GeoSphereStation] = []

    for preferred in PREFERRED_STATION_NAMES:
        needle = preferred.casefold()
        match = next((station for station in stations if needle in station.name.casefold()), None)
        if match is not None and match not in ordered:
            ordered.append(match)

    # After familiar reference stations, prefer active/high-elevation stations:
    # they are more likely to expose snow-depth observations in a short winter
    # window. This is candidate ordering only, never a scientific assumption.
    remaining = [station for station in stations if station not in ordered]
    remaining.sort(
        key=lambda station: (
            station.is_active is not True,
            -(float(station.elevation_m) if station.elevation_m is not None else -1.0),
            station.name.casefold(),
            station.station_id,
        )
    )
    ordered.extend(remaining)
    return ordered[:MAX_STATIONS_TO_PROBE]


def _numeric_count(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").notna().sum())


def _numeric_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {column: _numeric_count(frame, column) for column in REQUIRED_CANONICAL}


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
    attempts = 0
    for station in _candidate_order(parse_stations(metadata)):
        for start, end in _winter_intervals(station):
            if attempts >= MAX_TOTAL_INTERVAL_ATTEMPTS:
                break
            attempts += 1
            try:
                dataset = fetch_station_dataset(
                    station=station,
                    start=start,
                    end=end,
                    metadata=metadata,
                    canonical_variables=REQUIRED_CANONICAL,
                    timeout_s=timeout_s,
                )
                native_counts = _numeric_counts(dataset.data)
                if any(native_counts[column] <= 0 for column in REQUIRED_CANONICAL):
                    raise RuntimeError(f"native coverage insufficient: {native_counts}")

                hourly = prepare_historical_analysis_frame(dataset)
                hourly_counts = _numeric_counts(hourly)
                if any(hourly_counts[column] <= 0 for column in HOURLY_REQUIRED_CANONICAL):
                    raise RuntimeError(f"strict hourly rr/rrm coverage insufficient: {hourly_counts}")

                precipitation = annual_precipitation_indices(hourly)
                snow = snow_season_indices(dataset.data)
                if precipitation.empty:
                    raise RuntimeError("annual precipitation indices are empty")
                if snow.empty:
                    raise RuntimeError("snow-season indices are empty")

                return {
                    "schema": "climate-analyzer-geosphere-precip-snow-smoke-v2",
                    "station_id": station.station_id,
                    "station_name": station.name,
                    "state": station.state,
                    "elevation_m": station.elevation_m,
                    "ui_start_date": start.date().isoformat(),
                    "ui_end_date": end.date().isoformat(),
                    "probe_start": start.isoformat(),
                    "probe_end": end.isoformat(),
                    "native_interval_minutes": 10,
                    "required_provider_parameters": [provider_names[column] for column in REQUIRED_CANONICAL],
                    "required_canonical_variables": list(REQUIRED_CANONICAL),
                    "native_valid_records": native_counts,
                    "hourly_valid_records": hourly_counts,
                    "hourly_snow_available": hourly_counts["snow_depth_cm"] > 0,
                    "precipitation_index_rows": int(len(precipitation)),
                    "snow_season_rows": int(len(snow)),
                    "provider_probe_attempts": attempts,
                }
            except Exception as exc:  # provider candidate selection; preserve bounded diagnostics
                failures.append(
                    f"{station.station_id} {station.name} {start.date()}..{end.date()}: "
                    f"{type(exc).__name__}: {exc}"
                )
        if attempts >= MAX_TOTAL_INTERVAL_ATTEMPTS:
            break

    tail = " | ".join(failures[-12:])
    raise RuntimeError(
        f"No bounded winter GeoSphere smoke fixture exposed usable rr/rrm/sh after {attempts} attempt(s). " + tail
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/geosphere-precip-snow-smoke/provider-fixture.json")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fixture = find_fixture(timeout_s=args.timeout)
    except Exception as exc:
        # Leave machine-readable evidence even when the external provider probe
        # itself fails, so scheduled smoke failures are diagnosable from artifacts.
        failure = {
            "schema": "climate-analyzer-geosphere-precip-snow-smoke-v2",
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise

    fixture["success"] = True
    path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(fixture, indent=2, sort_keys=True))
    print(
        f"Provider probe PASS: {fixture['station_name']} (ID {fixture['station_id']}), "
        f"{fixture['ui_start_date']} → {fixture['ui_end_date']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
