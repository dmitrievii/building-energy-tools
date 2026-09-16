"""Capability helpers for measured historical climate analysis views.

The historical GeoSphere route exposes only analyses whose required measured
variables are actually present in the selected interval.  Provider support in
metadata is not enough: an all-missing column does not qualify a page.
"""

from __future__ import annotations

import pandas as pd

from .aggregations import native_interval_hours


def has_numeric_observations(df: pd.DataFrame, column: str) -> bool:
    """Return True when a column exists and contains at least one finite number."""
    if column not in df.columns:
        return False
    values = pd.to_numeric(df[column], errors="coerce")
    return bool(values.notna().any())


def available_historical_pages(df: pd.DataFrame) -> tuple[str, ...]:
    """Return source-agnostic historical pages supported by observed variables."""
    pages: list[str] = ["Climate File Source"]
    has_temperature = has_numeric_observations(df, "dry_bulb_temperature_c")
    has_humidity = has_numeric_observations(df, "relative_humidity_pct")
    has_wind = has_numeric_observations(df, "wind_speed_m_s") or has_numeric_observations(df, "wind_direction_deg")
    has_solar = has_numeric_observations(df, "global_horizontal_radiation_wh_m2") or has_numeric_observations(
        df, "diffuse_horizontal_radiation_wh_m2"
    )

    if has_temperature:
        pages.append("Temperature")
    if has_temperature and has_humidity:
        pages.append("Humidity and Psychrometrics")
    if has_solar:
        pages.append("Solar and Radiation")
    if has_wind:
        pages.append("Wind and Ventilation")
    pages.extend(["Time Series and Overlay", "Data Quality"])
    return tuple(pages)


def horizontal_irradiance_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Add mean horizontal irradiance [W/m²] from interval irradiation columns.

    Canonical radiation variables are interval-extensive Wh/m².  For a source
    with declared native interval ``dt`` [h], mean irradiance is ``Wh/m² / dt``.
    This avoids the hourly-only numerical equivalence between Wh/m² and W/m².
    """
    result = df.copy()
    interval_h = native_interval_hours(df)
    if interval_h <= 0:
        raise ValueError("Historical radiation conversion requires a positive native interval.")
    mapping = {
        "global_horizontal_radiation_wh_m2": "global_horizontal_irradiance_w_m2",
        "diffuse_horizontal_radiation_wh_m2": "diffuse_horizontal_irradiance_w_m2",
    }
    for source, target in mapping.items():
        if source in result.columns:
            result[target] = pd.to_numeric(result[source], errors="coerce") / interval_h
    result.attrs.update(df.attrs)
    return result
