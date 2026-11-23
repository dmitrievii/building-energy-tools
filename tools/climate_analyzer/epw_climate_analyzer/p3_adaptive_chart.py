"""Shared chronological adaptive-comfort presentation for interactive and Atlas charts."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .calendar_heatmap_axes import set_period_axis_scope, apply_monthly_axes

CATEGORIES = ("I","II","III")
COLUMNS = ("Running mean","Neutral",*(c+" "+b for c in CATEGORIES for b in ("lower","upper")))

def selected_daily_bands(table, source):
    """Retain selected real dates, without pooling nonlinear comfort states."""
    days=pd.DatetimeIndex(source.index).normalize().unique().sort_values()
    return table.reindex(days)

def adaptive_figure(table):
    """Nested bands with a separate polygon per contiguous valid episode."""
    if table.empty:raise ValueError("No selected days.")
    table=table.sort_index()
    idx=pd.DatetimeIndex(table.index)
    # Explicit missing dates break both lines and polygons.
    dates=pd.date_range(idx.min(),idx.max(),freq="D")
    data=table.reindex(dates)
    single=len(set(dates.year))==1
    x=dates.dayofyear.tolist() if single else dates.strftime("%Y-%m-%d").tolist()
    day_text=dates.strftime("%d %b" if single else "%d %b %Y").tolist()
    fig=go.Figure()
    fig.add_scatter(x=x,y=data["Running mean"],customdata=day_text,mode="lines",
                    name="Outdoor running mean",line=dict(color="#D55E00",dash="dot",width=1.8),
                    connectgaps=False,legendrank=50,
                    hovertemplate="%{customdata}<br>Outdoor running mean: %{y:.1f} °C<extra></extra>")
    # Outer to inner: darker interior conveys the progressively narrow band.
    for cat,fill,line,rank in (
        ("III","rgba(148,163,184,0.24)","#94A3B8",30),
        ("II","rgba(96,165,250,0.25)","#60A5FA",20),
        ("I","rgba(5,150,105,0.25)","#059669",10),
    ):
        lo=data[cat+" lower"].to_numpy(dtype=float)
        hi=data[cat+" upper"].to_numpy(dtype=float)
        valid=np.flatnonzero(np.isfinite(lo)&np.isfinite(hi))
        segments=np.split(valid,np.flatnonzero(np.diff(valid)>1)+1) if len(valid) else []
        xx=[];yy=[]
        for seg in segments:
            forward=seg.tolist(); reverse=forward[::-1]
            xx.extend([x[i] for i in forward+reverse]+[x[forward[0]],None])
            yy.extend([lo[i] for i in forward]+[hi[i] for i in reverse]+[lo[forward[0]],None])
        fig.add_scatter(x=xx,y=yy,mode="lines",fill="toself",fillcolor=fill,
                        line=dict(color=line,width=1),name="Category "+cat,
                        connectgaps=False,hoverinfo="skip",legendrank=rank)
    custom=np.column_stack([np.asarray(day_text,dtype=object),data[list(COLUMNS[2:])].to_numpy()])
    fig.add_scatter(x=x,y=data.Neutral,customdata=custom,mode="lines+markers",
                    marker=dict(size=3),line=dict(color="#047857",width=2),
                    name="Neutral operative temperature",legendrank=40,connectgaps=False,
                    hovertemplate="%{customdata[0]}<br>Neutral: %{y:.1f} °C<br>I: %{customdata[1]:.1f}–%{customdata[2]:.1f} °C<br>II: %{customdata[3]:.1f}–%{customdata[4]:.1f} °C<br>III: %{customdata[5]:.1f}–%{customdata[6]:.1f} °C<extra></extra>")
    fig.update_layout(template="plotly_white",title="Adaptive comfort · Categories I–III",
                      xaxis_title="Day of year" if single else "Date",
                      yaxis_title="Temperature [°C]",hovermode="closest",
                      legend=dict(orientation="h",x=0,y=-.24,xanchor="left",yanchor="top"),
                      margin=dict(b=110))
    set_period_axis_scope(fig,idx,aggregation="Daily")
    apply_monthly_axes(fig)
    return fig

def adaptive_interpretation(table):
    rm=table["Running mean"];neutral=table["Neutral"]
    n=len(table);valid=int(neutral.notna().sum())
    low=int(rm.lt(10).sum());high=int(rm.gt(30).sum())
    unknown=int(rm.isna().sum())
    note=(f"Climate applicability: {valid}/{n} selected days ({100*valid/max(n,1):.1f}%). "
          f"Outdoor running mean below 10 °C: {low} days; above 30 °C: {high} days; "
          f"insufficient preceding observations: {unknown} days. ")
    if valid:
        note+=f"Neutral indoor operative temperature ranges from {neutral.min():.1f} to {neutral.max():.1f} °C. "
    note+=("Category I defines the narrowest indoor operative-temperature band, II an intermediate band and III the widest band. "
           "Visible bands indicate days with a valid seven-day outdoor running mean in the 10–30 °C applicability domain. "
           "EN 16798-1 adaptive screening uses seven preceding complete daily means and normalized alpha=0.8. "
           "The outdoor running mean determines the climate-dependent indoor operative-temperature bounds. "
           "An indoor assessment combines those bounds with operative temperature, occupant window control and relevant air-speed effects. "
           "Daily chronology is preserved for multi-year weather records.")
    return note
