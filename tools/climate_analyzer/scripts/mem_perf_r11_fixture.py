"""Real Streamlit runtime fixture; intentionally accelerated TTL only in CI.
This is NOT the full Climate Analyzer app or production configuration.
"""
import json
import streamlit as st
import plotly.graph_objects as go
from epw_climate_analyzer import session_reaper as reaper,chart_lifecycle as charts
from epw_climate_analyzer.memory_lifecycle import memory_snapshot
from epw_climate_analyzer.memory_recovery import recovery_summary
from epw_climate_analyzer.chart_presentation import apply_chart_presentation,settings_from_state

reaper._INTERVAL=.25
reaper.ensure_session_reaper()
charts.begin_page(st.session_state)
st.session_state.setdefault("sentinel","preserved")
if st.checkbox("Generate test chart",key="generate"):
    fig=go.Figure(go.Scatter(x=list(range(8760)),y=list(range(8760))))
    apply_chart_presentation(fig,settings_from_state({}))
    charts.register_figure(st.session_state,fig,{},"","test")
    st.plotly_chart(fig,key="chart")
st.text("Sentinel: "+st.session_state["sentinel"])
st.button("Refresh measurement")
st.text("R11:"+json.dumps({"memory":memory_snapshot(),"reaper":reaper.reaper_summary(),
                          "recovery":recovery_summary(),"charts":charts.chart_lifecycle_summary(st.session_state)}))
