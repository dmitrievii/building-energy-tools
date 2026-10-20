"""SI thermodynamics for P9.3B3. Murphy & Koop (2005), eqs. 7 and 10.

State is T[K], absolute p[Pa], specific humidity q[kg/kg]. RH is a diagnostic.
Water saturation is the physical envelope; ice supersaturation is permitted.
BUCK_WATER_LEGACY is an explicit comparison policy, never an automatic switch.
"""
from __future__ import annotations

import numpy as np

RD = 287.05
RV = 461.5
EPSILON = RD / RV
MK = "MURPHY_KOOP_2005"
BUCK = "BUCK_WATER_LEGACY"
PHASES = ("WATER", "ICE", "WATER_ICE")


def epsilon_for(formulation):
    if formulation not in (MK, BUCK):
        raise ValueError("P93B3_UNKNOWN_SATURATION_FORMULATION")
    return .62198 if formulation == BUCK else EPSILON


def _finite(x):
    a = np.asarray(x, dtype=float)
    if not np.all(np.isfinite(a)):
        raise ValueError("P93B3_NONFINITE_STATE")
    return a


def saturation(T_K, phase="WATER", formulation=MK, derivative=False):
    """Return saturation pressure [Pa] (or its derivative [Pa/K]).

    Validity: liquid 123<T<332 K; ice 110<T<=273.16 K. WATER_ICE uses
    water at T>=273.15 K. No mixed-phase interpolation is silently invented.
    """
    t = _finite(T_K)
    if phase not in PHASES:
        raise ValueError("P93B3_UNKNOWN_RH_PHASE")
    if formulation == BUCK:
        if phase != "WATER" or np.any((t <= 168.15) | (t >= 332.0)):
            raise ValueError("P93B3_LEGACY_BUCK_WATER_DOMAIN")
        c = t - 273.15
        exponent = (18.678 - c / 234.5) * c / (257.14 + c)
        e = 611.21 * np.exp(exponent)
        dlog = ((18.678 - 2 * c / 234.5) * (257.14 + c)
                - (18.678 * c - c * c / 234.5)) / (257.14 + c) ** 2
        return e * dlog if derivative else e
    if formulation != MK:
        raise ValueError("P93B3_UNKNOWN_SATURATION_FORMULATION")
    if np.any((t <= (110 if phase == "ICE" else 123)) | (t >= 332)):
        raise ValueError("P93B3_MK_LIQUID_TEMPERATURE_DOMAIN")
    ice = np.ones(t.shape, dtype=bool) if phase == "ICE" else (
        t < 273.15 if phase == "WATER_ICE" else np.zeros(t.shape, dtype=bool))
    if np.any(ice & (t > 273.16)):
        raise ValueError("P93B3_ICE_ABOVE_TRIPLE_POINT")
    # Both formulae are evaluated on their mathematical domain, then selected.
    log_i = 9.550426 - 5723.265 / t + 3.53068 * np.log(t) - .00728332 * t
    di = 5723.265 / t ** 2 + 3.53068 / t - .00728332
    b = 53.878 - 1331.22 / t - 9.44523 * np.log(t) + .014025 * t
    u = np.tanh(.0415 * (t - 218.8))
    log_w = 54.842763 - 6763.22 / t - 4.210 * np.log(t) + .000367 * t + u * b
    dw = (6763.22 / t ** 2 - 4.210 / t + .000367
          + .0415 * (1 - u ** 2) * b
          + u * (1331.22 / t ** 2 - 9.44523 / t + .014025))
    e = np.exp(np.where(ice, log_i, log_w))
    return e * np.where(ice, di, dw) if derivative else e


def q_from_e(e_Pa, p_Pa, epsilon=EPSILON):
    e, p = np.broadcast_arrays(_finite(e_Pa), _finite(p_Pa))
    if np.any((p <= 0) | (e < 0) | (e >= p)):
        raise ValueError("P93B3_VAPOUR_TOTAL_PRESSURE_DOMAIN")
    return epsilon * e / (p - (1 - epsilon) * e)


def e_from_q(q_kgkg, p_Pa, epsilon=EPSILON):
    q, p = np.broadcast_arrays(_finite(q_kgkg), _finite(p_Pa))
    if np.any((p <= 0) | (q < 0) | (q >= 1)):
        raise ValueError("P93B3_SPECIFIC_HUMIDITY_DOMAIN")
    return q * p / (epsilon + (1 - epsilon) * q)


def q_saturation(T_K, p_Pa, formulation=MK):
    return q_from_e(saturation(T_K, "WATER", formulation), p_Pa, epsilon_for(formulation))


def qsat_derivative(T_K, p_Pa, formulation=MK):
    e = saturation(T_K, "WATER", formulation)
    de = saturation(T_K, "WATER", formulation, derivative=True)
    p = _finite(p_Pa)
    if np.any(e >= p):
        raise ValueError("P93B3_SATURATION_ABOVE_TOTAL_PRESSURE")
    eps = epsilon_for(formulation)
    return eps * p * de / (p - (1 - eps) * e) ** 2


def relative_humidity(T_K, p_Pa, q_kgkg, phase="WATER", formulation=MK):
    return 100 * e_from_q(q_kgkg, p_Pa, epsilon_for(formulation)) / saturation(T_K, phase, formulation)


def dew_point(e_Pa, formulation=MK):
    """Water dew point [K]; None for zero vapour or below formula domain."""
    e = float(_finite(e_Pa))
    if e < 0:
        raise ValueError("P93B3_NEGATIVE_VAPOUR_PRESSURE")
    lo, hi = (168.150001, 331.999999) if formulation == BUCK else (123.000001, 331.999999)
    if e == 0 or e < float(saturation(lo, formulation=formulation)):
        return None
    if e > float(saturation(hi, formulation=formulation)):
        raise ValueError("P93B3_DEWPOINT_OUTSIDE_FORMULATION_DOMAIN")
    for _ in range(64):
        mid = (lo + hi) / 2
        if saturation(mid, formulation=formulation) < e:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def state_diagnostics(T_K, p_Pa, q_kgkg, phase="WATER", formulation=MK):
    t, p, q = np.broadcast_arrays(_finite(T_K), _finite(p_Pa), _finite(q_kgkg))
    e = e_from_q(q, p, epsilon_for(formulation))
    return {"e_Pa": e.tolist(), "RH_water_pct": relative_humidity(t, p, q, "WATER", formulation).tolist(),
            "RH_source_pct": relative_humidity(t, p, q, phase, formulation).tolist(),
            "rho_v_kg_m3": (e / (RV * t)).tolist(),
            "dew_point_K": [dew_point(x, formulation) for x in e.flat]}
