"""P6 integrated overview: existing solar, degree-metric and comfort kernels."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from .p3_comfort import T,RH,W,V,GHI,numeric,complete,eligibility_mask,utci_frame,utci_class_hours,CLASSES,COLORS,ventilation_loads
from .p4_extremes import daily_stats
from .aggregations import native_interval_hours
from .decisions import natural_ventilation_condition,night_flushing_condition,shading_condition
from .degree_metrics import degree_metric_table
from .precipitation import aggregate_liquid_precipitation

P="liquid_precipitation_depth_mm"
def _period(df):
    return df.index.min().strftime("%d %b %Y")+" – "+df.index.max().strftime("%d %b %Y")
def _valid(df,c):
    s=numeric(df,c)
    if c in (GHI,P,V,W):s=s.where(s.ge(0))
    if c==RH:s=s.where(s.between(0,100))
    return s
def _fmt(v,unit,precision=1):
    return f"{v:,.{precision}f} {unit}" if np.isfinite(v) else "Unavailable"
def _cards(items):
    for offset in range(0,len(items),4):
        cols=st.columns(min(4,len(items)-offset))
        for col,(label,value,helptext) in zip(cols,items[offset:offset+4]):
            col.metric(label,value,help=helptext)
def _bar(s,title,unit,colour,render,note):
    fig=go.Figure(go.Bar(x=s.index,y=s,marker_color=colour))
    fig.update_layout(template="plotly_white",title=title,yaxis_title=unit,xaxis_title="Month")
    render(fig,note)
def _monthly(s,operation):
    res=s.resample("MS")
    return res.sum(min_count=1) if operation=="sum" else res.mean()

def select_overview(df,render,*,location,source,monthly=False,reference_df=None):
    options=["Climate summary","Annual climate dashboard"]+([] if monthly else ["Building design dashboard"])
    key="p6_overview_view"
    if st.session_state.get(key) not in options:st.session_state[key]=options[0]
    choice=st.selectbox("Analysis type",options,key=key)
    if choice=="Climate summary":return False
    # All KPIs use current sidebar selection; use a single actual year when
    # the active interval is multiyear, never multiply totals across years.
    years=sorted(df.index.year.unique())
    if len(years)>1:
        if st.session_state.get("p6_dashboard_year") not in years:st.session_state["p6_dashboard_year"]=years[-1]
        year=st.selectbox("Dashboard year",years,key="p6_dashboard_year")
        df=df.loc[df.index.year==year].copy()
    if df.empty:st.info("No data for dashboard.");return True
    from .p6_report import CONTEXT_KEY,set_context
    context=st.session_state.get(CONTEXT_KEY,{}).copy()
    extra={k:v for k,v in context.items() if k not in ("page","source","location","first timestamp","last timestamp","selected records","native interval minutes","time basis","filter")}
    set_context(st.session_state,page="Overview",source=source,location=location,df=df,extra={**extra,"dashboard":choice})
    st.header(choice)
    st.markdown("**"+str(location)+"**")
    st.caption(str(source)+" · "+_period(df)+f" · {len(df):,} selected records")
    st.caption("Active Data filter retained; totals are selected-period totals, not annualized. Missing values are excluded, not zero-filled.")
    if choice=="Annual climate dashboard":climate_dashboard(df,render,monthly=monthly)
    else:design_dashboard(df,render,reference_df=reference_df)
    return True

def climate_metrics(df):
    t=_valid(df,T);g=_valid(df,GHI);rain=_valid(df,P);wind=_valid(df,V)
    return {"temperature":t.mean(),"temperature_min":t.min(),"temperature_max":t.max(),
            "ghi":g.sum(min_count=1)/1000,"precipitation":rain.sum(min_count=1),
            "wind":wind.mean(),"rh":_valid(df,RH).mean(),"humidity_ratio":_valid(df,W).mean()}

def climate_dashboard(df,render,*,monthly=False):
    a=climate_metrics(df)
    _cards([("Mean air temperature",_fmt(a["temperature"],"°C"),"Mean of valid selected observations."),
            ("GHI total",_fmt(a["ghi"],"kWh/m²",0),"Horizontal irradiation, summed from source interval energy."),
            ("Mean wind speed",_fmt(a["wind"],"m/s"),"Valid speed observations."),
            ("Precipitation total",_fmt(a["precipitation"],"mm",0),"Valid selected depth records."),
            ("Minimum / maximum sampled temperature",_fmt(a["temperature_min"],"°C")+" / "+_fmt(a["temperature_max"],"°C"),"Sample extrema, not continuous extremes."),
            ("Mean relative humidity",_fmt(a["rh"],"%"),"Valid selected relative humidity."),
            ("Mean humidity ratio",_fmt(a["humidity_ratio"],"g/kg"),"Dry-air mass basis.")])
    t=_valid(df,T)
    if t.notna().any():
        agg=t.resample("MS").agg(["min","mean","max"])
        fig=go.Figure()
        if not monthly:
            fig.add_scatter(x=agg.index,y=agg["min"],name="Sample minimum",line=dict(color="#C48F67",width=1),connectgaps=False)
            fig.add_scatter(x=agg.index,y=agg["max"],name="Sample maximum",line=dict(color="#C48F67",width=1),fill="tonexty",fillcolor="rgba(196,143,103,.19)",connectgaps=False)
        fig.add_scatter(x=agg.index,y=agg["mean"],name="Mean",line=dict(color="#B96628",width=2.7),connectgaps=False)
        fig.update_layout(template="plotly_white",title="Monthly temperature profile",yaxis_title="Temperature [°C]",xaxis_title="Month")
        valid=agg["mean"].dropna()
        note=f"Warmest represented month: {valid.idxmax():%B} ({valid.max():.1f} °C); coolest: {valid.idxmin():%B} ({valid.min():.1f} °C)."
        render(fig,note+" Seasonal temperature contrast informs heating, summer protection and ventilation design. The range is sampled, not a normative design extreme.")
    rain=_valid(df,P)
    if rain.notna().any():
        agg=_monthly(rain,"sum")
        peak=agg.idxmax()
        _bar(agg,"Monthly precipitation","Depth [mm]","#5488B6",render,
             f"Highest observed monthly total: {peak:%B} ({agg.max():.1f} mm). Selected valid depths only; incomplete months may underestimate rainfall.")
    rh=_valid(df,RH);w=_valid(df,W)
    if rh.notna().any() or w.notna().any():
        from plotly.subplots import make_subplots
        fig=make_subplots(rows=1,cols=1,specs=[[{"secondary_y":True}]])
        if rh.notna().any():
            x=_monthly(rh,"mean");fig.add_scatter(x=x.index,y=x,name="Relative humidity",line=dict(color="#5488B6"),secondary_y=False)
        if w.notna().any():
            x=_monthly(w,"mean");fig.add_scatter(x=x.index,y=x,name="Humidity ratio",line=dict(color="#438B84"),secondary_y=True)
        fig.update_yaxes(title_text="Relative humidity [%]",secondary_y=False)
        fig.update_yaxes(title_text="Humidity ratio [g/kg]",secondary_y=True)
        fig.update_layout(template="plotly_white",title="Seasonal outdoor moisture")
        render(fig,"Relative humidity and absolute water content on a dry-air mass basis are distinct. High humidity ratio indicates a potential latent ventilation load; indoor condensation requires separate surface-temperature assessment.")
    ghi=_valid(df,GHI)
    if ghi.notna().any():
        _bar(_monthly(ghi,"sum")/1000,"Monthly horizontal solar irradiation","kWh/m²","#E0AE44",render,
             "The observed seasonal solar resource indicates periods where solar gains, photovoltaics and solar protection merit investigation.")
    if not monthly and complete(df,V,"wind_direction_deg"):
        from .directional_climate import directional_class_table,directional_class_figure,class_interpretation
        table=directional_class_table(df,radial="Percentage",quantity="Wind speed")
        if table.attrs.get("valid_hours",0)>0:
            render(directional_class_figure(table,"Wind distribution"),class_interpretation(table))
    if not monthly and complete(df,GHI,"diffuse_horizontal_radiation_wh_m2","direct_normal_radiation_wh_m2","solar_apparent_zenith_deg","solar_azimuth_deg"):
        from .facade_orientation import orientation_period_components,orientation_components_chart,TOTAL
        try:
            data,flat=orientation_period_components(df,tilt_deg=90.)
            if data[TOTAL].notna().any():
                fig=orientation_components_chart(data,flat,tilt_deg=90.,style="Bar chart",selected=())
                highest=data.loc[data[TOTAL].idxmax()]
                render(fig,f"Highest selected-period vertical POA: {highest['orientation']} ({highest[TOTAL]:.0f} kWh/m²). Unobstructed isotropic transposition, default ground-albedo model. Shading and glazing thermal effects require separate analysis.")
        except (ValueError,KeyError) as exc:st.caption("Façade irradiation unavailable: "+str(exc))
    coverage=pd.DataFrame({"Variable":[T,RH,W,V,GHI,P],"Valid records":[int(_valid(df,c).notna().sum()) for c in (T,RH,W,V,GHI,P)]})
    coverage["Selected records"]=len(df)
    with st.expander("Variable coverage"):st.dataframe(coverage,hide_index=True,use_container_width=True)

def design_ledgers(df,*,reference_df=None,t_min=16.,t_max=26.,w_max=9.,hot=26.,cool=20.,heat_i=20.,heat_l=12.,cool_i=26.,cool_l=26.):
    dt=native_interval_hours(df)
    s=_valid(df,T);ledger=pd.DataFrame(index=df.index)
    if complete(df,T,W):
        mask=natural_ventilation_condition(df,t_min_c=t_min,t_max_c=t_max,d_max_g_kg=w_max)
        ledger["Natural ventilation"]=eligibility_mask(df,mask)*dt
    if s.notna().any():
        # Full unfiltered reference day history, no future-day lookup.
        history=reference_df if reference_df is not None else df
        history=history.copy()
        if "hour_of_day" not in history:history["hour_of_day"]=history.index.hour
        try:
            d=daily_stats(history,T)
            night=night_flushing_condition(history,day_hot_threshold_c=hot,night_max_c=cool)
            days=df.index.normalize()
            anchors=days.where(df.index.hour>6,days-pd.DateOffset(days=1))
            known=d["max"].reindex(anchors).notna().to_numpy()
            night_clock=(df.index.hour>=22)|(df.index.hour<=6)
            # denominator is known nighttime slots only
            ledger["Night flushing"]=night.reindex(df.index).astype(float).where(known&night_clock&s.notna())*dt
        except ValueError:pass
    if complete(df,T,GHI):
        mask=shading_condition(df,t_threshold_c=24.,ghi_threshold_wh_m2=250.*dt)
        ledger["Solar protection screening"]=mask.astype(float).where(s.notna()&_valid(df,GHI).notna())*dt
    degrees=pd.DataFrame()
    if s.notna().any():
        try:
            daily=daily_stats(df,T)
            # Use the existing degree-day engine on complete daily means only.
            days=daily[["mean"]].rename(columns={"mean":T})
            days.attrs.update(df.attrs)
            degrees=degree_metric_table(days,heating_indoor_c=heat_i,heating_limit_c=heat_l,
                     cooling_indoor_c=cool_i,cooling_limit_c=cool_l,metric="Degree-days",aggregation="Monthly")
        except ValueError:pass
    return ledger,degrees

def design_dashboard(df,render,*,reference_df=None):
    with st.expander("Design assumptions",expanded=True):
        a,b,c=st.columns(3)
        t_min=a.number_input("NV minimum temperature [°C]",value=16.,step=.5,key="p6_nv_min")
        t_max=b.number_input("NV maximum temperature [°C]",value=26.,step=.5,key="p6_nv_max")
        w_max=c.number_input("NV humidity ratio limit [g/kg]",min_value=0.,value=9.,step=.5,key="p6_nv_w")
        a,b=st.columns(2)
        hot=a.number_input("Night flushing · hot-day threshold [°C]",value=26.,step=.5,key="p6_night_hot")
        cool=b.number_input("Night flushing · maximum night temperature [°C]",value=20.,step=.5,key="p6_night_cool")
        a,b,c,d=st.columns(4)
        hi=a.number_input("Heating indoor [°C]",value=20.,step=.5,key="p6_hgt_i")
        hl=b.number_input("Heating limit [°C]",value=12.,step=.5,key="p6_hgt_l")
        ci=c.number_input("Cooling indoor [°C]",value=26.,step=.5,key="p6_kgt_i")
        cl=d.number_input("Cooling limit [°C]",value=26.,step=.5,key="p6_kgt_l")
        st.caption("Solar protection screening: T ≥24 °C and mean GHI ≥250 W/m². Night: 22:00–06:59. NV: all selected hours, no additional wind filter. Other detailed design page settings are independent.")
    if t_min>t_max or hl>hi:st.warning("Check the temperature limits.");return
    ledger,degree=design_ledgers(df,reference_df=reference_df,t_min=t_min,t_max=t_max,w_max=w_max,hot=hot,cool=cool,heat_i=hi,heat_l=hl,cool_i=ci,cool_l=cl)
    items=[]
    for c in degree:
        items.append((str(c),_fmt(degree[c].sum(min_count=1),"K·d",0),"Complete daily means; HGT/KGT reference and selection temperatures above."))
    for c in ledger:
        eligible=float(ledger[c].sum(min_count=1))
        valid=ledger[c].notna().sum()*native_interval_hours(df)
        items.append((c,_fmt(eligible,"h",0),f"{valid:g} valid candidate hours; screening, not realized building performance."))
    if items:_cards(items)
    if not degree.empty:
        fig=go.Figure()
        for c,col in zip(degree,["#5488B6","#D98235"]):fig.add_bar(x=degree.index,y=degree[c],name=c,marker_color=col)
        fig.update_layout(template="plotly_white",barmode="group",title="Heating and cooling degree days",yaxis_title="K·d")
        render(fig,f"HGT {hi:g}/{hl:g}; KGT {ci:g}/{cl:g}. Complete days only. The indicators are climatic temperature differences, not building energy demand.")
    for c,col in zip(ledger,["#21866B","#527FA3","#D69A24"]):
        valid=ledger[c].notna().sum()*native_interval_hours(df);total=ledger[c].sum(min_count=1)
        note=f"{total:.0f} of {valid:.0f} valid candidate hours satisfy the configured criterion." if valid else "No valid candidate hours."
        if c=="Natural ventilation":note+=f" Temperature {t_min:g}–{t_max:g} °C, humidity ratio ≤{w_max:g} g/kg. No airflow prediction."
        elif c=="Night flushing":note+=f" Night ≤{cool:g} °C following a complete day reaching {hot:g} °C. No building heat-storage model."
        else:note+=" Climatic screening, not an aperture-specific shading calculation."
        _bar(_monthly(ledger[c],"sum"),c+" · monthly availability","Hours",col,render,note)
    if complete(df,T,RH,V):
        if st.checkbox("Include UTCI screening",value=False,key="p6_utci"):
            wind_factor=st.number_input("Source wind multiplier to 10 m",min_value=.01,value=1.,step=.1,key="p6_utci_wind")
            st.caption("Uniform radiant offset 0 K (MRT = air temperature); not sun-exposed or urban MRT. UTCI is a screening candidate; invalid domain inputs excluded.")
            values,_=utci_frame(df,wind_factor=wind_factor)
            table=utci_class_hours(df,values.iloc[:,0])
            fig=go.Figure()
            for c,col in zip(CLASSES,COLORS):
                if c in table:fig.add_bar(x=table.index,y=table[c],name=c,marker_color=col)
            fig.update_layout(template="plotly_white",title="UTCI thermal stress · monthly",barmode="stack",yaxis_title="Valid hours")
            render(fig,f"Uniform MRT assumption and wind multiplier {wind_factor:g}. {table.sum().sum():.0f} valid classified hours. Not qualified outdoor comfort under actual radiation.")
    if complete(df,T,W,"specific_volume_m3_kg"):
        if st.checkbox("Include ventilation conditioning loads",value=False,key="p6_loads"):
            flow=st.number_input("Outdoor airflow [m³/h]",min_value=0.,value=1000.,step=100.,key="p6_flow")
            if hi<=ci and w_max>=4:
                a=ventilation_loads(df,airflow=flow,heat=hi,cool=ci,w_low=4.,w_high=w_max)
                fig=go.Figure()
                for c in a:fig.add_bar(x=_monthly(a[c],"sum").index,y=_monthly(a[c],"sum"),name=c)
                fig.update_layout(template="plotly_white",title="Ventilation conditioning loads",barmode="group",yaxis_title="kWh")
                render(fig,f"Outdoor-air conditioning proxy for {flow:g} m³/h, {hi:g}–{ci:g} °C and humidity ratio 4–{w_max:g} g/kg. No heat recovery or plant model.")
            else:st.warning("Ventilation load deadband requires ordered temperature and moisture limits.")
