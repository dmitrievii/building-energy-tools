"""R2.3 — source-neutral wind interpretation and orientation screening.

Meteorological direction is the bearing wind COMES FROM. Directional hours are
station weather observations, never measured facade pressures, airflow or comfort.
Only scalar velocity is thresholded; no pressure coefficient or opening size is
implicitly inferred.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .aggregations import native_interval_hours
from .interpretations import _fmt, _fmt_hours

COMPASS = ("N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW")
SPEED = "wind_speed_m_s"
DIRECTION = "wind_direction_deg"
GUST = "wind_gust_speed_m_s"
GUST_DIRECTION = "wind_gust_direction_deg"
TEMP = "dry_bulb_temperature_c"
MOISTURE = "humidity_ratio_g_kg"
RAIN = "liquid_precipitation_depth_mm"


def _numeric(df, column):
    if column not in df:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce").replace([np.inf, -np.inf],np.nan)


def _sector_number(direction):
    """Direction 360° is N; exact boundaries are centered on 16 headings."""
    return (np.floor((direction % 360.0 + 11.25) / 22.5).astype(int) % 16)


def _sector_text(code):
    return COMPASS[int(code) % 16]


def opposite_sector(name):
    return COMPASS[(COMPASS.index(str(name)) + 8) % 16]


def wind_opportunity(
    df, *, min_speed_m_s=0.5, rain_max_mm_h=None,
    temperature_range_c=None, max_humidity_ratio_g_kg=None,
    speed=SPEED, direction=DIRECTION,
):
    """Monthly climatic exposure and candidate windward/leeward axes.

    A wind threshold is illustrative and user configurable. Any optional
    weather screening variable must have a valid observation. A missing
    rainfall/humidity/temperature column never silently passes a screen.
    Month rows pool the selected source years; no annualization is implied.

    Returns (summary, sector_table). Every directional selected hour belongs
    to exactly one 22.5° sector. 'Low-wind' is independent of optional
    rain, temperature and humidity screening.
    """
    threshold=float(min_speed_m_s)
    if not np.isfinite(threshold) or threshold < 0:
        raise ValueError("Minimum station wind speed must be finite and >= 0.")
    if rain_max_mm_h is not None and (not np.isfinite(rain_max_mm_h) or rain_max_mm_h < 0):
        raise ValueError("Rain limit must be >= 0 mm/h.")
    if temperature_range_c is not None:
        lo, hi=map(float,temperature_range_c)
        if not np.isfinite([lo,hi]).all() or lo>hi:
            raise ValueError("Temperature limits must be finite and increasing.")
    if max_humidity_ratio_g_kg is not None and (not np.isfinite(max_humidity_ratio_g_kg) or max_humidity_ratio_g_kg<0):
        raise ValueError("Humidity ratio cap must be >= 0 g/kg dry air.")
    if not isinstance(df.index,pd.DatetimeIndex):
        raise ValueError("Wind orientation screening requires dated climate observations.")
    from .extended_visualization import hourly_capable
    if not hourly_capable(df):
        raise ValueError("Wind orientation hours require subdaily observations at <=1-hour cadence, not monthly aggregates.")
    dt=float(native_interval_hours(df))
    if not np.isfinite(dt) or dt<=0:
        raise ValueError("Native source interval must be positive.")
    v=_numeric(df,speed)
    d=_numeric(df,direction)
    rain=_numeric(df,RAIN)
    t=_numeric(df,TEMP)
    w=_numeric(df,MOISTURE)
    wind_valid=v.ge(0)&v.notna()
    direction_valid=d.between(0,360)
    above=wind_valid & v.gt(threshold)
    directional=above & direction_valid
    selected=directional.copy()
    if rain_max_mm_h is not None:
        selected &= rain.ge(0)&(rain/dt<=float(rain_max_mm_h))
    if temperature_range_c is not None:
        selected &= t.between(lo,hi)
    if max_humidity_ratio_g_kg is not None:
        selected &= w.between(0,float(max_humidity_ratio_g_kg))
    codes=pd.Series(-1,index=df.index,dtype=int)
    codes.loc[direction_valid]=_sector_number(d.loc[direction_valid]).astype(int)
    months=np.asarray(df.index.month,dtype=int)
    summary=[]
    details=[]
    for month in sorted(set(months.tolist())):
        in_month=months==month
        valid_count=int((wind_valid&in_month).sum())
        low_count=int((wind_valid & v.le(threshold) & in_month).sum())
        missing_direction=int((above & ~direction_valid & in_month).sum())
        dir_count=int((directional & in_month).sum())
        picked=int((selected & in_month).sum())
        for sector in range(16):
            condition=(codes==sector)&in_month
            raw=condition&directional
            chosen=condition&selected
            num=int(chosen.sum())
            r=rain.loc[chosen]
            tmp=t.loc[chosen]
            moist=w.loc[chosen]
            details.append(dict(
                month=month,sector=COMPASS[sector],bearing_deg=sector*22.5,
                selected_hours=num*dt,wind_observation_hours=int(raw.sum())*dt,
                share_of_valid_source_hours_pct=100*num/max(1,valid_count),
                share_of_selected_directional_hours_pct=100*num/max(1,picked),
                rain_hours=int((r>0).sum())*dt if r.notna().any() else np.nan,
                dry_hours=int((r==0).sum())*dt if r.notna().any() else np.nan,
                mean_temperature_c=float(tmp.mean()) if tmp.notna().any() else np.nan,
                mean_humidity_ratio_g_kg=float(moist.mean()) if moist.notna().any() else np.nan,
            ))
        ordered=sorted(
            [(int(((codes==code)&selected&in_month).sum()),code) for code in range(16)],
            key=lambda pair:(-pair[0],pair[1]),
        )
        count,leader=ordered[0]
        summary.append(dict(
            month=month, valid_source_hours=valid_count*dt,
            low_wind_hours=low_count*dt,
            low_wind_pct_of_valid=100*low_count/max(1,valid_count),
            directional_wind_hours=dir_count*dt,
            direction_missing_hours=missing_direction*dt,
            selected_directional_hours=picked*dt,
            leading_from=COMPASS[leader] if count else "n/a",
            candidate_opposite=COMPASS[(leader+8)%16] if count else "n/a",
            leading_hours=count*dt,
            leading_share_of_selected_pct=100*count/max(1,picked),
        ))
    return pd.DataFrame(summary),pd.DataFrame(details)


def wind_design_interpretation(
    df, *, min_speed_m_s=0.5, rain_max_mm_h=None,
    temperature_range_c=None, max_humidity_ratio_g_kg=None,
    speed=SPEED, direction=DIRECTION,
):
    """Interpret monitored winds as candidate *orientation*, not airflow."""
    summary, sectors=wind_opportunity(
        df,min_speed_m_s=min_speed_m_s, rain_max_mm_h=rain_max_mm_h,
        temperature_range_c=temperature_range_c,
        max_humidity_ratio_g_kg=max_humidity_ratio_g_kg,
        speed=speed,direction=direction,
    )
    if summary.empty:
        return "No dated wind observations support an orientation analysis."
    total_valid=summary.valid_source_hours.sum()
    total_low=summary.low_wind_hours.sum()
    selected=summary.selected_directional_hours.sum()
    if selected<=0:
        return (f"The selected wind and outdoor-air conditions coincide during 0 directional hours. "
                f"{_fmt_hours(total_low)} of {_fmt_hours(total_valid)} valid station-wind hours "
                f"are at or below {min_speed_m_s:g} m/s. "
                "These settings yield no qualifying windward sector; adjust the climatic screening criteria to explore other operating regimes.")
    ranked=sectors.groupby("sector",sort=False).selected_hours.sum().sort_values(ascending=False)
    leader=ranked.index[0]
    runner=ranked.index[1] if len(ranked)>1 else leader
    worst=summary.sort_values("low_wind_pct_of_valid",ascending=False).iloc[0]
    seasons=[]
    for months,label in (((12,1,2,3),"Dec–Mar"),((6,7,8),"Jun–Aug")):
        piece=sectors.loc[sectors.month.isin(months)]
        by_sector=piece.groupby("sector").selected_hours.sum().sort_values(ascending=False)
        if not by_sector.empty and float(by_sector.iloc[0])>0:
            from_sector=str(by_sector.index[0])
            seasons.append(f"{label}: wind from {from_sector} "
                           f"({_fmt_hours(by_sector.iloc[0])} h; opposite axis "
                           f"{opposite_sector(from_sector)})")
    seasonal_summary=(". Calendar blocks: "+"; ".join(seasons)+". ") if seasons else " "
    restriction=[]
    if rain_max_mm_h is not None:restriction.append(f"rain ≤{rain_max_mm_h:g} mm/h")
    if temperature_range_c is not None:restriction.append(
        f"temperature {temperature_range_c[0]:g}–{temperature_range_c[1]:g} °C")
    if max_humidity_ratio_g_kg is not None:restriction.append(
        f"humidity ratio ≤{max_humidity_ratio_g_kg:g} g/kg")
    qualifier=" and ".join(restriction) if restriction else "all observed temperature, humidity and rainfall conditions"
    return (
        f"Using station wind >{min_speed_m_s:g} m/s and {qualifier}, "
        f"{_fmt_hours(selected)} directional hours remain from "
        f"{_fmt_hours(total_valid)} valid station-wind hours. "
        f"Most frequent incoming sectors are {leader} ({_fmt_hours(ranked.iloc[0])} h) "
        f"and {runner} ({_fmt_hours(ranked.iloc[1]) if len(ranked)>1 else '0'} h). "
        f"Candidate windward/exhaust façade axes include {leader}–{opposite_sector(leader)} "
        "and the seasonally relevant alternative bearings; these are meteorological FROM directions. "
        +seasonal_summary+
        f"Low/weak wind accounts for {_fmt_hours(total_low)} h ({100*total_low/max(1,total_valid):.1f}%). "
        f"The highest monthly low-wind share is month {int(worst.month)} "
        f"({worst.low_wind_pct_of_valid:.1f}%). "
        "The identified wind directions indicate candidate intake and exhaust exposure. The weakest-wind months prioritize fan-assisted or hybrid ventilation design."
    )


def wind_opportunity_figure(summary, sectors):
    """Compact month × wind-FROM sector heat map, with low-wind column."""
    columns=list(COMPASS)+["≤ speed limit"]
    months=summary["month"].tolist()
    mat=[]
    for row in summary.itertuples():
        s=sectors.loc[sectors.month==row.month].set_index("sector")
        n=max(float(row.valid_source_hours),1e-12)
        vals=[float(s.loc[d,"selected_hours"])/n*100 for d in COMPASS]
        vals.append(float(row.low_wind_pct_of_valid))
        mat.append(vals)
    f=go.Figure(go.Heatmap(
        z=mat,x=columns,y=months,
        zmin=0,zmax=max(10,float(np.nanmax(mat)) if mat else 10),
        colorscale="Blues",colorbar=dict(title="% of valid wind hours"),
        hovertemplate="Month %{y}<br>FROM sector %{x}<br>%{z:.1f}%<extra></extra>",
        xgap=1,ygap=1))
    f.update_layout(
        template="plotly_white",title="Monthly wind orientation opportunity — station weather",
        xaxis_title="Meteorological FROM sector; low-wind column is directionless",
        yaxis=dict(title="Month",tickmode="array",tickvals=list(range(1,13)),autorange="reversed"),
        height=570,margin=dict(l=50,r=20,t=65,b=80))
    return f


def _plotted(fig, preferred=None):
    if fig is None:return pd.Series(dtype=float),[]
    for tr in getattr(fig,"data",()):
        name=str(getattr(tr,"name","") or "")
        if preferred and preferred.lower() not in name.lower():continue
        if "quantile marker" in name.lower() or "threshold" in name.lower():continue
        raw=getattr(tr,"y",None)
        if raw is None:continue
        arr=np.asarray(raw,dtype=object)
        if arr.ndim!=1 or len(arr)==0:continue
        s=pd.to_numeric(pd.Series(arr),errors="coerce")
        if s.notna().any():
            x=getattr(tr,"x",None)
            return s,list(x) if x is not None else []
    return pd.Series(dtype=float),[]


def wind_figure_interpretation(df,fig,kind,*,column=SPEED,title="",args=()):
    """Kind-specific evidence for scalar and circular wind plots."""
    kind=str(kind).lower()
    if str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly":
        from .interpretations import variable_interpretation
        available=_numeric(df,column).dropna()
        if available.empty:return "No numeric monthly wind observations are available."
        return (f"{len(available):,} native monthly wind observations are represented; "
                f"range {_fmt(available.min())}–{_fmt(available.max())}. "
                "The monthly series describes seasonal average wind conditions; hourly wind availability is evaluated with hourly observations.")
    label=str(title or getattr(getattr(getattr(fig,"layout",None),"title",None),"text","") or "")
    lower_label=label.lower()
    args=tuple(args or ())
    is_gust=column in (GUST,GUST_DIRECTION)
    s_col=GUST if is_gust else SPEED
    d_col=GUST_DIRECTION if is_gust else DIRECTION
    velocity=_numeric(df,s_col)
    direction=_numeric(df,d_col)
    valid=velocity.notna()&velocity.ge(0)
    n=int(valid.sum())
    if n==0:return "No valid nonnegative station wind-speed observations."
    dt=native_interval_hours(df)
    zero=int((valid&velocity.eq(0)).sum())*dt
    weak=int((valid&velocity.le(0.5)).sum())*dt
    v=velocity.loc[valid]
    source_label="station-gust" if is_gust else "station-wind"
    mean_label="mean of recorded gust peaks" if is_gust else "mean wind speed"
    header=(f"{_fmt_hours(n*dt)} valid observed {source_label} hours; "
            f"{mean_label} {_fmt(v.mean())} m/s, "
            f"exact zeros {_fmt_hours(zero)} h and recorded speed ≤0.5 m/s "
            f"{_fmt_hours(weak)} h. ")
    warning=("Gust peaks and their associated directions describe short-duration wind exposure and façade protection priorities. " if is_gust else "")
    direction_valid=(valid&velocity.gt(0)&direction.between(0,360))
    sector_counts=pd.Series(dtype=int)
    if direction_valid.any():
        codes=_sector_number(direction.loc[direction_valid])
        sector_counts=codes.value_counts()
    direction_note=(
        f"The most frequent non-calm meteorological FROM sector is "
        f"{_sector_text(sector_counts.idxmax())}, with "
        f"{_fmt_hours(int(sector_counts.max())*dt)} h out of "
        f"{_fmt_hours(int(direction_valid.sum())*dt)} directionally classified hours. "
        if not sector_counts.empty else
        "No non-calm observations have a valid wind-FROM bearing. ")
    direction_note+=("Directional shares use valid non-calm observations; the low-wind frequency is given separately above. ")
    caveat=("Wind directions identify candidate façade exposures for testing intake and exhaust paths in the building layout.")

    if column in (DIRECTION,GUST_DIRECTION):
        return (header+direction_note+warning+
                "Wind direction is circular: 359° and 1° both indicate northerly flow. "+caveat)
    if kind in ("wind_panel",):
        monthly=[]
        for month in sorted(set(df.index.month)):
            mask=direction_valid & (df.index.month==month)
            if mask.any():
                codes=_sector_number(direction.loc[mask])
                top=_sector_text(codes.value_counts().idxmax())
                calm=int((valid&velocity.le(.5)&(df.index.month==month)).sum())*dt
                monthly.append((month,top,calm))
        if not monthly:return header+direction_note+caveat
        hi=max(monthly,key=lambda t:t[2])
        first=monthly[0];last=monthly[-1]
        return (header+f"Monthly leading FROM sectors include "
                f"month {first[0]}: {first[1]} and month {last[0]}: {last[1]}. "
                f"Month {hi[0]} has the largest count of low-wind hours "
                f"({_fmt_hours(hi[2])} h). The seasonal sectors indicate which intake and exhaust orientations are worth prioritizing. "+caveat)
    if kind in ("profile","percentile","time_series","time series / profile","native"):
        observed=kind in ("time_series","native") or "observed values" in lower_label
        center=("observed" if observed else
                "median" if kind=="percentile" or "median" in lower_label else "mean")
        plotted,x=_plotted(fig,None if observed else center)
        if not plotted.empty:
            low,high=int(plotted.idxmin()),int(plotted.idxmax())
            at=lambda ix:str(x[ix]) if ix<len(x) else str(ix+1)
            info=(f"Selected plotted {center} speed is lowest at {at(low)} "
                  f"({_fmt(plotted.iloc[low])} m/s) and highest at {at(high)} "
                  f"({_fmt(plotted.iloc[high])} m/s). ")
        else:info=""
        return header+info+warning+direction_note+caveat
    if kind in ("heatmap","heat map"):
        traces=[tr for tr in getattr(fig,"data",()) if getattr(tr,"type","")=="heatmap"]
        if traces:
            z=np.asarray(traces[0].z,dtype=float)
            if z.ndim==2 and np.isfinite(z).any():
                info=(f"The selected heatmap statistic spans {_fmt(np.nanmin(z))} to "
                      f"{_fmt(np.nanmax(z))} m/s across displayed cells. ")
            else:info=""
        else:info=""
        return header+info+warning+direction_note+caveat
    if kind in ("duration","duration curve","histogram","box","violin",
                "monthly boxplot","monthly violin plot"):
        info=(f"P05 {_fmt(v.quantile(.05))} m/s, median {_fmt(v.median())} m/s, "
              f"P95 {_fmt(v.quantile(.95))} m/s; "
              f"{_fmt_hours(int((v>2).sum())*dt)} h above 2 m/s. ")
        if kind in ("duration","duration curve"):
            info+="The ranked curve shows the cumulative frequency of observed wind speeds. "
        return header+info+warning+direction_note+caveat
    if kind in ("diurnal","typical daily profile"):
        mean=v.groupby(v.index.hour).mean() if isinstance(v.index,pd.DatetimeIndex) else pd.Series(dtype=float)
        if mean.empty:return header+direction_note+caveat
        return (header+f"Mean speed across selected clock hours is highest at "
                f"{int(mean.idxmax()):02d}:00 ({_fmt(mean.max())} m/s), "
                f"lowest at {int(mean.idxmin()):02d}:00 ({_fmt(mean.min())} m/s). "
                +direction_note+caveat)
    if kind=="occurrence":
        counts=[]
        for tr in getattr(fig,"data",()):
            y=getattr(tr,"y",None)
            if y is None:continue
            numeric=pd.to_numeric(pd.Series(np.asarray(y,dtype=object)),errors="coerce")
            if numeric.notna().any():
                counts.append((float(numeric.sum()),str(getattr(tr,"name","") or "class")))
        leader=max(counts,key=lambda item:item[0])[1] if counts else "not resolved"
        return (header+f"The largest plotted wind-speed class is {leader}; "
                "The distribution highlights the prevailing speed category for the selected time aggregation. "
                +direction_note+caveat)
    if kind=="persistence":
        threshold=float(args[0]) if args else 0.5
        above=bool(args[1]) if len(args)>1 else False
        qualifying=(v>=threshold) if above else (v<=threshold)
        comparator="at or above" if above else "at or below"
        return (header+f"{_fmt_hours(int(qualifying.sum())*dt)} h occur {comparator} the "
                f"selected {threshold:g} m/s threshold; continuous run lengths, "
                "together with total hours, describe the reliability of calm and windy periods. "+caveat)
    return header+warning+direction_note+caveat
