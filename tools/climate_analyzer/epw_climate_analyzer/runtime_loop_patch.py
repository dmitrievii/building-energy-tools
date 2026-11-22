"""Startup-only correction for Streamlit 1.63.0's retained loop locals.

Never mutate a suspended coroutine frame or patch an already running Runtime.
The normal managed deployment calls this before constructing Runtime.
"""
import inspect
import textwrap

_MARKER="        # Yield briefly between session message flushing cycles.\n"
_BEFORE="        for active_session_info in self._session_mgr.list_active_sessions():\n"

def patched_source(source):
    # Exact anchors in the dedented 1.63.0 implementation.
    marker="                # Yield briefly between session message flushing cycles.\n"
    before="                for active_session_info in self._session_mgr.list_active_sessions():\n"
    # Dedented method has 16 spaces at the flush branch. Fail closed if upstream
    # has changed rather than applying an approximate transformation.
    if source.count(marker)!=1 or source.count(before)!=1 or source.index(before)>source.index(marker):
        raise RuntimeError("Unsupported Streamlit runtime loop source")
    return source.replace(marker,
        "                active_session_info = msg_list = msg = None\n"+marker,1)

def install_before_runtime():
    import streamlit
    from streamlit.runtime.runtime import Runtime
    if streamlit.__version__!="1.63.0" or Runtime.exists():
        raise RuntimeError("Runtime loop correction requires fresh Streamlit 1.63.0")
    old=Runtime._loop_coroutine
    if getattr(old,"_ige_hf2_loop",False):return
    source=textwrap.dedent(inspect.getsource(old))
    # The source remains in the pinned dependency; no user code interpolated.
    namespace={}
    exec(compile(patched_source(source),inspect.getsourcefile(old) or "<streamlit-runtime>","exec"),old.__globals__,namespace)
    replacement=namespace["_loop_coroutine"]
    replacement.__qualname__=old.__qualname__
    replacement._ige_hf2_loop=True
    Runtime._loop_coroutine=replacement

def status():
    import sys
    module=sys.modules.get("streamlit.runtime.runtime")
    runtime=getattr(module,"Runtime",None)
    return {"startup_loop_patch":bool(getattr(getattr(runtime,"_loop_coroutine",None),"_ige_hf2_loop",False)),
            "scope":"Startup-only managed-launcher correction; direct platform launch uses upstream runtime."}
