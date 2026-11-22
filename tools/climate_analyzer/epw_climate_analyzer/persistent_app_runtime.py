"""R14.3B-C opt-in stable executable namespace.

The app module is imported as code, never recovered from a browser session.
Full runs share one lock because legacy provider adapters temporarily mutate
Streamlit's global surface. This is a transition candidate: callback and
fragment concurrency still require separate admission.
"""
from pathlib import Path
import importlib.util
import sys
from threading import RLock
import os

_NAME="_ige_r143_persistent_app"
_LOCK=RLock()
_MODULE=None
_TOKEN=None

def source_token(path):
    p=Path(path).resolve()
    s=p.stat()
    return (str(p),s.st_ino,s.st_size,s.st_mtime_ns)

def load_app(path):
    global _MODULE,_TOKEN
    with _LOCK:
        token=source_token(path)
        if _MODULE is not None:
            if token!=_TOKEN:raise RuntimeError("Persistent app source changed; restart the candidate runtime")
            return _MODULE
        spec=importlib.util.spec_from_file_location(_NAME,token[0])
        module=importlib.util.module_from_spec(spec)
        sys.modules[_NAME]=module
        try:spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(_NAME,None)
            raise
        _MODULE,_TOKEN=module,token
        return module

def execute(path):
    # Explicit independent qualification: no Degree-days fragment experiment
    # while the full-run serialization boundary is under test.
    if os.environ.get("IGE_R14_DEGREE_FRAGMENT")=="1":
        raise RuntimeError("Persistent app and Degree fragment pilots must be tested separately")
    from .source_parity_runtime import _RUNTIME_PATCH_LOCK
    from .source_parity_streamlit_surface import restore_streamlit_surface
    import streamlit as st
    with _LOCK,_RUNTIME_PATCH_LOCK:
        app=load_app(path)
        # Restrict this candidate to EPW, not provider fragments. Source mode
        # changes are still full reruns, and default production remains intact.
        if (st.session_state.get("active_canonical_climate") is not None or
                st.session_state.get("climate_source_mode","Upload EPW") not in ("Upload EPW",)):
            st.error("R14.3 persistent pilot supports uploaded EPW only. Disable pilot for other sources.")
            st.stop()
        try:app._execute_page()
        finally:restore_streamlit_surface()

def status():
    return {"enabled":os.environ.get("IGE_R143_PERSISTENT_APP")=="1",
            "module_loaded":_MODULE is not None,
            "scope":"Experimental EPW-only shared code module; serialized full runs, not general fragment/callback isolation."}
