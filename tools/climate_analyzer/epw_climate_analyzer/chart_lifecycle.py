"""R7: one page figure registry per session and bounded weak diagnostics."""
from collections import deque
from threading import RLock
from uuid import uuid4
import weakref

DISPLAYED="_p6_displayed_charts"
TOKEN="_p6_page_token"
_LOCK=RLock()
_RETIRED=deque(maxlen=256)
_TOTAL=0

def _track_retired(fig):
    global _TOTAL
    try:ref=weakref.ref(fig)
    except TypeError:return
    with _LOCK:
        _RETIRED.append(ref)
        _TOTAL+=1

def release_page(state):
    old=state.pop(DISPLAYED,[])
    state.pop(TOKEN,None)
    if isinstance(old,list):
        for item in old:
            if isinstance(item,tuple) and len(item)==4:_track_retired(item[0])

def begin_page(state):
    release_page(state)
    token=uuid4().hex
    state[TOKEN]=token
    state[DISPLAYED]=[]
    return token

def register_figure(state,fig,context,interpretation,key):
    entries=state.setdefault(DISPLAYED,[])
    for index,item in enumerate(entries):
        if item[3]==key:
            _track_retired(item[0])
            entries[index]=(fig,context,interpretation,key)
            return
    entries.append((fig,context,interpretation,key))

def chart_lifecycle_summary(state):
    with _LOCK:
        return {"current_page_figures":len(state.get(DISPLAYED,[])),
                "retired_total":_TOTAL,"retired_tracked":len(_RETIRED),
                "retired_alive":sum(ref() is not None for ref in _RETIRED),
                "scope":"Current session registry; bounded process-wide weak references to retired figures. Not exact heap attribution."}
