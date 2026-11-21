"""P4 observed extremes, persistence and empirical engineering statistics.

No weather-generation, code-design value, or extrapolated return level is implied.
Every run is on real chronological coordinates; missing values break events.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .aggregations import native_interval_hours
from .p3_comfort import numeric,T,RH,W,V
P="liquid_precipitation_depth_mm"
SNOW="snow_depth_cm"
H="moist_air_enthalpy_kj_kg"

def ordered(df):
    if not isinstance(df.index,pd.DatetimeIndex) or df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise ValueError("Analysis requires sorted unique datetime coordinates.")
    return df

def cadence(df):
    ordered(df)
    dt=native_interval_hours(df)
    if not np.isfinite(dt) or dt<=0 or dt>24:
        raise ValueError("A positive hourly/subdaily cadence is required.")
    return pd.Timedelta(hours=dt)

def valid_values(df,column,nonnegative=False):
    s=numeric(df,column)
    if nonnegative:s=s.where(s.ge(0))
    if column==RH:s=s.where(s.between(0,100))
    return s

def daily_stats(df,column,*,nonnegative=False):
    """Admit complete days only, checking every native timestamp; no partial-day extrema."""
    dt=cadence(df)
    if dt>pd.Timedelta(hours=1):
        raise ValueError("Daily extrema need hourly or finer source samples.")
    s=valid_values(df,column,nonnegative)
    daily=s.resample("D").agg(["min","mean","max","count"])
    daily["sum"]=s.resample("D").sum(min_count=1)
    for day,group in s.groupby(s.index.normalize()):
        expected=pd.date_range(day,day+pd.DateOffset(days=1),freq=dt,inclusive="left")
        # Canonical source clock uses interval-start labels. A fixed phase offset
        # is allowed only within the day and only if every expected slot exists.
        if len(group):
            phase=group.index[0]-day
            phase=phase%dt
            expected=expected+phase
        ok=group.index.equals(expected)&group.notna().all()
        if not ok:daily.loc[day,["min","mean","max","sum"]]=np.nan
    daily.loc[daily["count"].eq(0),["min","mean","max","sum"]]=np.nan
    return daily

def events(values,*,threshold,above=True,minimum=1,step=None,daily=False,inclusive=True):
    """Maximal runs, separate duration/count and excess intensity integral.
    Daily events use consecutive civil dates and K·day-like units; interval
    events use exact elapsed cadence and quantity·h. Boundaries are inclusive
    observation labels, not inferred physical event onset/end times.
    """
    s=pd.to_numeric(values,errors="coerce").replace([np.inf,-np.inf],np.nan)
    if not isinstance(s.index,pd.DatetimeIndex) or s.index.has_duplicates or not s.index.is_monotonic_increasing:
        raise ValueError("Events require sorted unique timestamps.")
    if minimum<=0 or not np.isfinite(threshold):raise ValueError("Invalid event parameters.")
    if not daily and (step is None or step<=pd.Timedelta(0)):raise ValueError("A declared step is required.")
    duration=1. if daily else step.total_seconds()/3600
    rows=[];run=[];prev=None
    def finish():
        if len(run)*duration>=minimum:
            ts=[r[0] for r in run];v=np.asarray([r[1] for r in run],float)
            excess=np.maximum(v-threshold if above else threshold-v,0)
            rows.append(dict(start=ts[0],end=ts[-1],duration=len(v)*duration,
                             samples=len(v),minimum=float(v.min()),maximum=float(v.max()),
                             mean=float(v.mean()),peak=float(v.max() if above else v.min()),
                             excess=float(excess.sum()*duration)))
        run.clear()
    for stamp,value in s.items():
        consecutive=prev is not None and (stamp==prev+pd.DateOffset(days=1) if daily else stamp-prev==step)
        if not consecutive:finish()
        hit=pd.notna(value) and (value>=threshold if above and inclusive else value>threshold if above else value<=threshold if inclusive else value<threshold)
        if hit:run.append((stamp,value))
        else:finish()
        prev=stamp
    finish()
    return pd.DataFrame(rows,columns=["start","end","duration","samples","minimum","maximum","mean","peak","excess"])

def temperature_events(df,*,threshold,above,minimum,stat):
    d=daily_stats(df,T)
    return d,events(d[stat],threshold=threshold,above=above,minimum=minimum,daily=True)

def day_indicators(df):
    d=daily_stats(df,T)
    return pd.DataFrame({"Frost days (Tmin < 0 °C)":d["min"].lt(0).astype(float).where(d["min"].notna()),
                        "Tropical nights (daily Tmin ≥ 20 °C)":d["min"].ge(20).astype(float).where(d["min"].notna())},index=d.index)

def wet_dry_events(df,threshold=1.,minimum=1):
    if threshold<=0:raise ValueError("Wet-day threshold must be positive.")
    d=daily_stats(df,P,nonnegative=True)
    return d,events(d["sum"],threshold=threshold,above=True,minimum=minimum,daily=True),events(d["sum"],threshold=threshold,above=False,minimum=minimum,daily=True,inclusive=False)

def rolling_windows(df,column,hours,*,total=False,nonnegative=False):
    """Trailing complete sample windows, never bridge excluded or missing records."""
    dt=cadence(df);n=hours*3600/dt.total_seconds()
    if n<1 or not np.isclose(n,round(n)):raise ValueError("Window must be an integer multiple of source cadence.")
    n=int(round(n));s=valid_values(df,column,nonnegative)
    groups=(s.index.to_series().diff().ne(dt)).cumsum()
    rolling=s.groupby(groups,group_keys=False).transform(lambda x:x.rolling(n,min_periods=n).sum() if total else x.rolling(n,min_periods=n).mean())
    return rolling

def cumulative_precipitation(df):
    """Within observed contiguous record blocks, reset at gaps and unknown values."""
    dt=cadence(df);s=valid_values(df,P,True)
    br=s.index.to_series().diff().ne(dt)|s.isna()|s.shift().isna()
    return s.groupby(br.cumsum()).cumsum()

def freeze_thaw_days(df,wet_threshold=1.):
    d=daily_stats(df,T)
    # One air-temperature crossing opportunity/day, not a count of material cycles.
    known=d["min"].notna()&d["max"].notna()
    cross=d["min"].lt(0)&d["max"].gt(0)
    result=pd.DataFrame({"Air freeze–thaw days":cross.astype(float).where(known)})
    if P in df:
        rain=daily_stats(df,P,nonnegative=True)["sum"]
        result["Wet freeze–thaw days"]=(cross&rain.ge(wet_threshold)).astype(float).where(known&rain.notna())
    return result

def complete_years(df,column):
    """Only years with every expected timestamp and a finite nonnegative value."""
    dt=cadence(df);s=valid_values(df,column,True);out=[]
    for year,g in s.groupby(s.index.year):
        start=pd.Timestamp(year=int(year),month=1,day=1,tz=s.index.tz)
        stop=start+pd.DateOffset(years=1)
        expected=pd.date_range(start,stop,freq=dt,inclusive="left")
        if len(g) and g.index.equals(expected) and g.notna().all():out.append(int(year))
    return out

def empirical_idf(df,*,historical_native=False,durations=(.25,.5,1,2,3,6,12,24),minimum_years=10):
    """Complete-year native block maxima, empirical Weibull plotting positions.
    No distribution fitting or return periods beyond observations. No TMY input.
    Rolling windows are constrained to the same complete calendar year.
    """
    if not historical_native:raise ValueError("IDF requires provider-native measured historical precipitation (not EPW or generated climate).")
    declared=df.attrs.get("canonical_native_interval_minutes")
    if declared is None or not np.isfinite(float(declared)) or not 0<float(declared)<=60:
        raise ValueError("IDF requires a declared native cadence of 60 minutes or finer.")
    if minimum_years<10:raise ValueError("At least ten complete years are required.")
    years=complete_years(df,P)
    if len(years)<minimum_years:raise ValueError(f"Only {len(years)} complete calendar years; at least {minimum_years} required.")
    dt=cadence(df).total_seconds()/3600
    rows=[]
    for hours in durations:
        if hours<dt or not np.isclose(hours/dt,round(hours/dt)):continue
        maxima=[]
        for y in years:
            frame=df.loc[df.index.year==y].copy();frame.attrs.update(df.attrs)
            rolling=rolling_windows(frame,P,hours,total=True,nonnegative=True)
            maxima.append((y,float(rolling.max()/hours)))
        maxima.sort(key=lambda a:(-a[1],a[0]))
        for rank,(year,intensity) in enumerate(maxima,1):
            rows.append(dict(duration_h=hours,year=year,intensity_mm_h=intensity,
                             rank=rank,return_period_y=(len(years)+1)/rank,complete_years=len(years)))
    return pd.DataFrame(rows)

def design_conditions(df,column,percentages,*,upper=True,coincident=()):
    """Empirical selected-hour quantiles and actual closest observed state.
    Stable first timestamp resolves exact ties; paired tail mean separately
    computed from valid observations, not an ASHRAE coincident design bin.
    """
    ordered(df);s=valid_values(df,column).dropna()
    rows=[]
    for pct in percentages:
        if not 0<pct<50:raise ValueError("Tail fraction must be between 0 and 50 percent.")
        if s.empty:continue
        q=float(s.quantile(1-pct/100 if upper else pct/100))
        stamp=(s-q).abs().idxmin()
        tail=s.ge(q) if upper else s.le(q)
        row={"Nominal tail [%]":pct,"Quantile":q,"Closest timestamp":stamp,
             "Observed value":s.loc[stamp],"Valid hours":len(s)*native_interval_hours(df),
             "Actual inclusive tail [%]":100*tail.mean()}
        for c in coincident:
            values=valid_values(df,c)
            row[c+" · coincident"]=values.loc[stamp]
            paired=values.reindex(s.index[tail]).dropna()
            row[c+" · tail mean"]=paired.mean()
            row[c+" · paired hours"]=len(paired)*native_interval_hours(df)
        rows.append(row)
    return pd.DataFrame(rows)

def correlation(df,columns):
    """Pairwise Pearson r and coincident sample counts; angular data excluded by UI."""
    a=pd.DataFrame({c:valid_values(df,c) for c in columns})
    valid=a.notna().astype(int)
    return a.corr(min_periods=3),valid.T@valid

def joint_density(df,x,y,*,bins=25):
    """Joint probability mass per fixed-width cell, not a KDE or independent marginals."""
    a=pd.DataFrame({"x":valid_values(df,x),"y":valid_values(df,y)}).dropna()
    if a.empty:return None
    counts,xe,ye=np.histogram2d(a.x,a.y,bins=bins)
    return (xe[:-1]+xe[1:])/2,(ye[:-1]+ye[1:])/2,counts.T/counts.sum()*100,counts.T*native_interval_hours(df)
