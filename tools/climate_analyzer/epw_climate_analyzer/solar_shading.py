"""P2 direct-beam shading of one rectangular vertical aperture.

Opaque horizontal overhang and vertical side fins begin at the aperture edges.
No wall thickness, diffuse obstruction or ground-reflection reduction is implied.
Area fraction is evaluated in closed form by integrating the two disjoint ray-exit regions of the aperture.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .chart_theme import SHADING_IRRADIATION_COLORS

def _shading_components(azimuth,elevation,*,facade=180.,width=2.,height=1.5,
                    overhang=0.,left_fin=0.,right_fin=0.):
    """Exact area for edge-attached, zero-thickness opaque devices.

    Use distances u from the sunward side and v from the top. A ray
    reaches the top first when u >= abs(lateral)/vertical * v;
    otherwise it reaches the sunward fin first. The two regions are
    disjoint except for their common edge (zero area), so their exact
    areas sum without overlap or double counting. Evaluate in normalized
    aperture coordinates to avoid cancellation near full shading.
    Non-front-facing and below-horizon directions return zero; missing
    or nonphysical elevation returns NaN. No spatial grid is used.
    """
    if not np.isfinite([facade,width,height,overhang,left_fin,right_fin]).all() or width<=0 or height<=0 or min(overhang,left_fin,right_fin)<0:
        raise ValueError("Invalid aperture or device dimensions.")
    az,el=np.broadcast_arrays(np.asarray(azimuth,dtype=float),np.asarray(elevation,dtype=float))
    valid=np.isfinite(az)&np.isfinite(el)&(el>=-90)&(el<=90)
    # Avoid trigonometric warnings for invalid inputs; preserve NaN outputs.
    rel=np.deg2rad(np.where(valid,az,0.)-facade)
    beta=np.deg2rad(np.where(valid,el,0.))
    normal=np.cos(beta)*np.cos(rel)
    lateral=np.cos(beta)*np.sin(rel)
    vertical=np.sin(beta)
    out=np.full(az.shape,np.nan,dtype=float)
    out[valid]=0.
    components=np.repeat(out[...,None],3,axis=-1)
    # Retain the previous grazing-incidence cutoff for numerical stability.
    front=valid&(normal>1e-10)&(el>0)
    if not np.any(front) or max(overhang,left_fin,right_fin)==0:
        return out,components,front
    n=normal[front]
    l=np.abs(lateral[front])/width
    z=vertical[front]/height
    sunward_depth=np.where(lateral[front]>=0,right_fin,left_fin)

    # Ray parameter at the first opposite aperture boundary, in local
    # coordinates. A due-normal azimuth has no sunward-side exit.
    t_side=np.divide(1.,l,out=np.full_like(l,np.inf),where=l>0)
    t_top=1./z
    t_limit=np.minimum(t_top,t_side)

    # Top exit: integrate remaining available width over the vertical strip.
    t_o=np.minimum(t_limit,overhang/n)
    u_o=l*t_o
    v_o=z*t_o
    a_o=v_o*(1.-.5*u_o)

    # Side exit: integrate remaining available height over the lateral strip.
    t_f=np.minimum(t_limit,sunward_depth/n)
    u_f=l*t_f
    v_f=z*t_f
    a_f=u_f*(1.-.5*v_f)

    fraction=np.clip(a_o+a_f,0.,1.)
    # Remove roundoff only at the exact full-shading limit. Preserve tiny
    # positive physical shade fractions for shallow devices or low sun.
    fraction=np.where(np.abs(fraction-1.)<=8*np.finfo(float).eps,1.,fraction)
    out[front]=fraction
    # Disjoint first-hit regions: a ray is attributed to only one device.
    # Allocate any full-shade roundoff correction to the larger contribution.
    correction=fraction-(a_o+a_f)
    top=a_o>=a_f
    a_o=a_o+np.where(top,correction,0.)
    a_f=a_f+np.where(top,0.,correction)
    right=lateral[front]>=0
    components[front]=np.column_stack((a_o,np.where(right,0.,a_f),np.where(right,a_f,0.)))
    return out,components,front


DEVICES=("Overhang","Left fin","Right fin")
TOTAL_DEVICE="All devices"


def shaded_fraction(azimuth,elevation,**geometry):
    """Exact total shaded aperture fraction; unchanged direct-only semantics."""
    return _shading_components(azimuth,elevation,**geometry)[0]


def shading_ledger(df,*,albedo=None,**geometry):
    from .runtime_module_guard import ensure_current_solar_runtime
    facade=geometry.get("facade",180.)
    poa=ensure_current_solar_runtime().surface_irradiance_components(df,90.,facade,albedo=albedo)
    elevation=90-pd.to_numeric(df["solar_apparent_zenith_deg"],errors="coerce")
    fraction,components,_=_shading_components(df["solar_azimuth_deg"],elevation,**geometry)
    direct=poa["poa_direct_wh_m2"]
    lost=direct*fraction
    result=pd.DataFrame({"Unshaded total":poa["poa_global_wh_m2"],
                         "Shaded total (direct-only)":poa["poa_global_wh_m2"]-lost,
                         "Intercepted direct":lost,"Unshaded direct":direct,
                         "Remaining direct":direct-lost,"Shaded area fraction":fraction},index=df.index)
    for i,device in enumerate(DEVICES):
        result[device+" area fraction"]=components[:,i]
        result[device+" intercepted direct"]=direct*components[:,i]
    return result

def monthly_shading_figure(table, labels):
    """Visualize the direct-only irradiation ledger, already in kWh/m²."""
    fig=go.Figure()
    for name in ("Shaded total (direct-only)", "Intercepted direct"):
        fig.add_bar(x=labels,y=table[name],name=name,marker_color=SHADING_IRRADIATION_COLORS[name])
    fig.add_scatter(x=labels,y=table["Unshaded total"],name="Unshaded total",
                    mode="lines+markers",line=dict(dash="dash",color=SHADING_IRRADIATION_COLORS["Unshaded total"]),connectgaps=False)
    fig.update_layout(template="plotly_white",
                      title="Monthly façade irradiation and intercepted direct beam",
                      barmode="stack",xaxis_title="Period",
                      yaxis_title="Irradiation [kWh/m²]")
    return fig


MASK_CLASSES=(
    ("0% · unshaded", "#CBD5E1"),
    (">0–<25% · low shade", "#B0B0B0"),
    ("25–<50% · partial shade", "#808080"),
    ("50–<100% · strong shade", "#454545"),
    ("100% · full shade", "#171717"),
)
MASK_EXPLANATION=(
    "The mask maps analytically calculated shading of the window for each direct-sun "
    "azimuth and elevation. Pale open circles indicate an exposed aperture; "
    "darker circles indicate greater shaded area. The diagram shows sunward "
    "façade directions, with monthly sun paths providing seasonal orientation. "
    "Hover to inspect the shaded area at each solar position."
)

def overlay_shading_mask(fig,*,inverted=False,technical=False,**geometry):
    # A fixed angular display grid; each direction is evaluated analytically.
    # Include only directions incident on the front of the selected vertical plane.
    # Keep r = zenith in both orientations; the reversed axis is managed by the
    # canonical polar layout, not by reversing the data a second time.
    az,el=np.meshgrid(np.arange(0,360,4.),np.arange(2,90,3.))
    f=shaded_fraction(az,el,**geometry)
    facade=geometry.get("facade",180.)
    front=np.cos(np.deg2rad(az-facade))*np.cos(np.deg2rad(el))>1e-10
    groups=(f==0,(f>0)&(f<.25),(f>=.25)&(f<.5),(f>=.5)&(f<1),f==1)
    for index,((label,color),group) in enumerate(zip(MASK_CLASSES,groups)):
        keep=front&group&np.isfinite(f)
        marker=dict(color=color, size=4 if index==0 else 6,
                    opacity=.5 if index==0 else .82,
                    symbol="circle-open" if index==0 else "circle")
        values=np.column_stack([az[keep],el[keep],100*f[keep]])
        args=dict(mode="markers",marker=marker,name=label,
                  legendgroup="direct-shading-"+str(index),showlegend=True,
                  customdata=values,meta={"direct_sun_shading_mask":True},
                  hovertemplate="Solar azimuth %{customdata[0]:.0f}°<br>Solar elevation %{customdata[1]:.0f}°<br>Window shaded area %{customdata[2]:.1f}%<extra></extra>")
        # An empty class still has a legend entry, without adding a dummy
        # physical observation, by using an explicit null coordinate.
        if not keep.any():
            args["customdata"]=[[None,None,None]]
        x=az[keep] if keep.any() else [None]
        y=el[keep] if keep.any() else [None]
        if technical:
            trace=go.Scattergl(x=x,y=y,**args)
        else:
            trace=go.Scatterpolargl(theta=x,r=90-el[keep] if keep.any() else [None],**args)
        fig.add_trace(trace)
    return fig

def thermal_overlay(fig,df,mode,*,cold=18.,warm=26.,technical=False):
    temp=pd.to_numeric(df["dry_bulb_temperature_c"],errors="coerce")
    az=pd.to_numeric(df["solar_azimuth_deg"],errors="coerce")
    el=pd.to_numeric(df["solar_elevation_deg"],errors="coerce")
    valid=temp.notna()&az.notna()&el.gt(0)
    if mode=="Outdoor temperature":
        marker=dict(color=temp[valid],colorscale="RdBu_r",size=5,opacity=.8,
                    showscale=True,colorbar=dict(title="Temperature [°C]"))
        groups=[("Outdoor temperature",valid,marker)]
    else:
        groups=[]
        for label,mask,color in (("Cold conditions",temp<cold,"#2563EB"),
                                 ("Intermediate conditions",(temp>=cold)&(temp<=warm),"#9CA3AF"),
                                 ("Hot conditions",temp>warm,"#DC2626")):
            groups.append((label,valid&mask,dict(color=color,size=5,opacity=.65)))
    for name,mask,marker in groups:
        if mode=="Outdoor temperature": mask=valid
        args=dict(mode="markers",marker=marker,name=name,customdata=temp[mask],
                  hovertemplate="%{customdata:.1f} °C<extra>%{fullData.name}</extra>")
        trace=go.Scattergl(x=az[mask],y=el[mask],**args) if technical else go.Scatterpolargl(theta=az[mask],r=90-el[mask],**args)
        fig.add_trace(trace)
    return fig
