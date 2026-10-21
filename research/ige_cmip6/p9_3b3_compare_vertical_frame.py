"""Explicit vertical references for the P1/C1 comparison, never inferred heights.

No geoid/ellipsoid transformation is supplied by this module. Coordinates in
different datums or different height representations must not be subtracted.
The geometric-height P1 calculation is explicitly a constant-g approximation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime as dt
import hashlib
import json
import math


G0 = 9.80665
HEIGHT_KINDS = ("GEOMETRIC_M", "GEOPOTENTIAL_HEIGHT_M", "GEOPOTENTIAL_M2_S2")
HEIGHT_ROLES = ("MSL_REFERENCE", "GRID_SURFACE", "STATION_GROUND", "BAROMETER", "THERMO_SENSOR")


class SourceBlocked(ValueError):
    """A missing reference is a source limitation, not solver infeasibility."""


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class VerticalCoordinate:
    value: float
    kind: str
    datum: str
    role: str
    evidence: str
    verified: bool = False

    def __post_init__(self):
        if (not math.isfinite(self.value) or self.kind not in HEIGHT_KINDS or
                self.role not in HEIGHT_ROLES or not self.datum or not self.evidence):
            raise ValueError("P93COMPARE_INVALID_VERTICAL_COORDINATE")
        if self.role == "MSL_REFERENCE" and (self.value != 0 or self.datum != "MSL_GEOID"):
            raise ValueError("P93COMPARE_MSL_REFERENCE_MUST_BE_GEOID_ZERO")

    @property
    def metres(self):
        """Value in its own height system, not a datum transformation."""
        return self.value / G0 if self.kind == "GEOPOTENTIAL_M2_S2" else self.value


def height_difference(anchor, target):
    if anchor.datum != target.datum or anchor.kind != target.kind:
        raise SourceBlocked("P93COMPARE_VERTICAL_TRANSFORMATION_NOT_ESTABLISHED")
    if anchor.datum not in ("MSL_GEOID", "GEOPOTENTIAL_ZERO"):
        raise SourceBlocked("P93COMPARE_UNSUPPORTED_VERTICAL_DATUM")
    return target.metres - anchor.metres


@dataclass(frozen=True)
class PressureSeries:
    values_Pa: tuple[float, ...]
    coordinate: VerticalCoordinate
    reference_date: str
    source: str
    time_support: str
    usage: str = "EXTERNAL_MODEL_INPUT"
    source_sha256: str = ""

    def __post_init__(self):
        object.__setattr__(self, "values_Pa", tuple(float(x) for x in self.values_Pa))
        dt.date.fromisoformat(self.reference_date)
        if (not self.values_Pa or any(not math.isfinite(x) or not 30000 < x < 115000
                                     for x in self.values_Pa)):
            raise ValueError("P93COMPARE_PRESSURE_PA_DOMAIN_OR_UNITS")
        if (not isinstance(self.coordinate, VerticalCoordinate) or not self.source or
                not self.time_support or self.usage not in
                ("EXTERNAL_MODEL_INPUT", "OBSERVED_VALIDATION_ONLY")):
            raise ValueError("P93COMPARE_PRESSURE_SEMANTICS_REQUIRED")
        if self.source_sha256 and (len(self.source_sha256) != 64 or
                                   any(c not in "0123456789abcdef" for c in self.source_sha256)):
            raise ValueError("P93COMPARE_SOURCE_SHA256_REQUIRED")

    @property
    def fingerprint(self):
        return fingerprint(asdict(self))


def require_generation_reference(series, target):
    if series.usage != "EXTERNAL_MODEL_INPUT":
        raise ValueError("P93COMPARE_OBSERVED_TEST_PRESSURE_FORBIDDEN")
    if target.role not in ("BAROMETER", "THERMO_SENSOR"):
        raise SourceBlocked("P93COMPARE_SENSOR_HEIGHT_REQUIRED_NOT_STATION_GROUND")
    if not series.coordinate.verified or not target.verified:
        raise SourceBlocked("P93COMPARE_VERIFIED_ANCHOR_AND_SENSOR_HEIGHT_REQUIRED")
    height_difference(series.coordinate, target)
