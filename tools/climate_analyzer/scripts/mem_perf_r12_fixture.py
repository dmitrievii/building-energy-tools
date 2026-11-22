"""R12 CI fixture: real Streamlit session transport, private data and native shutdown."""
import json
from uuid import uuid4
import streamlit as st
from epw_climate_analyzer import session_reaper as reaper,chart_lifecycle as charts
from epw_climate_analyzer.byte_cache import bounded_cache,session_cache_inventory,session_cache_summary
from epw_climate_analyzer.memory_lifecycle import memory_snapshot,reset_session
from epw_climate_analyzer.memory_recovery import recovery_summary
from epw_climate_analyzer.startup_runtime import ensure_initialized
reaper.ensure_session_reaper()
ensure_initialized()
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from epw_climate_analyzer.chart_presentation import apply_chart_presentation,settings_from_state
@bounded_cache(name="r12_fixture_private",max_bytes=8*1024**2,max_entries=2,scope="session")
def climate(value):
    return pd.DataFrame({"temperature":np.sin(np.arange(8760)/200)+value,
                         "humidity":np.full(8760,65.)})
charts.begin_page(st.session_state)
if "sentinel" not in st.session_state:st.session_state["sentinel"]=uuid4().hex
if st.button("Generate test chart"):st.session_state["generate"]=True
if st.session_state.get("generate"):
    data=climate(1)
    fig=go.Figure(go.Scatter(x=np.arange(len(data)),y=data.temperature))
    apply_chart_presentation(fig,settings_from_state({}))
    charts.register_figure(st.session_state,fig,{},"","test")
    st.plotly_chart(fig,key="chart")
st.text("Sentinel: "+st.session_state["sentinel"])
st.button("Reset test session",on_click=reset_session,args=(st.session_state,))
if st.button("Refresh measurement"):st.session_state["measurement"]=st.session_state.get("measurement",0)+1
st.text("R12:"+json.dumps({"measurement":st.session_state.get("measurement",0),
  "memory":memory_snapshot(),"reaper":reaper.reaper_summary(),"recovery":recovery_summary(),
  "private":session_cache_inventory(st.session_state),"aggregate":session_cache_summary(),
  "charts":charts.chart_lifecycle_summary(st.session_state)}))
