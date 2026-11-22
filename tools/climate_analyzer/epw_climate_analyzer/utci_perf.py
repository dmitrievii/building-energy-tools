"""Bounded, session-local UTCI result reuse; no physical approximation."""
from __future__ import annotations

from hashlib import sha256
from time import perf_counter
import numpy as np
import pandas as pd

from . import p3_comfort as p
from .temporal_filtering import time_basis

RESULT_KEY="_utci_perf_r1_result"
CSV_KEY="_utci_perf_r1_csv"
SENSITIVITY_KEY="_utci_perf_r1_sensitivity"
MAX_RESULT_BYTES=8*1024**2
MAX_CSV_BYTES=8*1024**2
MAX_SENSITIVITY_BYTES=1024**2
SCHEMA="UTCI-PERF-R1-v1"

def _array_hash(digest,raw):
    values=np.ascontiguousarray(np.asarray(raw,dtype=np.float64))
    digest.update(repr(values.shape).encode())
    digest.update(values.tobytes())

def physical_key(df,*,model,wind_factor=1.,**parameters):
    """Exact selected inputs, chronology, cadence and model; never chart state."""
    columns=(p.T,p.RH,p.V)
    if model=="Open-sky screening":
        columns+=(p.GHI,p.DHI,p.DNI,p.LW,p.ZEN)
        resolved={"albedo":.2,"absorptivity":.7,"emissivity":.95,
                  "projected_factor":.25,"ground_delta":0.}
        resolved.update(parameters)
    elif model=="Uniform radiant offset":
        resolved={"offset":parameters.get("offset",0.)}
    else:
        raise ValueError("Unknown radiation scenario.")
    digest=sha256()
    digest.update(repr((SCHEMA,model,float(wind_factor),sorted(resolved.items()),
                        p.native_interval_hours(df),time_basis(df),
                        str(df.index.dtype),str(df.index.name),len(df))).encode())
    digest.update(pd.util.hash_pandas_object(df.index,index=False).to_numpy(dtype=np.uint64).tobytes())
    for column in columns:
        digest.update(column.encode())
        _array_hash(digest,p.numeric(df,column).to_numpy(dtype=float,na_value=np.nan))
    return digest.hexdigest()

def _preload():
    # Import timing includes first-use module and eager numerical initialization.
    # Lazy compilation, if any, remains part of the subsequent calculation time.
    from pythermalcomfort.models import utci
    return utci

def cached_physical(state,df,*,model,wind_factor=1.,**parameters):
    started=perf_counter()
    key=physical_key(df,model=model,wind_factor=wind_factor,**parameters)
    fingerprint_s=perf_counter()-started
    existing=state.get(RESULT_KEY)
    if existing is not None and existing["key"]==key:
        values=existing["values"].copy(deep=False)
        values.attrs=dict(df.attrs)
        tr=existing["mrt"].copy(deep=False)
        return values,tr,key,dict(cache_hit=True,fingerprint_s=fingerprint_s,
            import_s=0.,calculation_s=0.,retained_bytes=existing["bytes"])
    # Invalidate old export and physical cache before allocating a new result.
    state.pop(RESULT_KEY,None)
    state.pop(CSV_KEY,None)
    started=perf_counter()
    _preload()
    import_s=perf_counter()-started
    started=perf_counter()
    values,tr=p.utci_frame(df,model=model,wind_factor=wind_factor,**parameters)
    calculation_s=perf_counter()-started
    size=int(values.memory_usage(index=True,deep=True).sum()+tr.memory_usage(index=True,deep=True).sum())
    retained=0
    if size<=MAX_RESULT_BYTES:
        # Retain only numerical outputs, not the original climate DataFrame.
        cached=values.copy(deep=False)
        cached.attrs={}
        state[RESULT_KEY]=dict(key=key,values=cached,mrt=tr,bytes=size)
        retained=size
    return values,tr,key,dict(cache_hit=False,fingerprint_s=fingerprint_s,
        import_s=import_s,calculation_s=calculation_s,retained_bytes=retained)

def cached_sensitivity(state,*args):
    started=perf_counter()
    digest=sha256(SCHEMA.encode())
    for arg in args:_array_hash(digest,arg)
    key=digest.hexdigest()
    fingerprint_s=perf_counter()-started
    existing=state.get(SENSITIVITY_KEY)
    if existing is not None and existing["key"]==key:
        return existing["values"],dict(cache_hit=True,fingerprint_s=fingerprint_s,
            import_s=0.,calculation_s=0.,retained_bytes=existing["values"].nbytes)
    state.pop(SENSITIVITY_KEY,None)
    started=perf_counter()
    _preload()
    import_s=perf_counter()-started
    started=perf_counter()
    values=p.utci_values(*args)
    calculation_s=perf_counter()-started
    retained=0
    if values.nbytes<=MAX_SENSITIVITY_BYTES:
        state[SENSITIVITY_KEY]={"key":key,"values":values}
        retained=values.nbytes
    return values,dict(cache_hit=False,fingerprint_s=fingerprint_s,
        import_s=import_s,calculation_s=calculation_s,retained_bytes=retained)

def cached_csv(state,key,values,mrt,*,prepare=False):
    """No serialization until an explicit request; never serve stale bytes."""
    existing=state.get(CSV_KEY)
    if existing is not None and existing["key"]==key:
        return existing["data"],0.
    state.pop(CSV_KEY,None)
    if not prepare:return None,0.
    started=perf_counter()
    data=pd.concat([values.add_prefix("UTCI · "),mrt.add_prefix("MRT · ")],axis=1).to_csv().encode()
    if len(data)<=MAX_CSV_BYTES:
        state[CSV_KEY]={"key":key,"data":data}
    return data,perf_counter()-started
