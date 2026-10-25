"""Explicit clocks, physical definitions and separate qualification axes.

Rows describe [start, start + one hour). State variables are sampled at the
right endpoint; interval energies and amounts cover the entire interval.
This convention is explicit per field and matches the EPW endpoint contract.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any, Literal

import numpy as np
import pandas as pd

from ..climate_model import CanonicalClimateDataset, ClimateLocation


def finite_number(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"IGE_INVALID_FINITE_{label}")
    return float(value)


@dataclass(frozen=True)
class HistoricalRequest:
    latitude: float
    longitude: float
    year: int
    utc_offset_minutes: int
    label: str = "IGE background"
    mode: Literal["grid_background"] = "grid_background"
    site_elevation_m: float | None = None
    site_elevation_reference: str = ""

    def __post_init__(self) -> None:
        if not -90 <= finite_number(self.latitude, "LATITUDE") <= 90:
            raise ValueError("IGE_LATITUDE_OUT_OF_RANGE")
        if not -180 <= finite_number(self.longitude, "LONGITUDE") <= 180:
            raise ValueError("IGE_LONGITUDE_OUT_OF_RANGE")
        if isinstance(self.year, bool) or not isinstance(self.year, int) or not 1901 <= self.year <= 2098:
            raise ValueError("IGE_INVALID_HISTORICAL_YEAR")
        offset = self.utc_offset_minutes
        if isinstance(offset, bool) or not isinstance(offset, int) or not -720 <= offset <= 720:
            raise ValueError("IGE_INVALID_FIXED_STANDARD_OFFSET")
        if offset % 60:
            raise ValueError("IGE_FRACTIONAL_OFFSET_REQUIRES_EXPLICIT_REBINNING_NOT_IMPLEMENTED")
        if self.mode != "grid_background":
            raise ValueError("IGE_LOCAL_RECONSTRUCTION_NOT_IMPLEMENTED")
        if not self.label.strip() or len(self.label) > 120 or any(c in self.label for c in ",\n\r\x00"):
            raise ValueError("IGE_INVALID_LOCATION_LABEL")
        if self.site_elevation_m is not None:
            if not -500 <= finite_number(self.site_elevation_m, "SITE_HEIGHT") <= 9000:
                raise ValueError("IGE_SITE_HEIGHT_OUT_OF_RANGE")
            if not self.site_elevation_reference.strip():
                raise ValueError("IGE_SITE_HEIGHT_REQUIRES_REFERENCE_AND_DATUM")

    @property
    def standard_timezone(self) -> timezone:
        return timezone(timedelta(minutes=self.utc_offset_minutes))

    @property
    def local_starts(self) -> pd.DatetimeIndex:
        start = datetime(self.year, 1, 1, tzinfo=self.standard_timezone)
        stop = datetime(self.year + 1, 1, 1, tzinfo=self.standard_timezone)
        return pd.date_range(start, stop, freq="h", inclusive="left", name="interval_start_local_standard")

    @property
    def utc_starts(self) -> pd.DatetimeIndex:
        return self.local_starts.tz_convert("UTC").rename("interval_start_utc")

    @property
    def utc_ends(self) -> pd.DatetimeIndex:
        return self.utc_starts + pd.Timedelta(hours=1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FutureRequest:
    """B-M/B-D identity. No future generator is activated by this contract."""
    historical_base_sha256: str
    model: str
    member: str
    scenario: str
    historical_window: tuple[int, int]
    future_window: tuple[int, int]
    semantics_version: str
    representative_pattern_year: int
    method: Literal["monthly_morph", "daily_joint"] = "monthly_morph"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.historical_base_sha256):
            raise ValueError("IGE_FUTURE_REQUIRES_HASHED_HISTORICAL_BASE")
        if any(not x.strip() for x in (self.model, self.member, self.semantics_version)):
            raise ValueError("IGE_FUTURE_IDENTITY_OR_SEMANTICS_MISSING")
        if self.scenario not in ("ssp126", "ssp245", "ssp370", "ssp585"):
            raise ValueError("IGE_UNSUPPORTED_SCENARIO")
        if self.method not in ("monthly_morph", "daily_joint"):
            raise ValueError("IGE_UNSUPPORTED_FUTURE_METHOD")
        for window in (self.historical_window, self.future_window):
            if len(window) != 2 or any(isinstance(y, bool) or not isinstance(y, int) for y in window) or not 1850 <= window[0] <= window[1] <= 2300:
                raise ValueError("IGE_INVALID_CLIMATE_WINDOW")
        if (isinstance(self.representative_pattern_year, bool) or not isinstance(self.representative_pattern_year, int)
                or not 1901 <= self.representative_pattern_year <= 2098):
            raise ValueError("IGE_INVALID_REPRESENTATIVE_YEAR")


@dataclass(frozen=True)
class FieldDefinition:
    unit: str
    operator: Literal["instant_at_interval_end", "interval_energy", "interval_amount"]
    source_id: str
    vertical_reference: str
    definition: str

    def __post_init__(self) -> None:
        if not all((self.unit, self.source_id, self.vertical_reference, self.definition)):
            raise ValueError("IGE_INCOMPLETE_FIELD_DEFINITION")
        if self.operator not in ("instant_at_interval_end", "interval_energy", "interval_amount"):
            raise ValueError("IGE_UNKNOWN_FIELD_TIME_OPERATOR")


@dataclass(frozen=True)
class QualityStatus:
    execution_correctness: str
    physical_admissibility: str
    independent_accuracy: str
    operational_and_application_scope: str
    production_ready: bool = False


@dataclass(frozen=True)
class ClimateResult:
    request: HistoricalRequest
    data: pd.DataFrame = field(repr=False, compare=False)
    location: ClimateLocation
    fields: dict[str, FieldDefinition]
    sources: tuple[dict[str, Any], ...]
    transformations: tuple[dict[str, Any], ...]
    adjustments: tuple[dict[str, Any], ...]
    quality: QualityStatus
    diagnostics: dict[str, Any]

    def __post_init__(self) -> None:
        self.validate_contract()
        object.__setattr__(self, "data", self.data.copy(deep=True))

    def validate_contract(self) -> None:
        """Recheck before serialization: pandas frames remain user-mutable."""
        frame = self.data
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise ValueError("IGE_RESULT_REQUIRES_AWARE_UTC_CLOCK")
        if not frame.index.equals(self.request.utc_starts):
            raise ValueError("IGE_RESULT_MISSING_DUPLICATE_SHIFTED_OR_REORDERED_HOUR")
        if set(frame.columns) != set(self.fields):
            raise ValueError("IGE_RESULT_EVERY_FIELD_REQUIRES_EXPLICIT_SEMANTICS")
        if not np.isfinite(frame.to_numpy(dtype=float)).all():
            raise ValueError("IGE_RESULT_MISSING_OR_NONFINITE_FIELD_NO_SILENT_FILL")
        source_ids = {s["id"] for s in self.sources}
        if len(source_ids) != len(self.sources) or any(f.source_id not in source_ids for f in self.fields.values()):
            raise ValueError("IGE_RESULT_SOURCE_LINEAGE_INCOMPLETE")

    def to_canonical(self) -> CanonicalClimateDataset:
        """Preserve historical dates; do not pass through typical-year EPW import.

        RH retains the provider's liquid-water Magnus definition and rounding.
        No app ASHRAE water/ice humidity ratio is inferred in this adapter.
        """
        from ..climate_model import ClimateProvenance, ClimateTemporalMetadata
        self.validate_contract()
        frame = self.data.copy(deep=True)
        frame.index = self.request.local_starts
        frame.attrs["ige_field_definitions"] = {k: asdict(v) for k, v in self.fields.items()}
        frame.attrs["ige_quality_status"] = asdict(self.quality)
        frame.attrs["ige_state_sample_offset_minutes_from_row_start"] = 60
        frame.attrs["ige_RH_phase"] = "PROVIDER_MAGNUS_LIQUID_WATER_NOT_APP_ASHRAE_ICE_BELOW_ZERO"
        return CanonicalClimateDataset(
            climate_id=f"ige-background-{self.request.year}-{self.request.latitude}-{self.request.longitude}",
            display_name=f"{self.request.label} {self.request.year} — research grid background",
            data=frame, location=self.location,
            temporal=ClimateTemporalMetadata(60, "historical", str(self.request.standard_timezone),
                "interval_start", (self.request.year,)),
            provenance=ClimateProvenance("Open-Meteo / NASA POWER", "ERA5-derived / SYN1deg longwave",
                "IGE engine", "historical background assembly", notes=(
                    "States at interval end; energies and amounts over the interval. See ige_field_definitions.",
                    "No local height correction or independent station qualification.",
                    "Provider RH is liquid-water Magnus; no automatic ASHRAE ice-phase conversion or humidity ratio.",
                )),
        )


def specific_humidity_to_mixing_ratio_g_kg(q_kg_kg: np.ndarray) -> np.ndarray:
    """q is water mass / moist-air mass; w is water mass / dry-air mass."""
    q = np.asarray(q_kg_kg, dtype=float)
    if not np.isfinite(q).all() or np.any((q < 0) | (q >= 1)):
        raise ValueError("IGE_SPECIFIC_HUMIDITY_DOMAIN")
    return 1000 * q / (1 - q)
