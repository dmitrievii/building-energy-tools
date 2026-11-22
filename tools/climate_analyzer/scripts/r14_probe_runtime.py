"""Isolated R14 experiment, never imported by production app.py.

The monitor emits only counts, lifecycle states and owner types to a local
CI evidence file. It does not retain sessions or inspect user content.
"""
import gc
import json
import os
from pathlib import Path
import time
import tracemalloc
import types
import weakref
from threading import RLock
from streamlit.runtime import Runtime

_LOCK=RLock()
_SESSIONS={}
_PAYLOADS={}
_RELEASES=0
_FULL_RUNS=0
_FRAGMENT_RUNS=0
_INSTALLED=False
_MODE=os.environ.get("R14_MODE","native")
_FILE=Path(os.environ["R14_PROBE_FILE"])

class Payload:
    def __init__(self):
        self.data=bytearray(8*1024*1024)
        # Touch all pages so the allocation is resident.
        for i in range(0,len(self.data),4096):self.data[i]=1

def new_payload():
    obj=Payload()
    with _LOCK:_PAYLOADS[id(obj)]=weakref.ref(obj)
    return obj

def release_payload(obj):
    global _RELEASES
    obj.data.clear()
    with _LOCK:_RELEASES+=1

def full_run():
    global _FULL_RUNS
    with _LOCK:_FULL_RUNS+=1

def fragment_run():
    global _FRAGMENT_RUNS
    with _LOCK:_FRAGMENT_RUNS+=1

def _session_observation(ref):
    obj=ref()
    if obj is None:return {"alive":False}
    holders=set()
    for wrapper in gc.get_referrers(obj):
        if type(wrapper).__name__ not in ("SessionInfo","ActiveSessionInfo"):continue
        for owner in gc.get_referrers(wrapper):
            if isinstance(owner,types.CoroutineType):holders.add("coroutine:"+owner.cr_code.co_name)
            elif isinstance(owner,types.FrameType):holders.add("frame:"+owner.f_code.co_name)
            elif isinstance(owner,dict):holders.add("dict")
    return {"alive":True,"state":str(obj._state.name),"holders":sorted(holders)}

def _rss():
    result={}
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(("VmRSS:","RssAnon:","RssFile:")):
            key,value=line.split(":",1)
            result[key]=int(value.split()[0])*1024
    return result

def _sample(ref):
    rt=ref()
    if rt is None:return
    try:
        manager=rt._session_mgr
        gc.collect()
        with _LOCK:
            tracked=[_session_observation(r) for r in _SESSIONS.values()]
            payloads_alive=sum(r() is not None for r in _PAYLOADS.values())
            counts={"full_runs":_FULL_RUNS,"fragment_runs":_FRAGMENT_RUNS,"release_calls":_RELEASES}
        storage=manager._session_storage._cache
        # Never call expire() here: native TTL behavior is under test.
        valid_count=sum(1 for _ in storage)
        physical_count=len(storage._data)
        result={"mode":_MODE,"version":__import__("streamlit").__version__,
                "sample_ns":time.monotonic_ns(),"active_count":len(manager.list_active_sessions()),
                "storage_valid_count":valid_count,"storage_physical_count":physical_count,
                "sessions":tracked,"payloads_alive":payloads_alive,**counts,
                "rss":_rss(),"python_trace_current_peak":list(tracemalloc.get_traced_memory()) if tracemalloc.is_tracing() else None,
                "loop_patch":bool(getattr(type(rt)._loop_coroutine,"_ige_r14_probe",False))}
        tmp=_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(result),encoding="utf-8")
        tmp.replace(_FILE)
    except Exception as exc:
        _FILE.write_text(json.dumps({"error":type(exc).__name__+": "+str(exc)[:300]}),encoding="utf-8")
    finally:
        rt._get_async_objs().eventloop.call_later(1.,_sample,ref)

def register(session_id):
    rt=Runtime.instance()
    loop=rt._get_async_objs().eventloop
    def init():
        global _INSTALLED
        manager=rt._session_mgr
        info=manager.get_active_session_info(session_id)
        if info is not None:
            with _LOCK:_SESSIONS.setdefault(session_id,weakref.ref(info.session))
        if _INSTALLED:return
        if _MODE in ("close","close-loop"):
            native_close=manager.close_session
            def disconnect(sid):
                native_close(sid)
            manager.disconnect_session=disconnect
        _INSTALLED=True
        loop.call_later(1.,_sample,weakref.ref(rt))
    loop.call_soon_threadsafe(init)
