"""Canonical UTCI stress presentation; never modify the physical UTCI values."""
from __future__ import annotations
import numpy as np
import plotly.graph_objects as go
from .p3_comfort import EDGES,CLASSES,COLORS
from .calendar_heatmap_axes import apply_calendar_heatmap_axes
from .duration_axes import apply_duration_axis

PRACTICAL_RANGE=(EDGES[0],EDGES[-1])
# Preserve existing right-closed classification (p3_comfort.utci_class_hours).
RANGES=("≤ −40","−40 to −27","−27 to −13","−13 to 0","0 to 9","9 to 26",
        "26 to 32","32 to 38","38 to 46","> 46")
LABELS=tuple(f"{c} · {r}" for c,r in zip(CLASSES,RANGES))
STRESS_NOTE=("UTCI stress classes use fixed boundaries −40, −27, −13, 0, 9, 26, "
             "32, 38 and 46 °C (upper-inclusive intervals). The practical legend "
             "spans −40 to +46 °C with distinct open-ended extreme classes. "
             "Colours are categorical; exact UTCI remains available in hover/data. "
             "Missing or invalid states are uncoloured; no thermal stress is not proof of comfort.")

def stress_codes(values):
    a=np.asarray(values,dtype=float)
    return np.where(np.isfinite(a),np.searchsorted(EDGES,a,side="left"),np.nan)

def stress_colorscale():
    n=len(COLORS)
    return [
        stop for i,color in enumerate(COLORS) for stop in ([i/n,color],[(i+1)/n,color])]

def stress_heatmap(x,y,values,*,title="",x_label="",y_label=""):
    raw=np.asarray(values,dtype=float)
    codes=stress_codes(raw)
    classes=np.full(raw.shape,"",dtype=object)
    for i,c in enumerate(CLASSES):classes[codes==i]=c
    fig=go.Figure(go.Heatmap(x=x,y=y,z=codes,zmin=-.5,zmax=len(COLORS)-.5,
        colorscale=stress_colorscale(),zauto=False,zsmooth=False,
        customdata=raw,text=classes,hoverongaps=False,
        hovertemplate="%{x}<br>%{y}<br>UTCI: %{customdata:.2f} °C<br>%{text}<extra></extra>",
        colorbar=dict(title="UTCI stress [°C]",tickmode="array",
                      tickvals=list(range(len(COLORS))),ticktext=list(LABELS),
                      thickness=15,tickfont=dict(size=11),len=.98)))
    fig.update_layout(template="plotly_white",title=title,xaxis_title=x_label,yaxis_title=y_label,
                      meta=dict(utci_stress_palette="categorical-v1",utci_practical_range=list(PRACTICAL_RANGE)),
                      margin=dict(l=55,r=200,t=65,b=65))
    return apply_calendar_heatmap_axes(fig)

def add_stress_bands(fig,values):
    """Context for numeric UTCI lines; preserve actual extrema, never clip data."""
    raw=np.asarray(values,dtype=float)
    finite=raw[np.isfinite(raw)]
    if not finite.size:return fig
    lo,hi=float(finite.min()),float(finite.max())
    pad=max(1.,(hi-lo)*.04)
    lo,hi=lo-pad,hi+pad
    edges=(-np.inf,*EDGES,np.inf)
    for i,color in enumerate(COLORS):
        a,b=max(lo,edges[i]),min(hi,edges[i+1])
        if a<b:fig.add_hrect(y0=a,y1=b,fillcolor=color,opacity=.15,line_width=0,layer="below")
    fig.update_yaxes(range=[lo,hi])
    return fig

def duration_figure(values,dt,title):
    fig=go.Figure()
    endpoints=[]
    for c in values:
        v=values[c].dropna().sort_values(ascending=False)
        if v.empty:continue
        x=np.arange(1,len(v)+1)*dt
        codes=stress_codes(v)
        classes=[CLASSES[int(i)] for i in codes]
        fig.add_scatter(x=x,y=v,name=str(c),mode="lines",text=classes,
                        hovertemplate="%{x:.1f} h<br>UTCI %{y:.2f} °C<br>%{text}<extra></extra>")
        endpoints.append(float(x[-1]))
    fig.update_layout(template="plotly_white",title=title,xaxis_title="Duration [h]",yaxis_title="UTCI [°C]",
                      legend=dict(orientation="h",x=0,y=-.22))
    if endpoints:apply_duration_axis(fig,max(endpoints))
    return add_stress_bands(fig,values)
