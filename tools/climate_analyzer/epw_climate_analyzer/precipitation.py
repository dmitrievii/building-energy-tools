"""Precipitation and snow helpers for EPW climate analysis.

Liquid precipitation depth is an extensive quantity and is summed over valid EPW
records. Snow depth is a state variable: it is never summed. Missing EPW sentinel
values are already converted to NA by the parser and remain excluded here.
"""

from __future__ import annotations

import math
import pandas as pd

LIQUID_PRECIPITATION_COLUMN = "liquid_precipitation_depth_mm"
SNOW_DEPTH_COLUMN = "snow_depth_cm"
SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]
RESAMPLE_RULES = {
    "Daily": "D",
    "Weekly": "W",
    "Monthly": "ME",
}


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


def aggregate_liquid_precipitation(df: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    """Sum valid EPW liquid-precipitation depth records by period."""
    values = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    if aggregation == "Seasonal":
        frame = pd.DataFrame({"season": df.get("season"), "value": values}, index=df.index)
        totals = (
            frame.groupby("season", observed=False)["value"]
            .sum(min_count=1)
            .reindex(SEASON_ORDER)
        )
    else:
        rule = RESAMPLE_RULES.get(aggregation)
        if rule is None:
            raise ValueError(f"Unsupported precipitation aggregation: {aggregation}")
        totals = values.resample(rule).sum(min_count=1)
    return totals.dropna().rename("precipitation_mm").to_frame()


def occurrence_hours(
    df: pd.DataFrame,
    column: str,
    threshold: float,
    aggregation: str,
    *,
    inclusive: bool = True,
) -> pd.DataFrame:
    """Count valid EPW records meeting a precipitation or snow threshold."""
    values = _numeric_series(df, column)
    valid = values.notna()
    indicator = pd.Series(pd.NA, index=df.index, dtype="Float64", name="hours")
    condition = values >= float(threshold) if inclusive else values > float(threshold)
    indicator.loc[valid] = condition.loc[valid].astype(float)

    if aggregation == "Seasonal":
        frame = pd.DataFrame({"season": df.get("season"), "hours": indicator}, index=df.index)
        counts = (
            frame.groupby("season", observed=False)["hours"]
            .sum(min_count=1)
            .reindex(SEASON_ORDER)
        )
    else:
        rule = RESAMPLE_RULES.get(aggregation)
        if rule is None:
            raise ValueError(f"Unsupported occurrence aggregation: {aggregation}")
        counts = indicator.resample(rule).sum(min_count=1)
    return counts.dropna().rename("hours").to_frame()


def precipitation_summary(df: pd.DataFrame, wet_threshold_mm: float = 0.1) -> dict[str, object]:
    """Return compact precipitation/snow diagnostics for the current filtered view."""
    liquid = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    snow = _numeric_series(df, SNOW_DEPTH_COLUMN)
    liquid_available = bool(liquid.notna().any())
    snow_available = bool(snow.notna().any())

    return {
        "liquid_data_available": liquid_available,
        "snow_data_available": snow_available,
        "liquid_total_mm": _finite_or_none(liquid.sum(min_count=1)) if liquid_available else None,
        "wet_hours": int((liquid >= wet_threshold_mm).sum()) if liquid_available else None,
        "max_record_precipitation_mm": _finite_or_none(liquid.max()) if liquid_available else None,
        "max_snow_depth_cm": _finite_or_none(snow.max()) if snow_available else None,
        "snow_cover_hours": int((snow > 0.0).sum()) if snow_available else None,
    }
