"""Conservative Linux container memory admission; no claim of OOM immunity."""
from pathlib import Path
import gc
from threading import Lock

EXPORT_LOCK=Lock()

MIB=1024**2
def _memory_reading():
    """Return current usage, finite limit and the matching cgroup directory."""
    candidates=[(Path("/sys/fs/cgroup/memory.current"),Path("/sys/fs/cgroup/memory.max")),
                (Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"),Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))]
    # On hosts exposing a nested cgroup, examine the process's own group.
    try:
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            _,controllers,relative=line.split(":",2)
            group=relative.lstrip("/")
            if ".." in Path(group).parts:continue
            if not controllers:
                root=Path("/sys/fs/cgroup")/group
                candidates.insert(0,(root/"memory.current",root/"memory.max"))
            elif "memory" in controllers.split(","):
                root=Path("/sys/fs/cgroup/memory")/group
                candidates.insert(0,(root/"memory.usage_in_bytes",root/"memory.limit_in_bytes"))
    except (OSError,ValueError):pass
    readings=[]
    for usage,limit in candidates:
        try:
            used=int(usage.read_text().strip());cap=int(limit.read_text().strip())
            if 0<cap<2**60 and used>=0:readings.append((used,cap,usage.parent))
        except (ValueError,OSError):continue
    return min(readings,key=lambda pair:pair[1]-pair[0]) if readings else None

def container_memory():
    value=_memory_reading()
    return value[:2] if value else None

def _pressure_details():
    reading=_memory_reading()
    if reading is None:return ""
    try:
        records=dict(line.split() for line in (reading[2]/"memory.stat").read_text().splitlines())
        parts=[]
        for key,aliases in (("anonymous",("anon","total_rss","rss")),("file",("file","total_cache","cache")),("shared memory",("shmem","total_shmem")),("inactive file",("inactive_file","total_inactive_file"))):
            for alias in aliases:
                if alias in records:
                    parts.append(f"{key} {int(records[alias])/MIB:.0f} MiB");break
        return " Cgroup composition: "+", ".join(parts)+"." if parts else ""
    except (OSError,ValueError):return ""

def _trim_allocator():
    # Linux/glibc may retain freed Python/native heap pages. This is best-effort
    # and the hard guard always re-reads actual cgroup use afterwards.
    import sys
    if sys.platform!="linux":return
    try:
        import ctypes
        trim=ctypes.CDLL(None).malloc_trim
        trim.argtypes=[ctypes.c_size_t];trim.restype=ctypes.c_int
        trim(0)
    except (AttributeError,OSError):pass

def require_headroom():
    value=container_memory()
    if value is None:return
    used,cap=value
    reserve=min(192*MIB,max(64*MIB,int(cap*.20)))
    if used+reserve>=cap:
        gc.collect()
        _trim_allocator()
        used,cap=container_memory() or value
        if used+reserve>=cap:
            raise MemoryError(f"Container memory pressure: {used/MIB:.0f}/{cap/MIB:.0f} MiB used. Export stopped safely. Release previous downloads or choose a smaller batch and retry."+_pressure_details())


def html_memory_headroom():
    """Estimate conservative usable memory for browserless streaming export.

    Credit at most half of inactive ordinary file cache, excluding shared
    memory. Missing or malformed statistics receive no credit. This is not
    an OOM guarantee and is deliberately not used by the PDF renderer.
    """
    reading=_memory_reading()
    if reading is None:return None
    used,cap,root=reading
    inactive=0
    try:
        records={k:int(v) for k,v in (line.split() for line in (root/"memory.stat").read_text().splitlines())}
        file_bytes=records.get("file",records.get("total_cache",records.get("cache",0)))
        shared=records.get("shmem",records.get("total_shmem",0))
        inactive=min(records.get("total_inactive_file",records.get("inactive_file",0)),max(0,file_bytes-shared),used)
    except (OSError,ValueError):pass
    credit=max(0,inactive)//2
    return used,cap,credit

def require_html_headroom(stage="HTML atlas"):
    """Admission based on raw cgroup use; file-cache credit is diagnostic only.

    Community Cloud may throttle before the kernel reclaims inactive pages.
    Keep additional headroom for transient Plotly objects and serialization.
    """
    reading=html_memory_headroom()
    if reading is None:return
    used,cap,credit=reading
    reserve=min(384*MIB,max(96*MIB,int(cap*.20)))
    if used+reserve>=cap:
        gc.collect();_trim_allocator()
        used,cap,credit=html_memory_headroom() or reading
        if used+reserve>=cap:
            raise MemoryError(f"Container memory pressure: {used/MIB:.0f}/{cap/MIB:.0f} MiB used; "
                f"required raw headroom {reserve/MIB:.0f} MiB. Export stopped safely. "
                f"Release previous downloads or choose a smaller batch and retry. Stage: {stage}."+_pressure_details())
