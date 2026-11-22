"""MEM-PERF R6: opt-in session and Streamlit payload counters.

No enumeration or serialization of other sessions, no content, no names or
identifiers. Backend byte counters are optional and describe payload only,
not allocator overhead, websocket buffers or the complete private heap.
"""
from __future__ import annotations
from .session_reaper import ensure_session_reaper,reaper_summary
RUNTIME_SESSION_SCHEMA="MEM-PERF-R7"


def _nonnegative_int(value):
    return value if type(value) is int and value>=0 else None


def _payload_total(provider):
    if provider is None:return None
    try:
        rows=provider.get_stats()
        # Streamlit providers emit a list of CacheStat objects, or a mapping
        # of metric-family name to a sequence (metrics API). Count each
        # returned row once, and inspect only its byte_length field.
        if isinstance(rows,dict):
            rows=[row for family in rows.values() for row in family]
        total=0
        for row in rows:
            n=_nonnegative_int(getattr(row,"byte_length",None))
            if n is None:return None
            total+=n
        return total
    except Exception:return None


def _active_count(runtime):
    try:
        manager=runtime._session_mgr
        count=getattr(manager,"num_active_sessions",None)
        if callable(count):return _nonnegative_int(count())
        rows=manager.get_stats(("active_sessions",)).get("active_sessions",[])
        if len(rows)==1:return _nonnegative_int(rows[0].value)
    except Exception:pass
    return None


def _backend_stats(runtime):
    result={"active_sessions":_active_count(runtime),
            "uploaded_payload_bytes":None,"media_payload_bytes":None}
    try:
        result["uploaded_payload_bytes"]=_payload_total(runtime.uploaded_file_mgr)
    except Exception:pass
    try:
        manager=runtime.media_file_mgr
        result["media_payload_bytes"]=_payload_total(getattr(manager,"_storage",None))
    except Exception:pass
    return result


def inspect_session_counters(state,known_keys=()):
    result={"scope":"Visible keys in current session; aggregate backend payloads and active-session count for this process only.",
            "visible_keys":None,"known_resource_keys_present":None,
            "active_sessions":None,"uploaded_payload_bytes":None,"media_payload_bytes":None}
    try:
        result["visible_keys"]=len(state.keys()) if hasattr(state,"keys") else len(state)
        result["known_resource_keys_present"]=sum(key in state for key in known_keys)
    except Exception:pass
    try:
        from streamlit.runtime import Runtime
        if Runtime.exists():result.update(_backend_stats(Runtime.instance()))
    except Exception:pass
    result["session_reaper"]=reaper_summary()
    try:
        from streamlit.runtime import Runtime
        if Runtime.exists():
            result["lazy_dataframe_sources"]=_nonnegative_int(Runtime.instance().dataframe_source_mgr.get_source_count())
    except Exception:pass
    result["limitations"]="Backend counters can be unavailable. Session reaper counts are last event-loop observations. Payloads are not RSS or complete heap attribution."
    return result
