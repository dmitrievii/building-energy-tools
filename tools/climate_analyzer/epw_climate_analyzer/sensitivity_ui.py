"""Shared controls for parameter-sensitivity maps (no retained weather matrices)."""
from __future__ import annotations
import numpy as np
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
    st.caption("Sweep two design parameters; all other active criteria and the global Data filter remain fixed.")
    with st.expander("Parameter ranges",expanded=False):
        a,b=st.columns(2)
        xr=(min(spec.x_range[0],ref[0]),max(spec.x_range[1],ref[0]))
        yr=(min(spec.y_range[0],ref[1]),max(spec.y_range[1],ref[1]))
        xmin=a.number_input(spec.x_label+" · from",value=float(xr[0]),key=key+"_"+kind+"_xmin")
        xmax=a.number_input(spec.x_label+" · to",value=float(xr[1]),key=key+"_"+kind+"_xmax")
        ymin=b.number_input(spec.y_label+" · from",value=float(yr[0]),key=key+"_"+kind+"_ymin")
        ymax=b.number_input(spec.y_label+" · to",value=float(yr[1]),key=key+"_"+kind+"_ymax")
        n=st.select_slider("Grid resolution per axis",options=[11,21,31,41,61],value=31,key=key+"_resolution")
    percent=st.radio("Result unit",["Hours [h]","Share of valid hours [%]"],horizontal=True,key=key+"_unit").startswith("Share")
    if xmin>=xmax or ymin>=ymax:
        st.warning("Each parameter range must have a positive width.")
        return
    x=np.linspace(xmin,xmax,n);y=np.linspace(ymin,ymax,n)
    try:render(*figure(df,kind,x,y,fixed=p,reference=ref,percentage=percent))
    except (ValueError,KeyError) as exc:st.info(str(exc))


def geometry_panel(df,render,*,geometry,albedo,key):
    from .threshold_sensitivity import shading_geometry_figure
    st.caption("Sweep the overhang and equal left/right fin depths. Aperture size and façade azimuth remain fixed.")
    with st.expander("Geometry ranges",expanded=False):
        a,b=st.columns(2)
        xmax=a.number_input("Maximum overhang depth [m]",min_value=.1,max_value=10.,value=max(2.,float(geometry["overhang"])),step=.1,key=key+"_x")
        ymax=b.number_input("Maximum depth of each fin [m]",min_value=.1,max_value=10.,value=max(2.,float(geometry["left_fin"]),float(geometry["right_fin"])),step=.1,key=key+"_y")
        n=st.select_slider("Grid resolution per axis",options=[5,11,21,31],value=11,key=key+"_n")
    percent=st.radio("Result unit",["Intercepted direct irradiation [kWh/m²]","Share of incident direct irradiation [%]"],horizontal=True,key=key+"_unit").startswith("Share")
    try:render(*shading_geometry_figure(df,np.linspace(0,xmax,n),np.linspace(0,ymax,n),geometry=geometry,albedo=albedo,percentage=percent))
    except ValueError as exc:st.info(str(exc))
