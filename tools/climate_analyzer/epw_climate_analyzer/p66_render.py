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
from .atlas_profile import phase
from .chart_theme import metric_color, series_color, semantic_color_from_text, event_color

class NotApplicable(ValueError):
    """Supported scientific method, but no valid qualifying state in this scope."""

def _line(s,title,unit,column=None):
    f=go.Figure(go.Scatter(x=s.index,y=s,mode="lines+markers" if len(s)<32 else "lines",connectgaps=False,line_color=metric_color(column) if column else series_color(str(s.name),title)))
    return f.update_layout(template="plotly_white",title=title,yaxis_title=unit,xaxis_title="Period")

def _bars(a,title,unit):
    if isinstance(a,pd.Series):a=a.to_frame()
    if a.empty or not a.notna().any().any():raise NotApplicable("No valid observations for this representation.")
    f=go.Figure()
    for c in a:f.add_bar(x=a.index,y=a[c],name=str(c),marker_color=series_color(str(c),title))
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
        f=go.Figure(go.Scatter(x=table.duration,y=table.peak,mode="markers",marker_color=event_color(quantity,above),customdata=table.excess,
            hovertemplate="Duration %{x}<br>Peak %{y}<br>Integrated excess %{customdata}<extra></extra>"))
        return f.update_layout(template="plotly_white",xaxis_title=f"Duration [{unit}]",yaxis_title=quantity)
    f=_bars(table.duration.value_counts().sort_index().rename("Number of events"),"Duration distribution","Events")
    f.update_traces(marker_color=event_color(quantity,above))
    return f.update_xaxes(title=f"Duration [{unit}]")

def _pressure(df,context):
    try:
        p=float(context["guide pressure Pa"])
        if np.isfinite(p) and p>0:return p
    except (KeyError,TypeError,ValueError):pass
    p=base.numeric(df,"atmospheric_station_pressure_pa").median()
    return float(p) if np.isfinite(p) and p>0 else 101325.

def _strip_atlas_attrs(values):
    values.attrs={}
    return values

def make_figure(d,df,context,reference_df=None,cache=None):
    if d.status!="available":raise NotApplicable(d.reason)
    if cache is None:cache={}
    k,c,u,a=d.kind,d.column,d.unit,d.args
    s=base.numeric(df,c) if c else None
    title=d.title
    dt=agg.native_interval_hours(df)
    note=""
    def memo(key,fn):
        if hasattr(cache,"get_or_compute"):return cache.get_or_compute(key,fn)
        if key not in cache:cache[key]=fn()
        return cache[key]
    def utci_model(mode):
        # Atlas charts consume only these numerical series. The original df
        # supplies chronology, cadence and aggregation semantics. Discard
        # unrelated source metadata and the MRT frame from the retained result.
        def compute():
            values,_=p3.utci_frame(df,model=mode)
            return values.set_axis(df.index).copy(deep=False).pipe(_strip_atlas_attrs)
        return memo(("utci",mode),compute)
    def design():
        from .p6_dashboard import design_ledgers
        return memo("design",lambda:design_ledgers(df,reference_df=reference_df)[0])
    if k=="native":f=ch.time_series_profile_chart(df,c,"Native",title,u,"Observed values")
    elif k=="time_series":
        f=ch.time_series_profile_chart(df,c,a[0],title,u,a[1])
    elif k=="profile":f=ch.profile_ribbon_chart(df,c,a[0],title,u)
    elif k=="percentile":f=ch.percentile_band_chart(df,c,a[0],title,u)
    elif k=="heatmap":
        bounds=base.temperature_thresholds(context) if c in ch.TEMPERATURE_HEATMAP_COLUMNS else None
        f=ch.temporal_heatmap_chart(df,c,*a,title,u,temperature_thresholds=bounds)
        if bounds:
            note+=f" Common continuous absolute temperature gradient; transition reference temperatures {bounds[0]:g}/{bounds[1]:g} °C."
            if c!=cat.T:note+=" Colours map the measured temperature on the selected absolute scale."
        if agg.heatmap_has_single_observation_cells(df,a[0],a[1]):
            note+=" Each occupied calendar cell displays the single corresponding source observation."
        else:note+=f" Cell statistic: {a[2]}; comparison: {a[1]}."
    elif k in ("duration","histogram","box","violin"):
        scope=df.loc[s.gt(0)].copy() if a[0]=="wet" else df
        if scope.empty:raise NotApplicable("No wet observations.")
        if k=="duration":
            from .p4_design_charts import add_design_quantiles,supports_design_quantiles,DESIGN_NOTE,DESIGN_PERCENTAGES
            f=ex.probability_figure(scope,c,u,a[1]) if a[2]=="probability" else ch.duration_chart(scope,c,title,u,ascending=a[1])
            percentages=context.get("duration quantile percentages",DESIGN_PERCENTAGES)
            if percentages and supports_design_quantiles(scope,c):
                add_design_quantiles(f,scope,c,u,ascending=a[1],percentage=a[2]=="probability",percentages=percentages)
                note+=" "+DESIGN_NOTE
        elif k=="histogram":f=ch.histogram_chart(scope,c,title,u,bins=40);note+=" Reference 40 histogram bins."
        else:f=ch.monthly_box_chart(scope,c,title,u,violin=k=="violin")
        if a[0]=="wet":note+=" Positive precipitation intervals only."
    elif k=="ridgeline":
        from .ridgeline import ridgeline_figure
        from .figure_interpretation_contract import bind_figure_interpretation
        try:f,note=ridgeline_figure(df,c,u,cat.LABELS[c],grouping=a[0],wet_only=a[1]=="wet")
        except ValueError as exc:raise NotApplicable(str(exc)) from exc
        bind_figure_interpretation(f,note)
        return f,note
    elif k=="diurnal":
        table=memo(("diurnal",c),lambda:ex.diurnal_statistics(df,c))
        f=ex.diurnal_figure(table,c,u,representation=a[0],centre=a[1],band=a[2])
        note+=" Equivalent clock hours pooled across selected months; complete source hours only."
    elif k=="occurrence":
        edges=ex.occurrence_default_edges(s,c,basis=a[0],daily_stat=a[1],interval_hours=dt)
        if not edges:raise NotApplicable("No valid class boundaries.")
        if c=="diffuse_radiation_fraction_pct" and a[0]=="Days":
            from .solar_findings import diffuse_fraction_daily_occurrence
            table=diffuse_fraction_daily_occurrence(df,edges,daily_stat=a[1])
            note+=" Daytime fraction uses only GHI>0 and fully observed GHI days with complete positive-GHI DHI; nighttime zero-GHI intervals are omitted from the ratio. Daily mean averages valid daylight interval fractions."
        else:
            table=ex.occurrence_table(df,c,edges,basis=a[0],daily_stat=a[1])
        if table.empty:raise NotApplicable("No complete observations for the selected class basis.")
        f=ex.occurrence_figure(table,u,a[0]);note+=" Reference classes: "+", ".join(ex.occurrence_boundary_label(v) for v in edges)+f" {u}. Classes are disjoint."
        if c in ex.DEPTH_OCCURRENCE_COLUMNS:note+=" Zero is a separate dry/snow-free class. Negative or missing depths are excluded. Positive bins classify observed accumulation depths."
        if c in ex.ILLUMINANCE_OCCURRENCE_COLUMNS:note+=" "+ex.ILLUMINANCE_OCCURRENCE_NOTE
        if ex.radiation_occurrence_kind(c):note+=" "+ex.radiation_occurrence_note(c,dt,basis=a[0],daily_stat=a[1])
        if c in ex.WIND_SPEED_COLUMNS:note+=" "+ex.WIND_OCCURRENCE_NOTE
    elif k=="amplitude":f=ex.amplitude_figure(df,c,a[0],cat.LABELS[c]);note+=" Amplitude equals the maximum minus minimum of observations within each aggregation period."
    elif k=="total":
        from .residual_findings import extensive_total_figure
        try:f,note=extensive_total_figure(df,c,a[0])
        except ValueError as exc:raise NotApplicable(str(exc)) from exc
    elif k=="climate_summary":
        table=memo("climate_summary",lambda:ex.climate_summary_table(df))
        if table.empty:raise NotApplicable("No paired complete months.")
        f=ex.climate_summary_figure(table,a[0]);note=ex.climate_summary_interpretation(table,a[0])
    elif k=="degree":
        from .degree_metrics import degree_metric_table,degree_metric_interpretation,degree_legend_below
        result=degree_metric_table(df,metric=a[0],aggregation=a[1],heating_indoor_c=20.,heating_limit_c=12.,cooling_indoor_c=26.,cooling_limit_c=26.,require_complete_days=True)
        if result.empty:raise NotApplicable("No complete valid degree-metric periods.")
        note=degree_metric_interpretation(result,metric=a[0],heating_indoor_c=20.,heating_limit_c=12.,cooling_indoor_c=26.,cooling_limit_c=26.)
        result=result.copy();result.index=display_period_labels(result.index,a[1],time_basis(df))
        f=_bars(result,title,u)
        degree_legend_below(f)
    elif k=="temp_threshold":
        from .residual_findings import temperature_threshold_figure
        low,high=base.temperature_thresholds(context)
        f,note=temperature_threshold_figure(df,a[0],low=low,high=high)
    elif k=="temp_events":
        stat,above,style=a;threshold=30. if above else 0.
        daily,ev=memo(("temp_events",stat,above),lambda:p4.temperature_events(df,threshold=threshold,above=above,minimum=3,stat=stat))
        f=_event_figure(ev,daily[stat],style,threshold,above,"days","Daily temperature [°C]")
        from .p4_ui import event_interpretation
        note=event_interpretation(ev,unit="days")
    elif k=="day_indicators":
        f=_bars(p4.day_indicators(df).resample("MS").sum(min_count=1),title,u)
        from .temperature_findings import temperature_figure_interpretation
        note=temperature_figure_interpretation(df,f,"day_indicators")
    elif k=="psychrometric":
        chart,mode=a;p=_pressure(df,context)
        f=ch.psychrometric_chart(df,chart_type=chart,pressure_pa=p,data_mode=mode)
        note+=f" Reference guide pressure {p:,.0f} Pa; chart coordinates use existing source-derived psychrometrics."
    elif k=="persistence":
        threshold,above,style=a;step=p4.cadence(df)
        ev=memo(("persistence",c,threshold,above),lambda:p4.events(s,threshold=threshold,above=above,minimum=3,step=step))
        f=_event_figure(ev,s,style,threshold,above,"hours",cat.LABELS.get(c,u),step=step)
        from .p4_ui import event_interpretation
        if d.chapter==cat.HUM:
            from .humidity_findings import humidity_figure_interpretation
            extra=humidity_figure_interpretation(df,None,"persistence",column=c,args=(threshold,above,""))
        else:
            from .wind_findings import wind_figure_interpretation
            extra=wind_figure_interpretation(df,None,"persistence",column=c,args=(threshold,above))
        note=event_interpretation(ev,unit="hours",extra_note=extra)
    elif k=="condensation":
        from .p3_ui import duration_ledger_figure
        from .humidity_findings import humidity_figure_interpretation
        margin=p3.condensation_margin(df,15.)
        if not margin.notna().any():raise NotApplicable("No valid dew-point observations.")
        f=duration_ledger_figure(df,pd.DataFrame({"Surface minus dew point":margin}),title,u)
        note=humidity_figure_interpretation(df,None,"condensation",surface_c=15.)
    elif k=="moisture":
        f=_bars(p3.monthly_totals(df,p3.moisture_loads(df,airflow=1000.,target=9.)),title,u)
        note+=" Reference 1,000 m³/h outdoor airflow conditioned to a 9 g/kg humidity-ratio threshold; monthly bars quantify the associated moisture transfer."
    elif k=="sunpath_view":
        from .sun_path_views import classic_sun_path,technical_sun_path,sun_path_3d
        from .solar_shading import thermal_overlay
        style,colour=a
        thermal=colour in ("Outdoor temperature","Solar benefit / risk")
        f=classic_sun_path(df,radiation_field=None if thermal or colour=="None" else colour) if style=="2D" else technical_sun_path(df) if style=="Technical" else sun_path_3d(df)
        if thermal:thermal_overlay(f,df,colour,cold=18.,warm=26.,technical=style=="Technical")
        note+=" Solar reference paths are astronomical guides; thermal classifications show observed outdoor temperature coincident with solar angles."
    elif k=="sky_patches":
        from .sky_distribution import cumulative_sky,sky_figure
        quantity,mf,style,*rest=a;model=rest[0] if rest else "Isotropic"
        table=memo(("sky",quantity,mf,model),lambda:cumulative_sky(df,mf=mf,quantity=quantity,model=model))
        f=sky_figure(table,quantity,style)
        note+=f" {model}. Horizontal irradiation contribution per sky patch; isotropic sky is the reference model, and Perez is an optional research model."
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
    elif k=="wind_panel":
        from .directional_climate import monthly_wind_rose_panel,MONTHLY_WIND_ROSE_NOTE
        direction,radial,colour=a
        try:f,_=monthly_wind_rose_panel(df,speed=c,direction=direction,radial=radial,colour=colour,title=title)
        except ValueError as exc:raise NotApplicable(str(exc)) from exc
        from .wind_findings import wind_figure_interpretation
        note=wind_figure_interpretation(df,f,"wind_panel",column=c,title=title)+"\n\n"+MONTHLY_WIND_ROSE_NOTE
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
    elif k=="wind_rain":
        from .directional_climate import directional_table,directional_figure,directional_interpretation
        radial="Wind-driven rain exposure"
        table=directional_table(df,radial=radial,colour=radial)
        if not table.radius.notna().any():raise NotApplicable("No coincident wind and precipitation observations.")
        f=directional_figure(table,radial,radial,title)
        note=directional_interpretation(table,radial,radial)
    elif k=="wetdry":
        wet,style=a;daily,wet_e,dry_e=memo("wetdry",lambda:p4.wet_dry_events(df))
        ev=wet_e if wet else dry_e
        f=_event_figure(ev,daily["sum"],style,1.,wet,"days","Daily precipitation [mm]")
        from .p4_ui import event_interpretation
        from .precipitation_findings import wet_dry_interpretation
        note=event_interpretation(ev,unit="days",extra_note=wet_dry_interpretation(df,wet=wet,threshold=1.,minimum=1))
    elif k=="rolling":
        v=p4.rolling_windows(df,c,a[0],total=True,nonnegative=True)
        if not v.notna().any():raise NotApplicable("No complete rolling windows.")
        f=_line(v,title,u,c);note+=f" Trailing complete {a[0]} h windows; gaps break the window."
    elif k=="cumulative":
        f=_line(p4.cumulative_precipitation(df),title,u,cat.P)
    elif k=="freeze_days":
        f=_bars(p4.freeze_thaw_days(df).resample("MS").sum(min_count=1),title,u)
        note+=" Air-temperature crossing (Tmin<0, Tmax>0) with a wet-day subset at ≥1 mm/day indicates periods of potential freeze–thaw exposure."
    elif k=="freeze_cycles":
        table=p4.freeze_thaw_cycles(df,wet_threshold=1.)
        if table.empty:raise NotApplicable("No qualifying warm–freeze–warm sequences.")
        table=table.set_index("Thaw timestamp",drop=False)
        monthly=pd.DataFrame({"Observed complete sequences":pd.Series(1.,index=table.index),
                              "Antecedent wet sequences":table["Antecedent wet at freeze"]})
        f=_bars(monthly.resample("MS").sum(min_count=1),title,"Sequences")
    elif k=="daylight":f=ex.daylight_envelope(df.index,float(context["latitude"]));note+=" Ideal horizon and apparent solar time."
    elif k=="sunshine":f=ex.sunshine_hour_heatmap(df);note+=" Measured sunshine duration, complete clock hours."
    elif k=="sky_conditions":
        table=ex.sky_distribution(df,c);table.columns=["Clear","Intermediate","Overcast"]
        f=ex.occurrence_figure(table,"","Hours")
    elif k=="illumination":
        from .sky_findings import illuminance_availability_figure
        try:f,note=illuminance_availability_figure(df,c,threshold_lux=300.,aggregation=a[0])
        except ValueError as exc:raise NotApplicable(str(exc)) from exc
    elif k=="shading_mask":
        from .shading_sketch import window_shading_sketch
        from .shading_findings import shading_mask_interpretation
        f=window_shading_sketch(**cat.GEOMETRY)
        note=shading_mask_interpretation(cat.GEOMETRY)
    elif k in ("shading_calendar","shading_profiles"):
        from .shading_calendar import shading_frame,shading_calendar,monthly_shading_profiles,shading_note
        from .solar_shading import TOTAL_DEVICE
        metric=a[0];device=a[4] if k=="shading_calendar" else TOTAL_DEVICE
        frame=memo(("shading_frame",metric,device),lambda:shading_frame(df,geometry=cat.GEOMETRY,metric=metric,device=device))
        if k=="shading_calendar":
            f=shading_calendar(frame,metric,a[1],a[2],a[3],title=title)
        else:
            f,_=monthly_shading_profiles(frame,metric,sorted(set(df.index.month)))
        from .shading_findings import shading_temporal_interpretation
        note=shading_temporal_interpretation(frame,metric,device=device)
    elif k=="shading_temporal":
        from .shading_temporal import temporal_shading_tables,shading_monthly_rose,shading_month_hour_heatmap
        metric,style,year,device=a
        result=memo(("shading",metric,year),lambda:temporal_shading_tables(df.loc[df.index.year==year].copy(),geometry=cat.GEOMETRY,metric=metric))
        monthly,cells=result[:2]
        f=shading_monthly_rose(monthly,metric) if style=="Monthly rose" else shading_month_hour_heatmap(cells,metric,device=device)
        from .shading_findings import (
            shading_monthly_interpretation,shading_cells_interpretation)
        stat=(shading_monthly_interpretation(monthly,metric,year=year)
              if style=="Monthly rose" else
              shading_cells_interpretation(cells,metric,device=device,year=year))
        note=stat
    elif k=="shading_irradiation":
        from .solar_shading import shading_ledger,monthly_shading_figure
        ledger=shading_ledger(df,**cat.GEOMETRY)
        cols=["Unshaded total","Shaded total (direct-only)","Intercepted direct"]
        table=pd.DataFrame({c:agg.period_total_series(ledger[c],df,"Monthly")/1000 for c in cols})
        f=monthly_shading_figure(table,display_period_labels(table.index,"Monthly",time_basis(df)))
        from .shading_findings import shading_ledger_interpretation
        note=shading_ledger_interpretation(ledger,df,geometry=cat.GEOMETRY)
    elif k in ("eligibility_map","eligibility_total"):
        from .residual_findings import eligibility_figure
        try:f,note=eligibility_figure(df,a[0],a[1],view="map" if k=="eligibility_map" else "total",ledger=design())
        except ValueError as exc:raise NotApplicable(str(exc)) from exc
    elif k=="nv_special":
        from .residual_findings import nv_special_figure
        try:f,note=nv_special_figure(df,a[0])
        except ValueError as exc:raise NotApplicable(str(exc)) from exc
    elif k=="passive":
        from .residual_findings import passive_matrix_figure
        try:f,note=passive_matrix_figure(df)
        except ValueError as exc:raise NotApplicable(str(exc)) from exc
    elif k=="vent_load":
        from .hvac_findings import conditioning_monthly_figure,conditioning_interpretation
        ledger=memo("hvac_ref_energy",lambda:p3.ventilation_loads(
            df,airflow=1000.,heat=20.,cool=26.,w_low=4.,w_high=9.,
        ))
        f=conditioning_monthly_figure(df,ledger,grouped=True,title=title)
        note=conditioning_interpretation(
            df,ledger,airflow=1000.,heat=20.,cool=26.,w_low=4.,w_high=9.,
        )
    elif k=="economizer_stages":
        from .hvac_findings import economizer_stages,economizer_stages_figure,economizer_interpretation
        steps=economizer_stages(df,h_return=50.)
        f=economizer_stages_figure(steps)
        note=economizer_interpretation(df,h_return=50.)
    elif k=="adaptive":
        from .p3_adaptive_chart import selected_daily_bands,adaptive_figure,adaptive_interpretation
        history=df if reference_df is None else reference_df
        table=memo("adaptive",lambda:p3.adaptive_bands(history))
        table=selected_daily_bands(table,df)
        if not table["Running mean"].notna().any():raise NotApplicable(adaptive_interpretation(table))
        extrapolate=bool(a and a[0]=="research_extrapolation")
        f=adaptive_figure(table,extrapolate=extrapolate);note=adaptive_interpretation(table,extrapolate=extrapolate)
        title="Adaptive comfort · Categories I–III"+(" · Research extrapolation" if extrapolate else "")
    elif k=="utci":
        model,style=a
        mode="Uniform radiant offset" if model=="Uniform radiant offset" else "Open-sky screening"
        values=utci_model(mode)
        col=model
        val=values[col]
        if not val.notna().any():raise NotApplicable("No valid UTCI states in model domain.")
        if style=="heatmap":
            from .utci_presentation import stress_heatmap,STRESS_NOTE
            with phase("utci_aggregation"):grid=p3.annual_hour_grid(df,val)
            with phase("utci_plot"):f=stress_heatmap(grid.columns,grid.index,grid,title=title,x_label="Date",y_label="Hour of day")
        elif style=="duration":
            from .utci_presentation import duration_figure
            with phase("utci_plot"):f=duration_figure(val.to_frame(),dt,title)
        else:
            with phase("utci_aggregation"):table=p3.utci_class_hours(df,val)
            f=go.Figure()
            for c1,color in zip(p3.CLASSES,p3.COLORS):
                if c1 in table:f.add_bar(x=table.index,y=table[c1],name=c1,marker_color=color)
            f.update_layout(barmode="stack",yaxis_title="Hours")
        from .utci_findings import utci_view_interpretation
        note=utci_view_interpretation(df,values,style,exposure=col)
    elif k=="critical_windows":
        from .p4_design_charts import critical_windows_figure
        from .hvac_findings import critical_window_interpretation
        f,table,detail=critical_windows_figure(df,c,u,upper=a[0])
        if f is None:raise NotApplicable(detail)
        quantity={"dry_bulb_temperature_c":"Air temperature",
                  "humidity_ratio_g_kg":"Humidity ratio",
                  "moist_air_enthalpy_kj_kg":"Moist-air enthalpy"}.get(c,c)
        note=critical_window_interpretation(
            table,quantity=quantity,unit=u,upper=a[0],hours=72,
        )+" "+detail
    elif k in ("utci_pair","utci_pair_delta","utci_pair_stress","utci_pair_mrt"):
        from .utci_findings import (
            paired_monthly_figure,paired_delta_figure,paired_threshold_figure,
            utci_view_interpretation,mrt_monthly_figure,
        )
        values=utci_model("Open-sky screening")
        common=values.dropna(subset=["Open sun","Direct-beam shade"])
        if common.empty:raise NotApplicable("No coincident admitted UTCI exposure states.")
        note=utci_view_interpretation(df,values,k)
        if k=="utci_pair":
            f=paired_monthly_figure(df,common,title=title)
            from .utci_presentation import add_stress_bands
            add_stress_bands(f,common.resample("MS").mean())
        elif k=="utci_pair_delta":
            f=paired_delta_figure(df,common)
        elif k=="utci_pair_stress":
            f=paired_threshold_figure(df,common)
        else:
            radiation=memo("utci_mrt",lambda:p3.radiant_scenarios(df))
            if radiation.empty:raise NotApplicable("Missing longwave and shortwave radiation inputs.")
            radiation=radiation.where(values[["Open sun","Direct-beam shade"]].notna().all(axis=1))
            f=mrt_monthly_figure(radiation)
    elif k=="utci_sensitivity":
        from .utci_findings import utci_sensitivity_inputs,utci_sensitivity_interpretation
        from .utci_presentation import stress_heatmap
        axis=a[0]
        x,y,inputs,xl,yl=utci_sensitivity_inputs(axis)
        z=p3.utci_values(*inputs)
        f=stress_heatmap(x,y,z,title=title,x_label=xl,y_label=yl)
        note=utci_sensitivity_interpretation(axis)
    elif k=="snow_calendar":
        from .p4_ui import snow_calendar_chart
        from .precipitation_findings import snow_summary
        observed=p4.daily_stats(df,cat.S,nonnegative=True)["max"]
        cover=observed.gt(0).astype(float).where(observed.notna())
        if not cover.notna().any():raise NotApplicable("No complete valid daily snow observations.")
        year=a[0] if a else int(cover.index.year.max())
        f,note=snow_calendar_chart(cover,year,title=title,note=snow_summary(df))
    elif k=="correlation":
        from .relationship_findings import correlation_chart
        f,note=correlation_chart(df,a)
    elif k=="joint":
        from .relationship_findings import joint_chart
        try:f,note=joint_chart(df,c,a[0],style=a[1],bins=25)
        except ValueError as exc:raise NotApplicable(str(exc)) from exc
    else:raise NotApplicable("No atlas renderer registered.")
    if not len(f.data):raise NotApplicable("No plotted data.")
    # Native monthly profiles already use the canonical website builder.
    # Only the specialized irradiation total bars require this adapter.
    from .chart_theme import metric_color,is_irradiation_metric
    if k=="total" and is_irradiation_metric(c):
        f.update_traces(marker_color=metric_color(c),selector=dict(type="bar"))
    f.update_layout(template="plotly_white",title=title)
    from .calendar_heatmap_axes import apply_calendar_heatmap_axes,apply_monthly_axes,set_period_axis_scope
    with phase("chart_axis_layout"):
        aggregation=a[0] if k in ("total","temp_threshold","amplitude") and a and a[0] in ("Daily","Weekly","Monthly","Seasonal","Annual") else a[1] if k in ("degree","eligibility_total") and len(a)>1 else None
        set_period_axis_scope(f,df,aggregation=aggregation)
        apply_calendar_heatmap_axes(f);apply_monthly_axes(f)
    if k in ("native","time_series","profile","percentile") and d.chapter in (
        cat.TEMP,cat.HUM,cat.WIND,cat.SOL,cat.SKY,cat.RAIN,
    ):
        from .profile_interpretation import profile_interpretation
        with phase("interpretation"):
            statement=profile_interpretation(
                df,f,k,domain=d.chapter,column=c,title=title,args=a,
                thresholds=base.temperature_thresholds(context),
                latitude=context.get("latitude"),
                plane=df.attrs.get("r24_solar_plane","reference vertical south-facing plane"),
            )
        from .figure_interpretation_contract import bind_figure_interpretation
        bind_figure_interpretation(f,statement)
        return f,statement
    if k in ("heatmap","duration","histogram","box","violin","diurnal","occurrence","amplitude") and d.chapter in (
        cat.TEMP,cat.HUM,cat.WIND,cat.SOL,cat.SKY,cat.RAIN,
    ):
        from .profile_interpretation import generic_figure_interpretation
        selected=scope if k in ("duration","histogram","box","violin") else df
        with phase("interpretation"):
            statement=generic_figure_interpretation(
                selected,f,k,domain=d.chapter,column=c,args=a,
                thresholds=base.temperature_thresholds(context),
                latitude=context.get("latitude"),
            )
        from .figure_interpretation_contract import bind_figure_interpretation
        bind_figure_interpretation(f,statement)
        return f,statement
    if k in ("time_series","profile","percentile","heatmap","duration","histogram","box","violin","diurnal","occurrence","amplitude","native","psychrometric","monthly_radiation","facade","tilt","sunpath_view","sky_patches","total"):
        # Reuse the wet-only frame already created by distribution charts.
        wet=bool(c and k in ("histogram","duration","box","violin") and a[0]=="wet")
        scope=scope if wet else df
        col=c if k in ("time_series","profile","percentile","heatmap","duration","histogram","box","violin","diurnal","occurrence","amplitude","native") else ""
        # Non-temperature pages retain their existing interpretation contract.
        if d.chapter not in (cat.TEMP, cat.HUM, cat.WIND, cat.SOL, cat.SKY, cat.RAIN):
            with phase("interpretation"):
                stat=memo(("interpretation",d.chapter,col,k,wet),lambda:base.source_interpretation(scope,d.chapter,col,cat.LABELS.get(col,""),cat.UNITS.get(col,u),thresholds=base.temperature_thresholds(context),kind=k))
            if stat and stat not in note:note=stat+"\n\n"+note
    if d.chapter == cat.TEMP and k not in ("temp_events","degree","day_indicators","temp_threshold"):
        from .temperature_findings import temperature_figure_interpretation
        with phase("interpretation"):
            stat=temperature_figure_interpretation(
                df,f,k,column=c if c in df else cat.T,
                title=title,thresholds=base.temperature_thresholds(context))
        if stat and stat not in note:note=stat+"\n\n"+note
    if d.chapter == cat.HUM and k not in ("persistence","condensation"):
        from .humidity_findings import humidity_figure_interpretation
        with phase("interpretation"):
            stat=humidity_figure_interpretation(
                df,f,k,column=c,title=title,args=a)
        if stat and k in ("psychrometric","condensation","moisture"):note=stat
        elif stat and stat not in note:note=stat+"\n\n"+note
    if d.chapter == cat.WIND and k not in ("wind_mean","wind_classes","wind_panel","persistence"):
        from .wind_findings import wind_figure_interpretation
        with phase("interpretation"):
            stat=wind_figure_interpretation(df,f,k,column=c,title=title,args=a)
        if stat and stat not in note:note=stat+"\n\n"+note
    if d.chapter == cat.SOL and k!="total":
        from .solar_findings import solar_figure_interpretation
        with phase("interpretation"):
            stat=solar_figure_interpretation(df,f,k,column=c,title=title,args=a)
        if stat and k in ("facade","tilt","sky_patches","sunpath_view","monthly_radiation"):note=stat
        elif stat and stat not in note:note=stat+"\n\n"+note
    if d.chapter == cat.SKY and k not in ("illumination","total"):
        from .sky_findings import sky_figure_interpretation
        mode="sunshine_heatmap" if k=="sunshine" else k
        with phase("interpretation"):
            stat=sky_figure_interpretation(
                df,f,mode,column=c,title=title,args=(300.,) if k=="illumination" else a,
                latitude=context.get("latitude"))
        if stat and k in ("daylight","sunshine","sky_conditions","illumination"):note=stat
        elif stat and stat not in note:note=stat+"\n\n"+note
    if d.chapter == cat.RAIN and k!="total":
        from .precipitation_findings import precipitation_figure_interpretation
        with phase("interpretation"):
            stat=precipitation_figure_interpretation(
                df,f,k,column=c,title=title,args=a)
        if k in ("climate_summary","wind_rain","wetdry","snow_calendar"):pass  # existing plot-specific interpretation is authoritative
        elif stat and k in ("total","rolling","freeze_days","freeze_cycles","cumulative"):note=stat
        elif stat and stat not in note:note=stat+"\n\n"+note
    from .figure_interpretation_contract import bind_figure_interpretation
    note=note.strip()
    if d.chapter==cat.NV and not note:
        raise ValueError("Natural Ventilation Atlas diagram requires a scientific interpretation.")
    bind_figure_interpretation(f,note)
    return f,note
