"""Weak-reference-only EPW object and phase diagnostics."""
from collections import deque,Counter
from threading import RLock
from time import perf_counter
import weakref
from .startup_runtime import begin_phase,end_phase
_LOCK=RLock()
_REFS=deque(maxlen=128)
_COUNTS=Counter()
def track(label,obj):
    try:r=weakref.ref(obj)
    except TypeError:return
    with _LOCK:
        _COUNTS[label]+=1
        if not any(ref() is obj for _,ref in _REFS):_REFS.append((label,r))
def phase_start():return begin_phase()
def phase_end(token,label):return end_phase(token,label,diagnostic=True)
def lifecycle_summary():
    with _LOCK:
        alive=Counter(label for label,ref in _REFS if ref() is not None)
        tracked=Counter(label for label,_ in _REFS)
        return {"tracked":dict(tracked),"alive":dict(alive),"observations":dict(_COUNTS),
                "scope":"Bounded weak references; alive includes active sessions, not proof of leak."}
