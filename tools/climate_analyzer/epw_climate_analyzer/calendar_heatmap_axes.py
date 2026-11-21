"""Calendar heatmap axes: explicit month labels without changing trace values."""
from __future__ import annotations
import re
import calendar
import math
import pandas as pd

_DATE=re.compile(r"^\d{4}-\d{2}(?:-\d{2})?(?:[ T].*)?$")
_MONTHS={name.lower():i for i,name in enumerate(calendar.month_abbr) if i}
_MONTHS.update({name.lower():i for i,name in enumerate(calendar.month_name) if i})

def _month_label(t,year):
    return t.strftime("%b %Y" if year else "%b")

def _date_ticks(values):
    try:idx=pd.DatetimeIndex(pd.to_datetime(values,format="mixed"))
    except (ValueError,TypeError,OverflowError):return None
    if idx.empty or idx.hasnans:return None
    # Use wall-calendar labels even when native records are timezone-aware.
    if idx.tz is not None:idx=idx.tz_localize(None)
    lo,hi=idx.min(),idx.max()
    periods=idx.to_period("M")
    months=pd.period_range(lo.to_period("M"),hi.to_period("M"),freq="M")
    if not len(months):return None
    # Every month for one annual cycle; bounded, explicitly labeled cadence
    # for longer real chronological intervals. Always retain the final month.
    step=max(1,math.ceil(len(months)/12))
    chosen=list(months[::step])
    if chosen[-1]!=months[-1]:chosen.append(months[-1])
    vals=[];labels=[]
    for m in chosen:
        start=m.start_time;end=m.end_time
        # Monthly cells are centered on their timestamp; daily cells use
        # the middle of their represented part of the month.
        actual=idx[periods==m]
        if len(actual)==1:pos=actual[0]
        else:pos=max(lo,start)+(min(hi,end)-max(lo,start))/2
        vals.append(pos.isoformat());labels.append(_month_label(start,lo.year!=hi.year))
    return vals,labels,"date"

def _numeric_ticks(values,semantic):
    try:nums=[int(v) for v in values if float(v)==int(v)]
    except (ValueError,TypeError,OverflowError):return None
    if len(nums)!=len(values) or not nums:return None
    lo,hi=min(nums),max(nums)
    if semantic=="month" and 1<=lo<=hi<=12:
        vals=list(range(lo,hi+1));return vals,[calendar.month_abbr[i] for i in vals],"linear"
    if semantic in ("day","day of year") and 1<=lo<=hi<=366:
        starts=[pd.Timestamp(2000,m,1).dayofyear for m in range(1,13)]
        ends=starts[1:]+[367]
        vals=[];labels=[]
        for m,(a,b) in enumerate(zip(starts,ends),1):
            if b-1<lo or a>hi:continue
            vals.append((max(a,lo)+min(b-1,hi))/2);labels.append(calendar.month_abbr[m])
        return vals,labels,"linear"
    return None

def apply_calendar_heatmap_axes(fig,*,period=None):
    """Only calendar dimensions of heatmaps; not numeric physics axes.
    Idempotent at the chart, shared presentation and print clone boundaries.
    """
    if not hasattr(fig,"layout"):return fig
    for trace in getattr(fig,"data",()):
        if getattr(trace,"type","") not in ("heatmap","heatmapgl"):continue
        for coord in ("x","y"):
            raw=getattr(trace,coord,None)
            if raw is None or not len(raw):continue
            vals=list(raw)
            ref=getattr(trace,coord+"axis",None) or coord
            axis=getattr(fig.layout,coord+"axis"+ref[1:],None)
            if axis is None:continue
            title=str(axis.title.text or "").strip().lower()
            semantic=str(period).lower() if period and coord=="x" else title
            # No auto calendar interpretation for a date-looking categorical
            # label on unrelated dimensions; actual date objects are safe.
            dates=all(isinstance(v,(pd.Timestamp,)) or _DATE.match(str(v)) for v in vals)
            month_names=all(str(v).strip().lower() in _MONTHS for v in vals)
            if dates:
                ticks=_date_ticks(vals)
            elif month_names:
                ticks=vals,[calendar.month_abbr[_MONTHS[str(v).strip().lower()]] for v in vals],"category"
            else:ticks=_numeric_ticks(vals,semantic)
            if ticks is None:continue
            tickvals,ticktext,kind=ticks
            if not tickvals:continue
            axis.update(type=kind,tickmode="array",tickvals=tickvals,ticktext=ticktext,automargin=True)
            if coord=="x":
                # Short labels keep a complete annual cycle visible even in
                # printed A4 portraits. Rotation provides room for large fonts.
                axis.tickangle=-45 if len(tickvals)>=9 or any(len(t)>4 for t in ticktext) else 0
                axis.showticklabels=True
            else:axis.showticklabels=True
    return fig

_MONTH_YEAR=re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[ .-]+(\d{4})$",re.I)

def apply_monthly_axes(fig):
    """Monthly bars/lines/boxes: explicit ticks for every represented month.
    Real multiyear dates keep year labels. Do not change daily/physical axes,
    trace values, categorical ordering, or animation frames.
    """
    by_axis={}
    for trace in getattr(fig,"data",()):
        if getattr(trace,"type","") not in ("bar","scatter","scattergl","box","violin"):continue
        raw=getattr(trace,"x",None)
        if raw is None or not len(raw):continue
        ref=getattr(trace,"xaxis",None) or "x"
        by_axis.setdefault(ref,[]).extend(v for v in raw if v is not None)
    for ref,values in by_axis.items():
        axis=getattr(fig.layout,"xaxis"+ref[1:],None)
        if axis is None or not values:continue
        vals=list(dict.fromkeys(str(v) for v in values))
        if all(_MONTH_YEAR.match(v) for v in vals):
            parsed=[_MONTH_YEAR.match(v) for v in vals]
            years={m.group(2) for m in parsed}
            axis.update(tickmode="array",tickvals=vals,ticktext=[m.group(1).title() if len(years)==1 else v for m,v in zip(parsed,vals)],
                        automargin=True,tickangle=-45 if len(years)>1 else 0,showticklabels=True)
            continue
        if all(v.strip().lower() in _MONTHS for v in vals):
            axis.update(tickmode="array",tickvals=vals,ticktext=[calendar.month_abbr[_MONTHS[v.strip().lower()]] for v in vals],automargin=True,tickangle=0,showticklabels=True)
            continue
        if not all(_DATE.match(v) for v in vals):continue
        try:idx=pd.DatetimeIndex(pd.to_datetime(vals,format="mixed"))
        except (ValueError,TypeError,OverflowError):continue
        if idx.hasnans or not len(idx):continue
        if idx.tz is not None:idx=idx.tz_localize(None)
        months=idx.to_period("M")
        # Each distinct represented month must have one date coordinate.
        if months.has_duplicates:continue
        title=str(axis.title.text or "").lower()
        graph_title=str(fig.layout.title.text or "").lower()
        contiguous=len(months)>1 and (max(months)-min(months)).n==len(months)-1
        if not ("month" in title or "monthly" in graph_title or contiguous):continue
        ticks=_date_ticks(vals)
        if ticks is None:continue
        tickvals,ticktext,kind=ticks
        axis.update(type=kind,tickmode="array",tickvals=tickvals,ticktext=ticktext,automargin=True,
                    tickangle=-45 if len(set(idx.year))>1 else 0,showticklabels=True)
    return fig
