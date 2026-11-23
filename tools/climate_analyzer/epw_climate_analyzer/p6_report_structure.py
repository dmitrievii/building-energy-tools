"""P6 report document structure, climate statistics and standard chart catalogue."""
from __future__ import annotations
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go

CHAPTERS={"Overview":"Climate overview","Temperature":"Temperature","Humidity and Psychrometrics":"Humidity and psychrometrics",
"Solar and Radiation":"Solar radiation","Wind and Ventilation":"Wind","Sky and Daylight":"Sky and daylight",
"Precipitation and Snow":"Precipitation and snow","Natural Ventilation":"Natural ventilation",
"Shading analysis":"Shading","HVAC and Passive Design":"HVAC and passive design","Outdoor Thermal Comfort":"Outdoor thermal comfort",
"Time Series and Overlay":"Time series and relationships","Compare Climates":"Climate comparison","Data Quality":"Data quality"}
T="dry_bulb_temperature_c";RH="relative_humidity_pct";W="humidity_ratio_g_kg";V="wind_speed_m_s";H="moist_air_enthalpy_kj_kg"
G="global_horizontal_radiation_wh_m2";D="diffuse_horizontal_radiation_wh_m2";N="direct_normal_radiation_wh_m2";P="liquid_precipitation_depth_mm"
VARIABLES={
"temperature":(T,"Air temperature","°C",False),"humidity":(RH,"Relative humidity","%",False),
"humidity_ratio":(W,"Humidity ratio","g/kg",False),"dew":("dew_point_temperature_c","Dew point","°C",False),
"enthalpy":("moist_air_enthalpy_kj_kg","Moist-air enthalpy","kJ/kg",False),
"wind":(V,"Wind speed","m/s",False),"gust":("wind_gust_speed_m_s","Wind gust","m/s",False),
"ghi":(G,"Horizontal irradiation","kWh/m²",True),"dhi":(D,"Diffuse irradiation","kWh/m²",True),
"dni":(N,"Direct normal irradiation","kWh/m²",True),"rain":(P,"Precipitation","mm",True),
"snow":("snow_depth_cm","Snow depth","cm",False),"sky":("total_sky_cover_tenths","Sky cover","tenths",False),
"sunshine":("sunshine_duration_s","Sunshine duration","h",True)}
OVERVIEW=("temperature","humidity","humidity_ratio","wind","ghi","rain")
GROUPS={"Temperature":("temperature",),"Humidity and Psychrometrics":("humidity","humidity_ratio","dew","enthalpy"),
"Solar and Radiation":("ghi","dhi","dni"),"Wind and Ventilation":("wind","gust"),"Sky and Daylight":("sky","sunshine","ghi"),
"Precipitation and Snow":("rain","snow"),"Natural Ventilation":("temperature","humidity_ratio","wind"),
"Shading analysis":("ghi","dni","temperature"),"HVAC and Passive Design":("temperature","humidity_ratio","enthalpy"),
"Outdoor Thermal Comfort":("temperature","humidity","wind","ghi"),"Time Series and Overlay":OVERVIEW,"Overview":OVERVIEW}
def numeric(df,c):
    if c not in df:return pd.Series(np.nan,index=df.index)
    s=pd.to_numeric(df[c],errors="coerce").replace([np.inf,-np.inf],np.nan)
    if c in (G,D,N,P,V,W,"wind_gust_speed_m_s","snow_depth_cm","sunshine_duration_s"):s=s.where(s>=0)
    if c==RH:s=s.where(s.between(0,100))
    return s

def statistics(df,keys=OVERVIEW):
    rows=[]
    if df is None or not len(df):return rows
    monthly=str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly"
    for key in keys:
        c,label,u,total=VARIABLES[key];s=numeric(df,c).dropna()
        if s.empty:continue
        coverage=f"{len(s):,} / {len(df):,}"
        if total:
            factor=1/1000 if key in ("ghi","dhi","dni") else 1/3600 if key=="sunshine" else 1
            rows.append([label,f"{s.sum()*factor:,.1f} {u} (total)",coverage])
        else:
            mean="Mean of monthly values" if monthly else "Mean"
            rows.append([label,f"{mean} {s.mean():,.1f} {u}; range {s.min():,.1f} to {s.max():,.1f} {u}",coverage])
    return rows

def capture_statistics(df,page):
    return {"overview":statistics(df),"chapter":statistics(df,GROUPS.get(page,OVERVIEW))}

def chapter_name(item):
    p=item["context"].get("page","Overview")
    return CHAPTERS.get(p,p)

def scope_key(context):
    return tuple(str(context.get(k,"")) for k in (
        "source id","source","location","first timestamp","last timestamp",
        "selected records","native interval minutes","time basis","filter",
        "pressure mode","custom pressure","quality policy",
        "temperature thresholds",
    ))

def ordered_groups(items):
    """Follow the scientific report chapter sequence; retain saved order within each."""
    groups={}
    for item in items:groups.setdefault(chapter_name(item),[]).append(item)
    chapter_order=list(dict.fromkeys(CHAPTERS.values()))
    ordered=[(c,groups[c]) for c in chapter_order if c in groups]
    return ordered+[(c,entries) for c,entries in groups.items() if c not in chapter_order]

def contexts(items):
    unique={}
    for item in items:
        c=item["context"];key=scope_key(c)
        if key not in unique:
            unique[key]={**c,"statistics":{"overview":[],"chapter":[]}}
        entry=unique[key]
        for field in ("latitude","longitude","elevation_m","station_id"):
            if field in c:entry.setdefault(field,c[field])
        for field in ("overview","chapter"):
            seen={row[0] for row in entry["statistics"][field]}
            entry["statistics"][field].extend(row for row in c.get("statistics",{}).get(field,[]) if row[0] not in seen)
    return list(unique.values())

def concise_context(c):
    a=str(c.get("first timestamp",""));b=str(c.get("last timestamp",""))
    period=(f"{a[:10]} – {b[:10]}" if a[11:16]=="00:00" and b[11:16] in ("23:00","23:50","23:59","00:00")
            else f"{a[:16]} – {b[:16]}") if a and b else ""
    try:spec=json.loads(c.get("filter","{}"))
    except (TypeError,ValueError):spec={}
    restrictions=[]
    months=spec.get("months")
    if isinstance(months,list) and sorted(months)!=list(range(1,13)):restrictions.append("Months "+", ".join(map(str,months)))
    hours=spec.get("hours")
    if isinstance(hours,list) and hours and sorted(hours)!=list(range(24)):restrictions.append(f"Hours {min(hours):02d}:00–{max(hours):02d}:59" if sorted(hours)==list(range(min(hours),max(hours)+1)) else "Hours "+", ".join(map(str,hours)))
    return " · ".join(x for x in (str(c.get("location","")),str(c.get("source","")),period,*restrictions) if x)

def site_details(c):
    rows=[]
    for k,label,unit in (("latitude","Latitude","°"),("longitude","Longitude","°"),("elevation_m","Elevation"," m")):
        try:v=float(c.get(k));assert math.isfinite(v)
        except (TypeError,ValueError,AssertionError):continue
        rows.append([label,f"{v:.3f}{unit}" if unit=="°" else f"{v:.0f}{unit}",""])
    return rows

def locator_figure(c):
    """Offline regional map, locally distance-proportional longitude/latitude."""
    try:lat=float(c.get("latitude"));lon=float(c.get("longitude"))
    except (TypeError,ValueError):return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180):return None
    data=json.loads((Path(__file__).parent/"p6_world_boundaries.json").read_text("utf-8"))
    cosine=max(.08,math.cos(math.radians(lat)))
    half_y=4.;half_x=min(60.,5.7/cosine)
    x0,x1=lon-half_x,lon+half_x
    y0,y1=max(-90,lat-half_y),min(90,lat+half_y)
    xs=[];ys=[]
    for ring in data["outlines"]:
        pts=[(lon+((x-lon+180)%360)-180,y) for x,y in ring]
        if max(y for x,y in pts)<y0 or min(y for x,y in pts)>y1 or max(x for x,y in pts)<x0 or min(x for x,y in pts)>x1:continue
        # Do not close a polygon across the longitude discontinuity.
        if any(abs(x-prev)>180 for (prev,_),(x,_) in zip(pts,pts[1:])):
            continue
        xs.extend(x for x,y in pts);ys.extend(y for x,y in pts)
        xs.append(None);ys.append(None)
    f=go.Figure(go.Scatter(x=xs,y=ys,mode="lines",fill="toself",fillcolor="#F4F1E7",
        line=dict(color="#9AA7A4",width=.85),hoverinfo="skip",showlegend=False))
    for country in data.get("labels",[]):
        name,x,y=country
        x=lon+((x-lon+180)%360)-180
        if x0+.15*half_x<x<x1-.15*half_x and y0+.15*half_y<y<y1-.15*half_y and math.hypot((x-lon)*cosine,y-lat)>.65:
            f.add_annotation(x=x,y=y,text=name,showarrow=False,font=dict(size=10,color="#566760"))
    f.add_scatter(x=[lon],y=[lat],mode="markers+text",text=[str(c.get("location","Station"))],
                  textposition="top center",marker=dict(size=11,color="#B93F37",line=dict(color="white",width=1.5)),showlegend=False)
    f.update_layout(template="plotly_white",plot_bgcolor="#DDEBF2",title="Station location",
        meta={"report_kind":"station_locator","latitude":lat},
        margin=dict(l=12,r=12,t=12,b=12),
        xaxis=dict(range=[x0,x1],scaleanchor="y",scaleratio=cosine,constrain="domain",visible=False,fixedrange=True),
        yaxis=dict(range=[y0,y1],constrain="domain",visible=False,fixedrange=True),height=440,width=650)
    return f

def zone_legend_entries(fig):
    """Lossless printed key for visible Givoni-Milne legend entries, in rank order."""
    if fig.layout.showlegend is False or getattr(getattr(fig.layout,"legend2",None),"visible",None) is False:return []
    entries=[]
    for t in fig.data:
        if getattr(t,"legend",None)!="legend2" or getattr(t,"showlegend",None) is False or getattr(t,"visible",None) in (False,"legendonly"):continue
        if not (getattr(t,"legendgroup",None) or "").startswith("givoni_zone_"):continue
        entries.append((getattr(t,"legendrank",1000) or 1000,str(t.name),str(getattr(t,"fillcolor",None) or "#F1F5F9")))
    return sorted(entries,key=lambda x:x[0])

def complex_figure(fig):
    from .extended_visualization import diurnal_panel_rows
    return bool(diurnal_panel_rows(fig)) or bool(zone_legend_entries(fig)) or any(getattr(t,"type","") in ("scatterpolar","scatterpolargl","barpolar","scatter3d","surface","mesh3d","cone") for t in fig.data)

def figure_height(fig,width_pt,height_pt):
    """Give scientific polar/psychrometric plots most of the printable page."""
    from .extended_visualization import diurnal_panel_rows
    if isinstance(fig.layout.meta,dict) and fig.layout.meta.get("layout_kind")=="monthly_wind_rose_panel":
        return height_pt*.90
    if diurnal_panel_rows(fig):
        return min(height_pt*.88,width_pt*.98)
    if complex_figure(fig):
        return min(height_pt*.83,width_pt*.92)
    return min(height_pt*.69,width_pt*.74,460.)

def report_figure(fig,*,width_pt,height_pt,font_pt=11,external_zone_legend=False):
    """Physical-size clone with chart-specific print reflow, preserving data/colors."""
    raw=go.Figure(fig).to_plotly_json()
    px=font_pt*96/72
    def restyle(obj):
        if isinstance(obj,dict):
            for k,v in obj.items():
                if isinstance(v,dict) and k in ("font","tickfont","textfont","insidetextfont","outsidetextfont","uniformtext"):
                    if k=="uniformtext":v["minsize"]=px
                    else:
                        v["size"]=px
                        v["family"]="Arial"
                restyle(v)
        elif isinstance(obj,(list,tuple)):
            for v in obj:restyle(v)
    restyle(raw)
    f=go.Figure(raw)
    from .extended_visualization import diurnal_panel_rows,reflow_diurnal_panels
    if diurnal_panel_rows(f):
        # Mark legacy saved snapshots before stripping the report title.
        meta=dict(f.layout.meta) if isinstance(f.layout.meta,dict) else {}
        meta.update(layout_kind="diurnal_small_multiples",unit=f.layout.yaxis.title.text or meta.get("unit",""))
        f.update_layout(meta=meta)
    names=[str(getattr(t,"name","") or "").lower() for t in f.data]
    if any("heating degree" in n for n in names) and any("cooling degree" in n for n in names):
        from .degree_metrics import degree_legend_below
        degree_legend_below(f)
    # Normalize legacy snapshots while their original title is still present.
    # In particular, pre-metadata daylight figures are recognized by title.
    from .calendar_heatmap_axes import apply_calendar_heatmap_axes,apply_monthly_axes
    apply_calendar_heatmap_axes(f);apply_monthly_axes(f)
    w,h=round(width_pt*96/72),round(height_pt*96/72)
    f.update_layout(width=w,height=h,autosize=False,font=dict(family="Arial",size=px),
                    paper_bgcolor="white",title_text=None,margin=dict(t=12,autoexpand=True))
    is_map=isinstance(f.layout.meta,dict) and f.layout.meta.get("report_kind")=="station_locator"
    if is_map:
        f.update_layout(margin=dict(l=8,r=8,t=8,b=8))
        return f
    f.update_xaxes(automargin=True,tickfont_size=px,title_font_size=px)
    f.update_yaxes(automargin=True,tickfont_size=px,title_font_size=px)
    zones=zone_legend_entries(f)
    if zones:
        if external_zone_legend:
            for t in f.data:
                if getattr(t,"legend",None)=="legend2":t.showlegend=False
            f.update_layout(legend2=dict(visible=False))
            f.update_xaxes(domain=[0.,1.])
        else:
            # Interactive standalone figure: move the secondary legend away
            # from the data rectangle and keep its entries visible.
            f.update_layout(legend2=dict(orientation="h",xref="container",x=.02,xanchor="left",
                            yref="container",y=.01,yanchor="bottom"))
            f.update_xaxes(domain=[0.,1.])
    if isinstance(f.layout.meta,dict) and f.layout.meta.get("layout_kind")=="monthly_wind_rose_panel":
        from .directional_climate import reflow_monthly_wind_roses
        classes=f.layout.meta.get("wind_panel_classes")
        small_font=max(9,min(12,px*.82))
        f.update_layout(margin=dict(l=18,r=18 if classes else 96,t=12,b=68 if classes else 18),
            legend=dict(orientation="h",xref="container",x=.5,xanchor="center",yref="container",y=.005,yanchor="bottom",font=dict(size=small_font),title=dict(font=dict(size=small_font))))
        return reflow_monthly_wind_roses(f,columns=4 if w>h*1.12 else 3,font_size=small_font)
    polar=any(getattr(t,"type","") in ("scatterpolar","scatterpolargl","barpolar") for t in f.data)
    if polar:
        # A polar circle is height-limited. Place it at the left of the
        # canvas with a compact legend to its right when width permits.
        traces=[t for t in f.data if getattr(t,"showlegend",None) is not False and getattr(t,"visible",None) not in (False,"legendonly") and (getattr(t,"legend",None) or "legend")=="legend"]
        max_chars=max((len(str(t.name or "")) for t in traces),default=0)
        legend_w=max(100,round(max_chars*px*.61+58))
        bars=[]
        for t in f.data:
            props=t.to_plotly_json()
            if props.get("showscale") and "colorbar" in props:bars.append(t.colorbar)
            if props.get("marker",{}).get("showscale"):bars.append(t.marker.colorbar)
        bar_w=90 if bars else 0
        side=bool(traces) and f.layout.showlegend is not False and w-legend_w-bar_w-40>=min(h*.72,350)
        if side and len(traces)*(px+6)+32<h-24:
            stop=max(.45,min(.85,(w-legend_w-bar_w-24)/w))
            f.update_layout(margin=dict(l=20,r=12,t=18,b=18,autoexpand=False),
                polar=dict(domain=dict(x=[0,stop],y=[.03,.97])),
                legend=dict(orientation="v",xref="paper",x=min(.99,stop+(bar_w+12)/max(1,w-32)),xanchor="left",yref="paper",y=.95,yanchor="top",font=dict(size=px)))
            for bar in bars:
                bar.update(xref="paper",x=stop+.015,xanchor="left",y=.52,len=.70,thickness=12)
        else:
            f.update_layout(margin=dict(l=28,r=bar_w+20,t=18,b=72),
                legend=dict(orientation="h",xref="container",x=.5,xanchor="center",yref="container",y=.005,yanchor="bottom"))
            for bar in bars:bar.update(x=1.02,xanchor="left",len=.68,thickness=12)
    else:
        # Recompute bottom-legend reservation for the actual print canvas,
        # not the original browser height. Axis title and legend cannot share
        # the same negative paper-coordinate offset.
        from .chart_presentation import ChartPresentationSettings,_space_bottom_legends
        props=f.layout.to_plotly_json()
        for name in props:
            if name.startswith("legend"):
                legend=getattr(f.layout,name)
                if legend.orientation=="h" and (legend.y is None or legend.y<=.1):
                    legend.update(yref="container",y=.006,yanchor="bottom",xref="container",x=.5,xanchor="center")
        f.update_layout(margin=dict(b=max(58,round(px*4)),l=max(48,int(f.layout.margin.l or 0)),r=max(18,min(80,int(f.layout.margin.r or 0)))))
        settings=ChartPresentationSettings(canvas="Custom",custom_width=w,custom_height=h,font_size=round(px))
        _space_bottom_legends(f,settings,round(px))
        if zones and not external_zone_legend:
            # reserve the full visible zone key; externally printed PDF
            # uses the more space-efficient document legend instead.
            chars=sum(len(name)+7 for _,name,_ in zones)
            rows=max(1,math.ceil(chars*px*.59/max(100,w-100)))
            f.layout.margin.b=max(f.layout.margin.b or 0,round((rows+3)*(px+7)))
            f.layout.legend.update(yref="paper",y=1.035,yanchor="bottom")
            f.layout.margin.t=max(46,round(px*3))
    return reflow_diurnal_panels(f,font_size=px)

def source_interpretation(df,page,column="",label="",unit="",*,thresholds=(18.,26.),kind=""):
    """Use the same interpretation functions as the analysis pages, with
    conservative capability checks (no invented unavailable variables)."""
    from . import interpretations as i
    from .extended_visualization import hourly_capable
    if not hourly_capable(df):return ""
    good=lambda *cols:all(c in df and numeric(df,c).notna().any() for c in cols)
    if kind=="psychrometric" and good(W,"moist_air_enthalpy_kj_kg"):
        return i.psychrometric_interpretation(df)
    if page=="Solar and Radiation" and kind not in ("profile","percentile","duration","histogram","box","violin","heatmap","diurnal","occurrence") and good(G,D,T):
        return i.solar_interpretation(df).replace("Annual horizontal irradiation","Selected-period horizontal irradiation")
    if page=="Wind and Ventilation" and good(V) and not column:return i.wind_interpretation(df)
    if page=="Sky and Daylight" and good("total_sky_cover_tenths") and not column:return i.sky_interpretation(df)
    if page=="HVAC and Passive Design" and good(T,W) and not column:return i.hvac_interpretation(df)
    if column and good(column) and column not in ("wind_direction_deg","wind_gust_direction_deg"):
        # Same statistical interpretation as generic explorer; explicitly
        # use the palette thresholds for dry-bulb temperature.
        kw=dict(high_threshold=thresholds[1],low_threshold=thresholds[0]) if column==T else {}
        return i.variable_interpretation(df,column,label or column,unit,**kw)
    if page=="Temperature" and good(T):return i.temperature_interpretation(df,*thresholds)
    return ""

def temperature_thresholds(context):
    try:
        a,b=map(float,context.get("temperature thresholds",(18.,26.)))
        if np.isfinite([a,b]).all() and a<=b:return a,b
    except (ValueError,TypeError):pass
    return 18.,26.

CATALOG=[
("temperature_profile","Temperature","Monthly temperature profile",T,"°C","profile"),
("temperature_duration","Temperature","Temperature duration curve",T,"°C","duration"),
("temperature_heatmap","Temperature","Month–hour temperature",T,"°C","heatmap"),
("humidity_profile","Humidity and Psychrometrics","Monthly relative humidity",RH,"%","profile"),
("humidity_ratio","Humidity and Psychrometrics","Monthly humidity ratio",W,"g/kg","profile"),
("psychrometric","Humidity and Psychrometrics","Psychrometric distribution",W,"g/kg","psychrometric"),
("ghi","Solar and Radiation","Monthly horizontal irradiation",G,"kWh/m²","total"),
("facade","Solar and Radiation","Vertical façade irradiation",G,"kWh/m²","facade"),
("solar_exposure","Solar and Radiation","Façade solar exposure by outdoor temperature",G,"kWh/m²","facade_temperature"),
("sunpath","Solar and Radiation","Sun path",N,"Wh/m²","sunpath"),
("wind_rose","Wind and Ventilation","Wind rose",V,"m/s","windrose"),
("wind_orientation","Wind and Ventilation","Seasonal windward/exhaust orientation screening",V,"%","wind_orientation"),
("wind_rose_panel","Wind and Ventilation","Monthly wind rose panel (12 months)",V,"%","wind_panel"),
("wind_speed","Wind and Ventilation","Monthly wind speed",V,"m/s","profile"),
("daylight","Sky and Daylight","Daylight envelope",T,"h","daylight"),
("sky_cover","Sky and Daylight","Monthly sky-cover conditions","total_sky_cover_tenths","h","sky_conditions"),
("exterior_light","Sky and Daylight","Exterior daylight availability","global_horizontal_illuminance_lux","h","illumination"),
("sunshine_ratio","Sky and Daylight","Sunshine share of astronomical daylight","sunshine_duration_s","%","relative_sunshine"),
("rain","Precipitation and Snow","Monthly precipitation",P,"mm","total"),
("rain_severity","Precipitation and Snow","Monthly precipitation-day severity",P,"days","rain_days"),
("rain_wind","Precipitation and Snow","Wind-driven rain by incoming sector",P,"mm·m/s","wind_rain"),
("snow_cover","Precipitation and Snow","Observed snow-cover hours","snow_depth_cm","h","snow_hours"),
("climograph","Precipitation and Snow","Walter–Lieth diagram",P,"mm","climograph"),
("snow","Precipitation and Snow","Monthly snow depth","snow_depth_cm","cm","profile"),
("nv","Natural Ventilation","Monthly natural ventilation suitability",W,"h","nv"),
("night","Natural Ventilation","Night-flushing availability",T,"h","night"),
("degree","HVAC and Passive Design","Heating and cooling degree days",T,"K·d","degree"),
("hvac_energy","HVAC and Passive Design","Outdoor-air conditioning · reference energy",T,"kWh","hvac_energy"),
("hvac_economizer","HVAC and Passive Design","Air-side economizer · climatic screening",H,"h","hvac_economizer"),
("hvac_design_hot","HVAC and Passive Design","Dry-bulb temperature · upper-tail design conditions",T,"°C","hvac_design_hot"),
("hvac_design_cold","HVAC and Passive Design","Dry-bulb temperature · lower-tail design conditions",T,"°C","hvac_design_cold"),
("hvac_critical","HVAC and Passive Design","Persistent hot-weather sequences · 72 hours",T,"°C","hvac_critical"),
("shade","Shading analysis","Solar protection screening",G,"h","shade"),
("shading_energy","Shading analysis","Reference window · monthly direct interception",G,"kWh/m²","shading_ledger"),
("shading_orientation","Shading analysis","Shading performance across eight façades",G,"kWh/m²","shading_orientation"),
("utci","Outdoor Thermal Comfort","Monthly UTCI stress",T,"h","utci"),
("utci_shading","Outdoor Thermal Comfort","Outdoor thermal exposure · direct-beam shade benefit",T,"K","utci_shading")]
PRESETS={"Architectural climate study":("temperature_profile","temperature_heatmap","psychrometric","ghi","facade","solar_exposure","sunpath","wind_rose","wind_orientation","daylight","sky_cover","exterior_light","rain","rain_severity","rain_wind","snow_cover","climograph","nv","night","shade","shading_energy","shading_orientation"),
"Climate overview":("temperature_profile","humidity_profile","ghi","wind_rose","sky_cover","rain","rain_severity","rain_wind","climograph"),
"Passive design":("temperature_heatmap","psychrometric","facade","solar_exposure","wind_rose","wind_orientation","sky_cover","exterior_light","nv","night","shade","shading_energy","shading_orientation","utci","utci_shading"),
"HVAC & engineering":("temperature_profile","temperature_duration","humidity_ratio","psychrometric","wind_speed","degree","hvac_energy","hvac_economizer","hvac_design_hot","hvac_design_cold","hvac_critical","nv","night","utci"),
"All standard diagrams":tuple(x[0] for x in CATALOG)}

def available_catalog(df,context):
    if df is None or df.empty:return []
    monthly=str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly"
    def has(*cols):
        return all(numeric(df,c).notna().any() for c in cols)
    requirements={"psychrometric":(T,RH,W),"sky_conditions":("total_sky_cover_tenths",),
       "illumination":("global_horizontal_illuminance_lux",),
       "relative_sunshine":("sunshine_duration_s",),
       "shading_ledger":(G,D,N,"solar_apparent_zenith_deg","solar_azimuth_deg"),
       "shading_orientation":(G,D,N,"solar_apparent_zenith_deg","solar_azimuth_deg",T),
       "facade":(G,D,N,"solar_apparent_zenith_deg","solar_azimuth_deg"),
       "facade_temperature":(G,D,N,"solar_apparent_zenith_deg","solar_azimuth_deg",T),
       "sunpath":(N,"solar_apparent_zenith_deg","solar_azimuth_deg"),"windrose":(V,"wind_direction_deg"),"wind_panel":(V,"wind_direction_deg"),"wind_orientation":(V,"wind_direction_deg"),
       "climograph":(T,P),"rain_days":(P,),"wind_rain":(P,V,"wind_direction_deg"),
       "hvac_energy":(T,W,"specific_volume_m3_kg"),
       "hvac_economizer":(T,H),
       "hvac_design_hot":(T,),"hvac_design_cold":(T,),"hvac_critical":(T,),
       "utci_shading":(T,RH,V,G,D,N,"solar_apparent_zenith_deg",
                        "horizontal_infrared_radiation_intensity_wh_m2"),
       "snow_hours":("snow_depth_cm",),
       "nv":(T,W),"night":(T,),"degree":(T,),"shade":(T,G),"utci":(T,RH,V)}
    out=[]
    for entry in CATALOG:
        id,page,label,c,u,kind=entry
        if monthly and kind not in ("profile","total","climograph"):continue
        if kind in ("daylight","relative_sunshine"):
            try:latitude_ok=math.isfinite(float(context.get("latitude")))
            except (ValueError,TypeError):latitude_ok=False
            ok=latitude_ok
            if ok and kind=="relative_sunshine":
                from .daylight import _complete_daily_sunshine_hours
                from .aggregations import native_interval_hours
                ok=has("sunshine_duration_s") and not _complete_daily_sunshine_hours(
                    df["sunshine_duration_s"],interval_hours=native_interval_hours(df)).empty
        elif kind=="rain_days":
            from .precipitation import complete_daily_precipitation
            ok=has(P) and complete_daily_precipitation(df).notna().any()
        elif kind=="snow_hours":
            ok=has("snow_depth_cm") and numeric(df,"snow_depth_cm").gt(0).any()
        else:ok=has(*requirements.get(kind,(c,)))
        if ok:out.append(entry)
    return out

def standard_figure(entry,df,context,reference_df=None):
    """One documented reference configuration per standard diagram."""
    from .charts import profile_ribbon_chart,duration_chart,month_hour_heatmap,psychrometric_chart,sun_path_chart
    id,page,label,column,unit,kind=entry
    s=numeric(df,column)
    monthly=str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly"
    if kind=="profile":
        if monthly:
            fig=go.Figure(go.Scatter(x=s.index,y=s,mode="lines+markers",connectgaps=False))
            fig.update_layout(template="plotly_white",title=label,yaxis_title=unit)
        else:fig=profile_ribbon_chart(df,column,"Monthly",label,unit)
        note="Monthly values summarize the observed source samples; their range identifies seasonal variability."
    elif kind=="duration":
        fig=duration_chart(df,column,label,unit);note="Ranked valid source observations in descending order."
    elif kind=="heatmap":
        from .charts import TEMPERATURE_HEATMAP_COLUMNS
        bounds=temperature_thresholds(context) if column in TEMPERATURE_HEATMAP_COLUMNS else None
        fig=month_hour_heatmap(df,column,label,unit,temperature_thresholds=bounds)
        note="Mean observed temperature by month and hour."
        if bounds:note+=f" Temperature classes use {bounds[0]:g}/{bounds[1]:g} °C heating/cooling thresholds (blue/green/red)."
    elif kind=="psychrometric":
        pressure=numeric(df,"atmospheric_station_pressure_pa").dropna()
        p=float(pressure.median()) if len(pressure) else 101325.
        try:p=float(context["guide pressure Pa"])
        except (ValueError,KeyError,TypeError):pass
        if "pressure mode" in context and "Normal pressure" in context["pressure mode"]:p=101325.
        if "Custom constant" in context.get("pressure mode",""):
            try:p=float(context["custom pressure"])
            except (ValueError,KeyError):pass
        fig=psychrometric_chart(df,pressure_pa=p,data_mode="Climate zone");note=f"T–d distribution, reference guide pressure {p:.0f} Pa. Reference guides help relate seasonal moisture and temperature combinations to candidate passive strategies."
    elif kind=="rain_days":
        from .precipitation_findings import rain_day_classes,rain_day_classes_figure
        table=rain_day_classes(df)
        if table.empty:raise ValueError("No complete precipitation days support the severity chart.")
        fig=rain_day_classes_figure(table)
        note="Disjoint daily precipitation classes: 1–<10, 10–<20 and ≥20 mm on complete observed calendar days."
    elif kind=="wind_rain":
        from .directional_climate import directional_table,directional_figure,directional_interpretation
        table=directional_table(df,radial="Wind-driven rain exposure",colour="Wind speed")
        fig=directional_figure(table,"Wind-driven rain exposure","Wind speed",label)
        note=directional_interpretation(table,"Wind-driven rain exposure","Wind speed")
    elif kind=="snow_hours":
        from .aggregations import native_interval_hours
        snow=numeric(df,"snow_depth_cm")
        mask=snow.gt(0).astype(float).where(snow.notna())*native_interval_hours(df)
        monthly=mask.resample("MS").sum(min_count=1)
        fig=go.Figure(go.Bar(x=monthly.index,y=monthly,marker_color="#5488B6"))
        fig.update_layout(template="plotly_white",title=label,xaxis_title="Month",yaxis_title="Observed snow-cover hours")
        note="Observed snow-depth records above 0 cm, integrated at the active source cadence."
    elif kind=="total":
        x=s.resample("MS").sum(min_count=1)/(1000 if column==G else 1)
        fig=go.Figure(go.Bar(x=x.index,y=x,marker_color="#D6A23D" if column==G else "#5488B6"))
        fig.update_layout(template="plotly_white",title=label,yaxis_title=unit)
        note="Observed selected-period totals; incomplete periods may underestimate the total."
    elif kind=="facade_temperature":
        from .solar_findings import facade_temperature_table,facade_temperature_figure,facade_temperature_interpretation
        from .extended_visualization import hourly_capable
        if not hourly_capable(df):
            raise ValueError("Façade solar–temperature exposure requires subdaily observations.")
        lo,hi=temperature_thresholds(context)
        table=facade_temperature_table(df,cold_c=lo,hot_c=hi)
        fig=facade_temperature_figure(table,cold_c=lo,hot_c=hi)
        note=facade_temperature_interpretation(table,cold_c=lo,hot_c=hi)
        note+=" Model: unobstructed isotropic POA, default ground albedo 0.20."
    elif kind=="shading_ledger":
        from .solar_shading import shading_ledger,monthly_shading_figure
        from .p66_catalogue import GEOMETRY
        from .shading_findings import shading_ledger_interpretation
        ledger=shading_ledger(df,**GEOMETRY)
        fields=["Unshaded total","Shaded total (direct-only)","Intercepted direct"]
        monthly=pd.DataFrame({
            key:ledger[key].resample("MS").sum(min_count=1)/1000.
            for key in fields})
        fig=monthly_shading_figure(monthly,monthly.index.strftime("%b %Y"))
        note=shading_ledger_interpretation(ledger,df,geometry=GEOMETRY)
    elif kind=="shading_orientation":
        from .p66_catalogue import GEOMETRY
        from .shading_findings import (
            orientation_shading_table,orientation_shading_figure,
            orientation_shading_interpretation)
        lo,hi=temperature_thresholds(context)
        table=orientation_shading_table(df,geometry=GEOMETRY,cold_c=lo,hot_c=hi)
        fig=orientation_shading_figure(table,cold_c=lo,hot_c=hi)
        note=orientation_shading_interpretation(table,cold_c=lo,hot_c=hi)
        note+=" Reference window: south-oriented 2 × 1.5 m, 0.6 m overhang and zero side fins; identical geometry is rotated for all eight orientations."
    elif kind=="facade":
        from .facade_orientation import orientation_period_components,orientation_components_chart
        a,f=orientation_period_components(df,tilt_deg=90.)
        fig=orientation_components_chart(a,f,tilt_deg=90.,style="Bar chart",selected=())
        note="Unobstructed vertical POA; isotropic diffuse model and default ground albedo."
    elif kind=="sunpath":fig=sun_path_chart(df);note="Solar position and direct-normal radiation for selected source records."
    elif kind=="wind_orientation":
        from .wind_findings import wind_opportunity,wind_opportunity_figure,wind_design_interpretation
        summary,sectors=wind_opportunity(df,min_speed_m_s=.5)
        fig=wind_opportunity_figure(summary,sectors)
        note=wind_design_interpretation(df,min_speed_m_s=.5)
        note+=" The 0.5 m/s source-wind threshold identifies directional outdoor wind availability. Façade pressure coefficients, opening areas, and interior flow paths resolve the corresponding building ventilation response."
    elif kind=="wind_panel":
        from .directional_climate import monthly_wind_rose_panel,MONTHLY_WIND_ROSE_NOTE
        fig,_=monthly_wind_rose_panel(df,title=label);note=MONTHLY_WIND_ROSE_NOTE
    elif kind=="windrose":
        from .directional_climate import directional_class_table,directional_class_figure,class_interpretation
        table=directional_class_table(df,radial="Percentage",quantity="Wind speed")
        fig=directional_class_figure(table,label);note=class_interpretation(table)
    elif kind=="daylight":
        from .extended_visualization import daylight_envelope
        fig=daylight_envelope(df.index,float(context["latitude"]))
        note="Sunrise–sunset envelope calculated for the represented latitude and calendar dates."
    elif kind=="sky_conditions":
        from .extended_visualization import sky_distribution,occurrence_figure
        table=sky_distribution(df)
        table.columns=["Clear","Intermediate","Overcast"]
        fig=occurrence_figure(table,"","Hours")
        fig.update_layout(title=label)
        note="Observed total sky-cover intervals grouped into clear (0–2), intermediate (above 2 and below 8), and overcast (8–10 tenths) conditions."
    elif kind=="illumination":
        from .aggregations import threshold_count_by_period
        from .sky_findings import illuminance_interpretation
        light=numeric(df,column)
        counts=threshold_count_by_period(df,light.ge(10000.)&light.notna(),"Monthly",label="hours")
        fig=go.Figure(go.Bar(x=counts.index,y=counts["hours"]))
        fig.update_layout(template="plotly_white",title=label,
            xaxis_title="Month",yaxis_title="Hours ≥10,000 lux")
        note=illuminance_interpretation(df,column,threshold_lux=10000.)
    elif kind=="relative_sunshine":
        from .daylight import monthly_daylight_sunshine_summary
        from .sky_findings import sunshine_interpretation
        table=monthly_daylight_sunshine_summary(df,float(context["latitude"]))
        if "relative_sunshine_pct" not in table or not table.relative_sunshine_pct.notna().any():
            raise ValueError("Complete sunshine days and site latitude are required.")
        fig=go.Figure(go.Bar(x=table["month"],y=table["relative_sunshine_pct"]))
        fig.update_layout(template="plotly_white",title=label,
            xaxis_title="Month",yaxis_title="Measured sunshine / astronomical daylight [%]")
        note=sunshine_interpretation(df,latitude=float(context["latitude"]),kind="relative_sunshine")
    elif kind=="climograph":
        from .extended_visualization import climate_summary_table,climate_summary_figure,climate_summary_interpretation
        table=climate_summary_table(df);fig=climate_summary_figure(table,"Walter–Lieth diagram");note=climate_summary_interpretation(table,"Walter–Lieth diagram")
    elif kind in ("nv","night","degree","shade"):
        from .p6_dashboard import design_ledgers
        ledger,degree=design_ledgers(df,reference_df=reference_df)
        fig=go.Figure()
        if kind=="degree":
            if degree.empty or not degree.notna().any().any():raise ValueError("No complete valid daily temperature observations.")
            for c in degree:fig.add_bar(x=degree.index,y=degree[c],name=c)
            note="HGT 20/12; KGT 26/26, complete daily mean observations. Selected-period degree-day totals express the duration and intensity of outdoor temperature exposure."
        else:
            c={"nv":"Natural ventilation","night":"Night flushing","shade":"Solar protection screening"}[kind]
            if c not in ledger or not ledger[c].notna().any():raise ValueError("No valid candidate hours.")
            a=ledger[c].resample("MS").sum(min_count=1)
            fig.add_bar(x=a.index,y=a,marker_color="#21866B")
            note={"nv":"Reference outdoor-air screening uses 16–26 °C and humidity ratio ≤9 g/kg.",
                  "night":"Nighttime 22:00–06:59, cool outdoor air ≤20 °C following a complete day reaching ≥26 °C.",
                  "shade":"Air temperature ≥24 °C and mean horizontal irradiance ≥250 W/m² identify coincident warm, sunny hours relevant to exterior solar protection."}[kind]
        fig.update_layout(template="plotly_white",title=label,barmode="group",yaxis_title=unit)
        if kind=="degree":
            from .degree_metrics import degree_legend_below
            degree_legend_below(fig)
    elif kind=="hvac_energy":
        from .p3_comfort import ventilation_loads
        from .hvac_findings import conditioning_monthly_figure,conditioning_interpretation
        q=ventilation_loads(df,airflow=1000.,heat=20.,cool=26.,w_low=4.,w_high=9.)
        fig=conditioning_monthly_figure(df,q,grouped=True,title=label)
        note=conditioning_interpretation(df,q,airflow=1000.,heat=20.,
                                         cool=26.,w_low=4.,w_high=9.)
    elif kind=="hvac_economizer":
        from .hvac_findings import economizer_stages,economizer_stages_figure,economizer_interpretation
        fig=economizer_stages_figure(economizer_stages(df,h_return=50.))
        note=economizer_interpretation(df,h_return=50.)
    elif kind in ("hvac_design_hot","hvac_design_cold"):
        from .p4_extremes import design_conditions
        from .hvac_findings import design_quantile_figure,design_quantile_interpretation
        upper=kind=="hvac_design_hot"
        table=design_conditions(df,T,[.4,1.,2.,5.],upper=upper,
                                coincident=[c for c in (W,H,RH,V) if numeric(df,c).notna().any()])
        if table.empty:raise ValueError("No source observations for the selected empirical tail.")
        fig=design_quantile_figure(table,quantity="Air temperature",unit="°C",upper=upper)
        note=design_quantile_interpretation(table,quantity="air temperature",unit="°C",upper=upper)
    elif kind=="hvac_critical":
        from .p4_design_charts import critical_windows_figure
        from .hvac_findings import critical_window_interpretation
        fig,table,details=critical_windows_figure(df,T,"°C",hours=72,upper=True)
        if fig is None:raise ValueError(details)
        note=critical_window_interpretation(table,quantity="Air temperature",
                                             unit="°C",upper=True,hours=72)+" "+details
    elif kind=="utci_shading":
        from .p3_comfort import utci_frame
        from .utci_findings import paired_delta_figure,paired_exposure_interpretation
        values,_=utci_frame(df,model="Open-sky screening")
        if not values[["Open sun","Direct-beam shade"]].notna().all(axis=1).any():
            raise ValueError("Source observations contain no coincident UTCI sun/shade states.")
        fig=paired_delta_figure(df,values)
        fig.update_layout(title=label)
        note=paired_exposure_interpretation(df,values)
    elif kind=="utci":
        from .p3_comfort import utci_frame,utci_class_hours,CLASSES,COLORS
        values,_=utci_frame(df)
        a=utci_class_hours(df,values.iloc[:,0]);fig=go.Figure()
        if not values.notna().any().any():raise ValueError("No valid UTCI input domain.")
        for c,color in zip(CLASSES,COLORS):
            if c in a:fig.add_bar(x=a.index,y=a[c],name=c,marker_color=color)
        fig.update_layout(template="plotly_white",title=label,barmode="stack",yaxis_title="Hours")
        from .utci_findings import utci_distribution_interpretation
        note=utci_distribution_interpretation(df,values,values.columns[0])
        note+=" The uniform MRT scenario sets mean radiant temperature equal to air temperature and evaluates wind at the 10 m reference height."
    else:raise ValueError("Unknown standard diagram.")
    if page=="Temperature":
        from .temperature_findings import temperature_figure_interpretation
        stat=temperature_figure_interpretation(
            df,fig,kind,column=column or T,thresholds=temperature_thresholds(context))
    elif page=="Humidity and Psychrometrics":
        from .humidity_findings import humidity_figure_interpretation
        stat=humidity_figure_interpretation(
            df,fig,kind,column=column,title=label)
    elif page=="Solar and Radiation":
        from .solar_findings import solar_figure_interpretation
        stat="" if kind=="facade_temperature" else solar_figure_interpretation(
            df,fig,kind,column=column,title=label)
    elif page=="Wind and Ventilation":
        from .wind_findings import wind_figure_interpretation
        stat="" if kind=="wind_orientation" else wind_figure_interpretation(
            df,fig,kind,column=column,title=label)
    elif page=="Sky and Daylight":
        from .sky_findings import sky_figure_interpretation
        stat=sky_figure_interpretation(df,fig,kind,column=column,title=label,
                                      latitude=context.get("latitude"))
    elif page=="Precipitation and Snow":
        from .precipitation_findings import precipitation_figure_interpretation
        mapped_kind="rain_days" if kind=="rain_days" else kind
        stat=precipitation_figure_interpretation(df,fig,mapped_kind,column=column,title=label)
    elif page=="Shading analysis" or kind in (
        "hvac_energy","hvac_economizer","hvac_design_hot","hvac_design_cold",
        "hvac_critical","utci","utci_shading",
    ):
        stat=""
    else:
        stat=source_interpretation(df,page,column if kind in ("profile","duration","heatmap") else "",label,unit,thresholds=temperature_thresholds(context),kind=kind)
    if kind=="nv" and c in ledger:
        from .interpretations import natural_ventilation_interpretation
        stat=natural_ventilation_interpretation(df,ledger[c].gt(0)&ledger[c].notna())
    elif kind=="night" and c in ledger:
        from .passive_design_findings import night_flushing_interpretation
        stat=night_flushing_interpretation(
            df,ledger[c].gt(0)&ledger[c].notna(),hot_day_c=26.,night_max_c=20.,
        )
    if stat and stat not in note:note=stat+"\n\n"+note
    from .calendar_heatmap_axes import apply_monthly_axes
    return apply_monthly_axes(fig),note
