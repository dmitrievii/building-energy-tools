"""Bounded, D-only numerical recovery; failed searches remain explicit."""
import time
import numpy as np
from scipy.optimize import minimize
from ige_auto.cases import macro_weights
from ige_auto.fit import BudgetReached,Unidentifiable,fit_cases,predict,loss_value


POLICY={"id":"IGE_CONTINUOUS_RECOVERY_v1","trigger":"UNRESOLVED_OPTIMIZATION_ONLY",
        "methods":["L-BFGS-B_eps_1e-5","Powell"],"max_evaluations_per_method":900,
        "max_iterations_per_method":180,"wall_seconds_per_method":600,
        "success_required":True,"bounds_and_objective_unchanged":True,
        "V_or_C_used_for_numerical_recovery":False}


def recover_search(initial,objective,ftol=1e-9,gtol=1e-6):
    if initial["status"]!="UNRESOLVED_OPTIMIZATION":return initial
    begin=time.monotonic();bounds=initial.get("bounds")
    if not bounds:return initial
    trace=[dict(t,stage="original") for t in initial.get("trace",[])]
    attempts=[]

    def starting_point():
        valid=[t for t in trace if t.get("failure") is None and np.isfinite(t["objective"]) and t["objective"]<1e29
               and len(t.get("eta",[]))==len(bounds)]
        if not valid:return None
        best=min(valid,key=lambda t:t["objective"])
        return np.clip(best["eta"],[a for a,b in bounds],[b for a,b in bounds])

    for method in POLICY["methods"]:
        start=starting_point()
        if start is None:break
        stage_begin=time.monotonic();count=0

        def guarded(eta):
            nonlocal count
            if count>=POLICY["max_evaluations_per_method"]:raise BudgetReached("RECOVERY_MAX_EVALUATIONS")
            if time.monotonic()-stage_begin>=POLICY["wall_seconds_per_method"]:raise BudgetReached("RECOVERY_WALL_BUDGET")
            failure=None
            try:
                value=float(objective(eta))
                if not np.isfinite(value):raise Unidentifiable("NONFINITE_RECOVERY_OBJECTIVE")
            except (Unidentifiable,FloatingPointError) as exc:value=1e30;failure=str(exc)
            count+=1
            trace.append({"evaluation":len(trace)+1,"stage":method,"eta":list(map(float,eta)),
                          "objective":value,"failure":failure})
            return value

        options={"maxiter":POLICY["max_iterations_per_method"],"ftol":ftol}
        if method.startswith("L-BFGS-B"):
            solver="L-BFGS-B"
            options.update(maxfun=POLICY["max_evaluations_per_method"],eps=1e-5,maxls=40,gtol=gtol)
        else:
            solver="Powell"
            options.update(maxfev=POLICY["max_evaluations_per_method"],xtol=1e-5)
        try:
            result=minimize(guarded,start,method=solver,bounds=bounds,options=options)
            good=bool(result.success and np.isfinite(result.fun) and result.fun<1e29 and np.all(np.isfinite(result.x)))
            attempts.append({"method":method,"success":good,"message":str(result.message),"objective":float(result.fun),
                             "eta":result.x.tolist(),"iterations":int(result.nit),"evaluations":count})
            if good:
                eta=result.x.tolist()
                return {**initial,"status":"CONVERGED","eta":eta,"objective":float(result.fun),"trace":trace,
                        "active_bounds":[bool(abs(v-a)<1e-5 or abs(v-b)<1e-5) for v,(a,b) in zip(eta,bounds)],
                        "recovery_policy":POLICY,"recovery_attempts":attempts,"recovery_used":True,
                        "recovery_wall_seconds":time.monotonic()-begin,
                        "optimizer_scope":"bounded local continuous searches; no global optimum claim"}
        except BudgetReached as exc:
            attempts.append({"method":method,"success":False,"message":str(exc),"evaluations":count})
    return {**initial,"trace":trace,"recovery_policy":POLICY,"recovery_attempts":attempts,"recovery_used":True,
            "recovery_wall_seconds":time.monotonic()-begin}


def recover_native(initial,folds,model,c):
    """Same fixed native loss and training-only SVD regression as original search."""
    if initial["status"]!="UNRESOLVED_OPTIMIZATION":return initial
    opt=c["optimizer"]
    if model["regression"]!="ols":raise ValueError("Native recovery is registered for OLS auxiliaries only")

    def objective(eta):
        scores=[]
        for a,b in folds:
            fit=fit_cases(a,model,eta,opt)
            pred,_,_=predict(b,model,eta,fit);mask=b.fit_mask
            if mask.sum()<opt["min_fit_cases"] or not np.all(np.isfinite(pred[mask])):
                raise Unidentifiable("INSUFFICIENT_INNER_VALIDATION")
            w=macro_weights(b,mask)
            scores.append(loss_value(pred[mask]-b.y[mask],w[mask],model["regression"],None))
        return float(np.mean(scores))

    result=recover_search(initial,objective)
    if result["status"]=="CONVERGED":
        result["inner_cv"]=[]
        for a,b in folds:
            fitted=fit_cases(a,model,result["eta"],opt);pred,_,_=predict(b,model,result["eta"],fitted)
            mask=b.fit_mask;w=macro_weights(b,mask,month_balance=False)
            result["inner_cv"].append({"fit":a.ledger,"check":b.ledger,"coefficients":fitted["coefficients"],
                "MAE":float(np.sum(w[mask]*np.abs(pred[mask]-b.y[mask]))),"huber_delta":None})
    return result
