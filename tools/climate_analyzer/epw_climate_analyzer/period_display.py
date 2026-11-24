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
