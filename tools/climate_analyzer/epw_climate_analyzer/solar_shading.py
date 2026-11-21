"""P2 direct-beam shading of one rectangular vertical aperture.

Opaque horizontal overhang and vertical side fins begin at the aperture edges.
No wall thickness, diffuse obstruction or ground-reflection reduction is implied.
Area fraction is calculated by deterministic midpoint quadrature.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go

def shaded_fraction(azimuth,elevation,*,facade=180.,width=2.,height=1.5,
                    overhang=0.,left_fin=0.,right_fin=0.,samples=24):
    if not np.isfinite([facade,width,height,overhang,left_fin,right_fin]).all() or width<=0 or height<=0 or min(overhang,left_fin,right_fin)<0 or not 1<=samples<=100:
        raise ValueError("Invalid aperture or device dimensions.")
    az=np.deg2rad(np.asarray(azimuth,dtype=float)-facade)
    el=np.deg2rad(np.asarray(elevation,dtype=float))
    az,el=np.broadcast_arrays(az,el)
    shape=az.shape
    normal=(np.cos(el)*np.cos(az)).ravel()
    lateral=(np.cos(el)*np.sin(az)).ravel()
    vertical=np.sin(el).ravel()
    out=np.full(len(normal),np.nan)
    valid=np.isfinite(normal)&np.isfinite(lateral)&np.isfinite(vertical)
    out[valid]=0.
    front=valid&(normal>1e-10)&(vertical>0)
    x,y=np.meshgrid((np.arange(samples)+.5)*width/samples-width/2,
                    (np.arange(samples)+.5)*height/samples)
    x=x.ravel()[None,:]; y=y.ravel()[None,:]
    for start in range(0,len(normal),256):
        idx=np.arange(start,min(start+256,len(normal)))
        idx=idx[front[idx]]
        if not len(idx): continue
        n=normal[idx,None]; l=lateral[idx,None]; z=vertical[idx,None]
        blocked=np.zeros((len(idx),samples*samples),dtype=bool)
        if overhang>0:
            d=(height-y)/z
            blocked|=(d*n<=overhang)&(np.abs(x+d*l)<=width/2)
        for depth,sign in ((left_fin,-1),(right_fin,1)):
            if depth<=0:continue
            side=sign*l>1e-10
            d=np.divide(sign*width/2-x,l,out=np.full_like(blocked,np.inf,dtype=float),where=side)
            with np.errstate(invalid="ignore"):
                blocked|=side&(d>=0)&(d*n<=depth)&(y+d*z<=height)
        out[idx]=blocked.mean(axis=1)
    return out.reshape(shape)

def shading_ledger(df,*,albedo=None,**geometry):
    from .runtime_module_guard import ensure_current_solar_runtime
    facade=geometry.get("facade",180.)
    poa=ensure_current_solar_runtime().surface_irradiance_components(df,90.,facade,albedo=albedo)
    elevation=90-pd.to_numeric(df["solar_apparent_zenith_deg"],errors="coerce")
    fraction=shaded_fraction(df["solar_azimuth_deg"],elevation,**geometry)
    direct=poa["poa_direct_wh_m2"]
    lost=direct*fraction
    return pd.DataFrame({"Unshaded total":poa["poa_global_wh_m2"],
                         "Shaded total (direct-only)":poa["poa_global_wh_m2"]-lost,
                         "Intercepted direct":lost,"Unshaded direct":direct,
                         "Remaining direct":direct-lost,"Shaded area fraction":fraction},index=df.index)

MASK_CLASSES=(
    ("0% · unshaded", "#CBD5E1"),
    (">0–<25% · low shade", "#B0B0B0"),
    ("25–<50% · partial shade", "#808080"),
    ("50–<100% · strong shade", "#454545"),
    ("100% · full shade", "#171717"),
)
MASK_EXPLANATION=(
    "The mask shows the fraction of the window opening shaded by its overhang and fins "
    "for each possible direct-sun direction. Pale open circles mean no shading from the devices; "
    "darker points mean a larger shaded fraction. Directions behind the façade are omitted "
    "because they cannot directly illuminate the front of the window. Read the mask together "
    "with the monthly sun paths; hover for azimuth, elevation and the exact sampled shaded area. "
    "This is geometric direct-beam shading only, independent of weather, diffuse light and indoor heat gains."
)

def overlay_shading_mask(fig,*,inverted=False,technical=False,**geometry):
    # A fixed angular sampling grid, independent of the climate observations.
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
