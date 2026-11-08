"""Variable projection, pre-specified continuous searches, fixed scoring masks."""
import time
import numpy as np
from scipy.optimize import minimize
from ige_auto.cases import macro_weights,feature_names
from ige_auto.fit import linear_solve,Unidentifiable,BudgetReached
from ige_hum.solver import recover_search
from .cases import restore,background_features


def fit(a,model,eta,opt):
    mask=a.fit_mask
    if int(mask.sum())<opt["min_fit_cases"]:raise Unidentifiable("INSUFFICIENT_FIT_CASES")
    base,x,_=a.design(model["basis"],model["kernel"],eta)
    if x.shape[1]==0:return {"coefficients":[],"feature_names":[],"fit_rows":int(mask.sum()),"rank":0,"columns":0,"case_id":a.case_id}
    loss=model["regression"];ridge=np.exp(eta[2]) if loss=="ridge" else 0.
    w=macro_weights(a,mask)
    if model["basis"]=="background":
        countries=sorted(set(a.country));x=background_features(a,countries);base=np.zeros(len(a.y))
    delta=None
    if loss=="huber":
        ls=linear_solve(x,a.y-base,w,rcond=opt["rank_rcond"],max_condition=opt["max_condition"])
        e=(a.y-base-x@np.array(ls["coefficients"]))[mask]
        delta=float(1.345*max(1e-6,1.4826*np.median(abs(e-np.median(e)))))
    result=linear_solve(x,a.y-base,w,loss,ridge,delta,opt["rank_rcond"],opt["max_condition"])
    result.update(case_id=a.case_id,feature_names=names(model,x.shape[1]))
    if model["basis"]=="background":result.update(transfer_coefficients=result["coefficients"][-5:],background_countries=countries)
    return result


def names(model,n):
    custom={"diurnal":["height","height_sin_year","height_cos_year","height_sin_local_hour","height_cos_local_hour"],
            "hinge":["height","height_above_fitted_knot"],"local_height":["global_height_shrinkage"],
            "barometric_residual":["height_residual_after_physics"]}
    if model["basis"] in custom:return custom[model["basis"]]
    if model["basis"]=="background":return ["country_month_%02d"%i for i in range(n-5)]+custom["diurnal"]
    return feature_names(model["basis"])


def predict(a,model,eta,fitted):
    base,x,w=a.design(model["basis"],model["kernel"],eta)
    coeff=fitted.get("transfer_coefficients",fitted["coefficients"])
    out=base+x@np.asarray(coeff)
    out[~a.ready]=np.nan
    return out,w


def search(folds,model,c,kind="native",coordinate=None,knot_bounds=None):
    """fold = train Cases, check Cases, mask fixed before model fitting, shared aux."""
    opt=c["optimizer"];begin=time.monotonic();cpu=time.process_time();trace=[];runs=[]
    if model["basis"]=="nearest":return {"status":"CONVERGED","eta":[2.,0.],"trace":[],"runs":[],"fixed_control":True,"wall_seconds":0.,"cpu_seconds":0.}
    if any(mask.sum()<opt["min_fit_cases"] for a,b,mask,aux in folds):
        return {"status":"INSUFFICIENT_INNER_CASES","trace":[],"runs":[]}
    ds=np.concatenate([a.dist[a.mask] for a,b,mask,aux in folds])
    if not len(ds):return {"status":"INSUFFICIENT_DONORS","trace":[],"runs":[]}
    median=float(np.median(ds));hi=max(2.,float(ds.max())*10)
    bounds=[(.1,8.),(-6.,7.)] if model["kernel"]=="idw" else [(np.log(max(.01,median/20)),np.log(hi)),(-6.,7.)]
    if model["regression"]=="ridge" or model["basis"]=="local_height":bounds.append((-14.,4.))
    if model["basis"]=="hinge":
        if knot_bounds is None or knot_bounds[1]-knot_bounds[0]<1e-6:return {"status":"NO_HEIGHT_KNOT_SUPPORT","trace":[],"runs":[]}
        bounds.append(tuple(knot_bounds))
    starts=[]
    for i in range(opt["starts"]):
        p=[([1.,4.,6.][i] if model["kernel"]=="idw" else float(np.log(median*[1.,2.,.5][i]))),[0.,3.,-3.][i]]
        if len(bounds)>=3:p.append(-5.)
        if len(bounds)==4:p.append(float(np.mean(knot_bounds)))
        starts.append(np.array(p))

    def core(eta):
        scores=[]
        for a,b,mask,aux in folds:
            fitted=fit(a,model,eta,opt);p,_=predict(b,model,eta,fitted)
            if kind=="RH":p=restore(coordinate,p,aux)["RH"];y=aux["RH_reference"];scale=100.
            else:y=b.y;scale=1.
            if not np.all(np.isfinite(p[mask])):raise Unidentifiable("NONFINITE_FIXED_INNER_PREDICTION")
            w=macro_weights(b,mask);e=(p[mask]-y[mask])/scale
            scores.append(float(np.sum(w[mask]*e*e)))
        return float(np.mean(scores))

    def objective(eta):
        if len(trace)>=opt["max_evaluations"]:raise BudgetReached("MAX_EVALUATIONS")
        if time.monotonic()-begin>opt["wall_seconds_per_model"]:raise BudgetReached("WALL_BUDGET")
        t0=time.monotonic();c0=time.process_time();reason=None
        try:v=core(eta)
        except (Unidentifiable,FloatingPointError,np.linalg.LinAlgError) as exc:v=1e30;reason=str(exc)
        trace.append({"evaluation":len(trace)+1,"eta":list(map(float,eta)),"objective":v,"failure":reason,
                      "wall_seconds":time.monotonic()-t0,"cpu_seconds":time.process_time()-c0})
        return v
    best=None
    for initial in starts:
        try:
            r=minimize(objective,initial,method="L-BFGS-B",bounds=bounds,
                options={"maxiter":opt["max_iterations"],"maxfun":opt["max_evaluations"],"ftol":1e-10 if kind=="RH" else 1e-9,"gtol":1e-7 if kind=="RH" else 1e-6})
            record={"success":bool(r.success),"objective":float(r.fun),"eta":r.x.tolist(),"iterations":int(r.nit),"message":str(r.message)}
            runs.append(record)
            if r.success and np.isfinite(r.fun) and r.fun<1e29 and (best is None or r.fun<best["objective"]):best=record
        except BudgetReached as exc:runs.append({"success":False,"message":str(exc)});break
    result={"status":"CONVERGED" if best else "UNRESOLVED_OPTIMIZATION","trace":trace,"runs":runs,"bounds":bounds}
    if best:result.update(eta=best["eta"],objective=best["objective"])
    else:result=recover_search(result,core,ftol=1e-10 if kind=="RH" else 1e-9,gtol=1e-7 if kind=="RH" else 1e-6)
    if result["status"]=="CONVERGED":result["active_bounds"]=[bool(abs(v-a)<1e-5 or abs(v-b)<1e-5) for v,(a,b) in zip(result["eta"],bounds)]
    result.update(wall_seconds=time.monotonic()-begin,cpu_seconds=time.process_time()-cpu,
                  inner_case_counts=[int(m.sum()) for a,b,m,aux in folds],
                  optimizer_scope="local continuous searches; no global optimum or causal identification claim")
    return result
