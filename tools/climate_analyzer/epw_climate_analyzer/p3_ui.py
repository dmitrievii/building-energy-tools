"""P3 panels using the existing render_plot presentation/export boundary."""
from __future__ import annotations
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

def outdoor_comfort(df,render):
    st.header("Outdoor thermal comfort · UTCI")
    if df.empty or not p.complete(df,p.T,p.RH,p.V):
        st.info("Coincident temperature, humidity and wind are required.");return
    years=available_years(df)
    if len(years)>1:df=filter_year(df,st.selectbox("Analysis year",years,index=len(years)-1,key="p3_otc_year"))
    options=["Uniform radiant offset"]
    if p.complete(df,p.T,p.RH,p.V,p.GHI,p.DHI,p.DNI,p.LW,p.ZEN):options.append("Open-sky screening")
    mode=st.selectbox("Radiation model",options,index=len(options)-1,key="p3_otc_model")
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
    chart=st.selectbox("Analysis type",choices,key="p3_otc_chart")
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
        try:z=p.utci_values(*args)
        except ImportError as exc:st.error("UTCI dependency unavailable: "+str(exc));return
        fig=go.Figure(go.Heatmap(x=x,y=y,z=z,colorscale="RdBu_r",colorbar=dict(title="UTCI [°C]"),hoverongaps=False))
        fig.update_layout(template="plotly_white",title="Controlled UTCI sensitivity",xaxis_title=xl,yaxis_title=yl)
        render(fig,"Hypothetical states, not frequencies. Other inputs held constant. "+note);return
    try:values,tr=p.utci_frame(df,model=mode,wind_factor=wind,**kw)
    except ImportError as exc:st.error("UTCI dependency unavailable: "+str(exc));return
    st.caption("Valid physical hours: "+", ".join(f"{c}: {v:g}" for c,v in (values.notna().sum()*native_interval_hours(df)).items()))
    if not values.notna().any().any():st.info("No admitted UTCI states.");return
    if chart=="UTCI duration curve":
        _duration(df,values,"UTCI duration curve","UTCI [°C]",render,note)
    elif chart=="Sun versus shade":
        common=values.dropna()
        if common.empty:st.info("No common admitted exposure intervals.");return
        fig=go.Figure()
        for c in common:
            a=common[c].resample("MS").mean()
            fig.add_scatter(x=a.index,y=a,mode="lines+markers",name=c)
        fig.update_layout(template="plotly_white",title="Paired monthly mean UTCI",yaxis_title="UTCI [°C]")
        delta=(common["Open sun"]-common["Direct-beam shade"]).mean()
        render(fig,f"Paired mean open-sun minus shade UTCI: {delta:.2f} °C. "+note)
        _duration(df,common,"Paired exposure duration curves","UTCI [°C]",render,note)
    else:
        scenario=st.selectbox("Exposure",list(values),key="p3_otc_exposure")
        if chart=="UTCI heat map":
            grid=p.annual_hour_grid(df,values[scenario])
            fig=go.Figure(go.Heatmap(x=grid.columns,y=grid.index,z=grid,colorscale="RdBu_r",zmid=20,colorbar=dict(title="UTCI [°C]"),hoverongaps=False))
            fig.update_layout(template="plotly_white",title="UTCI · "+scenario,xaxis_title="Date",yaxis_title="Analysis clock hour")
            render(fig,note+" Multiple observations within an hour cell are averaged.")
        else:
            tab=p.utci_class_hours(df,values[scenario]);fig=go.Figure()
            for c,color in zip(p.CLASSES,p.COLORS):fig.add_bar(x=tab.index,y=tab[c],name=c,marker_color=color)
            fig.update_layout(template="plotly_white",title="Monthly thermal-stress duration",barmode="stack",yaxis_title="Hours")
            render(fig,note+" Classes partition the valid duration.")
    st.download_button("UTCI and MRT data · CSV",pd.concat([values.add_prefix("UTCI · "),tr.add_prefix("MRT · ")],axis=1).to_csv().encode(),"outdoor_comfort.csv","text/csv",key="p3_otc_csv")

def nv_sensitivity(df,mask,wind_available,render):
    options=["Temperature × humidity ratio"]+(["Temperature × wind speed"] if wind_available else [])
    axis=p.W if st.selectbox("Sensitivity axes",options,key="p3_nv_sens")==options[0] else p.V
    z,h=p.suitability_grid(df,mask,axis=axis)
    if z.empty:st.info("No coincident observations for these axes.");return
    fig=go.Figure(go.Heatmap(x=z.columns,y=z.index,z=z,customdata=h,zmin=0,zmax=100,colorscale="RdYlGn",colorbar=dict(title="Suitable [%]"),hoverongaps=False,hovertemplate="T bin %{x}<br>Second variable bin %{y}<br>Suitable %{z:.1f}%<br>Valid %{customdata:.1f} h<extra></extra>"))
    fig.update_layout(template="plotly_white",title="Observed ventilation suitability",xaxis_title="Air temperature [°C]",yaxis_title="Humidity ratio [g/kg]" if axis==p.W else "Wind speed [m/s]")
    render(fig,"Fraction satisfying all configured limits within observed 2 K × 1 g/kg or 2 K × 0.5 m/s bins. Empty bins not extrapolated. Climatic suitability, not air change rate.")

def persistence_panel(df,mask,render,*,night=False):
    table=p.persistence(df,mask,night=night)
    fig=go.Figure()
    for c in ("Longest run [h]","Suitable hours [h]"):
        fig.add_scatter(x=table.index,y=table[c],mode="lines",name=c,connectgaps=False)
    fig.update_layout(template="plotly_white",title="Nightly flushing persistence" if night else "Daily consecutive ventilation availability",yaxis_title="Hours",xaxis_title="Night starting date" if night else "Date")
    render(fig,"Longest uninterrupted run and total suitable duration. Missing timestamps, rejected or unknown intervals break a run; overnight runs may cross midnight but not the night boundary.")
    st.dataframe(table,use_container_width=True)

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
    keys=["p3_adaptive_"+c for c in ("Running mean","Neutral","I lower","I upper","II lower","II upper","III lower","III upper")]
    if not all(k in df for k in keys):df=p.attach_adaptive(df)
    cat=st.selectbox("EN 16798-1 category",["I","II","III"],index=1,key="p3_adaptive_cat")
    a=df[keys].copy();a.columns=[k.removeprefix("p3_adaptive_") for k in keys];a=a.resample("D").first()
    if not a.Neutral.notna().any():st.info("No in-domain running means after seven complete preceding days.");return
    fig=go.Figure()
    fig.add_scatter(x=a.index,y=a[cat+" lower"],mode="lines",name="Lower limit",connectgaps=False)
    fig.add_scatter(x=a.index,y=a[cat+" upper"],mode="lines",name="Upper limit",fill="tonexty",connectgaps=False)
    fig.add_scatter(x=a.index,y=a.Neutral,mode="lines",name="Neutral operative temperature",connectgaps=False)
    fig.add_scatter(x=a.index,y=a["Running mean"],mode="lines",name="Outdoor running mean",line=dict(dash="dot"),connectgaps=False)
    fig.update_layout(template="plotly_white",title="Adaptive indoor operative temperature · Category "+cat,yaxis_title="Temperature [°C]")
    render(fig,"EN 16798-1 screening for occupant-controlled naturally ventilated spaces. Seven previous complete daily means, normalized alpha=.8, 10–30 °C domain. No elevated air speed adjustment, warm-up invention or indoor compliance claim.")

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
