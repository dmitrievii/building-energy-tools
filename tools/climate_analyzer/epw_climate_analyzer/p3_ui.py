"""P3 panels using the existing render_plot presentation/export boundary."""
from __future__ import annotations
from time import perf_counter
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from . import p3_comfort as p
from .aggregations import native_interval_hours
from .temporal_filtering import available_years,filter_year

def _monthly(df,ledger,title,unit,render,note):
    table=p.monthly_totals(df,ledger)
    fig=go.Figure()
    for c in table:fig.add_bar(x=table.index,y=table[c],name=c)
    fig.update_layout(template="plotly_white",title=title,barmode="stack",yaxis_title=unit)
    render(fig,note)
    st.dataframe(table,use_container_width=True)

def _duration(df,series,title,unit,render,note):
    fig=go.Figure();dt=native_interval_hours(df)
    for c in series:
        y=np.sort(series[c].dropna().to_numpy())[::-1]
        if len(y):fig.add_scatter(x=np.arange(1,len(y)+1)*dt,y=y,mode="lines",name=c)
    fig.update_layout(template="plotly_white",title=title,xaxis_title="Physical hours",yaxis_title=unit)
    render(fig,note)

def _utci_performance_diagnostics(timing,visualization_s,csv_s=0.,setup_s=0.):
    with st.expander("Performance diagnostics",expanded=False):
        st.caption("Session-local cache hit." if timing["cache_hit"] else "Physical calculation executed.")
        st.write({
            "Selection and controls [s]":round(setup_s,4),
            "Input fingerprint [s]":round(timing["fingerprint_s"],4),
            "Library import / initialization [s]":round(timing["import_s"],4),
            "Physical calculation [s]":round(timing["calculation_s"],4),
            "Chart construction and server rendering [s]":round(visualization_s,4),
            "CSV preparation [s]":round(csv_s,4),
            "Retained result [MiB]":round(timing["retained_bytes"]/1024**2,3),
        })
        st.caption("First-use lazy numerical initialization, if applicable, is included in calculation time. Browser drawing and network latency are not measured.")

def outdoor_comfort(df,render):
    from . import utci_perf as perf
    started=perf_counter()
    st.header("Outdoor thermal comfort · UTCI")
    if df.empty:
        st.info("Coincident temperature, humidity and wind are required.");return
    years=available_years(df)
    if len(years)>1:df=filter_year(df,st.selectbox("Analysis year",years,index=len(years)-1,key="p3_otc_year"))
    if not p.complete(df,p.T,p.RH,p.V):
        st.info("Coincident temperature, humidity and wind are required for the selected year.");return
    options=["Uniform radiant offset"]
    if p.complete(df,p.T,p.RH,p.V,p.GHI,p.DHI,p.DNI,p.LW,p.ZEN):options.append("Open-sky screening")
    if st.session_state.get("p3_otc_model") not in options:
        st.session_state["p3_otc_model"]=options[-1]
    mode=st.selectbox("Radiation model",options,key="p3_otc_model")
    st.warning("Research candidate: UTCI requires 10 m wind and human mean radiant temperature. This simplified open-sky radiation scenario is not site-specific urban comfort.")
    wind=st.number_input("Wind conversion factor to 10 m",.1,10.,1.,.1,key="p3_otc_wind")
    st.caption("Default factor 1 assumes the source wind represents 10 m. Model-domain violations remain missing.")
    kw={}
    if mode==options[0]:
        kw["offset"]=st.number_input("Mean radiant temperature minus air temperature [K]",-30.,70.,0.,1.,key="p3_otc_offset")
        st.caption("User-specified radiant scenario, not measured MRT.")
    else:
        cols=st.columns(3)
        kw["albedo"]=cols[0].number_input("Ground reflectance",0.,1.,.2,.05,key="p3_otc_albedo")
        kw["projected_factor"]=cols[1].number_input("Beam projected-area factor",0.,1.,.25,.01,key="p3_otc_fp")
        kw["ground_delta"]=cols[2].number_input("Ground minus air temperature [K]",-50.,70.,0.,1.,key="p3_otc_ground")
        st.caption("Spherical-equivalent radiation: source sky longwave; ground blackbody temperature assumed; absorptivity .7, emissivity .95. Shade removes beam only.")
    choices=["UTCI heat map","Monthly thermal-stress distribution","UTCI duration curve"]+(["Sun versus shade"] if mode=="Open-sky screening" else [])+["Sensitivity analysis"]
    if st.session_state.get("p3_otc_chart") not in choices:
        st.session_state["p3_otc_chart"]=choices[0]
    chart=st.selectbox("Analysis type",choices,key="p3_otc_chart")
    from .utci_presentation import stress_heatmap,add_stress_bands,duration_figure,STRESS_NOTE
    note="UTCI equivalent temperature; missing or out-of-domain states excluded. Duration uses physical interval hours."
    if chart=="Sensitivity analysis":
        c=st.columns(3)
        t=c[0].number_input("Reference air temperature [°C]",-50.,50.,30.,key="p3_sens_t")
        rh=c[1].number_input("Reference relative humidity [%]",0.,100.,50.,key="p3_sens_rh")
        v=c[2].number_input("Reference 10 m wind [m/s]",.5,17.,1.,key="p3_sens_v")
        axis=st.selectbox("Sensitivity axes",["Air temperature × radiant offset","Wind speed × radiant offset","Air temperature × wind speed"],key="p3_sens_axis")
        ta=np.arange(-10.,46.);va=np.linspace(.5,17,34);da=np.arange(-30.,71.,2.)
        if axis=="Air temperature × radiant offset":
            x,y=ta,da;xx,yy=np.meshgrid(x,y);args=(xx,xx+yy,v,rh);xl="Air temperature [°C]";yl="Radiant offset [K]"
        elif axis=="Wind speed × radiant offset":
            x,y=va,da;xx,yy=np.meshgrid(x,y);args=(t,t+yy,xx,rh);xl="10 m wind [m/s]";yl="Radiant offset [K]"
        else:
            delta=st.number_input("Reference radiant offset [K]",-30.,70.,0.,key="p3_sens_delta")
            x,y=ta,va;xx,yy=np.meshgrid(x,y);args=(xx,xx+delta,yy,rh);xl="Air temperature [°C]";yl="10 m wind [m/s]"
        setup_s=perf_counter()-started
        try:z,timing=perf.cached_sensitivity(st.session_state,*args)
        except ImportError as exc:st.error("UTCI dependency unavailable: "+str(exc));return
        draw=perf_counter()
        fig=stress_heatmap(x,y,z,title="Controlled UTCI sensitivity",x_label=xl,y_label=yl)
        render(fig,"Hypothetical states, not frequencies. Other inputs held constant. "+note+" "+STRESS_NOTE)
        _utci_performance_diagnostics(timing,perf_counter()-draw,setup_s=setup_s)
        return
    setup_s=perf_counter()-started
    try:values,tr,physical_key,timing=perf.cached_physical(st.session_state,df,model=mode,wind_factor=wind,**kw)
    except ImportError as exc:st.error("UTCI dependency unavailable: "+str(exc));return
    draw=perf_counter()
    st.caption("Valid physical hours: "+", ".join(f"{c}: {v:g}" for c,v in (values.notna().sum()*native_interval_hours(df)).items()))
    if not values.notna().any().any():
        st.info("No admitted UTCI states.")
        _utci_performance_diagnostics(timing,perf_counter()-draw,setup_s=setup_s)
        return
    if chart=="UTCI duration curve":
        render(duration_figure(values,native_interval_hours(df),"UTCI duration curve"),note+" Shaded background indicates UTCI stress classes.")
    elif chart=="Sun versus shade":
        common=values.dropna()
        if common.empty:st.info("No common admitted exposure intervals.");return
        fig=go.Figure()
        for c in common:
            a=common[c].resample("MS").mean()
            fig.add_scatter(x=a.index,y=a,mode="lines+markers",name=c)
        fig.update_layout(template="plotly_white",title="Paired monthly mean UTCI",yaxis_title="UTCI [°C]")
        delta=(common["Open sun"]-common["Direct-beam shade"]).mean()
        render(add_stress_bands(fig,common.resample("MS").mean()),f"Paired mean open-sun minus shade UTCI: {delta:.2f} °C. "+note+" Background classes describe monthly means, not hourly stress duration.")
        render(duration_figure(common,native_interval_hours(df),"Paired exposure duration curves"),note+" Shaded background indicates UTCI stress classes.")
    else:
        if st.session_state.get("p3_otc_exposure") not in values.columns:
            st.session_state["p3_otc_exposure"]=values.columns[0]
        scenario=st.selectbox("Exposure",list(values),key="p3_otc_exposure")
        if chart=="UTCI heat map":
            grid=p.annual_hour_grid(df,values[scenario])
            fig=stress_heatmap(grid.columns,grid.index,grid,title="UTCI · "+scenario,x_label="Date",y_label="Hour of day")
            render(fig,note+" Multiple observations within an hour cell are averaged before classifying. "+STRESS_NOTE)
        else:
            tab=p.utci_class_hours(df,values[scenario]);fig=go.Figure()
            for c,color in zip(p.CLASSES,p.COLORS):fig.add_bar(x=tab.index,y=tab[c],name=c,marker_color=color)
            fig.update_layout(template="plotly_white",title="Monthly thermal-stress duration",barmode="stack",yaxis_title="Hours")
            render(fig,note+" Classes partition the valid duration.")
    visualization_s=perf_counter()-draw
    data,csv_s=perf.cached_csv(st.session_state,physical_key,values,tr)
    if data is None and st.button("Prepare UTCI and MRT CSV",key="p3_otc_prepare_csv"):
        data,csv_s=perf.cached_csv(st.session_state,physical_key,values,tr,prepare=True)
    if data is not None:
        st.download_button("UTCI and MRT data · CSV",data,"outdoor_comfort.csv","text/csv",
                           key="p3_otc_csv",on_click="ignore")
        # Release only the export bytes, not the physical calculations.
        if st.session_state.get(perf.CSV_KEY) is not None:
            def release_csv():
                st.session_state.pop(perf.CSV_KEY,None)
            st.button("Release CSV",key="p3_otc_release_csv",on_click=release_csv)
    _utci_performance_diagnostics(timing,visualization_s,csv_s,setup_s)

NV_SUITABILITY_SCALE=[[0,"#FFFFFF"],[.25,"#D9EEE6"],[.5,"#96D1BC"],[.75,"#47A88D"],[1,"#09634F"]]

def nv_sensitivity(df,mask,wind_available,render,*,temperature_limits=None,wind_limits=None):
    if not wind_available:
        st.info("Wind speed is unavailable.");return
    try:
        z,h=p.suitability_grid(df,mask,axis=p.V)
    except ValueError as exc:
        st.warning(str(exc));return
    if z.empty:st.info("No coincident observations for temperature and wind.");return
    fig=go.Figure(go.Heatmap(x=z.columns,y=z.index,z=z,customdata=h,zmin=0,zmax=100,
        colorscale=NV_SUITABILITY_SCALE,colorbar=dict(title="Suitable [%]",tickvals=[0,25,50,75,100]),
        xgap=1,ygap=1,hoverongaps=False,
        hovertemplate="Temperature bin center: %{x:.1f} °C<br>Wind-speed bin center: %{y:.2f} m/s<br>Suitable: %{z:.1f}%<br>Observed: %{customdata:.1f} h<extra></extra>"))
    # Missing cells are visibly different from measured 0% suitability.
    fig.add_heatmap(x=z.columns,y=z.index,z=np.where(np.isfinite(z),np.nan,1.),
        colorscale=[[0,"#D1D5DB"],[1,"#D1D5DB"]],zmin=0,zmax=1,showscale=False,
        xgap=1,ygap=1,hoverongaps=False,hovertemplate="No coincident observations<extra></extra>")
    if temperature_limits is not None:
        for value in temperature_limits:
            fig.add_vline(x=value,line_dash="dash",line_color="#444444",line_width=1)
    if wind_limits is not None:
        for value in wind_limits:
            fig.add_hline(y=value,line_dash="dash",line_color="#444444",line_width=1)
    fig.update_layout(template="plotly_white",title="Temperature–wind ventilation suitability",
        xaxis_title="Outdoor temperature [°C]",yaxis_title="Wind speed [m/s]",height=520)
    render(fig,"White = 0% suitability, dark green = 100%, gray = no coincident observations. Dashed boundaries show the configured temperature limits and, when enabled, wind limits. Each 2 K × 0.5 m/s cell reports the share of observed valid hours satisfying all configured conditions, including humidity and occupancy. Hover for observed duration. Not a predicted ventilation flow rate.")

def persistence_panel(df,mask,render,*,night=False):
    table=p.persistence(df,mask,night=night)
    unit="nights" if night else "days"
    label="Night" if night else "Day"
    threshold=st.number_input("Required uninterrupted suitable period [h]",min_value=.5,
        max_value=9. if night else 24.,value=2.,step=.5,key="p3_persistence_threshold_"+unit)
    counts=p.persistence_monthly(table,threshold)
    valid=int(counts["Observed days"].sum())
    meets=int(counts["Meets minimum"].sum())
    if not valid:
        st.info("No observed "+unit+" with known suitability.");return
    st.caption(f"{meets} of {valid} observed {unit} ({100*meets/valid:.1f}%) provide at least {threshold:g} consecutive suitable hours.")
    from .p3_persistence_chart import persistence_figure
    fig=persistence_figure(counts,f"{label} availability · at least {threshold:g} uninterrupted hours",night=night)
    render(fig,f"A {label.lower()} qualifies when at least one continuous suitable period reaches {threshold:g} h. For example, suitable periods 08:00–10:00 and 14:00–16:00 provide four total hours but only two consecutive hours. Unknown, rejected or missing intervals break a run. Partial observed {unit} are counted from available records only; entirely unknown {unit} are excluded. The line is the total observed count, not an additional category.")
    with st.expander("Detailed "+label.lower()+"-by-"+label.lower()+" results"):
        st.dataframe(table,use_container_width=True)
        st.download_button("Download continuous-period results · CSV",table.to_csv().encode("utf-8"),
                           "continuous_ventilation_"+unit+".csv","text/csv",key="p3_persistence_csv_"+unit)

def ventilation_load_panel(df,render):
    if not p.complete(df,p.T,p.W,p.SV):st.info("Temperature, humidity ratio and dry-air specific volume required.");return
    c=st.columns(3)
    flow=c[0].number_input("Outdoor airflow [m³/h]",0.,1000000.,1000.,100.,key="p3_hvac_flow")
    heat=c[1].number_input("Heating target [°C]",value=20.,step=.5,key="p3_hvac_heat")
    cool=c[2].number_input("Cooling target [°C]",value=26.,step=.5,key="p3_hvac_cool")
    c=st.columns(2)
    lo=c[0].number_input("Minimum humidity ratio [g/kg]",min_value=0.,value=3.,step=.5,key="p3_hvac_lo")
    hi=c[1].number_input("Maximum humidity ratio [g/kg]",min_value=0.,value=10.,step=.5,key="p3_hvac_hi")
    try:q=p.ventilation_loads(df,airflow=flow,heat=heat,cool=cool,w_low=lo,w_high=hi)
    except ValueError as exc:st.warning(str(exc));return
    chart=st.selectbox("Chart type",["Monthly load energy","Load duration curves"],key="p3_hvac_chart")
    note="Actual outdoor airflow; dry-air mass from source specific volume, sensible cp dependent on humidity, latent reference heat 2501 kJ/kg. Positive demand magnitudes, not net energy. No recovery, fan, plant efficiency or building heat balance."
    if chart=="Monthly load energy":_monthly(df,q,"Outdoor-air sensible and latent energy","kWh",render,note)
    else:_duration(df,q/native_interval_hours(df),"Outdoor-air load duration","kW",render,note)

def adaptive_panel(df,render):
    from .p3_adaptive_chart import COLUMNS,selected_daily_bands,adaptive_figure,adaptive_interpretation
    keys=["p3_adaptive_"+c for c in COLUMNS]
    if not all(k in df for k in keys):df=p.attach_adaptive(df)
    a=df[keys].copy();a.columns=list(COLUMNS)
    a=a.groupby(a.index.normalize()).first()
    a=selected_daily_bands(a,df)
    if not a["Running mean"].notna().any():st.info(adaptive_interpretation(a));return
    render(adaptive_figure(a),adaptive_interpretation(a))


def condensation_panel(df,render):
    surface=st.number_input("Specified surface temperature [°C]",value=12.,step=.5,key="p3_cond_surface")
    margin=p.condensation_margin(df,surface)
    if not margin.notna().any():st.info("No dew-point data.");return
    chart=st.selectbox("Chart type",["Monthly exposure hours","Dew-point margin duration"],key="p3_cond_chart")
    note="Potential saturation when assumed surface temperature is at or below outdoor-air dew point. No construction surface response, frost/condensate mass or interstitial condensation prediction."
    if chart=="Monthly exposure hours":_monthly(df,pd.DataFrame({"At or below dew point":margin.le(0).astype(float).where(margin.notna())*native_interval_hours(df)}),"Condensation potential","Hours",render,note)
    else:_duration(df,pd.DataFrame({"Surface minus dew point":margin}),"Surface-temperature margin","K",render,note)

def moisture_panel(df,render):
    flow=st.number_input("Outdoor airflow [m³/h]",0.,1000000.,1000.,100.,key="p3_moist_flow")
    target=st.number_input("Target humidity ratio [g/kg]",0.,40.,9.,.5,key="p3_moist_target")
    q=p.moisture_loads(df,airflow=flow,target=target)
    if not q.notna().any().any():st.info("Humidity ratio and dry-air specific volume are required.");return
    note="Water mass added or removed to reach target; actual-volume flow and source dry-air specific volume. No indoor generation or equipment model."
    if st.selectbox("Chart type",["Monthly water mass","Moisture-load duration"],key="p3_moist_chart")=="Monthly water mass":
        _monthly(df,q,"Outdoor-air moisture load","kg water",render,note)
    else:_duration(df,q/native_interval_hours(df),"Outdoor-air moisture-load duration","kg water/h",render,note)

def illuminance_panel(df,render):
    columns={label:c for label,c in (("Global horizontal","global_horizontal_illuminance_lux"),("Diffuse horizontal","diffuse_horizontal_illuminance_lux"),("Direct normal","direct_normal_illuminance_lux")) if p.numeric(df,c).notna().any()}
    if not columns:st.info("No source illuminance observations.");return
    label=st.selectbox("Illuminance quantity",list(columns),key="p3_lux_quantity")
    threshold=st.number_input("Availability threshold [lux]",0.,200000.,10000.,1000.,key="p3_lux_threshold")
    lux=p.numeric(df,columns[label]);lux=lux.where(lux.ge(0));dt=native_interval_hours(df)
    q=pd.DataFrame({"Below threshold":lux.lt(threshold).astype(float).where(lux.notna())*dt,
                    "At or above threshold":lux.ge(threshold).astype(float).where(lux.notna())*dt})
    view=st.selectbox("Chart type",["Monthly availability hours","Monthly availability percentage"],key="p3_lux_view")
    tab=p.monthly_totals(df,q)
    if view.endswith("percentage"):tab=tab.div(tab.sum(axis=1,min_count=2).replace(0,np.nan),axis=0)*100
    fig=go.Figure()
    for c in tab:fig.add_bar(x=tab.index,y=tab[c],name=c)
    fig.update_layout(template="plotly_white",title=f"{label} illuminance availability · {threshold:g} lux",barmode="stack",yaxis_title="%" if view.endswith("percentage") else "Hours")
    render(fig,"Outdoor source illuminance only. Denominator includes all valid selected intervals, including night. No irradiance-to-lux conversion or indoor daylight autonomy.")
