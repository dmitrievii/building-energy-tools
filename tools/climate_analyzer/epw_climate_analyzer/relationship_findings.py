"""Canonical observed multivariate chart and scientific narrative adapters."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from . import p4_extremes as p
from .charts import paired_scatter_chart
from .aggregations import native_interval_hours

VARS={"Air temperature [°C]":p.T,"Relative humidity [%]":p.RH,
      "Humidity ratio [g/kg]":p.W,"Enthalpy [kJ/kg dry air]":p.H,
      "Wind speed [m/s]":p.V,"Dew point [°C]":"dew_point_temperature_c",
      "Station pressure [Pa]":"atmospheric_station_pressure_pa",
      "Global irradiation [Wh/m²]":"global_horizontal_radiation_wh_m2",
      "Precipitation [mm]":p.P,"Snow depth [cm]":p.SNOW}
LABELS={v:k for k,v in VARS.items()}


def correlation_chart(df,columns):
    columns=list(columns)
    r,n=p.correlation(df,columns)
    labels=[LABELS[c] for c in columns]
    fig=go.Figure(go.Heatmap(x=labels,y=labels,z=r,customdata=n,zmin=-1,zmax=1,zmid=0,
        colorscale="RdBu_r",colorbar=dict(title="Pearson r"),hoverongaps=False,
        hovertemplate="%{y} / %{x}<br>r %{z:.3f}<br>Paired records %{customdata}<extra></extra>"))
    fig.update_layout(template="plotly_white",title="Pairwise observed correlation")
    pairs=[(abs(float(r.iloc[i,j])),i,j) for i in range(len(columns)) for j in range(i+1,len(columns))
           if np.isfinite(r.iloc[i,j])]
    note="Pairwise Pearson correlation measures the direction and strength of linear association across at least three coincident observations. Each cell reports its own paired-record count."
    if pairs:
        _,i,j=max(pairs)
        note+=f" The strongest displayed absolute association is {labels[i]} and {labels[j]} (r = {r.iloc[i,j]:.3f}; {int(n.iloc[i,j]):,} paired records)."
    else:
        note+=" The selected quantities contain insufficient variation or coincident observations for a finite off-diagonal correlation."
    return fig,note


def joint_chart(df,x,y,*,style="density",bins=25):
    labels=(LABELS[x],LABELS[y])
    values=pd.DataFrame({"x":p.valid_values(df,x),"y":p.valid_values(df,y)}).dropna()
    if values.empty:raise ValueError("No coincident valid observations.")
    n=len(values)
    monthly=str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly"
    scope=" native monthly records" if monthly else f" records ({n*native_interval_hours(df):,.1f} h)"
    note=f"{n:,} coincident{scope} describe the joint distribution of {labels[0]} and {labels[1]}."
    if n>=3:
        corr=values.x.corr(values.y)
        if np.isfinite(corr):note+=f" Sample Pearson r = {corr:.3f}."
    if style=="scatter":
        f=paired_scatter_chart(values.x,values.y,"Paired observed states",*labels)
        note+=" Each point represents a paired observation at the same timestamp; clusters and spread reveal the combinations of weather conditions."
    elif style=="density":
        xx,yy,z,h=p.joint_density(df,x,y,bins=bins)
        if monthly:
            h=z*n/100.
        f=go.Figure(go.Heatmap(x=xx,y=yy,z=z,customdata=h,
            colorscale=[[0,"#FFFFFF"],[.5,"#83BCD8"],[1,"#165986"]],zmin=0,
            colorbar=dict(title="% of paired records" if monthly else "% of paired hours"),
            hovertemplate="X %{x:.2f}<br>Y %{y:.2f}<br>Probability mass %{z:.2f}%<br>"+("Records" if monthly else "Hours")+" %{customdata:.1f}<extra></extra>"))
        f.update_layout(template="plotly_white",title="Observed joint probability distribution",xaxis_title=labels[0],yaxis_title=labels[1])
        note+=f" Fixed-width {bins} × {bins} bins show the percentage of paired observations in each joint range; cell probability masses sum to 100%."
    else:raise ValueError("Unknown relationship chart.")
    return f,note
