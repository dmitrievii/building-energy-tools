"""Provider-neutral preparation helpers for real historical climate datasets.

Provider-native observations remain intact for provenance, export and native
source diagnostics.  Ordinary scientific analysis uses one canonical hourly
representation.  Source timestamp timezone and building-analysis clock are
separate: hourly normalization happens on the provider timeline first, then the
same physical instants can be represented in local civil/standard time before
calendar columns and calendar-based analyses are evaluated.
"""

from __future__ import annotations

from threading import RLock
import weakref

import pandas as pd

from .analysis_clock import (
    SOURCE_TIME,
    AnalysisClockMode,
    add_calendar_columns,
    prepare_analysis_calendar,
)
from .canonical_hourly import CANONICAL_ANALYSIS_INTERVAL_MINUTES, canonical_hourly_analysis_frame
from .climate_model import CanonicalClimateDataset
from .decisions import add_degree_metrics
from .psychrometrics import DEFAULT_PRESSURE_PA, add_psychrometric_properties
from .solar import ensure_solar_radiation_components


_HOURLY_CACHE_LOCK = RLock()
_HOURLY_CACHE: dict[int, tuple[weakref.ReferenceType[CanonicalClimateDataset], pd.DataFrame]] = {}
_NATIVE_DIAGNOSTIC_CACHE: dict[int, tuple[weakref.ReferenceType[CanonicalClimateDataset], pd.DataFrame]] = {}


def _remove_identity_cache_entry(
    cache: dict[int, tuple[weakref.ReferenceType[CanonicalClimateDataset], pd.DataFrame]],
    cache_key: int,
) -> None:
    with _HOURLY_CACHE_LOCK:
        current = cache.get(cache_key)
        if current is not None and current[0]() is None:
            cache.pop(cache_key, None)


def _canonical_hourly_for_dataset(dataset: CanonicalClimateDataset) -> pd.DataFrame:
    """Return cached canonical hourly physics on the original provider timeline."""
    key = id(dataset)
    with _HOURLY_CACHE_LOCK:
        cached = _HOURLY_CACHE.get(key)
        if cached is not None and cached[0]() is dataset:
            return cached[1]

    canonical_columns = list(dataset.available_canonical_variables)
    source_frame = dataset.data[canonical_columns].copy()
    source_frame.attrs.update(dict(dataset.data.attrs))
    hourly = canonical_hourly_analysis_frame(
        source_frame,
        source_interval_minutes=dataset.temporal.native_interval_minutes,
    )

    def _remove(_reference, *, cache_key: int = key) -> None:
        _remove_identity_cache_entry(_HOURLY_CACHE, cache_key)

    reference = weakref.ref(dataset, _remove)
    with _HOURLY_CACHE_LOCK:
        _HOURLY_CACHE[key] = (reference, hourly)
    return hourly


def clear_historical_hourly_cache() -> None:
    """Clear process-local historical identity caches (primarily for tests)."""
    with _HOURLY_CACHE_LOCK:
        _HOURLY_CACHE.clear()
        _NATIVE_DIAGNOSTIC_CACHE.clear()


def add_historical_calendar_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible alias for source-neutral calendar-column creation."""
    return add_calendar_columns(df)


def _calendar_frame(
    df: pd.DataFrame,
    *,
    analysis_clock_mode: AnalysisClockMode,
    local_timezone_name: str | None,
    standard_utc_offset_hours: float | None,
    source_timezone_name: str | None,
) -> pd.DataFrame:
    return prepare_analysis_calendar(
        df,
        mode=analysis_clock_mode,
        local_timezone_name=local_timezone_name,
        standard_utc_offset_hours=standard_utc_offset_hours,
        source_timezone_name=source_timezone_name,
    )


def prepare_historical_native_diagnostic_frame(dataset: CanonicalClimateDataset) -> pd.DataFrame:
    """Return provider-native observations for source Data Quality.

    Diagnostics deliberately remain on the provider/source clock.  User-facing
    building analysis may use another clock, but a source gap at 12:10 UTC must
    still be audited as the actual provider timestamp rather than relabelled.
    """
    key = id(dataset)
    with _HOURLY_CACHE_LOCK:
        cached = _NATIVE_DIAGNOSTIC_CACHE.get(key)
        if cached is not None and cached[0]() is dataset:
            return cached[1]

    native = _calendar_frame(
        dataset.data,
        analysis_clock_mode=SOURCE_TIME,
        local_timezone_name=None,
        standard_utc_offset_hours=None,
        source_timezone_name=dataset.temporal.timezone_name,
    )
    source_minutes = int(dataset.temporal.native_interval_minutes)
    native.attrs["canonical_source_interval_minutes"] = source_minutes
    native.attrs["canonical_native_interval_minutes"] = source_minutes
    native.attrs["canonical_analysis_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
    native.attrs["canonical_frame_role"] = "native-diagnostics"
    native.attrs["canonical_calendar_mode"] = dataset.temporal.calendar_mode
    native.attrs["canonical_timezone_name"] = dataset.temporal.timezone_name
    native.attrs["canonical_source_rows"] = int(len(dataset.data))

    def _remove(_reference, *, cache_key: int = key) -> None:
        _remove_identity_cache_entry(_NATIVE_DIAGNOSTIC_CACHE, cache_key)

    reference = weakref.ref(dataset, _remove)
    with _HOURLY_CACHE_LOCK:
        _NATIVE_DIAGNOSTIC_CACHE[key] = (reference, native)
    return native


def prepare_historical_native_analysis_frame(
    dataset: CanonicalClimateDataset,
    *,
    analysis_clock_mode: AnalysisClockMode = SOURCE_TIME,
    local_timezone_name: str | None = None,
    standard_utc_offset_hours: float | None = None,
    include_psychrometrics: bool = False,
    include_solar: bool = False,
    fallback_pressure_pa: float = DEFAULT_PRESSURE_PA,
) -> pd.DataFrame:
    """Prepare provider-native data for the Time Series page only.

    No temporal upsampling/downsampling is performed.  This function exists so
    sub-hourly observations can be inspected without forcing every climate chart
    to process the provider cadence.  Other analysis pages should use
    :func:`prepare_historical_analysis_frame`.
    """
    source = dataset.data.copy()
    data = _calendar_frame(
        source,
        analysis_clock_mode=analysis_clock_mode,
        local_timezone_name=local_timezone_name,
        standard_utc_offset_hours=standard_utc_offset_hours,
        source_timezone_name=dataset.temporal.timezone_name,
    )
    if include_psychrometrics:
        required = {"dry_bulb_temperature_c", "relative_humidity_pct"}
        if required.issubset(data.columns):
            data = add_psychrometric_properties(data, fallback_pressure_pa=float(fallback_pressure_pa))
    if include_solar:
        data = ensure_solar_radiation_components(
            data,
            latitude=float(dataset.location.latitude),
            longitude=float(dataset.location.longitude),
            elevation_m=dataset.location.elevation_m,
            timezone_name=local_timezone_name,
        )
    source_minutes = int(dataset.temporal.native_interval_minutes)
    data.attrs["canonical_source_interval_minutes"] = source_minutes
    data.attrs["canonical_native_interval_minutes"] = source_minutes
    data.attrs["canonical_analysis_interval_minutes"] = source_minutes
    data.attrs["canonical_frame_role"] = "native-time-series"
    data.attrs["canonical_calendar_mode"] = dataset.temporal.calendar_mode
    data.attrs["canonical_timezone_name"] = dataset.temporal.timezone_name
    return data


def prepare_historical_analysis_frame(
    dataset: CanonicalClimateDataset,
    *,
    include_psychrometrics: bool = False,
    include_solar: bool = False,
    fallback_pressure_pa: float = DEFAULT_PRESSURE_PA,
    pressure_override_pa: float | None = None,
    analysis_clock_mode: AnalysisClockMode = SOURCE_TIME,
    local_timezone_name: str | None = None,
    standard_utc_offset_hours: float | None = None,
) -> pd.DataFrame:
    """Prepare the canonical hourly frame used by ordinary analyses.

    Sub-hourly source values are normalized on the provider timeline first. Only
    after that physical aggregation is complete is the index represented in the
    selected analysis clock.  This prevents DST changes from creating malformed
    50/70-minute aggregation windows while ensuring occupancy, day/night and
    month-hour analyses use the intended local clock.
    """
    hourly = _canonical_hourly_for_dataset(dataset)
    data = _calendar_frame(
        hourly,
        analysis_clock_mode=analysis_clock_mode,
        local_timezone_name=local_timezone_name,
        standard_utc_offset_hours=standard_utc_offset_hours,
        source_timezone_name=dataset.temporal.timezone_name,
    )
    if "dry_bulb_temperature_c" in data.columns:
        data = add_degree_metrics(data)
    data.attrs["canonical_frame_role"] = "hourly-analysis"
    data.attrs["canonical_source_interval_minutes"] = int(dataset.temporal.native_interval_minutes)
    data.attrs["canonical_native_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
    data.attrs["canonical_analysis_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
    data.attrs["canonical_calendar_mode"] = dataset.temporal.calendar_mode
    data.attrs["canonical_timezone_name"] = dataset.temporal.timezone_name

    if pressure_override_pa is not None:
        pressure_override = float(pressure_override_pa)
        if not 30_000.0 <= pressure_override <= 120_000.0:
            raise ValueError("Historical psychrometric pressure override must be within 30000...120000 Pa.")
        data["atmospheric_station_pressure_pa"] = pressure_override

    if include_psychrometrics:
        required = {"dry_bulb_temperature_c", "relative_humidity_pct"}
        missing = sorted(required - set(data.columns))
        if missing:
            raise ValueError(
                "Psychrometric analysis requires canonical variables: " + ", ".join(missing)
            )
        if "atmospheric_station_pressure_pa" not in data.columns:
            data["atmospheric_station_pressure_pa"] = float(fallback_pressure_pa)
        data = add_psychrometric_properties(data, fallback_pressure_pa=float(fallback_pressure_pa))

    if include_solar:
        data = ensure_solar_radiation_components(
            data,
            latitude=float(dataset.location.latitude),
            longitude=float(dataset.location.longitude),
            elevation_m=dataset.location.elevation_m,
            timezone_name=local_timezone_name,
        )

    data.attrs["canonical_native_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
    data.attrs["canonical_analysis_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
    data.attrs["canonical_source_interval_minutes"] = int(dataset.temporal.native_interval_minutes)
    data.attrs["canonical_frame_role"] = "hourly-analysis"
    data.attrs["canonical_calendar_mode"] = dataset.temporal.calendar_mode
    data.attrs["canonical_timezone_name"] = dataset.temporal.timezone_name
    return data
