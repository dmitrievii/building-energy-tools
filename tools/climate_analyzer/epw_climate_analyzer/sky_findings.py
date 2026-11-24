"""R2.5 scientific interpretations of astronomical daylight and outdoor sky/light data.

All narrative sentences describe measured or computed quantities, their
seasonality and resulting architectural study priorities. No building model
or conversion between sunshine duration, solar irradiation and illuminance
is introduced.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .aggregations import native_interval_hours
from .interpretations import _fmt, _fmt_hours
from .period_display import format_plotted_time, canonical_profile_kind
from .daylight import daily_daylight_table, monthly_daylight_sunshine_summary

TOTAL="total_sky_cover_tenths"
OPAQUE="opaque_sky_cover_tenths"
SUN="sunshine_duration_s"
GLOBAL="global_horizontal_illuminance_lux"
DIRECT="direct_normal_illuminance_lux"
DIFFUSE="diffuse_horizontal_illuminance_lux"
GHI="global_horizontal_radiation_wh_m2"
UNITS={TOTAL:"tenths",OPAQUE:"tenths",SUN:"h",GLOBAL:"lux",DIRECT:"lux",DIFFUSE:"lux"}
LABELS={TOTAL:"total sky cover",OPAQUE:"opaque sky cover",SUN:"measured sunshine duration",
        GLOBAL:"global horizontal illuminance",DIRECT:"direct normal illuminance",
        DIFFUSE:"diffuse horizontal illuminance"}


def _numeric(df,column):
    if column not in df:return pd.Series(np.nan,index=df.index,dtype=float)
    value=pd.to_numeric(df[column],errors="coerce").replace([np.inf,-np.inf],np.nan)
    if column in (TOTAL,OPAQUE):return value.where(value.between(0,10))
    if column==SUN:
        dt=float(native_interval_hours(df))
        return value.where(value.between(0,dt*3600.+1e-6))
    return value.where(value.ge(0))


def _hours(df,mask):
    return _fmt_hours(int(mask.sum())*native_interval_hours(df))


def _date_at(index):
    return pd.Timestamp(index).strftime("%d %b") if isinstance(index,(pd.Timestamp,np.datetime64)) else str(index)


def _plotted(fig,preferred=None):
    if fig is None:return pd.Series(dtype=float),[]
    for tr in getattr(fig,"data",()):
        if preferred and preferred.lower() not in str(getattr(tr,"name","") or "").lower():
            continue
        raw=getattr(tr,"y",None)
        if raw is None:continue
        values=np.asarray(raw,dtype=object)
        if values.ndim!=1 or values.size==0:continue
        numeric=pd.to_numeric(pd.Series(values),errors="coerce")
        if numeric.notna().any():
            xx=getattr(tr,"x",None)
            return numeric,list(xx) if xx is not None else []
    return pd.Series(dtype=float),[]


def daylight_interpretation(df,latitude):
    """Annual-cycle daylight envelope for the represented calendar dates."""
    table=daily_daylight_table(pd.DatetimeIndex(df.index),float(latitude))
    if table.empty:return "The selected dates contain no astronomical daylight rows."
    d=table["daylight_duration_h"]
    summer=d.idxmax();winter=d.idxmin()
    span=float(d.max()-d.min())
    season=("The strong seasonal difference makes winter daylight admission "
            "and summer solar protection important orientation considerations."
            if span>=3. else
            "Daylight duration changes modestly across the year; direct-sun direction, "
            "solar altitude and façade shading deserve greater seasonal attention.")
    return (f"Astronomical daylight spans {_fmt(d.min(),2)} h on {_date_at(winter)} "
            f"to {_fmt(d.max(),2)} h on {_date_at(summer)} "
            f"(seasonal variation {_fmt(span,2)} h). "
            "The sunrise–sunset envelope follows local apparent solar time and a geometric horizon. "
            +season)


def sunshine_interpretation(df,latitude=None,kind="sunshine"):
    """Source duration, hourly availability and fraction of ideal daylight."""
    duration=_numeric(df,SUN)
    valid=duration.dropna()
    if valid.empty:return "The selected interval has no valid measured sunshine duration."
    dt=float(native_interval_hours(df))
    total=float(valid.sum()/3600.)
    measured=int((duration>0).sum())*dt
    summary=None
    if latitude is not None:
        summary=monthly_daylight_sunshine_summary(df,float(latitude))
    if kind=="relative_sunshine":
        if summary is None or "relative_sunshine_pct" not in summary:
            return "Relative sunshine duration uses measured sunshine on complete calendar days and astronomical daylight for the same dates."
        rows=summary.dropna(subset=["relative_sunshine_pct","sunshine_days"])
        if rows.empty:return "The selected data provide no complete calendar days for the sunshine/daylight ratio."
        hi=rows.loc[rows.relative_sunshine_pct.idxmax()]
        lo=rows.loc[rows.relative_sunshine_pct.idxmin()]
        numerator=float(rows.total_sunshine_h.sum())
        denominator=float(rows.observed_daylight_h.sum())
        ratio=100.*numerator/denominator if denominator>0 else np.nan
        return (f"Across {int(rows.sunshine_days.sum()):,} complete observation days, "
                f"measured sunshine occupies {_fmt(ratio)}% of their total astronomical daylight "
                f"({_fmt(numerator)} h of {_fmt(denominator)} h). "
                f"Highest monthly share: {hi['month']} ({_fmt(hi.relative_sunshine_pct)}%); "
                f"lowest: {lo['month']} ({_fmt(lo.relative_sunshine_pct)}%). "
                "The seasonal shares indicate periods for direct-sun access, glare management "
                "and orientation-specific external shading.")
    if kind=="sunshine_heatmap":
        grouped=(duration/3600.).groupby([duration.index.month,duration.index.hour]).mean()
        if not grouped.dropna().empty:
            idx=grouped.idxmax()
            peak=(f"The highest mean measured sunshine occurs in month "
                  f"{idx[0]} at {idx[1]:02d}:00 "
                  f"({_fmt(grouped.max(),2)} sunshine hours per observed hour). ")
        else:peak=""
        return (f"{_fmt(total)} h of measured sunshine occur in the selection, "
                f"including {_fmt_hours(measured)} h with positive sunshine duration. "
                +peak+"This identifies the most reliable seasonal and clock-hour opportunities "
                "for direct sunlight and associated glare-control design.")
    return (f"Measured sunshine totals {_fmt(total)} h across {len(valid):,} "
            f"valid source intervals; sunshine occurs within {_fmt_hours(measured)} "
            "hours of the selected period. "
            "The seasonal concentration helps prioritize direct-sun admission and "
            "solar-control strategies.")


def sky_condition_interpretation(df,column=TOTAL):
    s=_numeric(df,column)
    valid=s.dropna()
    if valid.empty:return "No observed sky-cover conditions are available."
    clear=int((valid<=2).sum());overcast=int((valid>=8).sum())
    intermediate=len(valid)-clear-overcast
    base=(f"{LABELS.get(column,'Sky cover').capitalize()} is clear (0–2 tenths) "
          f"for {_fmt_hours(clear*native_interval_hours(df))} h "
          f"({100*clear/len(valid):.1f}%), intermediate (3–7 tenths) "
          f"for {_fmt_hours(intermediate*native_interval_hours(df))} h "
          f"({100*intermediate/len(valid):.1f}%) and overcast (8–10 tenths) "
          f"for {_fmt_hours(overcast*native_interval_hours(df))} h "
          f"({100*overcast/len(valid):.1f}%). ")
    if isinstance(valid.index,pd.DatetimeIndex):
        months=valid.ge(8).groupby(valid.index.month).mean().sort_values(ascending=False)
        if not months.empty:
            base+=f"Overcast conditions are most frequent in month {int(months.index[0])} ({100*months.iloc[0]:.1f}% of valid observations). "
    base+="Overcast frequency prioritizes diffuse-light collection and effective daylight distribution; clear periods motivate direct-sun and glare control."
    if column==OPAQUE and TOTAL in df:
        total=_numeric(df,TOTAL)
        opaque=_numeric(df,OPAQUE)
        paired=total.notna()&opaque.notna()
        conflicts=paired&(opaque>total+1e-9)
        n=int(conflicts.sum())
        if n:
            base+=(f" Source-field consistency flag: {n:,} paired hours "
                   f"({100*n/int(paired.sum()):.1f}%) report opaque sky cover "
                   "greater than total sky cover. Review the corresponding cloud-cover "
                   "observations when drawing opaque-cloud conclusions.")
    return base


def illuminance_interpretation(df,column=GLOBAL,threshold_lux=10000.,kind="illumination"):
    val=_numeric(df,column)
    v=val.dropna()
    if v.empty:return "No valid exterior illuminance observations are available."
    th=float(threshold_lux)
    selected=v.ge(th)
    freq=100*int(selected.sum())/len(v)
    cond=(f"Outdoor {LABELS.get(column,column)} reaches at least {th:g} lux "
          f"for {_fmt_hours(int(selected.sum())*native_interval_hours(df))} h "
          f"({freq:.1f}% of {len(v):,} valid source intervals). ")
    if kind=="illumination" or kind=="threshold":
        return cond+("These hours identify the seasonal and daytime availability of exterior light "
                     "for façade daylight access, electric-light dimming studies and solar/glare controls.")
    return cond


def sky_light_table(df,threshold_lux=3000.):
    """Monthly bright exterior-light hours for clear, mixed and overcast sky."""
    if not isinstance(df.index,pd.DatetimeIndex):
        raise ValueError("Sky and daylight combinations require dated observations.")
    s=_numeric(df,TOTAL)
    lux=_numeric(df,GLOBAL)
    paired=s.notna() & lux.notna()
    bright=lux.ge(float(threshold_lux)) & paired
    dt=float(native_interval_hours(df))
    classes={
        "Clear 0–2 tenths":s.le(2),
        "Intermediate >2–<8":s.gt(2)&s.lt(8),
        "Overcast 8–10 tenths":s.ge(8),
    }
    rows=pd.DataFrame({label:(mask&bright).astype(float)*dt
                       for label,mask in classes.items()},index=df.index)
    rows["Valid paired hours"]=paired.astype(float)*dt
    rows["Bright exterior hours"]=bright.astype(float)*dt
    summary=rows.groupby(rows.index.month).sum(min_count=1)
    summary.index.name="Month"
    return summary


def sky_joint_interpretation(df,threshold_lux=3000.):
    """Interpret coincident sky cover and available exterior illumination."""
    s=_numeric(df,TOTAL)
    light=_numeric(df,GLOBAL)
    paired=pd.DataFrame({"sky":s,"lux":light},index=df.index).dropna()
    if paired.empty:return "Sky-cover and exterior-illuminance observations can be compared when both are available."
    overcast=paired.sky.ge(8)
    bright=paired.lux.ge(float(threshold_lux))
    n=int((overcast&bright).sum())
    clear=int((paired.sky.le(2)&bright).sum())
    return (f"Global horizontal illuminance ≥{float(threshold_lux):,.0f} lux coincides with "
            f"overcast sky (8–10 tenths) for {_fmt_hours(n*native_interval_hours(df))} h "
            f"and clear sky (0–2 tenths) for {_fmt_hours(clear*native_interval_hours(df))} h. "
            "Bright overcast periods support diffuse-daylight admission; bright clear periods "
            "indicate opportunities for daylight access alongside glare and direct-sun control.")


def sky_radiation_scatter_interpretation(df):
    """Describe irradiance contrasts on matched daylight source records."""
    s=_numeric(df,TOTAL)
    ghi=_numeric(df,GHI)
    dt=float(native_interval_hours(df))
    paired=pd.DataFrame({"sky":s,"ghi":ghi/dt},index=df.index).dropna()
    paired=paired.loc[paired.ghi.gt(0)]
    if paired.empty:
        return "Coincident daytime sky cover and positive global horizontal irradiance provide the basis for cloud–radiation comparison."
    clear=paired.loc[paired.sky.le(2),"ghi"]
    overcast=paired.loc[paired.sky.ge(8),"ghi"]
    descriptions=[]
    if not clear.empty:descriptions.append(f"clear sky: {_fmt(clear.mean())} W/m² across {len(clear):,} intervals")
    if not overcast.empty:descriptions.append(f"overcast sky: {_fmt(overcast.mean())} W/m² across {len(overcast):,} intervals")
    return (f"Across {len(paired):,} coincident positive-GHI daylight observations, "
            +"; ".join(descriptions)+". "
            "Sky-cover and horizontal-irradiance pairs reveal how cloud conditions influence "
            "the available solar and daylight resource across the observed solar positions.")


def sky_figure_interpretation(df,fig,kind,*,column="",title="",args=(),latitude=None):
    """One interpretation contract for interactive, atlas and standard-report figures."""
    kind=str(kind).lower()
    title=str(title or getattr(getattr(getattr(fig,"layout",None),"title",None),"text","") or "")
    kind=canonical_profile_kind(kind,title,args)
    if kind=="daylight":
        return daylight_interpretation(df,latitude) if latitude is not None else "Astronomical daylight is determined from the represented dates and site latitude."
    if kind in ("sunshine","sunshine_heatmap","relative_sunshine"):
        return sunshine_interpretation(df,latitude=latitude,kind=kind)
    if kind=="sky_conditions":
        return sky_condition_interpretation(df,column or TOTAL)
    if kind=="illumination":
        return illuminance_interpretation(df,column or GLOBAL,threshold_lux=(float(args[0]) if args and isinstance(args[0],(int,float)) else 300.))
    if kind=="sky_scatter":
        return sky_radiation_scatter_interpretation(df)
    if kind=="sky_joint":
        return sky_joint_interpretation(df,threshold_lux=(float(args[0]) if args else 3000.))
    if not column:
        return sky_joint_interpretation(df)
    v=_numeric(df,column).dropna()
    if v.empty:return "The selected chart has no valid outdoor sky or daylight observations."
    if column in (TOTAL,OPAQUE):
        context=sky_condition_interpretation(df,column)
        unit="tenths"
    elif column==SUN:
        context=sunshine_interpretation(df,latitude=latitude)
        unit="s"
    else:
        context=illuminance_interpretation(df,column)
        unit="lux"
    if kind in ("profile","percentile","time_series / profile","time_series","native"):
        centre="median" if kind=="percentile" or "median" in title.lower() else "mean"
        observed=kind in ("time_series","native") or "observed values" in title.lower()
        vals,x=_plotted(fig,None if observed else centre)
        if vals.empty: vals,x=_plotted(fig)
        if not vals.empty:
            lo=int(vals.idxmin());hi=int(vals.idxmax())
            at=lambda i:format_plotted_time(x[i],df,title=title) if i<len(x) else f"point {i+1}"
            return (f"In the selected {LABELS.get(column,column)} plot, the "
                    f"{'observed value' if observed else centre} is lowest at "
                    f"{at(lo)} ({_fmt(vals.iloc[lo])} {unit}) and highest at "
                    f"{at(hi)} ({_fmt(vals.iloc[hi])} {unit}). "+context)
    if kind in ("heatmap","heat map"):
        for tr in getattr(fig,"data",()):
            if getattr(tr,"type","")=="heatmap":
                z=np.asarray(tr.z,dtype=float)
                if z.ndim==2 and np.isfinite(z).any():
                    a=np.unravel_index(np.nanargmax(z),z.shape)
                    x=list(tr.x);y=list(tr.y)
                    return (f"Highest displayed {LABELS.get(column,column)} cell: "
                            f"{_fmt(z[a])} {unit} at x={x[a[1]]}, y={y[a[0]]}. "+context)
    if kind in ("duration","duration curve"):
        return (f"Ranked {LABELS.get(column,column)}: P05 {_fmt(v.quantile(.05))}, "
                f"median {_fmt(v.median())}, P95 {_fmt(v.quantile(.95))} {unit}. "
                +context)
    if kind in ("histogram","box","violin","monthly boxplot","monthly violin plot","occurrence"):
        return (f"The {LABELS.get(column,column)} distribution has P05 {_fmt(v.quantile(.05))}, "
                f"median {_fmt(v.median())} and P95 {_fmt(v.quantile(.95))} {unit}. "+context)
    if kind in ("diurnal","typical daily profile"):
        if isinstance(v.index,pd.DatetimeIndex):
            grouped=v.groupby([v.index.month,v.index.hour]).mean()
            if not grouped.empty:
                month,hour=grouped.idxmax()
                return (f"Month–hour mean {LABELS.get(column,column)} is highest in "
                        f"month {month} at {hour:02d}:00 ({_fmt(grouped.max())} {unit}). "+context)
    return context
