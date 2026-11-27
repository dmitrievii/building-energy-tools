"""Seam-aware contours over canonical calendar-cell centres (R2.21 B2).

Only the angular dimension can wrap. The calendar seam is closed only for
an explicitly pooled calendar profile; the clock seam is closed only for
recurring clock-hour aggregates. No closure across chronological year ends
or between 23:00 and 00:00 of a single observed day. Missing positions remain
masked, and corner_mask=False excludes every quad touching a missing sample.
Contour geometry is generated in native slot coordinates, then mapped to the
annulus. There are no new weather values and no scientific statistics here.
"""
from __future__ import annotations

import math
import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
from .circular_heatmap import CALENDAR_ANGLE, LAYER, _meta

MAX_VERTICES = 300_000
HOLE = .16
STATUS = "ige_circular_contour_status"


def prepare_grid(admitted, layout_meta, arrangement):
    _, z, hours, period, (periods, n, _, _) = admitted
    # Allocate only a single canonical full-cycle grid (<= 24 x 366).
    full = np.full((24, n), np.nan)
    full[np.ix_(hours, periods)] = z
    pooled = layout_meta.get("period_time_basis") == "Calendar profile"
    # X is the angular slot coordinate and Y the radial slot coordinate.
    if arrangement == CALENDAR_ANGLE:
        data, angular_count, radial_count = full, n, 24
        periodic = pooled
    else:
        data, angular_count, radial_count = full.T, 24, n
        periodic = pooled or period in ("week", "month")
    # Require the entire angular coordinate set. A filter omitting interior
    # positions is not a full cycle, even if its first and last slots survive.
    represented = periods if arrangement == CALENDAR_ANGLE else hours
    periodic = bool(periodic and len(represented) == angular_count)
    if periodic:
        data = np.concatenate((data, data[:, :1]), axis=1)
    x = np.arange(data.shape[1], dtype=float) + .5
    y = np.arange(radial_count, dtype=float) + .5
    return x, y, data, angular_count, radial_count, periodic


def has_valid_quad(z):
    v = np.isfinite(z)
    return bool((v[:-1,:-1] & v[1:,:-1] & v[:-1,1:] & v[1:,1:]).any())


def _polar_path(points, angular_count, radial_count):
    """Subdivide polar-coordinate line segments to bound curved-edge error.

    At most two angular degrees per segment; this is geometric tessellation,
    not new samples of the physical field. Keep angles unwrapped across 360.
    """
    p = np.asarray(points, dtype=float)
    if len(p)<2:return [], []
    out = [p[0]]
    for a,b in zip(p[:-1],p[1:]):
        segments = max(1, math.ceil(abs(b[0]-a[0])*360/angular_count/2))
        out.extend(a+(b-a)*t/segments for t in range(1,segments+1))
    v = np.asarray(out)
    return (v[:,0]*360/angular_count).tolist(), (HOLE+(1-HOLE)*v[:,1]/radial_count).tolist()


def _color_contract(t, fig, values):
    scale = getattr(fig.layout,t.coloraxis) if t.coloraxis else t
    lo = scale.cmin if t.coloraxis else t.zmin
    hi = scale.cmax if t.coloraxis else t.zmax
    lo = float(values.min()) if lo is None else float(lo)
    hi = float(values.max()) if hi is None else float(hi)
    # Plotly stores stops as tuples, and named CSS colours are legal in
    # a continuous scale. Normalize to RGB without changing stop locations.
    from PIL import ImageColor
    palette="Viridis"
    if scale.colorscale:
        palette=[]
        for position,css in scale.colorscale:
            channels=ImageColor.getrgb(css)
            if len(channels)==4 and channels[3]!=255:
                raise ValueError("Translucent colour scales require exact tiles.")
            palette.append([float(position),f"rgb({channels[0]}, {channels[1]}, {channels[2]})"])
    reverse = bool(scale.reversescale)
    def color(value):
        u = float(np.clip((value-lo)/max(hi-lo,1e-30),0.,1.))
        return sample_colorscale(palette,[1-u if reverse else u])[0]
    marker = dict(color=[lo,hi],size=0,opacity=0)
    if t.coloraxis:marker["coloraxis"]=t.coloraxis
    else:marker.update(colorscale=palette,cmin=lo,cmax=hi,reversescale=reverse,
                       showscale=t.showscale is not False,colorbar=t.colorbar.to_plotly_json())
    return color, marker


def build_layers(fig, admitted, arrangement, *, mode, levels, labels, width, contrast):
    """Return bounded presentation traces or raise before mutating the figure."""
    import contourpy
    t, z, _, _, _ = admitted
    x,y,grid,angular_count,radial_count,periodic = prepare_grid(admitted,_meta(fig.layout),arrangement)
    if not has_valid_quad(grid):raise ValueError("No complete neighbouring cells for circular contours.")
    g = contourpy.contour_generator(x=x,y=y,z=np.ma.masked_invalid(grid),
        name="serial",corner_mask=False,line_type="Separate",fill_type="OuterOffset")
    finite = z[np.isfinite(z)]
    lo,hi = float(finite.min()),float(finite.max())
    steps = np.arange(levels["start"],levels["end"]+levels["size"]*.25,levels["size"])
    # Avoid duplicated upper/lower bands and contours exactly at the extremes.
    steps = steps[(steps>lo)&(steps<hi)]
    color,marker=_color_contract(t,fig,finite)
    stroke = "#FFFFFF" if contrast=="Light" else "#252525"
    if contrast=="Auto":
        from plotly.colors import unlabel_rgb
        rgb=np.asarray([unlabel_rgb(color(lo+(hi-lo)*q)) for q in (.15,.35,.55,.75,.95)])
        if float(np.mean(rgb @ np.array([.2126,.7152,.0722])))/255 < .47:stroke="#FFFFFF"
    traces=[]; vertices=0
    def append_path(points, theta, radius):
        nonlocal vertices
        a,r=_polar_path(points,angular_count,radial_count)
        vertices+=len(a)
        if vertices>MAX_VERTICES:raise ValueError("Circular contour geometry exceeds the bounded vertex budget.")
        theta.extend(a+[None]);radius.extend(r+[None])
    if mode=="Contours":
        # OuterOffset retains outer and oppositely wound inner rings. Each
        # ring becomes a closed SVG subpath; holes remain unpainted.
        bounds=np.r_[np.nextafter(lo,-np.inf),steps,np.nextafter(hi,np.inf)]
        for a,b in zip(bounds[:-1],bounds[1:]):
            rings,offsets=g.filled(float(a),float(b))
            theta=[];radius=[]
            for polygon,offset in zip(rings,offsets):
                for i,j in zip(offset[:-1],offset[1:]):
                    append_path(polygon[int(i):int(j)],theta,radius)
            if theta:
                traces.append(go.Scatterpolar(theta=theta,r=radius,thetaunit="degrees",
                    mode="lines",fill="toself",fillcolor=color(float((a+b)/2)),
                    line=dict(width=0),hoverinfo="skip",showlegend=False,
                    name=f"Contour band {a:.4g}–{b:.4g}",
                    meta={LAYER:True,"presentation_only_trace":True,"circular_contour_band":True}))
        if not traces:raise ValueError("No finite circular contour regions.")
        # One zero-size scale carrier, instead of duplicating the full tile
        # layer underneath filled bands. The same canonical coloraxis remains.
        traces.append(go.Scatterpolar(theta=[0,0],r=[0,0],mode="markers",
            marker=marker,showlegend=False,hoverinfo="skip",name="Contour colour scale",
            meta={LAYER:True,"presentation_only_trace":True,"circular_contour_scale":True}))
    theta=[];radius=[];lt=[];lr=[];text=[]
    for level in steps:
        paths=g.lines(float(level))
        if not paths:continue
        for path in paths:append_path(path,theta,radius)
        if labels:
            # One label per level, on the longest available line; avoid
            # crowding by requiring a minimum physical angular/radial length.
            path=max(paths,key=len)
            if len(path)>=3:
                mid=path[len(path)//2]
                lt.append(float(mid[0]*360/angular_count))
                lr.append(float(HOLE+(1-HOLE)*mid[1]/radial_count))
                text.append(f"{level:g}")
    if theta:
        traces.append(go.Scatterpolar(theta=theta,r=radius,thetaunit="degrees",
            mode="lines",line=dict(color=stroke,width=width),connectgaps=False,
            hoverinfo="skip",showlegend=False,name="Circular contour lines",
            meta={LAYER:True,"presentation_only_trace":True,"circular_contour_lines":True}))
    if text:
        traces.append(go.Scatterpolar(theta=lt,r=lr,mode="text",text=text,
            textfont=dict(size=11,color=stroke),hoverinfo="skip",showlegend=False,
            name="Contour labels",meta={LAYER:True,"presentation_only_trace":True,"circular_contour_labels":True}))
    if mode=="Tiles + contour lines" and not theta:
        raise ValueError("No interior contour level crosses the valid grid.")
    return traces,dict(mode=mode,periodic=periodic,vertices=vertices,levels=steps.tolist())
