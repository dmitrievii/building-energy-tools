"""Shared duration–intensity bubble representation of observed event tables."""
from __future__ import annotations
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .chart_theme import event_color

def severity_unit(quantity,duration_unit):
    match=re.search(r"\[([^]]+)\]",quantity)
    unit=match.group(1) if match else quantity
    if "precipitation" in quantity.lower() and duration_unit=="days":
        return "mm"  # sum of daily depths above/below a daily threshold
    if unit=="°C":unit="K"
    elif unit=="%":unit="percentage points"
    return unit+"·"+("d" if duration_unit=="days" else "h")

def bubble_figure(table,*,unit,threshold,above,quantity):
    if table.empty:raise ValueError("No qualifying events.")
    severity=table.excess.to_numpy(dtype=float)
    if not np.isfinite(severity).all() or np.any(severity<0):
        raise ValueError("Event severity must be finite and nonnegative.")
    su=severity_unit(quantity,unit)
    f=go.Figure()
    peak=float(severity.max())
    # Plotly area scaling: radius is proportional to sqrt(excess).
    # Threshold-equality events have zero severity and use a distinct open glyph.
    for keep,zero in ((severity>0,False),(severity==0,True)):
        if not keep.any():continue
        d=table.loc[keep]
        datefmt="%d.%m.%Y" if unit=="days" else "%d.%m.%Y at %H:%M"
        custom=[[a,b,float(e),float(m)] for a,b,e,m in zip(d.start.dt.strftime(datefmt),d.end.dt.strftime(datefmt),d.excess,d["mean"])]
        marker=dict(color=event_color(quantity,above),opacity=.65,line=dict(width=1,color=event_color(quantity,above)))
        if zero:marker.update(size=7,symbol="circle-open",opacity=1.)
        else:marker.update(size=d.excess.to_numpy(dtype=float),sizemode="area",sizeref=2*peak/34**2,sizemin=0)
        f.add_scatter(x=d.duration,y=d.peak,mode="markers",marker=marker,customdata=custom,
            name="Zero excess" if zero else "Area = cumulative threshold excess",
            hovertemplate="Start: %{customdata[0]}<br>Last observation: %{customdata[1]}<br>Duration: %{x:g} "+unit+
                "<br>"+("Maximum" if above else "Minimum")+": %{y:.2f}<br>Mean: %{customdata[3]:.2f}<br>Integrated excess: %{customdata[2]:.2f} "+su+"<extra></extra>")
    f.add_hline(y=threshold,line_dash="dash",line_color="#777777",line_width=1)
    f.update_layout(title="Event duration, peak and cumulative severity",template="plotly_white",
        xaxis_title=f"Duration [{unit}]",yaxis_title=quantity,legend=dict(orientation="h",y=-.2),
        meta={"layout_kind":"event_severity","severity_unit":su})
    return f

def bubble_note(table,*,unit,above,quantity):
    su=severity_unit(quantity,unit)
    worst=table.loc[table.excess.idxmax()]
    extreme=table.loc[table.peak.idxmax() if above else table.peak.idxmin()]
    date=worst.start.strftime("%d.%m.%Y")
    return (f"Bubble area represents cumulative threshold excess [{su}]; open symbols represent events exactly at the threshold. "
            f"The greatest cumulative severity is {worst.excess:,.2f} {su}, beginning {date}, over {worst.duration:g} {unit}. "
            f"The most extreme observed peak is {extreme.peak:.2f}. "
            "Duration, peak and cumulative severity distinguish short intense episodes from longer persistent conditions.")
