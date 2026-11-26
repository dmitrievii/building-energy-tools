"""R2.19 UI state contracts: independent chart controls and service routing."""
from __future__ import annotations

import unittest
from datetime import date
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from epw_climate_analyzer import sidebar_layout as nav
from epw_climate_analyzer import heatmap_controls as hc
from epw_climate_analyzer.heatmap_presentation import (
    TILES, CONTOURS, HYBRID, apply_heatmap_presentation, context_from_state,
)
from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES,NAVIGATION_KEY
from epw_climate_analyzer.chart_presentation import reset_appearance,reset_underlay_position
from epw_climate_analyzer.p6_report_structure import report_figure

def grid(name="Temperature",quantity="dry_bulb_temperature_c",offset=0):
    z=np.add.outer(np.arange(24.),np.arange(12.))+offset
    f=go.Figure(go.Heatmap(x=list(range(1,13)),y=list(range(24)),z=z,
        coloraxis="coloraxis",meta={"heatmap_quantity":quantity,"heatmap_semantics":"continuous"}))
    f.update_layout(title=name,xaxis_title="Month",yaxis_title="Hour of day",
        coloraxis={"colorscale":"Viridis","cmin":0.,"cmax":40.,"colorbar":{"title":"°C"}})
    return f

class R219StateTests(unittest.TestCase):
    def test_all_navigation_pages_have_exactly_one_group(self):
        pages=[p for _,members in nav.grouped_pages(NAVIGATION_PAGES) for p in members]
        self.assertEqual(len(pages),len(set(pages)))
        self.assertEqual(set(pages),set(NAVIGATION_PAGES))
        self.assertEqual(nav.grouped_pages(["Overview","Temperature","Report"]),
            (("Overview",("Overview",)),("Climate",("Temperature",)),("Report",("Report",))))
        state={nav.SERVICE_KEY:True}
        nav.select_page(state,"Temperature")
        self.assertEqual(state[NAVIGATION_KEY],"Temperature")
        self.assertFalse(state[nav.SERVICE_KEY])

    def test_heatmap_semantic_identity_is_data_independent_and_slot_specific(self):
        state={NAVIGATION_KEY:"Temperature",hc.COUNTERS:{}}
        first=hc.chart_key(grid(),state)
        duplicate=hc.chart_key(grid(),state)
        humidity=hc.chart_key(grid("Humidity","relative_humidity_pct"),state)
        self.assertEqual(len({first,duplicate,humidity}),3)
        hc.save_preferences(state,first,{**hc.DEFAULT,"mode":TILES,"labels":False})
        state[hc.COUNTERS]={}
        self.assertEqual(first,hc.chart_key(grid(offset=3),state))
        self.assertEqual(duplicate,hc.chart_key(grid(),state))
        self.assertEqual(hc.get_preferences(state,first)["mode"],TILES)
        self.assertEqual(hc.get_preferences(state,duplicate)["mode"],CONTOURS)
        self.assertEqual(hc.get_preferences(state,humidity)["mode"],CONTOURS)
        self.assertTrue(hc.get_preferences(state,humidity)["labels"])

    def test_preferences_bounded_and_reset_appearance_isolated(self):
        state={"chart_presentation_underlay_enabled":True,
               "chart_presentation_underlay_scale":1.5,
               "chart_presentation_export_scale":3}
        for i in range(hc.MAX_PREFERENCES+3):
            hc.save_preferences(state,str(i),{**hc.DEFAULT,"mode":HYBRID})
        self.assertEqual(len(state[hc.STORE]),hc.MAX_PREFERENCES)
        self.assertNotIn("0",state[hc.STORE])
        before=dict(state[hc.STORE])
        reset_appearance(state)
        self.assertEqual(state[hc.STORE],before)
        self.assertTrue(state["chart_presentation_underlay_enabled"])
        self.assertEqual(state["chart_presentation_underlay_scale"],1.5)
        self.assertEqual(state["chart_presentation_export_scale"],3)
        reset_underlay_position(state)
        self.assertEqual(state["chart_presentation_underlay_scale"],1.)
        self.assertEqual(state[hc.STORE],before)

    def test_filter_state_restores_only_valid_dates_and_isolated_reset(self):
        state={"global_data_range_mode":"Custom",
               "global_data_range_start_date":date(2025,1,1),
               "global_data_range_end_date":date(2026,1,2),
               "global_data_range_year":2025,
               "historical_analysis_clock":"clock",
               "chart_presentation_font_size":21}
        nav.remember_filters(state)
        for key in nav.FILTER_KEYS:state.pop(key,None)
        nav.restore_filters(state)
        self.assertEqual(state["historical_analysis_clock"],"clock")
        self.assertNotIn("global_data_range_start_date",state)
        nav.restore_filters(state,pd.Timestamp("2026-01-01"),pd.Timestamp("2026-12-31"),[2026])
        self.assertNotIn("global_data_range_start_date",state)
        self.assertNotIn("global_data_range_year",state)
        self.assertEqual(state["global_data_range_end_date"],date(2026,1,2))
        nav.reset_filters(state)
        self.assertNotIn(nav.FILTER_STORE,state)
        self.assertEqual(state["chart_presentation_font_size"],21)

    def test_atlas_default_independent_of_previous_global_and_report_retains_contours(self):
        options=context_from_state({"chart_presentation_heatmap_mode":TILES,
                                     "chart_presentation_contour_labels":False})
        self.assertEqual(options["mode"],CONTOURS)
        self.assertTrue(options["labels"])
        f=grid()
        original=np.asarray(f.data[0].z).copy()
        apply_heatmap_presentation(f,**options)
        self.assertEqual(f.data[-1].type,"contour")
        self.assertTrue(f.data[-1].contours.showlabels)
        printed=report_figure(f,width_pt=500,height_pt=300)
        np.testing.assert_array_equal(printed.data[0].z,original)
        self.assertEqual(printed.data[-1].type,"contour")
        self.assertTrue(printed.data[-1].contours.showlabels)

    def test_actual_streamlit_widgets_are_independent_across_reruns(self):
        from streamlit.testing.v1 import AppTest
        source = """
import streamlit as st
import numpy as np
import plotly.graph_objects as go
from epw_climate_analyzer.heatmap_controls import COUNTERS,local_heatmap_settings
from epw_climate_analyzer.heatmap_presentation import apply_heatmap_presentation
st.session_state[COUNTERS]={}
results=[]
for name,quantity in [('Temperature','dry_bulb_temperature_c'),('Humidity','relative_humidity_pct')]:
    fig=go.Figure(go.Heatmap(x=list(range(1,13)),y=list(range(24)),
        z=np.add.outer(np.arange(24.),np.arange(12.)),
        meta={'heatmap_quantity':quantity,'heatmap_semantics':'continuous'},
        colorscale='Viridis',colorbar={'title':'°C'}))
    fig.update_layout(title=name,xaxis_title='Month',yaxis_title='Hour of day')
    settings=local_heatmap_settings(st,fig)
    apply_heatmap_presentation(fig,**settings)
    results.append((settings['mode'],settings['labels'],fig.data[-1].type))
st.session_state['r219_fixture_results']=results
"""
        at=AppTest.from_string(source).run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state["r219_fixture_results"],
                         [(CONTOURS,True,"contour"),(CONTOURS,True,"contour")])
        radios=[r for r in at.radio if r.label=="Heat-map visualization"]
        self.assertEqual(len(radios),2)
        radios[0].set_value(TILES).run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state["r219_fixture_results"],
                         [(TILES,True,"heatmap"),(CONTOURS,True,"contour")])

    def test_service_route_does_not_render_diagnostics_until_requested(self):
        from streamlit.testing.v1 import AppTest
        source="""
import streamlit as st
from epw_climate_analyzer.sidebar_layout import render_service
def diagnostics(st):
    st.write('DIAGNOSTICS_ACTIVE')
    st.session_state['diagnostic_calls']=st.session_state.get('diagnostic_calls',0)+1
if not render_service(st,st.sidebar,diagnostics):
    st.write('ANALYSIS_ACTIVE')
"""
        at=AppTest.from_string(source).run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state.filtered_state.get("diagnostic_calls",0),0)
        at.button(key="_r219_service_button").click().run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state["diagnostic_calls"],1)
        at.button(key="_r219_service_back").click().run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state["diagnostic_calls"],1)

    def test_geosphere_compatibility_wrappers_forward_container_and_prevent_duplicates(self):
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from epw_climate_analyzer import source_parity_fixes as fixes
        clock=Mock(return_value=("clock","Europe/Vienna",1.))
        quality=Mock(return_value="quality")
        parity=SimpleNamespace(_source_parity_unfixed_analysis_clock=clock,
                               _source_parity_unfixed_quality_policy=quality)
        dataset=SimpleNamespace(data=pd.DataFrame())
        dataset.data.attrs["canonical_analysis_timezone_name"]="Europe/Vienna"
        area=object()
        with patch.object(fixes.st,"session_state",{NAVIGATION_KEY:"Temperature"}):
            self.assertEqual(fixes._analysis_clock_without_duplicate_widget(parity,dataset,area),clock.return_value)
            self.assertEqual(fixes._quality_without_duplicate_widget(parity,dataset,area),quality.return_value)
            clock.assert_called_once_with(dataset,area=area)
            quality.assert_called_once_with(dataset,area=area)
        with patch.object(fixes.st,"session_state",{NAVIGATION_KEY:"Compare Climates"}):
            fixes._analysis_clock_without_duplicate_widget(parity,dataset,area)
            fixes._quality_without_duplicate_widget(parity,dataset,area)
            self.assertEqual(clock.call_count,1)
            self.assertEqual(quality.call_count,1)

    def test_group_expansion_survives_reruns_and_tracks_queued_route_changes(self):
        from streamlit.testing.v1 import AppTest
        source="""
import streamlit as st
from epw_climate_analyzer.sidebar_layout import render_navigation
from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES,NAVIGATION_KEY
st.checkbox("Unrelated control",key="unrelated")
page=render_navigation(st,NAVIGATION_PAGES)
st.write(page)
"""
        at=AppTest.from_string(source).run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state[NAVIGATION_KEY],"Overview")
        self.assertEqual(at.session_state[nav.OPEN_GROUPS],())
        at.sidebar.button(key="_r219_group_Climate").click().run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state[nav.OPEN_GROUPS],("Climate",))
        at.checkbox(key="unrelated").check().run(timeout=30)
        self.assertEqual(at.session_state[nav.OPEN_GROUPS],("Climate",))
        at.sidebar.button(key=nav.page_button_key("Precipitation and Snow")).click().run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state[NAVIGATION_KEY],"Precipitation and Snow")
        at.sidebar.button(key="_r219_group_Design").click().run(timeout=30)
        self.assertEqual(at.session_state[nav.OPEN_GROUPS],("Climate","Design"))
        at.sidebar.button(key="_r219_group_Climate").click().run(timeout=30)
        self.assertEqual(at.session_state[nav.OPEN_GROUPS],("Design",))
        at.run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state[nav.OPEN_GROUPS],("Design",))
        self.assertEqual(at.session_state[NAVIGATION_KEY],"Precipitation and Snow")
        self.assertFalse(any(b.key==nav.page_button_key("Precipitation and Snow") for b in at.sidebar.button))
        at.session_state[NAVIGATION_KEY]="Temperature"
        at.run(timeout=30)
        self.assertFalse(list(at.exception))
        self.assertEqual(at.session_state[nav.OPEN_GROUPS],("Climate","Design"))
        self.assertTrue(any(b.key==nav.page_button_key("Temperature") for b in at.sidebar.button))

    def test_explore_owns_comparison_and_quality_and_icons_cover_tree(self):
        groups=dict(nav.grouped_pages(NAVIGATION_PAGES))
        self.assertEqual(groups["Explore"],("Time Series and Overlay","Compare Climates","Data Quality"))
        self.assertNotIn("Compare Climates",groups)
        self.assertNotIn("Data Quality",groups)
        for group,members in groups.items():
            self.assertIn(group,nav.ICONS)
            if group in nav.EXPANDABLE:
                for page in members:self.assertIn(page,nav.ICONS)
