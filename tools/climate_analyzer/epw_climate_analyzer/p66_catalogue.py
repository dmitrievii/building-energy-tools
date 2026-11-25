"""P6.6 deterministic, source-gated visualization catalogue (no widget crawling)."""
from __future__ import annotations
from dataclasses import dataclass,asdict
import itertools
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from . import p6_report_structure as base
from .extended_visualization import hourly_capable,compatible_types
from .aggregations import heatmap_scope_statistics,heatmap_has_single_observation_cells,heatmap_default_statistic,native_interval_hours,profile_aggregations,profile_representation_options
from .climate_model import aggregation_semantics_for

REP="Representative"; AGG="All types and aggregations"; FULL="All types, aggregations and statistics"
LEVELS=(REP,AGG,FULL)
T,RH,W,V,G,D,N,P=base.T,base.RH,base.W,base.V,base.G,base.D,base.N,base.P
WD="wind_direction_deg"; H="moist_air_enthalpy_kj_kg"; S="snow_depth_cm"
SV="specific_volume_m3_kg"; Z="solar_apparent_zenith_deg"; AZ="solar_azimuth_deg"; EL="solar_elevation_deg"
DEW="dew_point_temperature_c"; LUX="global_horizontal_illuminance_lux"
TEMP="Temperature"; HUM="Humidity and Psychrometrics"; SOL="Solar and Radiation"; WIND="Wind and Ventilation"
RAIN="Precipitation and Snow"; SKY="Sky and Daylight"; NV="Natural Ventilation"; SHADE="Shading analysis"; HVAC="HVAC and Passive Design"; OTC="Outdoor Thermal Comfort"; REL="Time Series and Overlay"
# Mirror of mature public variable registry, excluding derived POA until the
# fixed reference plane can be calculated by the shared solar kernel.
VARIABLE_GROUPS={
TEMP:[(T,"Dry-bulb temperature","°C"),("dry_bulb_temperature_min_c","Minimum dry-bulb temperature","°C"),("dry_bulb_temperature_max_c","Maximum dry-bulb temperature","°C"),*[("ground_temperature_"+d+"m_c","Ground temperature "+label+" m","°C") for d,label in (("0_10","0.10"),("0_20","0.20"),("0_50","0.50"))]],
HUM:[(DEW,"Dew-point temperature","°C"),(RH,"Relative humidity","%"),(W,"Humidity ratio","g/kg dry air"),(H,"Moist-air enthalpy","kJ/kg dry air"),("wet_bulb_temperature_c","Wet-bulb temperature","°C"),(SV,"Specific volume","m³/kg dry air"),("moist_air_density_kg_m3","Moist-air density","kg/m³"),("atmospheric_station_pressure_pa","Station pressure","Pa")],
SOL:[(G,"Global horizontal irradiation","Wh/m²"),(N,"Direct normal irradiation","Wh/m²"),(D,"Diffuse horizontal irradiation","Wh/m²"),("diffuse_radiation_fraction_pct","Diffuse fraction","%"),("poa_global_wh_m2","Reference vertical POA","Wh/m²"),("poa_direct_wh_m2","Reference direct POA","Wh/m²"),("poa_sky_diffuse_wh_m2","Reference sky-diffuse POA","Wh/m²"),("poa_ground_diffuse_wh_m2","Reference ground-reflected POA","Wh/m²")],
WIND:[(V,"Wind speed","m/s"),(WD,"Wind direction","deg"),("wind_gust_speed_m_s","Wind gust speed","m/s"),("wind_gust_direction_deg","Wind gust direction","deg")],
SKY:[(LUX,"Global horizontal illuminance","lux"),("direct_normal_illuminance_lux","Direct normal illuminance","lux"),("diffuse_horizontal_illuminance_lux","Diffuse horizontal illuminance","lux"),("total_sky_cover_tenths","Total sky cover","tenths"),("opaque_sky_cover_tenths","Opaque sky cover","tenths"),("sunshine_duration_s","Sunshine duration","s")],
RAIN:[(P,"Liquid precipitation depth","mm"),("precipitation_duration_min","Precipitation duration","min"),(S,"Snow depth","cm")]}
UNITS={c:u for vars in VARIABLE_GROUPS.values() for c,_,u in vars}
LABELS={c:l for vars in VARIABLE_GROUPS.values() for c,l,_ in vars}
PERIODS=("Hourly","Daily","Weekly","Monthly","Seasonal","Annual")
TOTAL_PERIODS=PERIODS[1:]
GEOMETRY={"facade":180.,"width":2.,"height":1.5,"overhang":.6,"left_fin":0.,"right_fin":0.}
GEO_NOTE="Reference south-facing 2 × 1.5 m vertical aperture, 0.6 m overhang, no side fins."
@dataclass(frozen=True)
class Diagram:
    id:str
    chapter:str
    title:str
    kind:str
    column:str=""
    unit:str=""
    args:tuple=()
    status:str="available"
    reason:str=""

def prepare_frame(df):
    """Add only physically admitted reference derived fields, never alter source."""
    from .surface_radiation_views import with_diffuse_fraction,poa_frame
    from .monthly_radiation import surface_available
    if not hourly_capable(df):return df
    # Both builders create their own result frames; do not duplicate a source
    # before either builder, and never write into the input.
    if all(c in df for c in (G,D)):out=with_diffuse_fraction(df)
    else:out=df
    if surface_available(out):out=poa_frame(out,90.,180.,copy=out is df)
    return out

def catalogue(df,context,coverage=FULL):
    if coverage not in LEVELS:raise ValueError("Unknown atlas coverage.")
    monthly=str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly"
    hourly=hourly_capable(df)
    available={c for c in df if c in UNITS or c in (Z,AZ,EL,"horizontal_infrared_radiation_intensity_wh_m2") if base.numeric(df,c).notna().any()}
    has=lambda *cols:all(c in available for c in cols)
    rows=[]
    def add(chapter,title,kind,column="",unit="",args=(),ok=True,reason="Required source quantities or temporal resolution unavailable."):
        ident="|".join(map(str,(chapter,kind,column,*args)))
        rows.append(Diagram(ident,chapter,title,kind,column,unit,tuple(args),"available" if ok else "unsupported", "" if ok else reason))
    periods=("Monthly",) if coverage==REP or monthly else PERIODS
    for chapter,variables in VARIABLE_GROUPS.items():
        for c,label,u in variables:
            if not has(c):
                add(chapter,label,"source_variable",c,u,ok=False);continue
            angular=aggregation_semantics_for(c)=="circular mean"
            extensive=aggregation_semantics_for(c)=="sum"
            # Native-monthly observations are not hourly distributions.
            if monthly:
                add(chapter,label+" · native monthly values","native",c,u)
                continue
            profile_periods=profile_aggregations(df,c)
            if coverage==REP:profile_periods=("Monthly",) if "Monthly" in profile_periods else profile_periods[:1]
            for period in profile_periods:
                options=profile_representation_options(df,c,period)
                if "Min–mean–max" in options:
                    add(chapter,label+" · min–mean–max · "+period,"profile",c,u,(period,))
                    add(chapter,label+" · P05–median–P95 · "+period,"percentile",c,u,(period,))
                else:
                    rep=options[0]
                    add(chapter,label+" · "+period+" time series · "+rep,"time_series",c,u,(period,rep))
            if hourly:
                for period in (("month",) if coverage==REP else ("day","week","month")):
                    dims=("Hour of day",)
                    if coverage==FULL and len(set(df.index.year))>1:dims+=("Year",)
                    for dim in dims:
                        stats=heatmap_scope_statistics(df,c,period,dim) if coverage==FULL else (heatmap_default_statistic(c),)
                        single=heatmap_has_single_observation_cells(df,period,dim)
                        for stat in stats:
                            cell_label="Observed value" if single else stat
                            add(chapter,f"{label} · {period} × {dim} · {cell_label}","heatmap",c,u,(period,dim,stat))
            if not angular:
                bases=("wet","all") if c==P and coverage!=REP else ("wet",) if c==P else ("all",)
                for basis in bases:
                    suffix=" · wet intervals" if basis=="wet" else " · all intervals" if c==P else ""
                    valid=basis!="wet" or base.numeric(df,c).gt(0).any()
                    for order in ((False,True) if coverage==FULL else (False,)):
                        for axis in (("hours","probability") if coverage!=REP else ("hours",)):
                            add(chapter,f"{label} · {axis} duration · {'ascending' if order else 'descending'}"+suffix,"duration",c,u,(basis,order,axis),ok=valid,reason="No wet observation intervals.")
                    for kind in ("histogram","box","violin"):
                        add(chapter,label+" · "+{"histogram":"histogram","box":"monthly boxplot","violin":"monthly violin"}[kind]+suffix,kind,c,u,(basis,),ok=valid,reason="No wet observation intervals.")
                if compatible_types(df,c):
                    for style in (("Overlay",) if coverage==REP else ("Overlay","Small multiples")):
                        for centre in (("mean","median") if coverage==FULL else ("mean",)):
                            for band in (("P05–P95","Min–max","None") if coverage==FULL else ("P05–P95",)):
                                add(chapter,f"{label} · typical daily profile · {style} · {centre} · {band}","diurnal",c,u,(style,centre,band))
                    for basis in (("Hours",) if coverage==REP else ("Hours","Days","Percentage")):
                        stats=(("Total","Mean","Minimum","Maximum") if extensive else ("Mean","Minimum","Maximum")) if basis=="Days" and coverage==FULL else (("Total",) if basis=="Days" and extensive else ("Mean",))
                        for stat in stats:add(chapter,f"{label} · occurrence · {basis}"+(f" · daily {stat}" if basis=="Days" else ""),"occurrence",c,u,(basis,stat))
                if chapter==TEMP and u=="°C" and hourly:
                    for period in (("Daily",) if coverage==REP else TOTAL_PERIODS):
                        add(chapter,f"{label} · amplitude · {period}","amplitude",c,"K",(period,))
    # Dedicated extensive accumulations, not min/max ribbons of totals.
    for chapter,c,u in [(SOL,G,"kWh/m²"),(SOL,D,"kWh/m²"),(SOL,N,"kWh/m²"),(RAIN,P,"mm"),(RAIN,"precipitation_duration_min","h"),(SKY,"sunshine_duration_s","h")]:
        for period in (("Monthly",) if coverage==REP or monthly else TOTAL_PERIODS):
            add(chapter,f"{LABELS[c]} · total · {period}","total",c,u,(period,),ok=has(c))
    for style in ("Walter–Lieth diagram","Climograph","Temperature–precipitation loop"):
        add(RAIN,style,"climate_summary",args=(style,),ok=has(T,P))
    for metric in ("Degree-days","Degree-hours"):
        for period in (("Monthly",) if coverage==REP else TOTAL_PERIODS):
            add(TEMP,f"{metric} · {period}","degree",T,"K·d" if metric=="Degree-days" else "K·h",(metric,period),ok=hourly and has(T))
    for period in (("Monthly",) if coverage==REP else TOTAL_PERIODS[:-1]):
        add(TEMP,f"Temperature thresholds · {period}","temp_threshold",T,"h",(period,),ok=hourly and has(T))
    for stat in ("max","mean","min"):
        for above in (True,False):
            for style in (("timeline",) if coverage==REP else ("timeline","intensity","duration")):
                add(TEMP,f"{'Heatwaves' if above else 'Cold spells'} · daily {stat} · {style}","temp_events",T,"°C",(stat,above,style),ok=hourly and has(T))
    add(TEMP,"Frost days and tropical nights","day_indicators",T,"days",ok=hourly and has(T))
    for chart in ("T-d","i-d"):
        for mode in ("Climate zone","Points","Distribution grid"):
            add(HUM,f"Psychrometric · {chart} · {mode}","psychrometric",W,"g/kg",(chart,mode),ok=hourly and has(T,RH,W))
    for chapter,c,u,threshold,above in [(HUM,RH,"%",80.,True),(HUM,W,"g/kg",10.,True),(WIND,V,"m/s",.5,False)]:
        for style in ("timeline","intensity","duration"):
            add(chapter,f"{LABELS[c]} persistence · {style}","persistence",c,u,(threshold,above,style),ok=hourly and has(c))
    add(HUM,"Condensation margin · 15 °C surface","condensation",DEW,"K",ok=hourly and has(DEW))
    add(HUM,"Monthly moisture conditioning load","moisture",W,"kg",ok=hourly and has(W,SV))
    solar_ok=hourly and has(Z,AZ,G,D,N)
    from .sun_path_views import solar_reference,available_radiation_fields
    site_ok=hourly and solar_reference(df) is not None
    for style in ("2D","Technical","3D"):
        add(SOL,style+" sun path","sunpath_view",args=(style,"None"),ok=site_ok)
    for field,label in available_radiation_fields(df) if site_ok else []:
        add(SOL,"2D sun path · "+label,"sunpath_view",args=("2D",field),ok=site_ok)
    for style,colour in itertools.product(("2D","Technical"),("Outdoor temperature","Solar benefit / risk")):
        add(SOL,f"{style} sun path · {colour}","sunpath_view",args=(style,colour),ok=site_ok and has(T,AZ,EL))
    from .sky_distribution import available_quantities
    for quantity in ("Direct","Diffuse","Total"):
        models=("Isotropic","Perez 1993 (research)") if coverage==FULL and quantity!="Direct" and has(N) else ("Isotropic",)
        for mf,style,model in itertools.product((1,) if coverage==REP else (1,2),("2D hemisphere","3D dome"),models):
            add(SOL,f"Sky {quantity} · {'145' if mf==1 else '577'} patches · {style} · {model}","sky_patches",args=(quantity,mf,style,model),ok=hourly and quantity in available_quantities(df))
    for style in ("Bar chart","Solar rose"):
        add(SOL,"Façade irradiation · "+style,"facade",args=(style,),ok=solar_ok)
    for style in ("Heat map","Orientation sensitivity curves"):
        add(SOL,"Orientation–tilt · "+style,"tilt",args=(style,),ok=solar_ok)
    for style in ("Bar chart","Line chart","Monthly rose"):
        add(SOL,"Monthly source irradiation · "+style,"monthly_radiation",args=(style,),ok=has(G) or has(D) or has(N))
    from .directional_climate import colour_options,radial_options,CLASS_EDGES
    from .climate_model import aggregation_semantics_for as semantics
    for speed,direction,label in [(V,WD,"Mean wind"),("wind_gust_speed_m_s","wind_gust_direction_deg","Gust wind")]:
        if not hourly or not has(speed,direction):
            add(WIND,label+" rose","windrose",speed,"",ok=False);continue
        add(WIND,label+" · Monthly wind rose panel (12 months)","wind_panel",speed,"%",(direction,"Percentage","Wind speed"))
        months=(0,) if coverage==REP else (0,*sorted(set(df.index.month)))
        colours=colour_options(df,speed=speed)
        for m in months:
            season="Annual" if m==0 else pd.Timestamp(2000,m,1).strftime("%B")
            for colour in colours:
                radials=("Percentage",) if coverage!=FULL else tuple(radial_options(df,speed==V))
                for radial in radials:
                    add(WIND,f"{label} · {season} · {radial} · {colour} mean","wind_mean",speed,"",(direction,m,radial,colour))
                if colour in CLASS_EDGES:
                    for radial in ("Hours","Percentage") if coverage==FULL else ("Percentage",):
                        add(WIND,f"{label} · {season} · {radial} · {colour} classes","wind_classes",speed,"",(direction,m,radial,colour))
    add(RAIN,"Directional wind-driven rain exposure","wind_rain",P,"mm·m/s",
        ok=hourly and has(P,V,WD))
    for wet in (True,False):
        for style in ("timeline","intensity","duration"):
            add(RAIN,f"{'Wet' if wet else 'Dry'} spells · {style}","wetdry",P,"mm",(wet,style),ok=hourly and has(P))
    for hours in (1,3,6,12,24,48,72,168):
        add(RAIN,f"Rolling precipitation · {hours} h","rolling",P,"mm",(hours,),ok=hourly and has(P))
    add(RAIN,"Cumulative precipitation","cumulative",P,"mm",ok=hourly and has(P))
    add(RAIN,"Freeze–thaw days","freeze_days",T,"days",ok=hourly and has(T))
    add(RAIN,"Monthly observed freeze–thaw sequences","freeze_cycles",T,"Sequences",ok=hourly and has(T))
    add(SKY,"Daylight envelope","daylight",ok=site_ok)
    add(SKY,"Measured sunshine hour heatmap","sunshine",ok=hourly and has("sunshine_duration_s"))
    for c in ("total_sky_cover_tenths","opaque_sky_cover_tenths"):
        add(SKY,LABELS[c]+" · monthly sky conditions","sky_conditions",c,"h",ok=hourly and has(c))
    for period in (("Monthly",) if coverage==REP else TOTAL_PERIODS):
        add(SKY,f"Illuminance ≥ 300 lux · {period}","illumination",LUX,"h",(period,),ok=hourly and has(LUX))
    from .shading_temporal import ENERGY,REDUCTION,AREA
    from .solar_shading import DEVICES,TOTAL_DEVICE
    from .shading_calendar import OCCURRENCE,shading_statistics,DEFAULT_THRESHOLD
    geometry_ok=hourly and has(Z,AZ)
    add(SHADE,"Window shading · Geometry","shading_mask",args=("Geometry",),ok=geometry_ok)
    for metric in (AREA,OCCURRENCE,ENERGY,REDUCTION):
        ok=geometry_ok if metric in (AREA,OCCURRENCE) else solar_ok
        for period in (("day",) if coverage==REP else ("day","week","month")):
            dims=("Hour of day","Year") if coverage==FULL and len(set(df.index.year))>1 else ("Hour of day",)
            for dim in dims:
                stats=shading_statistics(df,metric,period,dim)
                if coverage!=FULL:stats=stats[:1]
                for stat in stats:
                    # All-device calendar is primary; individual-device means/totals
                    # retained in full Atlas without multiplying every statistic.
                    devices=(TOTAL_DEVICE,*DEVICES) if coverage==FULL and period=="month" and dim=="Hour of day" and stat==stats[0] and metric!=OCCURRENCE else (TOTAL_DEVICE,)
                    for device in devices:
                        label=metric+(f" ≥ {DEFAULT_THRESHOLD:g}% aperture" if metric==OCCURRENCE else "")
                        cell="Observed value" if heatmap_has_single_observation_cells(df,period,dim) and metric!=REDUCTION else stat
                        add(SHADE,f"{label} · {period} × {dim} · {cell} · {device}","shading_calendar",args=(metric,period,dim,stat,device),ok=ok)
        if metric in (AREA,OCCURRENCE):
            add(SHADE,metric+" · monthly hourly profiles","shading_profiles",args=(metric,),ok=ok)
        if metric!=OCCURRENCE:
            years=sorted(set(df.index.year))
            for year in (years[-1:] if coverage==REP else years):
                add(SHADE,f"{metric} · Monthly rose · {year}","shading_temporal",args=(metric,"Monthly rose",year,TOTAL_DEVICE),ok=ok)
    add(SHADE,"Shaded vs unshaded reference façade irradiation","shading_irradiation",ok=solar_ok)
    for name,c,ok in [("nv",W,hourly and has(T,W)),("night",T,hourly and has(T)),("shade",G,hourly and has(T,G))]:
        for period in (("Monthly",) if coverage==REP else TOTAL_PERIODS):
            add(NV if name!="shade" else SHADE,f"{name.replace('nv','Natural ventilation').replace('night','Night flushing').replace('shade','Solar protection screening')} · {period}","eligibility_total",c,"h",(name,period),ok=ok)
        for period in (("day",) if coverage==REP else ("day","week","month")):
            add(NV if name!="shade" else SHADE,f"{name} · {period} × hour eligibility","eligibility_map",c,"0/1",(name,period),ok=ok)
    for style in ("Persistence","Daily duration","Temperature–wind suitability","Rejected reasons","Directional suitability","Wind during suitable hours"):
        add(NV,"Natural ventilation · "+style,"nv_special",args=(style,),ok=hourly and has(T,W) and (has(V) if style=="Temperature–wind suitability" else has(V,WD) if style.startswith("Directional") or style.startswith("Wind during") else True))
    add(HVAC,"Monthly passive strategy hours","passive",ok=hourly and has(T))
    add(HVAC,"Ventilation conditioning loads","vent_load",ok=hourly and has(T,W,SV))
    add(HVAC,"Air-side economizer · temperature and enthalpy screening",
        "economizer_stages",ok=hourly and has(T,H))
    add(HVAC,"Adaptive comfort · Categories I–III","adaptive",ok=hourly and has(T))
    if coverage==FULL:
        add(HVAC,"Adaptive comfort · Categories I–III · Research extrapolation","adaptive",args=("research_extrapolation",),ok=hourly and has(T))
    for c in (T,W,H):
        for upper in (True,False):
            add(HVAC,f"{LABELS[c]} · {'upper' if upper else 'lower'} critical 3-day windows","critical_windows",c,UNITS[c],(upper,),ok=hourly and has(c))
    for model in ("Uniform radiant offset","Open sun","Direct-beam shade"):
        for style in ("heatmap","duration","stress"):
            add(OTC,f"UTCI · {model} · {style}","utci",T,"°C",(model,style),ok=hourly and has(T,RH,V) and (model=="Uniform radiant offset" or has(G,D,N,Z,"horizontal_infrared_radiation_intensity_wh_m2")))
    pair_ok=hourly and has(T,RH,V,G,D,N,Z,"horizontal_infrared_radiation_intensity_wh_m2")
    add(OTC,"UTCI · paired sun versus shade","utci_pair",ok=pair_ok)
    add(OTC,"UTCI · monthly direct-beam shading benefit","utci_pair_delta",ok=pair_ok)
    add(OTC,"UTCI · paired heat-stress exposure","utci_pair_stress",ok=pair_ok)
    add(OTC,"Mean radiant temperature · sun and shade","utci_pair_mrt",ok=pair_ok)
    for axis in ("Temperature–wind","Temperature–radiant offset","Wind–radiant offset"):
        add(OTC,"Controlled UTCI sensitivity · "+axis,"utci_sensitivity",args=(axis,),ok=hourly and has(T,RH,V))
    years=sorted(set(df.index.year))
    for year in (years[-1:] if coverage==REP else years):
        add(RAIN,f"Snow-cover calendar · {year}","snow_calendar",S,"",(int(year),),ok=hourly and has(S))
    paired=[c for c in (T,RH,W,H,V,G,P,DEW) if has(c)]
    add(REL,"Pairwise correlation matrix","correlation",args=tuple(paired),ok=len(paired)>=2)
    for x,y in itertools.combinations(paired,2):
        for style in ("scatter","density"):
            add(REL,f"{LABELS[x]} × {LABELS[y]} · {style}","joint",x,UNITS[x],(y,style),ok=hourly)
    # Explicit unavailable/non-enumerated cases remain in the audit manifest.
    for chap,title,reason in [(TEMP,"Calculated ground-temperature depth animations","Requires EPW ground model or explicitly assigned measured profile; animation not static report."),(RAIN,"Empirical precipitation IDF","Requires independently verified native historical precipitation including ≥10 complete years."),(REL,"Critical event context viewer","Requires selected event and surrounding variables; arbitrary event combinations not enumerated."),("Compare Climates","Multi-climate comparison diagrams","Requires explicit comparison basket, not single active climate."),("Data Quality","Provider-specific diagnostic figures","Provider-specific diagnostics remain on Data Quality page.")]:
        add(chap,title,"not_registered",args=(title,),ok=False,reason=reason)
    ids=[d.id for d in rows]
    if len(ids)!=len(set(ids)):raise ValueError("Nonunique atlas identifiers.")
    return rows
