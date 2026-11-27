"""R2.21 B1: reversible calendar heat-map geometry, without data interpolation.

A barpolar annulus tile is exactly one finite canonical cell. Chronological
grids must belong to one calendar year; pooled grids retain leap-neutral day
slots. Missing cells and unselected periods remain empty, never compressed.
B2 adds masked contours in a separate geometry kernel.
"""
from __future__ import annotations

import calendar
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go

CARTESIAN = "Cartesian"
CIRCULAR = "Circular"
CALENDAR_ANGLE = "Calendar angle"
CLOCK_ANGLE = "Clock-hour angle"
ARRANGEMENTS = (CALENDAR_ANGLE, CLOCK_ANGLE)
LAYER = "ige_circular_heatmap_layer"
ORIGINAL = "ige_circular_heatmap_original"
LAYOUT = "ige_circular_heatmap_layout"
MAX_CELLS = 24 * 366


def _meta(obj):
    m = getattr(obj, "meta", None)
    return dict(m) if isinstance(m, dict) else {}


def _axis(fig, trace, coord):
    ref = getattr(trace, coord + "axis", None) or coord
    return getattr(fig.layout, coord + "axis" + ref[1:])


def _calendar_positions(raw, period, meta):
    """Return original zero-based slots, full-cycle size and readable labels."""
    strings = [str(x) for x in raw]
    years = meta.get("period_source_years", ())
    year = int(years[0]) if len(years) == 2 and years[0] == years[1] else None
    numeric = all(re.fullmatch(r"\d{1,3}", s) for s in strings)
    if period == "day":
        if numeric:
            n = 366  # canonical pooled coordinates use the leap-neutral year
            positions = [int(s)-1 for s in strings]
            stamps = [pd.Timestamp(2000,1,1)+pd.Timedelta(days=p) for p in positions]
            labels = [s.strftime("%d.%m") + (f".{year}" if year is not None and not (s.month==2 and s.day==29 and not calendar.isleap(year)) else "") for s in stamps]
        else:
            if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?: 00:00:00)?", s) for s in strings):
                return None
            dates = pd.DatetimeIndex(pd.to_datetime(strings))
            if len(set(dates.year)) != 1:
                return None
            year = int(dates.year[0])
            n = 366 if calendar.isleap(year) else 365
            positions = list(dates.dayofyear-1)
            labels = [d.strftime("%d.%m.%Y") for d in dates]
    elif period == "month":
        n = 12
        if numeric:
            positions = [int(s)-1 for s in strings]
        elif all(re.fullmatch(r"\d{4}-\d{2}", s) for s in strings):
            if len({s[:4] for s in strings}) != 1:return None
            year = int(strings[0][:4])
            positions = [int(s[-2:])-1 for s in strings]
        else:
            names = {name.lower(): i-1 for i in range(1,13)
                     for name in (calendar.month_name[i], calendar.month_abbr[i])}
            if not all(s.lower() in names for s in strings):return None
            positions = [names[s.lower()] for s in strings]
        labels = [calendar.month_abbr[p+1] if 0<=p<12 else "?" for p in positions]
    elif period == "week":
        matches = [re.fullmatch(r"(?:(\d{4})-)?W?(\d{1,2})", s, re.I) for s in strings]
        if not all(matches):return None
        week_years = {m.group(1) for m in matches if m.group(1)}
        if len(week_years)>1:return None
        if week_years:
            year = int(next(iter(week_years)))
            n = pd.Timestamp(year,12,28).isocalendar().week
        else:n = 53
        positions = [int(m.group(2))-1 for m in matches]
        labels = [f"Week {p+1:02d}" for p in positions]
    else:return None
    if not positions or len(set(positions)) != len(positions) or not all(0<=p<n for p in positions):
        return None
    return np.asarray(positions,dtype=int), int(n), labels, year


def eligible(fig):
    """Strictly identify one canonical period × hour grid, including masks."""
    if fig is None or not hasattr(fig,"data"):return None
    source = [t for t in fig.data if not _meta(t).get("presentation_only_trace")]
    if len(source)!=1 or source[0].type!="heatmap":return None
    t=source[0]
    if t.visible in (False,"legendonly") and not _meta(t).get(ORIGINAL):return None
    # Never discard unrelated annotations, overlays or multiple subplots.
    if t.texttemplate or fig.layout.shapes or fig.layout.annotations:return None
    if (t.xaxis or "x")!="x" or (t.yaxis or "y")!="y":return None
    title=str(_axis(fig,t,"x").title.text or "").lower().strip()
    meta=_meta(fig.layout)
    if title in ("day","daily","day of year","calendar day · leap-year reference"):period="day"
    elif title in ("month","monthly","month of year"):period="month"
    elif title in ("week","weekly","week of year","iso week") or title.startswith("iso week ·"):period="week"
    else:return None
    if str(_axis(fig,t,"y").title.text or "").lower().strip() not in ("hour","hour of day","analysis clock hour","clock hour"):return None
    try:
        if t.x is None or t.y is None:return None
        z=np.asarray(t.z,dtype=float)
        h=np.asarray(t.y,dtype=float)
        if z.ndim!=2 or z.shape!=(len(h),len(t.x)) or z.size>MAX_CELLS:return None
        if not np.isfinite(h).all() or not np.all(h==h.astype(int)):return None
        h=h.astype(int)
        if len(set(h))!=len(h) or np.any((h<0)|(h>23)) or not np.isfinite(z).any():return None
        cal=_calendar_positions(t.x,period,meta)
        if cal is None:return None
        return t,z,h,period,cal
    except (ValueError,TypeError,OverflowError,AttributeError):return None


def restore(fig):
    """Remove only our generated traces and restore original layout properties."""
    from .circular_contours import STATUS
    meta=_meta(fig.layout)
    old=meta.pop(LAYOUT,None)
    meta.pop(STATUS,None)
    if old is None:return fig
    fig.data=tuple(t for t in fig.data if not _meta(t).get(LAYER))
    for t in fig.data:
        m=_meta(t)
        prior=m.pop(ORIGINAL,None)
        if isinstance(prior,dict):
            t.visible=prior["visible"]
            t.meta=prior["meta"]
    fig.layout.polar=old["polar"]
    fig.layout.xaxis.visible=old["xvisible"]
    fig.layout.yaxis.visible=old["yvisible"]
    fig.layout.height=old["height"]
    fig.layout.barmode=old["barmode"]
    fig.layout.meta=meta
    return fig


def contour_eligible(fig, arrangement=CALENDAR_ANGLE):
    from .heatmap_presentation import _eligible
    from .circular_contours import prepare_grid, has_valid_quad
    admitted=eligible(fig)
    if admitted is None or _eligible(fig,admitted[0],check_grid=False) is None:return None
    if not has_valid_quad(prepare_grid(admitted,_meta(fig.layout),arrangement)[2]):return None
    return admitted


def apply(fig, arrangement=CALENDAR_ANGLE, *, mode="Tiles", interval=0., labels=True, width=.25, contrast="Auto"):
    restore(fig)
    if arrangement not in ARRANGEMENTS:raise ValueError("Unknown circular calendar arrangement.")
    admitted=eligible(fig)
    if admitted is None:return fig
    from .circular_contours import build_layers, STATUS
    from .heatmap_presentation import _levels, CONTOUR_MIN_WIDTH, CONTOUR_MAX_WIDTH
    layers=[]
    status={"mode":"Tiles","requested":mode}
    if mode in ("Contours","Tiles + contour lines"):
        try:
            if contour_eligible(fig,arrangement) is None:raise ValueError("The grid does not support continuous neighbouring-cell contours.")
            from .heatmap_presentation import _scale
            _,unit=_scale(fig,admitted[0])
            finite=admitted[1][np.isfinite(admitted[1])]
            levels=_levels(float(finite.min()),float(finite.max()),unit,interval)
            if levels is None:raise ValueError("The requested contour interval exceeds the supported level count.")
            layers,status=build_layers(fig,admitted,arrangement,mode=mode,levels=levels,labels=labels,
                width=max(CONTOUR_MIN_WIDTH,min(CONTOUR_MAX_WIDTH,float(width))),contrast=contrast)
            status["requested"]=mode
        except (ValueError,ImportError) as exc:
            status["reason"]=str(exc)
    t,z,h,period,(p,n,labels,year)=admitted
    rr,cc=np.where(np.isfinite(z))
    values=z[rr,cc]
    hole=0.16
    if arrangement==CALENDAR_ANGLE:
        angle=(p[cc]+.5)*360./n
        widths=np.full(len(values),360./n)
        base=hole+(1-hole)*h[rr]/24
        thick=np.full(len(values),(1-hole)/24)
        if period=="month":
            tickvals=np.arange(12)*30+15
            ticktext=[calendar.month_abbr[m] for m in range(1,13)]
        elif period=="day":
            reference=year if n==365 else 2000
            tickvals=[(pd.Timestamp(reference,m,1).dayofyear-1)*360/n for m in range(1,13)]
            ticktext=[calendar.month_abbr[m] for m in range(1,13)]
        else:
            tickvals=np.arange(0,n,4)*360/n
            ticktext=[f"W{k+1:02d}" for k in range(0,n,4)]
        radialvals=hole+(1-hole)*np.arange(0,25,6)/24
        radialtext=["00","06","12","18","24"]
    else:
        angle=(h[rr]+.5)*15
        widths=np.full(len(values),15.)
        base=hole+(1-hole)*p[cc]/n
        thick=np.full(len(values),(1-hole)/n)
        tickvals=[0,90,180,270]
        ticktext=["00:00","06:00","12:00","18:00"]
        if period=="month":
            ticks=np.arange(12)+.5
            radialtext=[calendar.month_abbr[m] for m in range(1,13)]
        elif period=="day":
            reference=year if n==365 else 2000
            ticks=[pd.Timestamp(reference,m,1).dayofyear-1 for m in (1,4,7,10)]
            radialtext=["Jan","Apr","Jul","Oct"]
        else:
            ticks=np.arange(0,n,13)
            radialtext=[f"W{k+1:02d}" for k in ticks]
        radialvals=hole+(1-hole)*np.asarray(ticks)/n
    # Shared colouraxis is reused unchanged. For standalone heatmaps transfer
    # the complete original colour contract, including categorical tick text.
    if t.coloraxis:
        marker=dict(color=values,coloraxis=t.coloraxis,line=dict(width=0))
        colorbar=getattr(fig.layout,t.coloraxis).colorbar
    else:
        lo=t.zmin if t.zmin is not None else float(values.min())
        hi=t.zmax if t.zmax is not None else float(values.max())
        marker=dict(color=values,colorscale=t.colorscale or "Viridis",
                    cmin=lo,cmax=hi,reversescale=t.reversescale,
                    showscale=t.showscale is not False,
                    colorbar=t.colorbar.to_plotly_json(),line=dict(width=0))
        if t.zmid is not None and t.zmin is None and t.zmax is None:marker["cmid"]=t.zmid
        colorbar=t.colorbar
    unit=str(colorbar.title.text or "")
    custom=[[labels[j],f"{h[i]:02d}:00–{h[i]+1:02d}:00",float(z[i,j])] for i,j in zip(rr,cc)]
    layer=go.Barpolar(theta=angle,r=thick,base=base,width=widths,thetaunit="degrees",
        marker=marker,customdata=custom,showlegend=False,name="Calendar cells",
        hovertemplate="%{customdata[0]} · %{customdata[1]}<br>%{customdata[2]:.4g} "+unit+"<extra></extra>",
        meta={LAYER:True,"presentation_only_trace":True})
    meta=_meta(fig.layout)
    meta[LAYOUT]={"polar":fig.layout.polar.to_plotly_json(),
                  "xvisible":fig.layout.xaxis.visible,"yvisible":fig.layout.yaxis.visible,
                  "height":fig.layout.height,"barmode":fig.layout.barmode}
    m=_meta(t)
    m[ORIGINAL]={"visible":t.visible,"meta":t.meta}
    t.meta=m
    t.visible=False
    if status["mode"]!="Contours":fig.add_trace(layer)
    for contour in layers:fig.add_trace(contour)
    meta[STATUS]=status
    fig.update_layout(meta=meta,barmode="overlay",height=max(600,fig.layout.height or 0),
        polar=dict(barmode="overlay",angularaxis=dict(direction="clockwise",rotation=90,tickmode="array",
                                    tickvals=list(tickvals),ticktext=ticktext,showgrid=False),
                   radialaxis=dict(range=[0,1.],tickmode="array",tickvals=list(radialvals),
                                   ticktext=radialtext,angle=0,showgrid=False,
                                   showline=False),bgcolor=fig.layout.plot_bgcolor or "white"),
        xaxis_visible=False,yaxis_visible=False)
    return fig
