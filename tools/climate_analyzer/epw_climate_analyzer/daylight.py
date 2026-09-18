"""Astronomical daylight and measured-sunshine helpers.

The functions in this module deliberately separate astronomical daylight
(duration between sunrise and sunset in an ideal geometric horizon model) from
provider-measured sunshine duration. Sunshine is never used to fabricate sky
cover, illuminance or DNI.
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

MONTH_LABELS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


def daylight_duration_hours(latitude_deg: float, day_of_year: int | np.ndarray) -> np.ndarray:
    """Return ideal astronomical daylight duration [h] for latitude/day-of-year.

    Uses the standard Cooper declination approximation and geometric sunrise at
    solar elevation 0°. Refraction, terrain and local obstructions are not
    included; the result is therefore a calculated astronomical quantity.
    """
    latitude = math.radians(float(latitude_deg))
    n = np.asarray(day_of_year, dtype=float)
    declination = np.deg2rad(23.45) * np.sin(2.0 * np.pi * (284.0 + n) / 365.0)
    argument = -np.tan(latitude) * np.tan(declination)
    daylight = np.empty_like(argument, dtype=float)
    daylight[argument <= -1.0] = 24.0
    daylight[argument >= 1.0] = 0.0
    middle = (argument > -1.0) & (argument < 1.0)
    daylight[middle] = 24.0 / np.pi * np.arccos(argument[middle])
    return daylight


def daily_daylight_table(index: pd.DatetimeIndex, latitude_deg: float) -> pd.DataFrame:
    """Return one row per represented calendar day with astronomical daylight."""
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("Daylight calculation requires a DatetimeIndex.")
    if len(index) == 0:
        return pd.DataFrame(columns=["daylight_duration_h", "month_index", "month"])
    days = pd.DatetimeIndex(index.normalize().unique()).sort_values()
    values = daylight_duration_hours(float(latitude_deg), days.dayofyear.to_numpy())
    table = pd.DataFrame({"daylight_duration_h": values}, index=days)
    table.index.name = "date"
    table["month_index"] = table.index.month.astype(int)
    table["month"] = table["month_index"].map(MONTH_LABELS)
    return table


def _complete_daily_sunshine_hours(series: pd.Series) -> pd.Series:
    """Return measured sunshine [h/day] only for fully observed calendar days.

    Missing source/canonical intervals are not silently converted to zero. The
    active frame can also be hour-filtered by the global Data filter; such
    partial days therefore do not qualify for a full-day sunshine ratio.
    """
    values = pd.to_numeric(series, errors="coerce")
    if not isinstance(values.index, pd.DatetimeIndex) or len(values.index) < 2:
        return pd.Series(dtype=float)
    ordered = values.sort_index()
    deltas = ordered.index.to_series().diff().dropna().dt.total_seconds() / 60.0
    positive = deltas[deltas > 0]
    if positive.empty:
        return pd.Series(dtype=float)
    interval_minutes = float(positive.median())
    expected_per_day = int(round(24.0 * 60.0 / interval_minutes))
    if expected_per_day <= 0:
        return pd.Series(dtype=float)
    grouped = ordered.groupby(ordered.index.normalize())
    counts = grouped.count()
    sums_h = grouped.sum(min_count=1) / 3600.0
    complete = counts == expected_per_day
    return sums_h.where(complete).dropna()


def monthly_daylight_sunshine_summary(
    df: pd.DataFrame,
    latitude_deg: float,
    sunshine_column: str = "sunshine_duration_s",
) -> pd.DataFrame:
    """Return monthly astronomical daylight and optional measured sunshine.

    Astronomical daylight uses every represented calendar date. Measured
    sunshine and the relative-sunshine ratio use only complete observed days so
    missing provider intervals are never interpreted as zero sunshine.
    """
    daylight = daily_daylight_table(pd.DatetimeIndex(df.index), latitude_deg)
    if daylight.empty:
        return pd.DataFrame()
    summary = daylight.groupby("month_index").agg(
        mean_daylight_h=("daylight_duration_h", "mean"),
        total_daylight_h=("daylight_duration_h", "sum"),
        represented_days=("daylight_duration_h", "size"),
    )
    if sunshine_column in df.columns:
        complete_daily_sunshine = _complete_daily_sunshine_hours(df[sunshine_column])
        if not complete_daily_sunshine.empty:
            monthly_sunshine = complete_daily_sunshine.groupby(complete_daily_sunshine.index.month).agg(["mean", "sum", "count"])
            summary["mean_sunshine_h"] = monthly_sunshine["mean"]
            summary["total_sunshine_h"] = monthly_sunshine["sum"]
            summary["sunshine_days"] = monthly_sunshine["count"]

            observed_daylight = daylight.reindex(complete_daily_sunshine.index)["daylight_duration_h"]
            monthly_observed_daylight = observed_daylight.groupby(observed_daylight.index.month).sum(min_count=1)
            summary["observed_daylight_h"] = monthly_observed_daylight
            summary["relative_sunshine_pct"] = (
                100.0 * summary["total_sunshine_h"] / summary["observed_daylight_h"]
            )
    summary = summary.reindex(range(1, 13))
    summary.index.name = "month_index"
    summary["month"] = [MONTH_LABELS[m] for m in summary.index]
    return summary.reset_index()
