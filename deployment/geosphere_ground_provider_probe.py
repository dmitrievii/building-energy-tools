#!/usr/bin/env python3
"""Provider-backed live proof for GeoSphere shallow ground temperatures.

The probe finds a bounded real station/time fixture with tb10/tb20/tb50,
requires the matching provider quality flags, and independently verifies that
production canonical-hourly aggregation preserves these state temperatures by
arithmetic mean over complete native 10-minute hours.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from epw_climate_analyzer.geosphere import (
    FIELD_SPEC_BY_PROVIDER,
    GeoSphereStation,
    fetch_metadata,
    fetch_station_dataset,
    parse_stations,
    quality_flag_column,
    supported_parameter_mapping,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame

REQUIRED_PROVIDER = ("tb10", "tb20", "tb50")
REQUIRED_CANONICAL = tuple(FIELD_SPEC_BY_PROVIDER[name].canonical_name for name in REQUIRED_PROVIDER)
PREFERRED_STATION_NAMES = (
    "Wien Hohe Warte",
    "Graz Universität",
    "Salzburg Flughafen",
    "Innsbruck Universität",
    "Klagenfurt Flughafen",
)
MAX_STATIONS_TO_PROBE = 30
MAX_TOTAL_INTERVAL_ATTEMPTS = 60
WINDOW_DAYS = 3
YEARS_BACK = 3


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


def _candidate_intervals(station: GeoSphereStation) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    valid_start, valid_end = _validity_bounds(station)
    candidates: list[pd.Timestamp] = []
    latest_year = int(valid_end.year)
    for year in range(latest_year, latest_year - YEARS_BACK - 1, -1):
        for month, day in ((7, 15), (1, 15), (4, 15), (10, 15)):
            candidates.append(pd.Timestamp(year=year, month=month, day=day, tz="UTC"))
    result: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for start in candidates:
        end = start + pd.Timedelta(days=WINDOW_DAYS - 1, hours=23, minutes=50)
        if start >= valid_start and end <= valid_end:
            result.append((start, end))
    return result


def _candidate_order(stations: Iterable[GeoSphereStation]) -> list[GeoSphereStation]:
    stations = list(stations)
    ordered: list[GeoSphereStation] = []
    for preferred in PREFERRED_STATION_NAMES:
        needle = preferred.casefold()
        match = next((station for station in stations if needle in station.name.casefold()), None)
        if match is not None and match not in ordered:
            ordered.append(match)
    remaining = [station for station in stations if station not in ordered]
    remaining.sort(key=lambda station: (station.is_active is not True, station.name.casefold(), station.station_id))
    ordered.extend(remaining)
    return ordered[:MAX_STATIONS_TO_PROBE]


def _numeric_count(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").notna().sum())


def _flag_count(frame: pd.DataFrame, provider_name: str) -> int:
    column = quality_flag_column(provider_name)
    return 0 if column not in frame.columns else int(frame[column].notna().sum())


def _validate_hourly_mean(native: pd.DataFrame, hourly: pd.DataFrame) -> dict[str, object]:
    numeric = native[list(REQUIRED_CANONICAL)].apply(pd.to_numeric, errors="coerce")
    counts = numeric.notna().astype(int).resample("h").sum()
    complete = counts.index[(counts == 6).all(axis=1)]
    if len(complete) == 0:
        raise RuntimeError("no complete native hour contains all three ground temperatures")
    hour = pd.Timestamp(complete[0])
    source = numeric.loc[(numeric.index >= hour) & (numeric.index < hour + pd.Timedelta(hours=1))]
    if hour not in hourly.index:
        raise RuntimeError("complete native ground-temperature hour is absent from canonical hourly output")
    checks: dict[str, dict[str, float]] = {}
    for column in REQUIRED_CANONICAL:
        actual = float(hourly.loc[hour, column])
        expected = float(source[column].mean())
        if abs(actual - expected) > 1e-9:
            raise RuntimeError(f"hourly mean mismatch for {column}: actual={actual}, expected={expected}")
        checks[column] = {"actual": actual, "expected": expected}
    return {"hour": hour.isoformat(), "checks": checks}


def find_fixture(timeout_s: int) -> dict[str, object]:
    metadata = fetch_metadata(timeout_s=timeout_s)
    supported = supported_parameter_mapping(metadata)
    missing = [name for name in REQUIRED_PROVIDER if name not in supported]
    if missing:
        raise RuntimeError("GeoSphere metadata no longer expose ground fields: " + ", ".join(missing))

    parameters = metadata.get("parameters")
    live_names = {
        str(item.get("name"))
        for item in parameters
        if isinstance(item, dict) and item.get("name")
    } if isinstance(parameters, list) else set()
    missing_flags = [f"{name}_flag" for name in REQUIRED_PROVIDER if f"{name}_flag" not in live_names]
    if missing_flags:
        raise RuntimeError("GeoSphere metadata no longer expose matching ground quality flags: " + ", ".join(missing_flags))

    failures: list[str] = []
    attempts = 0
    for station in _candidate_order(parse_stations(metadata)):
        for start, end in _candidate_intervals(station):
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
                native_counts = {column: _numeric_count(dataset.data, column) for column in REQUIRED_CANONICAL}
                if any(count <= 0 for count in native_counts.values()):
                    raise RuntimeError(f"native ground coverage insufficient: {native_counts}")
                flag_counts = {name: _flag_count(dataset.data, name) for name in REQUIRED_PROVIDER}
                if any(count <= 0 for count in flag_counts.values()):
                    raise RuntimeError(f"ground flag coverage insufficient: {flag_counts}")
                hourly = prepare_historical_analysis_frame(dataset)
                hourly_counts = {column: _numeric_count(hourly, column) for column in REQUIRED_CANONICAL}
                if any(count <= 0 for count in hourly_counts.values()):
                    raise RuntimeError(f"canonical hourly ground coverage insufficient: {hourly_counts}")
                mean_proof = _validate_hourly_mean(dataset.data, hourly)
                return {
                    "schema": "climate-analyzer-geosphere-ground-smoke-v1",
                    "success": True,
                    "station_id": station.station_id,
                    "station_name": station.name,
                    "state": station.state,
                    "ui_start_date": start.date().isoformat(),
                    "ui_end_date": end.date().isoformat(),
                    "native_interval_minutes": 10,
                    "required_provider_parameters": list(REQUIRED_PROVIDER),
                    "required_canonical_variables": list(REQUIRED_CANONICAL),
                    "native_valid_records": native_counts,
                    "quality_flag_valid_records": flag_counts,
                    "hourly_valid_records": hourly_counts,
                    "hourly_semantics": "mean over six complete 10-minute source intervals",
                    "independent_hourly_check": mean_proof,
                    "provider_probe_attempts": attempts,
                }
            except Exception as exc:
                failures.append(
                    f"{station.station_id} {station.name} {start.date()}..{end.date()}: "
                    f"{type(exc).__name__}: {exc}"
                )
        if attempts >= MAX_TOTAL_INTERVAL_ATTEMPTS:
            break
    raise RuntimeError(
        f"No bounded live GeoSphere interval passed tb10/tb20/tb50 validation after {attempts} attempt(s). "
        + " | ".join(failures[-12:])
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/geosphere-ground-smoke/provider-fixture.json")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fixture = find_fixture(args.timeout)
    except Exception as exc:
        path.write_text(json.dumps({
            "schema": "climate-analyzer-geosphere-ground-smoke-v1",
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
    path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(fixture, indent=2, sort_keys=True))
    print(f"Ground provider probe PASS: {fixture['station_name']} (ID {fixture['station_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
