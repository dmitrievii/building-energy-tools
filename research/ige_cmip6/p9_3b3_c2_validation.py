"""Independent scalar C2 validator; no projection or thermodynamic core import.

Published saturation equations are provided by the frozen scalar B3 validator.
Geometry, weighted operators and hard diagnostic checks are recomputed from raw
inputs, independently of optimizer diagnostics and supplied success flags.
"""
from __future__ import annotations

import math

from p9_3b3_state_validation import _es


def _weights(w, n):
    if (len(w) != n or any(not math.isfinite(v) or v < 0 for v in w) or
            abs(math.fsum(w)-1) > 1e-12):
        raise ValueError("P93C2_VALIDATOR_WEIGHTS")
    return [float(v) for v in w]


def validate_projection(T, P, q, target, expected_pressure, donor_T,
                        q_weights, RH_weights, T_weights, *,
                        hard_q=False, hard_RH=False, formulation="MURPHY_KOOP_2005"):
    n = len(T)
    if not n or any(len(a) != n for a in (P, q, expected_pressure, donor_T)):
        raise ValueError("P93C2_VALIDATOR_ARRAY_LENGTH")
    if any(not math.isfinite(x) for a in (T, P, q, expected_pressure, donor_T) for x in a):
        raise ValueError("P93C2_VALIDATOR_NONFINITE")
    if any(p != fixed for p, fixed in zip(P, expected_pressure)):
        raise ValueError("P93C2_VALIDATOR_PRESSURE_WAS_CHANGED")
    u, v, wT = (_weights(w, n) for w in (q_weights, RH_weights, T_weights))
    dmin, dmax = min(donor_T), max(donor_T)
    if target.Tmin_K == target.Tmax_K:
        T0 = [target.Tmin_K]*n
    elif dmax-dmin < 1e-12:
        raise ValueError("P93C2_VALIDATOR_FLAT_DONOR")
    else:
        T0 = [target.Tmin_K + (target.Tmax_K-target.Tmin_K)*(x-dmin)/(dmax-dmin)
              for x in donor_T]
    fixed = {T0.index(min(T0)), T0.index(max(T0))}
    if target.Tmin_K == target.Tmax_K:
        fixed = set(range(n))
    for i, ti in enumerate(T):
        low, high = max(target.Tmin_K, T0[i]-2), min(target.Tmax_K, T0[i]+2)
        if ti < low-1e-7 or ti > high+1e-7 or (i in fixed and abs(ti-T0[i]) > 1e-7):
            raise ValueError("P93C2_VALIDATOR_DONOR_T_GEOMETRY")
    slope = max(6., max((abs(b-a)*n/24 for a,b in zip(T0,T0[1:])), default=0.))
    if any(abs(b-a)*n/24 > slope+1e-7 for a,b in zip(T,T[1:])):
        raise ValueError("P93C2_VALIDATOR_T_SLOPE")
    eps = .62198 if formulation == "BUCK_WATER_LEGACY" else 287.05/461.5
    rh, rw, vapour = [], [], []
    for ti, pi, qi in zip(T, P, q):
        if not 30000 < pi < 115000 or not 0 <= qi < 1:
            raise ValueError("P93C2_VALIDATOR_P_Q_DOMAIN")
        e = qi*pi/(eps+(1-eps)*qi)
        water = 100*e/_es(ti, "WATER", formulation)
        source = 100*e/_es(ti, target.semantics.rh_phase, formulation)
        if e >= pi or water > 100*(1+1e-8):
            raise ValueError("P93C2_VALIDATOR_SUPERSATURATION")
        back = eps*e/(pi-(1-eps)*e)
        if abs(back-qi) > max(1e-15, abs(qi)*1e-9):
            raise ValueError("P93C2_VALIDATOR_EOS_ROUNDTRIP")
        rh.append(source);rw.append(water);vapour.append(e)
    mean = lambda w,a: math.fsum(x*y for x,y in zip(w,a))
    Q, R, tm = mean(u,q), mean(v,rh), mean(wT,T)
    residual = {"Tmin_K":min(T)-target.Tmin_K, "Tmax_K":max(T)-target.Tmax_K,
                "q_mean_kgkg":Q-target.q_mean_kgkg, "RH_mean_pp":R-target.RH_mean_pct}
    if max(abs(residual[k]) for k in ("Tmin_K","Tmax_K")) > 1e-6:
        raise ValueError("P93C2_VALIDATOR_T_EXTREMA")
    if target.semantics.temperature_operator == "DERIVED_TAS_MIDRANGE":
        residual["tas_operator_K"] = (min(T)+max(T))/2-target.tas_K
        tolerance = 5e-5
    elif target.semantics.temperature_operator == "TIME_MEAN_TAS":
        residual["tas_operator_K"] = tm-target.tas_K
        tolerance = 1e-6
    else:
        raise ValueError("P93C2_VALIDATOR_UNKNOWN_T_OPERATOR")
    if abs(residual["tas_operator_K"]) > tolerance:
        raise ValueError("P93C2_VALIDATOR_TAS_OPERATOR")
    if hard_q and abs(residual["q_mean_kgkg"]) > 1e-9:
        raise ValueError("P93C2_VALIDATOR_HARD_Q")
    if hard_RH and abs(residual["RH_mean_pp"]) > 1e-4:
        raise ValueError("P93C2_VALIDATOR_HARD_RH")
    return {"physical_admissibility":"PASS_UNDER_DECLARED_DISCRETE_POLICY",
            "q_mean_kgkg":Q, "RH_source_mean_pct":R, "T_time_mean_K":tm,
            "daily_residuals":residual, "RH_water_max_pct":max(rw),
            "source_diagnostics_unchanged_within_numerical_tolerance":
                abs(residual["q_mean_kgkg"]) <= 1e-9 and abs(residual["RH_mean_pp"]) <= 1e-4,
            "diagnostics":{"RH_source_pct":rh, "RH_water_pct":rw, "e_Pa":vapour},
            "pressure_changed":False, "continuous_time_qualified":False,
            "mean_q_is_not_column_water_mass_conservation":True,
            "independent_accuracy":"NOT_TESTED", "operational_ready":False}
