"""Provider-neutral preparation helpers for real historical climate datasets.

Historical observations keep their real timezone-aware timestamps. Provider-
native data remain intact for provenance, export and native diagnostics. Ordinary
analysis is prepared from one canonical hourly representation before calendar
columns or derived psychrometric quantities are added.
"""

from __future__ import annotations

from threading import RLock
import weakref

import pandas as pd

from .canonical_hourly import canonical_hourly_analysis_frame
from .climate_model import CanonicalClimateDataset
from .psychrometrics import DEFAULT_PRESSURE_PA, add_psychrometric_properties


# Identity cache: the active CanonicalClimateDataset object lives in Streamlit
# session state across reruns.  Keep exactly one normalized hourly frame for that
# object without hashing/copying its large native dataframe.  Weak references
# remove entries automatically when the source dataset leaves the session.
_HOURLY_CACHE_LOCK = RLock()
_HOURLY_CACHE: dict[int, tuple[weakref.ReferenceType[CanonicalClimateDataset], pd.DataFrame]] = {}


def _canonical_hourly_for_dataset(dataset: CanonicalClimateDataset) -> pd.DataFrame:
    key = id(dataset)
    with _HOURLY_CACHE_LOCK:
        cached = _HOURLY_CACHE.get(key)
        if cached is not None and cached[0]() is dataset:
            return cached[1]

    hourly = canonical_hourly_analysis_frame(
        dataset.data,
        source_interval_minutes=dataset.temporal.native_interval_minutes,
    )

    def _remove(_reference, *, cache_key: int = key) -> None:
        with _HOURLY_CACHE_LOCK:
            current = _HOURLY_CACHE.get(cache_key)
            if current is not None and current[0]() is None:
                _HOURLY_CACHE.pop(cache_key, None)

    reference = weakref.ref(dataset, _remove)
    with _HOURLY_CACHE_LOCK:
        _HOURLY_CACHE[key] = (reference, hourly)
    return hourly


def clear_historical_hourly_cache() -> None:
    """Clear the process-local hourly identity cache (primarily for tests)."""
    with _HOURLY_CACHE_LOCK:
        _HOURLY_CACHE.clear()


def add_historical_calendar_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add analysis calendar columns without changing real historical timestamps."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Historical climate data require a pandas DatetimeIndex.")
    attrs = dict(df.attrs)
    data = df.copy()
    index = pd.DatetimeIndex(data.index)
    data["year"] = index.year
    data["date"] = index.date
    data["month_index"] = index.month
    data["month_name"] = index.month_name().str.slice(stop=3)
    data["day_of_year"] = index.dayofyear
    data["week_of_year"] = index.isocalendar().week.astype(int)
    data["hour_of_day"] = index.hour
    data["season"] = data["month_index"].map(
        {
            12: "Winter", 1: "Winter", 2: "Winter",
            3: "Spring", 4: "Spring", 5: "Spring",
            6: "Summer", 7: "Summer", 8: "Summer",
            9: "Autumn", 10: "Autumn", 11: "Autumn",
        }
    )
    data.attrs.update(attrs)
    return data


def prepare_historical_analysis_frame(
    dataset: CanonicalClimateDataset,
    *,
    include_psychrometrics: bool = False,
    fallback_pressure_pa: float = DEFAULT_PRESSURE_PA,
    pressure_override_pa: float | None = None,
) -> pd.DataFrame:
    """Prepare the cached canonical hourly frame used by ordinary analyses.

    Provider-native observations are normalized once per active dataset object
    before any calendar helpers or derived variables are added. Sub-hourly state
    variables use arithmetic means, extensive interval quantities use sums, and
    circular quantities use circular means. Strict hourly completeness is
    enforced by :func:`canonical_hourly_analysis_frame`.

    ``pressure_override_pa`` is an explicit calculation-mode override. When it
    is ``None``, valid hourly measured station pressure is retained record by
    record and ``fallback_pressure_pa`` is used only for missing/invalid values.
    When an override is supplied, the hourly pressure series is deliberately
    replaced before psychrometric derivation.
    """
    hourly = _canonical_hourly_for_dataset(dataset)
    data = add_historical_calendar_columns(hourly)
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
        # Derived psychrometrics must inherit the hourly analysis cadence, not
        # the provider-native sub-hourly cadence retained on the source dataset.
        data.attrs["canonical_native_interval_minutes"] = 60
        data.attrs["canonical_analysis_interval_minutes"] = 60
        data.attrs["canonical_calendar_mode"] = dataset.temporal.calendar_mode
        data.attrs["canonical_timezone_name"] = dataset.temporal.timezone_name
    return data
