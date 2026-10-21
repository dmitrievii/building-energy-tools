"""Declared finite-node observation operators, without inventing NASA bounds.

These are discrete operators. They do not certify continuous-time extrema or
integration accuracy. Zero weights support different q/RH averaging windows.
An assumed interval remains a hypothesis even when its coordinates are known.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import numpy as np

from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_thermodynamics import MK, relative_humidity


def normalized_weights(values, n=None):
    w = np.asarray(values, dtype=float)
    if (w.ndim != 1 or not len(w) or (n is not None and len(w) != n) or
            not np.all(np.isfinite(w)) or np.any(w < 0) or
            abs(float(w.sum()) - 1) > 1e-12):
        raise ValueError("P93COMPARE_NONNEGATIVE_NORMALIZED_WEIGHTS_REQUIRED")
    return w.copy()


@dataclass(frozen=True)
class IntervalSupport:
    start_seconds: float
    end_seconds: float
    calendar: str
    evidence: str
    status: str = "ASSUMED"

    def __post_init__(self):
        if (not all(math.isfinite(x) for x in (self.start_seconds, self.end_seconds)) or
                self.start_seconds >= self.end_seconds or not self.evidence or
                self.status not in ("VERIFIED", "ASSUMED", "UNKNOWN") or
                self.calendar not in ("365_day", "noleap", "gregorian", "standard",
                                      "proleptic_gregorian")):
            raise ValueError("P93COMPARE_INVALID_INTERVAL_SUPPORT")


@dataclass(frozen=True)
class DiscreteOperator:
    variable: str
    method: str
    weights: tuple[float, ...]
    unit: str
    spatial_support: str
    evidence: str
    interval: IntervalSupport | None = None
    hypothesis: str = ""
    phase: str | None = None
    independent_observation: bool = True

    def __post_init__(self):
        object.__setattr__(self, "weights", tuple(normalized_weights(self.weights)))
        if (self.method not in ("MEAN", "MINIMUM", "MAXIMUM", "MIDRANGE") or
                not self.variable or not self.unit or not self.spatial_support or not self.evidence):
            raise ValueError("P93COMPARE_INVALID_OBSERVATION_OPERATOR")
        units = {"tas": "K", "tasmin": "K", "tasmax": "K", "huss": "kg/kg",
                 "hurs": "%", "pressure": "Pa"}
        if self.variable in units and self.unit != units[self.variable]:
            raise ValueError("P93COMPARE_OBSERVATION_OPERATOR_UNITS")
        if self.interval is not None and not isinstance(self.interval, IntervalSupport):
            raise ValueError("P93COMPARE_INTERVAL_TYPE_REQUIRED")
        if (self.interval is None or self.interval.status != "VERIFIED") and not self.hypothesis:
            raise ValueError("P93COMPARE_UNKNOWN_INTERVAL_NEEDS_EXPLICIT_HYPOTHESIS")
        if self.variable == "hurs" and self.phase not in ("WATER", "ICE", "WATER_ICE"):
            raise ValueError("P93COMPARE_RH_PHASE_REQUIRED")
        if self.variable == "tas" and self.method == "MIDRANGE" and self.independent_observation:
            raise ValueError("P93COMPARE_MIDRANGE_IS_NOT_AN_INDEPENDENT_T_MEAN")

    @property
    def fingerprint(self):
        return fingerprint(asdict(self))

    def evaluate(self, values):
        a = np.asarray(values, dtype=float)
        w = normalized_weights(self.weights, len(a) if a.ndim == 1 else -1)
        if a.shape != w.shape or not np.all(np.isfinite(a)):
            raise ValueError("P93COMPARE_OPERATOR_ARRAY_ALIGNMENT")
        selected = a[w > 0]
        if self.method == "MEAN":
            return float(w @ a)
        if self.method == "MINIMUM":
            return float(selected.min())
        if self.method == "MAXIMUM":
            return float(selected.max())
        return float((selected.min() + selected.max()) / 2)

    def metadata(self):
        return {**asdict(self), "fingerprint": self.fingerprint,
                "interval_verified": self.interval is not None and self.interval.status == "VERIFIED",
                "evaluation_scope": "DECLARED_DISCRETE_NODES_NOT_CONTINUOUS_TIME",
                "spatial_operator_identified": False}


def humidity_means(T_K, p_Pa, q_kgkg, q_operator, rh_operator, formulation=MK):
    if (q_operator.variable != "huss" or rh_operator.variable != "hurs" or
            q_operator.method != "MEAN" or rh_operator.method != "MEAN"):
        raise ValueError("P93COMPARE_HUSS_HURS_MEAN_OPERATORS_REQUIRED")
    t, p, q = (np.asarray(x, float) for x in (T_K, p_Pa, q_kgkg))
    if t.ndim != 1 or p.shape != t.shape or q.shape != t.shape:
        raise ValueError("P93COMPARE_STATE_ARRAY_ALIGNMENT")
    return {"q_mean_kgkg": q_operator.evaluate(q),
            "RH_mean_pp": rh_operator.evaluate(relative_humidity(t, p, q,
                                                 rh_operator.phase, formulation)),
            "mean_q_is_not_a_column_water_mass_balance": True}
