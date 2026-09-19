#!/usr/bin/env python3
"""Provider-backed smoke probe for GeoSphere ``klima-v2-1h`` integration.

The probe deliberately uses the production adapter and canonical historical
analysis path. It validates live metadata, fetches real hourly observations,
confirms that native-hourly data take the no-resampling fast path, verifies the
hourly sunshine-duration conversion exposed by the long-term resource, records
station-dependent deep-ground coverage, and verifies calculated DNI only when
the live resource exposes both GHI and DHI.
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
    resource_spec,
    supported_parameter_mapping,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame
from epw_climate_analyzer.solar import variable_origin


RESOURCE_ID = "klima-v2-1h"
CORE_CANONICAL = (
    "dry_bulb_temperature_c",
    "relative_humidity_pct",
    "atmospheric_station_pressure_pa",
    "wind_speed_m_s",
    "wind_direction_deg",
)
HOURLY_REQUIRED_EXTRAS = (
    "sunshine_duration_s",
    "global_horizontal_radiation_wh_m2",
)
DEEP_GROUND_CANONICAL = (
    "ground_temperature_1_00m_c",
    "ground_temperature_2_00m_c",
)
DNI_INPUTS = (
    "global_horizontal_radiation_wh_m2",
    "diffuse_horizontal_radiation_wh_m2",
)
PREFERRED_STATION_NAMES = (
    "Wien Hohe Warte",
    "Graz Universität",
    "Salzburg Flughafen",
    "Innsbruck Universität",
    "Klagenfurt Flughafen",
)
MAX_STATIONS_TO_PROBE = 24
MAX_TOTAL_INTERVAL_ATTEMPTS = 60
WINDOW_DAYS = 2
YEARS_BACK = 4


def _parse_date(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _validity_bounds(station: GeoSphereStation) -> tuple[pd.Timestamp, pd.Timestamp]:
    today = pd.Timestamp.now(tz="UTC").normalize()
    parsed_start = _parse_date(station.valid_from)
    parsed_end = _parse_date(station.valid_to)
    start = parsed_start.normalize() if parsed_start is not None else pd.Timestamp("1880-01-01", tz="UTC")
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
        end = start + pd.Timedelta(days=WINDOW_DAYS - 1, hours=23)
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
            station.has_sunshine is not True,
            station.has_global_radiation is not True,
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


def _assert_fast_path(native: pd.DataFrame, hourly: pd.DataFrame, preserved_columns: Iterable[str]) -> None:
    if len(native) != len(hourly):
        raise RuntimeError(f"hourly fast path changed row count: native={len(native)}, analysis={len(hourly)}")
    if not pd.DatetimeIndex(native.index).equals(pd.DatetimeIndex(hourly.index)):
        raise RuntimeError("hourly fast path changed the provider timestamp grid")
    if int(hourly.attrs.get("canonical_hourly_expected_source_records", -1)) != 1:
        raise RuntimeError("canonical hourly engine did not report the native-hourly fast path")
    if int(hourly.attrs.get("canonical_source_interval_minutes", -1)) != 60:
        raise RuntimeError("canonical hourly output lost the 60-minute source cadence")
    for column in preserved_columns:
        if column not in native.columns or column not in hourly.columns:
            continue
        source = pd.to_numeric(native[column], errors="coerce")
        target = pd.to_numeric(hourly[column], errors="coerce")
        if not source.equals(target):
            raise RuntimeError(f"hourly fast path altered source values for {column}")


def _assert_hourly_sunshine_seconds(frame: pd.DataFrame) -> dict[str, float | int]:
    values = pd.to_numeric(frame.get("sunshine_duration_s"), errors="coerce").dropna()
    if values.empty:
        raise RuntimeError("live hourly resource returned no numeric sunshine-duration values")
    if float(values.min()) < -1e-9 or float(values.max()) > 3600.0 + 1e-6:
        raise RuntimeError(
            "hourly sunshine conversion is outside the physical 0..3600 s interval; "
            f"observed {float(values.min()):.3f}..{float(values.max()):.3f} s"
        )
    if not bool((values > 0.0).any()):
        raise RuntimeError("live hourly sunshine probe found only zero sunshine; choose another interval")
    return {
        "valid_records": int(len(values)),
        "positive_records": int((values > 0.0).sum()),
        "minimum_s": float(values.min()),
        "maximum_s": float(values.max()),
        "sum_h": float(values.sum() / 3600.0),
    }


def find_fixture(timeout_s: int) -> dict[str, object]:
    spec = resource_spec(RESOURCE_ID)
    if int(spec.native_interval_minutes) != 60:
        raise RuntimeError("klima-v2-1h production resource spec is not native hourly")

    metadata = fetch_metadata(resource_id=RESOURCE_ID, timeout_s=timeout_s)
    mapping = supported_parameter_mapping(metadata, resource_id=RESOURCE_ID)
    canonical_to_provider = {field.canonical_name: provider for provider, field in mapping.items()}
    missing_core = [column for column in CORE_CANONICAL if column not in canonical_to_provider]
    if missing_core:
        raise RuntimeError("live hourly metadata miss core canonical variables: " + ", ".join(missing_core))
    if canonical_to_provider.get("wind_speed_m_s") != "ff":
        raise RuntimeError("live hourly wind contract is not ff -> wind_speed_m_s")

    missing_extras = [column for column in HOURLY_REQUIRED_EXTRAS if column not in canonical_to_provider]
    if missing_extras:
        raise RuntimeError(
            "live hourly metadata miss required long-term integration fields: " + ", ".join(missing_extras)
        )
    if canonical_to_provider.get("sunshine_duration_s") != "so_h":
        raise RuntimeError("live hourly sunshine contract is not so_h -> sunshine_duration_s")

    dni_supported = all(column in canonical_to_provider for column in DNI_INPUTS)
    optional_deep_ground = [column for column in DEEP_GROUND_CANONICAL if column in canonical_to_provider]
    requested = list(dict.fromkeys(CORE_CANONICAL + HOURLY_REQUIRED_EXTRAS + tuple(optional_deep_ground)))
    if dni_supported:
        requested.extend(column for column in DNI_INPUTS if column not in requested)

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
                    resource_id=RESOURCE_ID,
                    metadata=metadata,
                    canonical_variables=requested,
                    timeout_s=timeout_s,
                )
                if int(dataset.temporal.native_interval_minutes) != 60:
                    raise RuntimeError("canonical dataset does not retain the 60-minute native cadence")
                native_counts = {column: _valid_count(dataset.data, column) for column in CORE_CANONICAL}
                if any(count <= 0 for count in native_counts.values()):
                    raise RuntimeError(f"core hourly coverage insufficient: {native_counts}")

                sunshine_evidence = _assert_hourly_sunshine_seconds(dataset.data)
                ghi_count = _valid_count(dataset.data, "global_horizontal_radiation_wh_m2")
                if ghi_count <= 0:
                    raise RuntimeError("live hourly resource returned no numeric GHI in the probe interval")

                deep_ground_counts = {
                    column: _valid_count(dataset.data, column)
                    for column in optional_deep_ground
                }
                dni_input_counts = {
                    column: _valid_count(dataset.data, column)
                    for column in DNI_INPUTS
                    if column in dataset.data.columns
                }
                if dni_supported and any(dni_input_counts.get(column, 0) <= 0 for column in DNI_INPUTS):
                    raise RuntimeError(f"hourly GHI/DHI coverage insufficient: {dni_input_counts}")

                hourly = prepare_historical_analysis_frame(
                    dataset,
                    include_psychrometrics=True,
                    include_solar=True,
                )
                _assert_fast_path(
                    dataset.data,
                    hourly,
                    CORE_CANONICAL + HOURLY_REQUIRED_EXTRAS + tuple(optional_deep_ground),
                )

                calculated_dni_count = 0
                dni_origin = "not available — hourly resource publishes GHI without DHI"
                if dni_supported:
                    calculated_dni_count = _valid_count(hourly, "direct_normal_radiation_wh_m2")
                    if calculated_dni_count <= 0:
                        raise RuntimeError("GHI+DHI were live but the source-neutral engine produced no calculable DNI")
                    dni_origin = variable_origin(hourly, "direct_normal_radiation_wh_m2")
                    if "calculated" not in dni_origin.casefold():
                        raise RuntimeError(f"derived DNI is not explicitly marked calculated: {dni_origin}")

                return {
                    "schema": "climate-analyzer-geosphere-hourly-smoke-v2",
                    "success": True,
                    "resource_id": RESOURCE_ID,
                    "station_id": station.station_id,
                    "station_name": station.name,
                    "state": station.state,
                    "probe_start": start.isoformat(),
                    "probe_end": end.isoformat(),
                    "native_interval_minutes": int(dataset.temporal.native_interval_minutes),
                    "native_rows": len(dataset.data),
                    "analysis_rows": len(hourly),
                    "canonical_hourly_expected_source_records": int(hourly.attrs.get("canonical_hourly_expected_source_records", -1)),
                    "core_provider_mapping": {column: canonical_to_provider[column] for column in CORE_CANONICAL},
                    "core_valid_records": native_counts,
                    "hourly_extra_provider_mapping": {
                        column: canonical_to_provider[column]
                        for column in HOURLY_REQUIRED_EXTRAS + tuple(optional_deep_ground)
                    },
                    "sunshine_duration_evidence": sunshine_evidence,
                    "ghi_valid_records": ghi_count,
                    "deep_ground_valid_records": deep_ground_counts,
                    "dni_reconstruction_supported_by_live_metadata": dni_supported,
                    "dni_input_valid_records": dni_input_counts,
                    "calculated_dni_valid_records": calculated_dni_count,
                    "dni_origin": dni_origin,
                    "provider_probe_attempts": attempts,
                    "fast_path": "PASS — native 60-minute timestamps and measured canonical values preserved without temporal resampling",
                }
            except Exception as exc:
                failures.append(
                    f"{station.station_id} {station.name} {start.date()}..{end.date()}: "
                    f"{type(exc).__name__}: {exc}"
                )
        if attempts >= MAX_TOTAL_INTERVAL_ATTEMPTS:
            break

    tail = " | ".join(failures[-15:])
    raise RuntimeError(
        f"No bounded live {RESOURCE_ID} interval passed metadata + hourly extras + data + fast-path validation after {attempts} attempt(s). "
        + tail
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/geosphere-hourly-smoke/provider-fixture.json")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fixture = find_fixture(timeout_s=args.timeout)
    except Exception as exc:
        failure = {
            "schema": "climate-analyzer-geosphere-hourly-smoke-v2",
            "success": False,
            "resource_id": RESOURCE_ID,
            "error": f"{type(exc).__name__}: {exc}",
        }
        path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise

    path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(fixture, indent=2, sort_keys=True))
    print(
        f"GeoSphere hourly provider probe PASS: {fixture['station_name']} (ID {fixture['station_id']}), "
        f"{fixture['probe_start']} → {fixture['probe_end']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
