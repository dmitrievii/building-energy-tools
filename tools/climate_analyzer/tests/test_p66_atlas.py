"""P6.6 catalogue and export qualification: deterministic IDs and explicit coverage."""
import csv
import io
import unittest
import zipfile
import numpy as np
import pandas as pd
from PIL import Image
from epw_climate_analyzer import p66_catalogue as c
from epw_climate_analyzer.p66_render import make_figure,NotApplicable
from epw_climate_analyzer.p66_export import generate_atlas,manifest_csv,PDF_MODES

class AtlasTests(unittest.TestCase):
    def fixture(self):
        idx=pd.date_range("2026-01-01",periods=96,freq="h")
        t=np.sin(np.arange(len(idx))*2*np.pi/24)*2+18.
        df=pd.DataFrame({c.T:t,c.RH:60.,c.W:7.,c.V:2.,c.WD:270.,c.P:np.where(np.arange(len(idx))%24==0,1.,0.)},index=idx)
        df["hour_of_day"]=idx.hour;df["month_index"]=idx.month;df.attrs["canonical_native_interval_minutes"]=60.
        return df
    def test_full_catalogue_explicit_aggregations(self):
        df=self.fixture();rows=c.catalogue(df,{},c.FULL)
        self.assertEqual(len(rows),len({d.id for d in rows}))
        temp=[d for d in rows if d.column==c.T and d.status=="available"]
        from epw_climate_analyzer.aggregations import profile_representation_options
        expected={p for p in c.PERIODS if "Min–mean–max" in profile_representation_options(df,c.T,p)}
        for kind in ("profile","percentile"):
            self.assertEqual({d.args[0] for d in temp if d.kind==kind},expected)
        native=[d for d in temp if d.kind=="time_series" and d.args[0]=="Hourly"]
        self.assertEqual(len(native),1)
        fig,note=make_figure(native[0],df,{})
        self.assertEqual(len(fig.data),1)
        np.testing.assert_allclose(fig.data[0].y,df[c.T])
        self.assertEqual(len([d for d in temp if d.kind=="heatmap"]),13)
        self.assertEqual(len([d for d in temp if d.kind=="heatmap" and d.args[0]=="day"]),1)
        self.assertEqual(len([d for d in temp if d.kind=="diurnal"]),12)
        self.assertEqual(len([d for d in temp if d.kind=="duration"]),4)
        self.assertGreater(len(rows),len(c.catalogue(df,{},c.REP)))
        self.assertTrue(any(d.kind=="not_registered" for d in rows))
    def test_adaptive_combined_categories_and_daily_axis(self):
        from epw_climate_analyzer.p3_comfort import adaptive_bands
        from epw_climate_analyzer.p3_adaptive_chart import adaptive_figure,adaptive_interpretation,selected_daily_bands
        for year,n in ((2026,365),(2024,366)):
            idx=pd.date_range(f"{year}-01-01",periods=n*24,freq="h")
            df=pd.DataFrame({c.T:18.},index=idx)
            df.attrs["canonical_native_interval_minutes"]=60.
            for coverage in c.LEVELS:
                self.assertEqual(len([d for d in c.catalogue(df,{},coverage) if d.kind=="adaptive"]),1)
            d=next(d for d in c.catalogue(df,{},c.FULL) if d.kind=="adaptive")
            fig,note=make_figure(d,df,{})
            self.assertEqual(set(tr.name for tr in fig.data),{"Category I","Category II","Category III","Neutral operative temperature","Outdoor running mean"})
            self.assertEqual(str(fig.layout.xaxis.ticktext[-1]),str(n))
            self.assertEqual(fig.layout.legend.orientation,"h")
            self.assertIn(f"{n-7}/{n}",note)
            expected=adaptive_bands(df)
            neutral=next(tr for tr in fig.data if tr.name=="Neutral operative temperature")
            np.testing.assert_allclose(np.asarray(neutral.y,float),expected.Neutral,equal_nan=True)
            # Noncontiguous selected dates must not be joined by a ribbon.
            subset=df.loc[(df.index.dayofyear==10)|(df.index.dayofyear==12)]
            table=selected_daily_bands(expected,subset)
            f=adaptive_figure(table)
            band=next(tr for tr in f.data if tr.name=="Category I")
            self.assertEqual(list(band.x).count(None),2)
            self.assertIn("2/2",adaptive_interpretation(table))
        cold=df.copy();cold[c.T]=0.
        f,note=make_figure(d,cold,{})
        self.assertIn("0/366",note)
        self.assertIn("below 10 °C: 359 days",note)

    def test_redundant_tail_diagrams_removed(self):
        df=self.fixture()
        for coverage in c.LEVELS:
            rows=c.catalogue(df,{},coverage)
            self.assertFalse(any(d.kind in ("design_tail","tail_curve") for d in rows))
            self.assertEqual(len([d for d in rows if d.kind=="critical_windows"]),6)
            self.assertTrue(any(d.kind=="duration" and d.column==c.T for d in rows))

    def test_design_markers_and_critical_window_chronology(self):
        from epw_climate_analyzer.p4_extremes import design_conditions
        from epw_climate_analyzer.p4_design_charts import critical_windows_figure
        df=self.fixture()
        for d in [d for d in c.catalogue(df,{},c.FULL) if d.kind=="duration" and d.column==c.T]:
            fig,note=make_figure(d,df,{})
            marker=next(tr for tr in fig.data if tr.name=="Design quantiles")
            expected=design_conditions(df,c.T,[.4,1.,2.,5.],upper=not d.args[1])
            np.testing.assert_allclose(marker.y,expected.Quantile)
            x=expected["Nominal tail [%]"]
            if d.args[2]=="hours":x=x*expected["Valid hours"]/100
            np.testing.assert_allclose(marker.x,x)
            self.assertEqual(len(fig.data[0].y),len(df))
        for upper in (True,False):
            fig,table,note=critical_windows_figure(df,c.T,"°C",upper=upper)
            self.assertEqual(len(table),1)
            self.assertEqual(table.End.iloc[0]-table.Start.iloc[0],pd.Timedelta(hours=71))
            self.assertAlmostEqual(table.Mean.iloc[0],df.loc[table.Start.iloc[0]:table.End.iloc[0],c.T].mean())
            cutoff=next(tr for tr in fig.data if tr.name.startswith("Selection cutoff"))
            self.assertEqual(cutoff.line.dash,"dot")
            np.testing.assert_allclose(cutoff.y,table.Mean.iloc[-1])
            self.assertEqual(len(fig.layout.shapes),1)
            self.assertTrue(all(tr.type=="scatter" for tr in fig.data))
        broken=df.drop(df.index[48])
        fig,table,note=critical_windows_figure(broken,c.T,"°C")
        self.assertIsNone(fig)
        self.assertTrue(table.empty)

    def test_persistence_stack_with_observed_total_line(self):
        from epw_climate_analyzer.p3_persistence_chart import persistence_figure
        from epw_climate_analyzer.p3_comfort import persistence_monthly
        from epw_climate_analyzer.p6_report_structure import report_figure
        table=pd.DataFrame({"Longest run [h]":[1.,3.,np.nan,2.]},
                           index=pd.to_datetime(["2026-01-01","2026-01-02","2026-02-01","2026-03-01"]))
        counts=persistence_monthly(table,2.)
        for night in (False,True):
            fig=persistence_figure(counts,"Persistence",night=night)
            for f in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                self.assertEqual(f.layout.barmode,"stack")
                self.assertEqual([tr.type for tr in f.data],["bar","bar","scatter"])
                self.assertEqual(f.data[2].mode,"lines+markers")
                self.assertFalse(f.data[2].connectgaps)
                np.testing.assert_allclose(np.asarray(f.data[0].y,float)+np.asarray(f.data[1].y,float),
                                           np.asarray(f.data[2].y,float),equal_nan=True)
                self.assertTrue(np.isnan(np.asarray(f.data[2].y,float)[1]))
                self.assertEqual(list(f.layout.xaxis.ticktext),["Jan","Feb","Mar"])
        df=self.fixture();d=next(d for d in c.catalogue(df,{},c.FULL) if d.kind=="nv_special" and d.args[0]=="Persistence")
        fig,note=make_figure(d,df,{})
        self.assertEqual([tr.type for tr in fig.data],["bar","bar","scatter"])
        self.assertEqual(fig.layout.barmode,"stack")

    def test_utci_stress_palette_and_raw_values(self):
        from epw_climate_analyzer.p3_comfort import EDGES,CLASSES,COLORS,utci_class_hours
        from epw_climate_analyzer.utci_presentation import stress_heatmap,stress_codes,duration_figure
        from epw_climate_analyzer.p6_report_structure import report_figure
        raw=np.array([-55.,*EDGES,60.,np.nan])
        expected=np.array([0.,*range(9),9.,np.nan])
        np.testing.assert_allclose(stress_codes(raw),expected,equal_nan=True)
        idx=pd.date_range("2026-01-01",periods=len(raw),freq="h")
        df=pd.DataFrame({"test":raw},index=idx)
        hours=utci_class_hours(df,df.test)
        np.testing.assert_allclose(hours.sum().to_numpy(),np.bincount(expected[np.isfinite(expected)].astype(int),minlength=10))
        fig=stress_heatmap(list(range(len(raw))),[0],raw[None,:],x_label="Physical input",y_label="Hour of day")
        for f in (fig,report_figure(fig,width_pt=500,height_pt=230)):
            trace=f.data[0]
            np.testing.assert_allclose(np.asarray(trace.customdata,float),raw[None,:],equal_nan=True)
            np.testing.assert_allclose(np.asarray(trace.z,float),expected[None,:],equal_nan=True)
            self.assertEqual((trace.zmin,trace.zmax),(-.5,9.5))
            self.assertEqual(len(trace.colorbar.ticktext),10)
            self.assertEqual([trace.colorscale[i*2][1] for i in range(10)],list(COLORS))
            self.assertEqual(list(f.layout.meta["utci_practical_range"]),[-40,46])
        curves=duration_figure(df,1.,"Test UTCI")
        self.assertGreater(curves.layout.yaxis.range[1],60.)
        self.assertLess(curves.layout.yaxis.range[0],-55.)
        self.assertEqual(len(curves.layout.shapes),10)

    def test_site_shading_calendar_profiles_and_occurrence(self):
        from epw_climate_analyzer.shading_calendar import (AREA,OCCURRENCE,VALUE,EVENT,FRONT,shading_frame,shading_matrix,shading_calendar,monthly_shading_profiles,shading_statistics)
        from epw_climate_analyzer.solar_shading import shaded_fraction
        idx=pd.date_range("2026-07-01 12:00",periods=4,freq="h")
        df=pd.DataFrame({"solar_azimuth_deg":[180.,180.,0.,np.nan],
                         "solar_apparent_zenith_deg":[80.,20.,45.,45.]},index=idx)
        geometry=dict(facade=180.,width=2.,height=1.5,overhang=.6,left_fin=0.,right_fin=0.)
        frame=shading_frame(df,geometry=geometry,metric=AREA)
        expected=100*shaded_fraction([180.,180.],[10.,70.],**geometry)
        np.testing.assert_allclose(frame[VALUE].iloc[:2],expected)
        self.assertTrue(frame[VALUE].iloc[2:].isna().all())
        self.assertEqual(frame[FRONT].iloc[2],0.)
        self.assertTrue(pd.isna(frame[FRONT].iloc[3]))
        np.testing.assert_allclose(frame[EVENT].iloc[:2],100*(expected>=80))
        for metric in (AREA,OCCURRENCE):
            for period in ("day","week","month"):
                values,front=shading_matrix(frame,metric,period,"Hour of day","Mean")
                fig=shading_calendar(frame,metric,period,"Hour of day","Mean")
                np.testing.assert_allclose(np.asarray(fig.data[0].z,float),values.values,equal_nan=True)
                self.assertEqual((fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax),(0.,100.))
                self.assertEqual(list(fig.layout.yaxis.ticktext),["0","6","12","18","24"])
                self.assertEqual(len(fig.layout.annotations),0)
                self.assertEqual(fig.layout.plot_bgcolor,"rgba(0,0,0,0)")
                self.assertFalse(fig.data[0].hoverongaps)
                # Known no-exposure at 14:00 is transparent; unknown
                # geometry at 15:00 still has a missing-value overlay.
                missing=np.asarray(fig.data[1].z,float)
                self.assertFalse(np.isfinite(missing[14]).any())
                self.assertTrue(np.isfinite(missing[15]).any())
            fig,table=monthly_shading_profiles(frame,metric,[7])
            self.assertTrue(table.iloc[14:].isna().all().all())
            self.assertEqual(list(fig.layout.xaxis.tickvals),[0,6,12,18,24])
        from epw_climate_analyzer.shading_temporal import temporal_shading_tables,shading_month_hour_heatmap
        _,cells=temporal_shading_tables(df,geometry=geometry,metric=AREA)
        legacy=shading_month_hour_heatmap(cells,AREA)
        self.assertEqual(np.asarray(legacy.data[0].z).shape,(24,12))
        np.testing.assert_allclose(np.asarray(legacy.data[0].z,float),cells["All devices"].to_numpy(float).reshape(12,24).T,equal_nan=True)
        self.assertEqual(list(legacy.layout.xaxis.ticktext),["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])
        self.assertEqual(list(legacy.layout.yaxis.ticktext),["0","6","12","18","24"])
        self.assertEqual(shading_statistics(frame,AREA,"day","Hour of day"),("Mean",))
        rows=c.catalogue(df,{},c.FULL)
        self.assertFalse(any(d.kind=="shading_mask" and d.args[0]!="Geometry" for d in rows))
        self.assertTrue(any(d.kind=="shading_calendar" and d.args[0]==OCCURRENCE for d in rows))

    def test_shading_daily_resolution_and_transparency(self):
        from epw_climate_analyzer.shading_calendar import (
            AREA,OCCURRENCE,FRONT,VALUE,EVENT,shading_calendar,shading_matrix)
        from epw_climate_analyzer.temporal_filtering import TIME_BASIS_ATTR,CALENDAR_PROFILE,CHRONOLOGICAL
        from epw_climate_analyzer.chart_presentation import ChartPresentationSettings,apply_chart_presentation
        from epw_climate_analyzer.p6_report_structure import report_figure
        idx=pd.date_range("2024-01-01","2025-01-01",freq="h",inclusive="left")
        daylight=(idx.hour>=8)&(idx.hour<18)
        frame=pd.DataFrame({FRONT:daylight.astype(float),
                            VALUE:np.where(daylight,idx.dayofyear%100,np.nan),
                            EVENT:np.where(daylight,100.*(idx.dayofyear%100>=80),np.nan)},
                           index=idx)
        frame.attrs["canonical_native_interval_minutes"]=60
        for basis in (CALENDAR_PROFILE,CHRONOLOGICAL):
            frame.attrs[TIME_BASIS_ATTR]=basis
            for metric in (AREA,OCCURRENCE):
                for period,ncols in (("day",366),("month",12)):
                    vals,front=shading_matrix(frame,metric,period,"Hour of day","Mean")
                    fig=shading_calendar(frame,metric,period,"Hour of day","Mean")
                    self.assertEqual(vals.shape,(24,ncols))
                    self.assertEqual(len(fig.data[0].x),ncols)
                    self.assertEqual(fig.layout.xaxis.title.text,period.capitalize())
                    self.assertEqual(len(fig.layout.annotations),0)
                    self.assertEqual(len(fig.data),1)
                    self.assertTrue(np.isnan(np.asarray(fig.data[0].z,float)[0]).all())
                    np.testing.assert_allclose(np.asarray(fig.data[0].z,float),vals.values,equal_nan=True)
                    apply_chart_presentation(fig,ChartPresentationSettings())
                    printed=report_figure(fig,width_pt=500,height_pt=230)
                    self.assertEqual(len(printed.data[0].x),ncols)
                    self.assertEqual(len(printed.layout.annotations),0)
                    self.assertEqual(len(printed.data),1)

    def test_monthly_source_no_hourly_invention(self):
        df=self.fixture().iloc[[0]].copy();df.attrs["canonical_native_resolution"]="monthly"
        rows=c.catalogue(df,{},c.FULL)
        self.assertFalse(any(d.status=="available" and d.kind in ("heatmap","duration","degree","utci","nv_special","wind_mean") for d in rows))
        self.assertTrue(any(d.kind=="native" and d.status=="available" for d in rows))
    def test_source_radiation_semantic_colors_and_domains(self):
        from epw_climate_analyzer.chart_theme import SOURCE_IRRADIATION_COLORS,SOURCE_IRRADIANCE_COLORS,SOLAR_COLORSCALE,metric_color
        from epw_climate_analyzer.charts import temporal_heatmap_chart
        from epw_climate_analyzer.aggregations import temporal_heatmap_matrix,HEATMAP_COMPARE_HOUR
        from epw_climate_analyzer.extended_visualization import occurrence_default_edges,occurrence_table,occurrence_figure
        df=self.fixture()
        cols=list(SOURCE_IRRADIATION_COLORS)
        for col,maximum in zip(cols,(800.,1000.,300.)):
            df[col]=np.linspace(0.,maximum,len(df))
        for col,maximum in zip(SOURCE_IRRADIANCE_COLORS,(80.,100.,30.)):
            df[col]=np.linspace(0.,maximum,len(df))
        for family in (SOURCE_IRRADIATION_COLORS,SOURCE_IRRADIANCE_COLORS):
            for col,color in family.items():
                self.assertEqual(metric_color(col),color)
                fig=temporal_heatmap_chart(df,col,"month",HEATMAP_COMPARE_HOUR,"Mean","Radiation","Wh/m²" if col.endswith("_wh_m2") else "W/m²")
                self.assertEqual(fig.layout.coloraxis.cmin,0.)
                self.assertEqual(fig.layout.coloraxis.cmax,1000. if col.endswith("_wh_m2") else 100.)
                self.assertEqual(fig.layout.coloraxis.colorscale,tuple(tuple(x) for x in SOLAR_COLORSCALE))
                if col.endswith("_wh_m2"):
                    fig=temporal_heatmap_chart(df,col,"month",HEATMAP_COMPARE_HOUR,"Total","Radiation","Wh/m²")
                    upper=float(temporal_heatmap_matrix(df,cols[1],"month",HEATMAP_COMPARE_HOUR,"Total").max().max())
                    self.assertEqual(fig.layout.coloraxis.cmax,upper)
                edges=occurrence_default_edges(df[col],col)
                self.assertEqual(edges,[50.,100.,200.,400.,600.,800.,1000.,1200.])
                self.assertEqual(occurrence_figure(occurrence_table(df,col,edges),"Wh/m²","Hours").data[0].marker.color,"#E5E7EB")
        rows=[d for d in c.catalogue(df,{},c.FULL) if d.kind=="total" and d.column in cols and d.status=="available"]
        self.assertEqual({d.column for d in rows},set(cols))
        for d in rows:
            fig,_=make_figure(d,df,{})
            self.assertEqual(fig.data[0].marker.color,SOURCE_IRRADIATION_COLORS[d.column])
        monthly=df.iloc[:1].copy();monthly.attrs["canonical_native_resolution"]="monthly"
        for col in cols:
            d=next(d for d in c.catalogue(monthly,{},c.REP) if d.kind=="native" and d.column==col and d.status=="available")
            fig,_=make_figure(d,monthly,{})
            self.assertEqual(fig.data[0].line.color,SOURCE_IRRADIATION_COLORS[col])

    def test_illuminance_threshold_yellow_all_periods(self):
        from epw_climate_analyzer.chart_theme import ILLUMINANCE_THRESHOLD_COLOR,semantic_color_from_text
        from epw_climate_analyzer.charts import threshold_bar_chart
        from epw_climate_analyzer.p6_report_structure import report_figure
        df=self.fixture()
        df[c.LUX]=np.resize([0.,299.,300.,1000.,np.nan],len(df))
        rows=[d for d in c.catalogue(df,{},c.FULL) if d.kind=="illumination" and d.status=="available"]
        self.assertEqual({d.args[0] for d in rows},set(c.TOTAL_PERIODS))
        for d in rows:
            fig,_=make_figure(d,df,{})
            for copy in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                self.assertTrue(all(tr.marker.color==ILLUMINANCE_THRESHOLD_COLOR for tr in copy.data))
            self.assertAlmostEqual(float(np.nansum(fig.data[0].y)),float(df[c.LUX].ge(300.).sum()))
        self.assertEqual(semantic_color_from_text("Illuminance >= 300 lux"),ILLUMINANCE_THRESHOLD_COLOR)
        self.assertEqual(threshold_bar_chart(pd.DataFrame({"hours":[10.]},index=["Jan"]),"Illuminance ≥ 300 lux").data[0].marker.color,ILLUMINANCE_THRESHOLD_COLOR)

    def test_degree_colors_semantic_in_atlas_and_legacy_reports(self):
        import plotly.graph_objects as go
        from epw_climate_analyzer.chart_theme import HEATING_COLOR,COOLING_COLOR
        from epw_climate_analyzer.degree_metrics import degree_legend_below
        from epw_climate_analyzer.p6_report_structure import report_figure
        df=self.fixture()
        df[c.T]=np.repeat([5.,30.,8.,32.],24)
        rows=[d for d in c.catalogue(df,{},c.FULL) if d.kind=="degree" and d.status=="available"]
        self.assertEqual(len(rows),2*len(c.TOTAL_PERIODS))
        for d in rows:
            fig,_=make_figure(d,df,{})
            for tr in fig.data:
                self.assertEqual(tr.marker.color,HEATING_COLOR if tr.name.startswith("Heating") else COOLING_COLOR)
        legacy=go.Figure()
        legacy.add_bar(x=["Jan"],y=[3.],name="Cooling degree-days (KGT)",marker_color=HEATING_COLOR)
        legacy.add_bar(x=["Jan"],y=[17.],name="Heating degree-days (HGT)",marker_color=COOLING_COLOR)
        for fig in (report_figure(legacy,width_pt=500,height_pt=230),degree_legend_below(go.Figure(legacy))):
            self.assertEqual([tr.marker.color for tr in fig.data],[COOLING_COLOR,HEATING_COLOR])
            self.assertEqual([float(tr.y[0]) for tr in fig.data],[3.,17.])
            self.assertEqual(fig.layout.legend.orientation,"h")

    def test_paired_scatter_visible_and_finite(self):
        from epw_climate_analyzer.charts import paired_scatter_chart,PAIRED_SCATTER_COLOR,PAIRED_SCATTER_SVG_LIMIT
        from epw_climate_analyzer.p6_report_structure import report_figure
        df=self.fixture()
        df.loc[df.index[0],c.T]=np.nan
        df.loc[df.index[1],c.RH]=np.inf
        d=next(d for d in c.catalogue(df,{},c.FULL) if d.kind=="joint" and d.column==c.T and d.args==(c.RH,"scatter"))
        fig,note=make_figure(d,df,{})
        for copy in (fig,report_figure(fig,width_pt=500,height_pt=230)):
            tr=copy.data[0]
            self.assertEqual(tr.type,"scatter")
            self.assertEqual(tr.marker.color,PAIRED_SCATTER_COLOR)
            self.assertGreaterEqual(tr.marker.opacity,.55)
            np.testing.assert_allclose(tr.x,df[c.T].iloc[2:])
            np.testing.assert_allclose(tr.y,df[c.RH].iloc[2:])
        self.assertIn("94 finite paired observations",note)
        x=pd.Series(np.zeros(PAIRED_SCATTER_SVG_LIMIT+1))
        big=paired_scatter_chart(x,x,"Test","X","Y")
        self.assertEqual(big.data[0].type,"scattergl")
        self.assertEqual(len(big.data[0].x),len(x))
        with self.assertRaises(ValueError):
            paired_scatter_chart(pd.Series([np.nan]),pd.Series([1.]),"Test","X","Y")

    def test_monthly_wind_rose_panel_shared_radial_and_report_layout(self):
        from epw_climate_analyzer.directional_climate import monthly_wind_rose_panel,directional_class_table
        from epw_climate_analyzer.p6_report_structure import report_figure
        df=pd.DataFrame({c.V:[1.,2.,4.,0.,8.,3.],c.WD:[0.,90.,90.,180.,270.,225.]},
            index=pd.to_datetime(["2026-01-01 07:00","2026-01-01 08:00","2026-02-01 09:00","2026-02-01 10:00","2026-12-01 12:00","2025-01-01 08:00"]))
        df.attrs["canonical_native_interval_minutes"]=60.
        fig,tables=monthly_wind_rose_panel(df)
        self.assertEqual(set(tables),{1,2,12})
        for m,table in tables.items():
            expected=directional_class_table(df.loc[df.index.month==m],radial="Percentage")
            np.testing.assert_allclose(table,expected)
            self.assertAlmostEqual(float(table.to_numpy().sum()),100.)
        self.assertEqual(sum(tr.showlegend is True for tr in fig.data),7)
        self.assertEqual(len(fig.layout.annotations),12)
        self.assertIn("no data",fig.layout.annotations[2].text)
        for copied in (fig,report_figure(fig,width_pt=500,height_pt=700),report_figure(fig,width_pt=740,height_pt=480)):
            polars=[getattr(copied.layout,"polar" if m==1 else f"polar{m}") for m in range(1,13)]
            self.assertEqual(len({tuple(p.domain.x)+tuple(p.domain.y) for p in polars}),12)
            self.assertEqual(len({tuple(p.radialaxis.range) for p in polars}),1)
            self.assertGreaterEqual(polars[0].radialaxis.range[1],100.)
        mean,_=monthly_wind_rose_panel(df,style="Directional mean",radial="Mean wind speed")
        valid=[tr for tr in mean.data if tr.marker.cmin is not None]
        self.assertEqual(len({(tr.marker.cmin,tr.marker.cmax) for tr in valid}),1)
        self.assertEqual(sum(tr.marker.showscale is True for tr in mean.data),1)
        fixture=self.fixture()
        d=next(d for d in c.catalogue(fixture,{},c.REP) if d.kind=="wind_panel")
        atlas,_=make_figure(d,fixture,{})
        self.assertEqual(len(atlas.layout.annotations),12)

    def test_monthly_wind_panel_hours_tight_shared_radial_scale(self):
        from epw_climate_analyzer.directional_climate import monthly_wind_rose_panel
        from epw_climate_analyzer.chart_presentation import ChartPresentationSettings,apply_chart_presentation
        from epw_climate_analyzer.p6_report_structure import report_figure
        idx=pd.date_range("2026-01-01",periods=600,freq="h")
        df=pd.DataFrame({c.V:2.,c.WD:np.repeat([0.,90.,180.],200)},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        for style in ("Class distribution","Directional mean"):
            fig,tables=monthly_wind_rose_panel(df,radial="Hours",style=style)
            apply_chart_presentation(fig,ChartPresentationSettings(font_size=24))
            for copy in (fig,report_figure(fig,width_pt=500,height_pt=700)):
                for m in range(1,13):
                    axis=getattr(copy.layout,"polar" if m==1 else f"polar{m}").radialaxis
                    self.assertEqual(tuple(axis.range),(0.,250.))
                    self.assertEqual(tuple(axis.tickvals),(50.,100.,150.,200.,250.))
                    self.assertEqual(tuple(axis.ticktext),("50","","150","","250"))
                    self.assertLessEqual(axis.tickfont.size,9)
            values=tables[1]
            self.assertAlmostEqual(float(values.to_numpy().sum() if style=="Class distribution" else values.radius.sum()),600.)
        df[c.WD]=0.
        fig,_=monthly_wind_rose_panel(df,radial="Hours")
        self.assertGreaterEqual(fig.layout.polar.radialaxis.range[1],600.)
        percentage,_=monthly_wind_rose_panel(df,radial="Percentage")
        self.assertGreaterEqual(percentage.layout.polar.radialaxis.range[1],100.)

    def test_core_chart_families_execute(self):
        df=self.fixture();rows=[d for d in c.catalogue(df,{},c.FULL) if d.status=="available"]
        types=("time_series","profile","percentile","heatmap","duration","histogram","box","violin","diurnal","occurrence","amplitude","total","degree","temp_threshold","temp_events","day_indicators","wind_mean","wind_classes","wetdry","rolling","cumulative","freeze_days","eligibility_map","eligibility_total","nv_special","critical_windows","correlation","joint")
        cache={}
        for k in types:
            rows_k=[d for d in rows if d.kind==k]
            self.assertTrue(rows_k,k)
            for d in rows_k[:1]:
                with self.subTest(kind=k):
                    fig,note=make_figure(d,df,{},df,cache)
                    self.assertTrue(len(fig.data)>0)
                    self.assertTrue(note)
    def test_export_all_outcomes_and_pdf_layouts(self):
        df=self.fixture();rows=c.catalogue(df,{},c.REP)
        selected=[next(d for d in rows if d.kind=="profile" and d.status=="available"),
                  next(d for d in rows if d.kind=="not_registered")]
        context={"source":"Test.epw","location":"Synthetic fixture"}
        def png(fig):
            result=io.BytesIO();Image.new("RGB",(int(fig.layout.width),int(fig.layout.height)),"white").save(result,format="PNG");return result.getvalue()
        for mode in PDF_MODES:
            data,manifest,metadata=generate_atlas(selected,df,context,mode=mode,image_renderer=png,per_page=2)
            self.assertEqual(metadata["counts"]["generated"],1)
            self.assertEqual(metadata["counts"]["unsupported"],1)
            if mode=="Single PDF":self.assertTrue(data.startswith(b"%PDF"))
            else:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    self.assertIn("coverage.csv",z.namelist())
                    self.assertIn("atlas_metadata.json",z.namelist())
                    self.assertTrue(any(n.endswith(".html" if "HTML" in mode else ".pdf") for n in z.namelist()))
    def test_complete_html_atlas_exceeds_pdf_batch_limit(self):
        from unittest.mock import patch
        import plotly.graph_objects as go
        df=self.fixture();rows=c.catalogue(df,{},c.FULL)
        selected=[d for d in rows if d.status=="available"][:61]
        self.assertEqual(len(selected),61)
        selected.append(next(d for d in rows if d.kind=="not_registered"))
        f=go.Figure(go.Scatter(x=[1,2],y=[3,4]))
        with patch("epw_climate_analyzer.p66_export.make_figure",return_value=(f,"Interpretation")) as render:
            data,manifest,metadata=generate_atlas(selected,df,{},mode=PDF_MODES[2])
        self.assertEqual(render.call_count,61)
        self.assertEqual(metadata["counts"]["generated"],61)
        self.assertEqual(metadata["counts"]["unsupported"],1)
        self.assertEqual(len(manifest),62)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn("index.html",z.namelist())
            self.assertEqual(z.namelist().count("plotly.min.js"),1)
            index=z.read("index.html").decode()
            for name in metadata["html_files"]:
                self.assertIn(name,index)
                self.assertIn("src='plotly.min.js'",z.read(name).decode())
            self.assertEqual(sum(z.read(n).count(b"Plotly.newPlot(") for n in metadata["html_files"]),61)

    def test_batches_cover_all_admitted_and_guard(self):
        from unittest.mock import patch
        from epw_climate_analyzer.p66_export import catalogue_batches
        from epw_climate_analyzer.p66_memory import require_headroom,MIB
        rows=c.catalogue(self.fixture(),{},c.FULL)
        batches=catalogue_batches(rows,20)
        self.assertEqual([d.id for batch in batches for d in batch],
                         [d.id for d in rows if d.status=="available"])
        self.assertTrue(all(len(batch)<=20 for batch in batches))
        with patch("epw_climate_analyzer.p66_memory.container_memory",return_value=(490*MIB,512*MIB)):
            with self.assertRaisesRegex(MemoryError,"Container memory pressure"):require_headroom()
        with patch("epw_climate_analyzer.p66_export.require_headroom",return_value=None):
            with self.assertRaisesRegex(ValueError,"bounded export batch"):
                generate_atlas([d for d in rows if d.status=="available"][:51],self.fixture(),{})
        with patch("epw_climate_analyzer.p66_export.require_headroom",side_effect=MemoryError("low memory")):
            with self.assertRaises(MemoryError):generate_atlas(batches[0],self.fixture(),{})

    def test_zero_event_timeline_and_distribution_status(self):
        df=self.fixture();rows=c.catalogue(df,{},c.FULL)
        timeline=next(d for d in rows if d.kind=="temp_events" and d.args==("max",True,"timeline"))
        dist=next(d for d in rows if d.kind=="temp_events" and d.args==("max",True,"duration"))
        fig,note=make_figure(timeline,df,{},df)
        self.assertEqual(len(fig.data),2)
        with self.assertRaises(NotApplicable):make_figure(dist,df,{},df)

if __name__=="__main__":unittest.main()
