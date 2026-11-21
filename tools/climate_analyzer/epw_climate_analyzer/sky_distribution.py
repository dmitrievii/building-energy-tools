"""Directional cumulative horizontal irradiation from a hemispherical patch grid.

Tregenza MF1 / Reinhart MF2 have 145 / 577 sky patches, no ground patch.
Diffuse relative radiance is normalized against exact projected patch solid
angles, so horizontal diffuse energy closes independently at each interval.
Direct energy is deposited at the actual solar bearing using its actual cosine.
Perez (1993) is a research candidate pending independent Radiance comparison.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .aggregations import native_interval_hours

DNI="direct_normal_radiation_wh_m2"
DHI="diffuse_horizontal_radiation_wh_m2"
Z="solar_apparent_zenith_deg"
AZ="solar_azimuth_deg"
# Numerical coefficients from Perez, Seals and Michalsky (1993), Table 1,
# with published erratum; cross-checked against Radiance gendaymtx.
COEFFICIENTS=np.array([
[1.3525,-.2576,-.2690,-1.4366,-.7670,.0007,1.2734,-.1233,2.8,.6004,1.2375,1.,1.8734,.6297,.9738,.2809,.0356,-.1246,-.5718,.9938],
[-1.2219,-.773,1.4148,1.1016,-.2054,.0367,-3.9128,.9156,6.975,.1774,6.4477,-.1239,-1.5798,-.5081,-1.7812,.108,.2624,.0672,-.219,-.4285],
[-1.1,-.2515,.8952,.0156,.2782,-.1812,-4.5,1.1766,24.7219,-13.0812,-37.7,34.8438,-5.,1.5218,3.9229,-2.6204,-.0156,.1597,.4199,-.5562],
[-.5484,-.6654,-.2672,.7117,.7234,-.6219,-5.6812,2.6297,33.3389,-18.3,-62.25,52.0781,-3.5,.0016,1.1477,.1062,.4659,-.3296,-.0876,-.0329],
[-.6,-.3566,-2.5,2.325,.2937,.0496,-5.6812,1.8415,21.,-4.7656,-21.5906,7.2492,-3.5,-.1554,1.4062,.3988,.0032,.0766,-.0656,-.1294],
[-1.0156,-.367,1.0078,1.4051,.2875,-.5328,-3.85,3.375,14.,-.9999,-7.1406,7.5469,-3.4,-.1078,-1.075,1.5702,-.0672,.4016,.3017,-.4844],
[-1.,.0211,.5025,-.5119,-.3,.1922,.7023,-1.6317,19.,-5.,1.2438,-1.9094,-4.,.025,.3844,.2656,1.0468,-.3788,-2.4517,1.4656],
[-1.05,.0289,.426,.359,-.325,.1156,.7781,.0025,31.0625,-14.5,-46.1148,55.375,-7.2312,.405,13.35,.6234,1.5,-.6426,1.8564,.5636]
]).reshape(8,5,4)
BANDS=[30,30,24,24,18,12,6]

def patches(mf=1):
    if mf not in (1,2): raise ValueError("MF must be 1 or 2")
    step=90/(7*mf+.5)
    rows=[]
    for ring in range(7*mf):
        n=BANDS[ring//mf]*mf; da=360/n
        for j in range(n):
            rows.append((ring*step,(ring+1)*step,j*da,da))
    rows.append((7*mf*step,90.,0.,360.))
    p=pd.DataFrame(rows,columns=["lower","upper","azimuth","width"])
    p["elevation"]=(p.lower+p.upper)/2
    p.loc[p.width==360,"elevation"]=90.
    lo=np.deg2rad(p.lower); hi=np.deg2rad(p.upper); da=np.deg2rad(p.width)
    p["solid_angle"]=da*(np.sin(hi)-np.sin(lo))
    p["projected_angle"]=.5*da*(np.sin(hi)**2-np.sin(lo)**2)
    return p

def sun_bins(az,el,mf):
    step=90/(7*mf+.5)
    ring=np.minimum(np.floor(el/step).astype(int),7*mf)
    counts=np.r_[np.repeat(np.array(BANDS)*mf,mf),1]
    offset=np.r_[0,np.cumsum(counts)[:-1]]
    n=counts[ring]
    j=(np.floor((az%360)/(360/n)+.5).astype(int)%n)
    return offset[ring]+j

def perez_weights(zenith,azimuth,dni_w,dhi_w,extra,patches):
    import pvlib
    z=np.deg2rad(zenith)
    epsilon=1+(dni_w/np.maximum(dhi_w,1e-9))/(1+1.041*z**3)
    cat=np.searchsorted([1.065,1.23,1.5,1.95,2.8,4.5,6.2],epsilon,side="right")
    delta=dhi_w*np.asarray(pvlib.atmosphere.get_relative_airmass(zenith))/extra
    delta=np.clip(delta,.01,.6)
    delta=np.where((epsilon>1.065)&(epsilon<2.8),np.maximum(delta,.2),delta)
    c=COEFFICIENTS[cat]
    params=c[:,:,0]+c[:,:,1]*z[:,None]+delta[:,None]*(c[:,:,2]+c[:,:,3]*z[:,None])
    overcast=cat==0
    if overcast.any():
        cc=c[overcast,2,:]; dd=c[overcast,3,:]; zz=z[overcast]; de=delta[overcast]
        params[overcast,2]=np.exp(np.maximum(de*(cc[:,0]+cc[:,1]*zz),0)**cc[:,2])-cc[:,3]
        params[overcast,3]=-np.exp(de*(dd[:,0]+dd[:,1]*zz))+dd[:,2]+de*dd[:,3]
    e=np.deg2rad(patches.elevation.to_numpy())[None,:]
    a=np.deg2rad(patches.azimuth.to_numpy())[None,:]
    cosgamma=np.clip(np.cos(z[:,None])*np.sin(e)+np.sin(z[:,None])*np.cos(e)*np.cos(a-np.deg2rad(azimuth)[:,None]),-1,1)
    gamma=np.arccos(cosgamma)
    A,B,C,D,E=(params[:,i,None] for i in range(5))
    luminance=(1+A*np.exp(np.clip(B/np.sin(e),-80,80)))*(1+C*np.exp(np.clip(D*gamma,-80,80))+E*cosgamma**2)
    weight=np.maximum(luminance,0)*patches.projected_angle.to_numpy()[None,:]
    total=weight.sum(axis=1,keepdims=True)
    if not np.isfinite(weight).all() or np.any(total<=0):
        raise ValueError("Perez model returned a nonphysical distribution; anisotropic result not admitted.")
    return weight/total

def available_quantities(df):
    good=lambda c:c in df and pd.to_numeric(df[c],errors="coerce").notna().any()
    if not all(good(c) for c in (Z,AZ)):return []
    return (["Diffuse"] if good(DHI) else [])+(["Direct"] if good(DNI) else [])+(["Total"] if good(DHI) and good(DNI) else [])

def cumulative_sky(df,*,mf=1,quantity="Total",model="Isotropic"):
    if model not in ("Isotropic","Perez 1993 (research)") or (quantity=="Direct" and model!="Isotropic"):
        raise ValueError("Unsupported sky model/component combination.")
    if quantity not in available_quantities(df):
        raise ValueError("Required radiation and solar position not available.")
    p=patches(mf)
    z=pd.to_numeric(df[Z],errors="coerce").to_numpy(float)
    a=pd.to_numeric(df[AZ],errors="coerce").to_numpy(float)
    valid=np.isfinite(z)&np.isfinite(a)&(z>=0)&(z<90)&(a>=0)&(a<=360)
    required=[]
    if quantity in ("Direct","Total") or model!="Isotropic":required.append(DNI)
    if quantity in ("Diffuse","Total"):required.append(DHI)
    for c in required:
        if c not in df:raise ValueError("Missing model input "+c)
        value=pd.to_numeric(df[c],errors="coerce").to_numpy(float)
        valid&=np.isfinite(value)&(value>=0)
    ii=np.flatnonzero(valid)
    if not len(ii):raise ValueError("No complete daylight intervals in the selected period.")
    z=z[ii];a=a[ii]; interval=native_interval_hours(df)
    p["direct_kwh_m2"]=0.;p["diffuse_kwh_m2"]=0.
    direct=np.zeros(len(p)); diffuse=np.zeros(len(p))
    if quantity in ("Direct","Total"):
        dni=pd.to_numeric(df[DNI],errors="coerce").to_numpy(float)[ii]
        direct=np.bincount(sun_bins(a,90-z,mf),weights=dni*np.cos(np.deg2rad(z))/1000,minlength=len(p))
    if quantity in ("Diffuse","Total"):
        dhi=pd.to_numeric(df[DHI],errors="coerce").to_numpy(float)[ii]
        if model=="Isotropic":
            diffuse=dhi.sum()/1000*p.projected_angle.to_numpy()/np.pi
        elif model=="Perez 1993 (research)":
            import pvlib
            dni=pd.to_numeric(df[DNI],errors="coerce").to_numpy(float)[ii]
            extra=np.asarray(pvlib.irradiance.get_extra_radiation(pd.DatetimeIndex(df.index[ii])))
            for s in range(0,len(ii),512):
                sl=slice(s,s+512); active=dhi[sl]>0
                if active.any():
                    weight=perez_weights(z[sl][active],a[sl][active],dni[sl][active]/interval,dhi[sl][active]/interval,extra[sl][active],p)
                    diffuse+=np.sum(weight*dhi[sl][active,None]/1000,axis=0)
        else:raise ValueError("Unknown sky model")
    p["direct_kwh_m2"]=direct;p["diffuse_kwh_m2"]=diffuse
    p["total_kwh_m2"]=direct+diffuse
    p.attrs["valid_intervals"]=len(ii)
    p.attrs["selected_intervals"]=len(df)
    return p

# Shared strictly nonnegative irradiation palette: exact white at zero.
from .chart_theme import SOLAR_COLORSCALE
SKY_COLORSCALE=SOLAR_COLORSCALE

def _add_dome_compass(fig):
    """Presentation guides in physical East/North/Up coordinates."""
    theta=np.linspace(0,2*np.pi,181)
    r=1.075; z=-.025
    opts=dict(mode="lines",showlegend=False,hoverinfo="skip",
              meta={"presentation_only_trace":True})
    fig.add_trace(go.Scatter3d(x=r*np.sin(theta),y=r*np.cos(theta),
        z=np.full_like(theta,z),line=dict(color="#526170",width=3),name="Horizon compass",**opts))
    # Four cardinal ticks on a ring outside the mesh, plus an unmistakable N arrow.
    x=[];y=[];zz=[]
    for a in (0,90,180,270):
        angle=np.deg2rad(a)
        x.extend([1.02*np.sin(angle),1.13*np.sin(angle),None])
        y.extend([1.02*np.cos(angle),1.13*np.cos(angle),None])
        zz.extend([z,z,None])
    fig.add_trace(go.Scatter3d(x=x,y=y,z=zz,line=dict(color="#526170",width=4),
        name="Cardinal ticks",**opts))
    fig.add_trace(go.Scatter3d(x=[0,0,-.045,0,.045],y=[1.01,1.18,1.115,1.18,1.115],
        z=[z]*5,line=dict(color="#263B4B",width=5),name="North arrow",**opts))
    fig.add_trace(go.Scatter3d(x=[0,1.24,0,-1.24],y=[1.28,0,-1.24,0],z=[.025]*4,
        text=["N","E","S","W"],mode="text",textfont=dict(color="#263B4B",size=18),
        showlegend=False,hoverinfo="skip",name="Compass labels",meta={"presentation_only_trace":True}))

def _dome_point(azimuth,elevation,radius=1.):
    """Right-handed ENU; azimuth is clockwise from geographic North."""
    return (radius*np.cos(elevation)*np.sin(azimuth),
            radius*np.cos(elevation)*np.cos(azimuth),
            radius*np.sin(elevation))

def _dome_patch_grid(p):
    # True patch boundaries only, not internal triangulation diagonals.
    # Slight radial offset prevents z-fighting with the opaque mesh.
    x=[];y=[];z=[]
    def add(a,e):
        xx,yy,zz=_dome_point(np.asarray(a),np.asarray(e),1.002)
        x.extend(xx.tolist()+[None]);y.extend(yy.tolist()+[None]);z.extend(zz.tolist()+[None])
    for row in p.itertuples():
        n=max(2,int(np.ceil(row.width/8)))
        az=np.deg2rad(np.linspace(row.azimuth-row.width/2,row.azimuth+row.width/2,n+1))
        lower,upper=np.deg2rad([row.lower,row.upper])
        add(az,np.full_like(az,lower))
        if row.width<360:
            add(az,np.full_like(az,upper))
            for a in (az[0],az[-1]):
                e=np.linspace(lower,upper,3)
                add(np.full_like(e,a),e)
    return go.Scatter3d(x=x,y=y,z=z,mode="lines",line=dict(color="#A8ADB4",width=1),
        hoverinfo="skip",showlegend=False,name="Sky patch boundaries",meta={"presentation_only_trace":True})

def sky_figure(p,quantity,style="2D hemisphere",*,show_compass=True):
    col={"Direct":"direct_kwh_m2","Diffuse":"diffuse_kwh_m2","Total":"total_kwh_m2"}[quantity]
    v=p[col].to_numpy(float); upper=max(1e-9,float(v.max()))
    colorbar=dict(title="kWh/m² per patch")
    if style=="2D hemisphere":
        fig=go.Figure(go.Barpolar(theta=p.azimuth,width=p.width,base=90-p.upper,r=p.upper-p.lower,
                      marker=dict(color=v,colorscale=SKY_COLORSCALE,cmin=0,cmax=upper,showscale=True,colorbar=colorbar,line=dict(color="rgba(160,160,160,.5)",width=.5)),
                      customdata=np.column_stack([p.lower,p.upper,v,p.solid_angle]),
                      hovertemplate="Elevation %{customdata[0]:.1f}–%{customdata[1]:.1f}°<br>%{customdata[2]:.3f} kWh/m²<extra></extra>"))
        fig.update_layout(polar=dict(barmode="overlay",angularaxis=dict(rotation=90,direction="clockwise",tickvals=[0,90,180,270],ticktext=["N","E","S","W"]),
              radialaxis=dict(range=[0,90],tickvals=[0,15,30,45,60,75,90],ticktext=["90°","75°","60°","45°","30°","15°","0°"])),
              meta={"compass_polar":True})
    elif style=="3D dome":
        x=[];y=[];z=[];i=[];j=[];k=[];intensity=[];patch_data=[]
        for patch_id,(row,value) in enumerate(zip(p.itertuples(),v)):
            # Tessellated quadrilateral strips, including a full azimuth zenith cap.
            n=max(2,int(np.ceil(row.width/8)))
            az=np.deg2rad(np.linspace(row.azimuth-row.width/2,row.azimuth+row.width/2,n+1))
            el=np.deg2rad([row.lower,row.upper])
            for a0,a1 in zip(az[:-1],az[1:]):
                base=len(x)
                for a,e in ((a0,el[0]),(a1,el[0]),(a1,el[1]),(a0,el[1])):
                    xx,yy,zz=_dome_point(a,e)
                    x.append(xx);y.append(yy);z.append(zz);intensity.append(value)
                    patch_data.append([patch_id,row.azimuth,row.lower,row.upper])
                # Azimuth increases clockwise in ENU, so azimuth-first
                # triangles have inward normals. Reverse winding and omit
                # the degenerate second triangle at the zenith apex.
                i.append(base);j.append(base+2);k.append(base+1)
                if row.upper<90.:
                    i.append(base);j.append(base+3);k.append(base+2)
        fig=go.Figure(go.Mesh3d(x=x,y=y,z=z,i=i,j=j,k=k,intensity=intensity,colorscale=SKY_COLORSCALE,cmin=0,cmax=upper,showscale=True,colorbar=colorbar,
               customdata=patch_data,flatshading=True,lighting=dict(ambient=1,diffuse=0,specular=0),
               hovertemplate="Patch %{customdata[0]} · azimuth %{customdata[1]:.1f}°<br>Elevation %{customdata[2]:.1f}–%{customdata[3]:.1f}°<br>%{intensity:.3f} kWh/m² per patch<extra></extra>"))
        fig.add_trace(_dome_patch_grid(p))
        if show_compass:
            _add_dome_compass(fig)
        # View from due South and above: east is screen-right, west left,
        # north at the back, south at the front, as in the polar map.
        axis=dict(showbackground=False,showgrid=False,showticklabels=False,
                  zeroline=False,showspikes=False,showaxeslabels=False)
        # Keep the numeric ENU axes available if the compass is hidden.
        if not show_compass:axis.update(showticklabels=True,showgrid=True,showaxeslabels=True)
        axis.pop("showaxeslabels",None)
        fig.update_layout(scene=dict(aspectmode="data",dragmode="orbit",
             xaxis=dict(title="" if show_compass else "East",range=[-1.36,1.36],**axis),
             yaxis=dict(title="" if show_compass else "North",range=[-1.36,1.36],**axis),
             zaxis=dict(title="" if show_compass else "Up",range=[-.08,1.08],**axis),
             camera=dict(up=dict(x=0,y=0,z=1),eye=dict(x=0,y=-2.4,z=2.0),projection=dict(type="orthographic"))))
    else:
        raise ValueError("Unknown sky chart style.")
    fig.update_layout(template="plotly_white",title=f"Cumulative {quantity.lower()} horizontal irradiation by sky patch",height=760)
    return fig
