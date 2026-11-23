"""R2.7 quantified solar-shading findings for the website and atlas.

The physical solver remains solar_shading._shading_components and shading_ledger.
Interpretations use coincident available direct irradiation and actual source
solar positions. Architectural recommendations distinguish winter admission,
warm-period solar control, and the chosen aperture geometry.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .solar_shading import shaded_fraction, shading_ledger, DEVICES
from .aggregations import native_interval_hours

TEMPERATURE="dry_bulb_temperature_c"


def _valid(frame,column):
    if column not in frame:
        return pd.Series(np.nan,index=frame.index,dtype=float)
    return pd.to_numeric(frame[column],errors="coerce").replace([np.inf,-np.inf],np.nan)


def _f(value,decimals=1):
    return f"{float(value):,.{decimals}f}" if pd.notna(value) and np.isfinite(float(value)) else "unavailable"


def shading_ledger_interpretation(ledger,df,*,geometry=None,cold_c=18.,hot_c=26.):
    """Physically consistent totals and causal design priorities."""
    if ledger is None or ledger.empty:
        return "No solar geometry and radiation observations are available."
    total=_valid(ledger,"Unshaded total")
    direct=_valid(ledger,"Unshaded direct")
    intercepted=_valid(ledger,"Intercepted direct")
    known=total.notna()&direct.notna()&intercepted.notna()
    if not known.any():
        return "The selected period contains no complete coincident façade irradiation observations."
    total_kwh=float(total[known].sum()/1000.)
    direct_kwh=float(direct[known].sum()/1000.)
    saved_kwh=float(intercepted[known].sum()/1000.)
    remaining=total_kwh-saved_kwh
    reduction=100*saved_kwh/direct_kwh if direct_kwh>0 else np.nan
    facade=float((geometry or {}).get("facade",180.))
    note=(f"For the {facade:g}° façade, the selected period has {_f(total_kwh)} kWh/m² "
          f"unshaded plane irradiation, including {_f(direct_kwh)} kWh/m² incident "
          f"direct beam. The specified devices intercept {_f(saved_kwh)} kWh/m² "
          f"({_f(reduction)}% of available direct irradiation), leaving "
          f"{_f(remaining)} kWh/m² of plane irradiation. "
          f"The calculation uses {int(known.sum()):,} coincident source intervals. ")
    if isinstance(ledger.index,pd.DatetimeIndex):
        monthly=intercepted[known].resample("MS").sum(min_count=1)/1000.
        monthly=monthly.dropna()
        if not monthly.empty:
            m=monthly.idxmax()
            note+=(f"Maximum monthly intercepted direct irradiation occurs in "
                   f"{m.strftime('%B %Y')} ({_f(monthly.loc[m])} kWh/m²). ")
        temp=_valid(df,TEMPERATURE).reindex(ledger.index)
        paired=known&temp.notna()
        if paired.any():
            hot=paired&temp.gt(hot_c)
            cold=paired&temp.lt(cold_c)
            hot_energy=float(intercepted[hot].sum()/1000.)
            cold_energy=float(intercepted[cold].sum()/1000.)
            note+=(f"Of this intercepted beam, {_f(hot_energy)} kWh/m² coincides "
                   f"with outdoor T >{hot_c:g} °C and {_f(cold_energy)} kWh/m² "
                   f"with T <{cold_c:g} °C. ")
            if hot_energy>cold_energy:
                note+="The selected shading geometry concentrates interception during warm-weather exposure."
            elif cold_energy>hot_energy:
                note+="The intercepted cold-weather beam motivates checking seasonal solar admission when sizing fixed shading."
            else:
                note+="The thermal categories support comparing seasonal solar protection and admission."
    return note


def shading_mask_interpretation(geometry):
    """Accessible reference fractions at three known sun elevations."""
    az=float(geometry.get("facade",180.))
    fractions=np.asarray(shaded_fraction(
        np.full(3,az,dtype=float),np.array([20.,45.,70.]),**geometry),dtype=float)
    devices=[]
    if geometry.get("overhang",0.)>0:devices.append("overhang")
    if geometry.get("left_fin",0.)>0:devices.append("left fin")
    if geometry.get("right_fin",0.)>0:devices.append("right fin")
    features=", ".join(devices) if devices else "open aperture"
    return (f"Analytical geometric shading for the {az:g}° façade with {features}: "
            f"when the sun is directly opposite the façade, shaded aperture area "
            f"is {_f(100*fractions[0])}% at 20° solar elevation, "
            f"{_f(100*fractions[1])}% at 45° and "
            f"{_f(100*fractions[2])}% at 70°. "
            "The sun-path mask adds oblique solar directions, showing the "
            "contributions of side fins at morning and afternoon incidence.")


def shading_temporal_interpretation(frame,metric,*,device="All devices",threshold=80.):
    from .shading_calendar import VALUE,EVENT,ENERGY_COLUMN,DENOM
    from .shading_temporal import AREA,ENERGY,REDUCTION
    if frame is None or frame.empty:return "No shading observations are selected."
    if metric in (AREA,"Mean shaded aperture"):
        v=_valid(frame,VALUE).dropna()
        if v.empty:return "No front-facing solar positions occur in the selected period."
        return (f"At {len(v):,} front-facing solar observations, {device.lower()} "
                f"shades {_f(v.mean())}% of the aperture on average "
                f"(maximum {_f(v.max())}%). "
                "The month–hour distribution identifies the solar positions "
                "where device dimensions produce the greatest coverage.")
    if metric=="Shading occurrence":
        v=_valid(frame,EVENT).dropna()
        if v.empty:return "No eligible front-facing solar positions occur in the selection."
        hits=int(v.ge(100.).sum())
        return (f"{device} shades at least {threshold:g}% of the opening "
                f"at {hits:,} of {len(v):,} front-facing solar observations "
                f"({_f(100*hits/len(v))}% of eligible duration). "
                "The calendar identifies the periods when this coverage level is most consistent.")
    energy=_valid(frame,ENERGY_COLUMN)
    if metric==ENERGY:
        valid=energy.dropna()
        if valid.empty:return "No complete intercepted direct-beam irradiation observations occur."
        return (f"{device} intercepts {_f(valid.sum())} kWh/m² of direct irradiation "
                f"over {len(valid):,} valid source intervals. "
                "The calendar highlights the month–hour periods of strongest intercepted solar energy.")
    if metric==REDUCTION:
        denom=_valid(frame,DENOM)
        paired=energy.notna()&denom.gt(0)
        if not paired.any():return "The selected intervals contain zero available incident direct irradiation."
        reduction=100*energy[paired].sum()/denom[paired].sum()
        return (f"Across intervals with incident direct irradiation, "
                f"{device.lower()} achieves {_f(reduction)}% energy-weighted "
                "direct-beam interception. The month–hour cells compare "
                "intercepted and incident direct-beam irradiation for each period.")
    return "The selected shading metric summarizes the active solar and geometry observations."


def shading_monthly_interpretation(monthly,metric,*,year=None):
    from .shading_temporal import TOTAL_DEVICE, AREA,ENERGY,REDUCTION,UNITS
    s=pd.to_numeric(monthly[TOTAL_DEVICE],errors="coerce").dropna()
    if s.empty:return "No valid monthly shading observations are available."
    high=s.idxmax()
    def name(x):
        try:return pd.Timestamp(2026,int(x),1).strftime("%B")
        except (TypeError,ValueError):return str(x)
    yy=f" in {year}" if year is not None else ""
    note=(f"Monthly {metric.lower()}{yy} peaks in {name(high)} "
          f"({_f(s.max())} {UNITS.get(metric,'%')}); "
          f"the minimum observed monthly value is {_f(s.min())} "
          f"{UNITS.get(metric,'%')}. ")
    if metric==ENERGY:
        note+=f"Annual sum of monthly intercepted beam is {_f(s.sum())} kWh/m². "
    if metric==REDUCTION:
        note+="Month-level percentages are ratios of summed intercepted to incident direct energy."
    if metric==AREA:
        note+="Monthly area percentages average the front-facing solar geometry."
    return note+"Overhang and fin segments show their disjoint contributions to the chosen metric."


def orientation_shading_table(df,*,geometry,albedo=None,cold_c=18.,hot_c=26.):
    """Compare a configured device geometry across eight vertical facades."""
    from .facade_orientation import ORIENTATIONS
    if not np.isfinite([cold_c,hot_c]).all() or cold_c>hot_c:
        raise ValueError("Cold temperature threshold must not exceed hot threshold.")
    temp=_valid(df,TEMPERATURE)
    rows=[]
    for label,abbrev,az in ORIENTATIONS:
        g={**geometry,"facade":float(az)}
        ledger=shading_ledger(df,albedo=albedo,**g)
        total=_valid(ledger,"Unshaded total")
        direct=_valid(ledger,"Unshaded direct")
        intercepted=_valid(ledger,"Intercepted direct")
        known=total.notna()&direct.notna()&intercepted.notna()
        if not known.any():continue
        incident=float(direct[known].sum()/1000.)
        blocked=float(intercepted[known].sum()/1000.)
        temperature=temp.reindex(ledger.index)
        paired=known&temperature.notna()
        hot=paired&temperature.gt(hot_c)
        cold=paired&temperature.lt(cold_c)
        middle=paired&temperature.ge(cold_c)&temperature.le(hot_c)
        unknown=known&temperature.isna()
        row={"orientation":label,"direction":abbrev,"azimuth_deg":float(az),
             "unshaded_total_kwh_m2":float(total[known].sum()/1000.),
             "incident_direct_kwh_m2":incident,
             "intercepted_direct_kwh_m2":blocked,
             "direct_reduction_pct":100*blocked/incident if incident>0 else np.nan,
             "cold_intercepted_kwh_m2":float(intercepted[cold].sum()/1000.),
             "intermediate_intercepted_kwh_m2":float(intercepted[middle].sum()/1000.),
             "hot_intercepted_kwh_m2":float(intercepted[hot].sum()/1000.),
             "unknown_temperature_intercepted_kwh_m2":float(intercepted[unknown].sum()/1000.),
             "valid_intervals":int(known.sum())}
        rows.append(row)
    return pd.DataFrame(rows)


def orientation_shading_figure(table,*,cold_c=18.,hot_c=26.):
    fig=go.Figure()
    if table.empty:return fig
    classes=[
        ("cold_intercepted_kwh_m2",f"T <{cold_c:g} °C","#527CB0"),
        ("intermediate_intercepted_kwh_m2",f"T {cold_c:g}–{hot_c:g} °C","#91A7A9"),
        ("hot_intercepted_kwh_m2",f"T >{hot_c:g} °C","#D98C39"),
        ("unknown_temperature_intercepted_kwh_m2","Temperature unavailable","#BBBBBB"),
    ]
    for column,label,color in classes:
        if column.startswith("unknown") and not table[column].gt(0).any():continue
        fig.add_bar(x=table["direction"],y=table[column],name=label,
                    marker_color=color)
    fig.update_layout(template="plotly_white",barmode="stack",
        title="Device-intercepted direct irradiation by façade orientation and outdoor temperature",
        xaxis_title="Façade outward normal [meteorological azimuth °]",
        yaxis_title="Intercepted direct irradiation [kWh/m²]",
        legend=dict(orientation="h",y=-.22),height=540)
    return fig


def orientation_shading_interpretation(table,*,cold_c=18.,hot_c=26.):
    if table is None or table.empty:return "The selected period has no complete façade solar irradiation observations."
    high=table.loc[table.intercepted_direct_kwh_m2.idxmax()]
    by_hot=table.loc[table.hot_intercepted_kwh_m2.idxmax()]
    by_cold=table.loc[table.cold_intercepted_kwh_m2.idxmax()]
    return (f"With the same overhang and fin dimensions on all eight façades, "
            f"the {high.orientation} exposure has the greatest total direct-beam "
            f"interception ({_f(high.intercepted_direct_kwh_m2)} kWh/m²). "
            f"The largest warm-weather interception (T >{hot_c:g} °C) occurs "
            f"on the {by_hot.orientation} façade "
            f"({_f(by_hot.hot_intercepted_kwh_m2)} kWh/m²); "
            f"the largest cold-weather interception (T <{cold_c:g} °C) occurs "
            f"on {by_cold.orientation} "
            f"({_f(by_cold.cold_intercepted_kwh_m2)} kWh/m²). "
            "These orientation contrasts identify which façade deserves "
            "priority for summer shading and where winter solar admission "
            "should be evaluated before selecting fixed device depths.")
