"""Astronomical daylight and measured-sunshine helpers.

The functions in this module deliberately separate astronomical daylight
(duration between sunrise and sunset in an ideal geometric horizon model) from
provider-measured sunshine duration.  Sunshine is never used to fabricate sky
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
    solar elevation 0°.  Refraction, terrain and local obstructions are not
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


def monthly_daylight_sunshine_summary(
    df: pd.DataFrame,
    latitude_deg: float,
    sunshine_column: str = "sunshine_duration_s",
) -> pd.DataFrame:
    """Return monthly astronomical daylight and optional measured sunshine.

    Measured sunshine is summed from interval durations. Relative sunshine is
    the measured sunshine duration divided by the astronomical daylight duration
    represented by the same observed dates.
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
        sunshine = pd.to_numeric(df[sunshine_column], errors="coerce")
        by_day = sunshine.resample("D").sum(min_count=1) / 3600.0
        monthly_sunshine = by_day.groupby(by_day.index.month).agg(["mean", "sum", "count"])
        summary["mean_sunshine_h"] = monthly_sunshine["mean"]
        summary["total_sunshine_h"] = monthly_sunshine["sum"]
        summary["sunshine_days"] = monthly_sunshine["count"]
        summary["relative_sunshine_pct"] = 100.0 * summary["total_sunshine_h"] / summary["total_daylight_h"]
    summary = summary.reindex(range(1, 13))
    summary.index.name = "month_index"
    summary["month"] = [MONTH_LABELS[m] for m in summary.index]
    return summary.reset_index()
