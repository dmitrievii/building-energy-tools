"""P2 directional climate indicators; meteorological FROM bearings."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .aggregations import native_interval_hours

METRICS={
    "Temperature":("dry_bulb_temperature_c","°C","RdBu_r"),
    "Relative humidity":("relative_humidity_pct","%","Blues"),
    "Humidity ratio":("humidity_ratio_g_kg","g/kg dry air","Blues"),
    "Absolute humidity":("_absolute_humidity","g/m³","Blues"),
    "Enthalpy":("moist_air_enthalpy_kj_kg","kJ/kg dry air","Viridis"),
    "Natural ventilation suitability":("_nv_suitable","%","Greens"),
}
ANGLES=np.arange(16)*22.5
COMPASS=["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]

def numeric(df,c):
    return pd.to_numeric(df[c],errors="coerce").replace([np.inf,-np.inf],np.nan) if c in df else pd.Series(np.nan,index=df.index)

def available(df,c):
    return bool(numeric(df,c).notna().any())

def absolute_humidity(df):
    # Humidity ratio g/kg dry air / specific volume m³/kg dry air.
    w=numeric(df,"humidity_ratio_g_kg")
    v=numeric(df,"specific_volume_m3_kg")
    return (w/v).where((w>=0)&(v>0))

def direction_rows(df,speed="wind_speed_m_s",direction="wind_direction_deg"):
    v=numeric(df,speed); a=numeric(df,direction)
    valid=(v>0)&a.between(0,360)
    data=pd.DataFrame({"speed":v,"sector":np.floor((a+11.25)/22.5)%16*22.5},index=df.index)
    return data.loc[valid].copy()

def colour_options(df,nv=False):
    result=["Wind speed"]
    for label,(c,_,_) in METRICS.items():
        if label=="Absolute humidity":
            ok=absolute_humidity(df).notna().any()
        elif label=="Natural ventilation suitability":
            ok=nv
        else:
            ok=available(df,c)
        if ok: result.append(label)
    return result

def radial_options(df,mean_wind=True):
    result=["Hours","Percentage","Mean wind speed"]
    if mean_wind and available(df,"liquid_precipitation_depth_mm"):
        result.append("Wind-driven rain exposure")
    if available(df,"moist_air_density_kg_m3"):
        result.append("Dynamic pressure potential")
    return result

def directional_table(df,*,speed="wind_speed_m_s",direction="wind_direction_deg",
                      radial="Hours",colour="Wind speed",nv_mask=None):
    rows=direction_rows(df,speed,direction)
    interval=native_interval_hours(df)
    if colour=="Wind speed": val=rows["speed"]
    elif colour=="Absolute humidity": val=absolute_humidity(df).loc[rows.index]
    elif colour=="Natural ventilation suitability":
        if nv_mask is None: raise ValueError("Suitability mask required")
        val=nv_mask.reindex(rows.index).astype(float)*100
    else: val=numeric(df,METRICS[colour][0]).loc[rows.index]
    rows["colour"]=val
    if radial=="Wind-driven rain exposure":
        p=numeric(df,"liquid_precipitation_depth_mm").loc[rows.index]
        rows["radial"]=(p*rows.speed).where(p>=0)
    elif radial=="Dynamic pressure potential":
        rho=numeric(df,"moist_air_density_kg_m3").loc[rows.index]
        rows["radial"]=(.5*rho*rows.speed**2).where(rho>0)
    else: rows["radial"]=rows.speed
    rows=rows.dropna(subset=["colour","radial"])
    grouped=rows.groupby("sector")
    counts=grouped.size().reindex(ANGLES,fill_value=0)
    if radial=="Hours": r=counts*interval
    elif radial=="Percentage": r=counts*100/max(1,int(counts.sum()))
    elif radial=="Wind-driven rain exposure": r=grouped.radial.sum(min_count=1).reindex(ANGLES)
    else: r=grouped.radial.mean().reindex(ANGLES)
    table=pd.DataFrame({"radius":r,"colour":grouped.colour.mean().reindex(ANGLES),
                        "valid_hours":counts*interval,"direction":COMPASS},index=ANGLES)
    table.index.name="azimuth_deg"
    return table

RADIAL_UNITS={"Hours":"h","Percentage":"%","Mean wind speed":"m/s",
              "Wind-driven rain exposure":"mm·m/s","Dynamic pressure potential":"Pa"}

def directional_figure(table,radial,colour,title):
    _,unit,scale=METRICS.get(colour,(None,"m/s","Viridis"))
    v=table["colour"].to_numpy(float)
    if colour=="Relative humidity" or colour=="Natural ventilation suitability":
        limits=dict(cmin=0,cmax=100)
    else: limits={}
    # Plot absent colours as NaN; zero-length sectors contribute no visible bars.
    radius=table.radius.where(table.valid_hours>0)
    fig=go.Figure(go.Barpolar(theta=table.index,r=radius,width=21.,
        marker=dict(color=v,colorscale=scale,showscale=True,colorbar=dict(title=f"{colour} [{unit}]"),**limits),
        customdata=np.column_stack([table.direction,table.colour,table.valid_hours]),
        hovertemplate="%{customdata[0]}<br>Radius: %{r:.3g} "+RADIAL_UNITS[radial]+
        "<br>"+colour+": %{customdata[1]:.2f} "+unit+"<br>Valid hours: %{customdata[2]:.1f}<extra></extra>"))
    fig.update_layout(template="plotly_white",title=title,
        polar=dict(angularaxis=dict(rotation=90,direction="clockwise",tickvals=ANGLES,ticktext=COMPASS),
                   radialaxis=dict(rangemode="nonnegative",ticksuffix=" "+RADIAL_UNITS[radial])),
        meta={"compass_polar":True},height=680)
    return fig

def directional_speed_figure(df,speed,direction,title):
    rows=direction_rows(df,speed,direction)
    fig=go.Figure()
    for angle,label in zip(ANGLES,COMPASS):
        fig.add_box(x=[label]*int((rows.sector==angle).sum()),y=rows.loc[rows.sector==angle,"speed"],
                    name=label,boxpoints=False,showlegend=False)
    fig.update_layout(template="plotly_white",title=title,xaxis_title="Wind FROM direction",
                      yaxis_title="Wind speed [m/s]",xaxis=dict(categoryorder="array",categoryarray=COMPASS))
    return fig

def directional_interpretation(table,radial,colour):
    valid=table.loc[table.valid_hours>0].dropna(subset=["radius"])
    if valid.empty: return "No coincident non-calm wind observations support the selected quantities."
    row=valid.loc[valid.radius.idxmax()]
    return (f"The largest {radial.lower()} value occurs for wind from {row.direction} "
            f"({row.radius:.2f} {RADIAL_UNITS[radial]}). The colour represents the directional mean "
            f"of {colour.lower()}, calculated from {valid.valid_hours.sum():.1f} valid non-calm observation hours. "
            "Missing coincident inputs and calm intervals are excluded from these directional statistics. "
            "Rain exposure is an uncalibrated sum of interval precipitation depth times mean wind speed, not façade catch ratio or rain load. "
            "Dynamic pressure is conditional mean ½ρv², not a design wind load or building pressure difference.")

def nv_valid_mask(df,mask,wind_filter=False):
    required=["dry_bulb_temperature_c","humidity_ratio_g_kg"]
    if wind_filter: required.append("wind_speed_m_s")
    valid=pd.DataFrame({c:numeric(df,c).notna() for c in required}).all(axis=1)
    return mask.where(valid)
