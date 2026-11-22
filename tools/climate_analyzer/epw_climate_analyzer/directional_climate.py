"""P2 directional climate indicators; meteorological FROM bearings."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .aggregations import native_interval_hours
from .chart_theme import WIND_SPEED_LABELS, WIND_SPEED_COLOR_MAP

METRICS={
    "Temperature":("dry_bulb_temperature_c","°C","RdBu_r"),
    "Relative humidity":("relative_humidity_pct","%","Blues"),
    "Humidity ratio":("humidity_ratio_g_kg","g/kg dry air","Blues"),
    "Absolute humidity":("_absolute_humidity","g/m³","Blues"),
    "Enthalpy":("moist_air_enthalpy_kj_kg","kJ/kg dry air","Viridis"),
    "Natural ventilation suitability":("_nv_suitable","%","Greens"),
    "Dynamic pressure potential":("_dynamic_pressure","Pa","Viridis"),
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

def dynamic_pressure(df,speed="wind_speed_m_s"):
    rho=numeric(df,"moist_air_density_kg_m3")
    v=numeric(df,speed)
    return (.5*rho*v**2).where((rho>0)&(v>=0))

def colour_options(df,nv=False,speed="wind_speed_m_s"):
    result=["Wind speed"]
    for label,(c,_,_) in METRICS.items():
        if label=="Absolute humidity":
            ok=absolute_humidity(df).notna().any()
        elif label=="Natural ventilation suitability":
            ok=nv
        elif label=="Dynamic pressure potential":
            ok=dynamic_pressure(df,speed).notna().any()
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
    elif colour=="Dynamic pressure potential": val=dynamic_pressure(df,speed).loc[rows.index]
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
    text=(f"The largest {radial.lower()} value occurs for wind from {row.direction} "
          f"({row.radius:.2f} {RADIAL_UNITS[radial]}). The colour represents the directional mean "
          f"of {colour.lower()}, calculated from {valid.valid_hours.sum():.1f} valid non-calm observation hours. "
          "Missing coincident inputs and calm intervals are excluded from these directional statistics.")
    if radial=="Wind-driven rain exposure":
        text+=" Rain exposure is an uncalibrated sum of interval precipitation depth times mean wind speed, not façade catch ratio or rain load."
    if radial=="Dynamic pressure potential":
        text+=" Dynamic pressure is conditional mean ½ρv², not a design wind load or building pressure difference."
    return text

def nv_valid_mask(df,mask,wind_filter=False):
    required=["dry_bulb_temperature_c","humidity_ratio_g_kg"]
    if wind_filter: required.append("wind_speed_m_s")
    valid=pd.DataFrame({c:numeric(df,c).notna() for c in required}).all(axis=1)
    return mask.where(valid)

# Fixed physical thresholds (not data-dependent quantile bins) permit
# comparisons across months, climates and wind datasets. Editable boundaries
# are accepted for all scalar quantities; suitability is Boolean by definition.
CLASS_EDGES={
    "Wind speed":(1,2,4,6,8,12),
    "Temperature":(0,10,20,25,30),
    "Relative humidity":(20,40,60,80),
    "Humidity ratio":(3,6,9,12,15),
    "Absolute humidity":(3,6,9,12,15),
    "Enthalpy":(0,20,40,60,80),
    "Dynamic pressure potential":(1,5,10,25,50,100),
}
CLASS_UNITS={"Wind speed":"m/s",**{k:v[1] for k,v in METRICS.items()}}
CLASS_UNITS["Natural ventilation suitability"]=""

def class_values(df,rows,quantity,speed,nv_mask):
    if quantity=="Wind speed":
        return rows.speed
    if quantity=="Absolute humidity":
        return absolute_humidity(df).loc[rows.index]
    if quantity=="Dynamic pressure potential":
        return dynamic_pressure(df,speed).loc[rows.index]
    if quantity=="Natural ventilation suitability":
        if nv_mask is None: raise ValueError("Suitability mask required")
        v=nv_mask.reindex(rows.index).astype(float)
        return v.where(v.isin([0.,1.]))
    v=numeric(df,METRICS[quantity][0]).loc[rows.index]
    if quantity=="Relative humidity":
        v=v.where(v.between(0,100))
    elif quantity=="Humidity ratio":
        v=v.where(v>=0)
    return v

def class_boundaries(text):
    """Parse strictly increasing finite class edges, at most 9 boundaries."""
    try:
        values=tuple(float(v.strip()) for v in text.split(","))
    except (TypeError,ValueError) as exc:
        raise ValueError("Enter comma-separated numeric class boundaries.") from exc
    if not 1<=len(values)<=9 or not np.isfinite(values).all() or np.any(np.diff(values)<=0):
        raise ValueError("Enter 1–9 finite, strictly increasing class boundaries.")
    return values

def directional_class_table(df,*,speed="wind_speed_m_s",direction="wind_direction_deg",
                            quantity="Wind speed",radial="Hours",edges=None,nv_mask=None):
    """Mutually exclusive classes; denominator is all valid paired non-calm hours."""
    if radial not in ("Hours","Percentage"):
        raise ValueError("Class radii must be additive observation hours or percentages.")
    rows=direction_rows(df,speed,direction)
    rows["value"]=class_values(df,rows,quantity,speed,nv_mask)
    rows=rows.dropna(subset=["value"])
    if quantity=="Natural ventilation suitability":
        labels=["Not suitable","Suitable"]
        rows["class"]=pd.Categorical(rows.value.map({0.:"Not suitable",1.:"Suitable"}),categories=labels,ordered=True)
        colours=["#9CA3AF","#16834A"]
    else:
        edges=CLASS_EDGES[quantity] if edges is None else tuple(edges)
        if not 1<=len(edges)<=9 or not np.isfinite(edges).all() or np.any(np.diff(edges)<=0):
            raise ValueError("Class boundaries must be finite and strictly increasing.")
        legacy=quantity=="Wind speed" and tuple(edges)==CLASS_EDGES["Wind speed"]
        if legacy:
            labels=list(WIND_SPEED_LABELS)
            bounds=[0.,*edges,np.inf]
            colours=[WIND_SPEED_COLOR_MAP[v] for v in labels]
        else:
            labels=[f"< {edges[0]:g}"]+[f"{lo:g} – < {hi:g}" for lo,hi in zip(edges[:-1],edges[1:])]+[f"≥ {edges[-1]:g}"]
            bounds=[-np.inf,*edges,np.inf]
            from plotly.colors import sample_colorscale
            scale="RdBu_r" if quantity in ("Temperature","Enthalpy") else "YlGnBu" if quantity in ("Relative humidity","Humidity ratio","Absolute humidity") else "Viridis"
            colours=sample_colorscale(scale,np.linspace(.08,.94,len(labels)).tolist())
        rows["class"]=pd.cut(rows.value,bounds,labels=labels,right=legacy,include_lowest=legacy)
    counts=rows.groupby(["sector","class"],observed=True).size().unstack(fill_value=0).reindex(index=ANGLES,columns=labels,fill_value=0)
    hours=counts.astype(float)*native_interval_hours(df)
    total=float(hours.to_numpy().sum())
    result=hours if radial=="Hours" else hours*100/total if total>0 else hours
    result.index.name="azimuth_deg"
    result.attrs.update({"valid_hours":total,"class_colours":dict(zip(labels,colours)),"quantity":quantity,
                         "radial":radial,"unit":CLASS_UNITS[quantity]})
    return result

def directional_class_figure(table,title):
    radial=table.attrs["radial"];quantity=table.attrs["quantity"];unit=table.attrs["unit"]
    fig=go.Figure()
    radius_unit="h" if radial=="Hours" else "%"
    for label in table.columns:
        name=f"{label} {unit}".strip()
        fig.add_trace(go.Barpolar(theta=table.index,r=table[label],width=21.,name=name,
            marker=dict(color=table.attrs["class_colours"][label],line=dict(width=.5,color="rgba(110,110,110,.3)")),
            customdata=COMPASS,hovertemplate="%{customdata}<br>"+name+"<br>%{r:.2f} "+radius_unit+"<extra></extra>"))
    fig.update_layout(template="plotly_white",title=title,barmode="stack",
        legend=dict(title=dict(text=quantity),orientation="h",y=-.17),
        polar=dict(barmode="stack",angularaxis=dict(rotation=90,direction="clockwise",tickvals=ANGLES,ticktext=COMPASS),
            radialaxis=dict(rangemode="nonnegative",ticksuffix=" "+radius_unit)),
        meta={"compass_polar":True},height=730)
    return fig

def class_interpretation(table):
    total=table.attrs["valid_hours"]
    if total<=0:
        return "No coincident non-calm observations support the selected class distribution."
    direction_totals=table.sum(axis=1); sector=direction_totals.idxmax()
    dominant=direction_totals.loc[sector]
    class_totals=table.sum(axis=0)
    cls=class_totals.idxmax()
    unit=table.attrs["unit"]; radial=table.attrs["radial"]
    share=float(class_totals.loc[cls]/class_totals.sum()*100)
    dominant_share=float(dominant/direction_totals.sum()*100)
    nv=""
    if table.attrs["quantity"]=="Natural ventilation suitability":
        nv=f" Suitable conditions account for {class_totals['Suitable']/class_totals.sum()*100:.1f}% of the classified hours."
    return (f"Wind from {COMPASS[int(round(sector/22.5))%16]} accounts for {dominant_share:.1f}% of classified observation hours. "
            f"The most frequent {table.attrs['quantity'].lower()} class is {cls} {unit} ({share:.1f}%).{nv} "
            f"All classes partition {total:.1f} valid non-calm hours. "
            "Missing coincident inputs and calm intervals are excluded; percentage uses the sum of all classified hours, not the hours within each individual direction. "
            "Colours indicate mutually exclusive classes, not per-direction means.")


MONTHLY_WIND_ROSE_NOTE = ("Each month uses its valid non-calm coincident source records within the active data filter. "
    "Percentage is normalized separately by month; hours preserve physical source duration. "
    "Calendar months pool selected years. All panels share the radial range and colour mapping; "
    "months without valid observations remain labelled, not interpreted as zero wind.")

def monthly_wind_rose_panel(df,*,speed="wind_speed_m_s",direction="wind_direction_deg",
                           radial="Percentage",colour="Wind speed",style="Class distribution",
                           edges=None,title="Monthly wind roses"):
    """Build twelve aligned polar panels using the same single-rose ledgers."""
    from .wind_rose_selection import select_wind_rose_period
    tables={};figures={};peaks=[];colour_values=[]
    classes=style=="Class distribution"
    for month in range(1,13):
        data=select_wind_rose_period(df,month=month)
        if data.empty:continue
        if classes:
            table=directional_class_table(data,speed=speed,direction=direction,quantity=colour,radial=radial,edges=edges)
            if table.attrs["valid_hours"]<=0:continue
            one=directional_class_figure(table,"")
            peaks.append(float(table.sum(axis=1).max()))
        else:
            table=directional_table(data,speed=speed,direction=direction,radial=radial,colour=colour)
            if not table.valid_hours.gt(0).any():continue
            one=directional_figure(table,radial,colour,"")
            peaks.extend(table.radius.dropna().tolist())
            colour_values.extend(table.colour.dropna().tolist())
        tables[month]=table;figures[month]=one
    if not tables:raise ValueError("No valid coincident non-calm observations for any month.")
    max_r=max([0.,*peaks])
    # Hours: fit a common, compact upper bound to the largest stacked
    # directional total over all months. Aim for five round intervals
    # with modest headroom instead of forcing three coarse intervals.
    if radial=="Hours":
        target=max_r*1.05 if max_r>0 else 1.
        rough=target/5
        power=10.**np.floor(np.log10(rough))
        step=next(v*power for v in (1.,2.,2.5,5.,10.) if v*power>=rough-1e-12*power)
        count=max(1,int(np.ceil(target/step-1e-12)))
        upper=max(count*step,max_r)
        ticks=[i*step for i in range(1,count+1)]
    else:
        # Restore the prior auto scaling for percentage and other units.
        step=max_r/3 if max_r>0 else 1.
        power=10.**np.floor(np.log10(step))
        step=next(v*power for v in (1.,2.,2.5,5.,10.) if v*power>=step-1e-12*power)
        upper=3*step
        ticks=[step,2*step,upper]
    fig=go.Figure()
    first=min(tables)
    limits={}
    if not classes:
        if colour in ("Relative humidity","Natural ventilation suitability"):limits=dict(cmin=0.,cmax=100.)
        else:
            lo,hi=min(colour_values),max(colour_values)
            if lo==hi:hi=lo+max(1.,abs(lo)*.01)
            limits=dict(cmin=lo,cmax=hi)
    month_info=[]
    for month in range(1,13):
        name="polar" if month==1 else f"polar{month}"
        polar=dict(barmode="stack" if classes else "overlay",
            angularaxis=dict(rotation=90,direction="clockwise",tickvals=ANGLES[::2],ticktext=COMPASS[::2],tickfont=dict(size=10)),
            radialaxis=dict(range=[0.,upper],tickmode="array",tickvals=ticks,
                ticktext=[f"{v:g}" if (len(ticks)-1-i)%2==0 or len(ticks)<=3 else "" for i,v in enumerate(ticks)],
                tickformat=".3g",tickfont=dict(size=9),angle=45))
        fig.update_layout(**{name:polar})
        if month not in tables:
            fig.add_trace(go.Barpolar(subplot=name,theta=[0],r=[0.],marker_color="rgba(0,0,0,0)",showlegend=False,hoverinfo="skip"))
            month_info.append((month,None))
            continue
        table=tables[month]
        valid=float(table.attrs["valid_hours"] if classes else table.valid_hours.sum())
        month_info.append((month,valid))
        for tr in figures[month].data:
            tr.subplot=name
            tr.showlegend=bool(classes and month==first)
            if classes:tr.legendgroup=str(tr.name)
            else:
                tr.marker.update(**limits,showscale=month==first)
                if month==first:tr.marker.colorbar.update(x=1.02,y=.5,len=.76,thickness=14)
            fig.add_trace(tr)
    fig.update_layout(template="plotly_white",title=title,height=1180,barmode="stack" if classes else "overlay",
        legend=dict(orientation="h",xref="container",x=.5,xanchor="center",yref="container",y=.01,yanchor="bottom",
                    title=dict(text=f"{colour} classes · radius [{RADIAL_UNITS[radial]}]")),
        margin=dict(l=38,r=34 if classes else 125,t=70,b=88 if classes else 35),
        meta={"compass_polar":True,"layout_kind":"monthly_wind_rose_panel","wind_months":month_info,
              "wind_panel_classes":classes,"wind_radial_unit":RADIAL_UNITS[radial]})
    reflow_monthly_wind_roses(fig,columns=3)
    return fig,tables

def reflow_monthly_wind_roses(fig,*,columns=3,font_size=12):
    """Keep all polar domains intact when laying out browser/print panels."""
    meta=fig.layout.meta
    if not isinstance(meta,dict) or meta.get("layout_kind")!="monthly_wind_rose_panel":return fig
    import calendar
    rows=12//columns
    annotations=[]
    for month,hours in meta["wind_months"]:
        row,col=divmod(int(month)-1,columns)
        x0=(col+.075)/columns;x1=(col+.925)/columns
        y0=1-(row+.91)/rows;y1=1-(row+.18)/rows
        name="polar" if month==1 else f"polar{month}"
        polar=getattr(fig.layout,name)
        polar.domain=dict(x=[x0,x1],y=[y0,y1])
        polar.angularaxis.tickfont.size=max(8,min(11,font_size*.78))
        polar.radialaxis.tickfont.size=max(7,min(9,font_size*.62))
        text=calendar.month_abbr[int(month)]+(" · no data" if hours is None else f" · {hours:g} h")
        annotations.append(dict(x=(x0+x1)/2,y=1-(row+.055)/rows,xref="paper",yref="paper",
            text=text,showarrow=False,xanchor="center",yanchor="top",font=dict(size=max(9,font_size*.9))))
    fig.update_layout(annotations=annotations)
    return fig
