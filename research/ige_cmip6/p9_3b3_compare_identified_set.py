"""C1 outer RH bounds with separate averaging weights and external pressure boxes.

For each node, q <= qsat_water(T_upper, p_lower). Monotonicity in p and
the within-phase monotonicity of es(T) relax the domain to separable functions.
The upper objective is concave in q; its Lagrangian dual is an upper bound at
ANY nonnegative multiplier, even before bisection converges. A linear chord
relaxation and its dual give a lower bound. This avoids treating an approximate
primal maximum as a rigorous upper bound. Float64 guards are explicit; this is
not a directed-rounding interval-arithmetic implementation.

No probability is attached to an identified set. Passing an outer bound is
never reported as feasibility of the full source/donor/continuous-time model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import numpy as np

from p9_3b3_compare_operators import normalized_weights
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_daily_feasibility import Q_TOL, RH_TOL
from p9_3b3_thermodynamics import MK, epsilon_for, q_saturation, saturation


@dataclass(frozen=True)
class MeanInterval:
    lower: float
    upper: float
    unit: str
    evidence: str
    interpretation: str = "EXACT_SOURCE_STATISTIC"

    def __post_init__(self):
        if (not all(math.isfinite(x) for x in (self.lower, self.upper)) or
                self.lower < 0 or self.lower > self.upper or self.unit not in ("kg/kg", "%") or
                (self.unit == "kg/kg" and self.upper >= 1) or not self.evidence or
                self.interpretation not in ("EXACT_SOURCE_STATISTIC", "ROUNDING_ONLY",
                    "EXTERNAL_UNCERTAINTY_INTERVAL", "SENSITIVITY_ONLY")):
            raise ValueError("P93COMPARE_INVALID_MEAN_INTERVAL")
        if self.interpretation == "EXACT_SOURCE_STATISTIC" and self.lower != self.upper:
            raise ValueError("P93COMPARE_NONZERO_EXACT_INTERVAL")


@dataclass(frozen=True)
class PressureBox:
    lower_Pa: tuple[float, ...]
    upper_Pa: tuple[float, ...]
    frame: str
    evidence: str
    interpretation: str = "FIXED_CONDITIONAL_REFERENCE"

    def __post_init__(self):
        object.__setattr__(self, "lower_Pa", tuple(float(x) for x in self.lower_Pa))
        object.__setattr__(self, "upper_Pa", tuple(float(x) for x in self.upper_Pa))
        lo, hi = np.asarray(self.lower_Pa), np.asarray(self.upper_Pa)
        if (lo.shape != hi.shape or lo.ndim != 1 or not len(lo) or
                not np.all(np.isfinite([lo, hi])) or np.any(lo > hi) or
                np.any(lo <= 30000) or np.any(hi >= 115000) or not self.frame or not self.evidence or
                self.interpretation not in ("FIXED_CONDITIONAL_REFERENCE",
                    "SENSITIVITY_BOX_NOT_CI", "EXTERNAL_INTERVAL_NOT_PROBABILITY")):
            raise ValueError("P93COMPARE_INVALID_EXTERNAL_PRESSURE_BOX")
        if self.interpretation == "FIXED_CONDITIONAL_REFERENCE" and not np.array_equal(lo, hi):
            raise ValueError("P93COMPARE_FIXED_PRESSURE_BOX_HAS_NONZERO_WIDTH")


def saturation_envelope(lo, hi, phase, formulation=MK):
    """Within-phase es is increasing; include both one-sided freezing values.

    WATER_ICE has an explicit branch at 273.15 K in the frozen formulation;
    its tiny discontinuity must not be silently replaced by a smooth curve.
    """
    a, b = saturation(lo, phase, formulation), saturation(hi, phase, formulation)
    lower, upper = np.minimum(a, b), np.maximum(a, b)
    if phase == "WATER_ICE":
        freezing = 273.15
        left = np.nextafter(freezing, -np.inf)
        for edge in (left, freezing):
            mask = (lo <= edge) & (edge <= hi)
            value = float(saturation(edge, phase, formulation))
            lower = np.where(mask, np.minimum(lower, value), lower)
            upper = np.where(mask, np.maximum(upper, value), upper)
    return lower, upper


def _upper_dual(caps, q_weights, rh_weights, coefficient, epsilon, mass):
    b = 1 - epsilon
    active = q_weights > 0
    max_lambda = float(np.max(np.divide(rh_weights * coefficient / epsilon, q_weights,
        out=np.zeros_like(q_weights), where=active)))

    def allocate(lam):
        if lam == 0:
            return np.where(rh_weights > 0, caps, 0.)
        ratio = np.divide(rh_weights * coefficient * epsilon, lam * q_weights,
            out=np.zeros_like(caps), where=active)
        q = np.clip((np.sqrt(ratio) - epsilon) / b, 0., caps)
        return np.where(~active & (rh_weights > 0), caps, q)

    if mass >= float(q_weights @ caps):
        lam = 0.
    elif mass == 0:
        lam = max_lambda
    else:
        left, right = 0., max_lambda
        for _ in range(90):
            mid = (left + right) / 2
            if float(q_weights @ allocate(mid)) > mass:
                left = mid
            else:
                right = mid
        lam = (left + right) / 2
    q = allocate(lam)
    value = rh_weights * coefficient * q / (epsilon + b * q)
    terms = value - lam * q_weights * q
    dual = float(lam * mass + np.sum(terms))
    # Guard cancellation, including an underfilled/overfilled numerical primal.
    guard = max(1e-7, 128 * np.finfo(float).eps *
                (abs(lam * mass) + float(np.sum(abs(terms))) + 1))
    return dual + guard, {"multiplier": lam, "roundoff_guard_pp": guard,
                          "primal_mass_residual": float(q_weights @ q) - mass}


def _lower_dual(caps, q_weights, coefficients, mass):
    if mass == 0:
        return 0., {"multiplier": 0., "roundoff_guard_pp": 0.}
    ratios = np.divide(coefficients, q_weights, out=np.full_like(caps, np.inf),
                       where=q_weights > 0)
    remaining, lam = mass, 0.
    for i in np.argsort(ratios, kind="stable"):
        if q_weights[i] == 0:
            continue
        lam = float(ratios[i])
        remaining -= min(remaining, q_weights[i] * caps[i])
        if remaining <= 1e-16:
            break
    terms = np.minimum(0., (coefficients - lam * q_weights) * caps)
    value = float(lam * mass + np.sum(terms))
    guard = max(1e-7, 128 * np.finfo(float).eps *
                (abs(lam * mass) + float(np.sum(abs(terms))) + 1))
    return max(0., value - guard), {"multiplier": lam, "roundoff_guard_pp": guard}


def identified_bounds(T_lower_K, T_upper_K, pressure: PressureBox,
                      q_target: MeanInterval, rh_target: MeanInterval,
                      q_weights, rh_weights, *, phase="WATER_ICE", formulation=MK):
    lo, hi = (np.asarray(x, float) for x in (T_lower_K, T_upper_K))
    pl, pu = np.asarray(pressure.lower_Pa), np.asarray(pressure.upper_Pa)
    if (lo.ndim != 1 or not len(lo) or hi.shape != lo.shape or pl.shape != lo.shape or
            not np.all(np.isfinite([lo, hi])) or np.any(lo > hi) or
            q_target.unit != "kg/kg" or rh_target.unit != "%"):
        raise ValueError("P93COMPARE_BOUND_ARRAYS_OR_UNITS")
    u, v = normalized_weights(q_weights, len(lo)), normalized_weights(rh_weights, len(lo))
    eps = epsilon_for(formulation)
    es_min, es_max = saturation_envelope(lo, hi, phase, formulation)
    caps = q_saturation(hi, pl, formulation)
    capacity = float(u @ caps)
    payload = {"T_lower_K": lo.tolist(), "T_upper_K": hi.tolist(),
        "pressure": asdict(pressure), "q_target": asdict(q_target),
        "rh_target": asdict(rh_target), "q_weights": u.tolist(), "rh_weights": v.tolist(),
        "phase": phase, "formulation": formulation}
    report = {"status": "BOUND_INCONCLUSIVE", "input_fingerprint": fingerprint(payload),
        "method": "CONCAVE_UPPER_DUAL_AND_LINEAR_CHORD_LOWER_DUAL",
        "scope": "ALL_PRESSURES_IN_DECLARED_RECTANGULAR_BOX_AND_DISCRETE_T_DOMAIN",
        "relaxed_constraints": ["donor_T_shape", "T_slopes", "required_extrema_attainment",
                                "pressure_correlation_with_T_q", "continuous_time_trajectory"],
        "pressure_interpretation": pressure.interpretation,
        "external_pressure_uncertainty_established": pressure.interpretation == "EXTERNAL_INTERVAL_NOT_PROBABILITY",
        "probability_or_confidence_interval": False,
        "q_target": asdict(q_target), "rh_target": asdict(rh_target),
        "q_mean_capacity_upper": capacity,
        "numerical_tolerances": {"q_mean_kgkg": Q_TOL, "RH_mean_pp": RH_TOL},
        "numerics": "FLOAT64_ANALYTIC_DUAL_WITH_EXPLICIT_ROUNDOFF_GUARDS",
        "source_feasibility_established": False,
        "physical_scope": "UNSATURATED_RELATIVE_TO_WATER_GAS_STATE",
        "independent_accuracy": "NOT_TESTED", "operational_ready": False,
        "production_epw_ready": False}
    if q_target.lower > capacity + Q_TOL:
        return {**report, "status": "CERTIFIED_INFEASIBLE",
                "reason": "Q_INTERVAL_ABOVE_DOMAIN_CAPACITY",
                "separation_q_kgkg": q_target.lower - capacity}
    q_low, q_high = max(0., q_target.lower - Q_TOL), min(capacity, q_target.upper + Q_TOL)
    upper, upper_info = _upper_dual(caps, u, v, 100 * pu / es_min, eps, q_high)
    # e(q,p_lower)/q >= p_lower/(eps+(1-eps)*caps) on [0,caps].
    coefficients = v * 100 * pl / ((eps + (1 - eps) * caps) * es_max)
    lower, lower_info = _lower_dual(caps, u, coefficients, q_low)
    if lower > upper + 1e-6:
        raise ArithmeticError("P93COMPARE_INVALID_OUTER_BOUND_ORDER")
    report.update(RH_mean_lower_pp=lower, RH_mean_upper_pp=upper,
                  upper_dual=upper_info, lower_dual=lower_info)
    if rh_target.lower > upper + RH_TOL:
        report.update(status="CERTIFIED_INFEASIBLE", reason="RH_INTERVAL_ABOVE_DOMAIN_UPPER",
                      separation_RH_pp=rh_target.lower - upper)
    elif rh_target.upper < lower - RH_TOL:
        report.update(status="CERTIFIED_INFEASIBLE", reason="RH_INTERVAL_BELOW_DOMAIN_LOWER",
                      separation_RH_pp=lower - rh_target.upper)
    else:
        report["reason"] = "OUTER_BOUNDS_DO_NOT_ESTABLISH_FEASIBILITY"
    return report


def summarize_scenarios(reports):
    """A nonexcluded box is not a witness; finite scenarios are not a continuum."""
    if not reports:
        raise ValueError("P93COMPARE_EMPTY_SCENARIO_SET")
    certified = sum(r["status"] == "CERTIFIED_INFEASIBLE" for r in reports)
    return {"scenario_count": len(reports), "certified_infeasible": certified,
            "status": ("ALL_DECLARED_SCENARIOS_CERTIFIED_INFEASIBLE" if certified == len(reports)
                       else "SOME_DECLARED_SCENARIOS_NOT_EXCLUDED"),
            "source_feasibility_established": False,
            "scope": "ONLY_THE_DECLARED_SCENARIOS_NOT_UNSPECIFIED_OPERATORS"}
