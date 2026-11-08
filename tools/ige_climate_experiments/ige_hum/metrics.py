"""Common-output errors and explicit physical/coverage diagnostics."""
import collections
import numpy as np
from .physics import dewpoint_water


def errors(y,p,case,mask):
    ref=mask&np.isfinite(y);use=ref&np.isfinite(p);e=p[use]-y[use]
    result={"N_reference":int(ref.sum()),"N_scored":int(use.sum()),
            "coverage_reference":float(use.sum()/ref.sum()) if ref.sum() else None}
    country,station,month=case.country,case.station,case.month
    groups={};buckets=collections.defaultdict(list)
    for st in sorted(set(station[ref])):
        ix=use&(station==st);err=p[ix]-y[ix]
        co=str(country[np.flatnonzero(station==st)[0]])
        groups[str(st)]={"country":co,"N":int(ix.sum()),"MAE":float(np.mean(np.abs(err))) if len(err) else None,
                         "bias":float(np.mean(err)) if len(err) else None}
        if len(err):buckets[co].append(float(np.mean(np.abs(err))))
    by_country={}
    for co in sorted(set(country[ref])):
        ix=use&(country==co);err=p[ix]-y[ix]
        by_country[str(co)]={"N":int(ix.sum()),"MAE":float(np.mean(np.abs(err))) if len(err) else None,
                             "station_macro_MAE":float(np.mean(buckets[str(co)])) if buckets[str(co)] else None}
    result.update(MAE=float(np.mean(np.abs(e))) if len(e) else None,
                  RMSE=float(np.sqrt(np.mean(e*e))) if len(e) else None,
                  bias=float(np.mean(e)) if len(e) else None,
                  macro_MAE=float(np.mean([np.mean(v) for v in buckets.values() if v])) if any(buckets.values()) else None,
                  by_country=by_country,by_station=groups,
                  by_month={str(m):{"N":int((use&(month==m)).sum()),
                    "MAE":float(np.mean(np.abs(p[use&(month==m)]-y[use&(month==m)]))) if np.any(use&(month==m)) else None}
                    for m in sorted(set(month[ref]))})
    return result


def score(native,pred,mask):
    b=native.base
    e_ref=np.where(native.eligible[:,:2].all(axis=1)&(native.e>0),native.e,np.nan)
    reference={"RH":np.where(native.eligible[:,1],native.values[:,1],np.nan),
               "e_hPa":e_ref,"q_kgkg":np.where(native.joint_reference,native.q,np.nan),
               "Td_water":dewpoint_water(e_ref)}
    result={name:errors(y,pred[name],b,mask) for name,y in reference.items()}
    result["physical_flags"]={name:int(np.sum(pred[name]&mask)) for name in
        ("supersaturated","negative_RH","vapour_ge_pressure","q_outside_0_1")}
    result["clipping_applied"]=False
    result["QC"]={}
    book=b.cube.meta["qc_codebook"]
    for codes in sorted({tuple(map(int,row)) for row in native.target_qc[mask]}):
        use=mask&np.all(native.target_qc==np.array(codes),axis=1)
        key="|".join(map(str,codes))
        result["QC"][key]={"definitions_TRHp":[book[code] for code in codes],"RH":errors(reference["RH"],pred["RH"],b,use)}
    return result
