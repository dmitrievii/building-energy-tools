"""Canonical reference charts shared by the explorer and both report modes."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .aggregations import native_interval_hours,period_total_series
from .temporal_filtering import display_period_labels,time_basis,CALENDAR_PROFILE
from .chart_theme import metric_color

T="dry_bulb_temperature_c"
G="global_horizontal_radiation_wh_m2"
D="diffuse_horizontal_radiation_wh_m2"
N="direct_normal_radiation_wh_m2"
P="liquid_precipitation_depth_mm"
R="precipitation_duration_min"
S="sunshine_duration_s"
SNOW="snow_depth_cm"
TOTAL_FIELDS={G:("Global horizontal irradiation","kWh/m²",.001),
 D:("Diffuse horizontal irradiation","kWh/m²",.001),
 N:("Direct normal irradiation","kWh/m²",.001),
 P:("Liquid precipitation","mm",1.),
 R:("Measured precipitation duration","h",1/60),
 S:("Measured sunshine duration","h",1/3600)}
PERIODS=("Monthly","Weekly","Daily","Seasonal","Annual")

def _numeric(df,c):
    return pd.to_numeric(df.get(c,pd.Series(np.nan,index=df.index)),errors="coerce").replace([np.inf,-np.inf],np.nan)

def _period(df,v,aggregation):
    x=period_total_series(v,df,aggregation)
    x.index=display_period_labels(x.index,aggregation,time_basis(df))
    return x

def _bar(x,title,unit,name,color):
    fig=go.Figure(go.Bar(x=x.index,y=x,name=name,marker_color=color))
    return fig.update_layout(template="plotly_white",title=title,xaxis_title="Period",yaxis_title=unit)

def extensive_total_figure(df,column,aggregation):
    label,unit,factor=TOTAL_FIELDS[column]
    v=_numeric(df,column);v=v.where(v.ge(0))
    if column in (R,S):
        # Source-duration records have a physical upper bound.
        v=v.where(v.le(native_interval_hours(df)*(60 if column==R else 3600)+1e-6))
    x=_period(df,v*factor,aggregation)
    if x.empty:raise ValueError("No valid observations for this accumulation.")
    f=_bar(x,f"{label} · {aggregation.lower()} total",unit,label,metric_color(column))
    peak=x.idxmax();low=x.idxmin()
    basis="Each calendar-profile bar is the mean of equivalent per-year period totals." if time_basis(df)==CALENDAR_PROFILE else "Each bar sums valid observed intervals within its period."
    note=(f"{label}: the plotted {aggregation.lower()} total ranges from {x.min():,.2f} {unit} "
          f"({low}) to {x.max():,.2f} {unit} ({peak}). {basis} ")
    if column in (G,D,N):
        note+=("Irradiation refers to the horizontal plane." if column!=N else "Direct normal irradiation refers to a plane perpendicular to the solar beam.")
        note+=" The period totals describe the incident solar resource for architectural exposure and solar-energy studies."
    elif column==P:
        from .precipitation_findings import rainfall_summary
        note+=rainfall_summary(df)
    elif column==R:
        from .precipitation_findings import measured_duration_summary
        note+=measured_duration_summary(df)
    else:
        from .sky_findings import sunshine_interpretation
        note+=sunshine_interpretation(df)
    return f,note

def snow_hours_figure(df,aggregation="Monthly"):
    from .precipitation_findings import snow_summary
    v=_numeric(df,SNOW);v=v.where(v.ge(0))
    x=_period(df,v.gt(0).astype(float).where(v.notna())*native_interval_hours(df),aggregation)
    if x.empty:raise ValueError("No valid snow-depth observations.")
    return (_bar(x,"Snow-cover duration","Observed snow-cover hours","Snow cover",metric_color(SNOW)),
        snow_summary(df)+f" Native snow observations use {native_interval_hours(df)*60:g}-minute intervals.")

def temperature_threshold_figure(df,aggregation,*,low=18.,high=26.,mode="Heating and cooling thresholds"):
    from .chart_theme import HEATING_COLOR,COOLING_COLOR
    v=_numeric(df,T);dt=native_interval_hours(df)
    if low>high:raise ValueError("Heating threshold must not exceed cooling threshold.")
    pairs=[(f"Below {low:g} °C",v.lt(low),HEATING_COLOR),(f"Above {high:g} °C",v.gt(high),COOLING_COLOR)]
    if mode=="Below heating threshold":pairs=pairs[:1]
    elif mode=="Above cooling threshold":pairs=pairs[1:]
    elif mode=="Frost hours (Tdry < 0 °C)":pairs=[("Below 0 °C",v.lt(0),HEATING_COLOR)]
    elif mode!="Heating and cooling thresholds":
        pairs=[("Above 20 °C · 20:00–06:59",v.gt(20)&((df.index.hour>=20)|(df.index.hour<=6)),COOLING_COLOR)]
    f=go.Figure();parts=[]
    for label,mask,color in pairs:
        x=_period(df,mask.astype(float).where(v.notna())*dt,aggregation)
        if x.empty:raise ValueError("No valid temperature observations.")
        f.add_bar(x=x.index,y=x,name=label,marker_color=color)
        parts.append(f"{label}: {float((mask&v.notna()).sum()*dt):,.1f} h")
    f.update_layout(template="plotly_white",title="Temperature threshold hours",yaxis_title="Hours",barmode="group",legend=dict(orientation="h",y=-.23))
    return f,("The selected outdoor-temperature thresholds identify "+ "; ".join(parts)+
        f" across {float(v.notna().sum()*dt):,.1f} valid observed hours. Bars describe their {aggregation.lower()} timing and support seasonal heating, cooling and envelope-exposure assessment.")

def eligibility_figure(df,name,period,*,view="total",reference_df=None,ledger=None,t_min=16.,t_max=26.,w_max=9.,hot=26.,cool=20.):
    from .p6_dashboard import design_ledgers
    from .charts import temporal_heatmap_chart
    from .passive_design_findings import night_flushing_interpretation
    col={"nv":"Natural ventilation","night":"Night flushing","shade":"Solar protection screening"}[name]
    if ledger is None:ledger=design_ledgers(df,reference_df=reference_df,t_min=t_min,t_max=t_max,w_max=w_max,hot=hot,cool=cool)[0]
    if col not in ledger or not ledger[col].notna().any():raise ValueError("No valid candidate hours.")
    v=ledger[col];dt=native_interval_hours(df);valid=float(v.notna().sum()*dt);eligible=float(v.sum())
    if view=="total":
        x=_period(df,v,period)
        f=_bar(x,col+" · "+period.lower(),"Hours",col,{"nv":"#21866B","night":"#527FA3","shade":"#D69A24"}[name])
    elif view=="map":
        data=pd.DataFrame({"screen":v/dt},index=df.index);data.attrs.update(df.attrs)
        f=temporal_heatmap_chart(data,"screen",period.lower(),"Hour of day","Mean",col+" · eligibility","0/1")
    else:raise ValueError("Unknown screening view.")
    note=f"{col}: {eligible:,.1f} of {valid:,.1f} valid candidate hours ({eligible/valid*100:.1f}%) satisfy the configured criterion. "
    if name=="nv":note+=f"Outdoor air is within {t_min:g}–{t_max:g} °C and humidity ratio is 0–{w_max:g} g/kg. The distribution identifies opportunities for outdoor-air ventilation."
    elif name=="night":note+=night_flushing_interpretation(df,v.gt(0),hot_day_c=hot,night_max_c=cool)
    else:note+="Outdoor air reaches 24 °C and coincident mean horizontal irradiance reaches 250 W/m². These hours guide the timing of external solar protection."
    if view=="map":note+=" Cell values represent the fraction of valid candidate observations satisfying the screen."
    else:note+=f" Bars show {period.lower()} eligible duration."
    return f,note

def passive_matrix_figure(df):
    from .decisions import passive_strategy_monthly
    from .passive_design_findings import monthly_strategy_matrix
    from .interpretations import hvac_interpretation
    table=passive_strategy_monthly(df)
    if table.empty:raise ValueError("No supported passive strategies.")
    return (monthly_strategy_matrix(table,"Monthly passive and HVAC strategy screens"),
        hvac_interpretation(df)+" Each matrix cell is the independently screened duration for one strategy. Coincident strategies remain visible in separate rows.")
