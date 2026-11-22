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
        return {"status":"sampled","glibc":version().decode("ascii"),
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
