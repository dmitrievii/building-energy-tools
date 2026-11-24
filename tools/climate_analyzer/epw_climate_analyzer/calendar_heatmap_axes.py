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
            # Hour indices 0..23 are cell centres in Plotly. Display elapsed
            # clock boundaries 00:00..24:00 at the corresponding cell edges.
            # Keep source coordinates and hover hour labels unchanged.
            if title in ("hour of day","analysis clock hour","clock hour","hour"):
                try:hours=[int(v) for v in vals if float(v)==int(v)]
                except (TypeError,ValueError,OverflowError):hours=[]
                if len(hours)==len(vals) and hours and 0<=min(hours)<=max(hours)<=23:
                    hours_ticks=[0,6,12,18,24]
                    ticks=[h-.5 for h in hours_ticks]
                    bounds=[23.5,-.5] if coord=="y" else [-.5,23.5]
                    axis.update(type="linear",tickmode="array",tickvals=ticks,
                                ticktext=[str(h) for h in hours_ticks],range=bounds,autorange=False,
                                autorangeoptions=dict(minallowed=-.5,maxallowed=23.5),
                                tickangle=0,automargin=True,showticklabels=True)
                    continue
            if coord=="x" and _period_ticks(axis,vals,fig,heatmap=True):continue
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

_ISO_WEEK=re.compile(r"^(?:(\d{4})-)?W(0?[1-9]|[1-4]\d|5[0-3])$",re.I)
_DAY_MONTH=re.compile(r"^(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$",re.I)

def set_period_axis_scope(fig,source=None,*,context=None,aggregation=None):
    """Preserve the source scope, not the potentially cross-year resample end."""
    meta=dict(fig.layout.meta) if isinstance(fig.layout.meta,dict) else {}
    try:
        if source is not None and len(source):
            idx=pd.DatetimeIndex(source.index if hasattr(source,"index") else source)
            first,last=idx.min(),idx.max()
            meta["period_source_years"]=[int(first.year),int(last.year)]
        elif context and "period_source_years" not in meta:
            first=pd.Timestamp(context["first timestamp"]);last=pd.Timestamp(context["last timestamp"])
            if pd.notna(first) and pd.notna(last):meta["period_source_years"]=[int(first.year),int(last.year)]
    except (KeyError,ValueError,TypeError,OverflowError):pass
    if aggregation:meta["period_aggregation"]=str(aggregation).lower()
    if meta:fig.update_layout(meta=meta)
    return fig

def _day_positions(numbers):
    """Readable calendar-day ticks with the exact represented last day."""
    lo,hi=min(numbers),max(numbers)
    span=hi-lo
    step=next((s for s in (1,2,5,10,20,25,50,100) if span/s<=9),100)
    ticks=[n for n in range(((lo+step-1)//step)*step,hi+1,step)]
    if not ticks or ticks[0]!=lo:
        if ticks and ticks[0]-lo<step*.35:ticks=ticks[1:]
        ticks.insert(0,lo)
    if ticks[-1]!=hi:
        if len(ticks)>1 and hi-ticks[-1]<step*.30:ticks.pop()
        ticks.append(hi)
    return ticks

def _bounded_positions(n,limit=14):
    step=max(1,math.ceil(n/limit))
    take=list(range(0,n,step))
    if take[-1]!=n-1:
        if len(take)>1 and n-1-take[-1]<step*.5:take.pop()
        take.append(n-1)
    return take

def _period_ticks(axis,values,fig,*,heatmap=False):
    """Shared daily/weekly presentation; never change trace coordinates."""
    if not values:return False
    meta=fig.layout.meta if isinstance(fig.layout.meta,dict) else {}
    years=meta.get("period_source_years")
    single_scope=bool(isinstance(years,(list,tuple)) and len(years)==2 and years[0]==years[1])
    multi_scope=bool(isinstance(years,(list,tuple)) and len(years)==2 and years[0]!=years[1])
    agg=str(meta.get("period_aggregation","")).lower()
    title=str(axis.title.text or "").strip().lower()
    graph=str(fig.layout.title.text or "").lower()
    raw=list(dict.fromkeys(values))
    strings=[str(v) for v in raw]
    weeks=[_ISO_WEEK.fullmatch(v) for v in strings]
    if all(weeks):
        iso_years={m.group(1) for m in weeks if m.group(1)}
        compact=single_scope or len(iso_years)<=1 and not multi_scope
        labels=[f"W{int(m.group(2)):02d}" if compact else v for m,v in zip(weeks,strings)]
        take=_bounded_positions(len(raw),14 if compact else 10)
        axis.update(tickmode="array",tickvals=[raw[i] for i in take],ticktext=[labels[i] for i in take],
                    tickangle=0 if compact else -45,automargin=True,showticklabels=True)
        return True
    # Numeric ISO weeks (calendar-profile heatmaps).
    if (title in ("week","week of year","iso week") or agg=="weekly" and title=="period"):
        try:nums=[int(v) for v in raw if float(v)==int(v)]
        except (TypeError,ValueError,OverflowError):nums=[]
        if len(nums)==len(raw) and nums and 1<=min(nums)<=max(nums)<=53:
            take=_bounded_positions(len(raw))
            axis.update(tickmode="array",tickvals=[raw[i] for i in take],ticktext=[f"W{nums[i]:02d}" for i in take],tickangle=0,automargin=True,showticklabels=True)
            return True
    if heatmap:return False # Day × hour retains the established month labels.
    daily=agg=="daily" or title in ("day","day of year","day of the year","calendar day","daily period") or ("daily" in graph and title in ("period","date","time"))
    try:nums=[int(v) for v in raw if float(v)==int(v)]
    except (TypeError,ValueError,OverflowError):nums=[]
    if len(nums)==len(raw) and nums and 1<=min(nums)<=max(nums)<=366 and (daily or title=="period" and max(nums)>53):
        # Preserve continuous ordinal chart coordinates and true selection bounds,
        # but display calendar dates when the source year is established.
        ticks=_day_positions(nums)
        numeric=all(not isinstance(v,str) for v in raw)
        year=int(years[0]) if single_scope else None
        def date_label(day):
            if year is not None and day<=pd.Timestamp(year,12,31).dayofyear:
                return (pd.Timestamp(year,1,1)+pd.Timedelta(days=int(day)-1)).strftime("%d.%m")
            return str(day)
        if numeric:
            axis.update(type="linear",tickmode="array",tickvals=ticks,
                        ticktext=[date_label(n) for n in ticks],
                        tickangle=0,automargin=True,showticklabels=True)
        else:
            lookup=dict(zip(nums,raw));ticks=[n for n in ticks if n in lookup]
            axis.update(tickmode="array",tickvals=[lookup[n] for n in ticks],
                        ticktext=[date_label(n) for n in ticks],
                        tickangle=0,automargin=True,showticklabels=True)
        return True
    if not daily:return False
    if all(_DAY_MONTH.fullmatch(v) for v in strings):
        leap=any(v.lower()=="29 feb" for v in strings)
        year=2000 if leap else 2001
        idx=pd.DatetimeIndex(pd.to_datetime([f"{v} {year}" for v in strings],format="%d %b %Y",errors="coerce"))
        if idx.hasnans:return False
        nums=list(idx.dayofyear);lookup=dict(zip(nums,raw));ticks=[n for n in _day_positions(nums) if n in lookup]
        axis.update(tickmode="array",tickvals=[lookup[n] for n in ticks],
                    ticktext=[idx[nums.index(n)].strftime("%d.%m") for n in ticks],
                    tickangle=0,automargin=True,showticklabels=True)
        return True
    if not all(_DATE.match(v) for v in strings):return False
    try:idx=pd.DatetimeIndex(pd.to_datetime(strings,format="mixed"))
    except (ValueError,TypeError,OverflowError):return False
    if idx.hasnans or idx.normalize().has_duplicates:return False
    if len(set(idx.year))>1 or multi_scope:
        take=_bounded_positions(len(raw),10)
        labels=[idx[i].strftime("%d.%m.%Y") for i in take]
        axis.update(tickmode="array",tickvals=[raw[i] for i in take],ticktext=labels,tickangle=-45,automargin=True,showticklabels=True)
        return True
    nums=list(idx.dayofyear);lookup=dict(zip(nums,raw));ticks=[n for n in _day_positions(nums) if n in lookup]
    axis.update(tickmode="array",tickvals=[lookup[n] for n in ticks],
                ticktext=[idx[nums.index(n)].strftime("%d.%m") for n in ticks],
                tickangle=0,automargin=True,showticklabels=True)
    return True

_MONTH_YEAR=re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[ .-]+(\d{4})$",re.I)

def apply_monthly_axes(fig):
    """Canonical calendar axes for bars/lines/boxes (legacy public name).
    Preserve source data and multiyear chronology; leave physical axes alone.
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
        meta=fig.layout.meta
        daylight=(isinstance(meta,dict) and meta.get("calendar_axis")=="daily_daylight_envelope" or str(fig.layout.title.text or "").lower().startswith("ideal sunrise–sunset envelope"))
        if not daylight and _period_ticks(axis,values,fig):continue
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
        # The daily sunrise/sunset envelope uses explicit month ticks while
        # retaining every daily sample and the actual chronological date axis.
        # Recognize legacy saved report snapshots by their original title.
        meta=fig.layout.meta
        daylight=(isinstance(meta,dict) and meta.get("calendar_axis")=="daily_daylight_envelope"
                  or str(fig.layout.title.text or "").lower().startswith("ideal sunrise–sunset envelope"))
        if daylight:
            ticks=_date_ticks(vals)
            if ticks is not None:
                tickvals,ticktext,kind=ticks
                axis.update(type=kind,tickmode="array",tickvals=tickvals,ticktext=ticktext,
                            automargin=True,tickangle=-45 if len(set(idx.year))>1 else 0,showticklabels=True)
            continue
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
