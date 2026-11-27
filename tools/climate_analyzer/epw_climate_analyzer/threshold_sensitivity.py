"""R2.21 C: bounded exact two-parameter climate screening maps.

A two-dimensional cumulative count replaces an observation x scenario cube.
Each observation is assigned to the first qualifying threshold index on each
axis; prefix sums recover every inclusive/strict comparison exactly.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .aggregations import native_interval_hours
from .p3_comfort import numeric, T, W, V
from .decisions import natural_ventilation_condition, night_flushing_reference
from .chart_theme import NV_SUITABILITY_COLORSCALE

G="global_horizontal_radiation_wh_m2"
H="moist_air_enthalpy_kj_kg"
VP="vapor_pressure_pa"
MAX_AXIS=81

@dataclass(frozen=True)
class Spec:
    title: str
    x_label: str
    y_label: str
    x_range: tuple
    y_range: tuple
    reference: tuple
    result: str
    fields: tuple

SPECS={
    "nv_temperature_moisture":Spec("Natural ventilation · temperature and moisture limits","Maximum outdoor temperature [°C]","Maximum humidity ratio [g/kg dry air]",(20.,34.),(5.,20.),(26.,9.),"Suitable",(T,W)),
    "nv_temperature_range":Spec("Natural ventilation · temperature range","Minimum outdoor temperature [°C]","Maximum outdoor temperature [°C]",(8.,26.),(20.,36.),(16.,26.),"Suitable",(T,W)),
    "nv_wind_range":Spec("Natural ventilation · wind-speed range","Minimum wind speed [m/s]","Maximum wind speed [m/s]",(0.,3.),(2.,12.),(.5,6.),"Suitable",(T,W,V)),
    "night":Spec("Night flushing · hot-day and night limits","Preceding hot-day threshold [°C]","Maximum night temperature [°C]",(20.,36.),(12.,28.),(26.,20.),"Suitable night",(T,)),
    "solar":Spec("Solar protection · climatic thresholds","Minimum outdoor temperature [°C]","Minimum GHI intensity [W/m²]",(16.,34.),(0.,800.),(24.,250.),"Solar-protection",(T,G)),
    "neutral":Spec("Passive design · neutral-temperature window","Heating threshold [°C]","Cooling threshold [°C]",(12.,24.),(20.,34.),(18.,26.),"Neutral-temperature",(T,)),
    "economizer":Spec("Economizer · temperature and enthalpy limits","Maximum outdoor temperature [°C]","Return-air enthalpy reference [kJ/kg dry air]",(16.,32.),(25.,80.),(24.,50.),"Eligible",(T,H)),
    "surface":Spec("Surface moisture · temperature and RH limits","Surface temperature [°C]","Surface RH threshold [%]",(0.,25.),(60.,100.),(12.,80.),"Surface moisture-risk",(VP,)),
}

def _axis(values):
    a=np.asarray(values,dtype=float)
    if a.ndim!=1 or not 1<=len(a)<=MAX_AXIS or not np.isfinite(a).all() or np.any(np.diff(a)<=0):
        raise ValueError("Threshold axes must be finite, strictly increasing and contain at most 81 values.")
    return a

def _admit(df):
    if not isinstance(df.index,pd.DatetimeIndex) or df.index.has_duplicates or df.empty:
        raise ValueError("Sensitivity requires nonempty, uniquely dated source observations.")
    if str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly":
        raise ValueError("Sensitivity requires hourly or finer climate records.")
    dt=native_interval_hours(df)
    if not np.isfinite(dt) or not 0<dt<=1:raise ValueError("Sensitivity requires hourly or finer source cadence.")
    return dt

def _first(values, thresholds, comparison):
    # Transform decreasing eligibility axes into increasing eligibility axes.
    reverse=comparison in (">=",">")
    if comparison not in ("<=","<",">=",">"):raise ValueError("Unsupported threshold comparison.")
    thresholds=-thresholds[::-1] if reverse else thresholds
    values=-values if reverse else values
    return np.searchsorted(thresholds,values,side="right" if comparison in ("<",">") else "left"),reverse

def joint_counts(a,b,x,y,*,x_op="<=",y_op="<="):
    """Exact counts for every x/y threshold pair; finite paired inputs only."""
    x,y=_axis(x),_axis(y)
    a,b=np.asarray(a,dtype=float),np.asarray(b,dtype=float)
    if a.shape!=b.shape or a.ndim!=1:raise ValueError("Paired one-dimensional observations are required.")
    valid=np.isfinite(a)&np.isfinite(b)
    ix,rx=_first(a[valid],x,x_op);iy,ry=_first(b[valid],y,y_op)
    keep=(ix<len(x))&(iy<len(y))
    counts=np.bincount(iy[keep]*len(x)+ix[keep],minlength=len(x)*len(y)).reshape(len(y),len(x))
    z=counts.cumsum(axis=0).cumsum(axis=1)
    if rx:z=z[:,::-1]
    if ry:z=z[::-1,:]
    return z.astype(float)

def _valid(*series):
    out=np.ones(len(series[0]),dtype=bool)
    for s in series:out &= np.isfinite(np.asarray(s,dtype=float))
    return out

def _schedule(df,p):
    if not p.get("occupied_only",False):return np.ones(len(df),dtype=bool)
    h=df["hour_of_day"].to_numpy()
    a,b=p.get("occupied_start_hour",8),p.get("occupied_end_hour",18)
    keep=(h>=a)&(h<=b) if a<=b else (h>=a)|(h<=b)
    if p.get("weekdays_only",False):keep &= df.index.weekday<5
    return keep

def calculate(df,kind,x,y,*,fixed=None):
    """Return exact hours grid and valid denominator in physical hours."""
    dt=_admit(df);x,y=_axis(x),_axis(y)
    p=dict(fixed or {});spec=SPECS[kind]
    if any(c not in df for c in spec.fields):raise ValueError("Required source quantities are unavailable.")
    t=numeric(df,T);w=numeric(df,W);v=numeric(df,V)
    invalid=None
    if kind.startswith("nv_"):
        varying={"nv_temperature_moisture":("t_max_c","d_max_g_kg"),"nv_temperature_range":("t_min_c","t_max_c"),"nv_wind_range":("wind_min_m_s","wind_max_m_s")}[kind]
        args={"t_min_c":16.,"t_max_c":26.,"d_max_g_kg":9.,"wind_min_m_s":None,"wind_max_m_s":None,
              "occupied_only":False,"occupied_start_hour":8,"occupied_end_hour":18,"weekdays_only":False}
        args.update(p)
        valid=_valid(t,w)&(w.to_numpy()>=0)&_schedule(df,args)
        if kind=="nv_wind_range" or args["wind_min_m_s"] is not None or args["wind_max_m_s"] is not None:
            valid &= _valid(v)&(v.to_numpy()>=0)
        relax={"t_min_c":-np.inf,"t_max_c":np.inf,"d_max_g_kg":np.inf,"wind_min_m_s":None,"wind_max_m_s":None}
        for name in varying:args[name]=relax[name]
        keep=valid&natural_ventilation_condition(df,**args).to_numpy(dtype=bool)
        if kind=="nv_temperature_moisture":
            a,b,ops=t,w,("<=","<=")
            invalid=(x[None,:]<args["t_min_c"]) | (y[:,None]<0)
        elif kind=="nv_temperature_range":
            a,b,ops=t,t,(">=","<=");invalid=x[None,:]>y[:,None]
        else:
            a,b,ops=v,v,(">=","<=");invalid=(x[None,:]>y[:,None])|(x[None,:]<0)|(y[:,None]<0)
    elif kind=="night":
        is_night,hot=night_flushing_reference(df)
        valid=_valid(t,hot)&is_night.to_numpy(dtype=bool)
        keep=valid;a,b,ops=hot,t,(">=","<=")
    elif kind=="solar":
        ghi=numeric(df,G)/dt
        valid=_valid(t,ghi)&(ghi.to_numpy()>=0)
        keep=valid;a,b,ops=t,ghi,(">=",">=")
        invalid=np.broadcast_to(y[:,None]<0,(len(y),len(x)))
    elif kind=="neutral":
        valid=_valid(t);keep=valid;a,b,ops=t,t,(">=","<=")
        invalid=x[None,:]>y[:,None]
    elif kind=="economizer":
        h=numeric(df,H);valid=_valid(t,h)
        low=float(p.get("t_min_c",5.))
        keep=valid&(t.to_numpy()>=low);a,b,ops=t,h,("<=","<")
        invalid=np.broadcast_to(x[None,:]<low,(len(y),len(x)))
    elif kind=="surface":
        from .psychrometrics import psychrolib
        pv=numeric(df,VP).to_numpy(dtype=float)
        valid=np.isfinite(pv)&(pv>=0)
        if np.any((x<-80)|(x>80)) or np.any((y<=0)|(y>100)):
            raise ValueError("Surface temperature range: −80 to 80 °C; RH threshold: >0 to 100%.")
        # RH_surface = p_v / p_sat(T_surface); no clipping at saturation.
        # ASHRAE saturation pressure is the existing PsychroLib convention.
        sat=np.asarray([float(psychrolib.GetSatVapPres(float(q))) for q in x])
        sorted_p=np.sort(pv[valid])
        threshold=y[:,None]*sat[None,:]/100
        z=(len(sorted_p)-np.searchsorted(sorted_p,threshold,side="left")).astype(float)*dt
        if not valid.any():raise ValueError("No valid coincident source observations.")
        return z,float(valid.sum()*dt)
    else:raise ValueError("Unknown sensitivity analysis.")
    if not valid.any():raise ValueError("No valid coincident source observations in the screening scope.")
    z=joint_counts(np.asarray(a)[keep],np.asarray(b)[keep],x,y,x_op=ops[0],y_op=ops[1])*dt
    if invalid is not None:z=np.where(invalid,np.nan,z)
    return z,float(valid.sum()*dt)

def figure(df,kind,x,y,*,fixed=None,reference=None,percentage=False):
    spec=SPECS[kind];x,y=_axis(x),_axis(y)
    hours,denom=calculate(df,kind,x,y,fixed=fixed)
    values=hours/denom*100 if percentage else hours
    unit="%" if percentage else "h"
    f=go.Figure(go.Heatmap(x=x,y=y,z=values,customdata=hours,hoverongaps=False,
        colorscale="Oranges" if kind=="surface" else NV_SUITABILITY_COLORSCALE,zmin=0,zmax=100 if percentage else denom,
        colorbar=dict(title=f"{spec.result} [{unit}]"),
        hovertemplate="%{x:.2f} · %{y:.2f}<br>"+spec.result+": %{z:,.2f} "+unit+"<br>Eligible: %{customdata:,.1f} h<extra></extra>",
        meta={"heatmap_semantics":"continuous","heatmap_quantity":"threshold sensitivity"}))
    ref=tuple(reference or spec.reference)
    ref_hours=float(calculate(df,kind,[ref[0]],[ref[1]],fixed=fixed)[0][0,0])
    if np.isfinite(ref_hours) and x[0]<=ref[0]<=x[-1] and y[0]<=ref[1]<=y[-1]:
        f.add_scatter(x=[ref[0]],y=[ref[1]],mode="markers",name="Active reference",
            marker=dict(symbol="circle-open",size=13,color="#202020",line=dict(width=2)),
            hovertemplate="Active reference<extra></extra>")
    f.update_layout(title=spec.title,xaxis_title=spec.x_label,yaxis_title=spec.y_label,
        template="plotly_white",height=520,plot_bgcolor="#E5E7EB",
        meta={"layout_kind":"threshold_sensitivity","sensitivity_kind":kind})
    finite=hours[np.isfinite(hours)]
    note=(f"Each cell evaluates {spec.result.lower()} hours at its exact threshold pair. "
          f"The common denominator is {denom:,.1f} valid observation hours within the active screening scope. ")
    if finite.size:note+=f"Across admissible pairs the result ranges from {finite.min():,.1f} to {finite.max():,.1f} h. "
    if np.isfinite(ref_hours):note+=f"The active reference ({ref[0]:g}, {ref[1]:g}) yields {ref_hours:,.1f} h ({100*ref_hours/denom:.1f}%). "
    if kind.startswith("nv_"):
        note+="The other ventilation limits and occupancy schedule remain fixed. "
        if kind=="nv_wind_range" and (fixed or {}).get("wind_min_m_s") is None and (fixed or {}).get("wind_max_m_s") is None:
            note+="The reference wind limits are the default candidate limits; the active ventilation screen has no wind-speed restriction. "
    if kind=="night":note+="Only night hours with a completely observed reference day enter the denominator. "
    if kind=="surface":note+="Surface relative humidity follows outdoor vapour pressure and the specified surface saturation pressure; RH at or above the threshold is counted. "
    if kind=="solar":note+="GHI interval energy is converted to mean intensity using the declared source cadence. "
    if kind=="economizer":note+="The fixed minimum outdoor temperature and strict enthalpy comparison are retained. "
    if kind=="neutral":note+="The neutral interval includes both temperature boundaries and describes the temperature-only band between heating and cooling thresholds. "
    note+="Grey cells indicate inadmissible threshold combinations. Hours quantify climatic opportunities or exposure under the stated screening assumptions."
    return f,note


def shading_geometry_figure(df,x,y,*,geometry,albedo=None,percentage=False):
    """Sweep overhang and symmetric fin depths, holding aperture/orientation fixed.

    Reuse one direct-beam plane-of-array field. The analytical aperture-area
    kernel remains identical to the existing shading ledger. No spatial
    sampling, per-candidate irradiance reconstruction or scenario cube.
    """
    dt=_admit(df);x,y=_axis(x),_axis(y)
    if len(x)>31 or len(y)>31 or np.any(x<0) or np.any(y<0):
        raise ValueError("Geometry sweep requires nonnegative depths and at most 31 values per axis.")
    from .solar_shading import shading_ledger, shaded_fraction
    az=numeric(df,"solar_azimuth_deg").to_numpy(dtype=float)
    el=90-numeric(df,"solar_apparent_zenith_deg").to_numpy(dtype=float)
    base=dict(geometry)
    ledger=shading_ledger(df,albedo=albedo,**base)
    direct=ledger["Unshaded direct"].to_numpy(dtype=float)
    valid=np.isfinite(direct)&(direct>=0)&np.isfinite(az)&np.isfinite(el)&(el>=-90)&(el<=90)
    if not valid.any():raise ValueError("No complete coincident direct-beam and solar-position observations.")
    observed_hours=float(valid.sum()*dt)
    az,el,direct=az[valid],el[valid],direct[valid]
    total=float(direct.sum()/1000.)
    # Bound total evaluations; multi-year archives can reduce grid resolution.
    if len(direct)*len(x)*len(y)>30_000_000:
        raise ValueError("Reduce geometry grid resolution or select a shorter observation period.")
    if percentage and total<=0:raise ValueError("No incident direct irradiation for percentage reduction.")
    matrix=np.empty((len(y),len(x)))
    for i,fin in enumerate(y):
        for j,overhang in enumerate(x):
            candidate={**base,"overhang":float(overhang),"left_fin":float(fin),"right_fin":float(fin)}
            matrix[i,j]=np.dot(direct,shaded_fraction(az,el,**candidate))/1000.
    z=100*matrix/total if percentage else matrix
    unit="%" if percentage else "kWh/m²"
    f=go.Figure(go.Heatmap(x=x,y=y,z=z,customdata=matrix,colorscale="YlOrBr",zmin=0,
        zmax=100 if percentage else max(total,1e-12),hoverongaps=False,
        colorbar=dict(title=f"Intercepted direct [{unit}]"),
        hovertemplate="Overhang %{x:.2f} m · each fin %{y:.2f} m<br>Intercepted direct: %{z:,.2f} "+unit+"<extra></extra>",
        meta={"heatmap_semantics":"continuous","heatmap_quantity":"intercepted direct irradiation"}))
    ref=base.get("overhang",0.),base.get("left_fin",0.)
    symmetric=np.isclose(ref[1],base.get("right_fin",0.))
    if symmetric and x[0]<=ref[0]<=x[-1] and y[0]<=ref[1]<=y[-1]:
        f.add_scatter(x=[ref[0]],y=[ref[1]],mode="markers",name="Active reference",
            marker=dict(symbol="circle-open",size=13,color="#202020",line=dict(width=2)))
    f.update_layout(title="Shading geometry · overhang and symmetric fins",
        xaxis_title="Overhang depth [m]",yaxis_title="Depth of each side fin [m]",
        template="plotly_white",height=520,meta={"layout_kind":"threshold_sensitivity"})
    actual=float(ledger["Intercepted direct"].to_numpy(dtype=float)[valid].sum()/1000.)
    note=(f"The selected façade and aperture receive {total:,.2f} kWh/m² of direct irradiation across "
          f"{observed_hours:,.1f} valid observation hours. The parameter grid intercepts "
          f"{matrix.min():,.2f}–{matrix.max():,.2f} kWh/m². "
          f"The active geometry intercepts {actual:,.2f} kWh/m². "
          "Each cell uses equal left and right fin depths and the specified overhang; aperture dimensions and façade azimuth remain fixed. "
          "Percentages refer to incident direct-beam irradiation. Diffuse and ground-reflected components retain the existing direct-only shading model.")
    if not symmetric:note+=" The active geometry has unequal fin depths and is outside this symmetric-fin parameter family."
    return f,note
