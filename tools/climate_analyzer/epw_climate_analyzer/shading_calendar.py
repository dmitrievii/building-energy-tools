"""Site-specific shading calendars using canonical temporal aggregation.
No synthetic angular sampling; exact aperture geometry at source solar positions.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .aggregations import (HEATMAP_COMPARE_HOUR,heatmap_scope_statistics,
    temporal_heatmap_matrix,native_interval_hours)
from .solar_shading import _shading_components,shading_ledger,DEVICES,TOTAL_DEVICE
from .shading_temporal import AREA,ENERGY,REDUCTION,MONTHS
from .chart_theme import MONTH_COLORS
from .calendar_heatmap_axes import apply_calendar_heatmap_axes,set_period_axis_scope

OCCURRENCE="Shading occurrence"
VALUE="shading_aperture_pct"
EVENT="shading_occurrence_pct"
ENERGY_COLUMN="shading_intercepted_kwh_m2"
DENOM="shading_available_kwh_m2"
FRONT="shading_front_exposure"
KNOWN="shading_observation_known"
FIELD={AREA:VALUE,OCCURRENCE:EVENT,ENERGY:ENERGY_COLUMN,REDUCTION:ENERGY_COLUMN}
PALETTE=[[0,"#FFF1C7"],[.25,"#D1D5DB"],[.50,"#9CA3AF"],[.75,"#52525B"],[1,"#18181B"]]
NO_EXPOSURE="#B5C1D0"
MISSING="#F3F4F6"
DEFAULT_THRESHOLD=80.

def shading_frame(df,*,geometry,metric,device=TOTAL_DEVICE,threshold=DEFAULT_THRESHOLD):
    if device not in (*DEVICES,TOTAL_DEVICE):raise ValueError("Unknown shading device.")
    if not 0<threshold<=100:raise ValueError("Shading threshold must be in (0,100].")
    if metric not in FIELD:raise ValueError("Unknown shading metric.")
    az=pd.to_numeric(df["solar_azimuth_deg"],errors="coerce")
    el=90-pd.to_numeric(df["solar_apparent_zenith_deg"],errors="coerce")
    total,components,front=_shading_components(az,el,**geometry)
    fraction=total if device==TOTAL_DEVICE else components[:,DEVICES.index(device)]
    known=np.isfinite(total)
    frame=pd.DataFrame(index=df.index)
    frame.attrs.update(df.attrs)
    frame.attrs["canonical_native_interval_minutes"]=60*native_interval_hours(df)
    if "hour_of_day" in df:frame["hour_of_day"]=df["hour_of_day"]
    frame[KNOWN]=np.where(known,1.,np.nan)
    frame[FRONT]=np.where(known,front.astype(float),np.nan)
    frame[VALUE]=np.where(front,100*fraction,np.nan)
    frame[EVENT]=np.where(front,100.*(fraction>=threshold/100.),np.nan)
    if metric in (ENERGY,REDUCTION):
        ledger=shading_ledger(df,**geometry)
        direct=ledger["Unshaded direct"].to_numpy(dtype=float)
        lost=ledger["Intercepted direct" if device==TOTAL_DEVICE else device+" intercepted direct"].to_numpy(dtype=float)
        valid=known&np.isfinite(direct)&(direct>=0)&np.isfinite(lost)
        frame[ENERGY_COLUMN]=np.where(valid,lost/1000.,np.nan)
        frame[DENOM]=np.where(valid,direct/1000.,np.nan)
    return frame

def shading_statistics(df,metric,period,dimension):
    if metric==REDUCTION:return ("Energy-weighted reduction",)
    if metric==OCCURRENCE:return ("Mean",)
    return heatmap_scope_statistics(df,FIELD[metric],period,dimension)

def shading_matrix(frame,metric,period,dimension,statistic):
    def matrix(column,stat):
        return temporal_heatmap_matrix(frame,column,period,dimension,stat)
    front=matrix(FRONT,"Maximum")
    if front.empty:raise ValueError("No valid solar geometry in selected intervals.")
    if dimension==HEATMAP_COMPARE_HOUR:front=front.reindex(index=range(24))
    if metric==REDUCTION:
        numerator=matrix(ENERGY_COLUMN,"Total").reindex_like(front)
        denominator=matrix(DENOM,"Total").reindex_like(front)
        values=100*numerator.div(denominator.where(denominator>0))
    else:
        values=matrix(FIELD[metric],statistic).reindex_like(front)
    return values,front

def shading_calendar(frame,metric,period,dimension,statistic,*,title="",threshold=DEFAULT_THRESHOLD):
    from .charts import temporal_heatmap_chart
    values,front=shading_matrix(frame,metric,period,dimension,statistic)
    if metric==ENERGY:
        unit="kWh/m²"
        palette=[[0,"#FFFFFF"],[.25,"#FEE4A6"],[.6,"#F39B43"],[1,"#A83C16"]]
        upper=max(0.001,float(np.nanmax(values.to_numpy())) if values.notna().any().any() else 0.)
    else:unit="%";palette=PALETTE;upper=100.
    # Common geometry, tick formatting, chronological and calendar profiles.
    fig=temporal_heatmap_chart(frame,FIELD[metric],period,dimension,
          "Mean" if metric==REDUCTION else statistic,title or metric,unit,matrix_override=values)
    fig.update_layout(coloraxis=dict(colorscale=palette,cmin=0.,cmax=upper),
                      plot_bgcolor=MISSING,margin=dict(b=95))
    # Only known, non-incident sky states get the distinct no-exposure colour.
    # Energy zeros remain measured zeros, not masked out.
    no_exposure=np.zeros(values.shape,dtype=bool)
    if metric!=ENERGY:
        no_exposure=(front.eq(0)&values.isna()).to_numpy()
        fig.add_heatmap(x=values.columns,y=values.index,z=np.where(no_exposure,1.,np.nan),
            colorscale=[[0,NO_EXPOSURE],[1,NO_EXPOSURE]],zmin=0,zmax=1,showscale=False,
            hoverongaps=False,hovertemplate="No front-facing daylight exposure<extra></extra>")
    # Explicit missing cells survive user-selected background and report styling.
    missing=values.isna().to_numpy()&~no_exposure
    fig.add_heatmap(x=values.columns,y=values.index,z=np.where(missing,1.,np.nan),
        colorscale=[[0,MISSING],[1,MISSING]],zmin=0,zmax=1,showscale=False,
        hoverongaps=False,hovertemplate="Missing or undefined<extra></extra>")
    fig.add_annotation(xref="paper",yref="paper",x=0,y=-.25,xanchor="left",
        text=("Blue-grey: no direct exposure · Light grey: missing/undefined" if metric!=ENERGY else
              "White: zero intercepted energy · Light grey: missing"),showarrow=False,font=dict(size=11))
    set_period_axis_scope(fig,frame)
    return apply_calendar_heatmap_axes(fig,period=period)

def monthly_shading_profiles(frame,metric,months):
    if metric not in (AREA,OCCURRENCE):raise ValueError("Profiles require area or occurrence.")
    hours=pd.to_numeric(frame["hour_of_day"],errors="coerce") if "hour_of_day" in frame else frame.index.hour
    table=frame[FIELD[metric]].groupby([frame.index.month,hours]).mean().unstack(0).reindex(index=range(24),columns=list(months))
    fig=go.Figure()
    for m in months:
        fig.add_scatter(x=np.arange(24)+.5,y=table[m],name=MONTHS[m-1],
            mode="lines+markers",line=dict(color=MONTH_COLORS[m-1],width=2),
            marker=dict(size=4),connectgaps=False,
            customdata=[f"{h:02d}:00–{h+1:02d}:00" for h in range(24)],
            hovertemplate="%{fullData.name} · %{customdata}<br>%{y:.1f}%<extra></extra>")
    fig.update_layout(template="plotly_white",title=metric+" · monthly hourly profiles",
        xaxis_title="Hour of day",yaxis_title=metric+" [%]",
        legend=dict(orientation="h",x=0,y=-.22),margin=dict(b=85))
    fig.update_xaxes(range=[0,24],tickmode="array",tickvals=[0,6,12,18,24])
    fig.update_yaxes(range=[0,100],dtick=25)
    return fig,table

def shading_note(metric,threshold=DEFAULT_THRESHOLD):
    detail={
        AREA:"Geometrically shaded aperture [%] during front-facing daylight; independent of clouds and direct irradiance.",
        OCCURRENCE:f"Share of eligible duration with shaded aperture ≥ {threshold:g}%. The denominator is known front-facing daylight intervals; equal native intervals contribute equally. This is not the mean shaded area.",
        ENERGY:"Intercepted direct irradiation in kWh/m² per source interval, aggregated using the selected statistic.",
        REDUCTION:"Energy-weighted reduction: 100 × sum(intercepted direct irradiation) / sum(available unshaded direct irradiation). Zero denominator is undefined.",
    }[metric]
    return detail+" Actual source solar positions only; no hypothetical directions. Zero shading is distinct from no front-facing sun and missing data. Uses the active analysis clock and source sampling cadence. Diffuse and reflected shading are not modelled."
