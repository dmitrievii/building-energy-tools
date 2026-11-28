"""R2.22 parametric architectural views using the direct-beam aperture model."""
from __future__ import annotations
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from .solar_shading import shaded_fraction, shading_ledger

WALL="#D1D1CD"
GLASS="#B6D7E4"
DEVICE="#78838A"
EDGE="#4C5960"
SHADOW="#708995"
SUN="#DCA439"

def _dimensions(geometry):
    w,h,o,l,r=(float(geometry[k]) for k in ("width","height","overhang","left_fin","right_fin"))
    if not np.isfinite([w,h,o,l,r,geometry["facade"]]).all() or min(w,h)<=0 or min(o,l,r)<0:
        raise ValueError("Invalid aperture or device dimensions.")
    return w,h,o,l,r

def window_geometry_3d(**geometry):
    """Metric local coordinates: +x right looking out, +y outward, +z up."""
    w,h,o,l,r=_dimensions(geometry)
    q=.18*max(w,h)
    f=go.Figure()
    def face(points,color,name):
        p=np.asarray(points,float)
        f.add_trace(go.Mesh3d(x=p[:,0],y=p[:,1],z=p[:,2],i=[0,0],j=[1,2],k=[2,3],
            color=color,flatshading=True,lighting=dict(ambient=.82,diffuse=.45,specular=.05),
            name=name,showlegend=False,hovertemplate=name+"<extra></extra>"))
        p=np.vstack([p,p[0]])
        f.add_trace(go.Scatter3d(x=p[:,0],y=p[:,1],z=p[:,2],mode="lines",
            line=dict(color=EDGE,width=3),showlegend=False,hoverinfo="skip"))
    def wall(x0,x1,z0,z1):
        face([(x0,0,z0),(x1,0,z0),(x1,0,z1),(x0,0,z1)],WALL,"Façade")
    # Four wall strips leave an actual opening, avoiding overlapping faces.
    wall(-q,0,-q,h+q);wall(w,w+q,-q,h+q)
    wall(0,w,-q,0);wall(0,w,h,h+q)
    face([(0,0,0),(w,0,0),(w,0,h),(0,0,h)],GLASS,f"Window {w:g} × {h:g} m")
    if o>0:face([(0,0,h),(w,0,h),(w,o,h),(0,o,h)],DEVICE,f"Overhang {o:g} m")
    if l>0:face([(0,0,0),(0,l,0),(0,l,h),(0,0,h)],DEVICE,f"Left fin {l:g} m")
    if r>0:face([(w,0,0),(w,r,0),(w,r,h),(w,0,h)],DEVICE,f"Right fin {r:g} m")
    def guide(a,b,label):
        p=np.asarray([a,b])
        f.add_trace(go.Scatter3d(x=p[:,0],y=p[:,1],z=p[:,2],mode="lines+text",
            text=["",label],textposition="top center",line=dict(color=SUN,width=3,dash="dash"),
            textfont=dict(size=13,color=EDGE),showlegend=False,hoverinfo="skip"))
    if o>0:guide((w+q*.5,0,h+q*.5),(w+q*.5,o,h+q*.5),f"{o:g} m")
    if l>0:guide((0,0,-q*.5),(0,l,-q*.5),f"{l:g} m")
    if r>0:guide((w,0,-q*.5),(w,r,-q*.5),f"{r:g} m")
    axis=dict(visible=False,showbackground=False)
    f.update_layout(title="Window and shading geometry · interactive 3D",template="plotly_white",
        height=475,margin=dict(l=0,r=0,t=55,b=0),showlegend=False,uirevision="shading-geometry",
        scene=dict(xaxis=axis,yaxis=axis,zaxis=axis,aspectmode="data",
            camera=dict(eye=dict(x=-1.45,y=2.1,z=1.35)),dragmode="orbit"),
        meta={"shading_geometry":dict(geometry),"fixed_physical_axis_relationship":True})
    return f

def _clip_polygon(poly,w,h):
    """Clip a projected planar polygon against the rectangular aperture."""
    for axis,bound,sign in ((0,0,1),(0,w,-1),(1,0,1),(1,h,-1)):
        if not len(poly):break
        out=[]
        for a,b in zip(poly,np.roll(poly,-1,axis=0)):
            da=sign*(a[axis]-bound);db=sign*(b[axis]-bound)
            if da>=0:out.append(a)
            if (da>=0)!=(db>=0):out.append(a+(b-a)*da/(da-db))
        poly=np.asarray(out,float).reshape(-1,2)
    return poly

def shadow_polygons(azimuth,elevation,**geometry):
    """Exact device projections onto glazing, clipped to its boundary.

    The opaque union is displayed without additive transparency. Area and
    irradiation metrics are always taken from the canonical analytical solver.
    """
    w,h,o,l,r=_dimensions(geometry)
    rel=np.deg2rad(azimuth-geometry["facade"]);beta=np.deg2rad(elevation)
    n=np.cos(beta)*np.cos(rel)
    if not np.isfinite([azimuth,elevation]).all() or elevation<=0 or n<=1e-10:return []
    dx=np.cos(beta)*np.sin(rel)/n;dz=np.sin(beta)/n
    planes=[]
    if o>0:planes.append([(0,0,h),(w,0,h),(w,o,h),(0,o,h)])
    if l>0:planes.append([(0,0,0),(0,l,0),(0,l,h),(0,0,h)])
    if r>0:planes.append([(w,0,0),(w,r,0),(w,r,h),(w,0,h)])
    result=[]
    for plane in planes:
        p=np.asarray(plane)
        clipped=_clip_polygon(np.column_stack([p[:,0]-dx*p[:,1],p[:,2]-dz*p[:,1]]),w,h)
        if len(clipped)>=3:result.append(clipped)
    return result

def comparison_figure(cases,azimuth,elevation,*,energy=None):
    """Common-scale axonometric view of exact shadow projections."""
    fig=make_subplots(rows=1,cols=len(cases),subplot_titles=[name for name,_ in cases],horizontal_spacing=.05)
    max_depth=max(max(_dimensions(g)[2:]) for _,g in cases)
    for col,(name,g) in enumerate(cases,1):
        w,h,o,l,r=_dimensions(g);q=.2*max(w,h)
        def project(p):
            x,y,z=np.asarray(p,float).T
            return np.column_stack([x+.45*y,z-.30*y])
        def polygon(points,fill,line=EDGE,local=False):
            p=np.asarray(points,float) if local else project(points)
            p=np.vstack([p,p[0]])
            fig.add_trace(go.Scatter(x=p[:,0],y=p[:,1],mode="lines",fill="toself",fillcolor=fill,
                line=dict(color=line,width=1.2),hoverinfo="skip",showlegend=False),row=1,col=col)
        polygon([(-q,0,-q),(w+q,0,-q),(w+q,0,h+q),(-q,0,h+q)],WALL)
        polygon([(0,0,0),(w,0,0),(w,0,h),(0,0,h)],GLASS)
        for p in shadow_polygons(azimuth,elevation,**g):polygon(p,SHADOW,SHADOW,local=True)
        if r>0:polygon([(w,0,0),(w,r,0),(w,r,h),(w,0,h)],DEVICE)
        if l>0:polygon([(0,0,0),(0,l,0),(0,l,h),(0,0,h)],"#919A9E")
        if o>0:polygon([(0,0,h),(w,0,h),(w,o,h),(0,o,h)],DEVICE)
        # Direction arrow above the façade: direction toward the sun is
        # projected using exactly the same local coordinates as the devices.
        rel=np.deg2rad(azimuth-g["facade"]);beta=np.deg2rad(elevation)
        direction=project([(0,0,0),(np.cos(beta)*np.sin(rel),np.cos(beta)*np.cos(rel),np.sin(beta))])[1]
        norm=float(np.linalg.norm(direction))
        if norm>1e-8:
            tip=np.array([w/2,h+q*2.15])
            tail=tip+direction/norm*q*.85
            fig.add_trace(go.Scatter(x=[tail[0],tip[0]],y=[tail[1],tip[1]],mode="lines+markers",
                line=dict(color=SUN,width=2,dash="dash"),marker=dict(size=[10,0],color=SUN),
                showlegend=False,hovertemplate="Projected direction of direct sun<extra></extra>"),row=1,col=col)
        shade=float(shaded_fraction(azimuth,elevation,**g))*100
        label=f"Overhang {o:.2f} m · fins {l:.2f}/{r:.2f} m<br>{shade:.1f}% of window shaded"
        if energy is not None:
            blocked,remaining=energy[col-1]
            label+=f"<br>{blocked:,.1f} kWh/m² intercepted<br>{remaining:,.1f} kWh/m² remaining"
        lower=min(-q,-.30*max_depth)
        fig.add_annotation(x=(w+.45*max_depth)/2,y=lower-q*.40,text=label,showarrow=False,
            yanchor="top",font=dict(size=12),row=1,col=col)
        anchor="x" if col==1 else f"x{col}"
        fig.update_xaxes(visible=False,range=[-q*1.3,w+.45*max_depth+q*1.3],row=1,col=col)
        fig.update_yaxes(visible=False,range=[lower-q*3.4,h+q*3.4],scaleanchor=anchor,scaleratio=1,constrain="domain",row=1,col=col)
    fig.update_layout(title=f"Window shadow comparison · solar azimuth {azimuth:.1f}° · elevation {elevation:.1f}°",
        template="plotly_white",height=480,margin=dict(l=10,r=10,t=90,b=15),showlegend=False,
        meta={"fixed_physical_axis_relationship":True})
    return fig

def comparison_energy(df,cases,*,albedo):
    """Same coincident valid radiation intervals for all alternatives."""
    ledgers=[shading_ledger(df,albedo=albedo,**g) for _,g in cases]
    fields=["Unshaded total","Intercepted direct","Shaded total (direct-only)"]
    valid=np.logical_and.reduce([np.isfinite(t[fields].to_numpy(float)).all(axis=1) for t in ledgers])
    if not valid.any():return None
    return [(float(t.loc[valid,"Intercepted direct"].sum()/1000),
             float(t.loc[valid,"Shaded total (direct-only)"].sum()/1000)) for t in ledgers]
