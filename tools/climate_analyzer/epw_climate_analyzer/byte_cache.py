"""MEM-PERF R4: registered, byte-bounded recomputable data/resource caches.

Data cache hits return independent deserialized results. Resource caches return
the original immutable-by-contract resource. Eviction drops references only.
Budgets apply to estimated retained payloads, not total process RSS.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import fields,is_dataclass
from functools import wraps
from hashlib import sha256
from inspect import signature
from threading import RLock
from time import monotonic
import marshal
import pickle
import sys
import datetime
from enum import Enum
MIB=1024**2
MISS=object()
_REGISTRY={}
_REGISTRY_LOCK=RLock()

def estimate_bytes(value,seen=None,depth=0):
    # Preserve lazy scientific dependencies on the source-selection page.
    import numpy as np
    import pandas as pd
    if seen is None:seen=set()
    if depth>32:return None
    ident=id(value)
    if ident in seen:return 0
    seen.add(ident)
    if isinstance(value,pd.DataFrame):
        n=int(value.memory_usage(index=True,deep=True).sum())+sys.getsizeof(value.columns)+512
        attrs=estimate_bytes(value.attrs,seen,depth+1)
        return None if attrs is None else n+attrs
    if isinstance(value,pd.Series):
        attrs=estimate_bytes(value.attrs,seen,depth+1)
        return None if attrs is None else int(value.memory_usage(deep=True))+256+attrs
    if isinstance(value,pd.Index):
        return int(value.memory_usage(deep=True))+256
    if isinstance(value,np.ndarray):
        if not value.dtype.hasobject:return int(value.nbytes)+128
        values=value.flat
    elif isinstance(value,dict):values=(part for pair in value.items() for part in pair)
    elif isinstance(value,(list,tuple,set,frozenset)):values=value
    elif is_dataclass(value) and not isinstance(value,type):values=(getattr(value,f.name) for f in fields(value))
    elif isinstance(value,(str,bytes,bytearray,int,float,bool,type(None),np.generic,datetime.date,datetime.time,datetime.timedelta,Enum)):
        return sys.getsizeof(value)
    else:return None
    total=sys.getsizeof(value)
    for element in values:
        size=estimate_bytes(element,seen,depth+1)
        if size is None:return None
        total+=size
    return total

class ByteLRU:
    def __init__(self,name,budget,entries,ttl=None):
        if budget<=0 or entries<=0:raise ValueError("Positive cache limits required.")
        self.name=name;self.budget=int(budget);self.entries=int(entries);self.ttl=ttl
        self.lock=RLock();self.data=OrderedDict();self.used=0
        self.hits=0;self.misses=0;self.evictions=0;self.rejected=0;self.generation=0

    def _drop(self,key):
        entry=self.data.pop(key,None)
        if entry is not None:self.used-=entry[1]

    def _expire(self,now):
        if self.ttl is None:return
        for key,entry in list(self.data.items()):
            if now-entry[2]>=self.ttl:
                self._drop(key);self.evictions+=1

    def get(self,key):
        with self.lock:
            self._expire(monotonic())
            entry=self.data.get(key)
            if entry is None:
                self.misses+=1;return MISS
            self.hits+=1;self.data.move_to_end(key);return entry[0]

    def put(self,key,value,size=None,*,generation=None):
        if size is None:
            try:size=estimate_bytes(value)
            except (TypeError,ValueError,RecursionError):size=None
        with self.lock:
            if generation is not None and generation!=self.generation:return False
            self._expire(monotonic())
            if size is not None:size=int(size)+sys.getsizeof(key)+192
            if size is None or size>self.budget:
                self.rejected+=1;return False
            self._drop(key)
            while self.data and (self.used+size>self.budget or len(self.data)>=self.entries):
                self._drop(next(iter(self.data)));self.evictions+=1
            self.data[key]=(value,size,monotonic());self.used+=size
            return True

    def pop_if(self,key,predicate):
        with self.lock:
            entry=self.data.get(key)
            if entry is not None and predicate(entry[0]):self._drop(key)

    def clear(self):
        with self.lock:
            n=len(self.data);size=self.used
            self.data.clear();self.used=0;self.generation+=1
            return n,size

    def info(self):
        with self.lock:
            self._expire(monotonic())
            return {"cache":self.name,"entries":len(self.data),"estimated_bytes":self.used,
                    "budget_bytes":self.budget,"hits":self.hits,"misses":self.misses,
                    "evictions":self.evictions,"not_retained":self.rejected}

def pool(name,budget,entries,ttl=None):
    with _REGISTRY_LOCK:
        current=_REGISTRY.get(name)
        if current is None or (current.budget,current.entries,current.ttl)!=(budget,entries,ttl):
            current=ByteLRU(name,budget,entries,ttl);_REGISTRY[name]=current
        return current

def cache_inventory():
    with _REGISTRY_LOCK:items=list(_REGISTRY.values())
    return [item.info() for item in items]

def clear_recomputable_caches():
    """Only registered recomputable objects; never clear arbitrary Streamlit state."""
    with _REGISTRY_LOCK:items=list(_REGISTRY.values())
    result=[]
    for item in items:
        n,size=item.clear()
        if n:result.append({"cache":item.name,"entries":n,"estimated_bytes":size})
    return result

def bounded_cache(*,name,max_bytes,max_entries,ttl=None,resource=False):
    """Stable across script reruns; consistent argument binding, underscore exclusions.

    Only trusted internal function results are serialized. No uploaded pickle
    data is deserialized. Uncacheable results are returned without retention.
    """
    def decorate(fn):
        cache=pool(name,max_bytes,max_entries,ttl)
        sig=signature(fn)
        revision=sha256(marshal.dumps(fn.__code__)).digest()
        @wraps(fn)
        def wrapped(*args,**kwargs):
            bound=sig.bind(*args,**kwargs);bound.apply_defaults()
            try:
                key=sha256(revision+pickle.dumps(tuple((n,v) for n,v in bound.arguments.items() if not n.startswith("_")),protocol=5)).digest()
            except (TypeError,ValueError,pickle.PickleError):return fn(*args,**kwargs)
            with cache.lock:
                hit=cache.get(key)
                generation=cache.generation
            if hit is not MISS:return hit if resource else pickle.loads(hit)
            value=fn(*args,**kwargs)
            if resource:cache.put(key,value,generation=generation)
            else:
                try:estimated=estimate_bytes(value)
                except (TypeError,ValueError,RecursionError):estimated=None
                if estimated is not None and estimated>max_bytes:
                    with cache.lock:cache.rejected+=1
                    return value
                try:stored=pickle.dumps(value,protocol=5)
                except (TypeError,ValueError,pickle.PickleError):return value
                cache.put(key,stored,sys.getsizeof(stored),generation=generation)
            return value
        wrapped.clear=cache.clear
        wrapped.cache_info=cache.info
        return wrapped
    return decorate

def session_inventory(state,keys):
    """Measure selected state objects only; do not serialize or expose contents."""
    rows=[]
    for key in keys:
        if key not in state:continue
        value=state.get(key)
        try:size=estimate_bytes(value)
        except (TypeError,ValueError,RecursionError):size=None
        rows.append({"resource":key,"estimated_bytes":size,"type":type(value).__name__})
    return rows
