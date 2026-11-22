"""R7: Streamlit 1.63 expired-disconnect maintenance.

Use only the pinned backend's native TTL expiration on the runtime event
loop. Do not enumerate active session content or shorten reconnection TTL.
Unsupported versions/hosts fail closed. No global state clearing.
"""
from threading import RLock
from datetime import datetime, timezone
import weakref

_LOCK=RLock()
_STATUS={"status":"not started","expired_reaped":0,"shutdown_failures":0,
         "sweeps":0,"disconnected_sessions":None}
_RUNTIME_REF=None
_INTERVAL=30.

def reaper_summary():
    with _LOCK:return dict(_STATUS)

def _set(**kw):
    with _LOCK:_STATUS.update(kw)

def _expire_storage(manager,cache):
    # expire() returns only entries past the storage's own configured TTL.
    expired=cache.expire()
    reaped=failed=0
    for session_id,info in expired:
        if manager.is_active_session(session_id):continue
        try:
            info.session.shutdown()
            reaped+=1
        except Exception:failed+=1
    with _LOCK:
        _STATUS["expired_reaped"]+=reaped
        _STATUS["shutdown_failures"]+=failed
        _STATUS["sweeps"]+=1
        # Count still-valid entries without another expiring operation.
        _STATUS["disconnected_sessions"]=sum(1 for _ in cache)
        _STATUS["status"]="running"

def _queue_sample(manager):
    """Event-loop-only, bounded size observations; no message content exported.

    This is pending ForwardMsg protobuf wire size, not resident memory or
    in-flight websocket data. Never flush or mutate any client queue.
    """
    try:
        from streamlit.runtime.forward_msg_queue import ForwardMsgQueue
        sessions=manager.list_active_sessions()
        total=sampled=wire_bytes=0
        limited=len(sessions)>16
        for info in sessions[:16]:
            queue=info.session._browser_queue
            if type(queue) is not ForwardMsgQueue:
                return {"status":"unsupported forward queue"}
            messages=queue._queue
            total+=len(messages)
            budget=128-sampled
            if len(messages)>budget:limited=True
            for msg in messages[:budget]:
                wire_bytes+=msg.ByteSize()
                sampled+=1
        return {"status":"sampled","captured_at_utc":datetime.now(timezone.utc).isoformat(),
                "active_sessions_sampled":min(len(sessions),16),
                "pending_messages_in_sampled_sessions":total,"messages_sized":sampled,
                "sampled_wire_bytes":wire_bytes,"limited":limited,
                "scope":"Pending active-session forward queues only; excludes websocket buffers, disconnected queues and allocator overhead."}
    except Exception as exc:
        return {"status":"unavailable: "+type(exc).__name__}

def _tick(runtime_ref):
    runtime=runtime_ref()
    if runtime is None:return
    try:
        async_objs=runtime._get_async_objs()
        if async_objs.must_stop.is_set():return
        from streamlit.runtime.memory_session_storage import MemorySessionStorage
        from streamlit.runtime.caching.ttl_cache import TTLCache
        from streamlit.runtime.websocket_session_manager import WebsocketSessionManager
        manager=runtime._session_mgr
        if type(manager) is not WebsocketSessionManager:
            _set(status="unsupported session manager");return
        storage=manager._session_storage
        if type(storage) is not MemorySessionStorage or type(storage._cache) is not TTLCache:
            _set(status="unsupported session storage");return
        _expire_storage(manager,storage._cache)
        _set(forward_queue_sample=_queue_sample(manager))
        async_objs.eventloop.call_later(_INTERVAL,_tick,runtime_ref)
    except Exception as exc:
        _set(status="unavailable: "+type(exc).__name__)

def ensure_session_reaper():
    global _RUNTIME_REF
    try:
        import streamlit
        from streamlit.runtime import Runtime
        if streamlit.__version__!="1.63.0":
            _set(status="unsupported Streamlit version");return
        if not Runtime.exists():return
        runtime=Runtime.instance()
        loop=runtime._get_async_objs().eventloop
        with _LOCK:
            if _RUNTIME_REF is not None and _RUNTIME_REF() is runtime:return
            ref=weakref.ref(runtime)
            loop.call_soon_threadsafe(_tick,ref)
            _RUNTIME_REF=ref
            _STATUS["status"]="scheduled"
    except Exception as exc:
        _set(status="unavailable: "+type(exc).__name__)
