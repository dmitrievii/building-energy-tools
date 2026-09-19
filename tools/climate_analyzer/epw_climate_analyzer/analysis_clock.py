"""Analysis-clock conversion for provider-neutral climate DataFrames.

Source timestamps and analysis/calendar time are deliberately separate concepts.
Measured APIs may publish UTC instants while building-design questions (occupied
hours, night-time overheating, day/night wind, month-hour heatmaps) are normally
asked in the station's local clock.  These helpers convert only the DataFrame
index representation; they never alter the physical instants or source data.

Typical-year EPW frames are commonly stored on a naive local-standard plotting
calendar.  That representation is preserved by default.  Historical timezone-
aware frames can be viewed in source time, local civil time (including DST), or
a fixed local-standard offset.
"""

from __future__ import annotations

from datetime import timedelta, timezone
from typing import Literal

import pandas as pd


AnalysisClockMode = Literal["source", "local_civil", "local_standard", "utc"]
SOURCE_TIME = "source"
LOCAL_CIVIL_TIME = "local_civil"
LOCAL_STANDARD_TIME = "local_standard"
UTC_TIME = "utc"

ANALYSIS_CLOCK_ATTR = "canonical_analysis_clock_mode"
ANALYSIS_TIMEZONE_ATTR = "canonical_analysis_timezone_name"
SOURCE_TIMEZONE_ATTR = "canonical_source_timezone_name"


def _fixed_offset(offset_hours: float) -> timezone:
    minutes = int(round(float(offset_hours) * 60.0))
    return timezone(timedelta(minutes=minutes))


def analysis_index(
    index: pd.DatetimeIndex,
    *,
    mode: AnalysisClockMode = LOCAL_CIVIL_TIME,
    local_timezone_name: str | None = None,
    standard_utc_offset_hours: float | None = None,
    source_timezone_name: str | None = None,
) -> pd.DatetimeIndex:
    """Return one analysis-clock representation of the same timestamp sequence.

    For timezone-aware input, ``tz_convert`` is used exclusively: UTC instants
    remain exact and DST duplicate civil-hour labels stay unambiguous because
    their UTC offsets differ.  Naive input is treated as an already-established
    source/plotting calendar unless sufficient timezone metadata is supplied.
    """
    idx = pd.DatetimeIndex(index)
    if mode not in {SOURCE_TIME, LOCAL_CIVIL_TIME, LOCAL_STANDARD_TIME, UTC_TIME}:
        raise ValueError(f"Unsupported analysis clock mode: {mode}")

    if idx.tz is None:
        if mode == SOURCE_TIME:
            return idx
        if mode == LOCAL_CIVIL_TIME:
            if not local_timezone_name:
                return idx
            # Naive historical/custom timestamps need an explicit localization
            # contract; EPW typical-year callers normally stay in source/local
            # standard mode and therefore do not pass through this branch.
            return idx.tz_localize(
                str(local_timezone_name), ambiguous="infer", nonexistent="shift_forward"
            )
        if mode == LOCAL_STANDARD_TIME:
            if standard_utc_offset_hours is None:
                return idx
            return idx.tz_localize(_fixed_offset(float(standard_utc_offset_hours)))
        # UTC conversion of naive timestamps is safe only when their source
        # timezone/standard offset is explicitly known.
        if source_timezone_name:
            localized = idx.tz_localize(
                str(source_timezone_name), ambiguous="infer", nonexistent="shift_forward"
            )
            return localized.tz_convert("UTC")
        if standard_utc_offset_hours is not None:
            return idx.tz_localize(_fixed_offset(float(standard_utc_offset_hours))).tz_convert("UTC")
        return idx.tz_localize("UTC")

    if mode == SOURCE_TIME:
        return idx
    if mode == UTC_TIME:
        return idx.tz_convert("UTC")
    if mode == LOCAL_CIVIL_TIME:
        if not local_timezone_name:
            return idx
        return idx.tz_convert(str(local_timezone_name))
    if standard_utc_offset_hours is None:
        raise ValueError("Local-standard analysis time requires standard_utc_offset_hours.")
    return idx.tz_convert(_fixed_offset(float(standard_utc_offset_hours)))


def with_analysis_clock(
    df: pd.DataFrame,
    *,
    mode: AnalysisClockMode = LOCAL_CIVIL_TIME,
    local_timezone_name: str | None = None,
    standard_utc_offset_hours: float | None = None,
    source_timezone_name: str | None = None,
) -> pd.DataFrame:
    """Return a shallow climate frame whose index is expressed in analysis time."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Climate analysis clock requires a pandas DatetimeIndex.")
    data = df.copy(deep=False)
    attrs = dict(df.attrs)
    data.index = analysis_index(
        pd.DatetimeIndex(df.index),
        mode=mode,
        local_timezone_name=local_timezone_name,
        standard_utc_offset_hours=standard_utc_offset_hours,
        source_timezone_name=source_timezone_name,
    )
    data.index.name = df.index.name or "timestamp"
    data.attrs.update(attrs)
    data.attrs[ANALYSIS_CLOCK_ATTR] = mode
    if source_timezone_name:
        data.attrs[SOURCE_TIMEZONE_ATTR] = str(source_timezone_name)
    if mode == LOCAL_CIVIL_TIME and local_timezone_name:
        data.attrs[ANALYSIS_TIMEZONE_ATTR] = str(local_timezone_name)
    elif mode == LOCAL_STANDARD_TIME and standard_utc_offset_hours is not None:
        data.attrs[ANALYSIS_TIMEZONE_ATTR] = f"UTC{float(standard_utc_offset_hours):+g} fixed standard time"
    elif mode == UTC_TIME:
        data.attrs[ANALYSIS_TIMEZONE_ATTR] = "UTC"
    else:
        data.attrs[ANALYSIS_TIMEZONE_ATTR] = str(source_timezone_name or data.index.tz or "source calendar")
    return data


def add_calendar_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add source-neutral calendar helpers from the already-selected clock."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Climate calendar columns require a pandas DatetimeIndex.")
    attrs = dict(df.attrs)
    data = df.copy()
    index = pd.DatetimeIndex(data.index)
    data["year"] = index.year
    data["date"] = index.date
    data["month_index"] = index.month
    data["month_name"] = index.month_name().str.slice(stop=3)
    data["day_of_year"] = index.dayofyear
    data["week_of_year"] = index.isocalendar().week.astype(int)
    data["hour_of_day"] = index.hour
    data["season"] = data["month_index"].map(
        {
            12: "Winter", 1: "Winter", 2: "Winter",
            3: "Spring", 4: "Spring", 5: "Spring",
            6: "Summer", 7: "Summer", 8: "Summer",
            9: "Autumn", 10: "Autumn", 11: "Autumn",
        }
    )
    data.attrs.update(attrs)
    return data


def prepare_analysis_calendar(
    df: pd.DataFrame,
    *,
    mode: AnalysisClockMode = LOCAL_CIVIL_TIME,
    local_timezone_name: str | None = None,
    standard_utc_offset_hours: float | None = None,
    source_timezone_name: str | None = None,
) -> pd.DataFrame:
    """Convert clock representation and add calendar columns in one operation."""
    converted = with_analysis_clock(
        df,
        mode=mode,
        local_timezone_name=local_timezone_name,
        standard_utc_offset_hours=standard_utc_offset_hours,
        source_timezone_name=source_timezone_name,
    )
    return add_calendar_columns(converted)
