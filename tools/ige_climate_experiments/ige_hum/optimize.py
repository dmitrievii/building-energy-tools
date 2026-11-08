"""Native-coordinate SVD inside continuous optimization of final RH error."""
import time
import numpy as np
from scipy.optimize import minimize
from ige_auto.cases import macro_weights
from ige_auto.fit import BudgetReached,Unidentifiable,fit_cases,predict,robust_delta
from .physics import restore


def optimize_chain(folds,coordinate,model,c):
    opt=c["optimizer"];begin=time.monotonic();trace=[];runs=[]
    prepared=[(a.view(coordinate),b.view(coordinate),b,aux,b.common_mask(aux)) for a,b,aux in folds]
    if any(mask.sum()<opt["min_fit_cases"] for _,_,_,_,mask in prepared):
        return {"status":"INSUFFICIENT_COMMON_INNER_CASES","trace":[],"runs":[]}
    ds=np.concatenate([a.dist[a.mask] for a,_,_,_,_ in prepared])
    if not len(ds):return {"status":"INSUFFICIENT_DONORS","trace":[],"runs":[]}
    median=float(np.median(ds));hi=max(2.,float(np.max(ds))*10)
    bounds=[(.1,8.),(-6.,7.)] if model["kernel"]=="idw" else [(np.log(max(.01,median/20)),np.log(hi)),(-6.,7.)]
    if model["regression"]=="ridge":bounds.append((-14.,4.))
    starts=[np.array(([1.,4.,6.][i] if model["kernel"]=="idw" else np.log(median*[1.,2.,.5][i]),
                     [0.,3.,-3.][i],*([-5.] if model["regression"]=="ridge" else []))) for i in range(opt["starts"])]
    try:deltas=[robust_delta(a,model,starts[0],opt) if model["regression"]=="huber" else None for a,_,_,_,_ in prepared]
    except Unidentifiable as exc:return {"status":"UNIDENTIFIABLE","reason":str(exc),"trace":[],"runs":[]}
    best=None

    def budget():
        if len(trace)>=opt["max_evaluations"]:raise BudgetReached("MAX_EVALUATIONS")
        if time.monotonic()-begin>opt["wall_seconds_per_model"]:raise BudgetReached("WALL_BUDGET")

    def objective(eta):
        budget();scores=[];failure=None
        try:
            for (a,b,native,aux,mask),delta in zip(prepared,deltas):
                budget();fit=fit_cases(a,model,eta,opt,delta)
                value,_,_=predict(b,model,eta,fit)
                rh=restore(coordinate,value,aux["T"],aux["p"],with_dewpoint=False)["RH"]
                if not np.all(np.isfinite(rh[mask])):raise Unidentifiable("NONFINITE_COMMON_RH; no dropping failed predictions")
                ww=macro_weights(b,mask)
                err=(rh[mask]-native.values[mask,1])/100
                scores.append(float(np.sum(ww[mask]*err*err)))
            value=float(np.mean(scores))
        except (Unidentifiable,FloatingPointError) as exc:value=1e30;failure=str(exc)
        trace.append({"evaluation":len(trace)+1,"eta":list(map(float,eta)),"objective":value,"fold_RH_MSE_fraction":scores,"failure":failure})
        return value

    for x0 in starts:
        try:
            budget();result=minimize(objective,x0,method="L-BFGS-B",bounds=bounds,
                options={"maxiter":opt["max_iterations"],"maxfun":opt["max_evaluations"],"ftol":1e-10,"gtol":1e-7})
            record={"success":bool(result.success),"message":str(result.message),"objective":float(result.fun),
                    "eta":result.x.tolist(),"iterations":int(result.nit)}
            runs.append(record)
            if result.success and np.isfinite(result.fun) and result.fun<1e29 and (best is None or result.fun<best["objective"]):best=record
        except BudgetReached as exc:runs.append({"success":False,"message":str(exc)});break
    if best is None:return {"status":"UNRESOLVED_OPTIMIZATION","trace":trace,"runs":runs}
    eta=best["eta"]
    return {"status":"CONVERGED","eta":eta,"objective":best["objective"],"bounds":bounds,
            "active_bounds":[bool(abs(v-lo)<1e-5 or abs(v-hi)<1e-5) for v,(lo,hi) in zip(eta,bounds)],
            "trace":trace,"runs":runs,"wall_seconds":time.monotonic()-begin,
            "inner_cases":[{"fit":a.ledger,"check":b.ledger,"common_RH_cases":int(mask.sum())} for a,b,_,_,mask in prepared],
            "objective_definition":"country/station/month balanced MSE of reconstructed RH fraction; same fixed cases across coordinates",
            "native_coefficients":"SVD OLS/ridge or training-only-delta Huber, not a coefficient grid",
            "global_optimum_or_physical_identifiability_established":False}
