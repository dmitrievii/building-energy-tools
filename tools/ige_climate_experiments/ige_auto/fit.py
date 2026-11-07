"""Variable projection: SVD regression inside continuous grouped-CV optimization."""
from __future__ import annotations

import time

import numpy as np
from scipy.optimize import minimize

from ige_local.common import InputError
from .cases import feature_names, macro_weights


class Unidentifiable(InputError):
    pass


class BudgetReached(RuntimeError):
    pass


def linear_solve(x, y, weights, loss="ols", ridge=0.0, delta=None, rcond=1e-10, max_condition=1e8):
    keep = (weights > 0) & np.isfinite(y) & np.all(np.isfinite(x), axis=1)
    x, y, w = x[keep], y[keep], weights[keep]
    if len(y) < x.shape[1]+2 or not len(y):
        raise Unidentifiable("INSUFFICIENT_REGRESSION_ROWS")
    w = w/w.sum()
    scale = np.sqrt(np.sum(w[:, None]*x*x, axis=0))
    if np.any(scale < 1e-12):
        raise Unidentifiable("ZERO_FEATURE_SUPPORT")
    a = x/scale
    singular = np.linalg.svd(a*np.sqrt(w[:, None]), compute_uv=False)
    rank = int(np.sum(singular > singular[0]*rcond))
    condition = float(singular[0]/singular[-1]) if singular[-1] > 0 else float("inf")
    if rank != x.shape[1] or condition > max_condition:
        raise Unidentifiable("RANK_OR_CONDITION_FAILURE: rank=%s, columns=%s, condition=%s" % (rank, x.shape[1], condition))
    raw_s = np.linalg.svd(x*np.sqrt(w[:, None]), compute_uv=False)

    def solve(ww):
        aa, yy = a*np.sqrt(ww[:, None]), y*np.sqrt(ww)
        if loss == "ridge":
            aa = np.vstack((aa, np.sqrt(ridge)*np.eye(x.shape[1])))
            yy = np.concatenate((yy, np.zeros(x.shape[1])))
        return np.linalg.lstsq(aa, yy, rcond=rcond)[0]

    beta = solve(w); iterations = 1
    if loss == "huber":
        if delta is None or not np.isfinite(delta) or delta <= 0:
            raise InputError("Huber requires a fixed positive training-only delta")
        for iterations in range(2, 202):
            residual = y-a@beta
            robust = np.minimum(1.0, delta/np.maximum(np.abs(residual), 1e-30))
            new = solve(w*robust)
            if np.linalg.norm(new-beta) <= 1e-8*(1+np.linalg.norm(beta)):
                beta = new
                break
            beta = new
        else:
            raise Unidentifiable("HUBER_IRLS_NOT_CONVERGED")
    return {"coefficients": (beta/scale).tolist(), "feature_rms": scale.tolist(), "rank": rank,
            "columns": int(x.shape[1]), "scaled_condition": condition,
            "raw_condition": float(raw_s[0]/raw_s[-1]), "singular_values_scaled": singular.tolist(),
            "fit_rows": int(len(y)), "loss": loss, "ridge_lambda": float(ridge) if loss == "ridge" else None,
            "huber_delta": float(delta) if loss == "huber" else None, "irls_iterations": iterations,
            "objective": "weighted_mean_squared_transfer_residual" if loss != "huber" else "weighted_mean_Huber_transfer_residual",
            "coefficient_identifiability": "numerical_full_rank_only; no causal or physical identification claim"}


def robust_delta(cases, model, eta, opt):
    base, x, _ = cases.design(model["basis"], model["kernel"], eta)
    weights = macro_weights(cases, cases.fit_mask)
    ls = linear_solve(x, cases.y-base, weights, rcond=opt["rank_rcond"], max_condition=opt["max_condition"])
    residual = (cases.y-base-x@np.array(ls["coefficients"]))[cases.fit_mask]
    mad = 1.4826*np.median(np.abs(residual-np.median(residual)))
    return float(1.345*max(mad, 1e-6))


def fit_cases(cases, model, eta, opt, delta=None):
    if cases.fit_mask.sum() < opt["min_fit_cases"]:
        raise Unidentifiable("INSUFFICIENT_SCORABLE_CASES: " + str(int(cases.fit_mask.sum())))
    base, x, _ = cases.design(model["basis"], model["kernel"], eta)
    if model["regression"] == "huber" and delta is None:
        delta = robust_delta(cases, model, eta, opt)
    result = linear_solve(x, cases.y-base, macro_weights(cases, cases.fit_mask), model["regression"],
                          np.exp(eta[2]) if model["regression"] == "ridge" else 0, delta,
                          opt["rank_rcond"], opt["max_condition"])
    result["feature_names"] = feature_names(model["basis"])
    result["case_id"] = cases.case_id
    return result


def predict(cases, model, eta, fitted):
    base, x, w = cases.design(model["basis"], model["kernel"], eta)
    p = base+x@np.array(fitted["coefficients"])
    p[~cases.ready] = np.nan
    neff = np.divide(1.0, np.sum(w*w, axis=1), out=np.zeros(len(p)), where=np.sum(w*w, axis=1) > 0)
    return p, neff, w


def loss_value(errors, weights, regression, delta):
    if regression == "huber":
        r = np.abs(errors)
        values = np.where(r <= delta, .5*r*r, delta*(r-.5*delta))
    else:
        values = errors*errors
    return float(np.sum(weights*values))


def optimize(folds, model, c):
    opt = c["optimizer"]; started = time.monotonic(); trace = []; runs = []
    ds = np.concatenate([a.dist[a.mask] for a, _ in folds])
    if not len(ds):
        return {"status": "INSUFFICIENT_DONORS", "trace": [], "runs": []}
    median = float(np.median(ds)); hi = max(2.0, float(np.max(ds))*10)
    bounds = [(.1, 8.0), (-6., 7.)] if model["kernel"] == "idw" else [(np.log(max(.01, median/20)), np.log(hi)), (-6., 7.)]
    if model["regression"] == "ridge":
        bounds.append((-14., 4.))
    starts = []
    for i in range(opt["starts"]):
        first = [1.0, 4.0, 6.0][i] if model["kernel"] == "idw" else np.log(median*[1., 2., .5][i])
        starts.append(np.array([first, [0., 3., -3.][i]] + ([-5.] if model["regression"] == "ridge" else [])))
    # Frozen within each fold for optimization; estimated using D-fitting data only.
    try:
        deltas = [robust_delta(a, model, starts[0], opt) if model["regression"] == "huber" else None for a, _ in folds]
    except Unidentifiable as exc:
        return {"status": "UNIDENTIFIABLE", "reason": str(exc), "trace": [], "runs": []}
    best = None

    def check_budget():
        if len(trace) >= opt["max_evaluations"]:
            raise BudgetReached("MAX_EVALUATIONS")
        if time.monotonic()-started > opt["wall_seconds_per_model"]:
            raise BudgetReached("WALL_BUDGET")

    def objective(eta):
        check_budget(); scores = []; counts = []; reason = None
        try:
            for (a, b), delta in zip(folds, deltas):
                check_budget()
                fit = fit_cases(a, model, eta, opt, delta)
                pred, _, _ = predict(b, model, eta, fit)
                mask = b.fit_mask
                if mask.sum() < opt["min_fit_cases"] or not np.all(np.isfinite(pred[mask])):
                    raise Unidentifiable("INSUFFICIENT_INNER_VALIDATION")
                weights = macro_weights(b, mask)
                scores.append(loss_value(pred[mask]-b.y[mask], weights[mask], model["regression"], delta))
                counts.append(int(mask.sum()))
            value = float(np.mean(scores))
        except (Unidentifiable, FloatingPointError) as exc:
            value = 1e30; reason = str(exc)
        trace.append({"evaluation": len(trace)+1, "eta": list(map(float, eta)), "objective": value,
                      "fold_objectives": scores, "fold_rows": counts, "failure": reason})
        return value

    # Each start is a local continuous search, not a coefficient grid. A converged
    # start remains usable when an additional diagnostic start exhausts the budget.
    for x0 in starts:
        try:
            check_budget()
            r = minimize(objective, x0, method="L-BFGS-B", bounds=bounds,
                         options={"maxiter": opt["max_iterations"], "maxfun": opt["max_evaluations"], "ftol": 1e-9, "gtol": 1e-6})
            run = {"success": bool(r.success), "message": str(r.message), "objective": float(r.fun),
                   "eta": r.x.tolist(), "iterations": int(r.nit)}
            runs.append(run)
            if r.success and np.isfinite(r.fun) and r.fun < 1e29 and (best is None or r.fun < best["objective"]):
                best = run
        except BudgetReached as exc:
            runs.append({"success": False, "message": str(exc)}); break
    if best is None:
        return {"status": "UNRESOLVED_OPTIMIZATION", "trace": trace, "runs": runs,
                "wall_seconds": time.monotonic()-started, "bounds": bounds}
    eta = best["eta"]
    cv = []
    for (a, b), delta in zip(folds, deltas):
        f = fit_cases(a, model, eta, opt, delta); p, _, _ = predict(b, model, eta, f)
        ix = b.fit_mask; ww = macro_weights(b, ix, month_balance=False)
        cv.append({"fit": a.ledger, "check": b.ledger, "coefficients": f["coefficients"],
                   "MAE": float(np.sum(ww[ix]*np.abs(p[ix]-b.y[ix]))), "huber_delta": delta})
    finite_objectives = [t["objective"] for t in trace if t["objective"] < 1e29]
    span = max(finite_objectives)-min(finite_objectives)
    return {"status": "CONVERGED", "eta": eta, "objective": best["objective"], "bounds": bounds,
            "active_bounds": [bool(abs(x-a)<1e-5 or abs(x-b)<1e-5) for x, (a, b) in zip(eta, bounds)],
            "inner_cv": cv, "trace": trace, "runs": runs, "wall_seconds": time.monotonic()-started,
            "weight_identifiability": "not established by optimizer convergence",
            "nearly_flat_sampled_objective": span < 1e-8*max(1., abs(best["objective"])),
            "optimizer_scope": "local optimum from declared starts; no global optimum claim"}


def kernel_parameters(model, eta):
    p = {"vertical_distance_multiplier": float(np.exp(eta[1])), "horizontal_distance_multiplier": 1.0}
    p["beta" if model["kernel"] == "idw" else "bandwidth_km"] = float(eta[0]) if model["kernel"] == "idw" else float(np.exp(eta[0]))
    if model["regression"] == "ridge":
        p["ridge_lambda"] = float(np.exp(eta[2]))
    return p
