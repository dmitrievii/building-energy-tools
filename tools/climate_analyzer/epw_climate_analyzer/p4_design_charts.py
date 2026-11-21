"""P4 engineering chart overlays shared by interactive and report paths."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from . import p4_extremes as p
from .chart_theme import metric_color
from .calendar_heatmap_axes import set_period_axis_scope,_day_positions,_bounded_positions

DESIGN_COLUMNS=(p.T,p.W,p.H)
DESIGN_PERCENTAGES=(.4,1.,2.,5.)

def supports_design_quantiles(df,column):
    return (column in DESIGN_COLUMNS and isinstance(df.index,pd.DatetimeIndex)
            and df.index.is_monotonic_increasing and not df.index.has_duplicates
            and str(df.attrs.get("canonical_native_resolution","")).lower()!="monthly"
            and 0<p.native_interval_hours(df)<=1.)

def add_design_quantiles(fig,df,column,unit,*,ascending=False,percentage=False):
    """Retain original rank coordinates; mark interpolated sample quantiles separately."""
    if not supports_design_quantiles(df,column):return fig
    table=p.design_conditions(df,column,DESIGN_PERCENTAGES,upper=not ascending)
    if table.empty:return fig
    pct=table["Nominal tail [%]"].to_numpy()
    hours=pct*table["Valid hours"].to_numpy()/100.
    x=pct if percentage else hours
    custom=np.column_stack([pct,hours,table["Actual inclusive tail [%]"].to_numpy()])
    fig.add_scatter(x=x,y=table.Quantile,mode="markers",name="Design quantiles",
                    marker=dict(symbol="diamond",size=8,color=metric_color(column),
                                line=dict(color="#FFFFFF",width=1.2)),
                    customdata=custom,
                    hovertemplate="Nominal tail: %{customdata[0]:g}%<br>Equivalent hours: %{customdata[1]:.1f}<br>Design quantile: %{y:.2f} "+unit+"<br>Actual inclusive tail: %{customdata[2]:.2f}%<extra></extra>")
    # Put values in a compact static note, not four overlapping point texts.
    text="Design quantiles: "+" · ".join(f"{q:g}%: {v:.2f} {unit}" for q,v in zip(pct,table.Quantile))
    fig.add_annotation(xref="paper",yref="paper",x=0,y=1.02,xanchor="left",yanchor="bottom",
                       text=text,showarrow=False,font=dict(size=10),align="left")
    fig.update_layout(margin=dict(t=max(100,int(fig.layout.margin.t or 0))),
                      legend=dict(orientation="h",x=0,y=-.22))
    return fig

DESIGN_NOTE=("Design markers are linearly interpolated empirical sample quantiles at nominal "
             "0.4%, 1%, 2% and 5% upper or lower tail fractions. They need not fall exactly on "
             "the discrete ranked curve. Equivalent hours use valid observed duration; "
             "these are not certified normative station design conditions.")

def critical_windows_figure(df,column,unit,*,hours=72,upper=True,limit=10):
    """Rank complete nonoverlapping windows; plot chronology and the actual ranking cutoff."""
    rolling=p.rolling_windows(df,column,hours)
    span=pd.Timedelta(hours=hours);step=p.cadence(df)
    ranked=rolling.dropna().sort_values(ascending=not upper,kind="stable")
    chosen=[]
    for end,value in ranked.items():
        if all(abs(end-r["End"])>=span for r in chosen):
            chosen.append({"Start":end-span+step,"End":end,"Mean":float(value)})
            if len(chosen)==limit:break
    table=pd.DataFrame(chosen,columns=["Start","End","Mean"])
    if table.empty:return None,table,"No complete consecutive windows."
    source=p.valid_values(df,column)
    idx=source.index
    # Insert one explicit break after each discontinuity, not a potentially huge reindex.
    gaps=[a+step for a,b in zip(idx[:-1],idx[1:]) if b>a+step]
    if gaps:
        extra=pd.Series(np.nan,index=pd.DatetimeIndex(gaps))
        source=pd.concat([source,extra]).sort_index()
        rolling=pd.concat([rolling,extra]).sort_index()
    color=metric_color(column)
    fig=go.Figure()
    fig.add_scatter(x=source.index,y=source,mode="lines",name="Observed quantity",
                    line=dict(color=color,width=1),opacity=.42,connectgaps=False)
    fig.add_scatter(x=rolling.index,y=rolling,mode="lines",name=f"{hours:g} h trailing mean",
                    line=dict(color=color,width=2),connectgaps=False)
    cutoff=float(table.Mean.iloc[-1])
    boundary="#B45309" if upper else "#2563EB"
    fig.add_scatter(x=[idx[0],idx[-1]],y=[cutoff,cutoff],mode="lines",
                    name=f"Selection cutoff: {cutoff:.2f} {unit}",
                    line=dict(color=boundary,width=1.7,dash="dot"))
    for row in chosen:
        fig.add_vrect(x0=row["Start"],x1=row["End"]+step,fillcolor=boundary,opacity=.10,
                      line_width=0,layer="below")
    fig.add_scatter(x=table.End,y=table.Mean,mode="markers",name="Selected windows",
                    marker=dict(color=boundary,size=7,symbol="diamond"),
                    customdata=table.Start.astype(str).to_numpy(),
                    hovertemplate="Start: %{customdata}<br>Last sample: %{x}<br>Mean: %{y:.2f} "+unit+"<extra></extra>")
    single=idx[0].year==idx[-1].year
    days=idx.normalize().unique()
    if single:
        ticks=_day_positions(list(days.dayofyear))
        anchor=pd.Timestamp(year=idx[0].year,month=1,day=1,tz=idx.tz)
        # Keep real timestamp coordinates, with canonical day-of-year labels.
        lookup={d.dayofyear:d for d in days}
        tickvals=[lookup.get(n,anchor+pd.DateOffset(days=n-1)) for n in ticks]
        ticktext=[str(n) for n in ticks]
    else:
        take=_bounded_positions(len(days),10)
        tickvals=[days[i] for i in take];ticktext=[days[i].strftime("%d %b %Y") for i in take]
    fig.update_layout(template="plotly_white",xaxis_title="Day of year" if single else "Date",
                      yaxis_title=unit,title=f"{'Upper' if upper else 'Lower'} critical {hours/24:g}-day windows",
                      legend=dict(orientation="h",x=0,y=-.24),margin=dict(b=100))
    fig.update_xaxes(type="date",tickmode="array",tickvals=tickvals,ticktext=ticktext,
                     tickangle=0 if single else -45,automargin=True)
    set_period_axis_scope(fig,idx)
    note=(f"{len(table)} nonoverlapping complete {hours:g}-hour windows selected by "
          f"{'highest' if upper else 'lowest'} mean; dotted line is the least extreme selected "
          f"window mean ({cutoff:.2f} {unit}), not a normative threshold. "
          "Shaded intervals show the actual selected windows; diamonds mark their trailing endpoints. "
          "Rank cutoff exceedance alone does not imply selection because overlapping windows are suppressed. "
          "Missing data break the lines and rolling windows. Real chronology is retained.")
    return fig,table,note
