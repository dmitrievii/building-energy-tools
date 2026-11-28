"""Shared controls for parameter-sensitivity maps (no retained weather matrices)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import streamlit as st
from .threshold_sensitivity import SPECS, figure
from .p3_comfort import numeric


def available(df, kinds):
    return [k for k in kinds if all(numeric(df,c).notna().any() for c in SPECS[k].fields)]


def panel(df,render,kinds,*,key,fixed=None,references=None):
    kinds=available(df,kinds)
    if not kinds:
        st.info("The selected climate has no usable source quantities for these parameter maps.")
        return
    kind=kinds[0] if len(kinds)==1 else st.selectbox("Sensitivity map",kinds,format_func=lambda k:SPECS[k].title,key=key+"_kind")
    spec=SPECS[kind]
    ref=tuple((references or {}).get(kind,spec.reference))
    p=dict(fixed or {})
    explanations={
        "nv_temperature_moisture":"Compare allowable maximum temperature and humidity to see which limit controls ventilation availability.",
        "nv_temperature_range":"Compare lower and upper outdoor temperature limits to evaluate the usable ventilation temperature band.",
        "nv_wind_range":"Compare minimum and maximum wind speeds to assess availability within a proposed operating range.",
        "night":"Compare the required hot-day temperature and allowable night temperature to assess night-flushing opportunities.",
        "night_delta":"Compare the required preceding-day maximum to night temperature difference and the night temperature ceiling.",
        "solar":"Compare outdoor temperature and horizontal solar intensity required to trigger solar protection.",
        "neutral":"Compare heating and cooling thresholds to assess the duration within the outdoor neutral-temperature band.",
        "economizer":"Compare maximum outdoor temperature and return-air enthalpy reference to assess outdoor-air cooling opportunities.",
        "surface":"Compare surface temperature and surface RH threshold to assess exposure to elevated surface relative humidity.",
    }
    st.caption(explanations[kind])
    st.markdown(f"**Reference:** {spec.x_label} = {ref[0]:g}; {spec.y_label} = {ref[1]:g}.")
    st.caption("Each cell counts observations satisfying both axis limits and the fixed criteria, within the active Data filter.")
    with st.expander("Fixed screening criteria",expanded=False):
        names={"t_min_c":"Minimum outdoor temperature [°C]","t_max_c":"Maximum outdoor temperature [°C]",
            "d_max_g_kg":"Maximum humidity ratio [g/kg]","wind_min_m_s":"Minimum wind speed [m/s]",
            "wind_max_m_s":"Maximum wind speed [m/s]","occupied_only":"Occupied hours only",
            "occupied_start_hour":"First occupied hour","occupied_end_hour":"Last occupied hour","weekdays_only":"Weekdays only"}
        varied={"nv_temperature_moisture":("t_max_c","d_max_g_kg"),
            "nv_temperature_range":("t_min_c","t_max_c"),"nv_wind_range":("wind_min_m_s","wind_max_m_s")}
        fixed_view={k:v for k,v in p.items() if k not in varied.get(kind,())}
        if kind=="economizer":fixed_view["t_min_c"]=p.get("t_min_c",5.)
        if fixed_view:
            for k,v in fixed_view.items():
                st.write(f"{names.get(k,k)}: {v if v is not None else 'Unrestricted'}")
        else:st.caption("Both displayed limits and the active climate selection define this screen.")
    if kind=="nv_wind_range" and p.get("wind_min_m_s") is None and p.get("wind_max_m_s") is None:
        st.caption("The reference is a candidate wind range; the active ventilation screen is unrestricted by wind.")
    with st.expander("Parameter ranges",expanded=False):
        a,b=st.columns(2)
        xr=(min(spec.x_range[0],ref[0]),max(spec.x_range[1],ref[0]))
        yr=(min(spec.y_range[0],ref[1]),max(spec.y_range[1],ref[1]))
        xmin=a.number_input(spec.x_label+" · from",value=float(xr[0]),key=key+"_"+kind+"_xmin")
        xmax=a.number_input(spec.x_label+" · to",value=float(xr[1]),key=key+"_"+kind+"_xmax")
        ymin=b.number_input(spec.y_label+" · from",value=float(yr[0]),key=key+"_"+kind+"_ymin")
        ymax=b.number_input(spec.y_label+" · to",value=float(yr[1]),key=key+"_"+kind+"_ymax")
        n=st.select_slider("Grid resolution per axis",options=[11,21,31,41,61],value=31,key=key+"_resolution")
    basis="hours"
    if kind.startswith("night"):
        basis=st.radio("Count basis",["Eligible hours","Nights with eligible intervals"],horizontal=True,key=key+"_basis").startswith("Nights") and "nights" or "hours"
    unit_options=["Hours [h]","Share of valid hours [%]"] if basis=="hours" else ["Nights","Share of observed nights [%]"]
    unit_options.append("Change from reference [h]" if basis=="hours" else "Change from reference [nights]")
    result=st.radio("Result quantity",unit_options,horizontal=True,key=key+"_unit_"+basis)
    percent=result.startswith("Share")
    relative=result.startswith("Change")
    if xmin>=xmax or ymin>=ymax:
        st.warning("Each parameter range must have a positive width.")
        return
    x=np.linspace(xmin,xmax,n);y=np.linspace(ymin,ymax,n)
    try:render(*figure(df,kind,x,y,fixed=p,reference=ref,percentage=percent,basis=basis,relative=relative))
    except (ValueError,KeyError) as exc:st.info(str(exc))


def geometry_panel(df,render,*,geometry,albedo,key):
    from .threshold_sensitivity import shading_geometry_figure
    from .architectural_shading import window_geometry_3d, comparison_figure, comparison_energy
    st.caption("Compare overhang and symmetric side-fin depths at fixed window dimensions and façade azimuth.")
    seasons={"Winter":(12,1,2),"Spring":(3,4,5),"Summer":(6,7,8),"Autumn":(9,10,11)}
    options=["Selected period",*seasons]
    t=numeric(df,"dry_bulb_temperature_c")
    if t.notna().any():options+=["Hot conditions","Cold conditions"]
    scope=st.selectbox("Performance period",options,key=key+"_scope")
    data=df
    if scope in seasons:data=df.loc[df.index.month.isin(seasons[scope])]
    if scope in ("Hot conditions","Cold conditions"):
        default=26. if scope=="Hot conditions" else 18.
        threshold=st.number_input("Outdoor temperature threshold [°C]",value=default,step=.5,key=key+"_thermal_"+scope)
        data=df.loc[t>threshold if scope=="Hot conditions" else t<threshold]
    if data.empty:
        st.info("No observations in this performance period.");return
    # Retain native interval metadata on filtered, discontinuous observations.
    from .aggregations import native_interval_hours
    if data is not df:
        data=data.copy();data.attrs.update(df.attrs)
        data.attrs["canonical_native_interval_minutes"]=native_interval_hours(df)*60
    active_albedo=albedo.reindex(data.index) if isinstance(albedo,pd.Series) else albedo
    with st.expander("Geometry ranges",expanded=False):
        a,b=st.columns(2)
        xmax=a.number_input("Maximum overhang depth [m]",min_value=.1,max_value=10.,value=max(2.,float(geometry["overhang"])),step=.1,key=key+"_x")
        ymax=b.number_input("Maximum depth of each fin [m]",min_value=.1,max_value=10.,value=max(2.,float(geometry["left_fin"]),float(geometry["right_fin"])),step=.1,key=key+"_y")
        n=st.select_slider("Grid resolution per axis",options=[5,11,21,31],value=11,key=key+"_n")
    x=np.linspace(0,xmax,n);y=np.linspace(0,ymax,n)
    # Grid-aligned choices provide exact correspondence with the heat-map cells.
    a,b=st.columns(2)
    cx=a.select_slider("Candidate overhang [m]",options=x.tolist(),
        value=float(x[np.abs(x-geometry["overhang"]).argmin()]),format_func=lambda v:f"{v:.2f}",key=key+"_cx_"+str(xmax)+"_"+str(n))
    mean_fin=(geometry["left_fin"]+geometry["right_fin"])/2
    cy=b.select_slider("Candidate depth of each fin [m]",options=y.tolist(),
        value=float(y[np.abs(y-mean_fin).argmin()]),format_func=lambda v:f"{v:.2f}",key=key+"_cy_"+str(ymax)+"_"+str(n))
    candidate={**geometry,"overhang":float(cx),"left_fin":float(cy),"right_fin":float(cy)}
    labels={"Remaining total irradiation [kWh/m²]":"remaining","Intercepted direct irradiation [kWh/m²]":"intercepted",
            "Total irradiation reduction [%]":"total_percent","Direct irradiation reduction [%]":"direct_percent"}
    quantity=st.selectbox("Performance quantity",list(labels),key=key+"_quantity")
    try:
        fig,note=shading_geometry_figure(data,x,y,geometry=geometry,albedo=active_albedo,quantity=labels[quantity],candidate=(cx,cy))
        render(fig,note+" The blue diamond identifies the selected candidate.")
    except ValueError as exc:
        st.info(str(exc));return
    st.markdown("#### Selected candidate · interactive 3D")
    st.plotly_chart(window_geometry_3d(**candidate),use_container_width=True,key=key+"_candidate_3d",
                    config={"displaylogo":False,"scrollZoom":True})
    st.markdown("#### Architectural comparison")
    zero={**geometry,"overhang":0.,"left_fin":0.,"right_fin":0.}
    cases=[("No shading",zero),("Current geometry",geometry),("Selected candidate",candidate)]
    energy=comparison_energy(data,cases,albedo=active_albedo)
    az=numeric(data,"solar_azimuth_deg")
    el=90-numeric(data,"solar_apparent_zenith_deg")
    normal=np.cos(np.deg2rad(el))*np.cos(np.deg2rad(az-geometry["facade"]))
    valid=az.notna()&el.between(0,90)&(el>0)&(normal>1e-10)
    dates=data.index[valid].normalize().unique().sort_values()
    if not len(dates):
        st.info("No front-facing sun positions in this period.");return
    day=st.selectbox("Solar position · date",list(dates),format_func=lambda d:d.strftime("%d.%m.%Y"),key=key+"_date_"+scope)
    times=data.index[valid&(data.index.normalize()==day)].sort_values()
    # Select an actual source interval, including subhourly records.
    stamp=st.selectbox("Solar position · time",list(times),index=len(times)//2,
        format_func=lambda d:d.strftime("%H:%M"),key=key+"_time_"+str(day))
    f=comparison_figure(cases,float(az.loc[stamp]),float(el.loc[stamp]),energy=energy)
    note=(f"Window shadows are projected for {stamp:%d.%m.%Y at %H:%M}, using the site solar position and actual geometry. "
          f"Irradiation totals cover {scope.lower()} within the active Data filter. "
          "The shaded window area refers to this solar position; intercepted and remaining irradiation describe the complete performance period. "
          "The direct-beam model retains diffuse and ground-reflected irradiation.")
    render(f,note)
