"""Source-neutral temporal filtering and calendar/profile semantics.

The Climate Analyzer keeps canonical real timestamps intact for every source.
Temporal presentation is attached as dataframe metadata so chart/aggregation
helpers can choose among chronological, climatological profile, and
interannual-overlay semantics without rewriting source time coordinates.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


CHRONOLOGICAL = "Chronological"
CALENDAR_PROFILE = "Calendar profile"
INTERANNUAL_OVERLAY = "Interannual overlay"
TIME_BASIS_ATTR = "climate_time_basis"
VALID_TIME_BASES = (CHRONOLOGICAL, CALENDAR_PROFILE, INTERANNUAL_OVERLAY)
SEASON_ORDER = ("Winter", "Spring", "Summer", "Autumn")
CALENDAR_ANCHOR_YEAR = 2000  # leap year: presentation axis has a real Feb 29 slot


def _require_datetime_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Temporal filtering requires a pandas DatetimeIndex.")
    return pd.DatetimeIndex(df.index)


def available_years(df: pd.DataFrame) -> list[int]:
    """Return sorted years that actually contain source records."""
    index = _require_datetime_index(df)
    return sorted({int(year) for year in index.year})


def is_multiyear(df_or_index: pd.DataFrame | pd.DatetimeIndex) -> bool:
    """Return whether more than one calendar year occurs in the data."""
    index = _require_datetime_index(df_or_index) if isinstance(df_or_index, pd.DataFrame) else pd.DatetimeIndex(df_or_index)
    return len(set(int(year) for year in index.year)) > 1


def time_basis(df: pd.DataFrame) -> str:
    """Return the temporal interpretation attached to a filtered frame."""
    value = str(df.attrs.get(TIME_BASIS_ATTR, CHRONOLOGICAL))
    return value if value in VALID_TIME_BASES else CHRONOLOGICAL


def with_time_basis(df: pd.DataFrame, basis: str) -> pd.DataFrame:
    """Return a data copy carrying an explicit temporal interpretation."""
    if basis not in VALID_TIME_BASES:
        raise ValueError(f"Unsupported time basis: {basis}")
    attrs = dict(df.attrs)
    out = df.copy()
    out.attrs.update(attrs)
    out.attrs[TIME_BASIS_ATTR] = basis
    return out


def _align_timestamp(value: object, index: pd.DatetimeIndex) -> pd.Timestamp:
    """Align a timestamp to the timezone semantics of ``index``."""
    stamp = pd.Timestamp(value)
    if index.tz is None:
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC").tz_localize(None)
        return stamp
    if stamp.tzinfo is None:
        return stamp.tz_localize(index.tz)
    return stamp.tz_convert(index.tz)


def filter_datetime_range(
    df: pd.DataFrame,
    start: object | None = None,
    end: object | None = None,
) -> pd.DataFrame:
    """Filter to an inclusive absolute timestamp range while preserving attrs."""
    index = _require_datetime_index(df)
    attrs = dict(df.attrs)
    mask = pd.Series(True, index=df.index)
    if start is not None:
        start_ts = _align_timestamp(start, index)
        mask &= index >= start_ts
    if end is not None:
        end_ts = _align_timestamp(end, index)
        mask &= index <= end_ts
    out = df.loc[mask.to_numpy()].copy()
    out.attrs.update(attrs)
    return out


def filter_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter to one year that is present in the source calendar."""
    years = available_years(df)
    selected = int(year)
    if selected not in years:
        raise ValueError(f"Year {selected} is not available in the loaded dataset.")
    attrs = dict(df.attrs)
    out = df.loc[pd.DatetimeIndex(df.index).year == selected].copy()
    out.attrs.update(attrs)
    return out


def season_name(month: int) -> str:
    month = int(month)
    if month in (12, 1, 2):
        return "Winter"
    if month in (3, 4, 5):
        return "Spring"
    if month in (6, 7, 8):
        return "Summer"
    return "Autumn"


def calendar_position(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Map real timestamps to a leap-year presentation axis without losing source time.

    The returned timestamps are presentation coordinates only. ``2000`` is used
    because it contains Feb 29. Real timestamps remain in the canonical frame and
    must be retained separately by year-preserving intermediate tables.
    """
    idx = pd.DatetimeIndex(index)
    values = [
        pd.Timestamp(
            year=CALENDAR_ANCHOR_YEAR,
            month=int(stamp.month),
            day=int(stamp.day),
            hour=int(stamp.hour),
            minute=int(stamp.minute),
            second=int(stamp.second),
            microsecond=int(stamp.microsecond),
        )
        for stamp in idx
    ]
    return pd.DatetimeIndex(values, name="calendar_position")


def interannual_calendar_bin(index: pd.DatetimeIndex, aggregation: str) -> pd.Index:
    """Return deterministic year-neutral bins for one interannual series.

    Weekly bins are fixed seven-day bins on the leap-year calendar axis starting
    on Jan 1. They never contain records from two real years because real year is
    always a separate grouping key. This avoids ISO week ownership crossing the
    Dec/Jan boundary while keeping equivalent calendar dates aligned.
    """
    idx = pd.DatetimeIndex(index)
    pos = calendar_position(idx)
    label = str(aggregation)
    if label in {"Native", "10 min", "30 min", "1 h", "3 h", "6 h"}:
        return pd.Index(pos, name="calendar_bin")
    if label in {"Hourly", "1h"}:
        return pd.Index(pos.floor("h"), name="calendar_bin")
    if label == "Daily":
        return pd.Index(pos.normalize(), name="calendar_bin")
    if label == "Weekly":
        anchor = pd.Timestamp(CALENDAR_ANCHOR_YEAR, 1, 1)
        day_index = (pos.normalize() - anchor).days
        week_index = day_index // 7
        return pd.Index(anchor + pd.to_timedelta(week_index * 7, unit="D"), name="calendar_bin")
    if label == "Monthly":
        return pd.Index([pd.Timestamp(CALENDAR_ANCHOR_YEAR, int(stamp.month), 1) for stamp in idx], name="calendar_bin")
    if label == "Seasonal":
        starts = []
        for stamp in idx:
            month = int(stamp.month)
            start_month = 12 if month in (12, 1, 2) else (3 if month in (3, 4, 5) else (6 if month in (6, 7, 8) else 9))
            starts.append(pd.Timestamp(CALENDAR_ANCHOR_YEAR, start_month, 1))
        return pd.Index(starts, name="calendar_bin")
    if label == "Annual":
        return pd.Index([pd.Timestamp(CALENDAR_ANCHOR_YEAR, 1, 1)] * len(idx), name="calendar_bin")
    raise ValueError(f"Unsupported aggregation: {aggregation}")


def calendar_profile_slot(index: pd.DatetimeIndex, aggregation: str) -> pd.Index:
    """Return a year-neutral grouping slot for one climatological profile."""
    idx = pd.DatetimeIndex(index)
    if aggregation == "Hourly":
        return pd.Index(idx.strftime("%m-%d %H:00"), name="Calendar period")
    if aggregation == "Daily":
        return pd.Index(idx.strftime("%m-%d"), name="Calendar period")
    if aggregation == "Weekly":
        return pd.Index(idx.isocalendar().week.astype(int), name="Calendar period")
    if aggregation == "Monthly":
        return pd.Index(idx.month.astype(int), name="Calendar period")
    if aggregation == "Seasonal":
        values = [season_name(month) for month in idx.month]
        return pd.CategoricalIndex(values, categories=list(SEASON_ORDER), ordered=True, name="Calendar period")
    if aggregation == "Annual":
        return pd.Index(["Annual"] * len(idx), name="Calendar period")
    raise ValueError(f"Unsupported aggregation: {aggregation}")


def chronological_season_start(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return chronological season-start timestamps, with Dec assigned to next winter."""
    idx = pd.DatetimeIndex(index)
    starts: list[pd.Timestamp] = []
    for stamp in idx:
        year = int(stamp.year)
        month = int(stamp.month)
        if month in (12, 1, 2):
            winter_year = year + 1 if month == 12 else year
            start = pd.Timestamp(year=winter_year - 1, month=12, day=1)
        elif month in (3, 4, 5):
            start = pd.Timestamp(year=year, month=3, day=1)
        elif month in (6, 7, 8):
            start = pd.Timestamp(year=year, month=6, day=1)
        else:
            start = pd.Timestamp(year=year, month=9, day=1)
        if idx.tz is not None:
            start = start.tz_localize(idx.tz)
        starts.append(start)
    return pd.DatetimeIndex(starts, name="Season start")


def display_period_labels(index: Iterable[object], aggregation: str, basis: str = CHRONOLOGICAL) -> list[object]:
    """Return compact, unique display labels for an already aggregated index."""
    if basis not in VALID_TIME_BASES:
        basis = CHRONOLOGICAL

    if isinstance(index, pd.DatetimeIndex):
        idx = pd.DatetimeIndex(index)
        multiyear = len(set(int(year) for year in idx.year)) > 1
        if basis == INTERANNUAL_OVERLAY:
            if aggregation == "Monthly":
                return list(idx.strftime("%b"))
            if aggregation == "Weekly":
                anchor = pd.Timestamp(CALENDAR_ANCHOR_YEAR, 1, 1)
                return [f"W{int(((stamp.normalize() - anchor).days // 7) + 1):02d}" for stamp in idx]
            if aggregation == "Daily":
                return list(idx.strftime("%d %b"))
            if aggregation in {"Hourly", "Native"}:
                return list(idx.strftime("%d %b %H:%M"))
        if aggregation == "Monthly":
            return list(idx.strftime("%b %Y" if multiyear else "%b"))
        if aggregation == "Weekly":
            if multiyear:
                iso = idx.isocalendar()
                return [f"{int(y):04d}-W{int(w):02d}" for y, w in zip(iso.year, iso.week, strict=False)]
            return [f"W{int(stamp.isocalendar().week):02d}" for stamp in idx]
        if aggregation == "Daily":
            if multiyear:
                return list(idx.strftime("%d %b %Y"))
            return [int(stamp.dayofyear) for stamp in idx]
        if aggregation == "Annual":
            return [str(int(stamp.year)) for stamp in idx]
        if aggregation == "Seasonal":
            return [f"{season_name(stamp.month)} {stamp.year if stamp.month != 12 else stamp.year + 1}" for stamp in idx]
        return list(idx)

    values = list(index)
    if basis in {CALENDAR_PROFILE, INTERANNUAL_OVERLAY}:
        if aggregation == "Monthly":
            labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            return [labels[int(value) - 1] if str(value).isdigit() and 1 <= int(value) <= 12 else str(value) for value in values]
        if aggregation == "Weekly":
            return [f"W{int(value):02d}" if str(value).isdigit() else str(value) for value in values]
        if aggregation == "Daily":
            parsed = pd.to_datetime([f"2000-{value}" for value in values], errors="coerce")
            return [stamp.strftime("%d %b") if pd.notna(stamp) else str(value) for stamp, value in zip(parsed, values, strict=False)]
        if aggregation == "Hourly":
            parsed = pd.to_datetime([f"2000-{value}" for value in values], errors="coerce")
            return [stamp.strftime("%d %b %H:%M") if pd.notna(stamp) else str(value) for stamp, value in zip(parsed, values, strict=False)]
    return [str(value) for value in values]
