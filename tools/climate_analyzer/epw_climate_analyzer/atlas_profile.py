"""MEM-PERF R3: exclusive wall-clock phases and bounded per-chapter reuse.

No source values or figures are recorded in the timing ledger. Nested phase
durations are subtracted from their parents, so reported totals do not double
count work. Timings are observational, not CPU or allocation attributions.
"""
from __future__ import annotations
from collections import OrderedDict,Counter
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
import sys
import numpy as np
import pandas as pd

_ACTIVE=ContextVar("ige_atlas_profile",default=None)
MIB=1024**2
GENERAL_BYTES=16*MIB
UTCI_BYTES=8*MIB
GENERAL_ENTRIES=32
UTCI_ENTRIES=2

class AtlasProfiler:
    def __init__(self,clock=perf_counter):
        self.clock=clock
        self.started=clock()
        self.stack=[]
        self.total=Counter()
        self.calls=Counter()
        self.diagrams=[]
        self.current=None
        self.cache_stats=Counter()
        self.cache_peak=Counter()
        self.utci_stats=Counter()

    @contextmanager
    def activate(self):
        token=_ACTIVE.set(self)
        try:yield self
        finally:_ACTIVE.reset(token)

    @contextmanager
    def measure(self,name):
        start=self.clock()
        frame=[0.]
        self.stack.append(frame)
        try:yield
        finally:
            elapsed=max(0.,self.clock()-start)
            self.stack.pop()
            exclusive=max(0.,elapsed-frame[0])
            if self.stack:self.stack[-1][0]+=elapsed
            self.total[name]+=exclusive
            self.calls[name]+=1
            if self.current is not None:self.current["phase_seconds"][name]+=exclusive

    def begin_diagram(self,d):
        if self.current is not None or self.stack:raise RuntimeError("Nested Atlas diagram profiling")
        self.current={"id":d.id,"title":d.title,"chapter":d.chapter,"kind":d.kind,
                      "phase_seconds":Counter(),"started":self.clock()}

    def end_diagram(self,status):
        row=self.current
        if row is None or self.stack:raise RuntimeError("Invalid Atlas profiling boundary")
        elapsed=max(0.,self.clock()-row.pop("started"))
        row["wall_seconds"]=elapsed
        row["status"]=status
        row["phase_seconds"]=dict(row["phase_seconds"])
        row["unattributed_seconds"]=max(0.,elapsed-sum(row["phase_seconds"].values()))
        self.diagrams.append(row)
        self.current=None

    def summary(self):
        elapsed=max(0.,self.clock()-self.started)
        return {"schema":"MEM-PERF-R3-v1","scope":"Atlas generation through pre-metadata finalization; excludes worker startup, final metadata write and result transfer",
                "wall_seconds":elapsed,"exclusive_phase_seconds":dict(self.total),
                "phase_calls":dict(self.calls),"unattributed_seconds":max(0.,elapsed-sum(self.total.values())),
                "diagrams":self.diagrams,"cache":dict(self.cache_stats),
                "estimated_cache_peak_bytes":dict(self.cache_peak),"utci":dict(self.utci_stats)}

@contextmanager
def phase(name):
    profile=_ACTIVE.get()
    if profile is None:yield
    else:
        with profile.measure(name):yield

def utci_count(key,n):
    profile=_ACTIVE.get()
    if profile is not None:profile.utci_stats[key]+=int(n)

def _estimate(value,seen=None):
    """Estimate retained payload incl. pandas/index; unknown types not cached.

    This is an accounting budget, not a process-memory guarantee. Count
    containers and their members conservatively, including attached attributes.
    """
    if seen is None:seen=set()
    ident=id(value)
    if ident in seen:return 0
    seen.add(ident)
    if isinstance(value,pd.DataFrame):
        n=int(value.memory_usage(index=True,deep=True).sum())
        attrs=_estimate(value.attrs,seen)
        return None if attrs is None else n+attrs+512
    if isinstance(value,(pd.Series,pd.Index)):
        n=int(value.memory_usage(deep=True))
        attrs=_estimate(getattr(value,"attrs",{}),seen)
        return None if attrs is None else n+attrs+256
    if isinstance(value,np.ndarray):
        if value.dtype.hasobject:return None
        return int(value.nbytes)+128
    if isinstance(value,(tuple,list,dict)):
        members=list(value.items()) if isinstance(value,dict) else value
        n=sys.getsizeof(value)
        for item in members:
            size=_estimate(item,seen)
            if size is None:return None
            n+=size
        return n
    if isinstance(value,(str,bytes,int,float,bool,type(None),np.generic,pd.Timestamp,pd.Timedelta)):
        return sys.getsizeof(value)
    return None

class AtlasCache:
    """Two independent bounded LRU pools; UTCI cannot be evicted by other kernels.

    All keys belong to a single chapter, fixed frame and calculation context.
    Oversized or unknown-size results remain correct but are not retained.
    """
    def __init__(self,profile,*,general_bytes=GENERAL_BYTES,utci_bytes=UTCI_BYTES):
        self.profile=profile
        self.pools={"general":OrderedDict(),"utci":OrderedDict()}
        self.used=Counter()
        self.limits={"general":general_bytes,"utci":utci_bytes}
        self.entries={"general":GENERAL_ENTRIES,"utci":UTCI_ENTRIES}

    def get_or_compute(self,key,fn):
        family=str(key[0] if isinstance(key,tuple) else key)
        pool="utci" if family=="utci" else "general"
        items=self.pools[pool]
        with phase("cache_lookup"):
            if key in items:
                items.move_to_end(key)
                self.profile.cache_stats[family+".hits"]+=1
                return items[key][0]
            self.profile.cache_stats[family+".misses"]+=1
        with phase("shared_compute."+family):
            value=fn()
        with phase("cache_admission"):
            try:size=_estimate(value)
            except (TypeError,ValueError,RecursionError):size=None
            if size is None or size>self.limits[pool]:
                self.profile.cache_stats[family+".not_retained"]+=1
                return value
            while items and (len(items)>=self.entries[pool] or self.used[pool]+size>self.limits[pool]):
                old,(_,n)=items.popitem(last=False)
                self.used[pool]-=n
                old_family=str(old[0] if isinstance(old,tuple) else old)
                self.profile.cache_stats[old_family+".evictions"]+=1
            items[key]=(value,size)
            self.used[pool]+=size
            self.profile.cache_peak[pool]=max(self.profile.cache_peak[pool],self.used[pool])
        return value

    def clear(self):
        for pool in self.pools.values():pool.clear()
        self.used.clear()
