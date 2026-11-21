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

    def test_multiyear_utci_not_truncated(self):
        idx=pd.date_range("2025-12-31","2026-12-31",freq="h")
        df=pd.DataFrame(index=idx)
        grid=annual_hour_grid(df,np.ones(len(idx)))
        self.assertEqual(str(grid.columns[-1].date()),"2026-12-31")
        self.assertEqual(grid.iloc[0,-1],1.)

if __name__=="__main__":unittest.main()
