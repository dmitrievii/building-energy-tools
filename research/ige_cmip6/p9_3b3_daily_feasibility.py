"""Fixed-T/p global RH upper bound, feasible witnesses and certified lower bound.

No local optimizer failure is called infeasibility. Lower RH minimization uses
MILP secants of concave RH(q): dual bound <= true minimum <= actual witness.
"""
from __future__ import annotations

import time
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, brentq, milp
from scipy.sparse import lil_matrix

from p9_3b3_thermodynamics import epsilon_for, MK, q_saturation, relative_humidity, saturation

Q_TOL = 1e-9
RH_TOL = 1e-4


def weights_for(n, weights=None):
    w = np.full(n, 1 / n) if weights is None else np.asarray(weights, float)
    if w.shape != (n,) or not np.all(np.isfinite(w)) or np.any(w <= 0) or abs(w.sum() - 1) > 1e-12:
        raise ValueError("P93B3_INVALID_QUADRATURE_WEIGHTS")
    return w


def bounded_mean_profile(prior, caps, mean, weights=None):
    """Euclidean projection onto box and weighted mean, with exact zero support."""
    prior = np.asarray(prior, float)
    c = np.asarray(caps, float)
    w = weights_for(len(c), weights)
    if (prior.shape != c.shape or not np.all(np.isfinite(prior)) or
            not np.all(np.isfinite(c)) or np.any(c < 0) or not np.isfinite(mean)):
        raise ValueError("P93B3_INVALID_Q_PROJECTION_INPUT")
    if mean < 0 or mean > w @ c + 1e-12:
        raise ValueError("P93B3_Q_EXCEEDS_FIXED_T_P_CAPACITY")
    if mean == 0:
        return np.zeros(len(c))
    if mean >= w @ c:
        return c.copy()
    lo, hi = -float(np.max(abs(prior)) + np.max(c) + 1), float(np.max(abs(prior)) + np.max(c) + 1)
    for _ in range(80):
        shift = (lo + hi) / 2
        if w @ np.clip(prior + shift, 0, c) < mean:
            lo = shift
        else:
            hi = shift
    return np.clip(prior + (lo + hi)/2, 0, c)


def upper_rh_profile(T, P, Q, phase="WATER", formulation=MK, weights=None, q_caps=None):
    t, p = np.asarray(T, float), np.asarray(P, float)
    w = weights_for(len(t), weights)
    # A caller may relax T and q caps independently for a rigorous outer bound.
    c = q_saturation(t, p, formulation) if q_caps is None else np.asarray(q_caps,float)
    if c.shape!=t.shape or not np.all(np.isfinite(c)) or np.any((c<0)|(c>=1)):
        raise ValueError("P93B3_INVALID_RELAXED_Q_CAPS")
    if Q < 0 or Q > w @ c + 1e-12:
        raise ValueError("P93B3_Q_EXCEEDS_FIXED_T_P_CAPACITY")
    if Q == 0:
        return np.zeros(len(t))
    if Q >= w @ c:
        return c.copy()
    a = 100 * p / saturation(t, phase, formulation)
    eps = epsilon_for(formulation)
    b = 1 - eps
    def allocation(lam):
        return np.clip((np.sqrt(a * eps / lam) - eps) / b, 0, c)
    lo = float(np.min(a * eps / (eps + b*c) ** 2)) / 2
    hi = float(np.max(a / eps)) * 2
    for _ in range(90):
        m = (lo + hi) / 2
        if w @ allocation(m) > Q:
            lo = m
        else:
            hi = m
    return allocation((lo + hi)/2)


def low_witness(caps, Q, weights=None):
    c = np.asarray(caps, float)
    w = weights_for(len(c), weights)
    if Q < 0 or Q > w @ c + 1e-12:
        raise ValueError("P93B3_Q_EXCEEDS_FIXED_T_P_CAPACITY")
    q = np.zeros(len(c))
    remaining = Q
    for i in sorted(range(len(c)), key=lambda j: (-c[j], j)):
        q[i] = min(c[i], max(0, remaining / w[i]))
        remaining -= w[i] * q[i]
    return q


def lower_rh_bound(T, P, Q, phase="WATER", formulation=MK, weights=None,
                   time_limit=5., gap_pp=RH_TOL):
    """Certified fixed-domain global lower bound; never overstates convergence."""
    t, p = np.asarray(T, float), np.asarray(P, float)
    n = len(t)
    w = weights_for(n, weights)
    caps = q_saturation(t, p, formulation)
    if Q < 0 or Q > w @ caps + 1e-12:
        raise ValueError("P93B3_Q_EXCEEDS_FIXED_T_P_CAPACITY")
    witness = low_witness(caps, Q, w)
    value = lambda q: float(w @ relative_humidity(t, p, q, phase, formulation))
    upper = value(witness)
    if Q == 0 or Q >= w @ caps:
        return {"lower_pp": upper, "witness_pp": upper, "witness_q": witness.tolist(),
                "gap_pp": 0., "status": "GLOBAL_MIN_CERTIFIED", "method": "UNIQUE_Q_PROFILE"}
    lower = 0.
    start = time.monotonic()
    attempts = []
    for segments in (8, 16, 32, 64):
        remain = time_limit - (time.monotonic() - start)
        if remain <= 0:
            break
        # lambda interpolation plus binary adjacent segment selection (SOS2).
        m = segments
        nl = n * (m + 1)
        nz = n * m
        nodes = caps[:, None] * np.linspace(0, 1, m + 1)
        f = relative_humidity(t[:, None], p[:, None], nodes, phase, formulation)
        obj = np.r_[(w[:, None] * f).ravel(), np.zeros(nz)]
        a = lil_matrix((2*n + 1 + nl, nl+nz))
        lb = np.full(a.shape[0], -np.inf)
        ub = np.full(a.shape[0], np.inf)
        for i in range(n):
            ids = np.arange(i*(m+1), (i+1)*(m+1))
            zs = np.arange(nl+i*m, nl+(i+1)*m)
            a[2*i, ids] = 1
            a[2*i+1, zs] = 1
            lb[2*i:2*i+2] = ub[2*i:2*i+2] = 1
            a[2*n, ids] = w[i] * nodes[i]
            for j, col in enumerate(ids):
                row = 2*n + 1 + i*(m+1) + j
                a[row, col] = 1
                if j > 0:
                    a[row, zs[j-1]] = -1
                if j < m:
                    a[row, zs[j]] = -1
                ub[row] = 0
        lb[2*n] = ub[2*n] = Q
        sol = milp(obj, integrality=np.r_[np.zeros(nl), np.ones(nz)],
                   bounds=Bounds(np.zeros(nl+nz), np.ones(nl+nz)),
                   constraints=LinearConstraint(a.tocsr(), lb, ub),
                   options={"time_limit": max(.001, remain), "mip_rel_gap": 1e-10})
        attempts.append({"segments": m, "status": int(sol.status)})
        dual = getattr(sol, "mip_dual_bound", None)
        # HiGHS MILP dual objective is a lower bound of the secant relaxation.
        if dual is not None and np.isfinite(dual):
            lower = max(lower, float(dual) - 1e-8)
        if sol.x is not None:
            q = np.sum(sol.x[:nl].reshape(n, m+1) * nodes, axis=1)
            if (abs(w @ q - Q) <= 1e-9 and np.all(q >= -1e-12)
                    and np.all(q <= caps + 1e-12)):
                q = np.clip(q, 0, caps)
                val = value(q)
                if val < upper:
                    upper, witness = val, q
        if lower > upper + 1e-6:
            raise ArithmeticError("P93B3_INVALID_GLOBAL_RH_MIN_BOUNDS")
        if upper - lower <= gap_pp:
            break
    return {"lower_pp": lower, "witness_pp": upper, "witness_q": witness.tolist(),
            "gap_pp": upper-lower, "status": (
                "GLOBAL_MIN_CERTIFIED" if upper-lower <= gap_pp else "RH_LOWER_BOUND_UNRESOLVED"),
            "method": "CONCAVE_RH_MILP_SECANT_DUAL_BOUND", "attempts": attempts}


def fixed_profile_feasibility(T, P, Q, R, phase="WATER", formulation=MK,
                              weights=None, lower_time_limit=5.):
    t, p = np.asarray(T, float), np.asarray(P, float)
    if t.ndim != 1 or p.shape != t.shape or len(t) < 1 or not np.isfinite(R):
        raise ValueError("P93B3_INVALID_FEASIBILITY_SHAPE")
    w = weights_for(len(t), weights)
    cap = q_saturation(t, p, formulation)
    capacity = float(w @ cap)
    report = {"domain": "FIXED_T_P_Q_BOX_WEIGHTED_MEAN", "capacity_q_mean": capacity,
              "required_q_mean": Q, "required_RH_mean_pct": R,
              "certificate_scope": "THIS_FIXED_PROFILE_ONLY"}
    if Q < 0 or Q > capacity + 1e-12:
        return {**report, "status": "CERTIFIED_INFEASIBLE", "reason": "Q_ABOVE_FIXED_PROFILE_CAPACITY"}
    high = upper_rh_profile(t, p, Q, phase, formulation, w)
    low = low_witness(cap, Q, w)
    rh = lambda q: float(w @ relative_humidity(t, p, q, phase, formulation))
    upper, lowval = rh(high), rh(low)
    report.update({"RH_max_pp": upper, "RH_low_witness_pp": lowval})
    if R > upper + RH_TOL:
        return {**report, "status": "CERTIFIED_INFEASIBLE", "reason": "RH_ABOVE_FIXED_PROFILE_GLOBAL_MAX"}
    if R < lowval - RH_TOL:
        bound = lower_rh_bound(t, p, Q, phase, formulation, w, lower_time_limit)
        report["RH_min_bound"] = bound
        if R < bound["lower_pp"] - RH_TOL:
            return {**report, "status": "CERTIFIED_INFEASIBLE", "reason": "RH_BELOW_FIXED_PROFILE_GLOBAL_MIN_BOUND"}
        low = np.asarray(bound["witness_q"])
        lowval = rh(low)
        if R < lowval - RH_TOL:
            return {**report, "status": "UNRESOLVED", "reason": "RH_LOWER_BOUND_UNRESOLVED"}
    # An explicit feasible segment establishes existence, not just an optimizer flag.
    if abs(R - upper) <= RH_TOL:
        q = high
    elif abs(R - lowval) <= RH_TOL:
        q = low
    else:
        alpha = brentq(lambda a: rh((1-a)*low+a*high)-R, 0, 1, xtol=1e-13)
        q = (1-alpha)*low + alpha*high
    if abs(w @ q-Q) > Q_TOL or abs(rh(q)-R) > RH_TOL or np.any(q > cap+1e-12):
        raise ArithmeticError("P93B3_FEASIBLE_WITNESS_VALIDATION_FAILED")
    return {**report, "status": "FEASIBLE", "reason": "Q_RH_FEASIBLE_WITNESS",
            "witness_q": q.tolist(), "achieved_RH_mean_pp": rh(q)}
