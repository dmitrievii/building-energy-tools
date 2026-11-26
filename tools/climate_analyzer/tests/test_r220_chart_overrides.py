"""R2.20 chart-local overrides preserve values and physical axis contracts."""
from __future__ import annotations

import unittest
import plotly.graph_objects as go
from epw_climate_analyzer import chart_overrides as co
from epw_climate_analyzer.chart_presentation import settings_from_state
from epw_climate_analyzer.p6_report_structure import report_figure

def figure(title="Outdoor temperature"):
    return go.Figure(go.Scatter(x=[1,2,3],y=[12,15,19],name="Temperature"),
                     layout=dict(title=title,xaxis_title="Sample",yaxis_title="Temperature [°C]"))

class ChartOverrideTests(unittest.TestCase):
    def test_identity_data_independent_and_distinct_duplicate_charts(self):
        state={"climate_analyzer_navigation":"Temperature"}
        f=figure()
        a=co.chart_identity(f,state)
        b=co.chart_identity(figure(),state)
        self.assertNotEqual(a,b)
        state[co.COUNTERS]={}
        f.data[0].y=[2,4,8]
        self.assertEqual(co.chart_identity(f,state),a)

    def test_local_edit_and_report_preserve_original_values(self):
        f=figure()
        other=figure()
        prefs={"title":"Winter conditions","legend_title":"Series",
               "axes":{"yaxis":{"title":"Air temperature [°C]","range":[0,25],"tick":5}}}
        co.bind_chart_overrides(f,prefs)
        self.assertEqual(f.layout.title.text,"Winter conditions")
        self.assertEqual(f.layout.yaxis.title.text,"Air temperature [°C]")
        self.assertEqual(tuple(f.layout.yaxis.range),(0,25))
        self.assertEqual(f.layout.yaxis.dtick,5)
        self.assertEqual(tuple(f.data[0].y),(12,15,19))
        self.assertEqual(f.data[0].name,"Temperature")
        self.assertEqual(other.layout.title.text,"Outdoor temperature")
        self.assertIsNone(other.layout.yaxis.range)
        printed=report_figure(f,width_pt=500,height_pt=300)
        self.assertEqual(printed.layout.yaxis.title.text,"Air temperature [°C]")
        self.assertEqual(tuple(printed.layout.yaxis.range),(0,25))
        self.assertEqual(tuple(printed.data[0].y),(12,15,19))
        self.assertEqual(f.layout.title.text,"Winter conditions")
        co.restore_canonical_labels(f)
        self.assertEqual(f.layout.title.text,"Outdoor temperature")
        co.replay_chart_overrides(f)
        self.assertEqual(f.layout.title.text,"Winter conditions")

    def test_scientific_scale_protections_and_invalid_bounds(self):
        f=figure()
        for case in ("date","category","fixed","anchor","calendar","heatmap","3d"):
            with self.subTest(case=case):
                g=figure()
                if case=="date":g.data[0].x=["2026-01-01","2026-02-01","2026-03-01"];g.update_xaxes(type="date")
                elif case=="category":g.data[0].x=["A","B","C"];g.update_xaxes(type="category")
                elif case=="fixed":g.update_layout(meta={"fixed_physical_axis_relationship":True})
                elif case=="anchor":g.update_yaxes(scaleanchor="x")
                elif case=="calendar":g.update_xaxes(title_text="Month")
                elif case=="heatmap":g=go.Figure(go.Heatmap(z=[[1,2],[3,4]],x=[1,2],y=[1,2]))
                elif case=="3d":g=go.Figure(go.Scatter3d(x=[1,2],y=[1,2],z=[1,2]))
                self.assertFalse(co.range_allowed(g,"xaxis"))
                co.apply_chart_overrides(g,{"axes":{"xaxis":{"range":[0,5],"tick":1}}})
                self.assertIsNone(g.layout.xaxis.range)
        co.apply_chart_overrides(f,{"axes":{"yaxis":{"range":[30,0],"tick":1}}})
        self.assertIsNone(f.layout.yaxis.range)
        co.apply_chart_overrides(f,{"axes":{"yaxis":{"range":[0,30],"tick":.00001}}})
        self.assertEqual(tuple(f.layout.yaxis.range),(0,30))
        self.assertIsNone(f.layout.yaxis.dtick)

    def test_obsolete_global_ranges_are_ignored_and_reset_is_local(self):
        s=settings_from_state({"chart_presentation_axis_title":"Air temperature",
                               "chart_presentation_axis_min":-40,"chart_presentation_axis_max":60})
        self.assertEqual(s.axis_title,"")
        state={}
        co._remember(state,"a",{"title":"A"})
        co._remember(state,"b",{"title":"B"})
        co.reset_editor(state,"a")
        self.assertEqual(state[co.STORE],{"b":{"title":"B"}})

    def test_actual_streamlit_editor_is_lazy_and_independent(self):
        from streamlit.testing.v1 import AppTest
        source="""
import streamlit as st
import plotly.graph_objects as go
from epw_climate_analyzer.chart_overrides import render_chart_editor
titles=[]
for key in ('a','b'):
    f=go.Figure(go.Scatter(x=[1,2],y=[3,4]),layout={'title':key,'yaxis_title':'Temperature'})
    render_chart_editor(st,f,key)
    titles.append(f.layout.title.text)
st.session_state['titles']=titles
"""
        at=AppTest.from_string(source).run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertFalse(list(at.text_input))
        at.button(key="_r220_toggle_a").click().run(timeout=30)
        self.assertFalse(list(at.exception))
        at.text_input(key="_r220_edit_a_title").set_value("Custom A").run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state["titles"],["Custom A","b"])
        at.button(key="_r220_toggle_b").click().run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state["titles"],["Custom A","b"])
        at.text_input(key="_r220_edit_b_title").set_value("Custom B").run(timeout=30)
        self.assertEqual(at.session_state["titles"],["Custom A","Custom B"])
        at.button(key="_r220_edit_b_reset").click().run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state["titles"],["Custom A","b"])
