"""Conservative Linux container memory admission; no claim of OOM immunity."""
from pathlib import Path
import gc
from threading import Lock

EXPORT_LOCK=Lock()

MIB=1024**2
def container_memory():
    """Return current usage and hard limit where a finite cgroup is visible."""
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
            if 0<cap<2**60 and used>=0:readings.append((used,cap))
        except (ValueError,OSError):continue
    return min(readings,key=lambda pair:pair[1]-pair[0]) if readings else None

def require_headroom():
    value=container_memory()
    if value is None:return
    used,cap=value
    reserve=min(192*MIB,max(64*MIB,int(cap*.20)))
    if used+reserve>=cap:
        gc.collect()
        used,cap=container_memory() or value
        if used+reserve>=cap:
            raise MemoryError(f"Container memory pressure: {used/MIB:.0f}/{cap/MIB:.0f} MiB used. Export stopped safely. Release previous downloads or choose a smaller batch and retry.")
