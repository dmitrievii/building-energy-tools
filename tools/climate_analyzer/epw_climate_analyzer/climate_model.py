"""Canonical climate-data model shared by current and future source adapters.

The Climate Analyzer started with EPW files, where one parsed dataframe carried
both source-specific calendar semantics and the normalized columns consumed by
the analysis pages.  Future sources (for example measured 10-minute station
data) must not be forced through EPW-specific assumptions such as a synthetic
typical year.  This module therefore defines a small canonical boundary:

* source adapters map provider fields to canonical variable names;
* spatial, temporal and provenance metadata are explicit and immutable;
* real historical timestamps stay real historical timestamps;
* typical-year EPW data remain explicitly marked as a typical-year calendar;
* temporal upsampling is never implied by the canonical model.

The model is deliberately independent of Streamlit and provider SDKs so it can
be used by ingestion, comparison, export and validation code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

import pandas as pd

from .epw_parser import EpwFile


CalendarMode = Literal["typical_year", "historical", "forecast", "climatology"]
IntervalSemantics = Literal["interval_start", "interval_end", "instantaneous", "unknown"]
AggregationSemantics = Literal["mean", "sum", "circular mean"]


@dataclass(frozen=True)
class CanonicalVariable:
    """Metadata contract for one canonical climate variable."""

    column: str
    unit: str
    unit_family: str
    aggregation: AggregationSemantics
    description: str


CANONICAL_VARIABLES: dict[str, CanonicalVariable] = {
    "dry_bulb_temperature_c": CanonicalVariable(
        "dry_bulb_temperature_c", "°C", "temperature", "mean", "Outdoor dry-bulb air temperature"
    ),
    "dew_point_temperature_c": CanonicalVariable(
        "dew_point_temperature_c", "°C", "temperature", "mean", "Outdoor dew-point temperature"
    ),
    "wet_bulb_temperature_c": CanonicalVariable(
        "wet_bulb_temperature_c", "°C", "temperature", "mean", "Outdoor wet-bulb temperature"
    ),
    "relative_humidity_pct": CanonicalVariable(
        "relative_humidity_pct", "%", "relative humidity", "mean", "Outdoor relative humidity"
    ),
    "humidity_ratio_g_kg": CanonicalVariable(
        "humidity_ratio_g_kg", "g/kg dry air", "humidity ratio", "mean", "Humidity ratio"
    ),
    "moist_air_enthalpy_kj_kg": CanonicalVariable(
        "moist_air_enthalpy_kj_kg", "kJ/kg dry air", "enthalpy", "mean", "Moist-air specific enthalpy"
    ),
    "specific_volume_m3_kg": CanonicalVariable(
        "specific_volume_m3_kg", "m³/kg dry air", "specific volume", "mean", "Moist-air specific volume"
    ),
    "moist_air_density_kg_m3": CanonicalVariable(
        "moist_air_density_kg_m3", "kg/m³", "density", "mean", "Moist-air density"
    ),
    "atmospheric_station_pressure_pa": CanonicalVariable(
        "atmospheric_station_pressure_pa", "Pa", "pressure", "mean", "Atmospheric station pressure"
    ),
    "global_horizontal_radiation_wh_m2": CanonicalVariable(
        "global_horizontal_radiation_wh_m2", "Wh/m²", "irradiation", "sum", "Global horizontal irradiation per source interval"
    ),
    "direct_normal_radiation_wh_m2": CanonicalVariable(
        "direct_normal_radiation_wh_m2", "Wh/m²", "irradiation", "sum", "Direct normal irradiation per source interval"
    ),
    "diffuse_horizontal_radiation_wh_m2": CanonicalVariable(
        "diffuse_horizontal_radiation_wh_m2", "Wh/m²", "irradiation", "sum", "Diffuse horizontal irradiation per source interval"
    ),
    "global_horizontal_illuminance_lux": CanonicalVariable(
        "global_horizontal_illuminance_lux", "lux", "illuminance", "mean", "Global horizontal illuminance"
    ),
    "direct_normal_illuminance_lux": CanonicalVariable(
        "direct_normal_illuminance_lux", "lux", "illuminance", "mean", "Direct normal illuminance"
    ),
    "diffuse_horizontal_illuminance_lux": CanonicalVariable(
        "diffuse_horizontal_illuminance_lux", "lux", "illuminance", "mean", "Diffuse horizontal illuminance"
    ),
    "wind_speed_m_s": CanonicalVariable(
        "wind_speed_m_s", "m/s", "wind speed", "mean", "Wind speed"
    ),
    "wind_direction_deg": CanonicalVariable(
        "wind_direction_deg", "deg", "direction", "circular mean", "Wind direction clockwise from north"
    ),
    "total_sky_cover_tenths": CanonicalVariable(
        "total_sky_cover_tenths", "tenths", "sky cover", "mean", "Total sky cover"
    ),
    "opaque_sky_cover_tenths": CanonicalVariable(
        "opaque_sky_cover_tenths", "tenths", "sky cover", "mean", "Opaque sky cover"
    ),
    "liquid_precipitation_depth_mm": CanonicalVariable(
        "liquid_precipitation_depth_mm", "mm", "precipitation", "sum", "Liquid precipitation depth per reported source interval"
    ),
    "snow_depth_cm": CanonicalVariable(
        "snow_depth_cm", "cm", "snow depth", "mean", "Snow depth state"
    ),
}


@dataclass(frozen=True)
class ClimateLocation:
    """Canonical spatial metadata for a point or representative climate site."""

    latitude: float
    longitude: float
    elevation_m: float | None = None
    city: str = ""
    state: str = ""
    country: str = ""
    station_id: str = ""

    def __post_init__(self) -> None:
        if not -90.0 <= float(self.latitude) <= 90.0:
            raise ValueError("Climate latitude must be between -90 and 90 degrees.")
        if not -180.0 <= float(self.longitude) <= 180.0:
            raise ValueError("Climate longitude must be between -180 and 180 degrees.")


@dataclass(frozen=True)
class ClimateTemporalMetadata:
    """Explicit time-axis semantics independent of the data provider."""

    native_interval_minutes: int
    calendar_mode: CalendarMode
    timezone_name: str
    interval_semantics: IntervalSemantics
    source_years: tuple[int, ...] = ()
    canonical_year: int | None = None

    def __post_init__(self) -> None:
        if int(self.native_interval_minutes) <= 0:
            raise ValueError("Native climate interval must be a positive number of minutes.")
        if not str(self.timezone_name).strip():
            raise ValueError("Climate timezone metadata must not be empty.")
        if self.calendar_mode == "typical_year" and self.canonical_year is None:
            raise ValueError("Typical-year data require an explicit canonical plotting year.")


@dataclass(frozen=True)
class ClimateProvenance:
    """Provider/source provenance retained across all analysis adapters."""

    provider: str
    dataset: str
    source_format: str
    source_name: str
    source_reference: str = ""
    provider_station_id: str = ""
    retrieval_time_utc: str = ""
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider, "provider"),
            (self.dataset, "dataset"),
            (self.source_format, "source format"),
            (self.source_name, "source name"),
        ):
            if not str(value).strip():
                raise ValueError(f"Climate provenance {label} must not be empty.")


@dataclass(frozen=True)
class CanonicalClimateDataset:
    """One normalized climate dataset with explicit metadata and provenance."""

    climate_id: str
    display_name: str
    data: pd.DataFrame = field(repr=False, compare=False)
    location: ClimateLocation
    temporal: ClimateTemporalMetadata
    provenance: ClimateProvenance

    def __post_init__(self) -> None:
        if not str(self.climate_id).strip():
            raise ValueError("Canonical climate_id must not be empty.")
        if not str(self.display_name).strip():
            raise ValueError("Canonical climate display_name must not be empty.")
        validated = validate_canonical_frame(self.data)
        object.__setattr__(self, "data", validated)
        inferred = infer_native_resolution_minutes(validated.index)
        # Gaps are allowed in historical observations, therefore only reject an
        # explicit cadence that is finer than the actually represented minimum
        # positive spacing. A declared 10-minute station remains valid even if
        # some observations are missing and the median gap becomes 20 minutes.
        positive = _positive_interval_minutes(validated.index)
        if positive and self.temporal.native_interval_minutes < min(positive):
            raise ValueError(
                "Declared native interval is finer than any timestamp spacing present in the canonical frame."
            )
        validated.attrs.setdefault("canonical_native_interval_minutes", self.temporal.native_interval_minutes)
        validated.attrs.setdefault("canonical_calendar_mode", self.temporal.calendar_mode)
        validated.attrs.setdefault("canonical_timezone_name", self.temporal.timezone_name)
        validated.attrs.setdefault("canonical_inferred_interval_minutes", inferred)

    @property
    def start(self) -> pd.Timestamp:
        return pd.Timestamp(self.data.index.min())

    @property
    def end(self) -> pd.Timestamp:
        return pd.Timestamp(self.data.index.max())

    @property
    def available_canonical_variables(self) -> tuple[str, ...]:
        return tuple(column for column in CANONICAL_VARIABLES if column in self.data.columns)


def _positive_interval_minutes(index: pd.DatetimeIndex) -> list[int]:
    idx = pd.DatetimeIndex(index).sort_values().unique()
    if len(idx) < 2:
        return []
    minutes: list[int] = []
    for delta in idx[1:] - idx[:-1]:
        value = int(round(float(delta / pd.Timedelta(minutes=1))))
        if value > 0:
            minutes.append(value)
    return minutes


def infer_native_resolution_minutes(index: pd.DatetimeIndex) -> int:
    """Infer the median positive timestamp spacing in whole minutes."""
    positive = _positive_interval_minutes(pd.DatetimeIndex(index))
    if not positive:
        return 60
    return max(1, int(round(float(pd.Series(positive, dtype=float).median()))))


def canonical_variable(column: str) -> CanonicalVariable | None:
    """Return canonical variable metadata when the column is registered."""
    return CANONICAL_VARIABLES.get(column)


def aggregation_semantics_for(column: str) -> AggregationSemantics:
    """Return quantity-aware aggregation semantics, defaulting to state mean."""
    variable = canonical_variable(column)
    return variable.aggregation if variable is not None else "mean"


def unit_family_for(column: str, fallback: str = "") -> str:
    """Return the canonical physical unit family for overlay-axis grouping."""
    variable = canonical_variable(column)
    if variable is not None:
        return variable.unit_family
    return fallback or column


def validate_canonical_frame(data: pd.DataFrame) -> pd.DataFrame:
    """Validate and return a defensive copy of a canonical timestamped frame."""
    if not isinstance(data.index, pd.DatetimeIndex):
        raise TypeError("Canonical climate data require a pandas DatetimeIndex.")
    if data.empty:
        raise ValueError("Canonical climate data must contain at least one record.")
    if data.index.has_duplicates:
        raise ValueError("Canonical climate timestamps must be unique.")
    if data.index.hasnans:
        raise ValueError("Canonical climate timestamps must not contain NaT values.")
    frame = data.copy()
    if not frame.index.is_monotonic_increasing:
        frame = frame.sort_index(kind="mergesort")
    frame.index.name = frame.index.name or "timestamp"
    return frame


def map_provider_frame(
    data: pd.DataFrame,
    column_map: Mapping[str, str],
    *,
    keep_unmapped: bool = False,
) -> pd.DataFrame:
    """Map provider-specific columns onto the canonical climate vocabulary.

    ``column_map`` is ``provider_name -> canonical_name``. Canonical targets must
    be registered to prevent silent vocabulary drift. Unknown provider columns
    are dropped by default; callers may retain them as explicitly non-canonical
    extras with ``keep_unmapped=True``.
    """
    unknown_targets = sorted({target for target in column_map.values() if target not in CANONICAL_VARIABLES})
    if unknown_targets:
        raise ValueError(f"Unknown canonical climate columns: {', '.join(unknown_targets)}")
    missing_sources = sorted(source for source in column_map if source not in data.columns)
    if missing_sources:
        raise KeyError(f"Provider frame is missing mapped columns: {', '.join(missing_sources)}")
    frame = data.copy() if keep_unmapped else data[list(column_map)].copy()
    frame = frame.rename(columns=dict(column_map))
    return validate_canonical_frame(frame)


def build_canonical_dataset(
    *,
    climate_id: str,
    display_name: str,
    data: pd.DataFrame,
    location: ClimateLocation,
    temporal: ClimateTemporalMetadata,
    provenance: ClimateProvenance,
    column_map: Mapping[str, str] | None = None,
    keep_unmapped: bool = True,
) -> CanonicalClimateDataset:
    """Build a provider-neutral dataset without changing its timestamp calendar."""
    frame = (
        map_provider_frame(data, column_map, keep_unmapped=keep_unmapped)
        if column_map is not None
        else validate_canonical_frame(data)
    )
    return CanonicalClimateDataset(
        climate_id=climate_id,
        display_name=display_name,
        data=frame,
        location=location,
        temporal=temporal,
        provenance=provenance,
    )


def canonical_from_epw(
    epw: EpwFile,
    *,
    data: pd.DataFrame | None = None,
    climate_id: str | None = None,
    display_name: str | None = None,
    source_reference: str = "",
    provider: str = "EPW",
    dataset: str = "EPW typical-year weather",
) -> CanonicalClimateDataset:
    """Adapt the current normalized EPW representation to the canonical model.

    EPW source years remain provenance metadata. The dataframe already contains
    the unified plotting year created by ``epw_parser``; this adapter marks that
    calendar explicitly as ``typical_year`` instead of pretending it is a real
    historical year.
    """
    frame = validate_canonical_frame(epw.data if data is None else data)
    source_years = tuple(int(year) for year in frame.attrs.get("source_years", ()) if pd.notna(year))
    canonical_year_attr = frame.attrs.get("typical_year")
    if canonical_year_attr is None and len(frame.index):
        canonical_year_attr = int(pd.DatetimeIndex(frame.index)[0].year)
    timezone_name = str(frame.attrs.get("timezone_name") or "UTC")
    temporal = ClimateTemporalMetadata(
        native_interval_minutes=infer_native_resolution_minutes(frame.index),
        calendar_mode="typical_year",
        timezone_name=timezone_name,
        # epw_parser converts EPW hour-ending records to interval-start plotting
        # timestamps (hour 1 -> 00:00, hour 24 -> 23:00).
        interval_semantics="interval_start",
        source_years=source_years,
        canonical_year=int(canonical_year_attr),
    )
    location = ClimateLocation(
        latitude=float(epw.location.latitude),
        longitude=float(epw.location.longitude),
        elevation_m=float(epw.location.elevation_m),
        city=str(epw.location.city),
        state=str(epw.location.state),
        country=str(epw.location.country),
        station_id=str(epw.location.wmo),
    )
    provenance = ClimateProvenance(
        provider=provider,
        dataset=dataset,
        source_format="EPW",
        source_name=str(epw.name),
        source_reference=source_reference,
        provider_station_id=str(epw.location.wmo),
        notes=(
            "EPW source years are preserved separately from the canonical typical-year plotting calendar.",
        ),
    )
    return build_canonical_dataset(
        climate_id=climate_id or str(epw.name),
        display_name=display_name or str(epw.name),
        data=frame,
        location=location,
        temporal=temporal,
        provenance=provenance,
    )
