"""Regression tests for the unified wind rose and independent temporal filters."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

import numpy as np
import pandas as pd
from epw_climate_analyzer.wind_rose_selection import available_wind_months, select_wind_rose_period
from epw_climate_analyzer.charts import wind_rose_chart


def fixture():
    idx = pd.to_datetime(["2025-06-01 06:50","2025-06-01 07:00","2025-06-01 19:50",
                          "2025-06-01 20:00","2025-07-01 06:50","2025-07-01 07:00",
                          "2026-06-01 20:00"])
    df = pd.DataFrame({"month_index": idx.month,"hour_of_day":idx.hour,
                       "wind_speed_m_s":[1.,2.,3.,4.,5.,6.,7.],
                       "wind_direction_deg":[0.,45.,90.,135.,180.,225.,270.],
                       "wind_gust_speed_m_s":[8.,9.,10.,11.,12.,13.,14.],
                       "wind_gust_direction_deg":[270.,225.,180.,135.,90.,45.,0.]},
                       index=idx)
    df.attrs["canonical_native_interval_minutes"] = 10
    return df


class WindRoseSelectionTests(unittest.TestCase):
    def test_annual_and_month_day_night_intersection(self):
        df=fixture()
        self.assertEqual(available_wind_months(df),[6,7])
        pd.testing.assert_frame_equal(select_wind_rose_period(df),df)
        for month, indices in ((None,[0,1,2,3,4,5,6]),(6,[0,1,2,3,6]),(7,[4,5])):
            annual=select_wind_rose_period(df,month=month)
            pd.testing.assert_frame_equal(annual,df.iloc[indices])
            day=select_wind_rose_period(df,month=month,period="Day")
            night=select_wind_rose_period(df,month=month,period="Night")
            self.assertEqual(len(day)+len(night),len(annual))
            self.assertTrue(day.index.intersection(night.index).empty)
            self.assertTrue(day["hour_of_day"].between(7,19).all())
            self.assertTrue((~night["hour_of_day"].between(7,19)).all())
            for subset in (day,night):
                self.assertEqual(subset.attrs,df.attrs)
                for speed,direction in (("wind_speed_m_s","wind_direction_deg"),
                                         ("wind_gust_speed_m_s","wind_gust_direction_deg")):
                    fig=wind_rose_chart(subset,speed_column=speed,direction_column=direction)
                    self.assertAlmostEqual(sum(np.nansum(t.r) for t in fig.data),len(subset)/6)
        self.assertEqual(len(select_wind_rose_period(df,month=6,period="Day")),2)
        self.assertEqual(len(select_wind_rose_period(df,period="Night")),4)

    def test_missing_clock_hours_excluded_and_empty_month(self):
        df=fixture()
        df.loc[df.index[0],"hour_of_day"]=np.nan
        self.assertEqual(len(select_wind_rose_period(df,period="Night")),3)
        self.assertEqual(len(select_wind_rose_period(df,period="Day")),3)
        self.assertTrue(select_wind_rose_period(df,month=1).empty)
        pd.testing.assert_index_equal(select_wind_rose_period(df.drop(columns=["month_index","hour_of_day"]),
                                                             month=6,period="Day").index,df.index[[1,2]])

    def test_legacy_cadence_is_inferred_before_day_night_filtering(self):
        idx=pd.date_range("2025-06-01",periods=48,freq="h")
        df=pd.DataFrame({"wind_speed_m_s":2.,"wind_direction_deg":180.},index=idx)
        night=select_wind_rose_period(df,period="Night")
        self.assertEqual(night.attrs["canonical_native_interval_minutes"],60.)
        fig=wind_rose_chart(night)
        self.assertAlmostEqual(sum(np.nansum(t.r) for t in fig.data),22.)

    def test_actual_wind_widgets_and_histogram_route(self):
        from streamlit.testing.v1 import AppTest
        source=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="render_wind")
        renderer=ast.get_source_segment(source,node)
        generic=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="render_generic_variable_page")
        self.assertIn('elif chart_type == "Histogram":',ast.get_source_segment(source,generic))
        script="""
import pandas as pd
import streamlit as st
from epw_climate_analyzer.charts import wind_rose_chart
MONTHS={"Jun":6,"Jul":7}
WIND_DIRECTION_FROM_NOTE="Wind direction FROM"
index=pd.to_datetime(["2025-06-01 06:00","2025-06-01 07:00","2025-07-01 19:00","2025-07-01 20:00"])
df=pd.DataFrame({"month_index":index.month,"hour_of_day":index.hour,"wind_speed_m_s":[1.,2.,3.,4.],
                 "wind_direction_deg":[0.,90.,180.,270.],"wind_gust_speed_m_s":[5.,6.,7.,8.],
                 "wind_gust_direction_deg":[270.,180.,90.,0.]},index=index)
df.attrs["canonical_native_interval_minutes"]=60
def render_generic_variable_page(*args):
    st.write("Explorer")
def wind_interpretation(df):
    return "Selected records"
def render_plot(fig,text):
    st.session_state["test_hours"]=sum(sum(float(v) for v in t.r) for t in fig.data)
    st.session_state["test_title"]=fig.layout.title.text
    st.session_state["test_trace_count"]=len(fig.data)
    st.plotly_chart(fig,key="wind_test")
"""
        app=AppTest.from_string(script+"\n"+renderer+"\nrender_wind(df)",default_timeout=45).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="wind_analysis_type").options,["Wind variable explorer","Wind rose","Directional statistics"])
        app.selectbox(key="wind_analysis_type").set_value("Wind rose").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="wind_rose_aggregation").value,"Annual")
        self.assertFalse(app.checkbox(key="wind_rose_daynight").value)
        self.assertEqual(app.session_state["test_hours"],4.)
        self.assertEqual(app.selectbox(key="wind_rose_representation").value,"Class distribution")
        self.assertEqual(app.session_state["test_trace_count"],7)
        app.selectbox(key="wind_rose_aggregation").set_value("Monthly").run()
        app.selectbox(key="wind_month").set_value("Jun").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["test_hours"],2.)
        app.checkbox(key="wind_rose_daynight").set_value(True).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["test_hours"],1.)
        self.assertIn("Jun · Day",app.session_state["test_title"])
        app.radio(key="wind_daynight_period").set_value("Night").run()
        app.selectbox(key="wind_rose_aggregation").set_value("Annual").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["test_hours"],2.)
        self.assertIn("Annual · Night",app.session_state["test_title"])
        app.selectbox(key="wind_paired_dataset").set_value("Maximum gust").run()
        self.assertFalse(app.exception)
        self.assertIn("Maximum gust",app.session_state["test_title"])
        app.checkbox(key="wind_rose_daynight").set_value(False).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["test_hours"],4.)


if __name__ == "__main__":
    unittest.main()
