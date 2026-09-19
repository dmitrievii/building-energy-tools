"""Canonical climate-data model shared by all source adapters.

Adapters map provider fields onto physical variables and explicit metadata;
calculation engines consume canonical timestamped DataFrames without knowing
whether the source was EPW, GeoSphere 10-minute, GeoSphere hourly, or a future
provider. Real historical timestamps remain real; typical-year calendars remain
explicitly marked as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

import pandas as pd

from .epw_parser import EpwFile


CalendarMode = Literal["typical_year", "historical", "forecast", "climatology"]
IntervalSemantics = Literal["interval_start", "interval_end", "instantaneous", "unknown"]
AggregationSemantics = Literal["mean", "sum", "max", "min", "circular mean", "paired max direction"]


@dataclass(frozen=True)
class CanonicalVariable:
    column: str
    unit: str
    unit_family: str
    aggregation: AggregationSemantics
    description: str


CANONICAL_VARIABLES: dict[str, CanonicalVariable] = {
    "dry_bulb_temperature_c": CanonicalVariable("dry_bulb_temperature_c", "°C", "temperature", "mean", "Outdoor dry-bulb air temperature"),
    "dry_bulb_temperature_min_c": CanonicalVariable("dry_bulb_temperature_min_c", "°C", "temperature", "min", "True source-interval minimum 2 m air temperature"),
    "dry_bulb_temperature_max_c": CanonicalVariable("dry_bulb_temperature_max_c", "°C", "temperature", "max", "True source-interval maximum 2 m air temperature"),
    "ground_temperature_0_10m_c": CanonicalVariable("ground_temperature_0_10m_c", "°C", "ground temperature", "mean", "Measured ground temperature at 0.10 m depth"),
    "ground_temperature_0_20m_c": CanonicalVariable("ground_temperature_0_20m_c", "°C", "ground temperature", "mean", "Measured ground temperature at 0.20 m depth"),
    "ground_temperature_0_50m_c": CanonicalVariable("ground_temperature_0_50m_c", "°C", "ground temperature", "mean", "Measured ground temperature at 0.50 m depth"),
    "ground_temperature_1_00m_c": CanonicalVariable("ground_temperature_1_00m_c", "°C", "ground temperature", "mean", "Measured ground temperature at 1.00 m depth"),
    "ground_temperature_2_00m_c": CanonicalVariable("ground_temperature_2_00m_c", "°C", "ground temperature", "mean", "Measured ground temperature at 2.00 m depth"),
    "dew_point_temperature_c": CanonicalVariable("dew_point_temperature_c", "°C", "temperature", "mean", "Outdoor dew-point temperature"),
    "wet_bulb_temperature_c": CanonicalVariable("wet_bulb_temperature_c", "°C", "temperature", "mean", "Outdoor wet-bulb temperature"),
    "relative_humidity_pct": CanonicalVariable("relative_humidity_pct", "%", "relative humidity", "mean", "Outdoor relative humidity"),
    "humidity_ratio_g_kg": CanonicalVariable("humidity_ratio_g_kg", "g/kg dry air", "humidity ratio", "mean", "Humidity ratio"),
    "moist_air_enthalpy_kj_kg": CanonicalVariable("moist_air_enthalpy_kj_kg", "kJ/kg dry air", "enthalpy", "mean", "Moist-air specific enthalpy"),
    "specific_volume_m3_kg": CanonicalVariable("specific_volume_m3_kg", "m³/kg dry air", "specific volume", "mean", "Moist-air specific volume"),
    "moist_air_density_kg_m3": CanonicalVariable("moist_air_density_kg_m3", "kg/m³", "density", "mean", "Moist-air density"),
    "atmospheric_station_pressure_pa": CanonicalVariable("atmospheric_station_pressure_pa", "Pa", "pressure", "mean", "Atmospheric station pressure"),
    "global_horizontal_radiation_wh_m2": CanonicalVariable("global_horizontal_radiation_wh_m2", "Wh/m²", "irradiation", "sum", "Global horizontal irradiation per source interval"),
    "direct_normal_radiation_wh_m2": CanonicalVariable("direct_normal_radiation_wh_m2", "Wh/m²", "irradiation", "sum", "Direct normal irradiation per source interval"),
    "diffuse_horizontal_radiation_wh_m2": CanonicalVariable("diffuse_horizontal_radiation_wh_m2", "Wh/m²", "irradiation", "sum", "Diffuse horizontal irradiation per source interval"),
    "extraterrestrial_horizontal_radiation_wh_m2": CanonicalVariable("extraterrestrial_horizontal_radiation_wh_m2", "Wh/m²", "irradiation", "sum", "Extraterrestrial horizontal irradiation per source interval"),
    "extraterrestrial_direct_normal_radiation_wh_m2": CanonicalVariable("extraterrestrial_direct_normal_radiation_wh_m2", "Wh/m²", "irradiation", "sum", "Extraterrestrial direct-normal irradiation per source interval"),
    "horizontal_infrared_radiation_intensity_wh_m2": CanonicalVariable("horizontal_infrared_radiation_intensity_wh_m2", "Wh/m²", "longwave irradiation", "sum", "Horizontal infrared atmospheric irradiation per source interval"),
    "global_horizontal_illuminance_lux": CanonicalVariable("global_horizontal_illuminance_lux", "lux", "illuminance", "mean", "Global horizontal illuminance"),
    "direct_normal_illuminance_lux": CanonicalVariable("direct_normal_illuminance_lux", "lux", "illuminance", "mean", "Direct normal illuminance"),
    "diffuse_horizontal_illuminance_lux": CanonicalVariable("diffuse_horizontal_illuminance_lux", "lux", "illuminance", "mean", "Diffuse horizontal illuminance"),
    "zenith_luminance_cd_m2": CanonicalVariable("zenith_luminance_cd_m2", "cd/m²", "luminance", "mean", "Zenith luminance"),
    "wind_speed_m_s": CanonicalVariable("wind_speed_m_s", "m/s", "wind speed", "mean", "Wind speed"),
    "wind_direction_deg": CanonicalVariable("wind_direction_deg", "deg", "direction", "circular mean", "Wind direction clockwise from north"),
    "wind_gust_speed_m_s": CanonicalVariable("wind_gust_speed_m_s", "m/s", "wind speed", "max", "Maximum wind gust speed within the source interval"),
    "wind_gust_direction_deg": CanonicalVariable("wind_gust_direction_deg", "deg", "direction", "paired max direction", "Direction paired with the maximum wind gust"),
    "total_sky_cover_tenths": CanonicalVariable("total_sky_cover_tenths", "tenths", "sky cover", "mean", "Total sky cover"),
    "opaque_sky_cover_tenths": CanonicalVariable("opaque_sky_cover_tenths", "tenths", "sky cover", "mean", "Opaque sky cover"),
    "visibility_km": CanonicalVariable("visibility_km", "km", "visibility", "mean", "Horizontal visibility"),
    "ceiling_height_m": CanonicalVariable("ceiling_height_m", "m", "cloud ceiling", "mean", "Cloud ceiling height"),
    "precipitable_water_mm": CanonicalVariable("precipitable_water_mm", "mm", "precipitable water", "mean", "Total atmospheric precipitable water"),
    "aerosol_optical_depth_thousandths": CanonicalVariable("aerosol_optical_depth_thousandths", "0.001", "optical depth", "mean", "Aerosol optical depth in EPW thousandths"),
    "albedo": CanonicalVariable("albedo", "-", "albedo", "mean", "Ground surface solar reflectance"),
    "liquid_precipitation_depth_mm": CanonicalVariable("liquid_precipitation_depth_mm", "mm", "precipitation", "sum", "Liquid precipitation depth per reported source interval"),
    "precipitation_duration_min": CanonicalVariable("precipitation_duration_min", "min", "duration", "sum", "Measured precipitation duration within the reported source interval"),
    "snow_depth_cm": CanonicalVariable("snow_depth_cm", "cm", "snow depth", "mean", "Snow depth state"),
    "days_since_last_snowfall": CanonicalVariable("days_since_last_snowfall", "d", "snow state", "mean", "Days since last snowfall"),
    "sunshine_duration_s": CanonicalVariable("sunshine_duration_s", "s", "duration", "sum", "Measured sunshine duration within the source interval"),
}


@dataclass(frozen=True)
class ClimateLocation:
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
    positive = _positive_interval_minutes(pd.DatetimeIndex(index))
    if not positive:
        return 60
    return max(1, int(round(float(pd.Series(positive, dtype=float).median()))))


def canonical_variable(column: str) -> CanonicalVariable | None:
    return CANONICAL_VARIABLES.get(column)


def aggregation_semantics_for(column: str) -> AggregationSemantics:
    variable = canonical_variable(column)
    return variable.aggregation if variable is not None else "mean"


def unit_family_for(column: str, fallback: str = "") -> str:
    variable = canonical_variable(column)
    return variable.unit_family if variable is not None else (fallback or column)


def validate_canonical_frame(data: pd.DataFrame) -> pd.DataFrame:
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
    """Adapt an EPW normalized frame to the canonical source contract."""
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
        notes=("EPW source years are preserved separately from the canonical typical-year plotting calendar.",),
    )
    return build_canonical_dataset(
        climate_id=climate_id or str(epw.name),
        display_name=display_name or str(epw.name),
        data=frame,
        location=location,
        temporal=temporal,
        provenance=provenance,
    )
