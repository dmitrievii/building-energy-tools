"""Independent reproductions of existing website routes for R2.8B.

Every admitted branch names its actual interactive chart controls. No call to
make_figure or standard_figure is permitted here. Unmatched representations
remain explicitly unqualified, even if they share an interpretation kernel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer import p66_catalogue as cat
from epw_climate_analyzer import charts as ch, extended_visualization as ex
from epw_climate_analyzer import p4_extremes as p4, p3_comfort as p3
from epw_climate_analyzer.aggregations import native_interval_hours, period_total_series
from epw_climate_analyzer.temporal_filtering import display_period_labels,time_basis


class UnmatchedRoute(ValueError):
    """A corresponding independently reproduced live configuration is absent."""


def atlas_live(d,df,context):
    k,c,a=d.kind,d.column,d.args
    from epw_climate_analyzer import directional_climate as wind
    if k in ("wind_mean","wind_classes","wind_panel","wind_rain"):
        if k=="wind_panel":
            from epw_climate_analyzer.wind_findings import wind_figure_interpretation
            direction,radial,colour=a
            f,_=wind.monthly_wind_rose_panel(df,speed=c,direction=direction,
                colour=colour,radial=radial,style="Class distribution")
            return f,wind_figure_interpretation(df,f,"wind_panel",column=c)+"\n\n"+wind.MONTHLY_WIND_ROSE_NOTE
        if k=="wind_rain":
            table=wind.directional_table(df,radial="Wind-driven rain exposure",colour="Wind speed")
            return wind.directional_figure(table,"Wind-driven rain exposure","Wind speed","Website"),wind.directional_interpretation(table,"Wind-driven rain exposure","Wind speed")
        direction,month,radial,colour=a
        from epw_climate_analyzer.wind_rose_selection import select_wind_rose_period
        data=select_wind_rose_period(df,month=month or None)
        if k=="wind_classes":
            table=wind.directional_class_table(data,speed=c,direction=direction,quantity=colour,radial=radial)
            return wind.directional_class_figure(table,"Website"),wind.class_interpretation(table)
        table=wind.directional_table(data,speed=c,direction=direction,radial=radial,colour=colour)
        return wind.directional_figure(table,radial,colour,"Website"),wind.directional_interpretation(table,radial,colour)
    if k=="psychrometric":
        from epw_climate_analyzer.humidity_findings import humidity_figure_interpretation
        chart,mode=a
        p=float(context.get("guide pressure Pa",df["atmospheric_station_pressure_pa"].median()))
        f=ch.psychrometric_chart(df,chart_type=chart,pressure_pa=p,data_mode=mode)
        return f,humidity_figure_interpretation(df,f,k,title=f"Psychrometric · {chart} · {mode}")
    if k in ("facade","tilt","sky_patches","sunpath_view","monthly_radiation"):
        from epw_climate_analyzer.solar_findings import solar_figure_interpretation,facade_figure_interpretation
        if k=="facade":
            from epw_climate_analyzer.facade_orientation import orientation_period_components,orientation_components_chart
            table,flat=orientation_period_components(df,tilt_deg=90.)
            f=orientation_components_chart(table,flat,tilt_deg=90.,style=a[0],selected=())
            return f,facade_figure_interpretation(f,tilt_deg=90.)
        if k=="tilt":
            from epw_climate_analyzer.solar import orientation_tilt_matrix
            from epw_climate_analyzer.surface_radiation_views import orientation_curves
            matrix=orientation_tilt_matrix(df)
            f=ch.matrix_heatmap(matrix,"Website","Azimuth [deg]","Tilt [deg]","kWh/m²") if a[0]=="Heat map" else orientation_curves(matrix)
        elif k=="sky_patches":
            from epw_climate_analyzer.sky_distribution import cumulative_sky,sky_figure
            quantity,mf,style,model=a
            f=sky_figure(cumulative_sky(df,mf=mf,quantity=quantity,model=model),quantity,style)
        elif k=="sunpath_view":
            from epw_climate_analyzer.sun_path_views import classic_sun_path,technical_sun_path,sun_path_3d
            from epw_climate_analyzer.solar_shading import thermal_overlay
            style,colour=a
            thermal=colour in ("Outdoor temperature","Solar benefit / risk")
            if style=="2D":f=classic_sun_path(df,radiation_field=None if thermal or colour=="None" else colour)
            elif style=="Technical":f=technical_sun_path(df)
            else:f=sun_path_3d(df)
            if thermal:thermal_overlay(f,df,colour,cold=18.,warm=26.,technical=style=="Technical")
        else:
            from epw_climate_analyzer.monthly_radiation import available_source_quantities,monthly_source_irradiation,monthly_radiation_chart,monthly_rose_years,monthly_rose_table
            table=monthly_source_irradiation(df,available_source_quantities(df))
            if a[0]=="Monthly rose":
                years=monthly_rose_years(table)
                table=monthly_rose_table(table,year=years[-1] if years else None)
            f=monthly_radiation_chart(table,style=a[0])
        return f,solar_figure_interpretation(df,f,k,column=c,args=a)
    if k in ("daylight","sunshine","sky_conditions"):
        from epw_climate_analyzer.sky_findings import sky_figure_interpretation
        if k=="daylight":f=ex.daylight_envelope(df.index,float(context["latitude"]));mode=k
        elif k=="sunshine":f=ex.sunshine_hour_heatmap(df);mode="sunshine_heatmap"
        else:
            if c!="total_sky_cover_tenths":
                raise UnmatchedRoute("Website monthly sky-condition distribution currently selects total cover")
            table=ex.sky_distribution(df)
            table.columns=["Clear","Intermediate","Overcast"]
            f=ex.occurrence_figure(table,"","Hours");mode=k
        return f,sky_figure_interpretation(df,f,mode,column=c,latitude=context.get("latitude"))
    if k in ("shading_calendar","shading_profiles","shading_temporal","shading_irradiation"):
        from epw_climate_analyzer.shading_findings import (
            shading_temporal_interpretation,shading_monthly_interpretation,shading_ledger_interpretation)
        from epw_climate_analyzer.solar_shading import TOTAL_DEVICE,shading_ledger,monthly_shading_figure
        from epw_climate_analyzer.shading_calendar import shading_frame,shading_calendar,monthly_shading_profiles,DEFAULT_THRESHOLD
        from epw_climate_analyzer.shading_temporal import temporal_shading_tables,shading_monthly_rose
        if k=="shading_irradiation":
            ledger=shading_ledger(df,**cat.GEOMETRY)
            cols=["Unshaded total","Shaded total (direct-only)","Intercepted direct"]
            table=pd.DataFrame({key:period_total_series(ledger[key],df,"Monthly")/1000 for key in cols})
            f=monthly_shading_figure(table,display_period_labels(table.index,"Monthly",time_basis(df)))
            return f,shading_ledger_interpretation(ledger,df,geometry=cat.GEOMETRY)
        metric=a[0]
        if k=="shading_temporal":
            _,style,year,device=a
            if style!="Monthly rose":raise UnmatchedRoute("Different shading heatmap representation")
            selected=df.loc[df.index.year==year]
            monthly,_=temporal_shading_tables(selected,geometry=cat.GEOMETRY,metric=metric)
            return shading_monthly_rose(monthly,metric),shading_monthly_interpretation(monthly,metric,year=year)
        device=a[4] if k=="shading_calendar" else TOTAL_DEVICE
        frame=shading_frame(df,geometry=cat.GEOMETRY,metric=metric,device=device,threshold=DEFAULT_THRESHOLD)
        if k=="shading_calendar":
            f=shading_calendar(frame,metric,a[1],a[2],a[3],title="Website",threshold=DEFAULT_THRESHOLD)
        else:f,_=monthly_shading_profiles(frame,metric,sorted(set(df.index.month)))
        return f,shading_temporal_interpretation(frame,metric,device=device,threshold=DEFAULT_THRESHOLD)
    if k=="climate_summary":
        table=ex.climate_summary_table(df)
        if table.empty:raise UnmatchedRoute("No complete paired month")
        return ex.climate_summary_figure(table,a[0]),ex.climate_summary_interpretation(table,a[0])
    if k=="rolling":
        from epw_climate_analyzer.precipitation_findings import rolling_interpretation
        s=p4.rolling_windows(df,c,a[0],total=True,nonnegative=True)
        return go.Figure(go.Scatter(x=s.index,y=s,mode="lines",connectgaps=False)),rolling_interpretation(df,a[0])
    if k=="freeze_days":
        from epw_climate_analyzer.precipitation_findings import freeze_interpretation
        table=p4.freeze_thaw_days(df,1.).resample("MS").sum(min_count=1)
        f=go.Figure()
        for key in table:f.add_bar(x=table.index,y=table[key],name=key)
        return f,freeze_interpretation(df,wet_threshold=1.)
    if k=="moisture":
        from epw_climate_analyzer.humidity_findings import humidity_figure_interpretation
        table=p3.monthly_totals(df,p3.moisture_loads(df,airflow=1000.,target=9.))
        f=go.Figure()
        for key in table:f.add_bar(x=table.index,y=table[key],name=key)
        return f,humidity_figure_interpretation(df,None,"moisture",airflow_m3_h=1000.,target_g_kg=9.)
    if k=="vent_load":
        from epw_climate_analyzer.hvac_findings import conditioning_monthly_figure,conditioning_interpretation
        q=p3.ventilation_loads(df,airflow=1000.,heat=20.,cool=26.,w_low=4.,w_high=9.)
        return conditioning_monthly_figure(df,q,grouped=True),conditioning_interpretation(df,q,airflow=1000.,heat=20.,cool=26.,w_low=4.,w_high=9.)
    if k=="economizer_stages":
        from epw_climate_analyzer.hvac_findings import economizer_stages,economizer_stages_figure,economizer_interpretation
        return economizer_stages_figure(economizer_stages(df,h_return=50.)),economizer_interpretation(df,h_return=50.)
    if k=="critical_windows":
        from epw_climate_analyzer.p4_design_charts import critical_windows_figure
        from epw_climate_analyzer.hvac_findings import critical_window_interpretation
        f,table,details=critical_windows_figure(df,c,d.unit,hours=72,upper=a[0])
        if f is None:raise UnmatchedRoute(details)
        quantity={cat.T:"Air temperature",cat.W:"Humidity ratio",cat.H:"Moist-air enthalpy"}.get(c,c)
        return f,critical_window_interpretation(table,quantity=quantity,unit=d.unit,upper=a[0],hours=72)+" "+details
    raise UnmatchedRoute("No independently reproduced matching website controls for "+k)


def standard_live(entry,df,context):
    ident,chapter,title,c,u,k=entry
    if k=="climograph":
        table=ex.climate_summary_table(df)
        if table.empty:raise UnmatchedRoute("No complete paired month")
        return ex.climate_summary_figure(table,"Walter–Lieth diagram"),ex.climate_summary_interpretation(table,"Walter–Lieth diagram")
    if k in ("rain_days","wind_orientation","shading_orientation","facade_temperature","relative_sunshine"):
        if k=="rain_days":
            from epw_climate_analyzer.precipitation_findings import rain_day_classes,rain_day_classes_figure,rainfall_summary
            return rain_day_classes_figure(rain_day_classes(df)),rainfall_summary(df)
        if k=="wind_orientation":
            from epw_climate_analyzer.wind_findings import wind_opportunity,wind_opportunity_figure,wind_design_interpretation
            table,sectors=wind_opportunity(df,min_speed_m_s=.5)
            return wind_opportunity_figure(table,sectors),wind_design_interpretation(df,min_speed_m_s=.5)
        if k=="shading_orientation":
            from epw_climate_analyzer.shading_findings import orientation_shading_table,orientation_shading_figure,orientation_shading_interpretation
            table=orientation_shading_table(df,geometry=cat.GEOMETRY,cold_c=18.,hot_c=26.)
            return orientation_shading_figure(table,cold_c=18.,hot_c=26.),orientation_shading_interpretation(table,cold_c=18.,hot_c=26.)
        if k=="facade_temperature":
            from epw_climate_analyzer.solar_findings import facade_temperature_table,facade_temperature_figure,facade_temperature_interpretation
            table=facade_temperature_table(df,cold_c=18.,hot_c=26.)
            return facade_temperature_figure(table,cold_c=18.,hot_c=26.),facade_temperature_interpretation(table,cold_c=18.,hot_c=26.)
        # The website uses the same monthly relative sunshine statistic.
        from epw_climate_analyzer.daylight import monthly_daylight_sunshine_summary
        from epw_climate_analyzer.sky_findings import sunshine_interpretation
        table=monthly_daylight_sunshine_summary(df,float(context["latitude"]))
        return go.Figure(go.Bar(x=table["month"],y=table["relative_sunshine_pct"])),sunshine_interpretation(df,latitude=float(context["latitude"]),kind="relative_sunshine")
    mappings={
        "psychrometric":("psychrometric",("T-d","Climate zone")),
        "facade":("facade",("Bar chart",)),
        "windrose":("wind_classes",(cat.WD,0,"Percentage","Wind speed")),
        "wind_panel":("wind_panel",(cat.WD,"Percentage","Wind speed")),
        "wind_rain":("wind_rain",()),
        "daylight":("daylight",()),
        "sky_conditions":("sky_conditions",()),
        "shading_ledger":("shading_irradiation",()),
        "hvac_energy":("vent_load",()),
        "hvac_economizer":("economizer_stages",()),
        "hvac_critical":("critical_windows",(True,)),
    }
    if k in mappings:
        kind,args=mappings[k]
        return atlas_live(cat.Diagram(ident,chapter,title,kind,c,u,args),df,context)
    raise UnmatchedRoute("No independently reproduced matching website controls for "+k)
