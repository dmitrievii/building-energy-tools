"""P4 chart adapters. Real chronology; existing presentation/export boundary."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from . import p4_extremes as p
from .aggregations import native_interval_hours
from .p3_comfort import numeric
from .relationship_findings import VARS,correlation_chart,joint_chart

def _available(df):
    return {k:v for k,v in VARS.items() if numeric(df,v).notna().any()}

def _show_table(table,key):
    st.dataframe(table,use_container_width=True)
    st.download_button("Download results · CSV",table.to_csv(index=True).encode("utf-8"),key+".csv","text/csv",key="p4_csv_"+key)

def _bars(table,title,unit,render,note):
    fig=go.Figure()
    for c in table:fig.add_bar(x=table.index,y=table[c],name=c)
    fig.update_layout(template="plotly_white",title=title,barmode="group",yaxis_title=unit,xaxis_title="Period")
    render(fig,note)

def event_timeline_figure(table,series,*,unit,threshold,above=True,quantity="Temperature [°C]",step=None):
    """Render the actual trace and threshold even when no qualifying runs exist."""
    if unit=="days":
        delta=pd.DateOffset(days=1)
    else:
        if step is None or step<=pd.Timedelta(0):
            raise ValueError("Interval timeline requires a positive source cadence.")
        delta=step
    fig=go.Figure()
    # Preserve gaps even when the selected interval contains zero events.
    stamps=series.index
    breaks=[a+delta for a,b in zip(stamps[:-1],stamps[1:]) if b!=a+delta and a+delta<b]
    plotted=series
    if breaks:
        plotted=pd.concat([series,pd.Series(np.nan,index=pd.DatetimeIndex(breaks))]).sort_index()
    fig.add_scatter(x=plotted.index,y=plotted,mode="lines+markers" if len(series)==1 else "lines",
                    name=quantity,connectgaps=False,line=dict(color="#64748B"))
    # Use a visible trace rather than a layout-only line: the threshold also
    # participates in y-axis autorange when it lies outside the observed range.
    if len(stamps):
        fig.add_scatter(x=[stamps[0],stamps[-1] if len(stamps)>1 else stamps[0]+delta],
                        y=[threshold,threshold],mode="lines",name=f"Threshold: {threshold:g}",
                        line=dict(dash="dash",color="#333333"))
    shapes=[dict(type="rect",xref="x",yref="paper",y0=0,y1=1,
                 x0=r.start,x1=r.end+delta,line=dict(width=0),
                 fillcolor="#DD783B" if above else "#497DB7",opacity=.20,layer="below")
            for _,r in table.iterrows()]
    fig.update_layout(template="plotly_white",shapes=shapes,xaxis_title="Date",
                      yaxis_title=quantity,title="Extreme-event timeline")
    return fig

def event_interpretation(table,*,unit,extra_note=""):
    """One event narrative for the interactive and report representations."""
    count=len(table)
    summary=(f"{count:,} qualifying continuous events; longest duration {table.duration.max():g} {unit}. "
             if count else "The selected criterion identifies zero qualifying continuous events. ")
    method="Events group consecutive observations meeting the selected threshold. The event peak and integrated threshold excess describe severity; the duration and timing identify persistent climatic episodes."
    return (summary+method+" "+extra_note).strip()


def _events(table,render,*,key,unit,threshold,series=None,above=True,quantity="Temperature [°C]",step=None,extra_note=""):
    if table.empty:
        if series is not None and series.notna().any():
            st.info("No qualifying continuous events in the selected records. Observations and the selected threshold are shown below.")
        else:
            st.info("No valid observed states or qualifying events in the selected records.")
        if series is None or series.empty:return
    else:
        st.caption(f"{len(table)} events · longest {table.duration.max():g} {unit}.")
    choices=(["Event timeline"] if series is not None else [])
    if not table.empty:choices+=["Duration and intensity","Duration distribution"]
    chart_key="p4_event_chart_"+key
    if st.session_state.get(chart_key) not in choices:
        st.session_state[chart_key]=choices[0]
    style=st.selectbox("Chart type",choices,key=chart_key)
    fig=go.Figure()
    if style=="Event timeline":
        fig=event_timeline_figure(table,series,unit=unit,threshold=threshold,above=above,quantity=quantity,step=step)
    elif style=="Duration and intensity":
        fig.add_scatter(x=table.duration,y=table.peak,mode="markers",marker=dict(size=9,color="#D98235" if above else "#4477AA"),
                        text=table.start.astype(str),customdata=table.excess,hovertemplate="%{text}<br>Duration %{x:g}<br>Peak %{y:.2f}<br>Integrated excess %{customdata:.2f}<extra></extra>")
        fig.update_layout(title="Event duration and peak",xaxis_title="Duration ["+unit+"]",yaxis_title=quantity)
    else:
        d=table.duration.value_counts().sort_index()
        fig.add_bar(x=d.index,y=d,marker_color="#4477AA")
        fig.update_layout(title="Event duration distribution",xaxis_title="Duration ["+unit+"]",yaxis_title="Number of events")
    fig.update_layout(template="plotly_white")
    render(fig,event_interpretation(table,unit=unit,extra_note=extra_note))
    _show_table(table,key)

def temperature_panel(df,render):
    view=st.selectbox("Extreme-day analysis",["Heatwaves, cold spells and consecutive days","Frost days and tropical nights"],key="p4_temperature_view")
    try:
        if view=="Frost days and tropical nights":
            a=p.day_indicators(df)
            tab=a.resample("MS").sum(min_count=1)
            _bars(tab,"Frost days and tropical nights","Complete days",render,"Frost day: complete-day sampled Tmin < 0 °C. Tropical-night indicator uses daily Tmin ≥ 20 °C (ETCCDI TR uses >20 °C in some conventions; this is the explicitly displayed ≥ convention). Hourly sampled minima, not continuous daily extrema. Incomplete days excluded.")
            _show_table(tab,"temperature_days");return
        above=st.radio("Event type",["Heat","Cold"],horizontal=True,key="p4_temp_event_type")=="Heat"
        method=st.selectbox("Daily temperature statistic",["Maximum","Mean","Minimum"],index=0 if above else 2,key="p4_temp_stat_"+str(above))
        threshold=st.number_input("Threshold [°C]",value=30. if above else 0.,step=.5,key="p4_temp_thresh_"+str(above))
        minimum=st.number_input("Minimum consecutive days",min_value=1,max_value=60,value=3,step=1,key="p4_temp_days")
        d,a=p.temperature_events(df,threshold=threshold,above=above,minimum=minimum,stat={"Maximum":"max","Mean":"mean","Minimum":"min"}[method])
        st.caption(f"Complete days: {d['mean'].notna().sum()} of {len(d)} calendar days in the selected span.")
        _events(a,render,key="temperature",unit="days",threshold=threshold,series=d[{"Maximum":"max","Mean":"mean","Minimum":"min"}[method]],above=above,quantity=f"Daily {method.lower()} temperature [°C]")
    except ValueError as exc:st.warning(str(exc))

def persistence_panel(df,render,*,wind=False):
    options={"Wind speed [m/s]":p.V} if wind else {k:v for k,v in _available(df).items() if v in (p.RH,p.W)}
    if not options:st.info("No supported coincident observations.");return
    label=st.selectbox("Quantity",list(options),key="p4_persist_quantity_"+str(wind));column=options[label]
    above=st.radio("Condition",["At or above threshold","At or below threshold"],index=1 if wind else 0,horizontal=True,key="p4_persist_condition_"+str(wind))=="At or above threshold"
    default=.5 if wind else (80. if column==p.RH else 10.)
    threshold=st.number_input("Threshold",min_value=0.,value=default,step=.5,key="p4_persist_threshold_"+str(wind)+column)
    minimum=st.number_input("Minimum continuous duration [h]",min_value=.1,value=3.,step=.5,key="p4_persist_duration_"+str(wind))
    try:
        s=p.valid_values(df,column,True)
        a=p.events(s,threshold=threshold,above=above,minimum=minimum,step=p.cadence(df))
        extra=""
        if wind:
            from .wind_findings import wind_figure_interpretation
            extra=wind_figure_interpretation(df,None,"persistence",column=column,args=(threshold,above))
        else:
            from .humidity_findings import humidity_figure_interpretation
            extra=humidity_figure_interpretation(
                df,None,"persistence",column=column,args=(threshold,above,""))
        _events(a,render,key="wind" if wind else "humidity",unit="hours",threshold=threshold,series=s,above=above,quantity=label,step=p.cadence(df),extra_note=extra)
    except ValueError as exc:st.warning(str(exc))

def precipitation_panel(df,native,view,render):
    try:
        if view=="Wet and dry spells":
            threshold=st.number_input("Wet-day threshold [mm/day]",min_value=.1,value=1.,step=.1,key="p4_wet_threshold")
            minimum=st.number_input("Minimum consecutive days",min_value=1,value=2,step=1,key="p4_wet_duration")
            wet=st.radio("Event type",["Wet spells","Dry spells"],horizontal=True,key="p4_wet_type")=="Wet spells"
            d,w,a=p.wet_dry_events(df,threshold,minimum)
            from .precipitation_findings import wet_dry_interpretation
            interpretation=wet_dry_interpretation(df,wet=wet,threshold=threshold,minimum=minimum)
            _events(w if wet else a,render,key="rain",unit="days",threshold=threshold,
                    series=d["sum"],above=wet,quantity="Daily precipitation [mm]",
                    extra_note=interpretation)
        elif view=="Precipitation accumulation":
            choice=st.selectbox("Accumulation type",["Rolling precipitation totals","Cumulative observed blocks"],key="p4_rain_accum")
            if choice=="Rolling precipitation totals":
                h=st.selectbox("Duration [h]",[1,3,6,12,24,48,72,168],index=4,key="p4_rain_roll")
                s=p.rolling_windows(native if native is not None else df,p.P,h,total=True,nonnegative=True)
                from .precipitation_findings import rolling_interpretation
                note=rolling_interpretation(native if native is not None else df,h)
            else:
                s=p.cumulative_precipitation(native if native is not None else df)
                from .precipitation_findings import rainfall_summary
                note=rainfall_summary(native if native is not None else df)
                note+=" The curve displays accumulation within consecutive observed blocks."
            fig=go.Figure(go.Scatter(x=s.index,y=s,mode="lines",connectgaps=False))
            fig.update_layout(template="plotly_white",title=choice,yaxis_title="Precipitation [mm]",xaxis_title="Timestamp");render(fig,note)
        elif view=="Empirical IDF":
            if native is None:st.info("Requires native historical precipitation, not EPW/generated data.");return
            a=p.empirical_idf(native,historical_native=True)
            if a.empty:st.info("No durations match the native cadence.");return
            fig=go.Figure()
            for dur,g in a.groupby("duration_h"):
                g=g.sort_values("return_period_y")
                fig.add_scatter(x=g.return_period_y,y=g.intensity_mm_h,mode="lines+markers",name=f"{dur:g} h",customdata=g.year,hovertemplate="T %{x:.2f} y<br>I %{y:.2f} mm/h<br>Year %{customdata}<extra></extra>")
            fig.update_layout(template="plotly_white",title="Empirical rainfall intensity–duration–frequency",xaxis_type="log",xaxis_title="Empirical return period [years]",yaxis_title="Intensity [mm/h]")
            peak=a.loc[a.intensity_mm_h.idxmax()]
            render(fig,f"Empirical intensities are calculated from {a.year.nunique()} complete measured years "
                   f"using observed rolling accumulation windows at native cadence. "
                   f"The highest calculated intensity is {peak.intensity_mm_h:.1f} mm/h "
                   f"for a {peak.duration_h:g}-h window. Ranked annual maxima use "
                   "Weibull plotting positions (n+1)/rank, supporting comparison across observed storm durations.")
            _show_table(a,"empirical_idf")
        elif view=="Snow-cover calendar":
            data=native if native is not None else df
            s=p.daily_stats(data,p.SNOW,nonnegative=True)["max"]
            s=s.gt(0).astype(float).where(s.notna())
            from .precipitation_findings import snow_summary
            _calendar(s,render,"Snow-cover calendar",snow_summary(data))
        elif view=="Freeze–thaw days":
            mode=st.selectbox("Chart type",["Daily crossing indicators","Observed freeze–thaw sequences"],key="p4_freeze_view")
            threshold=st.number_input("Precipitation threshold [mm]",min_value=.1,value=1.,step=.1,key="p4_freeze_wet")
            if mode=="Daily crossing indicators":
                a=p.freeze_thaw_days(df,threshold)
                tab=a.resample("MS").sum(min_count=1)
                from .precipitation_findings import freeze_interpretation
                _bars(tab,"Air freeze–thaw exposure days","Complete days",render,
                      freeze_interpretation(df,wet_threshold=threshold))
                _show_table(tab,"freeze_thaw")
            else:
                a=p.freeze_thaw_cycles(df,wet_threshold=threshold)
                if a.empty:st.info("No complete warm–freeze–warm sequences.");return
                a=a.set_index("Thaw timestamp",drop=False)
                tab=pd.DataFrame({"Observed complete sequences":pd.Series(1.,index=a.index),
                                  "Antecedent wet sequences":a["Antecedent wet at freeze"]})
                tab=tab.resample("MS").sum(min_count=1)
                from .precipitation_findings import freeze_interpretation
                _bars(tab,"Observed air freeze–thaw sequences","Sequences",render,
                      freeze_interpretation(df,"freeze_cycles",wet_threshold=threshold))
                _show_table(a,"freeze_thaw_sequences")
    except ValueError as exc:st.warning(str(exc))

def _calendar(s,render,title,note):
    if s.dropna().empty:st.info("No complete daily observations.");return
    years=sorted(s.index.year.unique())
    y=st.selectbox("Year",years,index=len(years)-1,key="p4_calendar_year_"+title)
    sub=s.loc[s.index.year==y]
    start=pd.Timestamp(year=int(y),month=1,day=1,tz=s.index.tz)
    dates=pd.date_range(start,start+pd.DateOffset(years=1),freq="D",inclusive="left")
    v=sub.reindex(dates)
    z=np.full((7,54),np.nan);labels=np.full((7,54),"",dtype=object)
    for i,(d,val) in enumerate(v.items()):
        w=(i+start.weekday())//7;day=d.weekday();z[day,w]=val;labels[day,w]=d.strftime("%Y-%m-%d")
    fig=go.Figure(go.Heatmap(z=z,x=list(range(1,55)),y=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],customdata=labels,zmin=0,zmax=1,colorscale=[[0,"#FFFFFF"],[1,"#427CAD"]],showscale=False,xgap=2,ygap=2,hoverongaps=False,hovertemplate="%{customdata}<br>Snow cover %{z}<extra></extra>"))
    fig.add_heatmap(z=np.where(np.isfinite(z)| (labels==""),np.nan,1.),x=list(range(1,55)),y=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],customdata=labels,
                    zmin=0,zmax=1,colorscale=[[0,"#D1D5DB"],[1,"#D1D5DB"]],showscale=False,xgap=2,ygap=2,hoverongaps=False,
                    hovertemplate="%{customdata}<br>Unknown<extra></extra>")
    fig.update_layout(template="plotly_white",title=title,xaxis_title="Calendar week position",yaxis=dict(autorange="reversed"))
    render(fig,note+" White = no cover, blue = snow cover, gray = unknown.")

def hvac_panel(df,render):
    options={k:v for k,v in _available(df).items() if v in (p.T,p.W,p.H)}
    if not options:st.info("No design-condition variables available.");return
    label=st.selectbox("Governing quantity",list(options),key="p4_hvac_quantity")
    column=options[label]
    upper=st.radio("Tail",["Upper (cooling / moisture)","Lower (heating)"],horizontal=True,key="p4_hvac_tail")=="Upper (cooling / moisture)"
    view=st.selectbox("Analysis type",["Statistical design conditions","Critical multiday sequences"],key="p4_hvac_view")
    st.caption(
        "Empirical hourly weather quantiles and continuous critical-weather sequences "
        "derived from the selected source interval. Long-term station climatological "
        "design references can be compared with these source-specific results."
    )
    if view=="Critical multiday sequences":
        n=st.number_input("Continuous window [days]",1,30,3,1,key="p4_hvac_window")
        from .p4_design_charts import critical_windows_figure
        unit=label.rsplit("[",1)[-1].rstrip("]")
        try:fig,a,note=critical_windows_figure(df,column,unit,hours=24*n,upper=upper)
        except ValueError as exc:st.warning(str(exc));return
        if fig is None:st.info(note);return
        from .hvac_findings import critical_window_interpretation
        finding=critical_window_interpretation(
            a,quantity=label.split(" [")[0],unit=unit,upper=upper,hours=24*n,
        )
        render(fig,finding+" "+note)
        _show_table(a,"hvac_sequences");return
    a=p.design_conditions(df,column,[.4,1.,2.,.5,1.5,5.],upper=upper,coincident=[v for v in (p.T,p.W,p.H,p.RH,p.V) if v!=column and numeric(df,v).notna().any()])
    if a.empty:st.info("No valid observations.");return
    a=a.sort_values("Nominal tail [%]")
    from .hvac_findings import design_quantile_figure,design_quantile_interpretation
    unit=label.rsplit("[",1)[-1].rstrip("]")
    quantity=label.split(" [")[0]
    render(
        design_quantile_figure(a,quantity=quantity,unit=unit,upper=upper),
        design_quantile_interpretation(a,quantity=quantity,unit=unit,upper=upper),
    )
    _show_table(a,"hvac_design")
    st.caption(
        "Quantiles use linear sample interpolation. The nearest observed timestamp "
        "identifies one actual weather state; inclusive-tail means and paired-hour "
        "counts describe the accompanying variables across all qualifying hours."
    )

def multivariate_panel(df,render,*,density_only=False):
    options=_available(df)
    if len(options)<2:st.info("Two observable quantities are required.");return
    view="Joint probability density" if density_only else st.selectbox("Multivariate analysis",["Correlation matrix","Joint probability density","Paired scatter"],key="p4_multi_view")
    if view=="Correlation matrix":
        selected=st.multiselect("Quantities",list(options),default=list(options)[:min(6,len(options))],key="p4_corr_quantities")
        if len(selected)<2:st.info("Select at least two quantities.");return
        render(*correlation_chart(df,[options[x] for x in selected]))
    else:
        x=st.selectbox("X quantity",list(options),key="p4_density_x_"+str(density_only))
        others=[k for k in options if k!=x]
        y=st.selectbox("Y quantity",others,key="p4_density_y_"+str(density_only))
        style="scatter" if view=="Paired scatter" else "density"
        bins=st.slider("Bins per axis",10,60,25,5,key="p4_density_bins_"+str(density_only)) if style=="density" else 25
        try:render(*joint_chart(df,options[x],options[y],style=style,bins=bins))
        except ValueError as exc:st.info(str(exc))


def event_viewer(df,render):
    options=_available(df)
    if not options:st.info("No observable variables.");return
    label=st.selectbox("Event governing quantity",list(options),key="p4_viewer_quantity")
    s=p.valid_values(df,options[label])
    if s.dropna().empty:st.info("No valid values.");return
    above=st.radio("Event type",["High","Low"],horizontal=True,key="p4_viewer_direction")=="High"
    threshold=st.number_input("Threshold",value=float(s.quantile(.95 if above else .05)),key="p4_viewer_threshold_"+label+str(above))
    minimum=st.number_input("Minimum event duration [h]",min_value=.1,value=3.,step=.5,key="p4_viewer_min")
    try:a=p.events(s,threshold=threshold,above=above,minimum=minimum,step=p.cadence(df))
    except ValueError as exc:st.warning(str(exc));return
    if a.empty:st.info("No qualifying events.");return
    a=a.sort_values("excess",ascending=False).reset_index(drop=True)
    i=st.selectbox("Event",list(a.index),format_func=lambda k:f"{a.loc[k,'start']} · {a.loc[k,'duration']:g} h",key="p4_viewer_event")
    event=a.loc[i];padding=st.slider("Context before and after [h]",0,168,24,1,key="p4_viewer_pad")
    window=df.loc[(df.index>=event.start-pd.Timedelta(hours=padding))&(df.index<=event.end+pd.Timedelta(hours=padding))]
    chosen=st.multiselect("Coincident quantities",list(options),default=[label],key="p4_viewer_series")
    if not chosen:return
    from plotly.subplots import make_subplots
    fig=make_subplots(rows=len(chosen),cols=1,shared_xaxes=True)
    for row,name in enumerate(chosen,1):
        series=p.valid_values(window,options[name])
        # Insert missing cadence slots for honest visual discontinuities.
        series=series.reindex(pd.date_range(window.index[0],window.index[-1],freq=p.cadence(df)))
        fig.add_trace(go.Scatter(x=series.index,y=series,mode="lines",name=name,connectgaps=False),row=row,col=1)
        fig.update_yaxes(title_text=name,row=row,col=1)
        fig.add_vrect(x0=event.start,x1=event.end+p.cadence(df),fillcolor="#D98235",opacity=.14,line_width=0,row=row,col=1)
    fig.update_layout(template="plotly_white",title="Critical event · coincident source conditions",height=max(350,210*len(chosen)))
    render(fig,"All displayed quantities retain their coincident observed timestamps; missing slots are not interpolated. Event ranked by integrated excess relative to the selected threshold.")
    _show_table(a,"critical_events")
