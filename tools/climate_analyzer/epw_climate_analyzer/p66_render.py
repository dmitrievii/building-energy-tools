"""P6.6 chart adapters. Share analytical kernels with the interactive pages."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from . import p66_catalogue as cat
from . import p6_report_structure as base
from . import charts as ch
from . import extended_visualization as ex
from . import p4_extremes as p4
from . import p3_comfort as p3
from . import aggregations as agg
from .temporal_filtering import time_basis,display_period_labels
from .climate_model import aggregation_semantics_for

class NotApplicable(ValueError):
    """Supported scientific method, but no valid qualifying state in this scope."""

def _line(s,title,unit):
    f=go.Figure(go.Scatter(x=s.index,y=s,mode="lines+markers" if len(s)<32 else "lines",connectgaps=False))
    return f.update_layout(template="plotly_white",title=title,yaxis_title=unit,xaxis_title="Period")

def _bars(a,title,unit):
    if isinstance(a,pd.Series):a=a.to_frame()
    if a.empty or not a.notna().any().any():raise NotApplicable("No valid observations for this representation.")
    f=go.Figure()
    for c in a:f.add_bar(x=a.index,y=a[c],name=str(c))
    return f.update_layout(template="plotly_white",title=title,yaxis_title=unit,barmode="group")

def _totals(df,a,period):
    if isinstance(a,pd.Series):a=a.to_frame()
    out=pd.DataFrame({c:agg.period_total_series(a[c],df,period) for c in a})
    out.index=display_period_labels(out.index,period,time_basis(df))
    return out

def _event_figure(table,series,style,threshold,above,unit,quantity,step=None):
    from .p4_ui import event_timeline_figure
    if style=="timeline":
        if not series.notna().any():raise NotApplicable("No valid observations.")
        return event_timeline_figure(table,series,unit=unit,threshold=threshold,above=above,quantity=quantity,step=step)
    if table.empty:raise NotApplicable("No qualifying events; the timeline remains available.")
    if style=="intensity":
        f=go.Figure(go.Scatter(x=table.duration,y=table.peak,mode="markers",customdata=table.excess,
            hovertemplate="Duration %{x}<br>Peak %{y}<br>Integrated excess %{customdata}<extra></extra>"))
        return f.update_layout(template="plotly_white",xaxis_title=f"Duration [{unit}]",yaxis_title=quantity)
    return _bars(table.duration.value_counts().sort_index().rename("Number of events"),"Duration distribution","Events").update_xaxes(title=f"Duration [{unit}]")

def _pressure(df,context):
    try:
        p=float(context["guide pressure Pa"])
        if np.isfinite(p) and p>0:return p
    except (KeyError,TypeError,ValueError):pass
    p=base.numeric(df,"atmospheric_station_pressure_pa").median()
    return float(p) if np.isfinite(p) and p>0 else 101325.

def make_figure(d,df,context,reference_df=None,cache=None):
    if d.status!="available":raise NotApplicable(d.reason)
    if cache is None:cache={}
    k,c,u,a=d.kind,d.column,d.unit,d.args
    s=base.numeric(df,c) if c else None
    title=d.title
    dt=agg.native_interval_hours(df)
    note="Selected source records only; missing observations are not synthesized."
    def memo(key,fn):
        if key not in cache:cache[key]=fn()
        return cache[key]
    def design():
        from .p6_dashboard import design_ledgers
        return memo("design",lambda:design_ledgers(df,reference_df=reference_df)[0])
    if k=="native":f=_line(s,title,u);note+=" Published monthly observations; no hourly reconstruction."
    elif k=="profile":f=ch.profile_ribbon_chart(df,c,a[0],title,u)
    elif k=="percentile":f=ch.percentile_band_chart(df,c,a[0],title,u);note+=" Central 90% of observations, not a confidence interval."
    elif k=="heatmap":
        bounds=base.temperature_thresholds(context) if c in ch.TEMPERATURE_HEATMAP_COLUMNS else None
        f=ch.temporal_heatmap_chart(df,c,*a,title,u,temperature_thresholds=bounds)
        if bounds:
            note+=f" Absolute temperature classes at {bounds[0]:g}/{bounds[1]:g} °C."
            if c!=cat.T:note+=" Colours are not comfort or heating/cooling demand indicators."
        if agg.heatmap_has_single_observation_cells(df,a[0],a[1]):
            note+=" One observed value per occupied cell; no statistic required."
        else:note+=f" Cell statistic: {a[2]}; comparison: {a[1]}."
    elif k in ("duration","histogram","box","violin"):
        scope=df.loc[s.gt(0)].copy() if a[0]=="wet" else df
        if scope.empty:raise NotApplicable("No wet observations.")
        if k=="duration":f=ex.probability_figure(scope,c,u,a[1]) if a[2]=="probability" else ch.duration_chart(scope,c,title,u,ascending=a[1])
        elif k=="histogram":f=ch.histogram_chart(scope,c,title,u,bins=40);note+=" Reference 40 histogram bins."
        else:f=ch.monthly_box_chart(scope,c,title,u,violin=k=="violin")
        if a[0]=="wet":note+=" Positive precipitation intervals only."
    elif k=="diurnal":
        table=memo(("diurnal",c),lambda:ex.diurnal_statistics(df,c))
        f=ex.diurnal_figure(table,c,u,representation=a[0],centre=a[1],band=a[2])
        note+=" Equivalent clock hours pooled across selected months; complete source hours only."
    elif k=="occurrence":
        edges=[0.,15.,25.,30.] if c==cat.T else sorted(set(s.dropna().quantile([.25,.5,.75]).tolist()))
        if not edges:raise NotApplicable("No valid class boundaries.")
        table=ex.occurrence_table(df,c,edges,basis=a[0],daily_stat=a[1])
        if table.empty:raise NotApplicable("No complete observations for the selected class basis.")
        f=ex.occurrence_figure(table,u,a[0]);note+=" Reference classes: "+", ".join(f"{v:g}" for v in edges)+f" {u}. Classes are disjoint."
    elif k=="amplitude":f=ex.amplitude_figure(df,c,a[0],cat.LABELS[c]);note+=" Observed max minus min, not interpolated extrema."
    elif k=="total":
        factor=1/1000 if u=="kWh/m²" else 1/60 if c=="precipitation_duration_min" else 1/3600 if c=="sunshine_duration_s" else 1
        f=_bars(_totals(df,(s*factor).rename(cat.LABELS[c]),a[0]),title,u);note+=" Totals over selected valid data, not annualized."
    elif k=="climate_summary":
        table=memo("climate_summary",lambda:ex.climate_summary_table(df))
        if table.empty:raise NotApplicable("No paired complete months.")
        f=ex.climate_summary_figure(table,a[0]);note=ex.climate_summary_interpretation(table,a[0])
    elif k=="degree":
        from .degree_metrics import degree_metric_table
        data=df
        if a[0]=="Degree-days":
            daily=memo("daily_T",lambda:p4.daily_stats(df,cat.T))
            data=daily[["mean"]].rename(columns={"mean":cat.T});data.attrs.update(df.attrs)
        result=degree_metric_table(data,metric=a[0],aggregation=a[1],heating_indoor_c=20.,heating_limit_c=12.,cooling_indoor_c=26.,cooling_limit_c=26.)
        result=result.copy();result.index=display_period_labels(result.index,a[1],time_basis(df))
        f=_bars(result,title,u)
        from .degree_metrics import degree_legend_below
        degree_legend_below(f)
        note+=" Reference HGT 20/12, KGT 26/26. Degree-days require complete daily means; not energy demand."
    elif k=="temp_threshold":
        a1=pd.DataFrame({"Below 18 °C":s.lt(18).astype(float).where(s.notna())*dt,"Above 26 °C":s.gt(26).astype(float).where(s.notna())*dt})
        f=_bars(_totals(df,a1,a[0]),title,u);note+=" Reference low/high temperature thresholds 18/26 °C."
    elif k=="temp_events":
        stat,above,style=a;threshold=30. if above else 0.
        daily,ev=memo(("temp_events",stat,above),lambda:p4.temperature_events(df,threshold=threshold,above=above,minimum=3,stat=stat))
        f=_event_figure(ev,daily[stat],style,threshold,above,"days",u)
        note+=f" Daily {stat}, {'≥' if above else '≤'} {threshold:g} °C for at least three consecutive complete days. {len(ev)} events."
    elif k=="day_indicators":
        f=_bars(p4.day_indicators(df).resample("MS").sum(min_count=1),title,u)
        note+=" Frost: Tmin <0 °C; tropical nights: daily Tmin ≥20 °C."
    elif k=="psychrometric":
        chart,mode=a;p=_pressure(df,context)
        f=ch.psychrometric_chart(df,chart_type=chart,pressure_pa=p,data_mode=mode)
        note+=f" Reference guide pressure {p:,.0f} Pa; chart coordinates use existing source-derived psychrometrics."
    elif k=="persistence":
        threshold,above,style=a;step=p4.cadence(df)
        ev=memo(("persistence",c,threshold,above),lambda:p4.events(s,threshold=threshold,above=above,minimum=3,step=step))
        f=_event_figure(ev,s,style,threshold,above,"hours",u,step=step)
        note+=f" {'≥' if above else '≤'} {threshold:g} {u}, minimum three continuous hours. {len(ev)} events."
    elif k=="condensation":
        f=_line(p3.condensation_margin(df,15.),title,u);f.add_hline(y=0,line_dash="dash")
        note+=" Assumed constant surface temperature 15 °C; negative margin indicates possible condensation."
    elif k=="moisture":
        f=_bars(p3.monthly_totals(df,p3.moisture_loads(df,airflow=1000.,target=9.)),title,u)
        note+=" Outdoor air flow 1000 m³/h, target 9 g/kg dry air; no building moisture balance."
    elif k=="sunpath_view":
        from .sun_path_views import classic_sun_path,technical_sun_path,sun_path_3d
        from .solar_shading import thermal_overlay
        style,colour=a
        thermal=colour in ("Outdoor temperature","Solar benefit / risk")
        f=classic_sun_path(df,radiation_field=None if thermal or colour=="None" else colour) if style=="2D" else technical_sun_path(df) if style=="Technical" else sun_path_3d(df)
        if thermal:thermal_overlay(f,df,colour,cold=18.,warm=26.,technical=style=="Technical")
        note+=" Solar reference paths are astronomical guides; thermal benefit/risk uses outdoor thresholds, not building energy."
    elif k=="sky_patches":
        from .sky_distribution import cumulative_sky,sky_figure
        quantity,mf,style,*rest=a;model=rest[0] if rest else "Isotropic"
        table=memo(("sky",quantity,mf,model),lambda:cumulative_sky(df,mf=mf,quantity=quantity,model=model))
        f=sky_figure(table,quantity,style)
        note+=f" {model}. Horizontal irradiation contribution per sky patch; no ground contribution. Perez research path is not independently qualified."
    elif k=="facade":
        from .facade_orientation import orientation_period_components,orientation_components_chart
        data,flat=memo("facade",lambda:orientation_period_components(df,tilt_deg=90.))
        f=orientation_components_chart(data,flat,tilt_deg=90.,style=a[0],selected=())
        note+=" Unobstructed vertical façade POA; isotropic sky and default ground albedo."
    elif k=="tilt":
        from .solar import orientation_tilt_matrix
        from .surface_radiation_views import orientation_curves
        matrix=memo("tilt",lambda:orientation_tilt_matrix(df))
        f=orientation_curves(matrix) if a[0]!="Heat map" else ch.matrix_heatmap(matrix,title,"Azimuth [deg]","Tilt [deg]","kWh/m²")
        note+=" Fixed 10° tilt and 15° azimuth grid, unobstructed isotropic POA."
    elif k=="monthly_radiation":
        from .monthly_radiation import available_source_quantities,monthly_source_irradiation,monthly_radiation_chart,monthly_rose_years
        table=memo("monthly_radiation",lambda:monthly_source_irradiation(df,available_source_quantities(df)))
        years=monthly_rose_years(table)
        f=monthly_radiation_chart(table,style=a[0],rose_year=years[-1] if years and a[0]=="Monthly rose" else None)
        if a[0]=="Monthly rose" and years:note+=f" Rose uses {years[-1]}."
    elif k in ("wind_mean","wind_classes"):
        from .directional_climate import directional_table,directional_figure,directional_interpretation,directional_class_table,directional_class_figure,class_interpretation
        direction,month,radial,colour=a
        data=df if not month else df.loc[df.index.month==month].copy()
        if k=="wind_classes":
            table=directional_class_table(data,speed=c,direction=direction,quantity=colour,radial=radial)
            if table.attrs.get("valid_hours",0)<=0:raise NotApplicable("No coincident non-calm observation hours.")
            f=directional_class_figure(table,title);note=class_interpretation(table)
        else:
            table=directional_table(data,speed=c,direction=direction,radial=radial,colour=colour)
            if not table.valid_hours.gt(0).any():raise NotApplicable("No coincident non-calm observation hours.")
            f=directional_figure(table,radial,colour,title);note=directional_interpretation(table,radial,colour)
    elif k=="wetdry":
        wet,style=a;daily,wet_e,dry_e=memo("wetdry",lambda:p4.wet_dry_events(df))
        ev=wet_e if wet else dry_e
        f=_event_figure(ev,daily["sum"],style,1.,wet,"days",u)
        note+=f" Wet ≥1 mm/day; dry <1 mm/day. Complete days only. {len(ev)} events."
    elif k=="rolling":
        v=p4.rolling_windows(df,c,a[0],total=True,nonnegative=True)
        if not v.notna().any():raise NotApplicable("No complete rolling windows.")
        f=_line(v,title,u);note+=f" Trailing complete {a[0]} h windows; gaps break the window."
    elif k=="cumulative":
        f=_line(p4.cumulative_precipitation(df),title,u);note+=" Accumulation restarts at unknown observations or gaps."
    elif k=="freeze_days":
        f=_bars(p4.freeze_thaw_days(df).resample("MS").sum(min_count=1),title,u)
        note+=" Air-temperature crossing opportunity (Tmin<0, Tmax>0); wet criterion ≥1 mm/day; not material damage."
    elif k=="freeze_cycles":
        table=p4.freeze_thaw_cycles(df)
        if table.empty:raise NotApplicable("No qualifying warm–freeze–warm sequences.")
        f=go.Figure(go.Scatter(x=table["Thaw timestamp"],y=table["Freeze-to-thaw duration [h]"],mode="markers")).update_layout(template="plotly_white",yaxis_title=u)
        note+=" Observed warm–freeze–warm sequences; no material thermal model."
    elif k=="daylight":f=ex.daylight_envelope(df.index,float(context["latitude"]));note+=" Ideal horizon and apparent solar time."
    elif k=="sunshine":f=ex.sunshine_hour_heatmap(df);note+=" Measured sunshine duration, complete clock hours."
    elif k=="sky_conditions":f=ex.occurrence_figure(ex.sky_distribution(df,c),"tenths","Hours");note+=" Clear ≤2, overcast ≥8 tenths."
    elif k=="illumination":
        v=s.ge(300).astype(float).where(s.notna())*dt
        f=_bars(_totals(df,v.rename("≥300 lux"),a[0]),title,u)
        note+=" Outdoor horizontal illuminance screening; not indoor daylight autonomy."
    elif k=="shading_mask":
        from .sun_path_views import classic_sun_path,technical_sun_path
        from .shading_sketch import window_shading_sketch
        from .solar_shading import overlay_shading_mask
        if a[0]=="Geometry":f=window_shading_sketch(**cat.GEOMETRY)
        else:
            technical=a[0]=="Technical mask"
            f=technical_sun_path(df) if technical else classic_sun_path(df)
            overlay_shading_mask(f,technical=technical,**cat.GEOMETRY)
        note+=" "+cat.GEO_NOTE+" Direct solar geometry, not diffuse or reflected obstruction."
    elif k=="shading_temporal":
        from .shading_temporal import temporal_shading_tables,shading_monthly_rose,shading_month_hour_heatmap
        metric,style,year,device=a
        data=df.loc[df.index.year==year].copy()
        result=memo(("shading",metric,year),lambda:temporal_shading_tables(data,geometry=cat.GEOMETRY,metric=metric))
        monthly,cells=result[:2]
        f=shading_monthly_rose(monthly,metric) if style=="Monthly rose" else shading_month_hour_heatmap(cells,metric,device=device)
        note+=" "+cat.GEO_NOTE+" Direct-beam-only screening."
    elif k=="shading_irradiation":
        from .solar_shading import shading_ledger
        ledger=shading_ledger(df,**cat.GEOMETRY)
        direct=ledger["Unshaded direct"]
        intercepted=ledger[[c1 for c1 in ledger if c1.endswith(" intercepted direct")]].sum(axis=1,min_count=1)
        f=_bars(_totals(df,pd.DataFrame({"Unshaded direct":direct/1000,"Remaining direct":(direct-intercepted)/1000,"Intercepted direct":intercepted/1000}),"Monthly"),title,"kWh/m²")
        note+=" "+cat.GEO_NOTE+" Direct-beam ledger only; diffuse and ground terms remain unchanged."
    elif k in ("eligibility_map","eligibility_total"):
        name,period=a
        col={"nv":"Natural ventilation","night":"Night flushing","shade":"Solar protection screening"}[name]
        ledger=design()
        if col not in ledger or not ledger[col].notna().any():raise NotApplicable("No valid candidate hours.")
        if k=="eligibility_total":f=_bars(_totals(df,ledger[col],period),title,"h")
        else:
            data=df.copy();data["atlas_suitable"]=ledger[col]/dt
            f=ch.heatmap_chart(data,"atlas_suitable",period,title,"0/1")
        note+=" "+{"nv":"16–26 °C, humidity ratio ≤9 g/kg; no wind or occupancy filter.","night":"22:00–06:59, ≤20 °C after complete day ≥26 °C.","shade":"T≥24 °C, GHI≥250 W/m²; no façade geometry."}[name]
    elif k=="nv_special":
        from .decisions import natural_ventilation_condition
        from .directional_climate import directional_table,directional_figure,directional_class_table,directional_class_figure
        mask=p3.eligibility_mask(df,natural_ventilation_condition(df))
        style=a[0]
        if style=="Persistence":
            t=p3.persistence(df,mask);f=_bars(p3.persistence_monthly(t,2.),title,"Days")
            note+=" Longest uninterrupted daily run ≥2 h."
        elif style=="Daily duration":
            t=p3.persistence(df,mask);v=t["Suitable hours [h]"].dropna().sort_values(ascending=False)
            f=go.Figure(go.Scatter(x=np.arange(1,len(v)+1),y=v,mode="lines")).update_layout(template="plotly_white",xaxis_title="Ranked days",yaxis_title="Suitable hours/day")
        elif style=="Temperature–wind suitability":
            t,h=p3.suitability_grid(df,mask,axis=cat.V)
            if t.empty:raise NotApplicable("No paired valid observations.")
            f=go.Figure(go.Heatmap(x=t.columns,y=t.index,z=t,zmin=0,zmax=100,colorscale="Greens",customdata=h,colorbar=dict(title="%"))).update_layout(xaxis_title="Temperature [°C]",yaxis_title="Wind speed [m/s]")
        elif style=="Rejected reasons":
            reasons=pd.Series({"Too cold":df[cat.T].lt(16).sum()*dt,"Too hot":df[cat.T].gt(26).sum()*dt,"Too humid":df[cat.W].gt(9).sum()*dt},name="Hours")
            f=_bars(reasons,title,"h");note+=" Rejection reasons can overlap."
        elif style=="Directional suitability":
            t=directional_table(df,radial="Hours",colour="Natural ventilation suitability",nv_mask=mask)
            f=directional_figure(t,"Hours","Natural ventilation suitability",title)
        else:
            view=df.loc[mask.eq(1)].copy()
            if view.empty:raise NotApplicable("No suitable ventilation hours.")
            f=directional_class_figure(directional_class_table(view,quantity="Wind speed",radial="Hours"),title)
        note+=" Reference NV 16–26 °C and ≤9 g/kg. Outdoor suitability, not realized airflow."
    elif k=="passive":
        from .decisions import passive_strategy_monthly
        table=passive_strategy_monthly(df)
        if table.empty:raise NotApplicable("No supported passive strategies.")
        f=ch.stacked_monthly_bar(table,title,"Hours");note+=" Strategies overlap; not a partition of total hours."
    elif k=="vent_load":
        f=_bars(p3.monthly_totals(df,p3.ventilation_loads(df,airflow=1000.,heat=20.,cool=26.,w_low=4.,w_high=9.)),title,"kWh")
        note+=" 1000 m³/h outdoor-air proxy; 20–26 °C, 4–9 g/kg; no recovery or plant model."
    elif k=="adaptive":
        history=df if reference_df is None else reference_df
        table=memo("adaptive",lambda:p3.adaptive_bands(history))
        table=table.reindex(pd.DatetimeIndex(df.index.normalize().unique()))
        if not table.Neutral.notna().any():raise NotApplicable("No valid seven-day preceding running means within 10–30 °C.")
        category=a[0] if a else "II";f=go.Figure()
        for c1 in (category+" lower",category+" upper","Neutral","Running mean"):f.add_scatter(x=table.index,y=table[c1],name=c1,mode="lines",connectgaps=False)
        f.update_layout(template="plotly_white",yaxis_title="Temperature [°C]");note+=" EN 16798-1 screening; category "+category+", seven previous complete days, alpha=.8; not compliance."
    elif k=="design_tail":
        t=p4.design_conditions(df,c,[.4,1.,2.,5.],upper=a[0])
        if t.empty:raise NotApplicable("No valid tail observations.")
        f=go.Figure(go.Scatter(x=t["Nominal tail [%]"],y=t.Quantile,mode="lines+markers")).update_layout(template="plotly_white",xaxis_title="Nominal tail [%]",yaxis_title=u)
        note+=" Empirical selected-sample quantiles; not certified design conditions."
    elif k=="utci":
        model,style=a
        mode="Uniform radiant offset" if model=="Uniform radiant offset" else "Open-sky screening"
        values,_=memo(("utci",mode),lambda:p3.utci_frame(df,model=mode))
        col=model
        val=values[col]
        if not val.notna().any():raise NotApplicable("No valid UTCI states in model domain.")
        if style=="heatmap":
            grid=p3.annual_hour_grid(df,val);f=go.Figure(go.Heatmap(x=grid.columns,y=grid.index,z=grid,colorscale="RdBu_r",zmid=20,colorbar=dict(title="°C"),hoverongaps=False))
            f.update_layout(xaxis_title="Date",yaxis_title="Hour of day")
        elif style=="duration":
            v=val.dropna().sort_values(ascending=False);f=go.Figure(go.Scatter(x=np.arange(1,len(v)+1)*dt,y=v,mode="lines")).update_layout(xaxis_title="Duration [h]",yaxis_title="UTCI [°C]")
        else:
            table=p3.utci_class_hours(df,val);f=go.Figure()
            for c1,color in zip(p3.CLASSES,p3.COLORS):
                if c1 in table:f.add_bar(x=table.index,y=table[c1],name=c1,marker_color=color)
            f.update_layout(barmode="stack",yaxis_title="Hours")
        note+=" UTCI research screening; wind assumed at 10 m, uniform MRT=T or simplified open-sky radiation. Out-of-domain states remain missing."
    elif k=="tail_curve":
        v=s.dropna().sort_values(ascending=not a[0])
        if v.empty:raise NotApplicable("No valid tail observations.")
        f=go.Figure(go.Scatter(x=np.arange(1,len(v)+1)*100/len(v),y=v,mode="lines")).update_layout(xaxis_title="Rank fraction [%]",yaxis_title=u)
        note+=" Empirical ranks, no extrapolation."
    elif k=="critical_windows":
        ranked=p4.rolling_windows(df,c,72).dropna().sort_values(ascending=not a[0],kind="stable")
        chosen=[];span=pd.Timedelta(hours=72);step=p4.cadence(df)
        for end,value in ranked.items():
            if all(abs(end-other[0])>=span for other in chosen):
                chosen.append((end,value))
                if len(chosen)==10:break
        if not chosen:raise NotApplicable("No complete three-day windows.")
        f=go.Figure(go.Bar(x=[str(end-span+step) for end,value in chosen],y=[value for end,value in chosen])).update_layout(xaxis_title="Window start",yaxis_title=u)
        note+=" Ten highest/lowest nonoverlapping complete 72-hour windows, ranked by mean."
    elif k=="utci_pair":
        values,_=memo(("utci","Open-sky screening"),lambda:p3.utci_frame(df,model="Open-sky screening"))
        common=values.dropna()
        if common.empty:raise NotApplicable("No paired admitted UTCI states.")
        table=common.resample("MS").mean();f=go.Figure()
        for c1 in table:f.add_scatter(x=table.index,y=table[c1],mode="lines+markers",name=c1)
        f.update_layout(yaxis_title="UTCI [°C]")
        note+=" Paired simplified open-sky radiation; shade removes direct beam only. Not a qualified urban MRT model."
    elif k=="utci_sensitivity":
        axis=a[0];t=np.linspace(0,40,41);v=np.linspace(.5,10,39);delta=np.linspace(-20,50,36)
        if axis=="Temperature–wind":
            x,y=t,v;xx,yy=np.meshgrid(x,y);z=p3.utci_values(xx,xx,yy,np.full_like(xx,50.));xl="Air temperature [°C]";yl="10 m wind [m/s]"
        elif axis=="Temperature–radiant offset":
            x,y=t,delta;xx,yy=np.meshgrid(x,y);z=p3.utci_values(xx,xx+yy,np.full_like(xx,2.),np.full_like(xx,50.));xl="Air temperature [°C]";yl="Radiant offset [K]"
        else:
            x,y=v,delta;xx,yy=np.meshgrid(x,y);z=p3.utci_values(np.full_like(xx,30.),30.+yy,xx,np.full_like(xx,50.));xl="10 m wind [m/s]";yl="Radiant offset [K]"
        f=go.Figure(go.Heatmap(x=x,y=y,z=z,colorscale="RdBu_r",colorbar=dict(title="UTCI [°C]"),hoverongaps=False)).update_layout(xaxis_title=xl,yaxis_title=yl)
        note="Hypothetical controlled states: RH 50%; remaining fixed inputs T=30 °C, wind 2 m/s, MRT offset 0 K as applicable. Not occurrence frequencies."
    elif k=="snow_calendar":
        observed=p4.daily_stats(df,cat.S,nonnegative=True)["max"]
        cover=observed.gt(0).astype(float).where(observed.notna())
        if not cover.notna().any():raise NotApplicable("No complete valid daily snow observations.")
        days=pd.date_range(cover.index.min(),cover.index.max(),freq="D")
        z=np.asarray(cover.reindex(days),float)[None,:]
        f=go.Figure(go.Heatmap(x=days,y=["Snow cover"],z=z,zmin=0,zmax=1,colorscale=[[0,"#FFFFFF"],[1,"#427CAD"]],hoverongaps=False,colorbar=dict(tickvals=[0,1],ticktext=["No snow","Snow"]))).update_layout(xaxis_title="Date")
        note+=" Daily maximum snow depth >0 cm; complete observed days only."
    elif k=="correlation":
        corr,n=p4.correlation(df,list(a))
        labels=[cat.LABELS[c1] for c1 in a]
        f=go.Figure(go.Heatmap(x=labels,y=labels,z=corr,zmin=-1,zmax=1,zmid=0,colorscale="RdBu_r",customdata=n,colorbar=dict(title="r"),hovertemplate="%{x} / %{y}<br>r=%{z:.3f}, n=%{customdata}<extra></extra>"))
        note+=" Pairwise Pearson coefficient, at least 3 coincident samples. No causal claim."
    elif k=="joint":
        y,style=a
        if style=="scatter":
            x1=base.numeric(df,c);y1=base.numeric(df,y);ok=x1.notna()&y1.notna()
            if not ok.any():raise NotApplicable("No paired observations.")
            f=go.Figure(go.Scattergl(x=x1[ok],y=y1[ok],mode="markers",marker=dict(size=3,opacity=.35)))
        else:
            values=p4.joint_density(df,c,y,bins=25)
            if values is None:raise NotApplicable("No paired observations.")
            x1,y1,z,h=values
            f=go.Figure(go.Heatmap(x=x1,y=y1,z=z,customdata=h,colorscale="Blues",colorbar=dict(title="%")))
        f.update_layout(xaxis_title=f"{cat.LABELS[c]} [{u}]",yaxis_title=f"{cat.LABELS[y]} [{cat.UNITS[y]}]")
        note+=" Coincident observations only. Density chart displays probability mass in 25 × 25 bins."
    else:raise NotApplicable("No atlas renderer registered.")
    if not len(f.data):raise NotApplicable("No plotted data.")
    f.update_layout(template="plotly_white",title=title)
    from .calendar_heatmap_axes import apply_calendar_heatmap_axes,apply_monthly_axes
    apply_calendar_heatmap_axes(f);apply_monthly_axes(f)
    if k in ("profile","percentile","heatmap","duration","histogram","box","violin","diurnal","occurrence","amplitude","native","psychrometric","monthly_radiation","facade","tilt","sunpath_view","sky_patches","total"):
        scope=df.loc[s.gt(0)].copy() if c and k in ("histogram","duration","box","violin") and a[0]=="wet" else df
        col=c if k in ("profile","percentile","heatmap","duration","histogram","box","violin","diurnal","occurrence","amplitude","native") else ""
        stat=base.source_interpretation(scope,d.chapter,col,cat.LABELS.get(col,""),cat.UNITS.get(col,u),thresholds=base.temperature_thresholds(context),kind=k)
        if stat and stat not in note:note=stat+"\n\n"+note
    return f,note
