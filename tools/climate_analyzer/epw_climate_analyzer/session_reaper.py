"""R12: close disconnected sessions on the pinned Streamlit event loop.

No reconnection retention. Native close_session owns shutdown, uploads,
media and Streamlit caches. Never close a different active session.
"""
from threading import RLock
from datetime import datetime, timezone
import weakref

_LOCK=RLock()
_STATUS={"status":"not started","expired_reaped":0,"shutdown_failures":0,
         "sweeps":0,"disconnected_sessions":None}
_RUNTIME_REF=None
_INTERVAL=1.
_QUEUE_INTERVAL=30.
_LAST_QUEUE_SAMPLE=0.
RUNTIME_RECOVERY_SCHEMA="MEM-PERF-R12"
_RECOVERY_PENDING=False
_STOPPING_THREADS=weakref.WeakSet()

def _close_on_disconnect(manager,session_id):
    """Called only by Runtime.disconnect_session after its client check."""
    global _RECOVERY_PENDING
    info=manager.get_active_session_info(session_id)
    if info is None:return
    runner=getattr(info.session,"_scriptrunner",None)
    thread=getattr(runner,"_script_thread",None)
    if thread is not None:_STOPPING_THREADS.add(thread)
    from .byte_cache import close_session_caches
    try:
        # Native close never puts this session into reconnect storage.
        manager.close_session(session_id)
    except Exception as exc:
        with _LOCK:_STATUS["shutdown_failures"]+=1
        _set(status="shutdown failed: "+type(exc).__name__)
        raise
    finally:
        close_session_caches(session_id)
        _RECOVERY_PENDING=True
    with _LOCK:
        _STATUS["closed_on_disconnect"]=_STATUS.get("closed_on_disconnect",0)+1

def _install_disconnect_policy(manager):
    if getattr(manager,"_ige_r12_no_reconnect",False):return
    ref=weakref.ref(manager)
    def disconnect(session_id):
        current=ref()
        if current is not None:_close_on_disconnect(current,session_id)
    manager.disconnect_session=disconnect
    manager._ige_r12_no_reconnect=True
    _set(disconnect_policy="native close; no reconnect retention")

def reaper_summary():
    with _LOCK:return {**_STATUS,"allocator_recovery_pending":_RECOVERY_PENDING}

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
    return reaped

def _idle_for_recovery(manager,cache):
    # Only between scripts, after disconnected-session TTL entries expire.
    try:
        return (not any(True for _ in cache) and
                not any(thread.is_alive() for thread in list(_STOPPING_THREADS)) and
                all(info.session._scriptrunner is None and
                    info.session._browser_queue.is_empty()
                    for info in manager.list_active_sessions()))
    except Exception:
        return False

def _recover_if_idle(manager,cache,reaped):
    global _RECOVERY_PENDING
    # Delay a sweep after shutdown; release expired references first.
    if reaped:
        _RECOVERY_PENDING=True
        return
    if not _RECOVERY_PENDING or not _idle_for_recovery(manager,cache):
        return
    from .memory_recovery import recovery_probe
    result=recovery_probe("Disconnected session resources released")
    if result["status"]=="busy export":return
    _RECOVERY_PENDING=False
    _set(last_post_session_recovery=result)
    # An actual zero-active-session sample, not a startup proxy. Different
    # warmed library sets may legitimately have different steady baselines.
    if result.get("status")=="complete" and not manager.list_active_sessions():
        from .byte_cache import session_cache_summary
        _set(last_idle_server_sample={"memory":result["after_trim"],
              "captured_at_utc":result["captured_at_utc"],
              "session_caches":session_cache_summary(),
              "scope":"Warm process after zero-active-session recovery; not a guarantee of reclaimable RSS."})

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
    global _LAST_QUEUE_SAMPLE
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
        _install_disconnect_policy(manager)
        reaped=_expire_storage(manager,storage._cache)
        _recover_if_idle(manager,storage._cache,reaped)
        # Do not continuously traverse message queues at the faster maintenance rate.
        from time import monotonic
        now=monotonic()
        if now-_LAST_QUEUE_SAMPLE>=_QUEUE_INTERVAL:
            _set(forward_queue_sample=_queue_sample(manager))
            _LAST_QUEUE_SAMPLE=now
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
