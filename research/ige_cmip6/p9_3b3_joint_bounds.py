"""Outer bounds for variable T, fixed p, mean q and mean RH.

For L_i <= T_i <= U_i, c_i=q_sat_water(U_i,p_i), e(q) is concave.
  RH_i <= 100 e(q_i,p_i)/es_source(L_i)
  RH_i >= [100 e(c_i,p_i)/(c_i es_source(U_i))] q_i.
The upper problem is separable concave maximization (KKT); the lower is a
continuous knapsack LP. Relaxing mean T, slope and extrema cannot exclude a
real witness. Certificates are conditional on the supplied pressure and phase.
Neither local optimizer status nor a fitted correction enters these bounds.
"""
from __future__ import annotations
import numpy as np
from p9_3b3_daily_feasibility import weights_for,upper_rh_profile,Q_TOL,RH_TOL
from p9_3b3_thermodynamics import MK,q_saturation,relative_humidity


def joint_domain_bounds(T_lower,T_upper,P,Q,R,phase="WATER",formulation=MK,weights=None):
    lo,hi,p=map(lambda x:np.asarray(x,float),(T_lower,T_upper,P))
    if (lo.ndim!=1 or not len(lo) or hi.shape!=lo.shape or p.shape!=lo.shape or
            not np.all(np.isfinite([lo,hi,p])) or np.any(lo>hi) or
            not np.isfinite(Q) or Q<0 or not np.isfinite(R)):
        raise ValueError("P93B3_INVALID_JOINT_BOUND_INPUT")
    w=weights_for(len(lo),weights)
    c=q_saturation(hi,p,formulation);capacity=float(w@c)
    report={"scope":"THIS_PRESSURE_AND_T_INTERVAL_DOMAIN_ONLY",
        "method":"MONOTONE_T_CONCAVE_Q_UPPER_AND_CHORD_Q_LOWER",
        "relaxed_constraints":["T_mean","T_slope","required_extrema_attainment"],
        "capacity_q_mean_upper":capacity,"target_q_mean":Q,"target_RH_mean_pp":R,
        "status":"BOUND_INCONCLUSIVE"}
    if Q>capacity+Q_TOL:
        return {**report,"status":"CERTIFIED_INFEASIBLE","reason":"Q_ABOVE_JOINT_DOMAIN_CAPACITY_UPPER"}
    # Expand the allowed mass by the validator's tolerance to avoid rejecting a
    # numerical witness that is accepted by that independently defined contract.
    qhi=min(capacity,Q+Q_TOL);qlo=max(0.,Q-Q_TOL)
    upper_q=upper_rh_profile(lo,p,qhi,phase,formulation,w,q_caps=c)
    upper=float(w@relative_humidity(lo,p,upper_q,phase,formulation))+1e-7
    slope=relative_humidity(hi,p,c,phase,formulation)/c
    remaining=qlo;lower=0.
    for i in sorted(range(len(c)),key=lambda i:(slope[i],i)):
        mass=min(w[i]*c[i],max(0.,remaining))
        lower+=mass*slope[i];remaining-=mass
    lower=max(0.,lower-1e-7)
    report.update(RH_mean_lower_pp=lower,RH_mean_upper_pp=upper)
    if R>upper+RH_TOL:
        return {**report,"status":"CERTIFIED_INFEASIBLE","reason":"RH_ABOVE_JOINT_DOMAIN_GLOBAL_UPPER"}
    if R<lower-RH_TOL:
        return {**report,"status":"CERTIFIED_INFEASIBLE","reason":"RH_BELOW_JOINT_DOMAIN_GLOBAL_LOWER"}
    return report
