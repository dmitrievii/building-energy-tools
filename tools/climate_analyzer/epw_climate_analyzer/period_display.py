"""Source-calendar labels shared by climate plots and interpretations.

Keep actual x coordinates unchanged. Daily profile ordinals are displayed as
calendar dates derived from the selected source year.
"""
from __future__ import annotations

from datetime import date, datetime
import re

import numpy as np
import pandas as pd

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2})?)?$")
_DAY_MONTH = re.compile(r"^\d{1,2} [A-Za-z]{3}(?: \d{4})?(?: \d{2}:\d{2})?$")
_MONTH_DAY = re.compile(r"^\d{2}-\d{2}(?: \d{2}:\d{2})?$")


def source_year(df):
    index=getattr(df,"index",None)
    if not isinstance(index,pd.DatetimeIndex) or index.empty:
        return None
    years=index.year.unique()
    return int(years[0]) if len(years)==1 else None


def format_timestamp(stamp, *, multiple_years=False, with_time=False):
    fmt="%d.%m"
    if multiple_years:fmt+=".%Y"
    if with_time:fmt+=" at %H:%M"
    return pd.Timestamp(stamp).strftime(fmt)


def format_plotted_time(value,df=None,*,aggregation="",title=""):
    """Convert identifiable chart positions to dates and, where known, clock times.

    A number such as 21 on a daily profile represents day 21, not hour 21.
    Bare ordinal numbers without an actual source year remain unchanged.
    """
    agg=str(aggregation or "").strip().lower()
    chart=str(title or "").lower()
    daily=agg=="daily" or ("daily" in chart and agg not in ("hourly","native"))
    year=source_year(df)
    if isinstance(value,(pd.Timestamp,np.datetime64,datetime,date)):
        stamp=pd.Timestamp(value)
        timed=(agg in ("hourly","native") or isinstance(value,datetime)
               or stamp.hour!=0 or stamp.minute!=0) and not daily
        return format_timestamp(stamp,multiple_years=year is None,with_time=timed)
    if isinstance(value,(int,float,np.integer,np.floating)) or (
            isinstance(value,str) and re.fullmatch(r"\d{1,3}",value.strip())):
        try:number=float(value)
        except (ValueError,TypeError):return str(value)
        if daily and number.is_integer() and 1<=number<=366 and year is not None:
            if number<=pd.Timestamp(year,12,31).dayofyear:
                stamp=pd.Timestamp(year,1,1)+pd.Timedelta(days=int(number)-1)
                return stamp.strftime("%d.%m")
        return str(value)
    label=str(value)
    try:
        if _ISO_DATE.fullmatch(label):
            stamp=pd.Timestamp(label)
            timed=("T" in label or " " in label and ":" in label) and not daily
            return format_timestamp(stamp,multiple_years=year is None or year!=stamp.year,with_time=timed)
        if _MONTH_DAY.fullmatch(label):
            stamp=pd.Timestamp(f"{year or 2000}-{label}")
            return format_timestamp(stamp,with_time=" " in label and not daily)
        if _DAY_MONTH.fullmatch(label):
            has_year=bool(re.search(r"\s\d{4}(?:\s|$)",label))
            has_time=bool(re.search(r"\d{2}:\d{2}$",label))
            parsed=pd.to_datetime(label,format="mixed",errors="coerce")
            if pd.notna(parsed):
                return format_timestamp(parsed,multiple_years=has_year,with_time=has_time and not daily)
    except (ValueError,TypeError,OverflowError):
        pass
    return label



def format_hour_interval(hour):
    """Clock-hour bin uses a zero-based hour, not a point observation."""
    try:
        h = int(hour)
        if float(hour) == h and 0 <= h <= 23:
            return f"{h:02d}:00–{h+1:02d}:00"
    except (ValueError, TypeError, OverflowError):
        pass
    return str(hour)


def format_heatmap_cell(fig, trace, position, df=None):
    """Format actual calendar coordinates, respecting pooled and interannual cells.

    Numeric day slots use the leap-neutral calendar of the heatmap engine
    (2000 as reference only); the reference year is never displayed as data.
    Chronological coordinates retain the real displayed year.
    """
    import calendar

    row, col = position
    x, y = trace.x[col], trace.y[row]
    def axis_title(coord):
        ref = getattr(trace, coord + "axis", None) or coord
        axis = getattr(fig.layout, coord + "axis" + ref[1:], None)
        return str(axis.title.text or "").strip().lower() if axis is not None else ""
    period, comparison = axis_title("x"), axis_title("y")
    is_hour = comparison in ("hour", "hour of day", "clock hour", "analysis clock hour")
    is_year = comparison == "year"
    year = int(y) if is_year else source_year(df)
    label = str(x)
    try:
        if period in ("day", "daily"):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", label) or isinstance(x, (date, datetime, np.datetime64)):
                label = pd.Timestamp(x).strftime("%d.%m.%Y")
            elif re.fullmatch(r"\d{1,3}", label) and 1 <= int(label) <= 366:
                stamp = pd.Timestamp(2000, 1, 1) + pd.Timedelta(days=int(label)-1)
                label = stamp.strftime("%d.%m")
                if year is not None:
                    # An interannual empty leap-day cell is not a valid date.
                    date(year, stamp.month, stamp.day)
                    label += f".{year:04d}"
        elif period in ("week", "weekly"):
            match = re.fullmatch(r"(?:(\d{4})-)?W?(\d{1,2})", label, re.I)
            if match and 1 <= int(match.group(2)) <= 53:
                # A pooled ISO-week slot need not belong to the calendar year
                # at the edges of a single-year dataset.
                week_year = match.group(1) or (str(year) if is_year else None)
                label = f"Week {int(match.group(2)):02d}" + (f", {week_year}" if week_year else "")
        elif period in ("month", "monthly"):
            match = re.fullmatch(r"(?:(\d{4})-)?(\d{1,2})", label)
            if match and 1 <= int(match.group(2)) <= 12:
                month_year = match.group(1) or year
                label = calendar.month_name[int(match.group(2))] + (f" {month_year}" if month_year else "")
        else:
            return f"{period or 'x'}: {x}; {comparison or 'y'}: {y}"
    except (ValueError, TypeError, OverflowError):
        return f"{period or 'x'}: {x}; {comparison or 'y'}: {y}"
    if is_hour:
        return f"{label}, {format_hour_interval(y)}"
    if is_year:
        return label
    return f"{label}; {comparison or 'y'}: {y}"


def canonical_profile_kind(kind, title="", args=()):
    """Classify identical plotted profile statistics equally in UI, Atlas and report.

    The same profile can arrive from three routes using 'time_series',
    'Time series / Profile' or 'percentile'. Its shown representation, rather
    than the route name, determines the scientific interpretation.
    """
    route=str(kind or "").strip().lower()
    if route not in ("time_series","time series / profile","profile","percentile","native"):
        return route
    if route=="native":return "native"
    description=(str(title or "")+" "+" ".join(map(str,args or ()))).lower()
    if "observed values" in description or "native observations" in description:
        return "time_series"
    if "p05" in description and "p95" in description:
        return "percentile"
    if route=="percentile":
        return "percentile"
    # A single hourly median or mean is a profile of that statistic, not a
    # source-observation sequence. For single-source hourly data this
    # distinction is resolved by the 'Observed values' representation.
    if route in ("time_series","time series / profile"):
        return "profile"
    return route
