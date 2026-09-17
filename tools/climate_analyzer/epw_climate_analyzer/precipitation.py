"""Precipitation and snow helpers for canonical climate analysis.

Scientific quantity semantics are explicit:

* liquid precipitation depth is interval-extensive and is summed;
* measured precipitation duration is interval-extensive and is summed only when
  the provider exposes an independent duration field;
* precipitation record occurrence is a source-record count, never rain hours;
* snow depth is a state variable and is never summed;
* snow-cover duration integrates the declared cadence of the frame supplied to
  the helper, so provider-native state duration remains available where needed.
"""

from __future__ import annotations

import math
import pandas as pd

from .aggregations import native_interval_hours, period_total_series
from .temporal_filtering import TIME_BASIS_ATTR, time_basis

LIQUID_PRECIPITATION_COLUMN = "liquid_precipitation_depth_mm"
PRECIPITATION_DURATION_COLUMN = "precipitation_duration_min"
SNOW_DEPTH_COLUMN = "snow_depth_cm"

WET_DAY_THRESHOLD_MM = 1.0
HEAVY_PRECIPITATION_DAY_THRESHOLD_MM = 10.0
VERY_HEAVY_PRECIPITATION_DAY_THRESHOLD_MM = 20.0
MEANINGFUL_SNOW_DEPTH_CM = 5.0
DEFAULT_SNOW_SEASON_START_MONTH = 7


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(index=df.index, dtype=float, name=column)
    return pd.to_numeric(df[column], errors="coerce").rename(column)


def _finite_or_none(value) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _with_temporal_attrs(result: pd.DataFrame, df: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    result.attrs.update(dict(df.attrs))
    result.attrs[TIME_BASIS_ATTR] = time_basis(df)
    result.attrs["aggregation"] = aggregation
    return result


def _aggregate_occurrence(indicator: pd.Series, df: pd.DataFrame, aggregation: str, label: str) -> pd.DataFrame:
    result = period_total_series(indicator, df, aggregation).dropna().rename(label).to_frame()
    return _with_temporal_attrs(result, df, aggregation)


def aggregate_liquid_precipitation(df: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    """Sum valid liquid-precipitation interval depth by period.

    Chronological mode preserves every real period. Calendar-profile mode first
    totals each period independently by year and then averages equivalent
    calendar periods, so a multiyear January is not reported as the sum of all
    Januaries.
    """
    values = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    totals = period_total_series(values, df, aggregation)
    result = totals.dropna().rename("precipitation_mm").to_frame()
    return _with_temporal_attrs(result, df, aggregation)


def aggregate_precipitation_duration(df: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    """Sum independently measured precipitation duration by period.

    The function never derives duration from precipitation depth. If the source
    does not expose ``precipitation_duration_min`` the returned table is empty.
    """
    values = _numeric_series(df, PRECIPITATION_DURATION_COLUMN)
    if not values.notna().any():
        return _with_temporal_attrs(pd.DataFrame(columns=["duration_min"]), df, aggregation)
    totals = period_total_series(values, df, aggregation)
    result = totals.dropna().rename("duration_min").to_frame()
    return _with_temporal_attrs(result, df, aggregation)


def occurrence_records(
    df: pd.DataFrame,
    column: str,
    threshold: float,
    aggregation: str,
    *,
    inclusive: bool = True,
) -> pd.DataFrame:
    """Count valid records meeting a threshold.

    This is deliberately a record-occurrence metric. It must not be presented
    as rainfall duration because a precipitation-depth record describes an
    interval amount and does not identify how long rain occurred inside it.
    """
    values = _numeric_series(df, column)
    valid = values.notna()
    indicator = pd.Series(pd.NA, index=df.index, dtype="Float64", name="records")
    condition = values >= float(threshold) if inclusive else values > float(threshold)
    indicator.loc[valid] = condition.loc[valid].astype(float)
    return _aggregate_occurrence(indicator, df, aggregation, "records")


def occurrence_hours(
    df: pd.DataFrame,
    column: str,
    threshold: float,
    aggregation: str,
    *,
    inclusive: bool = True,
) -> pd.DataFrame:
    """Integrate physical hours for a thresholded state variable.

    Each valid record contributes exactly the declared cadence of ``df``.
    Missing timestamps contribute no duration. For provider-native GeoSphere
    data one 10-minute snow-state record therefore contributes one sixth hour.
    """
    values = _numeric_series(df, column)
    valid = values.notna()
    interval_h = float(native_interval_hours(df))
    indicator = pd.Series(pd.NA, index=df.index, dtype="Float64", name="hours")
    condition = values >= float(threshold) if inclusive else values > float(threshold)
    indicator.loc[valid] = condition.loc[valid].astype(float) * interval_h
    return _aggregate_occurrence(indicator, df, aggregation, "hours")


def daily_precipitation_totals(df: pd.DataFrame) -> pd.Series:
    """Return daily precipitation totals, retaining NaN for fully unobserved days."""
    values = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    if values.empty:
        return pd.Series(dtype=float, name="precipitation_mm")
    daily = values.resample("D").sum(min_count=1).rename("precipitation_mm")
    return daily


def _longest_dry_spell(valid_daily: pd.Series, wet_threshold_mm: float) -> int:
    longest = 0
    current = 0
    for value in valid_daily.tolist():
        if pd.isna(value):
            current = 0
            continue
        if float(value) < float(wet_threshold_mm):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def annual_precipitation_indices(
    df: pd.DataFrame,
    *,
    wet_threshold_mm: float = WET_DAY_THRESHOLD_MM,
    heavy_threshold_mm: float = HEAVY_PRECIPITATION_DAY_THRESHOLD_MM,
    very_heavy_threshold_mm: float = VERY_HEAVY_PRECIPITATION_DAY_THRESHOLD_MM,
) -> pd.DataFrame:
    """Return annual precipitation totals/extremes and dry-spell indices.

    Day thresholds are evaluated from daily precipitation totals in the current
    filtered view. A fully unobserved day remains NaN and breaks a dry spell; it
    is never silently interpreted as a zero-precipitation day.
    """
    daily = daily_precipitation_totals(df)
    columns = [
        "year",
        "precipitation_total_mm",
        "wet_days_ge_1mm",
        "heavy_days_ge_10mm",
        "very_heavy_days_ge_20mm",
        "max_daily_precipitation_mm",
        "longest_dry_spell_days",
        "valid_daily_totals",
    ]
    rows: list[dict[str, object]] = []
    if daily.empty:
        return pd.DataFrame(columns=columns)

    for year in sorted({int(value) for value in daily.index.year}):
        subset = daily[daily.index.year == year]
        valid = subset.dropna()
        if valid.empty:
            continue
        rows.append(
            {
                "year": year,
                "precipitation_total_mm": float(valid.sum()),
                "wet_days_ge_1mm": int((valid >= float(wet_threshold_mm)).sum()),
                "heavy_days_ge_10mm": int((valid >= float(heavy_threshold_mm)).sum()),
                "very_heavy_days_ge_20mm": int((valid >= float(very_heavy_threshold_mm)).sum()),
                "max_daily_precipitation_mm": float(valid.max()),
                "longest_dry_spell_days": _longest_dry_spell(subset, float(wet_threshold_mm)),
                "valid_daily_totals": int(valid.size),
            }
        )

    result = pd.DataFrame(rows, columns=columns)
    duration = _numeric_series(df, PRECIPITATION_DURATION_COLUMN)
    if not result.empty and duration.notna().any():
        duration_by_year = duration.groupby(pd.DatetimeIndex(duration.index).year).sum(min_count=1) / 60.0
        result["measured_precipitation_duration_h"] = result["year"].map(duration_by_year.to_dict())
    return result


def annual_native_precipitation_peaks(df: pd.DataFrame) -> pd.DataFrame:
    """Return annual maximum provider-native precipitation interval values.

    This helper is intentionally native-resolution. It must not be used on an
    hourly-normalized frame when the requested metric is a true 10-minute
    GeoSphere maximum.
    """
    values = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    rows: list[dict[str, object]] = []
    if not values.notna().any():
        return pd.DataFrame(columns=["year", "max_native_interval_mm", "max_native_interval_timestamp"])
    for year in sorted({int(value) for value in pd.DatetimeIndex(values.index).year}):
        subset = values[pd.DatetimeIndex(values.index).year == year].dropna()
        if subset.empty:
            continue
        timestamp = pd.Timestamp(subset.idxmax())
        rows.append(
            {
                "year": year,
                "max_native_interval_mm": float(subset.max()),
                "max_native_interval_timestamp": timestamp,
            }
        )
    result = pd.DataFrame(rows)
    result.attrs.update(dict(df.attrs))
    result.attrs["native_interval_minutes"] = float(native_interval_hours(df)) * 60.0
    return result


def daily_snow_depth_max(df: pd.DataFrame) -> pd.Series:
    """Return daily maximum observed snow depth state."""
    values = _numeric_series(df, SNOW_DEPTH_COLUMN)
    if values.empty:
        return pd.Series(dtype=float, name="snow_depth_cm")
    return values.resample("D").max().rename("snow_depth_cm")


def snow_season_indices(
    df: pd.DataFrame,
    *,
    season_start_month: int = DEFAULT_SNOW_SEASON_START_MONTH,
    cover_threshold_cm: float = 0.0,
    meaningful_threshold_cm: float = MEANINGFUL_SNOW_DEPTH_CM,
) -> pd.DataFrame:
    """Return snow-season indices from state observations.

    Seasons use a transparent July–June analysis year by default so autumn and
    spring snow belonging to one cold season are not split at 31 December. The
    start month is configurable for future use. Missing days do not count as
    snow-cover days.
    """
    start_month = int(season_start_month)
    if not 1 <= start_month <= 12:
        raise ValueError("Snow-season start month must be between 1 and 12.")
    daily = daily_snow_depth_max(df)
    columns = [
        "season",
        "season_start_year",
        "snow_cover_days",
        "days_gt_5cm",
        "max_snow_depth_cm",
        "first_snow_date",
        "last_snow_date",
        "snow_season_span_days",
        "valid_snow_days",
    ]
    if daily.empty:
        return pd.DataFrame(columns=columns)

    idx = pd.DatetimeIndex(daily.index)
    season_year = pd.Series(
        [int(stamp.year) if int(stamp.month) >= start_month else int(stamp.year) - 1 for stamp in idx],
        index=idx,
        dtype=int,
    )
    rows: list[dict[str, object]] = []
    for start_year in sorted(season_year.unique().tolist()):
        subset = daily.loc[season_year == int(start_year)]
        valid = subset.dropna()
        if valid.empty:
            continue
        cover = valid > float(cover_threshold_cm)
        meaningful = valid > float(meaningful_threshold_cm)
        snow_dates = valid.index[cover]
        first_date = pd.Timestamp(snow_dates.min()) if len(snow_dates) else pd.NaT
        last_date = pd.Timestamp(snow_dates.max()) if len(snow_dates) else pd.NaT
        span = int((last_date.normalize() - first_date.normalize()).days) + 1 if pd.notna(first_date) and pd.notna(last_date) else 0
        rows.append(
            {
                "season": f"{int(start_year)}/{str(int(start_year) + 1)[-2:]}",
                "season_start_year": int(start_year),
                "snow_cover_days": int(cover.sum()),
                "days_gt_5cm": int(meaningful.sum()),
                "max_snow_depth_cm": float(valid.max()),
                "first_snow_date": first_date,
                "last_snow_date": last_date,
                "snow_season_span_days": span,
                "valid_snow_days": int(valid.size),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def precipitation_summary(df: pd.DataFrame, wet_threshold_mm: float = 0.1) -> dict[str, object]:
    """Return compact precipitation/snow diagnostics for the supplied frame."""
    liquid = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    duration = _numeric_series(df, PRECIPITATION_DURATION_COLUMN)
    snow = _numeric_series(df, SNOW_DEPTH_COLUMN)
    liquid_available = bool(liquid.notna().any())
    duration_available = bool(duration.notna().any())
    snow_available = bool(snow.notna().any())
    interval_h = float(native_interval_hours(df))

    return {
        "liquid_data_available": liquid_available,
        "precipitation_duration_available": duration_available,
        "snow_data_available": snow_available,
        "liquid_total_mm": _finite_or_none(liquid.sum(min_count=1)) if liquid_available else None,
        "precipitation_records": int((liquid >= wet_threshold_mm).sum()) if liquid_available else None,
        "max_record_precipitation_mm": _finite_or_none(liquid.max()) if liquid_available else None,
        "measured_precipitation_duration_min": _finite_or_none(duration.sum(min_count=1)) if duration_available else None,
        "max_snow_depth_cm": _finite_or_none(snow.max()) if snow_available else None,
        "snow_cover_hours": _finite_or_none((snow > 0.0).sum() * interval_h) if snow_available else None,
    }
