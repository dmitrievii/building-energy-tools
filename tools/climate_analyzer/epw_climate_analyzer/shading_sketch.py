"""Dimensioned, dynamic plan and elevation of the direct-sun shading aperture.

Coordinates use the same convention as solar_shading: x increases to the
right when looking out, depth is positive outwards, and height increases up.
The sketch shows actual input proportions, not an additional shading solver.
"""
from __future__ import annotations
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np


def window_shading_sketch(*,facade=180.,width=2.,height=1.5,overhang=0.,
                          left_fin=0.,right_fin=0.,**_ignored):
    w,h,o,l,r=map(float,(width,height,overhang,left_fin,right_fin))
    if not np.isfinite([facade,w,h,o,l,r]).all() or min(w,h)<=0 or min(o,l,r)<0:
        raise ValueError("Invalid window or shading dimensions.")
    fig=make_subplots(rows=1,cols=2,subplot_titles=("Elevation · looking out","Plan · viewed from above"),
                      horizontal_spacing=.10)
    ink="#334155"; wall="#CBD5E1"; glass="#BAE6FD"; device="#64748B"; overhead="#D97706"
    span=max(w,h,o,l,r,.1)
    q=.075*span
    def line(col,x,y,*,color=ink,width=2,dash=None,name="Construction guide",fill=None):
        style=dict(color=color,width=width)
        if dash:style["dash"]=dash
        opts=dict(x=x,y=y,mode="lines",line=style,showlegend=False,hoverinfo="skip",
                  name=name,meta={"presentation_only_trace":True})
        if fill:opts.update(fill="toself",fillcolor=fill)
        fig.add_trace(go.Scatter(**opts),row=1,col=col)
    def label(col,x,y,text,*,color=ink,xanchor="center",yanchor="middle"):
        fig.add_annotation(x=x,y=y,text=text,showarrow=False,font=dict(color=color,size=13),
                           xanchor=xanchor,yanchor=yanchor,row=1,col=col)
    def dimension(col,x1,y1,x2,y2,text,offset_x=0.,offset_y=0.):
        line(col,[x1,x2],[y1,y2],width=1)
        dx=x2-x1;dy=y2-y1;length=(dx*dx+dy*dy)**.5
        if length>0:
            tx=-dy/length*q*.19;ty=dx/length*q*.19
            for x,y in ((x1,y1),(x2,y2)):
                line(col,[x-tx,x+tx],[y-ty,y+ty],width=1)
        label(col,(x1+x2)/2+offset_x,(y1+y2)/2+offset_y,text)
    # Elevation: aperture and schematic façade boundary.
    line(1,[-w/2-q,-w/2-q,w/2+q,w/2+q,-w/2-q],[-q,h+q,h+q,-q,-q],
         color=wall,width=1,fill="#E2E8F0",name="Façade plane")
    line(1,[-w/2,w/2,w/2,-w/2,-w/2],[0,0,h,h,0],
         color=ink,width=2,fill=glass,name="Window opening")
    if o>0:line(1,[-w/2,w/2],[h,h],color=overhead,width=5,name="Overhang edge")
    if l>0:line(1,[-w/2,-w/2],[0,h],color=device,width=5,name="Left fin edge")
    if r>0:line(1,[w/2,w/2],[0,h],color=device,width=5,name="Right fin edge")
    label(1,0,h/2,"Window")
    dimension(1,-w/2,-2*q,w/2,-2*q,f"W = {w:.2f} m",offset_y=-q*.65)
    dimension(1,w/2+2*q,0,w/2+2*q,h,f"H = {h:.2f} m",offset_x=2.0*q)
    # Plan: depth is an actual metric coordinate; no device drawn at zero depth.
    line(2,[-w/2-1.5*q,w/2+1.5*q],[0,0],color=wall,width=8,name="Façade")
    line(2,[-w/2,w/2],[0,0],color="#0284C7",width=4,name="Window")
    if o>0:
        line(2,[-w/2,-w/2,w/2,w/2,-w/2],[0,o,o,0,0],color=overhead,width=2,dash="dash",name="Overhang projection")
    if l>0:line(2,[-w/2,-w/2],[0,l],color=device,width=5,name="Left fin")
    if r>0:line(2,[w/2,w/2],[0,r],color=device,width=5,name="Right fin")
    # Keep dimensions outside the aperture to avoid obscuring the plan.
    dimension(2,-w/2-1.25*q,0,-w/2-1.25*q,l,f"L = {l:.2f} m",offset_x=-1.9*q)
    dimension(2,w/2+1.25*q,0,w/2+1.25*q,r,f"R = {r:.2f} m",offset_x=1.9*q)
    dimension(2,w/2+5.0*q,0,w/2+5.0*q,o,f"D = {o:.2f} m",offset_x=2.0*q)
    label(2,0,-q,"INDOORS",yanchor="top")
    label(2,0,max(o,l,r)+1.1*q,"OUTDOORS")
    label(2,0,max(o,l,r)+2.1*q,f"Façade azimuth {facade:g}°")
    # Each orthographic view independently preserves equal metric scales.
    # Extra margins reserve room for labels even with zero-depth devices.
    fig.update_xaxes(visible=False,range=[-w/2-2*q,w/2+5.4*q],row=1,col=1)
    fig.update_yaxes(visible=False,range=[-3.2*q,h+1.2*q],scaleanchor="x",
                     scaleratio=1,constrain="domain",row=1,col=1)
    fig.update_xaxes(visible=False,range=[-w/2-4.8*q,w/2+8.9*q],row=1,col=2)
    fig.update_yaxes(visible=False,range=[-2.2*q,max(o,l,r)+3.0*q],scaleanchor="x2",
                     scaleratio=1,constrain="domain",row=1,col=2)
    fig.update_layout(template="plotly_white",title="Window and shading geometry",
        height=440,margin=dict(l=15,r=15,t=75,b=35),showlegend=False,
        meta={"fixed_physical_axis_relationship":True,"shading_geometry":{
              "facade":float(facade),"width":w,"height":h,"overhang":o,"left_fin":l,"right_fin":r}})
    return fig
