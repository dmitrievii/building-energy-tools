"""Semantic-colour closure for GeoSphere native-monthly analysis."""

from __future__ import annotations

from typing import Any, Callable

from . import chart_theme, charts, source_parity_monthly_cleanup as cleanup
from .source_parity_longterm_followup import temperature_gradient_colorscale


def monthly_metric_color(column: str, fallback: Callable[[str | None], str]) -> str:
    """Map monthly semantic columns onto the shared physical colour families."""
    text = str(column).lower()
    if "__temperature__" in text:
        return fallback("dry_bulb_temperature_c")
    if "__humidity_and_psychrometrics__" in text:
        if "pressure" in text or "druck" in text:
            return fallback("atmospheric_station_pressure_pa")
        return fallback("relative_humidity_pct")
    if "__solar_and_radiation__" in text or "sunshine" in text or "sonnen" in text:
        return chart_theme.SOLAR_COMPONENT_COLORS["GHI"]
    if "__sky_and_daylight__" in text:
        return fallback("total_sky_cover_tenths")
    if "__wind_and_ventilation__" in text:
        return fallback("wind_speed_m_s")
    if "__precipitation_and_snow__" in text:
        if "snow" in text or "schnee" in text:
            return fallback("snow_depth_cm")
        return fallback("liquid_precipitation_depth_mm")
    return fallback(column)


def install_monthly_visual_contract() -> None:
    """Bind monthly semantic columns to the same colour rules as canonical fields."""
    cleanup.monthly_metric_color = monthly_metric_color

    if bool(getattr(charts, "_MONTHLY_HEATMAP_VISUAL_CONTRACT_INSTALLED", False)):
        return
    original = charts._heatmap_colorscale

    def colorscale(
        column: str,
        values: Any = None,
        temperature_thresholds: tuple[float, float] | None = None,
    ):
        text = str(column).lower()
        is_temperature = column == "dry_bulb_temperature_c" or "__temperature__" in text
        if is_temperature and temperature_thresholds is not None:
            return temperature_gradient_colorscale(values, temperature_thresholds)
        if "__precipitation_and_snow__" in text:
            # Reuse the exact precipitation scale by delegating through its
            # canonical representative rather than creating a source palette.
            return original("liquid_precipitation_depth_mm", values, temperature_thresholds)
        if "__solar_and_radiation__" in text:
            return original("global_horizontal_radiation_wh_m2", values, temperature_thresholds)
        if "__sky_and_daylight__" in text:
            return original("total_sky_cover_tenths", values, temperature_thresholds)
        return original(column, values, temperature_thresholds)

    charts._heatmap_colorscale = colorscale
    charts._MONTHLY_HEATMAP_VISUAL_CONTRACT_INSTALLED = True
