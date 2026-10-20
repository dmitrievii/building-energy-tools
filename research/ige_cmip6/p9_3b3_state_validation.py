"""Independent scalar evaluator. Does not import the thermodynamic core.

Deliberately computes raw-state checks from the published equations, not cached
solver diagnostics. No statistical accuracy or pressure qualification inferred.
"""
from __future__ import annotations
import math


def _es(t, phase, formulation):
    if formulation == "BUCK_WATER_LEGACY":
        if phase != "WATER" or not 168.15 < t < 332:
            raise ValueError("P93B3_VALIDATOR_BUCK_DOMAIN")
        c = t - 273.15
        return 611.21 * math.exp((18.678-c/234.5)*c/(257.14+c))
    if formulation != "MURPHY_KOOP_2005" or phase not in ("WATER", "ICE", "WATER_ICE"):
        raise ValueError("P93B3_VALIDATOR_UNKNOWN_POLICY")
    if not (110 if phase == "ICE" else 123) < t < 332:
        raise ValueError("P93B3_VALIDATOR_MK_DOMAIN")
    if phase == "ICE" or (phase == "WATER_ICE" and t < 273.15):
        if t > 273.16:
            raise ValueError("P93B3_VALIDATOR_ICE_DOMAIN")
        return math.exp(9.550426-5723.265/t+3.53068*math.log(t)-.00728332*t)
    return math.exp(54.842763-6763.22/t-4.210*math.log(t)+.000367*t
        + math.tanh(.0415*(t-218.8))*(53.878-1331.22/t-9.44523*math.log(t)+.014025*t))


def validate_state(T, P, q, target, weights, formulation="MURPHY_KOOP_2005", strict=True):
    if not len(T) == len(P) == len(q) == len(weights) or not T:
        raise ValueError("P93B3_VALIDATOR_ARRAY_LENGTH")
    if any(not math.isfinite(v) for arr in (T, P, q, weights) for v in arr):
        raise ValueError("P93B3_VALIDATOR_NONFINITE")
    if any(w <= 0 for w in weights) or abs(sum(weights)-1) > 1e-12:
        raise ValueError("P93B3_VALIDATOR_WEIGHTS")
    eps = .62198 if formulation == "BUCK_WATER_LEGACY" else 287.05/461.5
    e, rh, rw = [], [], []
    phase = target.semantics.rh_phase
    for ti, pi, qi in zip(T, P, q):
        if not 30000 < pi < 115000 or not 0 <= qi < 1:
            raise ValueError("P93B3_VALIDATOR_P_Q_DOMAIN")
        ei = qi*pi/(eps+(1-eps)*qi)
        e.append(ei)
        rw.append(100*ei/_es(ti, "WATER", formulation))
        rh.append(100*ei/_es(ti, phase, formulation))
        if ei >= pi or rw[-1] > 100*(1+1e-8):
            raise ValueError("P93B3_VALIDATOR_SUPERSATURATED_OR_E_GE_P")
        back = eps*ei/(pi-(1-eps)*ei)
        if abs(back-qi) > max(1e-15, abs(qi)*1e-9):
            raise ValueError("P93B3_VALIDATOR_INVERSE_IDENTITY")
    mean = lambda a: sum(w*x for w,x in zip(weights,a))
    residuals = {"Tmin_K": min(T)-target.Tmin_K, "Tmax_K": max(T)-target.Tmax_K,
                 "q_mean_kgkg": mean(q)-target.q_mean_kgkg,
                 "RH_mean_pp": mean(rh)-target.RH_mean_pct}
    if target.semantics.temperature_operator == "TIME_MEAN_TAS":
        residuals["tas_operator_K"] = mean(T)-target.tas_K
    else:
        residuals["tas_operator_K"] = (min(T)+max(T))/2-target.tas_K
    if max(abs(residuals[k]) for k in ("Tmin_K", "Tmax_K")) > 1e-6:
        raise ValueError("P93B3_VALIDATOR_EXTREMA_RESIDUAL")
    tol = 5e-5 if target.semantics.temperature_operator == "DERIVED_TAS_MIDRANGE" else 1e-6
    if abs(residuals["tas_operator_K"]) > tol:
        raise ValueError("P93B3_VALIDATOR_TAS_OPERATOR_RESIDUAL")
    if strict and (abs(residuals["q_mean_kgkg"]) > 1e-9 or abs(residuals["RH_mean_pp"]) > 1e-4):
        raise ValueError("P93B3_VALIDATOR_EXACT_DAILY_HUMIDITY_RESIDUAL")
    return {"physical_admissibility": "PASS_UNDER_DECLARED_DISCRETE_POLICY",
            "source_semantics_verified": target.semantics.verified,
            "T_time_mean_K": mean(T), "q_mean_kgkg": mean(q), "RH_source_mean_pct": mean(rh),
            "RH_water_max_pct": max(rw), "e_Pa": e, "RH_source_pct": rh,
            "daily_residuals": residuals, "operational_ready": False}
