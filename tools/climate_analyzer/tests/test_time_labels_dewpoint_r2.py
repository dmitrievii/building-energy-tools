"""R2 chronology: date/time labels and dew-point condensation semantics."""
import unittest

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.period_display import format_plotted_time
from epw_climate_analyzer.humidity_findings import humidity_figure_interpretation
from epw_climate_analyzer.temperature_findings import temperature_figure_interpretation
from epw_climate_analyzer.charts import profile_ribbon_chart,profile_line_chart
from epw_climate_analyzer.p6_report_structure import report_figure


class TemporalInterpretationR2Tests(unittest.TestCase):
    @staticmethod
    def frame(year=2026):
        dates=pd.date_range(f"{year}-01-01",periods=24*8,freq="h")
        values=np.linspace(-10,22,len(dates))
        df=pd.DataFrame({
            "dew_point_temperature_c":values,
            "dry_bulb_temperature_c":values+2,
        },index=dates)
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_daily_ordinal_is_calendar_date_not_hour_of_year(self):
        df=self.frame()
        self.assertEqual(format_plotted_time(21,df,title="Dew point · Daily"),"21.01")
        self.assertEqual(format_plotted_time(173,df,title="Dew point · Daily"),"22.06")
        self.assertEqual(format_plotted_time(173,df,aggregation="Daily"),"22.06")
        self.assertEqual(format_plotted_time(173,df,aggregation="Hourly"),"173")
        self.assertEqual(format_plotted_time(173,None,aggregation="Daily"),"173")

    def test_leap_year_and_multiple_real_years(self):
        df=self.frame(2024)
        self.assertEqual(format_plotted_time(60,df,aggregation="Daily"),"29.02")
        self.assertEqual(format_plotted_time(366,df,aggregation="Daily"),"31.12")
        self.assertEqual(format_plotted_time(366,self.frame(2026),aggregation="Daily"),"366")
        multi=pd.concat([self.frame(2025),self.frame(2026)]).sort_index()
        self.assertEqual(format_plotted_time("2025-01-21",multi,aggregation="Daily"),"21.01.2025")
        self.assertEqual(format_plotted_time(pd.Timestamp("2026-06-22 15:00"),multi,aggregation="Hourly"),
                         "22.06.2026 at 15:00")

    def test_datetime_and_month_day_hover_labels(self):
        df=self.frame()
        self.assertEqual(format_plotted_time(pd.Timestamp("2026-06-22 15:00"),df,aggregation="Hourly"),
                         "22.06 at 15:00")
        self.assertEqual(format_plotted_time(np.datetime64("2026-06-22T15:00"),df,aggregation="Native"),
                         "22.06 at 15:00")
        self.assertEqual(format_plotted_time("06-22 15:00",df,aggregation="Hourly"),
                         "22.06 at 15:00")
        self.assertEqual(format_plotted_time("Jun",df,aggregation="Monthly"),"Jun")

    def test_humidity_dew_point_interpretation_is_physical(self):
        df=self.frame()
        fig=go.Figure(go.Scatter(x=[21,173],y=[-12.4,20.6],name="Mean"))
        text=humidity_figure_interpretation(df,fig,"profile",
                   column="dew_point_temperature_c",title="Dew-point temperature · Daily")
        self.assertIn("21.01 (-12.4 °C)",text)
        self.assertIn("22.06 (20.6 °C)",text)
        self.assertIn("reaches saturation",text)
        self.assertIn("condense",text)
        self.assertNotIn("15 °C surface",text)
        self.assertNotIn("moisture accumulation",text)

    def test_temperature_profile_inherits_shared_calendar_dates(self):
        df=self.frame()
        fig=go.Figure(go.Scatter(x=[21,173],y=[-12.4,20.6],name="Mean"))
        note=temperature_figure_interpretation(df,fig,"profile",
             column="dry_bulb_temperature_c",title="Dry-bulb temperature · Daily")
        self.assertIn("21.01",note)
        self.assertIn("22.06",note)
        self.assertNotIn("day-of-year 21",note)

    def test_profile_ticks_and_hover_use_calendar_dates(self):
        df=self.frame()
        for builder in (profile_line_chart,profile_ribbon_chart):
            fig=builder(df,"dew_point_temperature_c","Daily","Dew-point temperature","°C")
            self.assertEqual(str(fig.data[0].x[0]),"1")
            self.assertEqual(fig.layout.xaxis.ticktext[0],"01.01")
            self.assertEqual(fig.layout.xaxis.ticktext[-1],"08.01")
            self.assertIn("Date %{customdata}",fig.data[0].hovertemplate)
            self.assertEqual(fig.data[0].customdata[0],"01.01")
            printed=report_figure(fig,width_pt=550,height_pt=300)
            self.assertEqual(printed.layout.xaxis.ticktext[-1],"08.01")

    def test_hourly_profile_keeps_native_timestamp_and_readable_hover(self):
        df=self.frame()
        fig=profile_line_chart(df,"dew_point_temperature_c","Hourly","Dew-point temperature","°C")
        self.assertEqual(len(fig.data[0].x),len(df))
        self.assertIn("%d.%m at %H:%M",fig.data[0].hovertemplate)


if __name__=="__main__":
    unittest.main()
