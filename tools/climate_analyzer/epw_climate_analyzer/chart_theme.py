"""Semantic colour system for Climate Analyzer charts.

Single-climate charts use colours that identify the physical quantity.  Climate
comparison charts use a stable colour per climate so the same dataset keeps the
same visual identity across chart families.
"""

from __future__ import annotations

from collections.abc import Iterable

PLOT_TEMPLATE = "plotly_white"

HEATING_COLOR = "#D55E00"
COOLING_COLOR = "#0072B2"
NEUTRAL_COLOR = "#6B7280"
DEFAULT_METRIC_COLOR = "#4F46E5"

SOLAR_COMPONENT_COLORS = {
    "GHI": "#F59E0B",
    "DNI": "#EA580C",
    "DHI": "#CA8A04",
}

TEMPERATURE_COMFORT_COLORSCALE = [
    [0.00, "#1d4ed8"],
    [0.32, "#3b82f6"],
    [0.45, "#22c55e"],
    [0.55, "#22c55e"],
    [0.70, "#f97316"],
    [1.00, "#dc2626"],
]
SOLAR_COLORSCALE = [
    [0.00, "#4c1d95"],
    [0.45, "#f97316"],
    [1.00, "#fef08a"],
]
BINARY_SUITABILITY_COLORSCALE = [
    [0.00, "rgba(255,255,255,0.0)"],
    [0.01, "#ecfdf5"],
    [1.00, "#047857"],
]
PSYCHROMETRIC_TILE_COLORSCALE = [
    [0.00, "rgba(255,255,255,0.0)"],
    [0.10, "#dbeafe"],
    [0.35, "#60a5fa"],
    [0.70, "#2563eb"],
    [1.00, "#172554"],
]
MONTH_COLORS = [
    "#2563eb", "#0ea5e9", "#14b8a6", "#22c55e", "#84cc16", "#eab308",
    "#f97316", "#ef4444", "#d946ef", "#8b5cf6", "#6366f1", "#475569",
]

# Stable, high-contrast comparison palette. Order, not physical variable, owns
# colour in multi-climate overlays.
CLIMATE_COLORS = [
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#7C3AED",
    "#E69F00",
    "#0E7490",
    "#CC79A7",
    "#475569",
]

WIND_SPEED_COLORS = [
    "#D1FAE5",
    "#A7F3D0",
    "#6EE7B7",
    "#34D399",
    "#10B981",
    "#047857",
    "#064E3B",
]
WIND_SPEED_LABELS = ["0-1", "1-2", "2-4", "4-6", "6-8", "8-12", ">12"]
WIND_SPEED_COLOR_MAP = dict(zip(WIND_SPEED_LABELS, WIND_SPEED_COLORS, strict=True))

ORIENTATION_COLORS = {
    "north": "#2563EB",
    "north-east": "#0891B2",
    "east": "#CA8A04",
    "south-east": "#EA580C",
    "south": "#DC2626",
    "south-west": "#C026D3",
    "west": "#7C3AED",
    "north-west": "#4F46E5",
}

METRIC_COLORS = {
    "dry_bulb_temperature_c": "#D55E00",
    "dew_point_temperature_c": "#0072B2",
    "wet_bulb_temperature_c": "#009E73",
    "relative_humidity_pct": "#2563EB",
    "humidity_ratio_g_kg": "#0891B2",
    "moist_air_enthalpy_kj_kg": "#7C3AED",
    "specific_volume_m3_kg": "#64748B",
    "moist_air_density_kg_m3": "#475569",
    "atmospheric_station_pressure_pa": "#64748B",
    "global_horizontal_radiation_wh_m2": SOLAR_COMPONENT_COLORS["GHI"],
    "direct_normal_radiation_wh_m2": SOLAR_COMPONENT_COLORS["DNI"],
    "diffuse_horizontal_radiation_wh_m2": SOLAR_COMPONENT_COLORS["DHI"],
    "global_horizontal_illuminance_lux": "#F59E0B",
    "direct_normal_illuminance_lux": "#EA580C",
    "diffuse_horizontal_illuminance_lux": "#CA8A04",
    "wind_speed_m_s": "#059669",
    "wind_direction_deg": "#7C3AED",
    "total_sky_cover_tenths": "#475569",
    "opaque_sky_cover_tenths": "#334155",
    "liquid_precipitation_depth_mm": "#2563EB",
    "snow_depth_cm": "#0284C7",
    "natural_ventilation_suitable": "#059669",
    "night_flushing_suitable": "#0D9488",
    "heating_degree_hours_kh": HEATING_COLOR,
    "cooling_degree_hours_kh": COOLING_COLOR,
    "ventilation_heating_kw": HEATING_COLOR,
    "ventilation_cooling_kw": COOLING_COLOR,
}


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        return 79, 70, 229
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _mix_with_white(color: str, fraction: float) -> str:
    r, g, b = _hex_to_rgb(color)
    f = max(0.0, min(1.0, float(fraction)))
    vals = [round(v + (255 - v) * f) for v in (r, g, b)]
    return "#" + "".join(f"{v:02X}" for v in vals)


def _darken(color: str, fraction: float) -> str:
    r, g, b = _hex_to_rgb(color)
    f = max(0.0, min(1.0, float(fraction)))
    vals = [round(v * (1.0 - f)) for v in (r, g, b)]
    return "#" + "".join(f"{v:02X}" for v in vals)


def rgba(color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(color)
    return f"rgba({r},{g},{b},{max(0.0, min(1.0, float(alpha))):.3f})"


def metric_color(column: str | None) -> str:
    """Return the semantic base colour for a physical variable."""
    if not column:
        return DEFAULT_METRIC_COLOR
    if column in METRIC_COLORS:
        return METRIC_COLORS[column]
    text = str(column).lower()
    if "radiation" in text or "irradiance" in text:
        if "direct" in text or "dni" in text:
            return SOLAR_COMPONENT_COLORS["DNI"]
        if "diffuse" in text or "dhi" in text:
            return SOLAR_COMPONENT_COLORS["DHI"]
        return SOLAR_COMPONENT_COLORS["GHI"]
    if "illuminance" in text:
        return SOLAR_COMPONENT_COLORS["GHI"]
    if "temperature" in text:
        return METRIC_COLORS["dry_bulb_temperature_c"]
    if "humidity" in text:
        return METRIC_COLORS["relative_humidity_pct"]
    if "wind" in text:
        return METRIC_COLORS["wind_speed_m_s"]
    if "heating" in text:
        return HEATING_COLOR
    if "cooling" in text:
        return COOLING_COLOR
    if "ventilation" in text or "suitable" in text:
        return METRIC_COLORS["natural_ventilation_suitable"]
    return DEFAULT_METRIC_COLOR


def metric_band_colors(column: str | None) -> tuple[str, str, str, str]:
    """Return low, central, high and translucent fill colours for a ribbon."""
    if column and "temperature" in str(column).lower():
        return "#2563EB", METRIC_COLORS["dry_bulb_temperature_c"], "#DC2626", "rgba(107,114,128,0.16)"
    base = metric_color(column)
    return _mix_with_white(base, 0.48), base, _darken(base, 0.22), rgba(base, 0.14)


def semantic_color_from_text(text: str | None) -> str:
    """Infer a semantic colour from a displayed series/title string."""
    value = (text or "").strip().lower()
    if not value:
        return DEFAULT_METRIC_COLOR

    if value in ORIENTATION_COLORS:
        return ORIENTATION_COLORS[value]
    if "global horizontal" in value or " ghi" in f" {value}" or value.startswith("ghi"):
        return SOLAR_COMPONENT_COLORS["GHI"]
    if "direct normal" in value or " dni" in f" {value}" or value.startswith("dni"):
        return SOLAR_COMPONENT_COLORS["DNI"]
    if "diffuse horizontal" in value or " dhi" in f" {value}" or value.startswith("dhi"):
        return SOLAR_COMPONENT_COLORS["DHI"]
    if "heating" in value or "hdd" in value:
        return HEATING_COLOR
    if "cooling" in value or "cdd" in value:
        return COOLING_COLOR
    if "natural ventilation" in value or "economizer" in value or "suitable" in value:
        return "#059669"
    if "night flushing" in value:
        return "#0D9488"
    if "dehumid" in value:
        return "#7C3AED"
    if "humidification" in value:
        return "#0891B2"
    if "solar" in value or "radiation" in value or "irradiation" in value or "illuminance" in value:
        return SOLAR_COMPONENT_COLORS["GHI"]
    if "wind" in value:
        return METRIC_COLORS["wind_speed_m_s"]
    if "temperature" in value:
        return METRIC_COLORS["dry_bulb_temperature_c"]
    if "humidity" in value or "moisture" in value:
        return METRIC_COLORS["humidity_ratio_g_kg"]
    if "sky" in value:
        return METRIC_COLORS["total_sky_cover_tenths"]
    return DEFAULT_METRIC_COLOR


def series_color(name: str, fallback_column: str | None = None) -> str:
    """Colour a named physical series, falling back to its source column."""
    inferred = semantic_color_from_text(name)
    if inferred != DEFAULT_METRIC_COLOR:
        return inferred
    return metric_color(fallback_column)


def climate_color_map(names: Iterable[str]) -> dict[str, str]:
    """Return deterministic colours by climate order for one comparison view."""
    return {str(name): CLIMATE_COLORS[index % len(CLIMATE_COLORS)] for index, name in enumerate(names)}


def metric_colorscale(column: str | None):
    """Return a continuous colourscale suitable for the selected metric."""
    text = str(column or "").lower()
    if "radiation" in text or "irradiance" in text or "illuminance" in text:
        return SOLAR_COLORSCALE
    if "sky_cover" in text:
        return [[0.0, "rgba(255,255,255,0.0)"], [0.25, "#dbeafe"], [1.0, "#0f172a"]]
    if "wind" in text:
        return "Turbo"
    if "suitable" in text or "ventilation" in text:
        return BINARY_SUITABILITY_COLORSCALE
    return "Viridis"
