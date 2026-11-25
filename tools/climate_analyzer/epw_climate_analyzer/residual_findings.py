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
    x=x.dropna()
    if x.empty:raise ValueError("No valid observations for this accumulation.")
    f=_bar(x,f"{label} · {aggregation.lower()} total",unit,label,metric_color(column))
    from .calendar_heatmap_axes import set_period_axis_scope,apply_monthly_axes
    set_period_axis_scope(f,df,aggregation=aggregation);apply_monthly_axes(f)
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
    f=_bar(x,"Snow-cover duration","Observed snow-cover hours","Snow cover",metric_color(SNOW))
    from .calendar_heatmap_axes import set_period_axis_scope,apply_monthly_axes
    set_period_axis_scope(f,df,aggregation=aggregation);apply_monthly_axes(f)
    return (f,snow_summary(df)+f" Native snow observations use {native_interval_hours(df)*60:g}-minute intervals.")

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
    f.update_layout(template="plotly_white",title="Temperature threshold hours",xaxis_title="Period",yaxis_title="Hours",barmode="group",legend=dict(orientation="h",y=-.23))
    from .calendar_heatmap_axes import set_period_axis_scope,apply_monthly_axes
    set_period_axis_scope(f,df,aggregation=aggregation);apply_monthly_axes(f)
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


def nv_special_figure(df,style,*,mask=None,t_min=16.,t_max=26.,w_max=9.,wind_min=None,wind_max=None):
    """Reference NV views with the same admitted mask and physical-hour accounting."""
    from .decisions import natural_ventilation_condition,rejection_reasons_for_nv
    from .p3_comfort import eligibility_mask,persistence,persistence_monthly
    from .p3_ui import nv_sensitivity_figure,persistence_interpretation
    from .p3_persistence_chart import persistence_figure
    from .directional_climate import (directional_table,directional_figure,directional_interpretation,
        directional_class_table,directional_class_figure,class_interpretation)
    if mask is None:
        mask=natural_ventilation_condition(df,t_min_c=t_min,t_max_c=t_max,d_max_g_kg=w_max,
                                         wind_min_m_s=wind_min,wind_max_m_s=wind_max)
    mask=eligibility_mask(df,mask,wind=wind_min is not None or wind_max is not None)
    dt=native_interval_hours(df)
    if style=="Persistence":
        table=persistence(df,mask);counts=persistence_monthly(table,2.)
        if counts.empty or not counts["Observed days"].notna().any():raise ValueError("No observed days with known suitability.")
        return persistence_figure(counts,"Day availability · at least 2 uninterrupted hours"),persistence_interpretation(2.)
    if style=="Daily duration":
        table=persistence(df,mask);v=table["Suitable hours [h]"].dropna().sort_values(ascending=False)
        if v.empty:raise ValueError("No observed days with known suitability.")
        f=go.Figure(go.Scatter(x=np.arange(1,len(v)+1),y=v,mode="lines",name="Suitable hours"))
        f.update_layout(template="plotly_white",title="Daily natural-ventilation suitable-hours duration curve",
                        xaxis_title="Ranked observed days",yaxis_title="Suitable hours/day")
        return f,(f"Across {len(v):,} days with known screening observations, daily suitable duration ranges from "
                  f"{v.min():.1f} to {v.max():.1f} h. The ranked curve shows how frequently days offer extended outdoor-air ventilation opportunities; partial days contribute their observed hours.")
    if style=="Temperature–wind suitability":
        return nv_sensitivity_figure(df,mask,temperature_limits=(t_min,t_max),
            wind_limits=(wind_min,wind_max) if wind_min is not None and wind_max is not None else None)
    if style=="Rejected reasons":
        reasons=rejection_reasons_for_nv(df,t_min,t_max,w_max,wind_min_m_s=wind_min,wind_max_m_s=wind_max)
        f=go.Figure(go.Bar(x=reasons["reason"],y=reasons["hours"],marker_color="#798D9D"))
        f.update_layout(template="plotly_white",title="Natural-ventilation rejected reasons",xaxis_title="Reason",yaxis_title="Hours")
        peak=reasons.iloc[0]
        return f,(f"The largest rejection duration is {peak['reason'].lower()} ({peak['hours']:,.1f} h). "
                  "The bars report physical observed hours outside each configured temperature, moisture or wind limit. Reasons can coincide within one interval.")
    if style=="Directional suitability":
        table=directional_table(df,radial="Eligible hours",colour="Natural ventilation suitability",nv_mask=mask)
        return directional_figure(table,"Eligible hours","Natural ventilation suitability",
            "Directionally classified strict-screen eligible hours"),directional_interpretation(table,"Eligible hours","Natural ventilation suitability")
    if style=="Wind during suitable hours":
        view=df.loc[mask.eq(1)].copy();view.attrs.update(df.attrs)
        if view.empty:raise ValueError("No suitable ventilation hours.")
        table=directional_class_table(view,quantity="Wind speed",radial="Hours",nv_mask=mask)
        if table.attrs["valid_hours"]<=0:raise ValueError("No valid coincident non-calm observations.")
        return directional_class_figure(table,"Mean wind during natural-ventilation-suitable hours"),class_interpretation(table)
    raise ValueError("Unknown ventilation chart.")
