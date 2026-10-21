"""P1 hydrostatic candidate with actual sensor references and explicit proxies.

An externally prescribed lapse or isothermal column is a conditional model,
not a measured profile or a qualified station-pressure prediction. B4's
independent negative result is preserved. No observation residual is fitted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import numpy as np

from p9_3b3_compare_vertical_frame import (G0, PressureSeries, VerticalCoordinate,
                                         height_difference, require_generation_reference)
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_thermodynamics import RD, RV


@dataclass(frozen=True)
class PressureCandidate:
    pressure: PressureSeries
    method: str
    proxy_source: str
    lapse_K_per_m: float
    log_pressure_ratio: tuple[float, ...]

    def metadata(self):
        return {"method": self.method, "proxy_source": self.proxy_source,
                "lapse_K_per_m": self.lapse_K_per_m,
                "coordinate": asdict(self.pressure.coordinate),
                "pressure_fingerprint": self.pressure.fingerprint,
                "profile_status": "EXTERNAL_COLUMN_ASSUMPTION_NOT_NATIVE_MEASURED_PROFILE",
                "height_approximation": ("CONSTANT_G0_GEOMETRIC_HEIGHT" if
                    self.pressure.coordinate.kind == "GEOMETRIC_M" else "GEOPOTENTIAL_HEIGHT"),
                "code_status": "REQUIRES_SEPARATE_TEST_RESULTS",
                "physical_scope": "CONDITIONAL_HYDROSTATIC_GAS_COLUMN",
                "independent_accuracy": "NOT_ESTABLISHED",
                "pressure_model_qualified": False, "operational_ready": False,
                "production_epw_ready": False, "B4_negative_result_retained": True}


def hydrostatic_pressure(anchor: PressureSeries, target: VerticalCoordinate,
                         T_target_K, q_target_kgkg, *, proxy_source, proxy_date,
                         lapse_K_per_m=0.0065):
    require_generation_reference(anchor, target)
    if proxy_date != anchor.reference_date or not proxy_source:
        raise ValueError("P93COMPARE_PROXY_DATE_AND_PROVENANCE_REQUIRED")
    if not np.isfinite(lapse_K_per_m) or not 0 <= lapse_K_per_m <= .02:
        raise ValueError("P93COMPARE_LAPSE_OUTSIDE_DECLARED_DOMAIN")
    p = np.asarray(anchor.values_Pa)
    t, q = (np.asarray(x, float) for x in (T_target_K, q_target_kgkg))
    if (t.shape != p.shape or q.shape != p.shape or not np.all(np.isfinite([t, q])) or
            np.any((t <= 173) | (t >= 332)) or np.any((q < 0) | (q >= .1))):
        raise ValueError("P93COMPARE_COLUMN_PROXY_ARRAY_OR_DOMAIN")
    dz = height_difference(anchor.coordinate, target)
    factor = 1 + (RV / RD - 1) * q
    tv = t * factor
    gamma = lapse_K_per_m * factor
    # T_target is at the target level; T_anchor = T_target + Gamma * dz.
    if np.any(tv + gamma * dz <= 0):
        raise ValueError("P93COMPARE_NONPOSITIVE_ANCHOR_VIRTUAL_T")
    if lapse_K_per_m == 0:
        log_ratio = -G0 * dz / (RD * tv)
        method = "P1_ISOTHERMAL_DECLARED_COLUMN"
    else:
        log_ratio = -G0 / (RD * gamma) * np.log1p(gamma * dz / tv)
        method = "P1_FIXED_LAPSE_DECLARED_COLUMN"
    derived = PressureSeries(tuple(p * np.exp(log_ratio)), target, anchor.reference_date,
        anchor.source + "|" + method + "|" + proxy_source, anchor.time_support,
        source_sha256=anchor.fingerprint)
    return PressureCandidate(derived, method, proxy_source, lapse_K_per_m, tuple(log_ratio))


def to_legacy_reference(candidate):
    """Adapter returns a new immutable input; it never changes frozen B3 code."""
    p = candidate.pressure
    if p.coordinate.role != "THERMO_SENSOR":
        raise ValueError("P93COMPARE_THERMODYNAMIC_SENSOR_PRESSURE_REQUIRED")
    require_generation_reference(p, p.coordinate)
    return PressureReference(p.values_Pa, p.source,
        "P1|" + "|".join((p.coordinate.role, p.coordinate.kind, p.coordinate.datum)),
        mode="SITE_HYDROSTATIC_PROVISIONAL", height_m=p.coordinate.metres,
        source_sha256=p.fingerprint, reference_date=p.reference_date,
        time_support=p.time_support)
