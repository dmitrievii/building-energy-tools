"""R2.18 palette evidence: inspect actual visible trace colour channels.

This is an audit, never a recolouring pass. Missing assignments and
cross-surface differences are reported with their chart/trace identifiers.
Plotly defaults cannot earn an explicit-palette pass.
"""
from __future__ import annotations
import hashlib
import json
from plotly.utils import PlotlyJSONEncoder

def _digest(value):
    return hashlib.sha256(json.dumps(value,cls=PlotlyJSONEncoder,sort_keys=True).encode()).hexdigest()

def _scale(trace,layout,marker=False):
    source=trace.get("marker",{}) if marker else trace
    axis=source.get("coloraxis")
    if axis:
        props=layout.get(axis,{})
        return props.get("colorscale"),props.get("cmin"),props.get("cmax")
    return source.get("colorscale"),source.get("cmin" if marker else "zmin"),source.get("cmax" if marker else "zmax")

def inspect_palette(fig):
    raw=fig.to_plotly_json()
    layout=raw.get("layout",{})
    signatures=[];missing=[]
    for i,tr in enumerate(raw.get("data",[])):
        if tr.get("visible") in (False,"legendonly") or tr.get("opacity")==0:continue
        kind=tr.get("type","scatter");name=str(tr.get("name",""))
        marker=tr.get("marker",{});line=tr.get("line",{})
        mode=tr.get("mode","lines")
        fill=tr.get("fillcolor")
        color=marker.get("color");lc=line.get("color")
        scale=None;bounds=None
        if kind in ("heatmap","contour","surface"):
            scale,lo,hi=_scale(tr,layout);bounds=(lo,hi)
            # A line-only contour uses an explicit stroke, not a filled scale.
            line_only=(kind=="contour" and tr.get("contours",{}).get("coloring")=="none" and lc is not None)
            if scale is None and tr.get("surfacecolor") is None and not line_only:missing.append(f"{i}:{name}:colorscale")
        elif kind in ("bar","barpolar","histogram","box","violin"):
            if color is None and lc is None and fill is None:missing.append(f"{i}:{name}:marker/line")
            if marker.get("colorscale") is not None or marker.get("coloraxis"):
                scale,lo,hi=_scale(tr,layout,True);bounds=(lo,hi)
        elif kind.startswith("scatter"):
            if "markers" in mode and color is None and lc is None and marker.get("opacity")!=0:
                missing.append(f"{i}:{name}:marker")
            if "lines" in mode and lc is None and line.get("width",1)!=0 and color is None:
                missing.append(f"{i}:{name}:line")
            if marker.get("colorscale") is not None or marker.get("coloraxis"):
                scale,lo,hi=_scale(tr,layout,True);bounds=(lo,hi)
        elif kind in ("mesh3d","cone"):
            scale=tr.get("colorscale")
            if all(tr.get(key) is None for key in ("color","vertexcolor","facecolor","colorscale")):
                missing.append(f"{i}:{name}:3D colour")
        else:
            # Map tiles, images, tables and other non-palette trace types.
            continue
        signatures.append((kind,name,lc,color,fill,scale,bounds))
    return {"implicit_channels":missing,"signature":_digest(signatures),"trace_count":len(signatures)}
