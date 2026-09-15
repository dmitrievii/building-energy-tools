"""Provider-neutral preparation helpers for real historical climate datasets.

Historical observations keep their real timezone-aware timestamps. This module
adds only the calendar helper columns required by existing analysis views and,
when requested, derives psychrometric quantities from canonical primary
observations. It does not convert observations to an EPW typical-year calendar.
"""

from __future__ import annotations

import pandas as pd

from .climate_model import CanonicalClimateDataset
from .psychrometrics import DEFAULT_PRESSURE_PA, add_psychrometric_properties


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
    """Prepare a canonical historical dataset for source-agnostic analysis views.

    ``pressure_override_pa`` is an explicit calculation-mode override. When it
    is ``None``, valid measured station pressure is retained record by record and
    ``fallback_pressure_pa`` is used only for missing/invalid values. When an
    override is supplied, the measured pressure series is deliberately replaced
    before psychrometric derivation.
    """
    data = add_historical_calendar_columns(dataset.data)
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
        data.attrs.setdefault("canonical_native_interval_minutes", dataset.temporal.native_interval_minutes)
        data.attrs.setdefault("canonical_calendar_mode", dataset.temporal.calendar_mode)
        data.attrs.setdefault("canonical_timezone_name", dataset.temporal.timezone_name)
    return data
