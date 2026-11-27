"""Opt-in contour rendering of continuous, rectangular climate heat maps.

The canonical heatmap remains the scientific data trace. Generated contours
are presentation-only, never inputs to statistics or interpretations.
No new grids, smoothing, extrapolation, global caches or retained figure copies.
"""
from __future__ import annotations
import math
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go

TILES="Tiles"
CONTOURS="Contours"
HYBRID="Tiles + contour lines"
MODES=(TILES,CONTOURS,HYBRID)
LAYER="ige_heatmap_contour"
ORIGINAL="ige_heatmap_original"
# Fixed physical default steps; automatic nice-number fallback handles
# unusually small or large domains, including irradiation and pressure.
MAX_LEVELS=60
CONTOUR_MIN_WIDTH=0.25
CONTOUR_DEFAULT_WIDTH=CONTOUR_MIN_WIDTH
CONTOUR_MAX_WIDTH=3.0

def _meta(obj):
    m=getattr(obj,"meta",None)
    return dict(m) if isinstance(m,dict) else {}

def _axis(fig,trace,coord):
    return getattr(fig.layout,coord+"axis"+(getattr(trace,coord+"axis",None) or coord)[1:])

def _scale(fig,trace):
    ref=trace.coloraxis
    source=getattr(fig.layout,ref,None) if ref else trace
    bar=source.colorbar
    return source, str(bar.title.text or "")

def _ordered_grid(values,n,axis):
    """Only ordered cell-centre coordinates; do not bridge absent calendar days."""
    if values is None or len(values)!=n or n<2:return False
    a=list(values)
    if any(v is None for v in a):return False
    if len({str(v) for v in a})!=n:return False
    text=[str(v) for v in a]
    try:
        numeric=np.asarray(a,dtype=float)
        if not np.isfinite(numeric).all():return False
        diff=np.diff(numeric)
        if not (np.all(diff>0) or np.all(diff<0)):return False
        title=str(axis.title.text or "").lower()
        if any(k in title for k in ("day","week","month","hour")) and np.max(abs(diff))>1.01*np.min(abs(diff)):
            # Day-of-year leap-slot gap or a filtered calendar discontinuity.
            return False
        return True
    except (ValueError,TypeError,OverflowError):pass
    if all(re.fullmatch(r"\d{4}-W\d{2}",v) for v in text):
        try:dates=pd.DatetimeIndex([pd.Timestamp.fromisocalendar(int(v[:4]),int(v[-2:]),1) for v in text])
        except ValueError:return False
        return bool(np.all(np.diff(dates.asi8)==pd.Timedelta(days=7).value))
    if all(re.fullmatch(r"W\d{2}",v) for v in text):
        return all(b-a==1 for a,b in zip([int(v[1:]) for v in text],[int(v[1:]) for v in text][1:]))
    if all(re.match(r"^\d{4}-\d{2}",v) for v in text):
        try:dates=pd.DatetimeIndex(pd.to_datetime(a,format="mixed"))
        except (ValueError,TypeError,OverflowError):return False
        if dates.hasnans:return False
        if all(re.fullmatch(r"\d{4}-\d{2}",v) for v in text):
            ordinals=dates.to_period("M").asi8
            return bool(np.all(np.diff(ordinals)==1))
        diffs=np.diff(dates.asi8)
        return bool(len(diffs) and np.all(diffs>0) and np.all(diffs==diffs[0]))
    months={m:i for i,m in enumerate(("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"),1)}
    if all(v in months for v in text):
        return all(months[b]-months[a]==1 for a,b in zip(text,text[1:]))
    # Other categorical axes (climate names, classes, variables, etc.) are
    # not ordered physical interpolation coordinates.
    return False

def _eligible(fig,trace):
    if trace.type!="heatmap" or trace.visible in (False,"legendonly"):return None
    meta=_meta(trace);layout_meta=_meta(fig.layout)
    if meta.get("presentation_only_trace") or meta.get("heatmap_semantics") in ("categorical","binary","circular","mask"):
        return None
    if layout_meta.get("utci_stress_palette") or layout_meta.get("heatmap_semantics") in ("categorical","binary","circular","mask"):
        return None
    scale,unit=_scale(fig,trace)
    names=" ".join([str(fig.layout.title.text or ""),str(trace.name or ""),str(meta.get("heatmap_quantity","")),unit]).lower()
    if any(v in names for v in ("wind direction","wind_direction","wind_gust_direction","direction [","stress class","utci stress","correlation","class","snow cover","snow-cover","availability","suitab","eligibility","0/1","binary","missing or undefined","occurrence","joint probability","frequency","probability","count","number of","hours per")):
        return None
    # Reject colorbar-coded or count-derived heatmaps even if their source
    # column is a continuous physical quantity.
    # A quantity/explicit continuous admission is required. Never infer
    # continuity merely from floating-point values in an unknown matrix.
    u=unit.lower().strip()
    known=meta.get("heatmap_semantics")=="continuous" or any(v in u for v in ("°c","kelvin","k·","g/kg","kj/kg","m/s","w/m²","wh/m²","w/m2","wh/m2","lux","lx","kpa","pa","kg/m³","m³/kg","mm","cm","%"))
    if not known:return None
    # Reject discrete colorbar labels and stepped categorical palettes.
    ticks=scale.colorbar.ticktext
    if ticks and any(not re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?(?:\s*%)?",str(v).strip()) for v in ticks):
        return None
    colors=getattr(scale,"colorscale",None)
    if colors and any(float(a[0])==float(b[0]) and a[1]!=b[1] for a,b in zip(colors,colors[1:])):return None
    if trace.showscale is False and not trace.coloraxis:return None
    # A categorical row of years represents distinct samples, not an
    # interpolable continuous coordinate, even when years are numeric.
    if any(str(_axis(fig,trace,c).title.text or "").lower() in ("year","climate","station","scenario","variable") for c in ("x","y")):return None
    try:z=np.asarray(trace.z,dtype=float)
    except (ValueError,TypeError):return None
    if z.ndim!=2 or min(z.shape)<2:return None
    finite=z[np.isfinite(z)]
    if not finite.size or float(finite.min())==float(finite.max()):return None
    # Even a generic numeric 0/1 state must remain a discrete tile map.
    if np.all((finite==0)|(finite==1)):return None
    # Contouring requires at least one full valid 2×2 cell, and ordered axes.
    valid=np.isfinite(z)
    if not (valid[:-1,:-1]&valid[1:,:-1]&valid[:-1,1:]&valid[1:,1:]).any():return None
    if not _ordered_grid(trace.x,z.shape[1],_axis(fig,trace,"x")):return None
    if not _ordered_grid(trace.y,z.shape[0],_axis(fig,trace,"y")):return None
    # This version leaves mixed categorical masks and annotated matrices as
    # tiles; their exact cell presentation is important.
    if trace.texttemplate:return None
    return z,scale,unit,float(finite.min()),float(finite.max())

def _levels(lo,hi,unit,requested):
    span=hi-lo
    if not math.isfinite(span) or span<=0:return None
    u=unit.lower()
    preferred=5. if "°c" in u else 10. if "%" in u else 2. if "m/s" in u else None
    step=float(requested or 0)
    if not math.isfinite(step) or step<=0:step=0.
    if not step:
        desired=span/10.
        if preferred and 2<=span/preferred<=20:step=preferred
        else:
            base=10.**math.floor(math.log10(desired))
            step=next((base*m for m in (1,2,2.5,5,10) if base*m>=desired),10*base)
    if span/step>MAX_LEVELS:return None
    start=math.ceil(lo/step-1e-10)*step
    end=math.floor(hi/step+1e-10)*step
    if end<start:return None
    return dict(start=start,end=end,size=step)

def _restore(fig):
    """Idempotent and reversible. Remove only our own generated traces."""
    fig.data=tuple(t for t in fig.data if not _meta(t).get(LAYER))
    for t in fig.data:
        meta=_meta(t)
        old=meta.pop(ORIGINAL,None)
        if isinstance(old,dict):
            t.opacity=old.get("opacity")
            t.showscale=old.get("showscale")
            t.meta=old.get("meta")

def apply_heatmap_presentation(fig,mode=TILES,*,interval=0.,labels=True,width=CONTOUR_DEFAULT_WIDTH,contrast="Auto",geometry="Cartesian",arrangement="Calendar angle"):
    from . import circular_heatmap as circular
    circular.restore(fig)
    if geometry==circular.CIRCULAR:
        _restore(fig)
        return circular.apply(fig,arrangement)
    if mode not in MODES:mode=TILES
    # Avoid any data scan/allocation in the default path on ordinary figures.
    if not any(_meta(t).get(LAYER) or _meta(t).get(ORIGINAL) for t in fig.data) and mode==TILES:return fig
    _restore(fig)
    if mode==TILES:return fig
    for trace in tuple(fig.data):
        admitted=_eligible(fig,trace)
        if admitted is None:continue
        z,scale,unit,lo,hi=admitted
        if trace.coloraxis:
            cmin,cmax=scale.cmin,scale.cmax
        else:cmin,cmax=trace.zmin,trace.zmax
        levels=_levels(lo,hi,unit,interval)
        if levels is None:continue
        line_color="#FFFFFF" if contrast=="Light" else "#252525"
        if contrast=="Auto":
            from plotly.colors import sample_colorscale,unlabel_rgb
            try:
                palette=scale.colorscale or "Viridis"
                sample=sample_colorscale(palette,[.15,.35,.55,.75,.95])
                rgb=np.asarray([unlabel_rgb(v) for v in sample],dtype=float)/255.
                luminance=float(np.mean(rgb @ np.array([.2126,.7152,.0722])))
                line_color="#FFFFFF" if luminance<.47 else "#252525"
            except (ValueError,TypeError,IndexError):pass
        # Plotly contour receives the identical source coordinates and values.
        # connectgaps=False prevents filling through invalid cells. No added
        # samples, no interpolation of categorical codes or circular angles.
        local=dict(coloraxis=trace.coloraxis) if trace.coloraxis else dict(
            colorscale=trace.colorscale or "Viridis",zmin=cmin if cmin is not None else lo,
            zmax=cmax if cmax is not None else hi,zmid=trace.zmid,
            reversescale=trace.reversescale,colorbar=trace.colorbar.to_plotly_json(),zauto=False)
        opts=dict(x=trace.x,y=trace.y,z=z,xaxis=trace.xaxis,yaxis=trace.yaxis,
            connectgaps=False,hoverongaps=False,hoverinfo="skip",
            showlegend=False,showscale=mode==CONTOURS and not trace.coloraxis,
            autocontour=False,contours=dict(**levels,coloring="heatmap" if mode==CONTOURS else "none",
                showlabels=bool(labels),labelfont=dict(color=line_color,size=11)),
            line=dict(color=line_color,width=max(CONTOUR_MIN_WIDTH,min(4.,float(width))),smoothing=0),
            name="Contour rendering",meta={LAYER:True,"presentation_only_trace":True},**local)
        # Validate the complete generated trace before touching canonical tiles.
        contour=go.Contour(**opts)
        if mode==CONTOURS:
            meta=_meta(trace)
            meta[ORIGINAL]={"opacity":trace.opacity,"showscale":trace.showscale,"meta":trace.meta}
            trace.meta=meta;trace.opacity=0.;trace.showscale=False
        fig.add_trace(contour)
    return fig

def settings_from_context(context):
    settings=context.get("heatmap presentation",{}) if isinstance(context,dict) else {}
    return settings if isinstance(settings,dict) else {}

def context_from_state(state):
    """Defaults for automatic Atlas and standard-report diagrams, not explorer state."""
    return {"mode":CONTOURS,"interval":0.,"labels":True,"width":CONTOUR_DEFAULT_WIDTH,"contrast":"Auto"}
