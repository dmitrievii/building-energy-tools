"""R9: best-effort, bounded and non-destructive process allocator observations."""
from __future__ import annotations
from datetime import datetime,timezone
from threading import Lock
from time import perf_counter
import gc
import sys
from . import p66_memory as m

_LOCK=Lock()
_LAST=None
_COUNT=0

def _numeric_limit(value):
    return int(value) if isinstance(value,str) and value.isascii() and value.isdigit() and len(value)<=6 else None

def _arena_origin(initial,current):
    """Only return allowlisted numeric allocator settings, never raw environment."""
    if initial is None:
        return {"arena_max_exec_env":None,"arena_tunable_exec":None,
                "arena_setting_origin":"exec environment unavailable"}
    values={}
    for entry in initial.split(b"\0"):
        key,sep,value=entry.partition(b"=")
        if sep and key in (b"MALLOC_ARENA_MAX",b"GLIBC_TUNABLES"):
            values[key]=value.decode("ascii",errors="replace")
    initial_limit=_numeric_limit(values.get(b"MALLOC_ARENA_MAX"))
    tunables=[v.split("=",1)[1] for v in values.get(b"GLIBC_TUNABLES","").split(":")
              if v.startswith("glibc.malloc.arena_max=")]
    tunable=_numeric_limit(tunables[-1]) if tunables else None
    if tunables:
        origin="exec glibc tunable present; allocator application not independently verified"
    elif initial_limit is not None:
        origin="exec environment requested; allocator application not independently verified"
    elif current is not None:
        origin="runtime environment only; startup application NOT established"
    else:
        origin="no explicit exec arena limit observed"
    return {"arena_max_exec_env":initial_limit,"arena_tunable_exec":tunable,"arena_setting_origin":origin}

def allocator_origin():
    import os
    from pathlib import Path
    current=_numeric_limit(os.environ.get("MALLOC_ARENA_MAX"))
    try:
        with Path("/proc/self/environ").open("rb") as file:
            initial=file.read(2*1024**2+1)
        if len(initial)>2*1024**2 or (initial and not initial.endswith(b"\0")):initial=None
    except OSError:initial=None
    return _arena_origin(initial,current)

def allocator_snapshot():
    """glibc mallinfo2 counters, not a complete Python/native heap census.

    No allocation tracing, arena enumeration, XML dumps or heap traversal.
    glibc counters can omit other arenas and non-glibc allocators; RSS overlaps.
    """
    if sys.platform!="linux":return {"status":"unsupported platform"}
    try:
        import ctypes
        libc=ctypes.CDLL(None)
        version=libc.gnu_get_libc_version
        version.argtypes=[]
        version.restype=ctypes.c_char_p
        fields=("arena","ordblks","smblks","hblks","hblkhd","usmblks","fsmblks","uordblks","fordblks","keepcost")
        class Mallinfo2(ctypes.Structure):
            _fields_=[(name,ctypes.c_size_t) for name in fields]
        fn=libc.mallinfo2
        fn.argtypes=[]
        fn.restype=Mallinfo2
        info=fn()
        import os
        arena_max=os.environ.get("MALLOC_ARENA_MAX","")
        # Record only an allowlisted numeric setting, never environment contents.
        return {"status":"sampled","glibc":version().decode("ascii"),
                "arena_max_env":_numeric_limit(arena_max),**allocator_origin(),
                "free_arena_fraction":float(info.fordblks/info.arena) if info.arena else None,
                "arena_bytes":int(info.arena),"allocated_arena_bytes":int(info.uordblks),
                "free_arena_bytes":int(info.fordblks),"mmap_bytes":int(info.hblkhd),
                "top_releasable_bytes":int(info.keepcost),"free_chunks":int(info.ordblks),
                "scope":"glibc mallinfo2 reported counters only; excludes other allocators and may omit arenas. Values overlap RSS; free bytes are not guaranteed reclaimable."}
    except (AttributeError,OSError,ValueError):return {"status":"unavailable"}

def recovery_summary():
    with _LOCK:
        return {"completed_probes":_COUNT,"last":_LAST}

def recovery_probe(reason):
    """Measure gc and trimming separately. Never drop caches or session data."""
    global _LAST,_COUNT
    if not m.EXPORT_LOCK.acquire(blocking=False):return {"status":"busy export","reason":reason}
    try:
        from .memory_lifecycle import memory_snapshot
        start=perf_counter()
        before=memory_snapshot()
        alloc_before=allocator_snapshot()
        gc_count=gc.collect()
        after_gc=memory_snapshot()
        trimmed=m._trim_allocator()
        after_trim=memory_snapshot()
        result={"status":"complete","reason":reason,"captured_at_utc":datetime.now(timezone.utc).isoformat(),
                "before":before,"after_gc":after_gc,"after_trim":after_trim,
                "allocator_before":alloc_before,"allocator_after":allocator_snapshot(),
                "collected_objects":gc_count,"trim_reported_release":trimmed,"seconds":perf_counter()-start,
                "scope":"Process-wide measured deltas, not exact session ownership; concurrent work can affect samples."}
        with _LOCK:
            _LAST=result
            _COUNT+=1
        return result
    except Exception as exc:
        return {"status":"unavailable: "+type(exc).__name__,"reason":reason}
    finally:
        m.EXPORT_LOCK.release()
