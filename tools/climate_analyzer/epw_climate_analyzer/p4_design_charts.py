"""P4 engineering chart overlays shared by interactive and report paths."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from . import p4_extremes as p
from .chart_theme import metric_color
from .calendar_heatmap_axes import set_period_axis_scope,_day_positions,_bounded_positions

DESIGN_COLUMNS=(p.T,p.W,p.H)
# Duration-curve positions, not the separate normative-design screen defaults.
DESIGN_PERCENTAGES=(0.,.5,1.,2.,5.,95.,98.,99.,99.5,100.)
DURATION_QUANTILE_STATE="p4_duration_curve_percentages"

def parse_duration_percentages(raw):
    """Validate editable percent positions; blank deliberately disables markers."""
    if isinstance(raw,str):
        raw=raw.strip()
        if not raw:return ()
        parts=[part.strip().removesuffix("%").strip() for part in raw.replace(";",",").split(",")]
    else:
        parts=raw
    try:
        values=tuple(float(part) for part in parts)
    except (TypeError,ValueError):
        raise ValueError("Enter comma-separated percentages, for example 0, 0.4, 1, 95, 100.") from None
    if any(not np.isfinite(v) or not 0<=v<=100 for v in values):
        raise ValueError("Each percentage must be a finite number from 0 to 100.")
    return tuple(sorted(set(values)))

def duration_quantile_controls(st):
    key="p4_duration_curve_percentages_input"
    if key not in st.session_state:
        current=st.session_state.get(DURATION_QUANTILE_STATE,DESIGN_PERCENTAGES)
        st.session_state[key]=", ".join(f"{v:g}" for v in current)
    raw=st.text_input("Quantile positions [%]",key=key,
        help="Edit, add or delete comma-separated percentages. Empty = no markers. "
             "Positions are measured from the left of the sorted curve.")
    try:
        values=parse_duration_percentages(raw)
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.session_state[DURATION_QUANTILE_STATE]=list(values)
    if st.button("Reset quantile positions",key="p4_duration_quantile_reset",
                 on_click=_reset_duration_quantiles,args=(st.session_state,key)):
        pass
    return values

def _reset_duration_quantiles(state,key):
    state[key]=", ".join(f"{v:g}" for v in DESIGN_PERCENTAGES)
    state[DURATION_QUANTILE_STATE]=list(DESIGN_PERCENTAGES)

def supports_design_quantiles(df,column):
    # Same observation basis as the ordinary duration curve. No normative
    # station-design qualification is implied by these descriptive markers.
    return (column in df and pd.api.types.is_numeric_dtype(df[column])
            and np.isfinite(df[column].to_numpy(dtype=float,na_value=np.nan)).any())

def duration_quantile_table(df,column,percentages=DESIGN_PERCENTAGES,*,ascending=False):
    positions=parse_duration_percentages(percentages)
    columns=["Position [%]","Quantile","Equivalent hours","Actual inclusive tail [%]"]
    if not positions or not supports_design_quantiles(df,column):
        return pd.DataFrame(columns=columns)
    values=df[column].to_numpy(dtype=float,na_value=np.nan)
    values=values[np.isfinite(values)]
    fractions=np.asarray(positions)/100.
    quantiles=np.quantile(values,fractions if ascending else 1.-fractions,method="linear")
    hours=fractions*len(values)*p.native_interval_hours(df)
    actual=[100.*np.mean(values<=v if ascending else values>=v) for v in quantiles]
    return pd.DataFrame(dict(zip(columns,[positions,quantiles,hours,actual])))

def add_design_quantiles(fig,df,column,unit,*,ascending=False,percentage=False,percentages=DESIGN_PERCENTAGES):
    """Both sorted tails and custom positions, with leader-line callouts."""
    table=duration_quantile_table(df,column,percentages,ascending=ascending)
    if table.empty:return fig
    pct=table["Position [%]"].to_numpy(dtype=float)
    hours=table["Equivalent hours"].to_numpy(dtype=float)
    y=table.Quantile.to_numpy(dtype=float)
    x=pct if percentage else hours
    custom=np.column_stack([pct,hours,table["Actual inclusive tail [%]"].to_numpy()])
    color=metric_color(column)
    fig.add_scatter(x=x,y=y,mode="markers",name="Quantiles",showlegend=False,
                    marker=dict(symbol="diamond",size=7,color=color,line=dict(color="#FFFFFF",width=1.)),
                    customdata=custom,
                    hovertemplate="Curve position: %{customdata[0]:g}%<br>Equivalent hours: %{customdata[1]:.1f}<br>Quantile: %{y:.2f} "+unit+"<br>Actual inclusive tail: %{customdata[2]:.2f}%<extra></extra>")
    values=df[column].to_numpy(dtype=float,na_value=np.nan)
    values=values[np.isfinite(values)]
    total=100. if percentage else len(values)*p.native_interval_hours(df)
    if not np.isfinite(total) or total<=0:return fig
    lo,hi=float(values.min()),float(values.max())
    span=hi-lo or max(1.,abs(lo)*.1)
    # Respect constrained physical axes where possible, e.g. 0–100% RH.
    current=fig.layout.yaxis.range
    if current and all(v is not None and np.isfinite(v) for v in current):
        bottom,top=map(float,current)
    else:
        bottom,top=lo-.05*span,hi+.05*span
    if top<=bottom:bottom,top=lo-.5*span,hi+.5*span
    span=top-bottom
    for side,indices in (("left",np.flatnonzero(pct<=50)),("right",np.flatnonzero(pct>50))):
        if not len(indices):continue
        # Spread text vertically in small stacks; leaders preserve exact
        # point coordinates even if neighbouring extremes nearly coincide.
        order=sorted(indices,key=lambda i:(-y[i],i))
        n=len(order)
        spacing=min(.085,.8/max(n-1,1))
        preferred=float(np.mean(y[order]))
        centre=float(np.clip(preferred,bottom+(.10+(n-1)*spacing/2)*span,
                            top-(.10+(n-1)*spacing/2)*span))
        for j,i in enumerate(order):
            target=centre+((n-1)/2-j)*spacing*span
            label=f"{pct[i]:g}%: {y[i]:.2f} {unit}"
            fig.add_annotation(x=float(x[i]),y=float(y[i]),xref="x",yref="y",
                ax=total*(.17 if side=="left" else .83),ay=float(target),
                axref="x",ayref="y",xanchor="left" if side=="left" else "right",
                text=label,showarrow=True,arrowhead=0,arrowwidth=.8,arrowcolor="#64748B",
                bgcolor="rgba(255,255,255,0.88)",borderpad=2,
                font=dict(size=11,color="#334155"),align="left")
    # Increase the interactive height for long custom lists without changing
    # chart coordinates, duration ticks, or the numerical sample.
    max_stack=max(int(np.sum(pct<=50)),int(np.sum(pct>50)))
    if max_stack>5:
        fig.update_layout(height=max(int(fig.layout.height or 450),100+max_stack*31))
    return fig

DESIGN_NOTE=("Markers are linearly interpolated empirical sample quantiles at the selected "
             "positions on the sorted curve (descending: exceedance; ascending: cumulative "
             "frequency). 0% and 100% are the observed endpoints. Equivalent hours use valid "
             "observed duration. The plotted quantile positions define an empirical "
             "source-specific weather envelope; the inclusive observed tail is "
             "reported separately where repeated source values occur.")

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
          f"window mean ({cutoff:.2f} {unit}) and defines the observed empirical selection boundary. "
          "Shaded intervals identify the selected windows; diamonds mark their trailing endpoints. "
          "The ranking retains disjoint windows, selecting the strongest available mean "
          "then excluding all windows that overlap a prior selection. "
          "Missing observations separate the chronological source series and break rolling means.")
    return fig,table,note
