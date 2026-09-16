"""Precipitation and snow helpers for canonical climate analysis.

Liquid precipitation depth is an interval-extensive measurement quantity and is
summed over valid source records. Snow depth is a state variable and is never
summed. Event-record occurrence and physical duration are intentionally kept
separate: precipitation occurrence counts source records, while snow-cover
hours integrate the declared native source cadence.
"""

from __future__ import annotations

import math
import pandas as pd

from .aggregations import native_interval_hours, period_total_series
from .temporal_filtering import TIME_BASIS_ATTR, time_basis

LIQUID_PRECIPITATION_COLUMN = "liquid_precipitation_depth_mm"
SNOW_DEPTH_COLUMN = "snow_depth_cm"


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
    """Sum valid liquid-precipitation depth records by period.

    Chronological mode preserves every real period. Calendar-profile mode first
    sums each period independently by year and then averages equivalent calendar
    periods, so a multiyear January is not reported as the sum of all Januaries.
    """
    values = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    totals = period_total_series(values, df, aggregation)
    result = totals.dropna().rename("precipitation_mm").to_frame()
    return _with_temporal_attrs(result, df, aggregation)


def occurrence_records(
    df: pd.DataFrame,
    column: str,
    threshold: float,
    aggregation: str,
    *,
    inclusive: bool = True,
) -> pd.DataFrame:
    """Count valid source records meeting a threshold.

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

    Each valid source record contributes exactly the declared native interval.
    Missing timestamp gaps therefore contribute no duration. This preserves
    hourly EPW numerics while correctly mapping a 10-minute GeoSphere record to
    one sixth of an hour.
    """
    values = _numeric_series(df, column)
    valid = values.notna()
    interval_h = float(native_interval_hours(df))
    indicator = pd.Series(pd.NA, index=df.index, dtype="Float64", name="hours")
    condition = values >= float(threshold) if inclusive else values > float(threshold)
    indicator.loc[valid] = condition.loc[valid].astype(float) * interval_h
    return _aggregate_occurrence(indicator, df, aggregation, "hours")


def precipitation_summary(df: pd.DataFrame, wet_threshold_mm: float = 0.1) -> dict[str, object]:
    """Return compact precipitation/snow diagnostics for the current filtered view."""
    liquid = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    snow = _numeric_series(df, SNOW_DEPTH_COLUMN)
    liquid_available = bool(liquid.notna().any())
    snow_available = bool(snow.notna().any())
    interval_h = float(native_interval_hours(df))

    return {
        "liquid_data_available": liquid_available,
        "snow_data_available": snow_available,
        "liquid_total_mm": _finite_or_none(liquid.sum(min_count=1)) if liquid_available else None,
        "precipitation_records": int((liquid >= wet_threshold_mm).sum()) if liquid_available else None,
        "max_record_precipitation_mm": _finite_or_none(liquid.max()) if liquid_available else None,
        "max_snow_depth_cm": _finite_or_none(snow.max()) if snow_available else None,
        "snow_cover_hours": _finite_or_none((snow > 0.0).sum() * interval_h) if snow_available else None,
    }
