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

def duration_ledger_figure(df,series,title,unit):
    fig=go.Figure();dt=native_interval_hours(df)
    for c in series:
        y=np.sort(series[c].dropna().to_numpy())[::-1]
        if len(y):fig.add_scatter(x=np.arange(1,len(y)+1)*dt,y=y,mode="lines",name=c)
    fig.update_layout(template="plotly_white",title=title,xaxis_title="Physical hours",yaxis_title=unit)
    return fig


def _duration(df,series,title,unit,render,note):
    render(duration_ledger_figure(df,series,title,unit),note)

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
    if len(years)>1:
        choices=[*years,"All selected years"]
        year=st.selectbox("Analysis year",choices,index=len(years)-1,key="p3_otc_year")
        if year!="All selected years":df=filter_year(df,year)
    if not p.complete(df,p.T,p.RH,p.V):
        st.info("Coincident temperature, humidity and wind are required for the selected year.");return
    options=["Uniform radiant offset"]
    if p.complete(df,p.T,p.RH,p.V,p.GHI,p.DHI,p.DNI,p.LW,p.ZEN):options.append("Open-sky screening")
    if st.session_state.get("p3_otc_model") not in options:
        st.session_state["p3_otc_model"]=options[-1]
    mode=st.selectbox("Radiation model",options,key="p3_otc_model")
    st.caption(
        "UTCI combines air temperature, humidity, 10 m wind speed and human-equivalent "
        "mean radiant temperature. The selected radiation model determines the radiant "
        "exposure scenario used in the calculation."
    )
    wind=st.number_input("Wind conversion factor to 10 m",.1,10.,1.,.1,key="p3_otc_wind")
    st.caption("Default factor 1 assumes the source wind represents 10 m. Model-domain violations remain missing.")
    kw={}
    if mode==options[0]:
        kw["offset"]=st.number_input("Mean radiant temperature minus air temperature [K]",-30.,70.,0.,1.,key="p3_otc_offset")
        st.caption("The chosen temperature offset defines an equivalent radiant environment over the selected period.")
    else:
        cols=st.columns(3)
        kw["albedo"]=cols[0].number_input("Ground reflectance",0.,1.,.2,.05,key="p3_otc_albedo")
        kw["projected_factor"]=cols[1].number_input("Beam projected-area factor",0.,1.,.25,.01,key="p3_otc_fp")
        kw["ground_delta"]=cols[2].number_input("Ground minus air temperature [K]",-50.,70.,0.,1.,key="p3_otc_ground")
        st.caption(
            "Spherical-equivalent MRT model: measured sky longwave, ground emission at the "
            "specified temperature, assumed absorptivity 0.70 and emissivity 0.95. "
            "The shade scenario intercepts direct solar beam while retaining sky and ground exchange."
        )
    choices=["UTCI heat map","Monthly thermal-stress distribution","UTCI duration curve"]+(["Sun versus shade"] if mode=="Open-sky screening" else [])+["Sensitivity analysis"]
    if st.session_state.get("p3_otc_chart") not in choices:
        st.session_state["p3_otc_chart"]=choices[0]
    chart=st.selectbox("Analysis type",choices,key="p3_otc_chart")
    from .utci_presentation import stress_heatmap,add_stress_bands,duration_figure,STRESS_NOTE
    from .utci_findings import (
        utci_view_interpretation,utci_sensitivity_inputs,utci_sensitivity_interpretation,
        paired_monthly_figure,paired_delta_figure,paired_threshold_figure,mrt_monthly_figure,
    )
    note="UTCI equivalent temperature evaluated for the selected weather and radiation scenario. Duration uses physical observation hours."
    if chart=="Sensitivity analysis":
        c=st.columns(3)
        t=c[0].number_input("Reference air temperature [°C]",-50.,50.,30.,key="p3_sens_t")
        rh=c[1].number_input("Reference relative humidity [%]",0.,100.,50.,key="p3_sens_rh")
        v=c[2].number_input("Reference 10 m wind [m/s]",.5,17.,1.,key="p3_sens_v")
        axis=st.selectbox("Sensitivity axes",["Air temperature × radiant offset","Wind speed × radiant offset","Air temperature × wind speed"],key="p3_sens_axis")
        delta=0.
        if axis=="Air temperature × wind speed":
            delta=st.number_input("Reference radiant offset [K]",-30.,70.,0.,key="p3_sens_delta")
        x,y,args,xl,yl=utci_sensitivity_inputs(axis,temperature=t,rh=rh,wind=v,offset=delta)
        setup_s=perf_counter()-started
        try:z,timing=perf.cached_sensitivity(st.session_state,*args)
        except ImportError as exc:st.error("UTCI dependency unavailable: "+str(exc));return
        draw=perf_counter()
        fig=stress_heatmap(x,y,z,title="Controlled UTCI sensitivity",x_label=xl,y_label=yl)
        render(fig,utci_sensitivity_interpretation(axis,temperature=t,rh=rh,wind=v,offset=delta))
        _utci_performance_diagnostics(timing,perf_counter()-draw,setup_s=setup_s)
        return
    setup_s=perf_counter()-started
    try:values,tr,physical_key,timing=perf.cached_physical(st.session_state,df,model=mode,wind_factor=wind,**kw)
    except ImportError as exc:st.error("UTCI dependency unavailable: "+str(exc));return
    draw=perf_counter()
    st.caption(
        "Valid UTCI evaluation hours: " + ", ".join(
            f"{c}: {v:g} ({100*v/max(len(df)*native_interval_hours(df),1):.1f}% of period)"
            for c,v in (values.notna().sum()*native_interval_hours(df)).items()
        )
    )
    if not values.notna().any().any():
        st.info("No admitted UTCI states.")
        _utci_performance_diagnostics(timing,perf_counter()-draw,setup_s=setup_s)
        return
    if chart=="UTCI duration curve":
        scenarios=list(values)
        if len(scenarios)>1:
            selection=st.selectbox("Exposure",["All exposures",*scenarios],key="p3_otc_duration_exposure")
            if selection!="All exposures":scenarios=[selection]
        render(duration_figure(values[scenarios],native_interval_hours(df),"UTCI duration curve"),
               utci_view_interpretation(df,values[scenarios],"duration"))
    elif chart=="Sun versus shade":
        common=values.dropna(subset=["Open sun","Direct-beam shade"])
        if common.empty:
            st.info("No common admitted exposure intervals.")
            return
        comparison=st.selectbox(
            "Comparison view",
            ["Monthly mean UTCI","Monthly UTCI reduction","Heat-stress exposure",
             "Duration curves","Mean radiant temperature"],
            key="p3_otc_pair_view",
        )
        if comparison=="Monthly mean UTCI":
            fig=paired_monthly_figure(df,common)
            render(add_stress_bands(fig,common.resample("MS").mean()),
                   utci_view_interpretation(df,values,"utci_pair"))
        elif comparison=="Monthly UTCI reduction":
            render(paired_delta_figure(df,common),utci_view_interpretation(df,values,"utci_pair_delta"))
        elif comparison=="Heat-stress exposure":
            render(paired_threshold_figure(df,common),
                   utci_view_interpretation(df,values,"utci_pair_stress"))
        elif comparison=="Duration curves":
            render(duration_figure(common,native_interval_hours(df),"Paired exposure duration curves"),
                   utci_view_interpretation(df,values,"utci_pair_duration"))
        else:
            render(mrt_monthly_figure(tr.where(values[["Open sun","Direct-beam shade"]].notna().all(axis=1))),
                   utci_view_interpretation(df,values,"utci_pair_mrt"))
    else:
        if st.session_state.get("p3_otc_exposure") not in values.columns:
            st.session_state["p3_otc_exposure"]=values.columns[0]
        scenario=st.selectbox("Exposure",list(values),key="p3_otc_exposure")
        if chart=="UTCI heat map":
            grid=p.annual_hour_grid(df,values[scenario])
            fig=stress_heatmap(grid.columns,grid.index,grid,title="UTCI · "+scenario,x_label="Date",y_label="Hour of day")
            render(fig,utci_view_interpretation(df,values,"heatmap",exposure=scenario))
        else:
            tab=p.utci_class_hours(df,values[scenario]);fig=go.Figure()
            for c,color in zip(p.CLASSES,p.COLORS):fig.add_bar(x=tab.index,y=tab[c],name=c,marker_color=color)
            fig.update_layout(template="plotly_white",title="Monthly thermal-stress duration",barmode="stack",yaxis_title="Hours")
            render(fig,utci_view_interpretation(df,values,"stress",exposure=scenario))
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

def nv_sensitivity_figure(df,mask,*,temperature_limits=None,wind_limits=None):
    z,h=p.suitability_grid(df,mask,axis=p.V)
    if z.empty:raise ValueError("No coincident observations for temperature and wind.")
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
    observed=h.where(z.notna()).fillna(0.)
    valid=float(observed.to_numpy().sum())
    eligible=float((z.fillna(0.)*observed/100.).to_numpy().sum())
    note=f"Across {valid:,.1f} coincident temperature–wind observation hours, {eligible:,.1f} h ({100*eligible/valid:.1f}%) satisfy the active outdoor-air screen. "
    if eligible>0:
        suitable=(z.fillna(0.)*observed/100.).stack()
        wind,temp=suitable.idxmax()
        note+=f"The largest concentration of eligible time is at the {temp:g} °C and {wind:g} m/s bin centres ({suitable.max():,.1f} h). "
    note+="White = 0% suitability, dark green = 100%, gray = no coincident observations. Each 2 K × 0.5 m/s cell reports the share of observed valid hours satisfying the configured conditions. Dashed boundaries mark active limits. The distribution informs opening operation and façade ventilation design."
    return fig,note

def nv_sensitivity(df,mask,wind_available,render,*,temperature_limits=None,wind_limits=None):
    if not wind_available:
        st.info("Wind speed is unavailable.");return
    try:render(*nv_sensitivity_figure(df,mask,temperature_limits=temperature_limits,wind_limits=wind_limits))
    except ValueError as exc:st.warning(str(exc))


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
    render(fig,persistence_interpretation(threshold,night=night,counts=counts))

    with st.expander("Detailed "+label.lower()+"-by-"+label.lower()+" results"):
        st.dataframe(table,use_container_width=True)
        st.download_button("Download continuous-period results · CSV",table.to_csv().encode("utf-8"),
                           "continuous_ventilation_"+unit+".csv","text/csv",key="p3_persistence_csv_"+unit)

def ventilation_load_panel(df,render):
    from .hvac_findings import (
        conditioning_interpretation,conditioning_summary,conditioning_monthly_figure,
    )
    if not p.complete(df,p.T,p.W,p.SV):
        st.info("Temperature, humidity ratio and dry-air specific volume are required.")
        return
    c=st.columns(3)
    flow=c[0].number_input("Outdoor airflow [m³/h]",0.,1000000.,1000.,100.,key="p3_hvac_flow")
    heat=c[1].number_input("Heating target [°C]",value=20.,step=.5,key="p3_hvac_heat")
    cool=c[2].number_input("Cooling target [°C]",value=26.,step=.5,key="p3_hvac_cool")
    c=st.columns(2)
    # Shared documented reference inputs for the archived complete atlas.
    lo=c[0].number_input("Minimum humidity ratio [g/kg]",min_value=0.,value=4.,step=.5,key="p3_hvac_lo")
    hi=c[1].number_input("Maximum humidity ratio [g/kg]",min_value=0.,value=9.,step=.5,key="p3_hvac_hi")
    try:
        q=p.ventilation_loads(df,airflow=flow,heat=heat,cool=cool,w_low=lo,w_high=hi)
    except ValueError as exc:
        st.warning(str(exc))
        return
    note=conditioning_interpretation(
        df,q,airflow=flow,heat=heat,cool=cool,w_low=lo,w_high=hi,
    )
    st.caption(
        "The reference evaluates outdoor dry-air mass from specific volume, "
        "temperature-dependent sensible heat capacity and water-vapour "
        "phase-change energy at a fixed outdoor airflow."
    )
    chart=st.selectbox(
        "Chart type",["Monthly grouped energies","Monthly stacked contributions",
                      "Load duration curves"],key="p3_hvac_chart",
    )
    if chart=="Load duration curves":
        _duration(df,q/native_interval_hours(df),"Outdoor-air load duration",
                  "kW",render,note)
    else:
        grouped=chart=="Monthly grouped energies"
        fig=conditioning_monthly_figure(
            df,q,grouped=grouped,title="Monthly outdoor-air sensible and latent energy",
        )
        render(fig,note)
        st.dataframe(p.monthly_totals(df,q),use_container_width=True)
    with st.expander("Calculated energy summary",expanded=False):
        st.dataframe(
            conditioning_summary(df,q).rename("Value").to_frame(),
            use_container_width=True,
        )


def adaptive_panel(df,render):
    from .p3_adaptive_chart import COLUMNS,selected_daily_bands,adaptive_figure,adaptive_interpretation,ADAPTIVE_MODES,RESEARCH_MODE
    model=st.selectbox("Adaptive comfort model",ADAPTIVE_MODES,key="p3_adaptive_model")
    extrapolate=model==RESEARCH_MODE
    keys=["p3_adaptive_"+c for c in COLUMNS]
    if not all(k in df for k in keys):df=p.attach_adaptive(df)
    a=df[keys].copy();a.columns=list(COLUMNS)
    a=a.groupby(a.index.normalize()).first()
    a=selected_daily_bands(a,df)
    note=adaptive_interpretation(a,extrapolate=extrapolate)
    if not a["Running mean"].notna().any():st.info(note);return
    render(adaptive_figure(a,extrapolate=extrapolate),note)


def condensation_panel(df,render):
    surface=st.number_input("Specified surface temperature [°C]",value=12.,step=.5,key="p3_cond_surface")
    margin=p.condensation_margin(df,surface)
    if not margin.notna().any():st.info("No dew-point data.");return
    chart=st.selectbox("Chart type",["Monthly exposure hours","Dew-point margin duration"],key="p3_cond_chart")
    from .humidity_findings import humidity_figure_interpretation
    note=humidity_figure_interpretation(df,None,"condensation",surface_c=surface)
    if chart=="Monthly exposure hours":_monthly(df,pd.DataFrame({"At or below dew point":margin.le(0).astype(float).where(margin.notna())*native_interval_hours(df)}),"Condensation potential","Hours",render,note)
    else:_duration(df,pd.DataFrame({"Surface minus dew point":margin}),"Surface-temperature margin","K",render,note)

def moisture_panel(df,render):
    flow=st.number_input("Outdoor airflow [m³/h]",0.,1000000.,1000.,100.,key="p3_moist_flow")
    target=st.number_input("Target humidity ratio [g/kg]",0.,40.,9.,.5,key="p3_moist_target")
    q=p.moisture_loads(df,airflow=flow,target=target)
    if not q.notna().any().any():st.info("Humidity ratio and dry-air specific volume are required.");return
    from .humidity_findings import humidity_figure_interpretation
    note=humidity_figure_interpretation(
        df,None,"moisture",airflow_m3_h=flow,target_g_kg=target)
    if st.selectbox("Chart type",["Monthly water mass","Moisture-load duration"],key="p3_moist_chart")=="Monthly water mass":
        _monthly(df,q,"Outdoor-air moisture load","kg water",render,note)
    else:_duration(df,q/native_interval_hours(df),"Outdoor-air moisture-load duration","kg water/h",render,note)

def illuminance_panel(df,render):
    columns={label:c for label,c in (("Global horizontal","global_horizontal_illuminance_lux"),("Diffuse horizontal","diffuse_horizontal_illuminance_lux"),("Direct normal","direct_normal_illuminance_lux")) if p.numeric(df,c).notna().any()}
    if not columns:st.info("No source illuminance observations.");return
    label=st.selectbox("Illuminance quantity",list(columns),key="p3_lux_quantity")
    threshold=st.number_input("Availability threshold [lux]",0.,200000.,10000.,1000.,key="p3_lux_threshold")
    aggregation=st.selectbox("Aggregation",["Monthly","Weekly","Daily","Seasonal","Annual"],key="p3_lux_period")
    view=st.selectbox("Chart type",["Availability hours","Availability percentage"],key="p3_lux_view")
    from .sky_findings import illuminance_availability_figure
    render(*illuminance_availability_figure(df,columns[label],threshold_lux=threshold,
                aggregation=aggregation,percentage=view.endswith("percentage")))


def extensive_total_panel(df,render,*,columns):
    from .residual_findings import TOTAL_FIELDS,PERIODS,extensive_total_figure
    options={TOTAL_FIELDS[c][0]:c for c in columns if p.numeric(df,c).notna().any()}
    if not options:st.info("No valid observations for the selected accumulation.");return
    label=next(iter(options)) if len(options)==1 else st.selectbox("Quantity",list(options),key="extensive_total_quantity")
    period=st.selectbox("Aggregation",list(PERIODS),key="extensive_total_period")
    try:render(*extensive_total_figure(df,options[label],period))
    except ValueError as exc:st.info(str(exc))


def reference_eligibility_panel(df,render,*,reference_df=None,names=("nv","night","shade")):
    from .residual_findings import eligibility_figure,PERIODS
    from .p6_dashboard import design_ledgers
    ledger,_=design_ledgers(df,reference_df=reference_df)
    labels={"nv":"Natural ventilation","night":"Night flushing","shade":"Solar protection screening"}
    options={labels[k]:k for k in names if labels[k] in ledger and ledger[labels[k]].notna().any()}
    if not options:st.info("No valid candidate hours.");return
    name=options[st.selectbox("Screen",list(options),key="reference_screen_name")]
    view=st.selectbox("Chart type",["Eligible hours by period","Eligibility heat map"],key="reference_screen_view")
    mode="total" if view=="Eligible hours by period" else "map"
    period=st.selectbox("Aggregation",list(PERIODS) if mode=="total" else ["Day","Week","Month"],key="reference_screen_period")
    render(*eligibility_figure(df,name,period if mode=="total" else period.lower(),view=mode,ledger=ledger))


def temperature_threshold_panel(df,render):
    from .residual_findings import temperature_threshold_figure
    period=st.selectbox("Aggregation",["Monthly","Weekly","Daily","Seasonal"],key="temperature_threshold_period")
    mode=st.radio("Condition",["Below heating threshold","Above cooling threshold","Heating and cooling thresholds","Frost hours (Tdry < 0 °C)","Nighttime hours > 20 °C (20:00–06:59)"],key="temperature_threshold_mode")
    low=st.slider("Heating threshold [°C]",-5.,25.,18.,.5,key="temperature_condition_heating") if mode in ("Below heating threshold","Heating and cooling thresholds") else 18.
    high=st.slider("Cooling threshold [°C]",15.,40.,26.,.5,key="temperature_condition_cooling") if mode in ("Above cooling threshold","Heating and cooling thresholds") else 26.
    try:render(*temperature_threshold_figure(df,period,low=low,high=high,mode=mode))
    except ValueError as exc:st.info(str(exc))


def snow_hours_panel(df,render):
    from .residual_findings import snow_hours_figure,PERIODS
    period=st.selectbox("Aggregation",list(PERIODS),key="snow_hours_period")
    try:render(*snow_hours_figure(df,period))
    except ValueError as exc:st.info(str(exc))


def persistence_interpretation(threshold,*,night=False,counts=None):
    unit="nights" if night else "days"
    label="Night" if night else "Day"
    prefix=""
    if counts is not None:
        valid=float(counts["Observed days"].sum())
        meets=float(counts["Meets minimum"].sum())
        if valid:
            prefix=f"{meets:,.0f} of {valid:,.0f} observed {unit} ({100*meets/valid:.1f}%) provide at least {threshold:g} consecutive suitable hours. "
            monthly=counts["Meets minimum"].dropna()
            if not monthly.empty and monthly.max()>0:
                prefix+=f"The highest number of qualifying {unit} occurs in {pd.Timestamp(monthly.idxmax()):%B %Y} ({monthly.max():,.0f}). "
            prefix+="These durations guide the scheduling of sustained ventilation opportunities. "
    return prefix+f"A {label.lower()} qualifies when at least one continuous suitable period reaches {threshold:g} h. For example, suitable periods 08:00–10:00 and 14:00–16:00 provide four total hours but only two consecutive hours. Unknown, rejected or missing intervals break a run. Partial observed {unit} are counted from available records only; entirely unknown {unit} are excluded. The line reports the total observed day count, while the stacked bars resolve the qualifying and shorter-duration days."
