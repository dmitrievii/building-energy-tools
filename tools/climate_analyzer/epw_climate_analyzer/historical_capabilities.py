"""Capability helpers for measured historical climate analysis views.

The historical GeoSphere route exposes only analyses whose required measured
variables are actually present in the selected interval.  Provider support in
metadata is not enough: an all-missing column does not qualify a page.
"""

from __future__ import annotations

import pandas as pd

from .aggregations import native_interval_hours


def has_numeric_observations(df: pd.DataFrame, column: str) -> bool:
    """Return True when a column exists and contains at least one finite number."""
    if column not in df.columns:
        return False
    values = pd.to_numeric(df[column], errors="coerce")
    return bool(values.notna().any())


def _requested_timeline_bounds(df: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Return the requested historical bounds when known, else observed bounds."""
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return None, None
    requested_start = df.attrs.get("canonical_requested_start")
    requested_end = df.attrs.get("canonical_requested_end")
    start = pd.to_datetime(requested_start, utc=True, errors="coerce") if requested_start else pd.NaT
    end = pd.to_datetime(requested_end, utc=True, errors="coerce") if requested_end else pd.NaT
    index = pd.DatetimeIndex(df.index).sort_values()
    if pd.isna(start):
        start = pd.Timestamp(index.min())
    if pd.isna(end):
        end = pd.Timestamp(index.max())
    return pd.Timestamp(start), pd.Timestamp(end)


def historical_coverage_summary(df: pd.DataFrame) -> dict[str, float | int | str | None]:
    """Summarize measured-timeline coverage without interpolating missing records.

    Coverage is evaluated against the exact requested interval when the adapter
    provides it. Otherwise it falls back to the first/last observed timestamp.
    A missing 10-minute source record therefore contributes one missing interval;
    a timestamp gap is never expanded into fabricated observations.
    """
    interval_h = float(native_interval_hours(df))
    interval_minutes = interval_h * 60.0
    start, end = _requested_timeline_bounds(df)
    if start is None or end is None or interval_minutes <= 0:
        return {
            "native_interval_minutes": interval_minutes if interval_minutes > 0 else None,
            "requested_start": None,
            "requested_end": None,
            "expected_records": 0,
            "observed_records": 0,
            "missing_timestamp_intervals": 0,
            "timeline_coverage_pct": 0.0,
            "gap_count": 0,
            "longest_missing_gap_minutes": 0.0,
            "observed_duration_hours": 0.0,
            "expected_duration_hours": 0.0,
        }

    step = pd.Timedelta(minutes=interval_minutes)
    expected_records = int((end - start) // step) + 1
    observed_index = pd.DatetimeIndex(df.index).drop_duplicates().sort_values()
    observed_in_range = observed_index[(observed_index >= start) & (observed_index <= end)]
    observed_records = int(len(observed_in_range))
    missing_intervals = max(0, expected_records - observed_records)

    gap_count = 0
    longest_missing = 0.0
    if observed_records:
        first_obs = pd.Timestamp(observed_in_range[0])
        last_obs = pd.Timestamp(observed_in_range[-1])

        leading_missing = max(0, int((first_obs - start) // step))
        if leading_missing:
            gap_count += 1
            longest_missing = max(longest_missing, leading_missing * interval_minutes)

        if observed_records > 1:
            for delta in observed_in_range[1:] - observed_in_range[:-1]:
                missing_between = max(0, int(round(float(delta / step))) - 1)
                if missing_between:
                    gap_count += 1
                    longest_missing = max(longest_missing, missing_between * interval_minutes)

        trailing_missing = max(0, int((end - last_obs) // step))
        if trailing_missing:
            gap_count += 1
            longest_missing = max(longest_missing, trailing_missing * interval_minutes)
    elif expected_records:
        gap_count = 1
        longest_missing = expected_records * interval_minutes

    coverage = 100.0 * observed_records / expected_records if expected_records else 0.0
    return {
        "native_interval_minutes": interval_minutes,
        "requested_start": str(start),
        "requested_end": str(end),
        "expected_records": expected_records,
        "observed_records": observed_records,
        "missing_timestamp_intervals": missing_intervals,
        "timeline_coverage_pct": coverage,
        "gap_count": gap_count,
        "longest_missing_gap_minutes": longest_missing,
        "observed_duration_hours": observed_records * interval_h,
        "expected_duration_hours": expected_records * interval_h,
    }


def historical_variable_coverage(
    df: pd.DataFrame,
    columns: tuple[str, ...] | list[str] | None = None,
) -> pd.DataFrame:
    """Return per-variable valid-record coverage against the requested timeline."""
    summary = historical_coverage_summary(df)
    expected = int(summary["expected_records"] or 0)
    interval_h = float(summary["native_interval_minutes"] or 0.0) / 60.0
    selected = list(columns) if columns is not None else list(df.columns)
    rows: list[dict[str, object]] = []
    for column in selected:
        if column not in df.columns:
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        valid = int(numeric.notna().sum())
        rows.append(
            {
                "variable": str(column),
                "valid_records": valid,
                "missing_or_unobserved_records": max(0, expected - valid),
                "observed_hours": valid * interval_h,
                "coverage_pct": (100.0 * valid / expected) if expected else 0.0,
            }
        )
    return pd.DataFrame(rows)


def available_historical_pages(df: pd.DataFrame) -> tuple[str, ...]:
    """Return source-agnostic historical pages supported by observed variables."""
    pages: list[str] = ["Climate File Source", "Overview"]
    has_temperature = has_numeric_observations(df, "dry_bulb_temperature_c")
    has_humidity = has_numeric_observations(df, "relative_humidity_pct")
    has_wind = has_numeric_observations(df, "wind_speed_m_s") or has_numeric_observations(df, "wind_direction_deg")
    has_solar = has_numeric_observations(df, "global_horizontal_radiation_wh_m2") or has_numeric_observations(
        df, "diffuse_horizontal_radiation_wh_m2"
    )

    if has_temperature:
        pages.append("Temperature")
    if has_temperature and has_humidity:
        pages.append("Humidity and Psychrometrics")
    if has_solar:
        pages.append("Solar and Radiation")
    if has_wind:
        pages.append("Wind and Ventilation")
    pages.extend(["Time Series and Overlay", "Data Quality"])
    return tuple(pages)


def horizontal_irradiance_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Add mean horizontal irradiance [W/m²] from interval irradiation columns.

    Canonical radiation variables are interval-extensive Wh/m².  For a source
    with declared native interval ``dt`` [h], mean irradiance is ``Wh/m² / dt``.
    This avoids the hourly-only numerical equivalence between Wh/m² and W/m².
    """
    result = df.copy()
    interval_h = native_interval_hours(df)
    if interval_h <= 0:
        raise ValueError("Historical radiation conversion requires a positive native interval.")
    mapping = {
        "global_horizontal_radiation_wh_m2": "global_horizontal_irradiance_w_m2",
        "diffuse_horizontal_radiation_wh_m2": "diffuse_horizontal_irradiance_w_m2",
    }
    for source, target in mapping.items():
        if source in result.columns:
            result[target] = pd.to_numeric(result[source], errors="coerce") / interval_h
    result.attrs.update(df.attrs)
    return result
