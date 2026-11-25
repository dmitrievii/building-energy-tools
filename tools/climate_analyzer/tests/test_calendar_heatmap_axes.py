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
    @staticmethod
    def _calendar_rows(fig):
        rows=[str(v).split("<br>") for v in fig.layout.xaxis.ticktext]
        assert all(len(v)==2 for v in rows),rows
        return tuple([v[i] for v in rows if v[i]!="&nbsp;"] for i in (0,1))

    def test_r29_daily_leap_partial_multiyear_and_legacy(self):
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        for start,end,first,last,expected_months in (
            ("2024-01-01","2024-12-31",1,366,["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]),
            ("2025-02-27","2025-03-03",58,62,["Feb","Mar"]),
            ("2025-12-28","2026-01-05",362,5,["Dec 2025","Jan 2026"]),
        ):
            with self.subTest(start=start,end=end):
                idx=pd.date_range(start,pd.Timestamp(end)+pd.Timedelta(hours=23),freq="h")
                df=pd.DataFrame({"temperature":np.arange(len(idx),dtype=float)},index=idx)
                fig=temporal_heatmap_chart(df,"temperature","day",HEATMAP_COMPARE_HOUR,"Mean","Example","°C")
                a,b=self._calendar_rows(fig)
                self.assertEqual((a[0],a[-1]),(str(first),str(last)))
                self.assertEqual(b,expected_months)
                matrix=temporal_heatmap_matrix(df,"temperature","day",HEATMAP_COMPARE_HOUR,"Mean")
                np.testing.assert_array_equal(fig.data[0].z,matrix.values)
                old=go.Figure(fig)
                old.update_layout(meta=None,xaxis=dict(title="Date",ticktext=None,tickvals=None,tickmode="auto"))
                printed=report_figure(old,width_pt=500,height_pt=230)
                self.assertEqual(self._calendar_rows(printed)[0][-1],str(last))
                self.assertEqual(self._calendar_rows(printed)[1][-1],expected_months[-1])
                np.testing.assert_array_equal(printed.data[0].z,fig.data[0].z)
                np.testing.assert_array_equal(printed.data[0].x,fig.data[0].x)
                original=fig.to_plotly_json()["layout"]["xaxis"]
                apply_calendar_heatmap_axes(fig)
                self.assertEqual(fig.to_plotly_json()["layout"]["xaxis"],original)

    def test_r29_week_coordinates_iso_year_and_month_intersections(self):
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        idx=pd.date_range("2020-12-21","2021-01-10 23:00",freq="h")
        df=pd.DataFrame({"temperature":np.arange(len(idx),dtype=float)},index=idx)
        fig=temporal_heatmap_chart(df,"temperature","week",HEATMAP_COMPARE_HOUR,"Mean","Example","°C")
        self.assertEqual(list(fig.data[0].x),["2020-W52","2020-W53","2021-W01"])
        self.assertEqual(self._calendar_rows(fig),(["W52","W53","W01"],["Dec 2020","Jan 2021"]))
        month_ticks={t.split("<br>")[1]:v for v,t in zip(fig.layout.xaxis.tickvals,fig.layout.xaxis.ticktext)}
        # W53 begins Dec 28; Jan begins 4/7 of the way through that cell.
        self.assertAlmostEqual(month_ticks["Dec 2020"],(-.5+(.5+4/7))/2)
        self.assertAlmostEqual(month_ticks["Jan 2021"],((.5+4/7)+2.5)/2)
        matrix=temporal_heatmap_matrix(df,"temperature","week",HEATMAP_COMPARE_HOUR,"Mean")
        np.testing.assert_array_equal(fig.data[0].z,matrix.values)
        printed=report_figure(fig,width_pt=500,height_pt=230)
        self.assertEqual(self._calendar_rows(printed),self._calendar_rows(fig))
        self.assertEqual(list(printed.data[0].x),list(fig.data[0].x))
        apply_calendar_heatmap_axes(fig)
        self.assertEqual(self._calendar_rows(fig),self._calendar_rows(printed))

    def test_r29_calendar_profile_and_monthly_unchanged(self):
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        from epw_climate_analyzer.temporal_filtering import with_time_basis,CALENDAR_PROFILE
        idx=pd.date_range("2024-01-01","2025-12-31 23:00",freq="h")
        df=with_time_basis(pd.DataFrame({"temperature":np.arange(len(idx),dtype=float)},index=idx),CALENDAR_PROFILE)
        for period,last in (("day","366"),("week","W52")):
            fig=temporal_heatmap_chart(df,"temperature",period,HEATMAP_COMPARE_HOUR,"Mean","Example","°C")
            self.assertEqual(self._calendar_rows(fig)[1][-1],"Dec")
            self.assertEqual(self._calendar_rows(fig)[0][-1],last)
            self.assertIn("reference" if period=="day" else "guide",fig.layout.xaxis.title.text)
            np.testing.assert_array_equal(fig.data[0].z,temporal_heatmap_matrix(df,"temperature",period,HEATMAP_COMPARE_HOUR,"Mean").values)
        monthly=temporal_heatmap_chart(df,"temperature","month",HEATMAP_COMPARE_HOUR,"Mean","Example","°C")
        self.assertEqual(list(monthly.layout.xaxis.ticktext),["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])

    def test_r29_single_year_week_guide_excludes_adjacent_unselected_years(self):
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        idx=pd.date_range("2026-01-01","2026-12-31 23:00",freq="h")
        df=pd.DataFrame({"temperature":np.arange(len(idx),dtype=float)},index=idx)
        fig=temporal_heatmap_chart(df,"temperature","week",HEATMAP_COMPARE_HOUR,"Mean","Example","°C")
        self.assertEqual(self._calendar_rows(fig)[1],["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
        self.assertEqual(self._calendar_rows(fig)[0][0],"W01")
        self.assertEqual(self._calendar_rows(fig)[0][-1],"W53")
        self.assertEqual(len(fig.data[0].x),53)

    def test_r29_pinned_plotly_static_svg_retains_two_visible_tick_rows(self):
        # Exercise the actual Kaleido/Plotly print renderer, not only Python
        # layout validation: categorical ISO week tickvals include fractions.
        import xml.etree.ElementTree as ET
        from epw_climate_analyzer.calendar_heatmap_axes import set_period_axis_scope
        x=["2020-W52","2020-W53","2021-W01"]
        fig=go.Figure(go.Heatmap(x=x,y=list(range(24)),z=np.zeros((24,3))))
        fig.update_layout(xaxis_title="Week",yaxis_title="Hour of day")
        set_period_axis_scope(fig,pd.date_range("2020-12-21","2021-01-10",freq="D"))
        apply_calendar_heatmap_axes(fig)
        printed=report_figure(fig,width_pt=500,height_pt=230)
        root=ET.fromstring(printed.to_image(format="svg"))
        ns={"s":"http://www.w3.org/2000/svg"}
        texts=[]
        for group in root.findall(".//s:g",ns):
            if group.attrib.get("class")=="xtick":
                texts.extend(t.text for t in group.findall(".//s:tspan",ns) if t.text and t.text.strip())
        for label in ("W52","W53","W01","Dec 2020","Jan 2021"):
            self.assertIn(label,texts)

    def test_r29_dew_point_occurrence_uses_fixed_classes_and_all_month_labels(self):
        from epw_climate_analyzer.extended_visualization import (
            occurrence_default_edges,occurrence_table,occurrence_figure,
            DEW_POINT_OCCURRENCE_EDGES,DEW_POINT_OCCURRENCE_COLORS)
        from epw_climate_analyzer.calendar_heatmap_axes import apply_monthly_axes
        from epw_climate_analyzer.humidity_findings import humidity_figure_interpretation
        col="dew_point_temperature_c"
        idx=pd.date_range("2026-01-01","2026-12-31 23:00",freq="h")
        df=pd.DataFrame({col:np.resize([-2.,0.,5.,10.,15.,20.,25.],len(idx))},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        for basis,stat in (("Hours","Mean"),("Percentage","Mean"),("Days","Mean"),("Days","Minimum"),("Days","Maximum")):
            with self.subTest(basis=basis,stat=stat):
                edges=occurrence_default_edges(df[col],col,basis=basis,daily_stat=stat)
                self.assertEqual(tuple(edges),DEW_POINT_OCCURRENCE_EDGES)
                self.assertEqual(occurrence_default_edges(df[col]+30,col,basis=basis,daily_stat=stat),edges)
                table=occurrence_table(df,col,edges,basis=basis,daily_stat=stat)
                self.assertEqual(len(table.columns),7)
                if basis=="Days":
                    np.testing.assert_array_equal(table.sum(axis=1),pd.date_range("2026-01-01",periods=12,freq="MS").days_in_month)
                elif basis=="Hours":
                    self.assertAlmostEqual(float(table.to_numpy().sum()),8760.)
                else:
                    np.testing.assert_allclose(table.sum(axis=1),100.)
                fig=occurrence_figure(table,"°C",basis)
                fig.update_layout(title=f"Dew-point temperature · occurrence · {basis} · daily {stat}")
                expected=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                for plot in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                    apply_monthly_axes(plot)
                    self.assertEqual(list(plot.layout.xaxis.ticktext),expected)
                    self.assertEqual(tuple(tr.marker.color for tr in plot.data),DEW_POINT_OCCURRENCE_COLORS)
                    np.testing.assert_array_equal(plot.data[-1].y,table.iloc[:,-1].to_numpy())
                legacy=go.Figure(fig);legacy.update_layout(meta=None,xaxis=dict(title="Period",tickvals=None,ticktext=None))
                self.assertEqual(list(report_figure(legacy,width_pt=500,height_pt=230).layout.xaxis.ticktext),expected)
                note=humidity_figure_interpretation(df,fig,"occurrence",column=col,args=(basis,stat))
                self.assertIn("Fixed outdoor moisture-reference boundaries",note)
                if basis=="Days":self.assertIn({"Mean":"typical dew-point level","Minimum":"persistent moisture exposure","Maximum":"peak moisture exposure"}[stat],note)

    def test_r29b_hourly_daily_monthly_seasonal_and_physical_axes(self):
        from epw_climate_analyzer.calendar_heatmap_axes import apply_monthly_axes,set_period_axis_scope
        def check(x,aggregation,first,last,guide_first,guide_last):
            f=go.Figure(go.Scatter(x=x,y=np.arange(len(x),dtype=float),mode="lines"))
            f.update_layout(xaxis_title="Time" if aggregation=="Hourly" else "Period")
            if aggregation:set_period_axis_scope(f,aggregation=aggregation)
            apply_monthly_axes(f)
            a,b=self._calendar_rows(f)
            self.assertEqual((a[0],a[-1]),(first,last))
            self.assertEqual((b[0],b[-1]),(guide_first,guide_last))
            for clone in (report_figure(f,width_pt=500,height_pt=230),go.Figure(f)):
                apply_monthly_axes(clone)
                self.assertEqual(self._calendar_rows(clone)[0][-1],last)
                self.assertEqual(self._calendar_rows(clone)[1][-1],guide_last)
                np.testing.assert_array_equal(clone.data[0].x,f.data[0].x)
                np.testing.assert_array_equal(clone.data[0].y,f.data[0].y)
            return f
        check(pd.date_range("2026-05-31 18:00",periods=18,freq="h"),"Hourly","18:00","11:00","31 May","01 Jun")
        check(pd.date_range("2026-01-01","2026-12-31 23:00",freq="h"),"Hourly","1","365","Jan","Dec")
        check(["28 Dec 2025","29 Dec 2025","01 Jan 2026","02 Jan 2026"],"Daily","362","2","Dec 2025","Jan 2026")
        check(["Nov 2025","Dec 2025","Jan 2026","Feb 2026"],"Monthly","Nov","Feb","2025","2026")
        check(["Autumn 2025","Winter 2026","Spring 2026"],"Seasonal","Autumn","Spring","2025","2026")
        for title in ("Sorted duration [h]","Temperature [°C]","Wind speed [m/s]","Empirical return period [years]"):
            f=go.Figure(go.Scatter(x=list(range(1,366)),y=list(range(365))))
            f.update_layout(xaxis_title=title)
            before=f.to_plotly_json()["layout"]["xaxis"]
            apply_monthly_axes(f)
            self.assertEqual(f.to_plotly_json()["layout"]["xaxis"],before)
        annual=go.Figure(go.Bar(x=["2024","2025","2026"],y=[1,2,3]))
        set_period_axis_scope(annual,aggregation="Annual")
        apply_monthly_axes(annual)
        self.assertIsNone(annual.layout.xaxis.ticktext)

    def test_r29b_interannual_preserves_reference_geometry(self):
        from epw_climate_analyzer.interannual_profiles import interannual_profile_figure
        from epw_climate_analyzer.temporal_filtering import with_time_basis,INTERANNUAL_OVERLAY
        idx=pd.date_range("2024-01-01","2025-12-31 23:00",freq="h")
        df=with_time_basis(pd.DataFrame({"dry_bulb_temperature_c":np.sin(np.arange(len(idx))/24)},index=idx),INTERANNUAL_OVERLAY)
        for period in ("Daily","Weekly","Hourly"):
            f=interannual_profile_figure(df,"dry_bulb_temperature_c",period,"Temperature","°C",kind="minmax")
            self.assertEqual(self._calendar_rows(f)[1][-1],"Dec")
            if period=="Weekly":
                self.assertIn("7-day reference bins",f.layout.xaxis.title.text)
            else:self.assertIn("leap-year reference",f.layout.xaxis.title.text)
            printed=report_figure(f,width_pt=500,height_pt=230)
            for a,b in zip(f.data,printed.data):
                np.testing.assert_array_equal(a.x,b.x)
                np.testing.assert_array_equal(a.y,b.y)

    def test_temperature_threshold_widgets_are_scoped_to_consuming_charts(self):
        import ast
        from pathlib import Path
        tree=ast.parse((Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8"))
        funcs={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        def guards(node, ancestors=()):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=="slider" and node.args and isinstance(node.args[0],ast.Constant):
                yield node.args[0].value,ancestors
            if isinstance(node,ast.IfExp):
                yield from guards(node.body,ancestors+(ast.unparse(node.test),))
                yield from guards(node.orelse,ancestors)
            elif isinstance(node,ast.If):
                condition=ast.unparse(node.test)
                for child in node.body:yield from guards(child,ancestors+(condition,))
                for child in node.orelse:yield from guards(child,ancestors)
            else:
                for child in ast.iter_child_nodes(node):yield from guards(child,ancestors)
        explorer=dict(guards(funcs["render_generic_variable_page"]))
        for label in ("Lower colour reference [°C]","Upper colour reference [°C]"):
            self.assertIn("chart_type == 'Heat map'",explorer[label])
            self.assertIn("column in TEMPERATURE_HEATMAP_COLUMNS",explorer[label])
        panel_tree=ast.parse((Path(__file__).resolve().parents[1]/"epw_climate_analyzer/p3_ui.py").read_text(encoding="utf-8"))
        panel=next(n for n in panel_tree.body if isinstance(n,ast.FunctionDef) and n.name=="temperature_threshold_panel")
        temperature=dict(guards(panel))
        self.assertIn("mode in ('Below heating threshold', 'Heating and cooling thresholds')",temperature["Heating threshold [°C]"])
        self.assertIn("mode in ('Above cooling threshold', 'Heating and cooling thresholds')",temperature["Cooling threshold [°C]"])
        self.assertIn("temperature_threshold_panel",ast.unparse(funcs["render_temperature"]))
        self.assertNotIn("Heating threshold [°C]",explorer)
        self.assertNotIn("Cooling threshold [°C]",explorer)

    def test_full_year_december_labels_and_values(self):
        idx=pd.date_range("2026-01-01","2027-01-01",freq="h",inclusive="left")
        df=pd.DataFrame({"night_flushing_suitable":(idx.month==12).astype(float)},index=idx)
        fig=heatmap_chart(df,"night_flushing_suitable","day","Example","0/1")
        self.assertEqual(len(fig.data[0].x),365)
        self.assertEqual(self._calendar_rows(fig)[1],["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
        self.assertEqual(self._calendar_rows(fig)[0][0],"1")
        self.assertEqual(self._calendar_rows(fig)[0][-1],"365")
        np.testing.assert_allclose(np.asarray(fig.data[0].z)[:,-31:],1)
        copy=report_figure(fig,width_pt=500,height_pt=230)
        self.assertEqual(self._calendar_rows(copy)[1][-1],"Dec")
        self.assertEqual(self._calendar_rows(copy)[0][-1],"365")
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
        self.assertEqual(self._calendar_rows(fig)[1][-1],"Dec")
        self.assertEqual(self._calendar_rows(fig)[0][-1],"366")
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
        self.assertEqual(self._calendar_rows(daily)[0][-1],"30")
        self.assertEqual(self._calendar_rows(daily)[1],["Jan"])

    def test_daylight_envelope_calendar_ticks(self):
        from epw_climate_analyzer.extended_visualization import daylight_envelope
        from epw_climate_analyzer.calendar_heatmap_axes import apply_monthly_axes
        for year,days in [(2024,366),(2026,365)]:
            idx=pd.date_range(f"{year}-01-01",f"{year}-12-31 23:00",freq="h")
            fig=daylight_envelope(idx,47.08)
            expected=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            self.assertEqual(self._calendar_rows(fig)[1],expected)
            self.assertEqual(self._calendar_rows(fig)[0][-1],str(days))
            self.assertEqual(len(fig.data[0].x),days)
            self.assertEqual(pd.Timestamp(fig.data[0].x[-1]).date(),pd.Timestamp(f"{year}-12-31").date())
            copy=report_figure(fig,width_pt=500,height_pt=230)
            self.assertEqual(self._calendar_rows(copy)[1],expected)
            legacy=go.Figure(fig)
            legacy.update_layout(meta=None,xaxis=dict(tickmode="auto",tickvals=None,ticktext=None))
            # Exercise a real pre-fix saved JSON snapshot directly through
            # the print path, without normalizing the input first.
            import plotly.io as pio
            restored=pio.from_json(pio.to_json(legacy))
            self.assertIsNone(restored.layout.meta)
            self.assertIsNone(restored.layout.xaxis.ticktext)
            printed=report_figure(restored,width_pt=500,height_pt=230)
            self.assertEqual(self._calendar_rows(printed)[1],expected)
            self.assertEqual(printed.layout.xaxis.tickmode,"array")
            self.assertEqual(len(printed.data[0].x),days)
            self.assertEqual(pd.Timestamp(printed.data[0].x[-1]).date(),pd.Timestamp(f"{year}-12-31").date())
            np.testing.assert_array_equal(printed.data[0].y,restored.data[0].y)
            np.testing.assert_array_equal(printed.data[1].y,restored.data[1].y)
            self.assertIsNone(restored.layout.xaxis.ticktext)
            apply_monthly_axes(legacy)
            self.assertEqual(self._calendar_rows(legacy)[1],expected)
        multi=daylight_envelope(pd.date_range("2025-11-01","2026-12-31",freq="D"),47.08)
        self.assertEqual(self._calendar_rows(multi)[1][-1],"Dec 2026")
        self.assertTrue(all(len(v)>3 for v in self._calendar_rows(multi)[1]))

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
        from epw_climate_analyzer.chart_theme import temperature_gradient_domain
        lo,hi,scale=temperature_gradient_domain()
        self.assertEqual((lo,hi),(-15.,32.))
        self.assertEqual(figs[0].layout.coloraxis.colorscale,tuple(tuple(v) for v in scale))
        self.assertEqual((figs[0].layout.coloraxis.cmin,figs[0].layout.coloraxis.cmax),(lo,hi))
        self.assertTrue(all(b[0]>a[0] for a,b in zip(scale,scale[1:])))
        self.assertEqual(scale[4][1],"#BCD1F9")
        self.assertEqual(scale[5][1],"#5CC56B")
        for c in cols:
            auto=temporal_heatmap_chart(df,c,"month",HEATMAP_COMPARE_HOUR,"Mean",c,"°C")
            self.assertEqual(auto.layout.coloraxis.colorscale,figs[0].layout.coloraxis.colorscale)
        extreme=df.copy();extreme.loc[extreme.index[0],cols[2]]=-38.;extreme.loc[extreme.index[-1],cols[0]]=48.
        for c in cols:
            f=temporal_heatmap_chart(extreme,c,"day",HEATMAP_COMPARE_HOUR,"Mean",c,"°C")
            self.assertEqual((f.layout.coloraxis.cmin,f.layout.coloraxis.cmax),(-38.,48.))
        printed=report_figure(figs[1],width_pt=500,height_pt=230)
        self.assertEqual(printed.layout.coloraxis.colorscale,figs[1].layout.coloraxis.colorscale)
        self.assertEqual(printed.layout.coloraxis.colorbar.tickvals,figs[1].layout.coloraxis.colorbar.tickvals)
        self.assertEqual(printed.layout.coloraxis.colorbar.ticktext,figs[1].layout.coloraxis.colorbar.ticktext)
        self.assertEqual(printed.layout.coloraxis.colorbar.tickformat,".0f")
        for c,f in zip(cols,figs):
            expected=temporal_heatmap_matrix(df,c,"day",HEATMAP_COMPARE_HOUR,"Mean")
            np.testing.assert_allclose(np.asarray(f.data[0].z,float),expected.values,equal_nan=True)

    def test_absolute_temperature_family_and_ground_share_canonical_coloraxis(self):
        from epw_climate_analyzer.chart_theme import TEMPERATURE_HEATMAP_COLUMNS,temperature_coloraxis,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        from epw_climate_analyzer.comparison import ClimateDataset,heatmap_small_multiples
        from epw_climate_analyzer.extended_visualization import ground_depth_heatmap
        columns=("dry_bulb_temperature_c","dry_bulb_temperature_min_c","dry_bulb_temperature_max_c",
                 "dew_point_temperature_c","wet_bulb_temperature_c","ground_temperature_0_10m_c",
                 "ground_temperature_0_20m_c","ground_temperature_0_50m_c")
        self.assertEqual(set(columns),TEMPERATURE_HEATMAP_COLUMNS)
        idx=pd.date_range("2026-01-01",periods=48,freq="h")
        df=pd.DataFrame({c:np.linspace(-5+i,20+i,48) for i,c in enumerate(columns)},index=idx)
        df.loc[idx[0],columns[1]]=-38.
        df.loc[idx[-1],columns[2]]=48.
        df["hour_of_day"]=idx.hour
        df["month"]=idx.month
        df["day_of_year"]=idx.dayofyear
        expected=temperature_coloraxis(frames=(df,),thresholds=(18.,26.))
        def check(fig):
            axis=fig.layout.coloraxis
            self.assertEqual((axis.cmin,axis.cmax),(-38.,48.))
            self.assertEqual(axis.colorscale,tuple(tuple(v) for v in expected["colorscale"]))
            self.assertEqual(axis.colorbar.title.text,"°C")
            self.assertEqual(axis.colorbar.tickvals,tuple(expected["colorbar"]["tickvals"]))
            self.assertEqual(axis.colorbar.ticktext,tuple(str(int(t)) for t in axis.colorbar.tickvals))
            self.assertEqual(axis.colorbar.tickformat,".0f")
            self.assertFalse(axis.cauto)
        for column in columns:
            for period in ("day","month"):
                check(temporal_heatmap_chart(df,column,period,HEATMAP_COMPARE_HOUR,"Mean",column,"°C"))
            self.assertEqual(metric_colorscale(column),metric_colorscale(columns[0]))
        climates=[ClimateDataset("x","Example","fixture",None,df,[])]
        check(heatmap_small_multiples(climates,columns[1],"day","Temperature","°C"))
        check(ground_depth_heatmap(pd.DataFrame({"Jan":[5.,10.],"Feb":[8.,11.]},index=[0.,1.]),source_frames=(df,)))
        self.assertNotIn("temperature_amplitude_k",TEMPERATURE_HEATMAP_COLUMNS)
        equal=temperature_coloraxis(thresholds=(20.,20.))
        self.assertTrue(all(b[0]>a[0] for a,b in zip(equal["colorscale"],equal["colorscale"][1:])))
        # Extending the axis keeps all existing physical colour anchors unchanged.
        base=temperature_coloraxis()
        for position,color in base["colorscale"]:
            temperature=base["cmin"]+position*(base["cmax"]-base["cmin"])
            target=(temperature-expected["cmin"])/(expected["cmax"]-expected["cmin"])
            self.assertTrue(any(abs(pos-target)<1e-10 and clr==color for pos,clr in expected["colorscale"]))

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
                self.assertEqual(self._calendar_rows(daily)[0][-1],str(days))
                self.assertEqual(self._calendar_rows(daily)[1][-1],"Dec")
                self.assertEqual(daily.layout.xaxis.tickvals[-1],days)
                self.assertEqual(len(daily.data[0].x),days)
                printed=report_figure(daily,width_pt=500,height_pt=230)
                self.assertEqual(self._calendar_rows(printed)[0][-1],str(days))
                weekly=chart(df,c,"Weekly","Temperature","°C")
                self.assertTrue(all(str(v).startswith("W") for v in self._calendar_rows(weekly)[0]))
                self.assertEqual(len(set(weekly.data[0].x)),len(weekly.data[0].x))
                self.assertEqual(self._calendar_rows(weekly)[0][-1],str(weekly.data[0].x[-1])[-3:])
                self.assertEqual(weekly.layout.xaxis.tickangle,0)
            f=profile_line_chart(with_time_basis(df,CALENDAR_PROFILE),c,"Daily","Temperature","°C")
            self.assertEqual(self._calendar_rows(f)[0][-1],"366")
            self.assertEqual(self._calendar_rows(f)[1][-1],"Dec")
        partial=go.Figure(go.Scatter(x=list(range(101,151)),y=list(range(50))))
        partial.update_layout(xaxis_title="Period",title="Daily mean")
        apply_monthly_axes(partial)
        self.assertEqual(self._calendar_rows(partial)[0][-1],"150")
        legacy=go.Figure(go.Scatter(x=["2026-W51","2026-W52","2026-W53","2027-W01"],y=[1,2,3,4]))
        legacy.update_layout(xaxis_title="Period")
        set_period_axis_scope(legacy,context={"first timestamp":"2026-01-01","last timestamp":"2026-12-31"})
        apply_monthly_axes(legacy)
        self.assertEqual(self._calendar_rows(legacy)[0],["W51","W52","W53","W01"])
        multi=go.Figure(go.Bar(x=["2025-W52","2026-W01"],y=[1,2]))
        apply_monthly_axes(multi)
        self.assertEqual(self._calendar_rows(multi)[0],["W52","W01"])
        self.assertEqual(self._calendar_rows(multi)[1],["Dec 2025","Jan 2026"])
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

    def test_illuminance_occurrence_fixed_classes_and_zero(self):
        from epw_climate_analyzer.extended_visualization import occurrence_default_edges,occurrence_table,occurrence_figure,ILLUMINANCE_OCCURRENCE_COLUMNS
        edges=[100.,1000.,5000.,10000.,25000.,50000.,100000.]
        for c in ILLUMINANCE_OCCURRENCE_COLUMNS:
            vals=[0.,0.,1.,*edges,-1.,np.nan]
            df=pd.DataFrame({c:vals},index=pd.date_range("2026-01-01",periods=len(vals),freq="h"))
            self.assertEqual(occurrence_default_edges(pd.Series([0.,0.,0.]),c),edges)
            table=occurrence_table(df,c,edges)
            self.assertEqual(len(table.columns),9)
            self.assertEqual(table.iloc[0,0],2.)
            np.testing.assert_allclose(table.iloc[0,1:],np.ones(8))
            self.assertEqual(table.sum().sum(),len(vals)-2)
            self.assertAlmostEqual(occurrence_table(df,c,edges,basis="Percentage").sum().sum(),100.)
            fig=occurrence_figure(table,"lx","Hours")
            self.assertEqual(fig.data[0].name,"No recorded illumination (= 0) lx")
            self.assertEqual(fig.data[0].marker.color,"#E5E7EB")
            self.assertEqual(len({x.marker.color for x in fig.data}),9)
            with self.assertRaises(ValueError):occurrence_table(df,c,[0.,100.])
            daily=pd.DataFrame({c:np.repeat([0.,1000.,10000.,-1.],24)},index=pd.date_range("2026-01-01",periods=96,freq="h"))
            d=occurrence_table(daily,c,edges,basis="Days",daily_stat="Mean")
            self.assertEqual(d.sum().sum(),3.)
            self.assertEqual(d.iloc[0,0],1.)

    def test_illuminance_white_zero_and_stable_source_domain(self):
        from epw_climate_analyzer.chart_theme import ILLUMINANCE_COLORSCALE,metric_colorscale,SOLAR_COLORSCALE
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        for c in ("global_horizontal_illuminance_lux","direct_normal_illuminance_lux","diffuse_horizontal_illuminance_lux"):
            df=pd.DataFrame({c:np.linspace(0.,87321.,len(idx))},index=idx)
            df.iloc[2,0]=np.nan
            self.assertEqual(metric_colorscale(c),ILLUMINANCE_COLORSCALE)
            for period in ("day","week","month"):
                for stat in ("Mean","P95"):
                    fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,stat,"Illuminance","lx")
                    for copy in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                        self.assertEqual((copy.layout.coloraxis.cmin,copy.layout.coloraxis.cmax),(0.,88000.))
                        self.assertEqual(copy.layout.coloraxis.colorscale,tuple(tuple(v) for v in ILLUMINANCE_COLORSCALE))
                        np.testing.assert_allclose(np.asarray(copy.data[0].z,float),temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,stat).values,equal_nan=True)
            df[c]=0.
            fig=temporal_heatmap_chart(df,c,"day",HEATMAP_COMPARE_HOUR,"Mean","Illuminance","lx")
            self.assertEqual((fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax),(0.,1000.))
        self.assertEqual(ILLUMINANCE_COLORSCALE[0],[0.,"#FFFFFF"])
        self.assertEqual(metric_colorscale("global_horizontal_radiation_wh_m2"),SOLAR_COLORSCALE)

    def test_illuminance_common_absolute_domain_across_components(self):
        from epw_climate_analyzer.chart_theme import ILLUMINANCE_COLUMNS,ILLUMINANCE_COLORSCALE
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        from epw_climate_analyzer.extended_visualization import occurrence_default_edges,occurrence_table,occurrence_figure
        idx=pd.date_range("2026-07-01",periods=72,freq="h")
        df=pd.DataFrame({c:np.linspace(0.,m,len(idx)) for c,m in zip(ILLUMINANCE_COLUMNS,(87321.,123456.,24560.))},index=idx)
        reference_labels=None
        reference_colors=None
        for c in ILLUMINANCE_COLUMNS:
            for period in ("day","week","month"):
                for stat in ("Mean","Maximum","P95"):
                    fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,stat,"Illuminance","lx")
                    self.assertEqual((fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax),(0.,124000.))
                    self.assertEqual(fig.layout.coloraxis.colorscale,tuple(tuple(x) for x in ILLUMINANCE_COLORSCALE))
                    np.testing.assert_allclose(np.asarray(fig.data[0].z,float),temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,stat).values,equal_nan=True)
            fig=occurrence_figure(occurrence_table(df,c,occurrence_default_edges(df[c],c)),"lx","Hours")
            labels=[tr.name for tr in fig.data];colors=[tr.marker.color for tr in fig.data]
            if reference_labels is None:reference_labels,reference_colors=labels,colors
            self.assertEqual(labels,reference_labels)
            self.assertEqual(colors,reference_colors)
        incomplete=df.drop(columns=[ILLUMINANCE_COLUMNS[1]])
        fig=temporal_heatmap_chart(incomplete,ILLUMINANCE_COLUMNS[2],"day",HEATMAP_COMPARE_HOUR,"Mean","Illuminance","lx")
        self.assertEqual(fig.layout.coloraxis.cmax,88000.)

    def test_radiation_occurrence_reference_classes(self):
        from epw_climate_analyzer.extended_visualization import occurrence_default_edges,occurrence_table,occurrence_figure
        short=[50.,100.,200.,400.,600.,800.,1000.,1200.]
        daily=[500.,1000.,2000.,4000.,6000.,8000.,10000.,12000.]
        for c in ("global_horizontal_radiation_wh_m2","direct_normal_radiation_wh_m2",
                  "diffuse_horizontal_radiation_wh_m2","poa_global_wh_m2","poa_direct_wh_m2",
                  "poa_sky_diffuse_wh_m2","poa_ground_diffuse_wh_m2",
                  "extraterrestrial_direct_normal_radiation_wh_m2"):
            self.assertEqual(occurrence_default_edges(pd.Series([0.]),c),short)
            self.assertEqual(occurrence_default_edges(pd.Series([0.]),c,interval_hours=.25),[v*.25 for v in short])
            self.assertEqual(occurrence_default_edges(pd.Series([0.]),c,basis="Days",daily_stat="Total",interval_hours=.25),daily)
            vals=[0.,0.,1.,*short,-1.,np.nan]
            df=pd.DataFrame({c:vals},index=pd.date_range("2026-01-01",periods=len(vals),freq="h"))
            tab=occurrence_table(df,c,short)
            np.testing.assert_allclose(tab.iloc[0],[2.,*([1.]*(len(short)+1))])
            self.assertEqual(tab.sum().sum(),len(vals)-2)
            self.assertAlmostEqual(occurrence_table(df,c,short,basis="Percentage").sum().sum(),100.)
            fig=occurrence_figure(tab,"Wh/m²","Hours")
            self.assertEqual(fig.data[0].name,"No recorded radiation (= 0) Wh/m²")
            self.assertEqual(fig.data[0].marker.color,"#E5E7EB")
        self.assertEqual(occurrence_default_edges(pd.Series([0.]),"global_horizontal_irradiance_w_m2",interval_hours=.25),short)
        c="horizontal_infrared_radiation_intensity_wh_m2"
        self.assertEqual(occurrence_default_edges(pd.Series([300.]),c),[200.,250.,300.,350.,400.,450.,500.])
        c="diffuse_radiation_fraction_pct"
        df=pd.DataFrame({c:[0.,10.,20.,40.,60.,80.,100.,101.,-1.,np.nan]},index=pd.date_range("2026-01-01",periods=10,freq="h"))
        edges=occurrence_default_edges(df[c],c)
        self.assertEqual(edges,[20.,40.,60.,80.])
        tab=occurrence_table(df,c,edges)
        np.testing.assert_allclose(tab.iloc[0],[1.,1.,1.,1.,1.,2.])
        self.assertEqual(tab.sum().sum(),7.)
        c="global_horizontal_radiation_wh_m2"
        df=pd.DataFrame({c:np.repeat([0.,100.,400.,-1.],24)},index=pd.date_range("2026-01-01",periods=96,freq="h"))
        self.assertEqual(occurrence_table(df,c,daily,basis="Days",daily_stat="Total").sum().sum(),3.)

    def test_poa_semantic_colors_and_common_heatmap_domain(self):
        from epw_climate_analyzer.chart_theme import POA_COMPONENT_COLORS,SOLAR_COLORSCALE,metric_color,metric_band_colors,semantic_color_from_text
        from epw_climate_analyzer.charts import temporal_heatmap_chart,duration_chart,histogram_chart,monthly_box_chart,profile_line_chart
        from epw_climate_analyzer.monthly_radiation import SURFACE_FIELDS,SURFACE_COLORS
        from epw_climate_analyzer.extended_visualization import occurrence_default_edges,occurrence_table,occurrence_figure
        idx=pd.date_range("2026-07-01",periods=72,freq="h")
        cols=list(POA_COMPONENT_COLORS)
        df=pd.DataFrame({c:np.linspace(0.,m,len(idx)) for c,m in zip(cols,(1000.,700.,220.,80.))},index=idx)
        self.assertEqual(len(set(POA_COMPONENT_COLORS.values())),4)
        labels=("Reference vertical POA","Reference direct POA","Reference sky-diffuse POA","Reference ground-reflected POA")
        for c,label in zip(cols,labels):
            color=POA_COMPONENT_COLORS[c]
            self.assertEqual(metric_color(c),color)
            self.assertEqual(semantic_color_from_text(label),color)
            self.assertEqual(metric_band_colors(c)[1],color)
            self.assertEqual(duration_chart(df,c,label,"Wh/m²").data[0].line.color,color)
            self.assertEqual(histogram_chart(df,c,label,"Wh/m²").data[0].marker.color,color)
            self.assertEqual(monthly_box_chart(df,c,label,"Wh/m²").data[0].line.color,color)
            self.assertEqual(profile_line_chart(df,c,"Native",label,"Wh/m²").data[0].line.color,color)
            for stat in ("Mean","Total"):
                fig=temporal_heatmap_chart(df,c,"month",HEATMAP_COMPARE_HOUR,stat,label,"Wh/m²")
                upper=1000. if stat=="Mean" else float(temporal_heatmap_matrix(df,cols[0],"month",HEATMAP_COMPARE_HOUR,stat).max().max())
                self.assertEqual((fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax),(0.,upper))
                self.assertEqual(fig.layout.coloraxis.colorscale,tuple(tuple(v) for v in SOLAR_COLORSCALE))
            edges=occurrence_default_edges(df[c],c)
            self.assertEqual(edges,[50.,100.,200.,400.,600.,800.,1000.,1200.])
            fig=occurrence_figure(occurrence_table(df,c,edges),"Wh/m²","Hours")
            self.assertEqual(fig.data[0].marker.color,"#E5E7EB")
        self.assertEqual(SURFACE_COLORS,{label:POA_COMPONENT_COLORS[c] for label,c in SURFACE_FIELDS.items()})

    def test_irradiation_heatmaps_white_absolute_zero(self):
        from epw_climate_analyzer.chart_theme import SOLAR_COLORSCALE,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart,matrix_heatmap
        idx=pd.date_range("2026-07-01",periods=72,freq="h")
        for c in ("global_horizontal_radiation_wh_m2","direct_normal_radiation_wh_m2",
                  "diffuse_horizontal_radiation_wh_m2","global_horizontal_irradiance_w_m2",
                  "horizontal_infrared_radiation_intensity_wh_m2","extraterrestrial_horizontal_radiation_wh_m2",
                  "poa_global_wh_m2","poa_direct_wh_m2","poa_sky_diffuse_wh_m2",
                  "poa_ground_diffuse_wh_m2"):
            df=pd.DataFrame({c:np.linspace(10.,800.,len(idx))},index=idx)
            df.iloc[2,0]=np.nan
            self.assertEqual(metric_colorscale(c),SOLAR_COLORSCALE)
            for period in ("day","week","month"):
                fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,"Mean","Irradiation","Wh/m²")
                for copy in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                    self.assertEqual(copy.layout.coloraxis.cmin,0.)
                    self.assertGreater(copy.layout.coloraxis.cmax,0.)
                    self.assertEqual(copy.layout.coloraxis.colorscale,tuple(tuple(v) for v in SOLAR_COLORSCALE))
                    np.testing.assert_allclose(np.asarray(copy.data[0].z,float),temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,"Mean").values,equal_nan=True)
            df[c]=0.
            fig=temporal_heatmap_chart(df,c,"day",HEATMAP_COMPARE_HOUR,"Mean","Irradiation","Wh/m²")
            self.assertEqual(fig.layout.coloraxis.cmin,0.)
            self.assertGreater(fig.layout.coloraxis.cmax,0.)
        mat=pd.DataFrame([[50.,100.],[150.,200.]])
        fig=matrix_heatmap(mat,"Orientation–tilt irradiation","Azimuth","Tilt","kWh/m²")
        self.assertEqual((fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax),(0.,200.))
        self.assertEqual(fig.layout.coloraxis.colorscale,tuple(tuple(v) for v in SOLAR_COLORSCALE))
        self.assertEqual(SOLAR_COLORSCALE[0],[0.,"#FFFFFF"])

    def test_wind_occurrence_reference_classes_match_rose(self):
        from epw_climate_analyzer.chart_theme import WIND_SPEED_COLUMNS,WIND_SPEED_COLORS,WIND_SPEED_OCCURRENCE_EDGES
        from epw_climate_analyzer.extended_visualization import occurrence_default_edges,occurrence_table,occurrence_figure
        edges=list(WIND_SPEED_OCCURRENCE_EDGES)
        for c in WIND_SPEED_COLUMNS:
            vals=[0.,.1,1.,1.1,2.,2.1,4.,4.1,6.,6.1,8.,8.1,12.,12.1,25.,-1.,np.nan]
            df=pd.DataFrame({c:vals},index=pd.date_range("2026-01-01",periods=len(vals),freq="h"))
            self.assertEqual(occurrence_default_edges(pd.Series([0.]),c),edges)
            self.assertEqual(occurrence_default_edges(df[c],c,basis="Days",daily_stat="Maximum",interval_hours=.25),edges)
            table=occurrence_table(df,c,edges)
            np.testing.assert_allclose(table.iloc[0],[1.,2.,2.,2.,2.,2.,2.,2.])
            self.assertEqual(table.sum().sum(),15.)
            self.assertAlmostEqual(occurrence_table(df,c,edges,basis="Percentage").sum().sum(),100.)
            fig=occurrence_figure(table,"m/s","Hours")
            self.assertEqual([tr.marker.color for tr in fig.data],["#E5E7EB",*WIND_SPEED_COLORS])
            self.assertEqual(fig.data[1].name,"0 < x ≤ 1 m/s")
            self.assertEqual(fig.data[-1].name,"> 12 m/s")
            custom=occurrence_figure(occurrence_table(df,c,[3.,7.]),"m/s","Hours")
            self.assertEqual(len(custom.data),4)
            sub=df.copy();sub.attrs["canonical_native_interval_minutes"]=15.
            self.assertAlmostEqual(occurrence_table(sub,c,edges).sum().sum(),15*.25)
            day=pd.DataFrame({c:np.repeat([0.,4.,13.,-1.],24)},index=pd.date_range("2026-01-01",periods=96,freq="h"))
            np.testing.assert_allclose(occurrence_table(day,c,edges,basis="Days",daily_stat="Maximum").iloc[0],[1.,0.,0.,1.,0.,0.,0.,1.])

    def test_wind_direction_cyclic_absolute_compass_domain(self):
        from epw_climate_analyzer.chart_theme import WIND_DIRECTION_COLUMNS,WIND_DIRECTION_COLORSCALE,WIND_DIRECTION_TICKS,WIND_DIRECTION_LABELS,ORIENTATION_COLORS,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        from epw_climate_analyzer.aggregations import heatmap_default_statistic
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        angles=np.resize([0.,45.,90.,135.,180.,225.,270.,315.,360.,359.,1.,np.nan],len(idx))
        for col in WIND_DIRECTION_COLUMNS:
            self.assertEqual(metric_colorscale(col),WIND_DIRECTION_COLORSCALE)
            df=pd.DataFrame({col:angles,"wind_speed_m_s":5.,"wind_gust_speed_m_s":8.},index=idx)
            stat=heatmap_default_statistic(col)
            for period in ("day","week","month"):
                fig=temporal_heatmap_chart(df,col,period,HEATMAP_COMPARE_HOUR,stat,"Wind direction","deg")
                for copy in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                    ca=copy.layout.coloraxis
                    self.assertEqual((ca.cmin,ca.cmax),(0.,360.))
                    self.assertEqual(ca.colorscale,tuple(tuple(v) for v in WIND_DIRECTION_COLORSCALE))
                    self.assertEqual(ca.colorscale[0][1],ca.colorscale[-1][1])
                    self.assertEqual(tuple(ca.colorbar.tickvals),WIND_DIRECTION_TICKS)
                    self.assertEqual(tuple(ca.colorbar.ticktext),tuple(f"{label} · {angle}°" for angle,label in zip(WIND_DIRECTION_TICKS,WIND_DIRECTION_LABELS)))
                    np.testing.assert_allclose(np.asarray(copy.data[0].z,float),temporal_heatmap_matrix(df,col,period,HEATMAP_COMPARE_HOUR,stat).values,equal_nan=True)
            df[col]=100.
            fig=temporal_heatmap_chart(df,col,"day",HEATMAP_COMPARE_HOUR,stat,"Wind direction","deg")
            self.assertEqual((fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax),(0.,360.))
        self.assertEqual(WIND_DIRECTION_COLORSCALE[4],[.5,ORIENTATION_COLORS["south"]])

    def test_wind_speed_and_gust_green_absolute_domain(self):
        from epw_climate_analyzer.chart_theme import WIND_SPEED_COLUMNS,WIND_SPEED_COLORSCALE,wind_speed_colorscale,metric_colorscale
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        idx=pd.date_range("2026-01-01",periods=72,freq="h")
        df=pd.DataFrame({WIND_SPEED_COLUMNS[0]:np.linspace(0.,7.5,len(idx)),
                         WIND_SPEED_COLUMNS[1]:np.linspace(0.,19.3,len(idx))},index=idx)
        df.iloc[2,0]=np.nan
        for c in WIND_SPEED_COLUMNS:
            self.assertEqual(metric_colorscale(c),WIND_SPEED_COLORSCALE)
            for period in ("day","week","month"):
                for stat in ("Mean","Maximum","P95"):
                    fig=temporal_heatmap_chart(df,c,period,HEATMAP_COMPARE_HOUR,stat,"Wind speed","m/s")
                    for copied in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                        self.assertEqual((copied.layout.coloraxis.cmin,copied.layout.coloraxis.cmax),(0.,20.))
                        self.assertEqual(copied.layout.coloraxis.colorscale,tuple(tuple(v) for v in wind_speed_colorscale(20.)))
                        np.testing.assert_allclose(np.asarray(copied.data[0].z,float),temporal_heatmap_matrix(df,c,period,HEATMAP_COMPARE_HOUR,stat).values,equal_nan=True)
        calm=df[[WIND_SPEED_COLUMNS[0]]].copy()
        calm.iloc[:,0]=0.
        fig=temporal_heatmap_chart(calm,WIND_SPEED_COLUMNS[0],"day",HEATMAP_COMPARE_HOUR,"Mean","Wind speed","m/s")
        self.assertEqual((fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax),(0.,12.))
        self.assertEqual(fig.layout.coloraxis.colorscale[0],(0.,"#FFFFFF"))
        self.assertNotEqual(metric_colorscale("wind_direction_deg"),WIND_SPEED_COLORSCALE)
        self.assertEqual(wind_speed_colorscale(20.)[-2],[.6,"#064E3B"])

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
