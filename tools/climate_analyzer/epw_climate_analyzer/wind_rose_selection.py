"""Independent calendar and clock-hour selection for the canonical wind rose."""
from __future__ import annotations

import pandas as pd


def _months(df: pd.DataFrame) -> pd.Series:
    if "month_index" in df:
        return pd.to_numeric(df["month_index"], errors="coerce")
    return pd.Series(pd.DatetimeIndex(df.index).month, index=df.index)


def available_wind_months(df: pd.DataFrame) -> list[int]:
    """Only valid calendar months represented in the active data filter."""
    return sorted({int(v) for v in _months(df).dropna() if v in range(1, 13)})


def select_wind_rose_period(df: pd.DataFrame, *, month: int | None = None,
                            period: str | None = None) -> pd.DataFrame:
    """Intersect calendar and clock filters without changing interval weights.

    Annual (month=None) means all currently selected dates. The historical
    day/night convention is retained: hours 7 through 19 inclusive are day.
    Missing clock hours are excluded from both day and night, never guessed.
    """
    if month is not None and month not in range(1, 13):
        raise ValueError("Wind-rose month must be in 1–12.")
    if period not in (None, "Day", "Night"):
        raise ValueError("Wind-rose period must be Day, Night or None.")
    mask = pd.Series(True, index=df.index)
    if month is not None:
        mask &= _months(df).eq(month)
    if period is not None:
        hours = (pd.to_numeric(df["hour_of_day"], errors="coerce")
                 if "hour_of_day" in df
                 else pd.Series(pd.DatetimeIndex(df.index).hour, index=df.index))
        valid = hours.between(0, 23, inclusive="both")
        day = hours.between(7, 19, inclusive="both")
        mask &= valid & (day if period == "Day" else ~day)
    result = df.loc[mask.to_numpy()].copy()
    result.attrs.update(df.attrs)
    return result
