"""Shared SI vapour algebra and an explicitly conditional 0-to-2m adapter.

Murphy & Koop (2005), equations 7/10, as used in unchanged P9.3B3 research.
The two-metre layer is assumed isothermal with uniform specific humidity.
Surface pressure is an external proxy, not a future GCM pressure prediction.
"""
from __future__ import annotations
import numpy as np

RD, RV, G = 287.05, 461.5, 9.80665
EPSILON = RD / RV
VIRTUAL_FACTOR = RV / RD - 1


def _finite(value):
    out = np.asarray(value, dtype=float)
    if not np.isfinite(out).all():
        raise ValueError("BM1_NONFINITE_THERMODYNAMIC_STATE")
    return out


def saturation_water_pa(t_c):
    t = _finite(t_c) + 273.15
    if np.any((t <= 123) | (t >= 332)):
        raise ValueError("BM1_MURPHY_KOOP_WATER_DOMAIN_123_TO_332_K")
    u = np.tanh(.0415 * (t - 218.8))
    b = 53.878 - 1331.22 / t - 9.44523 * np.log(t) + .014025 * t
    return np.exp(54.842763 - 6763.22 / t - 4.210 * np.log(t) + .000367 * t + u * b)


def saturation_nasa_phase_pa(t_c):
    t = _finite(t_c) + 273.15
    water = saturation_water_pa(t_c)
    ice = np.exp(9.550426 - 5723.265 / t + 3.53068 * np.log(t) - .00728332 * t)
    return np.where(t < 273.15, ice, water)


def q_from_e(e, p):
    e, p = np.broadcast_arrays(_finite(e), _finite(p))
    if np.any((e < 0) | (p <= e)):
        raise ValueError("BM1_VAPOUR_PRESSURE_DOMAIN")
    return EPSILON * e / (p - (1 - EPSILON) * e)


def e_from_q(q, p):
    q, p = np.broadcast_arrays(_finite(q), _finite(p))
    if np.any((q < 0) | (q >= 1) | (p <= 0)):
        raise ValueError("BM1_SPECIFIC_HUMIDITY_DOMAIN")
    return q * p / (EPSILON + (1 - EPSILON) * q)


def pressure_at_2m(t_c, q, surface_p):
    t, q, p = np.broadcast_arrays(_finite(t_c) + 273.15, _finite(q), _finite(surface_p))
    if np.any((t <= 0) | (q < 0) | (q >= 1) | (p <= 0)):
        raise ValueError("BM1_TWO_METRE_ADAPTER_DOMAIN")
    return p * np.exp(-G * 2 / (RD * t * (1 + VIRTUAL_FACTOR * q)))


def state_from_vapour(t_c, e, surface_p):
    """Solve q(e,p2m) and the isothermal hydrostatic adapter simultaneously."""
    p = _finite(surface_p).copy()
    for _ in range(16):
        q = q_from_e(e, p)
        updated = pressure_at_2m(t_c, q, surface_p)
        if np.max(np.abs(updated - p)) < 1e-9:
            p = updated
            break
        p = updated
    q = q_from_e(e, p)
    if np.max(np.abs(pressure_at_2m(t_c, q, surface_p) - p)) > 1e-8:
        raise ValueError("BM1_TWO_METRE_ADAPTER_DID_NOT_CONVERGE")
    return q, p


def baseline_vapour_state(t_c, td_c, surface_p):
    t, td = np.broadcast_arrays(_finite(t_c), _finite(td_c))
    if np.any(td > t + 1e-9):
        raise ValueError("BM1_BASE_DEWPOINT_ABOVE_T_REQUIRES_SEPARATE_INPUT_ADMISSION")
    e = saturation_water_pa(td)
    q, p = state_from_vapour(t, e, surface_p)
    return q, p, 100 * (e / saturation_water_pa(t))


def q_saturation_at_2m(t_c, surface_p):
    """Feasible floating-point representation of the coupled water bound.

    Directed rounding by at most a few ulps prevents an exactly saturated
    state being encoded as RH=100.00000000000003. No RH clipping or change to
    the target monthly q mean is used.
    """
    es = saturation_water_pa(t_c)
    q, _ = state_from_vapour(t_c, es, surface_p)
    for _ in range(32):
        bad = e_from_q(q, pressure_at_2m(t_c, q, surface_p)) > es
        if not np.any(bad):
            return q
        q = np.where(bad, np.nextafter(q, 0), q)
    raise ValueError("BM1_COUPLED_SATURATION_DIRECTED_ROUNDING_FAILED")


def dew_point_water_c(e):
    e = _finite(e)
    lo, hi = np.full(e.shape, -149.999999), np.full(e.shape, 58.849999)
    if np.any((e <= saturation_water_pa(lo)) | (e >= saturation_water_pa(hi))):
        raise ValueError("BM1_DEWPOINT_OUTSIDE_FINITE_FORMULA_DOMAIN")
    for _ in range(60):
        mid = (lo + hi) / 2
        below = saturation_water_pa(mid) < e
        lo = np.where(below, mid, lo); hi = np.where(below, hi, mid)
    return (lo + hi) / 2


def project_monthly_q(target, upper):
    """Unique minimum-L2 q projection, 0<=q<=upper, sum(q)=sum(target).

    This preserves a time-average of specific humidity, not atmospheric water
    mass. All hours have equal quadrature weight; no arbitrary RH floor.
    """
    target, upper = _finite(target), _finite(upper)
    if target.ndim != 1 or target.shape != upper.shape or not len(target) or np.any((target < 0) | (upper < 0) | (upper >= 1)):
        raise ValueError("BM1_Q_PROJECTION_DIMENSIONS_OR_DOMAIN")
    total, capacity = float(target.sum()), float(upper.sum())
    if total > capacity + 1e-12:
        raise ValueError("BM1_Q_MONTHLY_TARGET_INFEASIBLE_NO_SILENT_CLIPPING")
    if total == 0:
        return np.zeros_like(target), 0.
    if np.all(target <= upper):
        return target.copy(), 0.
    low, high = float(np.min(-target)), float(np.max(upper - target))
    for _ in range(100):
        lam = (low + high) / 2
        if float(np.clip(target + lam, 0, upper).sum()) < total:
            low = lam
        else:
            high = lam
    lam = (low + high) / 2
    result = np.clip(target + lam, 0, upper)
    if abs(float(result.sum()) - total) > 1e-11:
        raise ValueError("BM1_Q_PROJECTION_NUMERICAL_RESIDUAL")
    return result, lam
