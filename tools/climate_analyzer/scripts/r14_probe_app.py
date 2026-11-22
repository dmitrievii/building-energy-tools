"""Synthetic isolated fixture: native scope, fragment and session lifecycle."""
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx
import r14_probe_runtime as probe

probe.register(get_script_run_ctx().session_id)
probe.full_run()

# Definitions in the script are stable by Streamlit's function-key contract.
@st.cache_resource(scope="session",max_entries=1,on_release=probe.release_payload)
def private_payload():
    return probe.new_payload()

resource=private_payload()
st.title("R14 lifecycle probe")
st.write("Payload bytes:",len(resource.data))

@st.fragment
def control():
    probe.fragment_run()
    value=st.slider("Fragment control",0,10,0)
    st.write("Fragment result:",value)
control()
