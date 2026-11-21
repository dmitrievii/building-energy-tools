"""Month/hour visualization of disjoint analytical direct-shading contributions."""
from __future__ import annotations

import calendar
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .aggregations import native_interval_hours
from .solar_shading import DEVICES, TOTAL_DEVICE, _shading_components, shading_ledger

ENERGY="Intercepted direct irradiation"
REDUCTION="Direct-beam reduction"
AREA="Mean shaded aperture"
METRICS=(ENERGY,REDUCTION,AREA)
UNITS={ENERGY:"kWh/m²",REDUCTION:"%",AREA:"%"}
COLORS={"Overhang":"#D99032","Left fin":"#4477AA","Right fin":"#228877"}
MONTHS=list(calendar.month_abbr)[1:]
HOURS=[f"{hour:02d}:00" for hour in range(24)]


def temporal_shading_tables(df,*,geometry,metric,albedo=None):
    """Return monthly and month-hour device tables on a single selected year.

    Energy sums interval Wh/m² (no second duration multiplication).
    Reduction uses sum(intercepted direct)/sum(unshaded direct).
    Area averages only front-facing daylight geometry, independent of DNI.
    All contributions share a denominator within each group. Missing/undefined
    bins remain NaN, not zero. Timestamp bins follow the active analysis clock.
    """
    if metric not in METRICS:
        raise ValueError("Unknown shading metric.")
    if not isinstance(df.index,pd.DatetimeIndex) or df.empty:
        raise ValueError("Select a nonempty datetime-indexed climate period.")
    if len(df.index.year.unique())!=1:
        raise ValueError("Select one analysis-clock year before grouping.")
    if metric==AREA:
        az=pd.to_numeric(df["solar_azimuth_deg"],errors="coerce")
        el=90-pd.to_numeric(df["solar_apparent_zenith_deg"],errors="coerce")
        _,components,front=_shading_components(az,el,**geometry)
        duration=native_interval_hours(df)
        values=np.where(front[:,None],components*duration,np.nan)
        denom=np.where(front,duration,np.nan)
    else:
        ledger=shading_ledger(df,albedo=albedo,**geometry)
        values=ledger[[d+" intercepted direct" for d in DEVICES]].to_numpy(dtype=float)
        denom=ledger["Unshaded direct"].to_numpy(dtype=float)
        valid=np.isfinite(denom)&(denom>=0)&np.isfinite(values).all(axis=1)
        values=np.where(valid[:,None],values,np.nan)
        denom=np.where(valid,denom,np.nan)
    raw=pd.DataFrame(values,columns=DEVICES,index=df.index)
    raw["denominator"]=denom
    raw["valid_hours"]=np.where(np.isfinite(denom),native_interval_hours(df),np.nan)

    def reduce(keys,index):
        sums=raw.groupby(keys).sum(min_count=1).reindex(index)
        if metric==ENERGY:
            out=sums[list(DEVICES)]/1000.
        else:
            out=sums[list(DEVICES)].div(sums["denominator"].where(sums["denominator"]>0),axis=0)*100.
        out[TOTAL_DEVICE]=out[list(DEVICES)].sum(axis=1,min_count=len(DEVICES))
        out["valid_hours"]=sums["valid_hours"]
        return out

    months=pd.Index(range(1,13),name="month")
    cells=pd.MultiIndex.from_product([months,range(24)],names=["month","hour"])
    return reduce(df.index.month,months),reduce([df.index.month,df.index.hour],cells)


def shading_monthly_rose(monthly,metric):
    """Stack disjoint contributions; month sectors are calendar, not compass."""
    fig=go.Figure()
    theta=np.arange(12)*30.
    details=np.empty((12,3),dtype=object)
    details[:,0]=MONTHS
    details[:,1]=monthly[TOTAL_DEVICE].to_numpy(dtype=float)
    details[:,2]=monthly["valid_hours"].to_numpy(dtype=float)
    for device in DEVICES:
        fig.add_barpolar(r=monthly[device],theta=theta,width=[26]*12,
                         name=device,marker_color=COLORS[device],
                         customdata=details,
                         hovertemplate="%{customdata[0]} · %{fullData.name}: %{r:.2f} "+UNITS[metric]+
                         "<br>All devices: %{customdata[1]:.2f} "+UNITS[metric]+
                         "<br>Valid duration: %{customdata[2]:.1f} h<extra></extra>")
    axis=dict(ticksuffix=" "+UNITS[metric],angle=45)
    if metric!=ENERGY:
        axis["range"]=[0,100]
    fig.update_layout(template="plotly_white",title=metric+" by month",
                      barmode="stack",polar=dict(barmode="stack",radialaxis=axis,
                      angularaxis=dict(rotation=90,direction="clockwise",
                      tickmode="array",tickvals=theta,ticktext=MONTHS)),
                      margin=dict(t=80,b=60,l=50,r=50),legend=dict(orientation="h"))
    return fig


def shading_month_hour_heatmap(cells,metric,device=TOTAL_DEVICE):
    """Month × hour grid: gray means missing or undefined, white means zero."""
    if device not in (*DEVICES,TOTAL_DEVICE):
        raise ValueError("Unknown shading device.")
    z=cells[device].to_numpy(dtype=float).reshape(12,24)
    coverage=cells["valid_hours"].to_numpy(dtype=float).reshape(12,24)
    fig=go.Figure(go.Heatmap(z=z,x=HOURS,y=MONTHS,customdata=coverage,
                             zmin=0,zmax=100 if metric!=ENERGY else None,
                             colorscale=[[0,"#FFFFFF"],[.25,"#FEE4A6"],[.6,"#F39B43"],[1,"#A83C16"]],
                             colorbar=dict(title=UNITS[metric]),
                             hoverongaps=False,
                             hovertemplate="%{y} · %{x}<br>"+device+": %{z:.2f} "+UNITS[metric]+
                             "<br>Valid duration: %{customdata:.1f} h<extra></extra>"))
    fig.add_heatmap(z=np.where(np.isfinite(z),np.nan,1.),x=HOURS,y=MONTHS,
                    colorscale=[[0,"#D1D5DB"],[1,"#D1D5DB"]],zmin=0,zmax=1,
                    showscale=False,hoverongaps=False,
                    hovertemplate="%{y} · %{x}<br>Missing or undefined<extra></extra>")
    fig.update_layout(template="plotly_white",title=metric+" · "+device,
                      xaxis_title="Hour of day (analysis clock timestamp)",
                      yaxis_title="Month",yaxis=dict(autorange="reversed"),
                      xaxis=dict(tickmode="array",tickvals=HOURS[::2]),height=500)
    return fig
