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
RUNTIME_RECOVERY_SCHEMA="MEM-PERF-R13-HF1"
_POLICY_VERSION="r13-hf1"
_TICK_GENERATION_ATTR="_ige_reaper_generation"
_RESET_REQUESTS=set()
# Strong references are limited to closed sessions still awaiting their own
# ScriptRunner termination. Store weak refs to avoid creating new owners.
_RETIRED=[]
_CLOSED_REFS=[]
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
    # Direct close policy owns shutdown accounting when installed.
    if getattr(manager,"_ige_r12_hf1_close",False) is True:
        manager.close_session(session_id)
    else:
        from .byte_cache import close_session_caches
        try:manager.close_session(session_id)
        finally:
            close_session_caches(session_id)
            _RECOVERY_PENDING=True
    with _LOCK:
        _STATUS["closed_on_disconnect"]=_STATUS.get("closed_on_disconnect",0)+1

def _install_disconnect_policy(manager):
    # Instance-bound closures from older code survive importlib.reload.
    # Replace them from the pinned class implementation, not from another
    # wrapper. A boolean marker alone cannot establish current ownership.
    installed=getattr(manager,"_ige_policy_version",None)
    if (installed==_POLICY_VERSION and
            getattr(manager.close_session,"_ige_policy_version",None)==_POLICY_VERSION and
            getattr(manager.disconnect_session,"_ige_policy_version",None)==_POLICY_VERSION):
        _set(policy_version=_POLICY_VERSION,policy_verified=True)
        return
    ref=weakref.ref(manager)
    original_close=type(manager).close_session.__get__(manager,type(manager))
    if installed or getattr(manager,"_ige_r12_hf1_close",False):
        with _LOCK:_STATUS["policy_replacements"]=_STATUS.get("policy_replacements",0)+1
    def close(session_id):
        global _RECOVERY_PENDING
        current=ref()
        if current is None:return
        info=current.get_active_session_info(session_id)
        if info is None:return original_close(session_id)
        session=info.session
        runner=getattr(session,"_scriptrunner",None)
        thread=getattr(runner,"_script_thread",None)
        if thread is not None:
            _STOPPING_THREADS.add(thread)
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            ctx=get_script_run_ctx(thread,suppress_warning=True)
            if ctx is not None:ctx._ige_session_closed=True
        try:_CLOSED_REFS.append(weakref.ref(session))
        except TypeError:pass
        del _CLOSED_REFS[:-128]
        try:_RETIRED.append((weakref.ref(session),weakref.ref(thread) if thread is not None else None))
        except TypeError:pass
        from .byte_cache import close_session_caches
        try:original_close(session_id)
        except Exception as exc:
            with _LOCK:_STATUS["shutdown_failures"]+=1
            _set(last_shutdown_error=type(exc).__name__)
            raise
        finally:
            close_session_caches(session_id)
            _RECOVERY_PENDING=True
        with _LOCK:
            _STATUS["native_closes"]=_STATUS.get("native_closes",0)+1
            if session_id in _RESET_REQUESTS:
                _RESET_REQUESTS.discard(session_id)
                _STATUS["native_resets"]=_STATUS.get("native_resets",0)+1
                _STATUS["last_reset_status"]="old AppSession closed after browser reload"
    close._ige_policy_version=_POLICY_VERSION
    manager.close_session=close
    manager._ige_r12_hf1_close=True
    def disconnect(session_id):
        current=ref()
        if current is not None:
            with _LOCK:_STATUS["disconnect_events"]=_STATUS.get("disconnect_events",0)+1
            _close_on_disconnect(current,session_id)
    disconnect._ige_policy_version=_POLICY_VERSION
    manager.disconnect_session=disconnect
    manager._ige_r12_no_reconnect=True
    manager._ige_policy_version=_POLICY_VERSION
    _set(policy_version=_POLICY_VERSION,policy_verified=True,
         disconnect_policy="native close; no reconnect retention; versioned direct close")

def request_native_reset():
    """Record the current connection's reset, then let the browser reload.

    Streamlit's WS reconnect can replay browser widget state or omit a rerun.
    A real document reload prevents both cases. The existing native disconnect
    policy destroys the old AppSession, never the server. No user-provided JS.
    """
    import streamlit
    from streamlit.runtime import Runtime
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    ctx=get_script_run_ctx(suppress_warning=True)
    if streamlit.__version__!="1.63.0" or ctx is None or not Runtime.exists():
        return False
    runtime=Runtime.instance()
    if getattr(runtime._session_mgr,"_ige_policy_version",None)!=_POLICY_VERSION:return False
    session_id=ctx.session_id
    loop=runtime._get_async_objs().eventloop
    def expire_request():
        if session_id in _RESET_REQUESTS:
            _RESET_REQUESTS.discard(session_id)
            with _LOCK:_STATUS["reset_failures"]=_STATUS.get("reset_failures",0)+1
            _set(last_reset_status="browser reload not observed; reload manually")
    def mark():
        if not runtime._session_mgr.is_active_session(session_id):return
        _RESET_REQUESTS.add(session_id)
        with _LOCK:_STATUS["reset_requests"]=_STATUS.get("reset_requests",0)+1
        loop.call_later(15.,expire_request)
    loop.call_soon_threadsafe(mark)
    return True

def _finalize_retired(manager):
    """Only clear native payloads once their closed session has stopped."""
    from streamlit.runtime.app_session import AppSessionState
    pending=[]
    for session_ref,thread_ref in _RETIRED:
        session=session_ref()
        thread=thread_ref() if thread_ref is not None else None
        if session is None:continue
        if thread is not None and thread.is_alive():
            pending.append((session_ref,thread_ref));continue
        if manager.is_active_session(session.id):
            continue
        if session._state is not AppSessionState.SHUTDOWN_REQUESTED or session._scriptrunner is not None:
            pending.append((session_ref,thread_ref));continue
        # Native shutdown already cleared user-upload/media caches; purge
        # only the dead session's retained widget state and pending messages.
        try:
            session.session_state.clear()
            session._browser_queue.clear()
            session._client_state.Clear()
            for task in tuple(session._background_tasks):task.cancel()
            with _LOCK:_STATUS["retired_payloads_cleared"]=_STATUS.get("retired_payloads_cleared",0)+1
        except Exception as exc:
            with _LOCK:_STATUS["retired_clear_failures"]=_STATUS.get("retired_clear_failures",0)+1
            _set(last_retired_clear_error=type(exc).__name__)
    _RETIRED[:]=pending

def retired_reference_summary():
    """On-demand only: bounded immediate referrer types of retired AppSessions."""
    import gc
    from collections import Counter
    observations=[]
    for ref in tuple(_CLOSED_REFS)[-8:]:
        obj=ref()
        if obj is None:continue
        counts=Counter(type(owner).__module__+"."+type(owner).__name__ for owner in gc.get_referrers(obj))
        observations.append(dict(counts.most_common(12)))
        del obj
    return {"sampled":len(observations),"immediate_referrer_types":observations,
            "scope":"On-demand immediate GC-tracked referrer type counts; diagnostic frames may appear. No object contents or user IDs."}

def reaper_summary():
    with _LOCK:return {**_STATUS,"allocator_recovery_pending":_RECOVERY_PENDING,
        "closed_session_refs_tracked":len(_CLOSED_REFS),
        "closed_session_refs_alive":sum(ref() is not None for ref in _CLOSED_REFS)}

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
    if not _RECOVERY_PENDING or _RETIRED or not _idle_for_recovery(manager,cache):
        return
    # Only when no session can use the composed wrappers. Restore the
    # shared pristine binding snapshot, not the scientific library imports.
    if not manager.list_active_sessions():
        import sys
        parity=sys.modules.get("epw_climate_analyzer.source_parity_runtime")
        release=getattr(parity,"release_idle_bindings",None)
        if callable(release):release()
    from .memory_recovery import recovery_probe
    result=recovery_probe("Disconnected session resources released")
    if result["status"]=="busy export":return
    _RECOVERY_PENDING=False
    _set(last_post_session_recovery=result)
    # An actual zero-active-session sample, not a startup proxy. Different
    # warmed library sets may legitimately have different steady baselines.
    if result.get("status")=="complete" and not manager.list_active_sessions():
        from .byte_cache import session_cache_summary
        from .epw_lifecycle import lifecycle_summary
        _set(last_idle_server_sample={"memory":result["after_trim"],
              "captured_at_utc":result["captured_at_utc"],
              "session_caches":session_cache_summary(),
              "closed_session_refs_alive":sum(ref() is not None for ref in _CLOSED_REFS),
              "epw_lifecycle":lifecycle_summary(),
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

def _tick(runtime_ref,generation=None):
    global _LAST_QUEUE_SAMPLE
    runtime=runtime_ref()
    if runtime is None or generation is None or getattr(runtime,_TICK_GENERATION_ATTR,None) is not generation:return
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
        _finalize_retired(manager)
        _set(active_sessions=len(manager.list_active_sessions()),
             pending_retired_finalization=len(_RETIRED),
             stopping_script_threads=sum(t.is_alive() for t in list(_STOPPING_THREADS)))
        reaped=_expire_storage(manager,storage._cache)
        _recover_if_idle(manager,storage._cache,reaped)
        # Do not continuously traverse message queues at the faster maintenance rate.
        from time import monotonic
        now=monotonic()
        if now-_LAST_QUEUE_SAMPLE>=_QUEUE_INTERVAL:
            _set(forward_queue_sample=_queue_sample(manager))
            _LAST_QUEUE_SAMPLE=now
        async_objs.eventloop.call_later(_INTERVAL,_tick,runtime_ref,generation)
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
            # One active generation per Runtime, including after module reload.
            generation=object()
            def activate():
                setattr(runtime,_TICK_GENERATION_ATTR,generation)
                _tick(ref,generation)
            loop.call_soon_threadsafe(activate)
            _RUNTIME_REF=ref
            _STATUS["status"]="scheduled"
    except Exception as exc:
        _set(status="unavailable: "+type(exc).__name__)
