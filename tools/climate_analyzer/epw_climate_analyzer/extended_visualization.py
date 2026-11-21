"""P1 reusable climate visualizations, preserving canonical source semantics."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .aggregations import native_interval_hours, duration_curve
from .climate_model import aggregation_semantics_for
from .chart_theme import metric_color, MONTH_COLORS, rgba
from .temporal_filtering import CHRONOLOGICAL, time_basis
from .daylight import daily_daylight_table

MONTHS = ("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")
T = "dry_bulb_temperature_c"
P = "liquid_precipitation_depth_mm"
NEW_TYPES = ("Typical daily profile", "Monthly occurrence classes")


def hourly_capable(df):
    return (isinstance(df.index,pd.DatetimeIndex)
            and str(df.attrs.get("canonical_native_resolution","")).lower()!="monthly"
            and native_interval_hours(df)<=1.0)


def compatible_types(df,column):
    if not hourly_capable(df) or aggregation_semantics_for(column)=="circular mean" or "direction" in column:
        return []
    return list(NEW_TYPES)


def _numeric(df,column):
    return pd.to_numeric(df[column],errors="coerce").replace([np.inf,-np.inf],np.nan)


def _hourly_values(df,column):
    """One complete real clock hour; sums extensive intervals, means states."""
    if not hourly_capable(df):
        raise ValueError("Hourly or finer data are required.")
    values=_numeric(df,column).sort_index()
    if not values.index.is_unique:
        raise ValueError("Duplicate timestamps are not admitted.")
    interval=native_interval_hours(df)
    count=int(round(1/interval))
    if not np.isclose(count*interval,1.):
        raise ValueError("Source cadence must divide one hour.")
    resampled=values.resample("h")
    semantics=aggregation_semantics_for(column)
    if semantics=="sum":
        hourly=resampled.sum(min_count=1)
    elif semantics=="min":
        hourly=resampled.min()
    elif semantics=="max":
        hourly=resampled.max()
    else:
        hourly=resampled.mean()
    return hourly.where(resampled.count()==count)


def diurnal_statistics(df,column,months=range(1,13)):
    """Representative hourly profile, distribution across actual observed hours."""
    if not compatible_types(df,column):
        raise ValueError("Diurnal profiles require subdaily non-directional data.")
    h=_hourly_values(df,column)
    grouped=h.groupby([h.index.month,h.index.hour])
    table=grouped.agg(mean="mean",median="median",min="min",max="max",count="count")
    table["p05"]=grouped.quantile(.05)
    table["p95"]=grouped.quantile(.95)
    table=table.reindex(pd.MultiIndex.from_product([list(months),range(24)],names=["month","hour"]))
    return table


def diurnal_panel_rows(fig):
    """Recognize current and legacy monthly small-multiple figures."""
    meta=fig.layout.meta
    title=str(fig.layout.title.text or "").lower()
    annotations=list(fig.layout.annotations or ())
    marked=isinstance(meta,dict) and meta.get("layout_kind")=="diurnal_small_multiples"
    if not marked and "typical daily profile" not in title:return 0
    if not annotations or not all(a.text in MONTHS for a in annotations):return 0
    return (len(annotations)+2)//3


def reflow_diurnal_panels(fig,*,font_size=None):
    """Fit physical label spacing to the actual canvas, without changing data."""
    rows=diurnal_panel_rows(fig)
    if not rows:return fig
    layout=fig.layout
    annotations=list(layout.annotations)
    size=float(font_size or layout.font.size or 12)
    height=float(layout.height or max(480,rows*285))
    width=float(layout.width or 1000)
    margin=layout.margin
    top=max(float(margin.t or 0),size*(3.6 if layout.title.text else 1.7)+8)
    bottom=max(size*3.2+8,45)
    left=max(size*4.1+10,58)
    right=max(size*.8+8,18)
    plot_h=max(1,height-top-bottom)
    plot_w=max(1,width-left-right)
    gap=min(.20 if rows<=3 else .16,max(.045,(size*1.5+6)/plot_h))
    col_gap=min(.12,max(.055,(size*2.5+8)/plot_w))
    row_h=(1-(rows-1)*gap)/rows
    col_w=(1-2*col_gap)/3
    n=len(annotations)
    unit=(layout.yaxis.title.text or (layout.meta.get("unit","") if isinstance(layout.meta,dict) else ""))
    meta=dict(layout.meta) if isinstance(layout.meta,dict) else {}
    meta.update(layout_kind="diurnal_small_multiples",unit=unit)
    fig.update_layout(meta=meta,showlegend=False,margin=dict(l=left,r=right,t=top,b=bottom))
    bottom_row_start=(rows-1)*3
    title_index=bottom_row_start+min(1,n-bottom_row_start-1)
    for i,a in enumerate(annotations):
        row,col=divmod(i,3)
        y1=min(1.,max(0.,1-row*(row_h+gap)));y0=max(0.,y1-row_h)
        x0=max(0.,col*(col_w+col_gap));x1=min(1.,x0+col_w)
        suffix=str(i+1) if i else ""
        xa=getattr(layout,"xaxis"+suffix);ya=getattr(layout,"yaxis"+suffix)
        lowest=i+3>=n
        xa.update(domain=[x0,x1],showticklabels=lowest,tickangle=0,
                  tickvals=[0,6,12,18,24] if plot_w*col_w>=size*13 else [0,12,24],
                  title_text="Hour" if i==title_index else "",automargin=False)
        ya.update(domain=[y0,y1],showticklabels=col==0,title_text=unit if col==0 else "",
                  nticks=3 if row_h*plot_h<size*5 else 4,automargin=False)
        a.update(x=(x0+x1)/2,y=y1,xref="paper",yref="paper",xanchor="center",yanchor="bottom",yshift=3,font=dict(size=size))
    # Existing selected months can leave unused axes in the last row.
    for i in range(n,rows*3):
        suffix=str(i+1)
        getattr(layout,"xaxis"+suffix).visible=False
        getattr(layout,"yaxis"+suffix).visible=False
    return fig


def diurnal_figure(table,column,unit,*,representation="Overlay",centre="mean",band="P05–P95"):
    months=list(dict.fromkeys(table.index.get_level_values("month")))
    small=representation=="Small multiples"
    rows=(len(months)+2)//3 if small else 1
    fig=make_subplots(rows=rows,cols=3,shared_yaxes=True,
        subplot_titles=[MONTHS[m-1] for m in months],vertical_spacing=min(.08,.25/max(1,rows))) if small else go.Figure()
    bounds={"Min–max":("min","max"),"P05–P95":("p05","p95")}.get(band)
    for i,m in enumerate(months):
        sub=table.loc[m]; color=MONTH_COLORS[m-1] if len(months)>1 else metric_color(column)
        kw={"row":i//3+1,"col":i%3+1} if small else {}
        if bounds:
            low,high=bounds
            fig.add_trace(go.Scatter(x=list(range(24)),y=sub[low],mode="lines",line=dict(width=0),showlegend=False,hoverinfo="skip",legendgroup=str(m)),**kw)
            fig.add_trace(go.Scatter(x=list(range(24)),y=sub[high],mode="lines",line=dict(width=0),fill="tonexty",fillcolor=rgba(color,.16),showlegend=False,hoverinfo="skip",legendgroup=str(m)),**kw)
        fig.add_trace(go.Scatter(x=list(range(24)),y=sub[centre],mode="lines+markers",name=MONTHS[m-1],
            line=dict(color=color,width=2.5),marker=dict(size=4),connectgaps=False,
            legendgroup=str(m),showlegend=not small,customdata=sub["count"],
            hovertemplate="%{x}:00<br>%{y:.3g} "+unit+"<br>Observed hours: %{customdata}<extra>%{fullData.name}</extra>"),**kw)
    fig.update_xaxes(range=[0,24],tickvals=[0,6,12,18,24],title_text="Hour")
    fig.update_yaxes(title_text=unit)
    if small:
        fig.update_yaxes(matches="y")
        fig.layout.yaxis.matches=None
    fig.update_layout(template="plotly_white",title="Typical daily profile",height=max(480,rows*285) if small else 540,
                      legend=dict(orientation="h",y=-.2,groupclick="togglegroup"))
    if small:
        fig.update_layout(meta={"layout_kind":"diurnal_small_multiples","unit":unit})
        reflow_diurnal_panels(fig)
    return fig


def _complete_daily(df,column,stat):
    values=_numeric(df,column).sort_index()
    if not values.index.is_unique:
        raise ValueError("Duplicate timestamps are not admitted.")
    freq=pd.Timedelta(hours=native_interval_hours(df))
    groups=values.resample("D")
    start=groups.size().index
    # Local civil days can contain 23 or 25 physical hours.
    expected=np.array([(x+pd.DateOffset(days=1)-x)/freq for x in start])
    if stat=="Amplitude":
        out=groups.max()-groups.min()
    elif stat=="Total":
        out=groups.sum(min_count=1)
    elif stat=="Minimum":
        out=groups.min()
    elif stat=="Maximum":
        out=groups.max()
    else:
        out=groups.mean()
    return out.where(groups.count().to_numpy()==expected)


def occurrence_table(df,column,edges,*,basis="Hours",daily_stat="Mean"):
    """Disjoint value classes; missing observations do not enter denominators."""
    if not compatible_types(df,column):
        raise ValueError("Occurrence classes require subdaily non-directional data.")
    edges=list(map(float,edges))
    if not edges or not np.isfinite(edges).all() or any(b<=a for a,b in zip(edges,edges[1:])):
        raise ValueError("Class boundaries must be finite, strictly increasing numbers.")
    daily=basis=="Days"
    v=_complete_daily(df,column,daily_stat) if daily else _numeric(df,column)
    v=v.dropna()
    limits=[-np.inf,*edges,np.inf]
    labels=[f"< {edges[0]:g}"]+[f"{a:g} – < {b:g}" for a,b in zip(edges,edges[1:])]+[f"≥ {edges[-1]:g}"]
    if v.empty:
        return pd.DataFrame(columns=labels,dtype=float)
    classes=pd.cut(v,limits,labels=labels,right=False)
    keys=v.index.strftime("%Y-%m")
    counts=pd.crosstab(keys,classes,dropna=False).reindex(columns=labels,fill_value=0)
    counts.index=pd.Index(counts.index,name="Period")
    if basis=="Percentage":
        counts=100.*counts.div(counts.sum(axis=1).replace(0,np.nan),axis=0)
    elif basis=="Hours":
        counts=counts*native_interval_hours(df)
    if time_basis(df)!=CHRONOLOGICAL:
        counts=counts.groupby(counts.index.str[-2:]).mean()
        counts.index=[MONTHS[int(m)-1] for m in counts.index]
    return counts


def occurrence_figure(table,unit,basis):
    fig=go.Figure()
    palette=["#2563EB","#0EA5E9","#059669","#EAB308","#EA580C","#DC2626"]
    for i,c in enumerate(table):
        fig.add_bar(x=table.index,y=table[c],name=c+" "+unit,marker_color=palette[min(len(palette)-1,int(i*len(palette)/max(1,len(table.columns))))])
    fig.update_layout(template="plotly_white",title="Monthly occurrence classes",
                      barmode="stack",xaxis_title="Period",yaxis_title="Observed "+basis.lower() if basis!="Percentage" else "Share of observed intervals [%]",legend=dict(orientation="h",y=-.2))
    if basis=="Percentage":
        fig.update_yaxes(range=[0,100])
    return fig


def probability_figure(df,column,unit,ascending=False):
    v=duration_curve(df,column,ascending)
    label="Cumulative frequency [%]" if ascending else "Exceedance frequency [%]"
    fig=go.Figure(go.Scatter(x=v["exceedance_fraction"]*100,y=v[column],mode="lines",
                               line=dict(color=metric_color(column))))
    fig.update_layout(template="plotly_white",title="Empirical frequency curve",xaxis_title=label,yaxis_title=unit)
    from .duration_axes import apply_duration_axis
    apply_duration_axis(fig,100.,percentage=True)
    return fig


def daily_amplitude(df):
    if not hourly_capable(df):
        raise ValueError("Daily temperature amplitude requires subdaily observations.")
    return _complete_daily(df,T,"Amplitude")


def climate_summary_table(df):
    """Paired complete calendar-month T means and precipitation totals.

    Average equivalent *complete* year-months with equal weight; never
    interpret missing precipitation as zero or accumulate multiple Januaries.
    Published monthly frames require canonical temperature and precipitation.
    """
    if T not in df or P not in df:
        return pd.DataFrame()
    v=pd.DataFrame({T:_numeric(df,T),P:_numeric(df,P).where(_numeric(df,P)>=0)})
    v=v.sort_index()
    if not v.index.is_unique:
        raise ValueError("Duplicate timestamps are not admitted.")
    if str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly":
        monthly=v.dropna()
        if monthly.index.to_period("M").duplicated().any():
            raise ValueError("Duplicate calendar months are not admitted.")
    elif hourly_capable(df):
        group=v.resample("MS")
        monthly=group.agg({T:"mean",P:"sum"})
        expected=np.asarray([(x+pd.offsets.MonthBegin(1)-x)/pd.Timedelta(hours=native_interval_hours(df)) for x in monthly.index])
        complete=group.count().eq(expected,axis=0).all(axis=1)
        monthly=monthly.loc[complete]
    else:
        return pd.DataFrame()
    if monthly.empty:
        return pd.DataFrame()
    grouped=monthly.groupby(monthly.index.month)
    out=grouped.mean().reindex(range(1,13))
    out["samples"]=grouped.size().reindex(range(1,13),fill_value=0)
    return out


def walter_precip_scale(p):
    a=np.asarray(p,dtype=float)
    return np.where(a<=100.,a/2.,50.+(a-100.)/20.)


def climate_summary_figure(table,style):
    temp=table[T].to_numpy(dtype=float);precip=table[P].to_numpy(dtype=float)
    if style=="Temperature–precipitation loop":
        fig=go.Figure(go.Scatter(x=np.r_[temp,temp[0]],y=np.r_[precip,precip[0]],
            mode="lines+markers+text",text=[*MONTHS,""],textposition="top center",connectgaps=False,
            meta={"annual_loop_closure_vertex":True},
            marker=dict(color=list(range(12))+[0],colorscale="Turbo",size=8),name="Monthly climate"))
        fig.update_layout(xaxis_title="Mean temperature [°C]",yaxis_title="Monthly precipitation [mm]")
    elif style in ("Walter–Lieth","Walter–Lieth diagram"):
        scaled=walter_precip_scale(precip)
        fig=go.Figure()
        for i,m in enumerate(MONTHS):
            if np.isfinite(temp[i]) and np.isfinite(precip[i]):
                dry=precip[i]<2*temp[i]
                fig.add_bar(x=[m],y=[abs(scaled[i]-temp[i])],base=[min(scaled[i],temp[i])],
                            width=.75,marker_color="#EAB308" if dry else "#93C5FD",opacity=.35,
                            showlegend=False,name="Dry" if dry else "Humid",hoverinfo="skip",
                            meta={"presentation_only_trace": True})
        fig.add_scatter(x=list(MONTHS),y=temp,name="Temperature",mode="lines+markers",line_color="#D55E00",connectgaps=False)
        fig.add_scatter(x=list(MONTHS),y=scaled,name="Precipitation",mode="lines+markers",line_color="#0072B2",
                        customdata=precip,meta={"export_y_from_customdata":True},
                        hovertemplate="%{x}<br>%{customdata:.1f} mm<extra></extra>",connectgaps=False)
        valid=np.r_[temp[np.isfinite(temp)],scaled[np.isfinite(scaled)],0.]
        low=min(0.,float(valid.min())-3);high=max(55.,float(valid.max())+3)
        ticks=[0,20,40,60,80,100]+list(range(300, int(max(300.,np.nanmax(precip) if np.isfinite(precip).any() else 300.))+200,200))
        fig.update_layout(xaxis_title="Month",yaxis=dict(title="Temperature [°C]",range=[low,high]),
                          yaxis2=dict(title="Precipitation [mm]",overlaying="y",side="right",range=[low,high],
                                      tickvals=walter_precip_scale(ticks),ticktext=ticks,showgrid=False))
        # A dummy invisible trace activates the explicitly coupled right axis.
        fig.add_scatter(x=[None],y=[None],yaxis="y2",showlegend=False,hoverinfo="skip",
                        meta={"presentation_only_trace":True})
        fig.add_hline(y=50,line_dash="dot",line_color="#94A3B8")
        fig.update_layout(meta={"fixed_physical_axis_relationship": True})
    else:
        fig=make_subplots(specs=[[{"secondary_y":True}]])
        fig.add_bar(x=list(MONTHS),y=precip,name="Precipitation",marker_color="#0072B2",secondary_y=True)
        fig.add_scatter(x=list(MONTHS),y=temp,name="Temperature",mode="lines+markers",line_color="#D55E00",secondary_y=False)
        fig.update_yaxes(title_text="Temperature [°C]",secondary_y=False)
        fig.update_yaxes(title_text="Precipitation [mm]",rangemode="tozero",secondary_y=True)
    fig.update_layout(template="plotly_white",title=style,legend=dict(orientation="h",y=-.2))
    return fig


def climate_summary_interpretation(table, style):
    """Data-driven climate reading; no inference of unobserved months."""
    observed=table[[T,P]].dropna()
    if observed.empty:
        return "No paired monthly values are available."
    name=lambda i: MONTHS[int(i)-1]
    cold=observed[T].idxmin();warm=observed[T].idxmax()
    wet=observed[P].idxmax();dry=observed[P].idxmin()
    arid=observed[observed[P]<2*observed[T]]
    wet_count=len(observed)-len(arid)
    parts=[
        f"The represented climate ranges from {observed.loc[cold,T]:.1f} °C in {name(cold)} to {observed.loc[warm,T]:.1f} °C in {name(warm)} (monthly mean temperature range {observed[T].max()-observed[T].min():.1f} K).",
        f"Precipitation is highest in {name(wet)} ({observed.loc[wet,P]:.1f} mm) and lowest in {name(dry)} ({observed.loc[dry,P]:.1f} mm).",
    ]
    if len(observed)==12:
        parts.append(f"The sum of the twelve representative monthly precipitation totals is {observed[P].sum():.0f} mm.")
    else:
        missing=[name(i) for i in range(1,13) if i not in observed.index]
        parts.append("Only "+str(len(observed))+" of 12 months are supported; missing months: "+", ".join(missing)+". No annual total or full-year dryness conclusion is inferred.")
    if len(arid):
        parts.append("Walter–Lieth climatic dryness (P < 2T) occurs during "+", ".join(name(i) for i in arid.index)+
                     f" ({len(arid)} of {len(observed)} represented months). During those months, planting and landscape water demand warrant particular assessment; rainfall harvesting and storage can help bridge dry periods.")
    else:
        parts.append(f"No Walter–Lieth dry month is identified among the {len(observed)} represented months. This does not exclude short dry spells or summertime water deficits.")
    if observed[T].min()<0:
        parts.append("At least one monthly mean is below freezing: freeze protection and winter drainage deserve attention. Monthly means do not establish frost-day counts.")
    if observed.loc[warm,T]>=20:
        parts.append("The warmest monthly mean supports assessment of summer shading and ventilation; overheating cannot be determined from monthly temperature alone.")
    if observed.loc[warm,P] < observed[P].median():
        parts.append("The warmest month is drier than the median represented month, suggesting a seasonal mismatch between warmth and precipitation availability.")
    else:
        parts.append("The warmest month has precipitation at or above the median represented month; warm-period moisture and rain protection should be considered alongside summer thermal design.")
    parts.append("These are climatic indicators, not a water balance or a building-load prediction. The Walter–Lieth dryness criterion is empirical.")
    return " ".join(parts)


def amplitude_figure(df,column,aggregation,label):
    """Observed within-period range; no synthetic intra-interval extrema."""
    from .temporal_filtering import CALENDAR_PROFILE, INTERANNUAL_OVERLAY, calendar_profile_slot, display_period_labels, chronological_season_start
    values=_numeric(df,column).sort_index()
    if aggregation=="Seasonal":
        grouped=values.groupby(chronological_season_start(values.index))
    else:
        rule={"Daily":"D","Weekly":"W","Monthly":"ME","Annual":"YE"}[aggregation]
        grouped=values.resample(rule)
    ranges=(grouped.max()-grouped.min()).where(grouped.count()>=2)
    fig=go.Figure()
    basis=time_basis(df)
    if basis==CALENDAR_PROFILE:
        slots=calendar_profile_slot(ranges.index,aggregation)
        ranges=ranges.groupby(slots,observed=True).mean()
        fig.add_scatter(x=display_period_labels(ranges.index,aggregation,basis),y=ranges,name=label,mode="lines+markers",line=dict(color=metric_color(column),width=2.5),marker=dict(size=5),connectgaps=False)
    elif basis==INTERANNUAL_OVERLAY:
        for year in sorted(set(ranges.index.year)):
            v=ranges.loc[ranges.index.year==year]
            slots=calendar_profile_slot(v.index,aggregation)
            fig.add_scatter(x=display_period_labels(slots,aggregation,basis),y=v,mode="lines+markers",connectgaps=False,name=str(year))
    else:
        fig.add_scatter(x=display_period_labels(ranges.index,aggregation,basis),y=ranges,name=label,mode="lines+markers",line=dict(color=metric_color(column),width=2.5),marker=dict(size=5),connectgaps=False)
    fig.update_layout(template="plotly_white",title=f"{aggregation} amplitude · {label}",xaxis_title="Period",yaxis_title="Amplitude [K]",legend=dict(orientation="h",y=-.2))
    fig.update_yaxes(rangemode="tozero")
    from .calendar_heatmap_axes import set_period_axis_scope,apply_monthly_axes
    set_period_axis_scope(fig,df,aggregation=aggregation)
    return apply_monthly_axes(fig)


def ground_depth_heatmap(profile):
    return go.Figure(go.Heatmap(x=list(profile.columns),y=profile.index,z=profile.to_numpy(dtype=float),
                       colorscale="RdBu_r",colorbar=dict(title="°C"),
                       hovertemplate="%{x}<br>Depth %{y:g} m<br>%{z:.2f} °C<extra></extra>")).update_layout(
                       template="plotly_white",title="Calculated ground temperature by depth and month",
                       xaxis_title="Month",yaxis=dict(title="Depth [m]",autorange="reversed"))


def daylight_envelope(index,latitude):
    table=daily_daylight_table(pd.DatetimeIndex(index),latitude)
    d=table["daylight_duration_h"]
    fig=go.Figure()
    fig.add_scatter(x=table.index,y=12-d/2,mode="lines",name="Sunrise",line_color="#D55E00")
    fig.add_scatter(x=table.index,y=12+d/2,mode="lines",name="Sunset",line_color="#0072B2",
                    fill="tonexty",fillcolor="rgba(245,158,11,.16)")
    fig.update_layout(template="plotly_white",title="Ideal sunrise–sunset envelope (local apparent solar time)",
                      xaxis_title="Date",yaxis=dict(title="Solar time [h]",range=[0,24],tickvals=[0,6,12,18,24]),
                      meta={"calendar_axis":"daily_daylight_envelope"})
    from .calendar_heatmap_axes import apply_monthly_axes
    return apply_monthly_axes(fig)


def sky_distribution(df,column="total_sky_cover_tenths"):
    # Three classes partition all valid observations on the 0–10 scale.
    clean=df.copy()
    clean[column]=_numeric(df,column).where(_numeric(df,column).between(0,10))
    return occurrence_table(clean,column,[np.nextafter(2.,np.inf),8],basis="Hours")


def sunshine_hour_heatmap(df):
    h=_hourly_values(df,"sunshine_duration_s")
    h=h.where(h.between(0.,3600.))
    averages=(h/3600.).groupby([h.index.month,h.index.hour]).mean().unstack().reindex(index=range(1,13),columns=range(24))
    return go.Figure(go.Heatmap(x=list(range(24)),y=list(MONTHS),z=averages.to_numpy(),
                      zmin=0,zmax=1,colorscale="YlOrRd",colorbar=dict(title="h/h"),
                      hovertemplate="%{y} %{x}:00<br>%{z:.2f} sunshine h/h<extra></extra>")).update_layout(
                      template="plotly_white",title="Mean measured sunshine duration by month and hour",
                      xaxis=dict(title="Hour",tickvals=[0,6,12,18,23]),yaxis=dict(title="Month",autorange="reversed"))
