"""MEM-PERF R5 process-owned startup and bounded runtime diagnostics.

Imports are synchronous and idempotent. No climate/network request is made.
Memory differences are sampled process/container observations, not exact
per-library attribution. Deferred stages retry only when raw headroom permits.
"""
from __future__ import annotations
from collections import Counter,deque
from copy import deepcopy
from importlib import import_module,reload
from threading import RLock
from time import monotonic,perf_counter
from types import FunctionType,ModuleType,BuiltinFunctionType,CellType,MappingProxyType
import gc
import sys
import weakref
from .p66_memory import MIB,container_memory

_LOCK=RLock()
_STAGES={}
_EVENTS=deque(maxlen=64)
_SCRIPT_REFS=deque(maxlen=64)
_EVENT_COUNTS=Counter()
_CORE_RESERVE=768*MIB
_UTCI_RESERVE=1536*MIB
_CENSUS_RESERVE=768*MIB

# Order exposes the marginal initialization cost of the principal stacks.
STAGES=(
    ("NumPy and Pandas",("numpy","pandas"),None,_CORE_RESERVE),
    ("Plotly",("plotly.graph_objects","plotly.express","plotly.io"),"plotly",_CORE_RESERVE),
    ("SciPy",("scipy","scipy.interpolate","scipy.optimize"),None,_CORE_RESERVE),
    ("Solar / pvlib",("pvlib",),None,_CORE_RESERVE),
    ("PsychroLib / SI",("epw_climate_analyzer.psychrometrics",),None,_CORE_RESERVE),
    ("Folium",("folium","streamlit_folium"),None,_CORE_RESERVE),
    ("UTCI (conditional)",("pythermalcomfort.models",),"utci",_UTCI_RESERVE),
)

def _sample():
    from .memory_lifecycle import memory_snapshot
    sample=memory_snapshot()
    sample["python_blocks"]=getattr(sys,"getallocatedblocks",lambda:None)()
    sample["module_count"]=len(sys.modules)
    return sample

def _ready(reserve):
    reading=container_memory()
    return reading is None or reading[1]-reading[0]>reserve

def _warmup(name):
    if name=="plotly":
        go=import_module("plotly.graph_objects")
        pio=import_module("plotly.io")
        # Trigger representative validators and JSON serialization once.
        fig=go.Figure(go.Scatter(x=[0,1],y=[0,1]))
        pio.to_json(fig)
    elif name=="utci":
        model=import_module("pythermalcomfort.models").utci
        result=model(tdb=[25.],tr=[25.],v=[1.],rh=[50.],limit_inputs=True,round_output=False)
        if not 24.<float(result.utci[0])<26.:raise RuntimeError("UTCI startup reference check failed.")

def ensure_initialized():
    with _LOCK:
        for label,modules,warmup,reserve in STAGES:
            previous=_STAGES.get(label)
            if previous and previous["status"] in ("ready","already loaded","failed"):continue
            before=_sample()
            loaded=all(name in sys.modules for name in modules)
            if loaded and warmup is None:
                _STAGES[label]={"stage":label,"status":"already loaded","seconds":0.,"before":before,"after":before}
                continue
            if not _ready(reserve):
                _STAGES[label]={"stage":label,"status":"deferred (raw headroom)","seconds":0.,"before":before,"after":before}
                continue
            start=perf_counter()
            status="ready";error=None
            try:
                for name in modules:import_module(name)
                if warmup:_warmup(warmup)
            except Exception as exc:
                status="failed";error=type(exc).__name__+": "+str(exc)[:240]
            after=_sample()
            row={"stage":label,"status":status,"seconds":perf_counter()-start,"before":before,"after":after}
            if error:row["error"]=error
            _STAGES[label]=row
        return deepcopy(list(_STAGES.values()))

def current_runtime_guard():
    """Reload the small compatibility guard only when disk source changes."""
    from pathlib import Path
    from hashlib import sha256
    with _LOCK:
        module=import_module("epw_climate_analyzer.runtime_module_guard")
        current=sha256(Path(module.__file__).read_bytes()).hexdigest()
        if getattr(module,"_RUNTIME_GUARD_SOURCE_SHA256",None)!=current:
            module=reload(module)
        return module

def startup_summary():
    with _LOCK:return deepcopy(list(_STAGES.values()))

def record_event(name,before,after,seconds,**counts):
    with _LOCK:
        _EVENT_COUNTS[name]+=1
        _EVENTS.append({"event":name,"at_monotonic_seconds":monotonic(),"seconds":seconds,
                        "before":before,"after":after,**counts})

def begin_script(fn):
    # Weak references do not themselves prolong previous script lifetimes.
    with _LOCK:_SCRIPT_REFS.append(weakref.ref(fn))
    return perf_counter(),_sample()

def end_script(token,page):
    start,before=token
    record_event("script rerun",before,_sample(),perf_counter()-start,page=str(page)[:80])

def profile_install(fn,*args,**kwargs):
    start=perf_counter();before=_sample()
    try:return fn(*args,**kwargs)
    finally:record_event("source parity installation",before,_sample(),perf_counter()-start)

def runtime_summary():
    with _LOCK:
        return {"startup":deepcopy(list(_STAGES.values())),
                "event_counts":dict(_EVENT_COUNTS),"recent_events":deepcopy(list(_EVENTS)),
                "recent_script_functions_tracked":len(_SCRIPT_REFS),
                "recent_script_functions_still_alive":sum(ref() is not None for ref in _SCRIPT_REFS),
                "gc_counts":list(gc.get_count()),"gc_stats":gc.get_stats(),
                "notes":"Global process observations; overlapping sessions can affect deltas. Weak references cover at most 64 recent script functions, not all live sessions."}

def _census_type_name(typ):
    # Extension types and dynamically constructed classes can have non-string
    # or missing metadata. Never stringify arbitrary metadata objects.
    def metadata(key):
        try:value=type.__getattribute__(typ,key)
        except Exception:return None
        return value[:240] if type(value) is str and value else None
    module=metadata("__module__") or "<unknown module>"
    name=metadata("__qualname__") or metadata("__name__") or "<unknown type>"
    return module+"."+name

# Exact types only: no subclass __sizeof__ hooks and no direct call to
# object.__sizeof__ on arbitrary variable-sized or extension objects.
_CENSUS_MEASURABLE_TYPES=(list,dict,tuple,set,frozenset,bytes,str,bytearray,int,float,
                          bool,type(None),type,FunctionType,ModuleType,
                          BuiltinFunctionType,CellType,MappingProxyType)

def _safe_census_size(obj,bound):
    typ=type(obj)
    if not any(typ is basic for basic in _CENSUS_MEASURABLE_TYPES):return None
    try:
        size=sys.getsizeof(obj)
        if type(size) is int and 0<=size<=bound:return size
    except Exception:pass
    return None

def heap_census():
    """On demand only; bounded output and conservative admission.

    gc.get_objects creates a temporary list per generation. Never run this
    expensive diagnostic automatically or with little raw memory headroom.
    Sizes cover only an explicit allowlist of exact Python builtin types.
    Other objects are counted but not assigned bytes. No object contents or
    identities are returned; the result is not a heap or RSS reconciliation.
    """
    if not _ready(_CENSUS_RESERVE):return {"status":"blocked: insufficient raw headroom"}
    counts=Counter();sizes=Counter();measured=Counter()
    start=perf_counter();before=_sample()
    # Reject nonsensical size results even for allowlisted objects.
    # At most the container limit (or a 1 GiB diagnostic ceiling when unknown).
    bound=before.get("limit") or 1024*MIB
    for generation in (0,1,2):
        if not _ready(_CENSUS_RESERVE):return {"status":"stopped: insufficient raw headroom"}
        objects=gc.get_objects(generation=generation)
        try:
            for obj in objects:
                typ=type(obj)
                name=_census_type_name(typ)
                counts[name]+=1
                size=_safe_census_size(obj,bound)
                if size is not None:
                    sizes[name]+=size
                    measured[name]+=1
            if objects:del obj
        finally:del objects
    top=set(name for name,_ in counts.most_common(25))|set(name for name,_ in sizes.most_common(25))
    total=sum(counts.values());measured_total=sum(measured.values())
    return {"status":"complete","schema":"R5-HF2-safe-shallow-v1","seconds":perf_counter()-start,
            "before":before,"after":_sample(),"tracked_objects":total,
            "size_measured_objects":measured_total,"size_unavailable_objects":total-measured_total,
            "shallow_bytes":sum(sizes.values()),
            "types":[{"type":name,"count":counts[name],"size_measured_count":measured[name],
                      "size_unavailable_count":counts[name]-measured[name],
                      "shallow_bytes":sizes[name] if measured[name] else None}
                     for name in sorted(top,key=lambda n:(-sizes[n],n))],
            "scope":"GC-tracked objects; shallow bytes of allowlisted exact types only. Unmeasured objects are not zero-byte objects. No native allocation or retainer graph attribution."}
