"""Immutable, source-typed absolute pressure. B4 is NOT skill-qualified."""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
import hashlib
import json
import math

from p9_3b2d_canonical_pressure_fields import original_absolute_station_pressure, pressure_qc_tier

MODES = ("ERA5_GRID_PROVISIONAL", "SITE_HYDROSTATIC_PROVISIONAL",
         "OBSERVED_SITE_VALIDATION_ONLY", "NATIVE_GCM_HIGH_FREQUENCY")


@dataclass(frozen=True)
class PressureReference:
    values_Pa: tuple[float, ...]
    source: str
    frame: str
    mode: str = "ERA5_GRID_PROVISIONAL"
    height_m: float | None = None
    source_sha256: str = ""
    uncertainty_Pa: float | None = None
    uncertainty_calibrated: bool = False
    native_qc: str = "NOT_CERTIFIED"
    time_support: str = "REPRESENTATIVE_NODES"
    reference_date: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "values_Pa", tuple(float(v) for v in self.values_Pa))
        if self.mode not in MODES or not self.source or not self.frame:
            raise ValueError("P93B3_PRESSURE_REFERENCE_SEMANTICS_REQUIRED")
        if self.mode == "NATIVE_GCM_HIGH_FREQUENCY":
            raise ValueError("P93B3_NATIVE_GCM_PS_NOT_RECOVERED_SOURCE_ADAPTER_REQUIRED")
        if not self.values_Pa or any(not math.isfinite(v) or not 30000 < v < 115000 for v in self.values_Pa):
            raise ValueError("P93B3_INVALID_ABSOLUTE_PRESSURE_PA")
        if self.height_m is not None and not math.isfinite(self.height_m):
            raise ValueError("P93B3_NONFINITE_REFERENCE_HEIGHT")
        if self.source_sha256 and (len(self.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.source_sha256)):
            raise ValueError("P93B3_INVALID_PRESSURE_SOURCE_SHA")
        if self.uncertainty_Pa is not None and (not math.isfinite(self.uncertainty_Pa) or self.uncertainty_Pa <= 0):
            raise ValueError("P93B3_INVALID_PRESSURE_UNCERTAINTY")
        if self.uncertainty_calibrated and self.uncertainty_Pa is None:
            raise ValueError("P93B3_PRESSURE_UNCERTAINTY_NOT_ESTABLISHED")
        if self.mode == "SITE_HYDROSTATIC_PROVISIONAL" and self.height_m is None:
            raise ValueError("P93B3_SITE_REFERENCE_HEIGHT_REQUIRED")
        if self.reference_date is not None:
            import datetime
            datetime.date.fromisoformat(self.reference_date)

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, allow_nan=False).encode()).hexdigest()

    def metadata(self):
        d = asdict(self)
        d.pop("values_Pa")
        return {**d, "fingerprint": self.fingerprint, "pressure_model_qualified": False,
                "B4_independent_negative_result_retained": True}

    def stress(self, delta_Pa):
        """Symmetric sensitivity, NOT a calibrated confidence interval."""
        if delta_Pa not in (-500, 0, 500):
            raise ValueError("P93B3_UNREGISTERED_PRESSURE_STRESS")
        return replace(self, values_Pa=tuple(v + delta_Pa for v in self.values_Pa),
                       source=self.source + f"|STRESS_{delta_Pa:+d}_PA_NOT_CI")


def station_pressure(row, product):
    p = original_absolute_station_pressure(row, product)
    return (None if p is None else 100 * p), pressure_qc_tier(row, product)
