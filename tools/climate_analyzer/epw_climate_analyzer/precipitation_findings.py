"""R2.6 — evidence-based precipitation, snow and freeze–thaw interpretations.

Interval precipitation depth is extensive [mm], measured precipitation
duration is extensive [min], snow depth is a state [cm]. Annual event indices
use complete calendar days. Architectural priorities are implications of the
observed climatic exposure rather than inferred design runoff or roof load.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .aggregations import native_interval_hours
from .interpretations import _fmt, _fmt_hours
from .period_display import format_plotted_time, canonical_profile_kind
from .profile_interpretation import profile_centre
from .precipitation import (
    LIQUID_PRECIPITATION_COLUMN as P,
    PRECIPITATION_DURATION_COLUMN as DURATION,
    SNOW_DEPTH_COLUMN as SNOW,
    complete_daily_precipitation,
    daily_snow_depth_max,
)
T="dry_bulb_temperature_c"


def _valid(df,col):
    if col not in df:return pd.Series(dtype=float,index=df.index)
    v=pd.to_numeric(df[col],errors="coerce").replace([np.inf,-np.inf],np.nan)
    if col in (P,SNOW,DURATION):v=v.where(v.ge(0))
    if col==DURATION:
        v=v.where(v.le(60.*native_interval_hours(df)+1e-6))
    return v


def _peak_period(df,series):
    if not len(series) or not isinstance(series.index,pd.DatetimeIndex):
        return ""
    grouped=series.resample("MS").sum(min_count=1).dropna()
    if grouped.empty:return ""
    m=grouped.idxmax()
    return f" Greatest monthly accumulation: {_fmt(grouped.loc[m])} mm in {pd.Timestamp(m).strftime('%b %Y')}."


def rainfall_summary(df,*,wet_threshold_mm=1.):
    rain=_valid(df,P).dropna()
    if rain.empty:return "No valid selected precipitation-depth observations."
    dt=native_interval_hours(df)
    rain_positive=rain.gt(0)
    total=float(rain.sum())
    wet_rain=rain.loc[rain_positive]
    peak=float(rain.max())
    max_mean=float(peak/dt)
    note=(f"Selected-period liquid precipitation totals {_fmt(total)} mm from "
          f"{len(rain):,} valid {dt:g}-h observations. "
          f"{int(rain_positive.sum()):,} source intervals contain precipitation; "
          f"mean depth within these intervals is {_fmt(wet_rain.mean())} mm. "
          f"The largest single source-interval accumulation is {_fmt(peak)} mm "
          f"(equivalent interval-mean intensity {_fmt(max_mean)} mm/h). ")
    if isinstance(rain.index,pd.DatetimeIndex):
        monthly=rain.resample("MS").sum(min_count=1)
        if monthly.notna().any():
            k=monthly.idxmax()
            note+=f"The highest monthly total is {_fmt(monthly.max())} mm in {k.strftime('%b %Y')}. "
        try:
            daily=complete_daily_precipitation(df)
        except ValueError:
            daily=pd.Series(dtype=float)
        observed=daily.dropna()
        if not observed.empty:
            note+=(f"Across {len(observed):,} complete observed days, "
                   f"{int(observed.ge(wet_threshold_mm).sum()):,} days reach "
                   f"{wet_threshold_mm:g} mm, "
                   f"{int(observed.ge(10.).sum()):,} days reach 10 mm and "
                   f"{int(observed.ge(20.).sum()):,} days reach 20 mm. "
                   f"The highest complete-day total is {_fmt(observed.max())} mm. ")
    return note+("The monthly concentration informs runoff routing and rainwater storage; "
                 "high daily accumulations prioritize roof drainage, overflow paths, "
                 "rain-protected openings and façade water management.")


def snow_summary(df):
    snow=_valid(df,SNOW).dropna()
    if snow.empty:return "No valid snow-depth observations in the selected period."
    dt=float(native_interval_hours(df))
    positive=snow.gt(0)
    n=int(positive.sum())
    peaks=float(snow.max())
    note=(f"Observed snow depth ranges from {_fmt(snow.min())} to {_fmt(peaks)} cm; "
          f"recorded snow cover occurs in {_fmt_hours(n*dt)} h "
          f"({100*n/len(snow):.1f}% of valid snow-state observations). ")
    if isinstance(snow.index,pd.DatetimeIndex):
        daily=daily_snow_depth_max(df).dropna()
        note+=f"{int(daily.gt(0).sum())} observed calendar days have snow depth above 0 cm. "
        if peaks>0:
            peak_date=snow.idxmax()
            note+=f"The highest observed depth occurs on {peak_date.strftime('%d %b %Y')}. "
    if peaks>0:
        note+=("Snow persistence informs roof-weather exposure, snow-retention and "
               "meltwater drainage planning, with structural snow loading verified "
               "separately from the measured ground-depth record.")
    else:
        note+="The selected snow observations remain at zero depth throughout the period."
    return note


def measured_duration_summary(df):
    v=_valid(df,DURATION).dropna()
    if v.empty:return "No measured precipitation-duration values are present."
    minutes=float(v.sum())
    return (f"Measured precipitation totals {_fmt(minutes/60.)} h across "
            f"{len(v):,} valid source-duration records. "
            f"{int(v.gt(0).sum())} records contain positive precipitation duration; "
            f"the maximum observed interval duration is {_fmt(v.max())} min. "
            "These recorded wet-time intervals inform outdoor exposure, "
            "covered circulation and drying-time analysis.")


def wet_dry_interpretation(df,*,wet=True,threshold=1.,minimum=1):
    from .p4_extremes import wet_dry_events
    try:
        daily, wet_events,dry_events=wet_dry_events(df,threshold=threshold,minimum=minimum)
    except ValueError:
        return "Wet/dry event statistics require a complete subdaily calendar sequence."
    selected=wet_events if wet else dry_events
    label="wet" if wet else "dry"
    if selected.empty:return f"The selected series contains zero continuous {label} spells at the {threshold:g} mm/day boundary."
    longest=selected.loc[selected.duration.idxmax()]
    total=float(selected.duration.sum())
    return (f"{len(selected):,} observed {label} spells encompass {int(total)} complete days in total; "
            f"the longest lasts {int(longest.duration)} consecutive complete days "
            f"({longest.start.strftime('%d %b')}–{longest.end.strftime('%d %b')}). "
            +("Persistent wet spells guide moisture-safe façade junctions, "
              "drainage maintenance and drying-time assumptions."
              if wet else
              "Dry spells reveal potential rainwater-storage drawdown periods "
              "and seasonal irrigation requirements."))


def rolling_interpretation(df,hours=24):
    from .p4_extremes import rolling_windows
    try:
        v=rolling_windows(df,P,float(hours),total=True,nonnegative=True).dropna()
    except ValueError:return "The selected accumulation window requires an integral number of native source intervals."
    if v.empty:return f"No complete {hours:g}-h precipitation accumulation windows occur in the selection."
    peak=v.idxmax()
    return (f"The highest complete trailing {hours:g}-hour precipitation accumulation is "
            f"{_fmt(v.max())} mm, ending {peak.strftime('%d %b %Y %H:%M')}. "
            "The peak window identifies a concentrated rainwater-management episode. "
            "Use the duration-specific local design rainfall for final hydraulic sizing.")


def freeze_interpretation(df,kind="freeze_days",*,wet_threshold=1.):
    from .p4_extremes import freeze_thaw_days,freeze_thaw_cycles
    if kind=="freeze_cycles":
        try:events=freeze_thaw_cycles(df,wet_threshold=wet_threshold)
        except ValueError:return "An hourly temperature series is needed to identify consecutive freeze–thaw sequences."
        if events.empty:return "Zero warm–freeze–warm air-temperature sequences were observed in the selected period."
        return (f"{len(events):,} warm–freeze–warm sequences occur in the selected "
                f"air-temperature series; maximum freeze-to-thaw span "
                f"{_fmt(events['Freeze-to-thaw duration [h]'].max())} h. "
                "Repeated crossings encourage examination of exposed wet masonry, "
                "junction drainage and freeze-resistant surface detailing.")
    try:table=freeze_thaw_days(df,wet_threshold=wet_threshold)
    except ValueError:return "A complete daily temperature sequence is needed for freeze–thaw day classification."
    if table.empty:return "No complete daily temperature observations are present."
    crossing=table.iloc[:,0].dropna()
    wet=table.iloc[:,1].dropna() if table.shape[1]>1 else pd.Series(dtype=float)
    return (f"{int(crossing.sum()):,} complete days have outdoor Tmin <0 °C "
            f"and Tmax >0 °C; {int(wet.sum()):,} of {len(wet):,} days with "
            "complete rainfall and temperature observations also reach "
            f"the {wet_threshold:g} mm/day wet criterion. "
            "These crossings identify seasons for examining moisture-sensitive "
            "façade assemblies, drains, joints and paved surfaces.")


def rain_day_classes(df):
    """Mutually exclusive monthly wet-day classes from fully observed days."""
    daily=complete_daily_precipitation(df).dropna()
    if daily.empty:return pd.DataFrame(columns=["1–<10 mm","10–<20 mm","≥20 mm"],dtype=float)
    classes={
        "1–<10 mm":daily.ge(1.)&daily.lt(10.),
        "10–<20 mm":daily.ge(10.)&daily.lt(20.),
        "≥20 mm":daily.ge(20.),
    }
    data=pd.DataFrame({name:mask.astype(float) for name,mask in classes.items()},index=daily.index)
    grouped=data.resample("MS").sum(min_count=1)
    grouped.attrs.update({"complete_precipitation_days":int(len(daily)),"rain_day_source":"complete-day"})
    return grouped


def rain_day_classes_figure(table):
    fig=go.Figure()
    for key in ("1–<10 mm","10–<20 mm","≥20 mm"):
        if key in table:
            fig.add_bar(x=table.index,y=table[key],name=key)
    fig.update_layout(template="plotly_white",barmode="stack",
                      title="Monthly precipitation-day severity",
                      xaxis_title="Month",yaxis_title="Complete days",
                      legend=dict(orientation="h",y=-.23))
    return fig


def _plotted(fig,preferred=None):
    if fig is None:return pd.Series(dtype=float),[]
    for trace in getattr(fig,"data",()):
        name=str(getattr(trace,"name","") or "")
        if preferred and preferred.lower() not in name.lower():continue
        raw=getattr(trace,"y",None)
        if raw is None:continue
        arr=np.asarray(raw,dtype=object)
        if arr.ndim!=1 or arr.size==0:continue
        vals=pd.to_numeric(pd.Series(arr),errors="coerce")
        if vals.notna().any():
            xx=getattr(trace,"x",None)
            return vals,list(xx) if xx is not None else []
    return pd.Series(dtype=float),[]


def precipitation_figure_interpretation(df,fig,kind,*,column=P,title="",args=()):
    """Plot-relevant measured result and architectural interpretation."""
    kind=str(kind).lower()
    title=str(title or getattr(getattr(getattr(fig,"layout",None),"title",None),"text","") or "")
    args=tuple(args or ())
    kind=canonical_profile_kind(kind,title,args)
    if kind in ("wetdry","wet_dry"):
        wet=bool(args[0]) if args else ("wet" in title.lower())
        return wet_dry_interpretation(df,wet=wet)
    if kind=="rolling":return rolling_interpretation(df,float(args[0]) if args else 24.)
    if kind=="cumulative":
        return rainfall_summary(df)+" The cumulative graph traces successive precipitation accumulation blocks through the observed chronology."
    if kind in ("freeze_days","freeze_cycles"):return freeze_interpretation(df,kind)
    if kind=="snow_calendar":return snow_summary(df)
    if kind=="rain_days":return rainfall_summary(df)
    if kind=="climate_summary":
        return (rainfall_summary(df)+" Daily and monthly precipitation compared with "
                "temperature identify seasonal wetness and drying conditions.")
    if column==DURATION:base=measured_duration_summary(df);unit="min"
    elif column==SNOW:base=snow_summary(df);unit="cm"
    else:base=rainfall_summary(df);unit="mm"
    if kind in ("time_series","native"):
        return base+" The chronological trace exposes the timing and clustering of weather episodes."
    if kind in ("profile","percentile","time series / profile"):
        centre=profile_centre(fig,kind,title)
        vals,x=_plotted(fig,centre)
        if vals.empty:vals,x=_plotted(fig)
        if not vals.empty:
            lo,hi=int(vals.idxmin()),int(vals.idxmax())
            label=lambda i:format_plotted_time(x[i],df,title=title) if i<len(x) else f"point {i+1}"
            return (f"The plotted {centre} {column.replace('_',' ')} is lowest at "
                    f"{label(lo)} ({_fmt(vals.iloc[lo])} {unit}) and highest at "
                    f"{label(hi)} ({_fmt(vals.iloc[hi])} {unit}). "+base)
    if kind in ("heatmap","heat map"):
        for trace in getattr(fig,"data",()):
            if getattr(trace,"type","")=="heatmap":
                z=np.asarray(trace.z,dtype=float)
                if z.ndim==2 and np.isfinite(z).any():
                    loc=np.unravel_index(np.nanargmax(z),z.shape)
                    x=list(trace.x);y=list(trace.y)
                    return (f"The greatest displayed {title.split(' · ')[0].lower() or 'precipitation'} "
                            f"heatmap value is {_fmt(z[loc])} {unit}, "
                            f"at x={x[loc[1]]}, y={y[loc[0]]}. "+base)
    if kind in ("duration","duration curve"):
        v=_valid(df,column).dropna()
        if "wet intervals" in title.lower() and column==P:v=v.loc[v.gt(0)]
        if not v.empty:
            return (f"The ranked {column.replace('_',' ')} distribution has "
                    f"P05 {_fmt(v.quantile(.05))}, median {_fmt(v.median())}, "
                    f"P95 {_fmt(v.quantile(.95))} {unit}; "
                    f"{len(v):,} observations enter this curve. "+base)
    if kind in ("histogram","box","violin","monthly boxplot","monthly violin plot","occurrence","diurnal","total"):
        return base
    return base
