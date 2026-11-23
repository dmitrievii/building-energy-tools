"""R2.4 — evidence-based solar and façade interpretation.

Intervals are solar *irradiation* in Wh/m²; physical power-equivalent W/m²
requires division by source interval hours. Horizontal, direct-normal and
tilted-plane quantities must never be added as though they share a plane.
Thermal-exposure bins use OUTDOOR temperature only, never building heat loads.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .aggregations import native_interval_hours
from .interpretations import _fmt, _fmt_hours

GHI="global_horizontal_radiation_wh_m2"
DHI="diffuse_horizontal_radiation_wh_m2"
DNI="direct_normal_radiation_wh_m2"
T="dry_bulb_temperature_c"
FRACTION="diffuse_radiation_fraction_pct"
POA="poa_global_wh_m2"
POA_COMPONENTS=(POA,"poa_direct_wh_m2","poa_sky_diffuse_wh_m2","poa_ground_diffuse_wh_m2")
SOURCE=(GHI,DNI,DHI)
QUANTITIES={
    GHI:("global horizontal irradiation","Wh/m²"),
    DNI:("direct normal irradiation","Wh/m²"),
    DHI:("diffuse horizontal irradiation","Wh/m²"),
    FRACTION:("diffuse horizontal fraction","%"),
    POA:("plane-of-array irradiation","Wh/m²"),
    "poa_direct_wh_m2":("direct plane-of-array irradiation","Wh/m²"),
    "poa_sky_diffuse_wh_m2":("sky-diffuse plane-of-array irradiation","Wh/m²"),
    "poa_ground_diffuse_wh_m2":("ground-reflected plane-of-array irradiation","Wh/m²"),
}
DIRECTIONS=("N","NE","E","SE","S","SW","W","NW")


def _number(df,c):
    return (pd.to_numeric(df[c],errors="coerce").replace([np.inf,-np.inf],np.nan)
            if c in df else pd.Series(np.nan,index=df.index,dtype=float))


def _source_context(df,column,*,plane="reference vertical south-facing plane"):
    s=_number(df,column).dropna()
    if s.empty:
        return "No valid selected solar observations."
    name,unit=QUANTITIES.get(column,(column,""))
    hours=native_interval_hours(df)
    if column==FRACTION:
        g=_number(df,GHI)
        d=_number(df,DHI)
        valid=g.gt(0)&d.ge(0)&d.le(g)
        weighted=float(d[valid].sum()/g[valid].sum()*100) if valid.any() and g[valid].sum()>0 else np.nan
        return (f"Selected daylight interval-ratio median {_fmt(s.median())}%, "
                f"mean {_fmt(s.mean())}%; corresponding ratio of coincident positive-"
                f"GHI sums {_fmt(weighted)}%. These statistics differ because one "
                "weights intervals equally and the other by horizontal irradiation; "
                "nighttime zero-GHI ratios are undefined, not zero.")
    result=(f"{name.capitalize()} on the selected intervals: {_fmt(s.sum()/1000)} kWh/m² "
            f"from {len(s):,} valid records (each {hours:g} h); "
            f"maximum interval energy {_fmt(s.max())} {unit}. ")
    if column in SOURCE:
        return result + (
            "GHI and DHI are horizontal-plane quantities; DNI is normal to the "
            "solar beam. DNI cannot be added directly to GHI or DHI. "
            "Irradiance [W/m²] equals interval irradiation [Wh/m²] divided by "
            "source interval duration [h].")
    return result + (
        f"POA values describe the {plane}, with unobstructed isotropic sky "
        "transposition and explicitly selected ground albedo; no surrounding "
        "buildings, vegetation or window transmission are represented.")


def _plotted(fig,preferred=None):
    if fig is None:return pd.Series(dtype=float),[]
    for tr in getattr(fig,"data",()):
        name=str(getattr(tr,"name","") or "")
        if preferred and preferred.lower() not in name.lower():continue
        if "quantile marker" in name.lower() or "threshold" in name.lower():continue
        y=getattr(tr,"y",None)
        if y is None:continue
        vals=np.asarray(y,dtype=object)
        if vals.ndim!=1 or len(vals)==0:continue
        num=pd.to_numeric(pd.Series(vals),errors="coerce")
        if num.notna().any():
            x=getattr(tr,"x",None)
            return num,list(x) if x is not None else []
    return pd.Series(dtype=float),[]


def facade_figure_interpretation(fig,*,tilt_deg=90.):
    """Recover real per-orientation total POA from chart customdata, not labels."""
    rows=[]
    if fig is None:return "No façade irradiation diagram is provided."
    for tr in getattr(fig,"data",()):
        raw=getattr(tr,"customdata",None)
        if raw is None or getattr(tr,"type","") not in ("bar","barpolar"):continue
        vals=np.asarray(raw,dtype=object)
        if vals.ndim!=2 or vals.shape[1]<2:continue
        for direction,total in vals[:,:2]:
            try:
                val=float(total)
            except (TypeError,ValueError):continue
            if np.isfinite(val): rows.append((str(direction),val))
        if rows:break
    if not rows:return "Unobstructed façade totals are displayed; no numerical orientation comparison is available."
    ordered=sorted(rows,key=lambda item:item[1],reverse=True)
    peak=ordered[0];low=ordered[-1]
    ratio=(peak[1]/low[1]) if low[1]>0 else np.nan
    return (f"Unobstructed {tilt_deg:g}°-tilt surface irradiation is highest for "
            f"{peak[0]} ({peak[1]:,.1f} kWh/m²) and lowest for "
            f"{low[0]} ({low[1]:,.1f} kWh/m²); ratio {_fmt(ratio,2)}. "
            "The solar incidence direction is a surface azimuth, clockwise from north. "
            "These are solar-weather exposures, not solar gains through glazing, "
            "space cooling loads, or an optimized façade specification. "
            "Shading, glazing g-value, occupancy and building thermal balance are unmodeled.")


def solar_figure_interpretation(
    df,fig,kind,*,column="",title="",args=(),
    plane="reference vertical south-facing plane",
):
    """Figure-specific interpretation for the Solar Radiation tab and reports."""
    kind=str(kind).lower()
    args=tuple(args or ())
    title=str(title or getattr(getattr(getattr(fig,"layout",None),"title",None),"text","") or "")
    label=title.lower()
    if kind=="facade":
        tilt=float(getattr(getattr(fig,"layout",None),"meta",{}).get("tilt_deg",90.) or 90.)
        return facade_figure_interpretation(fig,tilt_deg=tilt)
    if kind=="tilt":
        maxima=[]
        if fig is not None:
            for tr in fig.data:
                if getattr(tr,"type","")=="heatmap":
                    z=np.asarray(tr.z,dtype=float)
                    if z.ndim==2 and np.isfinite(z).any():
                        i,j=np.unravel_index(np.nanargmax(z),z.shape)
                        maxima.append((float(z[i,j]),f"tilt {tr.y[i]}°, azimuth {tr.x[j]}°"))
                elif getattr(tr,"y",None) is not None and getattr(tr,"x",None) is not None:
                    y=pd.to_numeric(pd.Series(tr.y),errors="coerce")
                    if y.notna().any():
                        i=int(y.idxmax())
                        maxima.append((float(y[i]),f"{str(tr.name)}, azimuth {tr.x[i]}°"))
        if maxima:
            best=max(maxima,key=lambda t:t[0])
            return (f"Maximum modeled unobstructed selected-period plane irradiation "
                    f"is {best[0]:,.1f} kWh/m² at {best[1]} on the plotted grid. "
                    "Grid-optimal incident irradiation does not establish optimal PV electricity "
                    "yield or building energy demand; shading, performance ratio and use matter.")
        return "The tilt/azimuth diagram uses the selected-period unobstructed isotropic POA model."
    if kind=="sky_patches":
        return ("Each patch colour encodes its contribution to horizontal-plane irradiation "
                "over common valid daylight source intervals. Polar bar radius is sky-patch "
                "geometry, not energy. Direct uses DNI projected by solar zenith; diffuse "
                "uses the specified sky model. Total equals direct plus diffuse, with no "
                "ground component. The Perez 1993 option is research-only pending parity. "
                "Patch energy is not sky radiance, irradiance on a façade, or a shading load.")
    if kind=="sunpath_view":
        return ("The solar paths are astronomical references for the selected site and clock; "
                "they describe solar azimuth and altitude, not an irradiation or building "
                "heat-load calculation. Radiation/temperature overlays, where present, "
                "refer only to the selected observations.")
    if kind=="monthly_radiation":
        mode=("source components on distinct measurement planes"
              if any(getattr(t,"name","") in ("GHI","DNI","DHI") for t in getattr(fig,"data",()))
              else "selected plane-of-array irradiation components")
        return (f"The displayed monthly values are interval-irradiation sums for {mode}. "
                "GHI, DHI and DNI cannot be stacked as one physical total. "
                "Compare month-to-month variability and, for POA, surface orientations; "
                "no electrical PV yield or building cooling demand follows directly.")
    if kind in ("scatter","solar_scatter"):
        return solar_temperature_interpretation(df)
    if not column:
        return "No solar quantity was selected."
    name,unit=QUANTITIES.get(column,(column,""))
    v=_number(df,column).dropna()
    if v.empty:
        return f"No valid {name} observations support the selected chart."
    context=_source_context(df,column,plane=plane)
    if kind in ("time_series","native"):
        return context+" The trace retains observation chronology and gaps."
    if kind in ("profile","percentile","time series / profile"):
        centre="median" if kind=="percentile" or "median" in label else "mean"
        vals,x=_plotted(fig,centre)
        if vals.empty:vals,x=_plotted(fig)
        if not vals.empty:
            lo=int(vals.idxmin());hi=int(vals.idxmax())
            at=lambda i:str(x[i]) if i<len(x) else f"point {i+1}"
            return (f"Selected plotted {centre} {name}: lowest at {at(lo)} "
                    f"({_fmt(vals[lo])} {unit}), highest at {at(hi)} "
                    f"({_fmt(vals[hi])} {unit}). "
                    + ("P05–P95 is the central observed variability band, not a confidence interval. "
                       if kind=="percentile" else "") +context)
        return context
    if kind in ("heatmap","heat map"):
        if fig is not None:
            for tr in fig.data:
                if getattr(tr,"type","")=="heatmap":
                    z=np.asarray(tr.z,dtype=float)
                    if z.ndim==2 and np.isfinite(z).any():
                        hi=np.unravel_index(np.nanargmax(z),z.shape)
                        x=list(tr.x);y=list(tr.y)
                        return (f"Highest displayed {name} heat-map cell: "
                                f"{_fmt(z[hi])} {unit} at x={x[hi[1]]}, y={y[hi[0]]}. "
                                "This is the selected cell aggregation (sum, mean or percentile), "
                                "not an annual total or automatically a peak irradiance. "+context)
        return context
    if kind in ("duration","duration curve"):
        return (f"The sorted {name} duration curve contains {len(v):,} valid observations "
                f"(P05 {_fmt(v.quantile(.05))}, median {_fmt(v.median())}, "
                f"P95 {_fmt(v.quantile(.95))} {unit}). "
                "The curve loses chronology; zeros at night are physically meaningful for "
                "irradiation but the diffuse fraction is undefined when GHI is zero. "+context)
    if kind in ("histogram","box","violin","monthly boxplot","monthly violin plot"):
        return (f"The observed {name} distribution has median {_fmt(v.median())} {unit}, "
                f"P05 {_fmt(v.quantile(.05))} and P95 {_fmt(v.quantile(.95))} {unit}. "
                "For irradiation, nighttime zeros belong to the observed distribution. "+context)
    if kind in ("diurnal","typical daily profile"):
        if isinstance(v.index,pd.DatetimeIndex):
            pooled=v.groupby([v.index.month,v.index.hour]).mean()
            if not pooled.empty:
                month,hour=pooled.idxmax()
                return (f"The maximum pooled month–hour mean {name} is "
                        f"{_fmt(pooled.max())} {unit} (month {month}, {hour:02d}:00). "
                        "This identifies climatic timing rather than transmitted façade heat gain. "+context)
        return context
    if kind=="occurrence":
        basis=str(args[0]) if args else ("Days" if "days" in label else "Percentage" if "percentage" in label else "Hours")
        daily=str(args[1]) if len(args)>1 else ""
        return (f"Occurrence classes partition the selected {name} "
                f"by {basis.lower()}"+(f" using complete-day {daily.lower()} values" if basis=="Days" else "")+". "
                "Zero irradiation remains a physical class; missing or undefined diffuse "
                "fractions are excluded rather than assigned zero. "+context)
    if kind=="total":
        return (f"Selected-period total {name}: {v.sum()/1000:,.1f} kWh/m². "
                "This totals coincident valid intervals; it is not annualized or a "
                "solar-energy yield. "+context)
    return context


def solar_temperature_interpretation(
    df,*,threshold_w_m2=300.,hot_temperature_c=24.):
    """Hot+solar hours are a horizontal *weather screen*, not façade risk."""
    ghi=_number(df,GHI);temp=_number(df,T)
    dt=float(native_interval_hours(df))
    paired=ghi.ge(0)&ghi.notna()&temp.notna()
    if not paired.any():
        return "No coincident outdoor temperature and horizontal solar observations support a weather-exposure screen."
    hot=paired & temp.gt(float(hot_temperature_c)) & (ghi/dt).gt(float(threshold_w_m2))
    hours=float(hot.sum())*dt
    return (f"{_fmt_hours(hours)} observed hours have outdoor air >{hot_temperature_c:g} °C "
            f"and GHI-equivalent irradiance >{threshold_w_m2:g} W/m² "
            f"({int(paired.sum()):,} paired source intervals). "
            "This is horizontal-plane warm-weather coincidence, not predicted "
            "façade solar gain, indoor overheating or cooling demand. "
            "For design compare orientation-specific POA during the same hours.")


def facade_temperature_table(df,*,cold_c=18.,hot_c=26.,albedo=None):
    """Sum geometrically consistent POA for 8 azimuths by outdoor temperature.

    Uses the existing production solar transposition kernel unchanged and
    processes one orientation at a time, retaining only the small result table.
    """
    from .extended_visualization import hourly_capable
    from .monthly_radiation import surface_available
    from .facade_orientation import ORIENTATIONS
    from .runtime_module_guard import ensure_current_solar_runtime
    cold_c=float(cold_c);hot_c=float(hot_c)
    if not np.isfinite([cold_c,hot_c]).all() or cold_c>hot_c:
        raise ValueError("Cold threshold must not exceed hot threshold.")
    if not hourly_capable(df) or not surface_available(df):
        raise ValueError("Façade solar–temperature exposure requires complete subdaily GHI, DNI, DHI and solar position.")
    temp=_number(df,T)
    if not temp.notna().any():
        raise ValueError("Outdoor temperature data are unavailable.")
    solar=ensure_current_solar_runtime()
    rows=[]
    for name,short,az in ORIENTATIONS:
        poa=solar.surface_irradiance_series(df,90.,float(az),albedo=albedo)
        values=pd.to_numeric(poa,errors="coerce").where(lambda s:s.ge(0))
        valid=values.notna()
        t_valid=temp.notna()
        cold=float(values.loc[valid&t_valid&temp.lt(cold_c)].sum()/1000.)
        hot=float(values.loc[valid&t_valid&temp.gt(hot_c)].sum()/1000.)
        middle=float(values.loc[valid&t_valid&temp.ge(cold_c)&temp.le(hot_c)].sum()/1000.)
        unknown=float(values.loc[valid&~t_valid].sum()/1000.)
        total=float(values.sum(min_count=1)/1000.)
        rows.append(dict(orientation=name,direction=short,azimuth_deg=float(az),
            cold_kwh_m2=cold,intermediate_kwh_m2=middle,hot_kwh_m2=hot,
            unknown_temperature_kwh_m2=unknown,total_kwh_m2=total,
            hot_share_pct=(100*hot/total if total>0 else np.nan),
            valid_irradiation_intervals=int(valid.sum()),
            coincident_temperature_intervals=int((valid&t_valid).sum())))
    return pd.DataFrame(rows)


def facade_temperature_figure(table,*,cold_c=18.,hot_c=26.):
    fig=go.Figure()
    for field,name,color in (
        ("cold_kwh_m2",f"Outdoor T < {cold_c:g} °C","#527CB0"),
        ("intermediate_kwh_m2",f"{cold_c:g}–{hot_c:g} °C","#88A5A7"),
        ("hot_kwh_m2",f"Outdoor T > {hot_c:g} °C","#D89143"),
        ("unknown_temperature_kwh_m2","Unknown temperature","#B0B0B0"),
    ):
        if field=="unknown_temperature_kwh_m2" and not table[field].gt(0).any():continue
        fig.add_bar(x=table.direction,y=table[field],name=name,marker_color=color)
    fig.update_layout(template="plotly_white",barmode="stack",
        title="Façade irradiation × simultaneous outdoor air temperature",
        xaxis_title="Façade surface azimuth",
        yaxis_title="Unobstructed selected-period irradiation [kWh/m²]",
        legend=dict(orientation="h",y=-.22),height=560)
    return fig


def facade_temperature_interpretation(table,*,cold_c=18.,hot_c=26.):
    if table.empty:return "No complete solar–temperature exposure observations are available."
    totals=table.dropna(subset=["total_kwh_m2"])
    if totals.empty:return "No complete plane-of-array irradiation observations."
    peak=totals.loc[totals.total_kwh_m2.idxmax()]
    hot=totals.loc[totals.hot_kwh_m2.idxmax()]
    cold=totals.loc[totals.cold_kwh_m2.idxmax()]
    return (
        f"Highest selected-period unobstructed vertical exposure: {peak.orientation} "
        f"({peak.total_kwh_m2:,.1f} kWh/m²). Highest coincident irradiation when "
        f"outdoor T >{hot_c:g} °C: {hot.orientation} "
        f"({hot.hot_kwh_m2:,.1f} kWh/m²); "
        f"highest when T <{cold_c:g} °C: {cold.orientation} "
        f"({cold.cold_kwh_m2:,.1f} kWh/m²). "
        "These are weather-conditioned solar exposure priorities, not heating or cooling "
        "savings: glazing transmittance, room gains, façade shading and occupancy are unknown. "
        "Cold-period irradiation need not be useful without a building thermal balance; "
        "hot-period irradiation is not automatically an overheating event."
    )



def diffuse_fraction_daily_occurrence(df,edges,*,daily_stat="Mean"):
    """Daily daylight-only diffuse-fraction occurrence without inventing nights.

    GHI must be fully observed at source cadence over a real civil day. DHI
    and fraction must be admitted at EVERY strictly positive-GHI interval.
    Zero GHI defines an undefined ratio and is not a missing measurement.
    Daily Mean is the arithmetic mean of valid daylight interval ratios;
    it is not the irradiation-weighted daily DHI/GHI fraction.
    """
    from .temporal_filtering import CHRONOLOGICAL,time_basis
    from .extended_visualization import hourly_capable,occurrence_boundary_label,MONTHS
    if not hourly_capable(df) or GHI not in df or DHI not in df:
        raise ValueError("Daily diffuse-fraction occurrence requires subdaily GHI and DHI.")
    if daily_stat not in ("Mean","Minimum","Maximum"):
        raise ValueError("Unsupported daylight diffuse-fraction daily statistic.")
    edges=tuple(float(x) for x in edges)
    if (not edges or len(edges)>9 or not np.isfinite(edges).all()
            or edges[0]<=0 or edges[-1]>100
            or any(b<=a for a,b in zip(edges,edges[1:]))):
        raise ValueError("Diffuse fraction class boundaries must be positive, <=100 and strictly increasing.")
    ghi=_number(df,GHI).sort_index()
    dhi=_number(df,DHI).sort_index()
    if not isinstance(ghi.index,pd.DatetimeIndex) or not ghi.index.is_unique:
        raise ValueError("Unique dated source observations are required.")
    expected_days=ghi.resample("D").size().index
    dt=float(native_interval_hours(df))
    expected=pd.Series([
        (day+pd.DateOffset(days=1)-day).total_seconds()/3600./dt
        for day in expected_days],index=expected_days)
    complete_ghi=ghi.where(ghi.ge(0)).resample("D").count().eq(expected)
    sunlit=ghi.gt(0)
    valid_fraction=(100*dhi/ghi).where(sunlit & dhi.ge(0) & dhi.le(ghi))
    daylight_total=sunlit.resample("D").sum()
    daylight_valid=valid_fraction.resample("D").count()
    admitted=complete_ghi & daylight_total.gt(0) & daylight_valid.eq(daylight_total)
    grouped=valid_fraction.resample("D")
    if daily_stat=="Minimum":v=grouped.min()
    elif daily_stat=="Maximum":v=grouped.max()
    else:v=grouped.mean()
    v=v.where(admitted).dropna()
    text=[occurrence_boundary_label(x) for x in edges]
    labels=["No diffuse fraction (= 0)",f"0 < x < {text[0]}"]+[
        f"{lo} – < {hi}" for lo,hi in zip(text,text[1:])
    ]+[f"≥ {text[-1]}"]
    if v.empty:return pd.DataFrame(columns=labels,dtype=float)
    values=v.to_numpy()
    codes=np.where(values==0.,0,1+np.searchsorted(edges,values,side="right"))
    classes=pd.Series(pd.Categorical.from_codes(codes,categories=labels,ordered=True),index=v.index)
    periods=v.index.strftime("%Y-%m")
    table=pd.crosstab(periods,classes,dropna=False).reindex(columns=labels,fill_value=0)
    table.index=pd.Index(table.index,name="Period")
    if time_basis(df)!=CHRONOLOGICAL:
        table=table.groupby(table.index.str[-2:]).mean()
        table.index=[MONTHS[int(m)-1] for m in table.index]
    table.attrs.update({
        "occurrence_column":FRACTION,
        "occurrence_edges":tuple(edges),
        "daylight_ratio_definition":"DHI/GHI for GHI>0, daytime source measurements",
        "daily_statistic":daily_stat,
        "complete_real_days_required":True,
        "classified_days":len(v),
        "excluded_missing_days":int((~admitted).sum()),
    })
    return table
