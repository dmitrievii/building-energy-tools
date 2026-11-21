"""Calendar heatmap regressions: December, missing periods, print and physical axes."""
import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from epw_climate_analyzer.calendar_heatmap_axes import apply_calendar_heatmap_axes
from epw_climate_analyzer.aggregations import temporal_heatmap_matrix,HEATMAP_COMPARE_HOUR
from epw_climate_analyzer.charts import heatmap_chart
from epw_climate_analyzer.p6_report_structure import report_figure
from epw_climate_analyzer.p3_comfort import annual_hour_grid
from epw_climate_analyzer.chart_presentation import ChartPresentationSettings,apply_chart_presentation

class CalendarHeatmapTests(unittest.TestCase):
    def test_full_year_december_labels_and_values(self):
        idx=pd.date_range("2026-01-01","2027-01-01",freq="h",inclusive="left")
        df=pd.DataFrame({"night_flushing_suitable":(idx.month==12).astype(float)},index=idx)
        fig=heatmap_chart(df,"night_flushing_suitable","day","Example","0/1")
        self.assertEqual(len(fig.data[0].x),365)
        self.assertEqual(list(fig.layout.xaxis.ticktext),["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
        np.testing.assert_allclose(np.asarray(fig.data[0].z)[:,-31:],1)
        copy=report_figure(fig,width_pt=500,height_pt=230)
        self.assertEqual(list(copy.layout.xaxis.ticktext)[-1],"Dec")
        self.assertEqual(len(copy.data[0].x),365)

    def test_clock_hour_axis_canonical_for_ventilation_and_other_heatmaps(self):
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        df=pd.DataFrame({
            "natural_ventilation_suitable":((idx.hour>=6)&(idx.hour<18)).astype(float),
            "night_flushing_suitable":((idx.hour>=22)|(idx.hour<7)).astype(float),
            "dry_bulb_temperature_c":np.linspace(0.,25.,len(idx)),
        },index=idx)
        ticks=[-.5,5.5,11.5,17.5,23.5]
        labels=["0","6","12","18","24"]
        for column in df:
            for period in ("day","week","month"):
                with self.subTest(column=column,period=period):
                    fig=temporal_heatmap_chart(df,column,period,HEATMAP_COMPARE_HOUR,"Mean",column,"0/1" if "suitable" in column else "°C")
                    expected=temporal_heatmap_matrix(df,column,period,HEATMAP_COMPARE_HOUR,"Mean")
                    for copy in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                        self.assertEqual(list(copy.layout.yaxis.tickvals),ticks)
                        self.assertEqual(list(copy.layout.yaxis.ticktext),labels)
                        self.assertEqual(list(copy.data[0].y),list(range(24)))
                        self.assertEqual(list(copy.layout.yaxis.range),[23.5,-.5])
                        np.testing.assert_allclose(np.asarray(copy.data[0].z,float),expected.values,equal_nan=True)
        legacy=go.Figure(go.Heatmap(x=["2026-01-01"],y=list(range(24)),z=np.arange(24).reshape(24,1)))
        legacy.update_layout(yaxis_title="Hour of day")
        printed=report_figure(legacy,width_pt=500,height_pt=230)
        self.assertEqual(list(printed.layout.yaxis.tickvals),ticks)
        utci=go.Figure(legacy);utci.update_layout(yaxis_title="Analysis clock hour")
        apply_calendar_heatmap_axes(utci)
        self.assertEqual(list(utci.layout.yaxis.tickvals),ticks)
        physical=go.Figure(go.Heatmap(x=[10,20],y=[0,6,12],z=np.zeros((3,2))))
        physical.update_layout(yaxis_title="Wind speed [m/s]")
        apply_calendar_heatmap_axes(physical)
        self.assertIsNone(physical.layout.yaxis.tickvals)

    def test_missing_days_not_zero_filled(self):
        idx=pd.date_range("2026-11-29","2026-12-03 23:00",freq="h")
        df=pd.DataFrame({"temperature":1.},index=idx)
        df.loc[df.index.day==30,"temperature"]=np.nan
        m=temporal_heatmap_matrix(df,"temperature","day",HEATMAP_COMPARE_HOUR,"Mean")
        self.assertIn("2026-11-30",m.columns)
        self.assertTrue(m["2026-11-30"].isna().all())
        self.assertIn("2026-12-03",m.columns)

    def test_numeric_calendar_and_noncalendar(self):
        fig=go.Figure(go.Heatmap(x=list(range(1,367)),y=[0],z=[list(range(366))]))
        fig.update_layout(xaxis_title="Day of year")
        apply_calendar_heatmap_axes(fig)
        self.assertEqual(list(fig.layout.xaxis.ticktext)[-1],"Dec")
        solar=go.Figure(go.Heatmap(x=list(range(0,361,30)),y=[0,45,90],z=np.zeros((3,13))))
        solar.update_layout(xaxis_title="Surface azimuth [deg]")
        apply_calendar_heatmap_axes(solar)
        self.assertIsNone(solar.layout.xaxis.ticktext)

    def test_monthly_bars_explicit_ticks_and_daily_axis_unchanged(self):
        from epw_climate_analyzer.calendar_heatmap_axes import apply_monthly_axes
        idx=pd.date_range("2026-01-01",periods=12,freq="MS")
        fig=go.Figure(go.Bar(x=idx,y=np.arange(12)))
        apply_monthly_axes(fig)
        self.assertEqual(list(fig.layout.xaxis.ticktext),list(idx.strftime("%b")))
        category=go.Figure(go.Bar(x=idx.strftime("%b %Y"),y=np.arange(12)))
        apply_monthly_axes(category)
        self.assertEqual(list(category.layout.xaxis.ticktext)[-1],"Dec")
        self.assertEqual(str(category.data[0].x[-1]),"Dec 2026")
        daily=go.Figure(go.Scatter(x=pd.date_range("2026-01-01",periods=30,freq="D"),y=np.arange(30)))
        apply_monthly_axes(daily)
        self.assertIsNone(daily.layout.xaxis.ticktext)

    def test_daylight_envelope_calendar_ticks(self):
        from epw_climate_analyzer.extended_visualization import daylight_envelope
        from epw_climate_analyzer.calendar_heatmap_axes import apply_monthly_axes
        for year,days in [(2024,366),(2026,365)]:
            idx=pd.date_range(f"{year}-01-01",f"{year}-12-31 23:00",freq="h")
            fig=daylight_envelope(idx,47.08)
            expected=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            self.assertEqual(list(fig.layout.xaxis.ticktext),expected)
            self.assertEqual(len(fig.data[0].x),days)
            self.assertEqual(pd.Timestamp(fig.data[0].x[-1]).date(),pd.Timestamp(f"{year}-12-31").date())
            copy=report_figure(fig,width_pt=500,height_pt=230)
            self.assertEqual(list(copy.layout.xaxis.ticktext),expected)
            legacy=go.Figure(fig)
            legacy.update_layout(meta=None,xaxis=dict(tickmode="auto",tickvals=None,ticktext=None))
            # Exercise a real pre-fix saved JSON snapshot directly through
            # the print path, without normalizing the input first.
            import plotly.io as pio
            restored=pio.from_json(pio.to_json(legacy))
            self.assertIsNone(restored.layout.meta)
            self.assertIsNone(restored.layout.xaxis.ticktext)
            printed=report_figure(restored,width_pt=500,height_pt=230)
            self.assertEqual(list(printed.layout.xaxis.ticktext),expected)
            self.assertEqual(printed.layout.xaxis.tickmode,"array")
            self.assertEqual(len(printed.data[0].x),days)
            self.assertEqual(pd.Timestamp(printed.data[0].x[-1]).date(),pd.Timestamp(f"{year}-12-31").date())
            np.testing.assert_array_equal(printed.data[0].y,restored.data[0].y)
            np.testing.assert_array_equal(printed.data[1].y,restored.data[1].y)
            self.assertIsNone(restored.layout.xaxis.ticktext)
            apply_monthly_axes(legacy)
            self.assertEqual(list(legacy.layout.xaxis.ticktext),expected)
        multi=daylight_envelope(pd.date_range("2025-11-01","2026-12-31",freq="D"),47.08)
        self.assertEqual(multi.layout.xaxis.ticktext[-1],"Dec 2026")
        self.assertTrue(all(len(v)>3 for v in multi.layout.xaxis.ticktext))

    def test_psychrometric_temperature_heatmaps_share_absolute_colour_domain(self):
        from epw_climate_analyzer.charts import TEMPERATURE_HEATMAP_COLUMNS,temporal_heatmap_chart
        idx=pd.date_range("2026-01-01",periods=48,freq="h")
        cols=("dry_bulb_temperature_c","wet_bulb_temperature_c","dew_point_temperature_c")
        df=pd.DataFrame({c:np.linspace(-5-i*3,30-i*3,48) for i,c in enumerate(cols)},index=idx)
        figs=[temporal_heatmap_chart(df,c,"day",HEATMAP_COMPARE_HOUR,"Mean",c,"°C",temperature_thresholds=(18,26)) for c in cols]
        from epw_climate_analyzer.chart_theme import metric_band_colors,metric_color
        self.assertEqual(figs[1].layout.coloraxis.colorscale,figs[0].layout.coloraxis.colorscale)
        self.assertEqual(metric_band_colors(cols[1])[1],metric_color(cols[1]))
        self.assertEqual(figs[2].layout.coloraxis.colorscale,figs[0].layout.coloraxis.colorscale)
        for f in figs[1:]:
            self.assertEqual(f.layout.coloraxis.cmin,figs[0].layout.coloraxis.cmin)
            self.assertEqual(f.layout.coloraxis.cmax,figs[0].layout.coloraxis.cmax)
        printed=report_figure(figs[1],width_pt=500,height_pt=230)
        self.assertEqual(printed.layout.coloraxis.colorscale,figs[1].layout.coloraxis.colorscale)
        for c,f in zip(cols,figs):
            expected=temporal_heatmap_matrix(df,c,"day",HEATMAP_COMPARE_HOUR,"Mean")
            np.testing.assert_allclose(np.asarray(f.data[0].z,float),expected.values,equal_nan=True)

    def test_day_hour_statistics_only_when_cells_pool_source_records(self):
        from epw_climate_analyzer.aggregations import heatmap_scope_statistics
        from epw_climate_analyzer.temporal_filtering import TIME_BASIS_ATTR,CALENDAR_PROFILE
        c="dry_bulb_temperature_c"
        frame=lambda idx:pd.DataFrame({c:np.arange(len(idx),dtype=float)},index=idx)
        hourly=frame(pd.date_range("2026-01-01",periods=48,freq="h"))
        self.assertEqual(heatmap_scope_statistics(hourly,c,"day",HEATMAP_COMPARE_HOUR),("Mean",))
        self.assertGreater(len(heatmap_scope_statistics(hourly,c,"month",HEATMAP_COMPARE_HOUR)),1)
        subhourly=frame(pd.date_range("2026-01-01",periods=48,freq="10min"))
        self.assertGreater(len(heatmap_scope_statistics(subhourly,c,"day",HEATMAP_COMPARE_HOUR)),1)
        multi=frame(pd.DatetimeIndex(["2025-01-01","2026-01-01"]))
        self.assertEqual(heatmap_scope_statistics(multi,c,"day",HEATMAP_COMPARE_HOUR),("Mean",))
        multi.attrs[TIME_BASIS_ATTR]=CALENDAR_PROFILE
        self.assertGreater(len(heatmap_scope_statistics(multi,c,"day",HEATMAP_COMPARE_HOUR)),1)

    def test_diurnal_panel_reflow_at_print_size_and_legacy(self):
        from epw_climate_analyzer.extended_visualization import diurnal_figure,diurnal_panel_rows
        idx=pd.MultiIndex.from_product([range(1,13),range(24)],names=["month","hour"])
        t=pd.DataFrame({k:np.full(len(idx),i) for i,k in enumerate(("mean","median","min","max","count","p05","p95"))},index=idx)
        f=diurnal_figure(t,"dry_bulb_temperature_c","°C",representation="Small multiples")
        self.assertEqual(diurnal_panel_rows(f),4)
        legacy=go.Figure(f);legacy.update_layout(meta=None)
        for chart in (f,legacy):
            printed=report_figure(chart,width_pt=730,height_pt=330)
            self.assertEqual(diurnal_panel_rows(printed),4)
            for i in range(1,13):
                suffix=str(i) if i>1 else ""
                axis=getattr(printed.layout,"xaxis"+suffix)
                self.assertEqual(axis.showticklabels,i>=10)
                self.assertEqual(axis.title.text,"Hour" if i==11 else "")
                ya=getattr(printed.layout,"yaxis"+suffix)
                self.assertEqual(ya.showticklabels,(i-1)%3==0)
                self.assertAlmostEqual(printed.layout.annotations[i-1].y,ya.domain[1])
                np.testing.assert_array_equal(printed.data[i-1].y,chart.data[i-1].y)

    def test_daily_profile_endpoint_and_weekly_source_year_scope(self):
        from epw_climate_analyzer.charts import profile_ribbon_chart,percentile_band_chart,profile_line_chart
        from epw_climate_analyzer.calendar_heatmap_axes import apply_monthly_axes,set_period_axis_scope
        from epw_climate_analyzer.temporal_filtering import CALENDAR_PROFILE,with_time_basis
        c="dry_bulb_temperature_c"
        for year,days in ((2025,365),(2024,366),(2026,365)):
            idx=pd.date_range(f"{year}-01-01",f"{year}-12-31 23:00",freq="h")
            df=pd.DataFrame({c:np.sin(np.arange(len(idx))/24)},index=idx)
            df["season"]="Winter"
            for chart in (profile_ribbon_chart,percentile_band_chart,profile_line_chart):
                daily=chart(df,c,"Daily","Temperature","°C")
                self.assertEqual(daily.layout.xaxis.ticktext[-1],str(days))
                self.assertEqual(daily.layout.xaxis.tickvals[-1],days)
                self.assertEqual(len(daily.data[0].x),days)
                printed=report_figure(daily,width_pt=500,height_pt=230)
                self.assertEqual(printed.layout.xaxis.ticktext[-1],str(days))
                weekly=chart(df,c,"Weekly","Temperature","°C")
                self.assertTrue(all(str(v).startswith("W") for v in weekly.layout.xaxis.ticktext))
                self.assertEqual(len(set(weekly.data[0].x)),len(weekly.data[0].x))
                self.assertEqual(list(weekly.layout.xaxis.tickvals)[-1],weekly.data[0].x[-1])
                self.assertEqual(weekly.layout.xaxis.tickangle,0)
            f=profile_line_chart(with_time_basis(df,CALENDAR_PROFILE),c,"Daily","Temperature","°C")
            self.assertEqual(f.layout.xaxis.ticktext[-1],str(days))
        partial=go.Figure(go.Scatter(x=list(range(101,151)),y=list(range(50))))
        partial.update_layout(xaxis_title="Period",title="Daily mean")
        apply_monthly_axes(partial)
        self.assertEqual(partial.layout.xaxis.ticktext[-1],"150")
        legacy=go.Figure(go.Scatter(x=["2026-W51","2026-W52","2026-W53","2027-W01"],y=[1,2,3,4]))
        legacy.update_layout(xaxis_title="Period")
        set_period_axis_scope(legacy,context={"first timestamp":"2026-01-01","last timestamp":"2026-12-31"})
        apply_monthly_axes(legacy)
        self.assertEqual(list(legacy.layout.xaxis.ticktext),["W51","W52","W53","W01"])
        multi=go.Figure(go.Bar(x=["2025-W52","2026-W01"],y=[1,2]))
        apply_monthly_axes(multi)
        self.assertEqual(list(multi.layout.xaxis.ticktext),["2025-W52","2026-W01"])
        physical=go.Figure(go.Scatter(x=list(range(1,366)),y=list(range(365))))
        physical.update_layout(xaxis_title="Sorted duration [h]")
        apply_monthly_axes(physical)
        self.assertIsNone(physical.layout.xaxis.ticktext)

    def test_relative_humidity_semantic_colour_and_fixed_domain(self):
        from epw_climate_analyzer.chart_theme import RELATIVE_HUMIDITY_COLORSCALE,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        c="relative_humidity_pct"
        self.assertEqual(metric_colorscale(c),RELATIVE_HUMIDITY_COLORSCALE)
        idx=pd.date_range("2026-01-01",periods=48,freq="h")
        df=pd.DataFrame({c:np.linspace(35,85,48)},index=idx)
        for period in ("day","week","month"):
            fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,"Mean","Relative humidity","%")
            self.assertEqual(fig.layout.coloraxis.cmin,0.)
            self.assertEqual(fig.layout.coloraxis.cmax,100.)
            self.assertEqual(tuple(tuple(v) for v in RELATIVE_HUMIDITY_COLORSCALE),fig.layout.coloraxis.colorscale)
            expected=temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,"Mean")
            np.testing.assert_allclose(np.asarray(fig.data[0].z,float),expected.values,equal_nan=True)
            printed=report_figure(fig,width_pt=500,height_pt=230)
            self.assertEqual(printed.layout.coloraxis.colorscale,fig.layout.coloraxis.colorscale)
            self.assertEqual(printed.layout.coloraxis.cmin,0.)
            self.assertEqual(printed.layout.coloraxis.cmax,100.)

    def test_humidity_ratio_colour_and_scope_domain(self):
        from epw_climate_analyzer.chart_theme import HUMIDITY_RATIO_COLORSCALE,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        c="humidity_ratio_g_kg"
        self.assertEqual(metric_colorscale(c),HUMIDITY_RATIO_COLORSCALE)
        idx=pd.date_range("2026-01-01",periods=48,freq="h")
        df=pd.DataFrame({c:np.linspace(2,17,48)},index=idx)
        df.iloc[4,0]=np.nan
        for period in ("day","week","month"):
            for stat in ("Mean","Minimum","Maximum","P95"):
                fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,stat,"Humidity ratio","g/kg dry air")
                expected=temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,stat)
                np.testing.assert_allclose(np.asarray(fig.data[0].z,float),expected.values,equal_nan=True)
                self.assertEqual(fig.layout.coloraxis.cmin,0.)
                self.assertEqual(fig.layout.coloraxis.cmax,20.)
                self.assertEqual(fig.layout.coloraxis.colorscale,tuple(tuple(v) for v in HUMIDITY_RATIO_COLORSCALE))
                printed=report_figure(fig,width_pt=500,height_pt=230)
                self.assertEqual(printed.layout.coloraxis.colorscale,fig.layout.coloraxis.colorscale)
                self.assertEqual(printed.layout.coloraxis.cmax,20.)
        for value,cap in ((0.,5.),(42.,45.)):
            frame=pd.DataFrame({c:value},index=idx)
            fig=temporal_heatmap_chart(frame,c,"day",HEATMAP_COMPARE_HOUR,"Mean","Humidity ratio","g/kg dry air")
            self.assertEqual(fig.layout.coloraxis.cmin,0.)
            self.assertEqual(fig.layout.coloraxis.cmax,cap)

    def test_enthalpy_semantic_palette_and_signed_scope_domain(self):
        from epw_climate_analyzer.chart_theme import MOIST_AIR_ENTHALPY_COLORSCALE,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        c="moist_air_enthalpy_kj_kg"
        self.assertEqual(metric_colorscale(c),MOIST_AIR_ENTHALPY_COLORSCALE)
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        df=pd.DataFrame({c:np.linspace(-13.,67.,len(idx))},index=idx)
        for period in ("day","week","month"):
            for stat in ("Mean","P95"):
                fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,stat,"Moist-air enthalpy","kJ/kg dry air")
                self.assertEqual(fig.layout.coloraxis.cmin,-20.)
                self.assertEqual(fig.layout.coloraxis.cmax,70.)
                self.assertEqual(fig.layout.coloraxis.colorscale,tuple(tuple(v) for v in MOIST_AIR_ENTHALPY_COLORSCALE))
                expected=temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,stat)
                np.testing.assert_allclose(np.asarray(fig.data[0].z,float),expected.values,equal_nan=True)
                printed=report_figure(fig,width_pt=500,height_pt=230)
                self.assertEqual(printed.layout.coloraxis.colorscale,fig.layout.coloraxis.colorscale)
        constant=pd.DataFrame({c:-10.},index=idx)
        fig=temporal_heatmap_chart(constant,c,"day",HEATMAP_COMPARE_HOUR,"Mean","Enthalpy","kJ/kg dry air")
        self.assertLess(fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax)

    def test_occurrence_temperature_edges_round_before_classification(self):
        from epw_climate_analyzer.extended_visualization import occurrence_default_edges,occurrence_table,occurrence_figure
        c="wet_bulb_temperature_c"
        source=pd.Series([2.77255,8.08763,14.6989])
        self.assertEqual(occurrence_default_edges(source,"dry_bulb_temperature_c"),[0.,15.,25.,30.])
        v=pd.Series([0.,2.77255,8.08763,14.6989,20.])
        edges=occurrence_default_edges(v,c)
        self.assertEqual(edges,[2.8,8.1,14.7])
        df=pd.DataFrame({c:[2.79,2.8,8.09,8.1,14.69,14.7,np.nan]},index=pd.date_range("2026-01-01",periods=7,freq="h"))
        table=occurrence_table(df,c,edges)
        self.assertEqual(list(table.columns),["< 2.8","2.8 – < 8.1","8.1 – < 14.7","≥ 14.7"])
        np.testing.assert_allclose(table.iloc[0],[1.,2.,2.,1.])
        self.assertEqual(float(table.sum().sum()),6.)
        fig=occurrence_figure(table,"°C","Hours")
        self.assertEqual(fig.data[0].name,"< 2.8 °C")
        constant=occurrence_default_edges(pd.Series([1.01,1.02,1.03]),c)
        self.assertEqual(constant,[1.])
        manual=occurrence_table(df,c,[2.791,2.799])
        self.assertEqual(list(manual.columns),["< 2.791","2.791 – < 2.799","≥ 2.799"])

    def test_precipitation_and_snow_zero_separate_positive_classes(self):
        from epw_climate_analyzer.extended_visualization import occurrence_default_edges,occurrence_table,occurrence_figure
        for c,unit,edges in (
            ("liquid_precipitation_depth_mm","mm",[.1,1.,5.,10.]),
            ("snow_depth_cm","cm",[1.,5.,10.,20.,50.]),
        ):
            data=[0.,0.,edges[0]/2,*edges,-1.,np.nan]
            df=pd.DataFrame({c:data},index=pd.date_range("2026-01-01",periods=len(data),freq="h"))
            self.assertEqual(occurrence_default_edges(pd.Series([0.,0.,0.]),c),edges)
            table=occurrence_table(df,c,edges)
            self.assertEqual(table.iloc[0,0],2.)
            np.testing.assert_allclose(table.iloc[0,1:],np.ones(len(edges)+1))
            self.assertEqual(table.sum().sum(),len(data)-2)
            percent=occurrence_table(df,c,edges,basis="Percentage")
            self.assertAlmostEqual(percent.sum().sum(),100.)
            fig=occurrence_figure(table,unit,"Hours")
            self.assertIn("= 0",fig.data[0].name)
            self.assertEqual(fig.data[0].marker.color,"#E5E7EB")
            zero=df.copy();zero[c]=0.
            tab=occurrence_table(zero,c,edges)
            self.assertEqual(tab.iloc[0,0],len(zero))
            self.assertEqual(tab.iloc[0,1:].sum(),0.)
            with self.assertRaises(ValueError):occurrence_table(df,c,[0.,1.])
        self.assertEqual(occurrence_default_edges(pd.Series([0.]),"liquid_precipitation_depth_mm",basis="Days",daily_stat="Total"),[1.,5.,10.,20.])

    def test_snow_depth_semantic_heatmap(self):
        from epw_climate_analyzer.chart_theme import SNOW_DEPTH_COLORSCALE,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        c="snow_depth_cm"
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        df=pd.DataFrame({c:np.linspace(0.,23.,len(idx))},index=idx)
        df.iloc[2,0]=np.nan
        self.assertEqual(metric_colorscale(c),SNOW_DEPTH_COLORSCALE)
        for period in ("day","week","month"):
            fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,"Mean","Snow depth","cm")
            for copy in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                self.assertEqual(copy.layout.coloraxis.cmin,0.)
                self.assertEqual(copy.layout.coloraxis.cmax,25.)
                self.assertEqual(copy.layout.coloraxis.colorscale,tuple(tuple(v) for v in SNOW_DEPTH_COLORSCALE))
                np.testing.assert_allclose(np.asarray(copy.data[0].z,float),temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,"Mean").values,equal_nan=True)
        df[c]=0.
        fig=temporal_heatmap_chart(df,c,"day",HEATMAP_COMPARE_HOUR,"Mean","Snow depth","cm")
        self.assertEqual((fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax),(0.,5.))

    def test_specific_volume_semantic_palette_and_scope_domain(self):
        from epw_climate_analyzer.chart_theme import SPECIFIC_VOLUME_COLORSCALE,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        c="specific_volume_m3_kg"
        self.assertEqual(metric_colorscale(c),SPECIFIC_VOLUME_COLORSCALE)
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        df=pd.DataFrame({c:np.linspace(.753,.927,len(idx))},index=idx)
        df.iloc[4,0]=np.nan
        for period in ("day","week","month"):
            for stat in ("Mean","P95"):
                fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,stat,"Specific volume","m³/kg dry air")
                self.assertAlmostEqual(fig.layout.coloraxis.cmin,.75)
                self.assertAlmostEqual(fig.layout.coloraxis.cmax,.93)
                self.assertEqual(fig.layout.coloraxis.colorscale,tuple(tuple(v) for v in SPECIFIC_VOLUME_COLORSCALE))
                expected=temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,stat)
                np.testing.assert_allclose(np.asarray(fig.data[0].z,float),expected.values,equal_nan=True)
                printed=report_figure(fig,width_pt=500,height_pt=230)
                self.assertEqual(printed.layout.coloraxis.colorscale,fig.layout.coloraxis.colorscale)
        constant=pd.DataFrame({c:.8},index=idx)
        fig=temporal_heatmap_chart(constant,c,"day",HEATMAP_COMPARE_HOUR,"Mean","Specific volume","m³/kg dry air")
        self.assertLess(fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax)

    def test_moist_air_density_semantic_palette_and_scope_domain(self):
        from epw_climate_analyzer.chart_theme import MOIST_AIR_DENSITY_COLORSCALE,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        c="moist_air_density_kg_m3"
        self.assertEqual(metric_colorscale(c),MOIST_AIR_DENSITY_COLORSCALE)
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        df=pd.DataFrame({c:np.linspace(1.073,1.287,len(idx))},index=idx)
        df.iloc[4,0]=np.nan
        for period in ("day","week","month"):
            for stat in ("Mean","P95"):
                fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,stat,"Moist-air density","kg/m³")
                self.assertAlmostEqual(fig.layout.coloraxis.cmin,1.07)
                self.assertAlmostEqual(fig.layout.coloraxis.cmax,1.29)
                self.assertEqual(fig.layout.coloraxis.colorscale,tuple(tuple(v) for v in MOIST_AIR_DENSITY_COLORSCALE))
                expected=temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,stat)
                np.testing.assert_allclose(np.asarray(fig.data[0].z,float),expected.values,equal_nan=True)
                printed=report_figure(fig,width_pt=500,height_pt=230)
                self.assertEqual(printed.layout.coloraxis.colorscale,fig.layout.coloraxis.colorscale)
        constant=pd.DataFrame({c:1.2},index=idx)
        fig=temporal_heatmap_chart(constant,c,"day",HEATMAP_COMPARE_HOUR,"Mean","Moist-air density","kg/m³")
        self.assertLess(fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax)

    def test_station_pressure_semantic_palette_and_scope_domain(self):
        from epw_climate_analyzer.chart_theme import STATION_PRESSURE_COLORSCALE,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        c="atmospheric_station_pressure_pa"
        self.assertEqual(metric_colorscale(c),STATION_PRESSURE_COLORSCALE)
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        for lower,upper in ((97323.,100487.),(73123.,75987.)):
            df=pd.DataFrame({c:np.linspace(lower,upper,len(idx))},index=idx)
            df.iloc[4,0]=np.nan
            for period in ("day","week","month"):
                for stat in ("Mean","P95"):
                    fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,stat,"Station pressure","Pa")
                    self.assertAlmostEqual(fig.layout.coloraxis.cmin,np.floor(lower/100.)*100.)
                    self.assertAlmostEqual(fig.layout.coloraxis.cmax,np.ceil(upper/100.)*100.)
                    self.assertEqual(fig.layout.coloraxis.colorscale,tuple(tuple(v) for v in STATION_PRESSURE_COLORSCALE))
                    expected=temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,stat)
                    np.testing.assert_allclose(np.asarray(fig.data[0].z,float),expected.values,equal_nan=True)
                    printed=report_figure(fig,width_pt=500,height_pt=230)
                    self.assertEqual(printed.layout.coloraxis.colorscale,fig.layout.coloraxis.colorscale)
        constant=pd.DataFrame({c:99000.},index=idx)
        fig=temporal_heatmap_chart(constant,c,"day",HEATMAP_COMPARE_HOUR,"Mean","Station pressure","Pa")
        self.assertLess(fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax)

    def test_distinct_air_property_palettes_across_chart_families(self):
        from epw_climate_analyzer.chart_theme import (
            metric_color, metric_band_colors, metric_colorscale, semantic_color_from_text,
        )
        from epw_climate_analyzer.charts import (
            profile_line_chart, profile_ribbon_chart, percentile_band_chart,
            duration_chart, histogram_chart, monthly_box_chart, temporal_heatmap_chart,
        )
        properties = (
            ("specific_volume_m3_kg", "Specific volume", "m³/kg dry air", "#547C9A", .8),
            ("moist_air_density_kg_m3", "Moist-air density", "kg/m³", "#475569", 1.2),
            ("atmospheric_station_pressure_pa", "Station pressure", "Pa", "#92734D", 98000.),
        )
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        palettes=[]
        for column,title,unit,base,level in properties:
            with self.subTest(column=column):
                df=pd.DataFrame({column:np.linspace(level*.98,level*1.02,len(idx))},index=idx)
                self.assertEqual(metric_color(column),base)
                self.assertEqual(metric_band_colors(column)[1],base)
                self.assertEqual(semantic_color_from_text(title),base)
                self.assertEqual(semantic_color_from_text(column),base)
                palette=metric_colorscale(column)
                self.assertEqual(palette[3][1],base)
                palettes.append(tuple(tuple(v) for v in palette))
                fig=profile_line_chart(df,column,"Hourly",title,unit)
                self.assertEqual(fig.data[0].line.color,base)
                self.assertEqual(duration_chart(df,column,title,unit).data[0].line.color,base)
                self.assertEqual(histogram_chart(df,column,title,unit).data[0].marker.color,base)
                for builder in (profile_ribbon_chart,percentile_band_chart):
                    fig=builder(df,column,"Daily",title,unit)
                    self.assertIn(base,[trace.line.color for trace in fig.data])
                for violin in (False,True):
                    fig=monthly_box_chart(df,column,title,unit,violin=violin)
                    self.assertTrue(all(trace.line.color==base for trace in fig.data))
                fig=temporal_heatmap_chart(df,column,"day",HEATMAP_COMPARE_HOUR,"Mean",title,unit)
                self.assertEqual(fig.layout.coloraxis.colorscale,palettes[-1])
                printed=report_figure(fig,width_pt=500,height_pt=230)
                self.assertEqual(printed.layout.coloraxis.colorscale,palettes[-1])
        self.assertEqual(len(set(palettes)),3)

    def test_multiyear_utci_not_truncated(self):
        idx=pd.date_range("2025-12-31","2026-12-31",freq="h")
        df=pd.DataFrame(index=idx)
        grid=annual_hour_grid(df,np.ones(len(idx)))
        self.assertEqual(str(grid.columns[-1].date()),"2026-12-31")
        self.assertEqual(grid.iloc[0,-1],1.)

if __name__=="__main__":unittest.main()
