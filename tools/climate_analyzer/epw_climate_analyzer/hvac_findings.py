"""R2.10: numerical HVAC/design-condition interpretation and figures.

Screening uses existing physical results; this module does not introduce a new
plant, building-load, or weather model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .aggregations import native_interval_hours
from .p3_comfort import T, W
from .p4_extremes import H, daily_stats
from .chart_theme import semantic_color_from_text

LOAD_COLUMNS=("Sensible heating","Sensible cooling",
              "Latent humidification","Latent dehumidification")
DESIGN_PERCENTAGES=(0.4,1.0,2.0,5.0)


def conditioning_summary(df: pd.DataFrame, ledger: pd.DataFrame) -> pd.Series:
    """Conditioning kWh under the specified source air-flow/target assumptions."""
    valid=ledger[list(LOAD_COLUMNS)].notna().all(axis=1)
    totals=ledger.loc[valid,list(LOAD_COLUMNS)].sum(axis=0).astype(float)
    sensible=float(totals["Sensible heating"]+totals["Sensible cooling"])
    latent=float(totals["Latent humidification"]+totals["Latent dehumidification"])
    dt=native_interval_hours(df)
    return pd.Series({**totals.to_dict(),
        "Valid hours":float(valid.sum())*dt,
        "Selected hours":len(df)*dt,
        "Sensible total":sensible,"Latent total":latent,
        "Combined conditioning indicator":sensible+latent,
        "Latent share [%]":100*latent/(sensible+latent) if sensible+latent else 0.,
        "Latent to sensible ratio":latent/sensible if sensible>0 else np.nan})


def conditioning_interpretation(df,ledger,*,airflow,heat,cool,w_low,w_high):
    summary=conditioning_summary(df,ledger)
    if not summary["Valid hours"]:
        return "The selected weather interval contains no complete outdoor-air conditioning observations."
    dt=native_interval_hours(df)
    monthly=ledger[list(LOAD_COLUMNS)].resample("MS").sum(min_count=1)
    components=[]
    for item in LOAD_COLUMNS:
        component=float(summary[item])
        months=monthly[item].dropna()
        if not months.empty and component>0:
            peak=months.idxmax().strftime("%B %Y")
            components.append(f"{item.lower()}: {component:,.0f} kWh (highest monthly contribution: {peak})")
        else:
            components.append(f"{item.lower()}: {component:,.0f} kWh")
    return (
        f"For {airflow:,.0f} m³/h constant outdoor-air flow, the selected {heat:g}–{cool:g} °C "
        f"and {w_low:g}–{w_high:g} g/kg conditioning bands yield "
        + "; ".join(components) + ". "
        + f"All four quantities have {summary['Valid hours']:,.0f} coincident observed hours "
          f"({100*summary['Valid hours']/summary['Selected hours']:.1f}% period coverage). "
        + f"Sensible contributions total {summary['Sensible total']:,.0f} kWh; "
          f"latent contributions total {summary['Latent total']:,.0f} kWh "
          f"({summary['Latent share [%]']:.1f}% of the summed reference indicator). "
        + ("Moisture treatment dominates the reference outdoor-air conditioning balance. "
           "Assess humidity control, recovery potential, supply-air strategy and peak coincident humidity."
           if summary["Latent total"]>summary["Sensible total"] else
           "Temperature conditioning dominates the reference outdoor-air balance. "
           "Assess ventilation heat recovery, supply-air temperatures and operation schedules.")
    )


def conditioning_monthly_figure(df,ledger,*,grouped=True,title="Monthly outdoor-air conditioning"):
    table=ledger[list(LOAD_COLUMNS)].resample("MS").sum(min_count=1)
    fig=go.Figure()
    for name in LOAD_COLUMNS:
        fig.add_bar(x=table.index,y=table[name],name=name,
                    marker_color=semantic_color_from_text(name))
    fig.update_layout(template="plotly_white",title=title,
        barmode="group" if grouped else "stack",xaxis_title="Month",
        yaxis_title="Reference conditioning energy [kWh]",
        legend=dict(orientation="h",x=0.,y=-.24),margin=dict(b=110))
    return fig


def economizer_stages(df,*,h_return=50.,t_min=5.,t_max=24.):
    """Separate temperature and enthalpy conditions using common observed hours."""
    t=pd.to_numeric(df.get(T,pd.Series(index=df.index,dtype=float)),errors="coerce")
    h=pd.to_numeric(df.get(H,pd.Series(index=df.index,dtype=float)),errors="coerce")
    valid=t.notna()&h.notna()
    temperature=valid&t.between(t_min,t_max)
    combined=temperature&h.lt(h_return)
    dt=native_interval_hours(df)
    return pd.DataFrame({
        "Criterion":["Coincident valid weather","Temperature range","Temperature and enthalpy"],
        "Hours":[valid.sum()*dt,temperature.sum()*dt,combined.sum()*dt],
    })


def economizer_interpretation(df,*,h_return,t_min=5.,t_max=24.):
    s=economizer_stages(df,h_return=h_return,t_min=t_min,t_max=t_max)
    valid,thermal,combined=s["Hours"].to_list()
    denom=valid if valid else 1.
    return (
        f"Outdoor temperature falls within {t_min:g}–{t_max:g} °C during "
        f"{thermal:,.0f} of {valid:,.0f} coincident valid weather hours. "
        f"An outdoor moist-air enthalpy below the selected {h_return:g} kJ/kg "
        f"return-air reference retains {combined:,.0f} hours "
        f"({100*combined/denom:.1f}% of coincident valid observations). "
        "These periods provide a weather-based starting point for air-side "
        "economizer and hybrid-system controls; refine with return-air temperature, "
        "humidity, ventilation rate and plant control assumptions."
    )


def economizer_stages_figure(table):
    fig=go.Figure(go.Bar(x=table["Criterion"],y=table["Hours"],
        text=table["Hours"],texttemplate="%{text:,.0f}",textposition="outside",
        marker_color="#0D9488"))
    fig.update_layout(template="plotly_white",title="Economizer screening by climatic criterion",
        xaxis_title="Criterion",yaxis_title="Observed hours",yaxis_rangemode="tozero")
    return fig


def design_quantile_figure(table,*,quantity,unit,upper):
    """Hourly empirical tail percentile versus quantile, retaining source sample."""
    a=table.sort_values("Nominal tail [%]")
    x=a["Nominal tail [%]"].to_numpy(dtype=float)
    y=a["Quantile"].to_numpy(dtype=float)
    fig=go.Figure(go.Scatter(x=x,y=y,mode="lines+markers",
        name="Empirical weather quantile",marker={"size":9,"color":"#2563EB"},
        customdata=a[["Actual inclusive tail [%]","Valid hours"]].to_numpy(),
        hovertemplate="Nominal tail: %{x:g}%<br>Quantile: %{y:.2f} "+unit+
        "<br>Actual inclusive tail: %{customdata[0]:.2f}%"
        "<br>Valid source duration: %{customdata[1]:,.0f} h<extra></extra>"))
    fig.update_layout(template="plotly_white",
        title=f"{'Upper' if upper else 'Lower'}-tail empirical {quantity} design screen",
        xaxis_title="Nominal tail fraction [%]",yaxis_title=f"{quantity} [{unit}]",
        margin=dict(b=85))
    fig.update_xaxes(tickmode="array",tickvals=x,ticktext=[f"{v:g}%" for v in x])
    return fig


def design_quantile_interpretation(table,*,quantity,unit,upper):
    if table.empty:return f"No valid {quantity} observations in the selected weather interval."
    a=table.sort_values("Nominal tail [%]")
    chosen=a.iloc[(a["Nominal tail [%]"]-1.).abs().argmin()]
    actual=float(chosen["Nominal tail [%]"])
    value=float(chosen["Quantile"])
    extent=float(chosen["Valid hours"])
    position="above" if upper else "below"
    stamp=pd.Timestamp(chosen["Closest timestamp"]).strftime("%d %b %Y %H:%M")
    return (
        f"The selected {actual:g}% {'upper' if upper else 'lower'} hourly tail "
        f"corresponds to {value:.2f} {unit} {quantity}; the equivalent sample "
        f"duration is {extent*actual/100.:.1f} hours among {extent:,.0f} valid observed hours. "
        f"With ties at the quantile boundary, the inclusive observed tail occupies "
        f"{float(chosen['Actual inclusive tail [%]']):.2f}% of valid hours "
        f"({extent*float(chosen['Actual inclusive tail [%]'])/100.:.0f} hours). "
        f"The closest observed weather state occurs on {stamp}. "
        f"Other columns in the table describe conditions at that observed time "
        f"and the independently averaged coincident states across the inclusive tail. "
        f"This {position}-threshold profile informs preliminary climatic "
        f"design-envelope and coincident-condition comparisons."
    )


def candidate_day_table(df,*,quantity,ranking,limit=15):
    """Rank only complete chronological days, with a traceable daily statistic."""
    d=daily_stats(df,quantity)
    stat={"Coldest days":"min","Hottest days":"max",
          "Highest enthalpy days":"max","Most humid days":"max"}[ranking]
    asc=ranking=="Coldest days"
    a=d.dropna(subset=[stat]).sort_values(stat,ascending=asc,kind="stable").head(limit)
    return a.rename(columns={"min":"Daily minimum","mean":"Daily mean",
                              "max":"Daily maximum","count":"Source records","sum":"Daily sum"})


def candidate_day_figure(table,*,quantity,unit,ranking):
    column="Daily minimum" if ranking=="Coldest days" else "Daily maximum"
    fig=go.Figure(go.Bar(x=[x.strftime("%d %b %Y") for x in table.index],
                         y=table[column],marker_color="#2563EB" if ranking=="Coldest days" else "#D97706"))
    fig.update_layout(template="plotly_white",title=f"{ranking} · complete daily observations",
        xaxis_title="Calendar day",yaxis_title=f"{quantity} [{unit}]",
        margin=dict(b=110))
    fig.update_xaxes(tickangle=-35)
    return fig


def candidate_day_interpretation(table,*,quantity,unit,ranking):
    if table.empty:return "No complete daily observations satisfy the selected data filter."
    col="Daily minimum" if ranking=="Coldest days" else "Daily maximum"
    extreme=table[col].iloc[0]
    date=table.index[0].strftime("%d %b %Y")
    return (
        f"The most extreme complete-day {ranking.lower()} candidate occurs on {date}, "
        f"with {quantity} {extreme:.2f} {unit}. "
        f"The chart ranks {len(table)} complete observed calendar days by their "
        f"{'daily minimum' if ranking=='Coldest days' else 'daily maximum'} and "
        "supports selection of weather sequences for further system analysis."
    )


def critical_window_interpretation(table,*,quantity,unit,upper,hours):
    if table.empty:return "The selected weather interval contains no complete critical windows."
    strongest=float(table["Mean"].iloc[0])
    last=float(table["Mean"].iloc[-1])
    stamp=pd.Timestamp(table["Start"].iloc[0]).strftime("%d %b %Y")
    return (
        f"The strongest {'upper' if upper else 'lower'} {hours:g}-hour "
        f"{quantity.lower()} sequence begins {stamp}, with mean {strongest:.2f} {unit}. "
        f"The {len(table)} selected nonoverlapping sequences extend to a "
        f"{last:.2f} {unit} mean at the selection boundary. "
        "This persistent-weather evidence supports evaluation of thermal "
        "storage, humidity-control endurance, temperature recovery and "
        "operation over multiday conditions."
    )
