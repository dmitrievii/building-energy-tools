#!/usr/bin/env python3
"""Provider-backed smoke probe for Climate Analyzer 0.7.3 GeoSphere Priority-A fields.

The probe uses the production GeoSphere adapter and live ``klima-v2-10min``
metadata/data. It searches a bounded set of recent station intervals until it
finds real numeric observations for tlmin/tlmax/ffx/ddx/so, then validates the
canonical hourly quantity semantics and native matching quality-flag retention.
No provider values are frozen into the repository.
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


REQUIRED_PROVIDER = ("tlmin", "tlmax", "ffx", "ddx", "so")
REQUIRED_CANONICAL = tuple(FIELD_SPEC_BY_PROVIDER[name].canonical_name for name in REQUIRED_PROVIDER)
PREFERRED_STATION_NAMES = (
    "Wien Hohe Warte",
    "Graz Universität",
    "Salzburg Flughafen",
    "Innsbruck Universität",
    "Klagenfurt Flughafen",
)
MAX_STATIONS_TO_PROBE = 20
MAX_TOTAL_INTERVAL_ATTEMPTS = 40
WINDOW_DAYS = 2
YEARS_BACK = 2


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

    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for start in candidates:
        end = start + pd.Timedelta(days=WINDOW_DAYS - 1, hours=23, minutes=50)
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
    remaining = [station for station in stations if station not in ordered]
    remaining.sort(
        key=lambda station: (
            station.is_active is not True,
            station.name.casefold(),
            station.station_id,
        )
    )
    ordered.extend(remaining)
    return ordered[:MAX_STATIONS_TO_PROBE]


def _valid_count(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").notna().sum())


def _flag_count(frame: pd.DataFrame, provider_name: str) -> int:
    column = quality_flag_column(provider_name)
    if column not in frame.columns:
        return 0
    return int(frame[column].notna().sum())


def _validate_hourly_semantics(native: pd.DataFrame, hourly: pd.DataFrame) -> None:
    if hourly.empty:
        raise RuntimeError("strict canonical hourly frame is empty")

    # Choose a complete hour where every Priority-A field is numeric at all six
    # source timestamps and compare production reductions against direct source
    # calculations. This validates semantics on actual provider values.
    numeric = native[list(REQUIRED_CANONICAL)].apply(pd.to_numeric, errors="coerce")
    source_counts = numeric.notna().astype(int).resample("h").sum()
    complete_hours = source_counts.index[(source_counts == 6).all(axis=1)]
    if len(complete_hours) == 0:
        raise RuntimeError("no fully observed native hour exists for all Priority-A quantities")

    hour = pd.Timestamp(complete_hours[0])
    source = numeric.loc[(numeric.index >= hour) & (numeric.index < hour + pd.Timedelta(hours=1))]
    if hour not in hourly.index:
        raise RuntimeError("complete source hour is absent from canonical hourly output")
    row = hourly.loc[hour]

    tlmin = FIELD_SPEC_BY_PROVIDER["tlmin"].canonical_name
    tlmax = FIELD_SPEC_BY_PROVIDER["tlmax"].canonical_name
    ffx = FIELD_SPEC_BY_PROVIDER["ffx"].canonical_name
    ddx = FIELD_SPEC_BY_PROVIDER["ddx"].canonical_name
    so = FIELD_SPEC_BY_PROVIDER["so"].canonical_name

    expected_gust = float(source[ffx].max())
    gust_rows = source[source[ffx] == expected_gust]
    expected_direction = float(gust_rows.iloc[0][ddx]) % 360.0

    checks = {
        "tlmin_min": (float(row[tlmin]), float(source[tlmin].min())),
        "tlmax_max": (float(row[tlmax]), float(source[tlmax].max())),
        "ffx_max": (float(row[ffx]), expected_gust),
        "ddx_paired": (float(row[ddx]) % 360.0, expected_direction),
        "so_sum": (float(row[so]), float(source[so].sum())),
    }
    failures = {
        name: {"actual": actual, "expected": expected}
        for name, (actual, expected) in checks.items()
        if abs(actual - expected) > 1e-9
    }
    if failures:
        raise RuntimeError(f"canonical hourly Priority-A semantics mismatch: {failures}")


def find_fixture(timeout_s: int) -> dict[str, object]:
    metadata = fetch_metadata(timeout_s=timeout_s)
    supported = supported_parameter_mapping(metadata)
    missing_resource = [name for name in REQUIRED_PROVIDER if name not in supported]
    if missing_resource:
        raise RuntimeError(
            "GeoSphere live metadata no longer expose required Priority-A fields: " + ", ".join(missing_resource)
        )

    parameters = metadata.get("parameters")
    live_parameter_names = {
        str(item.get("name"))
        for item in parameters
        if isinstance(item, dict) and item.get("name")
    } if isinstance(parameters, list) else set()
    missing_flags = [f"{name}_flag" for name in REQUIRED_PROVIDER if f"{name}_flag" not in live_parameter_names]
    if missing_flags:
        raise RuntimeError("GeoSphere live metadata no longer expose matching Priority-A quality flags: " + ", ".join(missing_flags))

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
                native_counts = {column: _valid_count(dataset.data, column) for column in REQUIRED_CANONICAL}
                if any(count <= 0 for count in native_counts.values()):
                    raise RuntimeError(f"native Priority-A coverage insufficient: {native_counts}")

                flag_counts = {name: _flag_count(dataset.data, name) for name in REQUIRED_PROVIDER}
                if any(count <= 0 for count in flag_counts.values()):
                    raise RuntimeError(f"matching quality-flag coverage insufficient: {flag_counts}")

                hourly = prepare_historical_analysis_frame(dataset)
                hourly_counts = {column: _valid_count(hourly, column) for column in REQUIRED_CANONICAL}
                if any(count <= 0 for count in hourly_counts.values()):
                    raise RuntimeError(f"strict hourly Priority-A coverage insufficient: {hourly_counts}")
                _validate_hourly_semantics(dataset.data, hourly)

                return {
                    "schema": "climate-analyzer-geosphere-priority-a-smoke-v1",
                    "success": True,
                    "station_id": station.station_id,
                    "station_name": station.name,
                    "state": station.state,
                    "ui_start_date": start.date().isoformat(),
                    "ui_end_date": end.date().isoformat(),
                    "probe_start": start.isoformat(),
                    "probe_end": end.isoformat(),
                    "native_interval_minutes": 10,
                    "required_provider_parameters": list(REQUIRED_PROVIDER),
                    "required_canonical_variables": list(REQUIRED_CANONICAL),
                    "native_valid_records": native_counts,
                    "quality_flag_valid_records": flag_counts,
                    "hourly_valid_records": hourly_counts,
                    "provider_probe_attempts": attempts,
                    "hourly_semantics": {
                        "tlmin": "min",
                        "tlmax": "max",
                        "ffx": "max",
                        "ddx": "direction paired with governing ffx row",
                        "so": "sum",
                    },
                }
            except Exception as exc:
                failures.append(
                    f"{station.station_id} {station.name} {start.date()}..{end.date()}: "
                    f"{type(exc).__name__}: {exc}"
                )
        if attempts >= MAX_TOTAL_INTERVAL_ATTEMPTS:
            break

    tail = " | ".join(failures[-12:])
    raise RuntimeError(
        f"No bounded live GeoSphere interval passed Priority-A data + flag semantics after {attempts} attempt(s). " + tail
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/geosphere-priority-a-smoke/provider-fixture.json")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fixture = find_fixture(timeout_s=args.timeout)
    except Exception as exc:
        failure = {
            "schema": "climate-analyzer-geosphere-priority-a-smoke-v1",
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise

    path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(fixture, indent=2, sort_keys=True))
    print(
        f"Priority-A provider probe PASS: {fixture['station_name']} (ID {fixture['station_id']}), "
        f"{fixture['ui_start_date']} → {fixture['ui_end_date']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
