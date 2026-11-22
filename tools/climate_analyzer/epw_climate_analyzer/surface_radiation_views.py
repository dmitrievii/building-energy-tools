"""Derived quantities using the admitted POA kernel."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .monthly_radiation import SOURCE_FIELDS,SURFACE_FIELDS,surface_available
from .runtime_module_guard import ensure_current_solar_runtime

FRACTION="diffuse_radiation_fraction_pct"

def with_diffuse_fraction(df):
    out=df.copy()
    ghi=SOURCE_FIELDS["GHI"]; dhi=SOURCE_FIELDS["DHI"]
    if ghi in out and dhi in out:
        g=pd.to_numeric(out[ghi],errors="coerce")
        d=pd.to_numeric(out[dhi],errors="coerce")
        out[FRACTION]=(100*d/g).where(np.isfinite(g)&np.isfinite(d)&(g>0)&(d>=0)&(d<=g))
    return out

def poa_frame(df,tilt,azimuth,albedo=None,*,copy=True):
    if not surface_available(df): raise ValueError("Surface radiation requires coincident GHI, DNI, DHI and solar geometry.")
    data=ensure_current_solar_runtime().surface_irradiance_components(df,tilt,azimuth,albedo=albedo)
    out=df.copy() if copy else df
    for c in SURFACE_FIELDS.values():out[c]=data[c]
    out.attrs.update(df.attrs)
    return out

def orientation_curves(matrix):
    fig=go.Figure()
    for tilt in matrix.index:
        vals=matrix.loc[tilt].sort_index()
        x=list(vals.index); y=list(vals)
        if x and float(x[0])==0:
            x.append(360.);y.append(y[0])
        fig.add_scatter(x=x,y=y,mode="lines+markers",name=f"{tilt:g}° tilt",connectgaps=False)
    fig.update_layout(template="plotly_white",title="Selected-period irradiation by orientation and tilt",
        xaxis=dict(title="Surface azimuth [°]",range=[0,360],tickvals=[0,90,180,270,360],ticktext=["0° N","90° E","180° S","270° W","360° N"]),
        yaxis_title="Irradiation [kWh/m²]",legend=dict(orientation="h",y=-.2))
    return fig
