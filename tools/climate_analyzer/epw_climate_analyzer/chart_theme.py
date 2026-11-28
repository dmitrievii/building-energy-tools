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

SHADING_IRRADIATION_COLORS = {
    "Shaded total (direct-only)": "#F59E0B",
    "Intercepted direct": "#64748B",
    "Unshaded total": "#EA580C",
}

SOURCE_IRRADIATION_COLORS = {
    "global_horizontal_radiation_wh_m2": SOLAR_COMPONENT_COLORS["GHI"],
    "direct_normal_radiation_wh_m2": SOLAR_COMPONENT_COLORS["DNI"],
    "diffuse_horizontal_radiation_wh_m2": SOLAR_COMPONENT_COLORS["DHI"],
}
SOURCE_IRRADIANCE_COLORS = {
    "global_horizontal_irradiance_w_m2": SOLAR_COMPONENT_COLORS["GHI"],
    "direct_normal_irradiance_w_m2": SOLAR_COMPONENT_COLORS["DNI"],
    "diffuse_horizontal_irradiance_w_m2": SOLAR_COMPONENT_COLORS["DHI"],
}
POA_COMPONENT_COLORS = {
    "poa_global_wh_m2": SOLAR_COMPONENT_COLORS["GHI"],
    "poa_direct_wh_m2": SOLAR_COMPONENT_COLORS["DNI"],
    "poa_sky_diffuse_wh_m2": SOLAR_COMPONENT_COLORS["DHI"],
    "poa_ground_diffuse_wh_m2": "#7493AA",
}

TEMPERATURE_HEATMAP_COLUMNS = frozenset((
    "dry_bulb_temperature_c", "dry_bulb_temperature_min_c",
    "dry_bulb_temperature_max_c", "dew_point_temperature_c",
    "wet_bulb_temperature_c", "ground_temperature_0_10m_c",
    "ground_temperature_0_20m_c", "ground_temperature_0_50m_c",
    "ground_temperature_1_00m_c", "ground_temperature_2_00m_c",
))

def temperature_gradient_domain(minimum=None,maximum=None,thresholds=(18.,26.)):
    """Continuous absolute temperature gradient; reference anchors at 18/26 °C.

    Preserve visible cold-to-hot colours under every reduction and scope.
    The default range is -15…32 °C; extend it rather than clipping extremes.
    The two configured thresholds shift the neutral transition together.
    """
    import math
    low,high=sorted(map(float,thresholds))
    if not math.isfinite(low) or not math.isfinite(high):raise ValueError("Temperature thresholds must be finite.")
    # A coincident pair still needs a nonzero continuous transition.
    if high == low:
        low,high=low-0.05,high+0.05
    # Keep the cold and hot tails independent of the data range.
    anchors=[(low-33,"#1F2555"),(low-28,"#29357C"),(low-18,"#4259D5"),
             (low-8,"#809BEF"),(low,"#BCD1F9"),
             ((low+high)/2,"#5CC56B"),(high,"#E5D98B"),
             (high+4,"#D8662E"),(high+6,"#AD3025")]
    lo=min(anchors[0][0],float(minimum)) if minimum is not None and math.isfinite(minimum) else anchors[0][0]
    hi=max(anchors[-1][0],float(maximum)) if maximum is not None and math.isfinite(maximum) else anchors[-1][0]
    # Extend the numeric axis without changing the absolute mapping: beyond
    # the fixed chromatic endpoints the colour saturates, not the data.
    if lo<anchors[0][0]:anchors.insert(0,(lo,anchors[0][1]))
    if hi>anchors[-1][0]:anchors.append((hi,anchors[-1][1]))
    scale=[[(v-lo)/(hi-lo),color] for v,color in anchors]
    return lo,hi,scale

def temperature_coloraxis(*, frames=(), values=(), thresholds=(18.,26.)):
    """Canonical absolute-temperature Plotly colour axis, including its legend.

    All available absolute-temperature columns in the selected source scope
    participate, independent of the displayed quantity or cell statistic.
    Additional calculated values extend the bounds if necessary.
    """
    import math
    import numpy as np
    import pandas as pd
    extrema=[]
    def collect(raw):
        v=np.asarray(raw,dtype=float).ravel()
        v=v[np.isfinite(v)]
        if v.size:
            extrema.extend((float(v.min()),float(v.max())))
    for frame in frames:
        if frame is None:
            continue
        for column in TEMPERATURE_HEATMAP_COLUMNS:
            if column in frame:
                collect(pd.to_numeric(frame[column],errors="coerce").to_numpy(dtype=float))
    for raw in values:
        collect(raw)
    lo,hi,scale=temperature_gradient_domain(min(extrema,default=None),max(extrema,default=None),thresholds)
    step=5. if hi-lo<=80. else 10. if hi-lo<=160. else 20.
    ticks=[float(i)*step for i in range(math.ceil(lo/step),math.floor(hi/step)+1)]
    return dict(colorscale=scale,cmin=lo,cmax=hi,cauto=False,
                colorbar=dict(title="°C",tickmode="array",tickvals=ticks,
                              ticktext=[str(int(t)) for t in ticks],tickformat=".0f"))

TEMPERATURE_COMFORT_COLORSCALE = temperature_gradient_domain()[2]
# Sequential irradiation palette: white is a physical zero, high values
# progress through yellow to saturated orange.
SOLAR_COLORSCALE = [
    [0.00, "#FFFFFF"],
    [0.12, "#FFFDEB"],
    [0.35, "#FFF3AE"],
    [0.60, "#FFD84D"],
    [0.82, "#FFAA25"],
    [1.00, "#E66A00"],
]

def is_irradiation_metric(column: str | None) -> bool:
    text = str(column or "").lower()
    return ("radiation" in text or "irradiance" in text or text.startswith("poa_")) and "illuminance" not in text

ILLUMINANCE_THRESHOLD_COLOR = "#EAB308"
ILLUMINANCE_COLUMNS = ("global_horizontal_illuminance_lux","direct_normal_illuminance_lux","diffuse_horizontal_illuminance_lux")
ILLUMINANCE_COLORSCALE = [
    [0.00, "#FFFFFF"],
    [0.25, "#FEF3C7"],
    [0.50, "#FCD34D"],
    [0.75, "#F59E0B"],
    [1.00, "#C2410C"],
]
RELATIVE_HUMIDITY_COLORSCALE = [
    [0.00, "#F5F7FF"],
    [0.25, "#BFDBFE"],
    [0.50, "#60A5FA"],
    [0.75, "#2563EB"],
    [1.00, "#4338CA"],
]
HUMIDITY_RATIO_COLORSCALE = [
    [0.00, "#F0FDFF"],
    [0.25, "#CFFAFE"],
    [0.50, "#67E8F9"],
    [0.75, "#0891B2"],
    [1.00, "#164E63"],
]
MOIST_AIR_ENTHALPY_COLORSCALE = [
    [0.00, "#FAF5FF"],
    [0.25, "#DDD6FE"],
    [0.50, "#A78BFA"],
    [0.75, "#7C3AED"],
    [1.00, "#4C1D95"],
]
SPECIFIC_VOLUME_COLORSCALE = [
    [0.00, "#F0F6FA"],
    [0.25, "#C4D8E6"],
    [0.50, "#8DAFC5"],
    [0.75, "#547C9A"],
    [1.00, "#26465F"],
]
STATION_PRESSURE_COLORSCALE = [
    [0.00, "#FAF6EF"],
    [0.25, "#E4D5BE"],
    [0.50, "#C5A77D"],
    [0.75, "#92734D"],
    [1.00, "#594027"],
]
MOIST_AIR_DENSITY_COLORSCALE = [
    [0.00, "#F1F5F9"],
    [0.25, "#CBD5E1"],
    [0.50, "#94A3B8"],
    [0.75, "#475569"],
    [1.00, "#0F172A"],
]
PRECIPITATION_COLORSCALE = [
    [0.00, "#ffffff"],
    [0.08, "#eff6ff"],
    [0.35, "#93c5fd"],
    [0.70, "#2563eb"],
    [1.00, "#172554"],
]
SNOW_DEPTH_COLORSCALE = [
    [0.00, "#FFFFFF"],
    [0.25, "#E0F2FE"],
    [0.50, "#7DD3FC"],
    [0.75, "#0284C7"],
    [1.00, "#0C4A6E"],
]
NV_COLOR = "#059669"
NIGHT_FLUSHING_COLOR = "#0D9488"
NV_REJECTED_COLOR = "#B8C0C6"
NV_MISSING_COLOR = "#D1D5DB"
NV_SUITABILITY_COLORSCALE = [
    [0., "#FFFFFF"], [.25, "#D9EEE6"], [.5, "#96D1BC"],
    [.75, "#47B394"], [1., NV_COLOR],
]
NIGHT_FLUSHING_COLORSCALE = [
    [0., "#FFFFFF"], [.25, "#D6F2EF"], [.5, "#91D7D0"],
    [.75, "#47B6AC"], [1., NIGHT_FLUSHING_COLOR],
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
WIND_SPEED_COLUMNS = ("wind_speed_m_s","wind_gust_speed_m_s")
WIND_SPEED_OCCURRENCE_EDGES = (1.,2.,4.,6.,8.,12.)
# Absolute anchors borrow the wind-rose green family. Higher-speed
# datasets retain all values with a darker green tail above 12 m/s.
WIND_SPEED_COLORSCALE = [[0., "#FFFFFF"], [1/12, "#D1FAE5"],
    [2/12, "#A7F3D0"], [4/12, "#6EE7B7"], [6/12, "#34D399"],
    [8/12, "#10B981"], [1., "#064E3B"]]

def wind_speed_colorscale(upper=12.):
    upper=max(12.,float(upper))
    if upper==12.:return WIND_SPEED_COLORSCALE
    return [[position*12./upper,color] for position,color in WIND_SPEED_COLORSCALE]+[[1.,"#022C22"]]

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

# A direction is circular, not a scalar intensity. Geographic North has
# the identical colour at both ends of the full compass domain.
WIND_DIRECTION_COLUMNS = ("wind_direction_deg","wind_gust_direction_deg")
WIND_DIRECTION_TICKS = tuple(range(0,361,45))
WIND_DIRECTION_LABELS = ("N","NE","E","SE","S","SW","W","NW","N")
# Dedicated high-contrast cyclic heat-map palette. Do not reuse the facade
# orientation series colours: neighbouring blue/indigo sectors were difficult
# to distinguish at hourly cell size. North closes the cycle exactly.
WIND_DIRECTION_HEATMAP_COLORS = (
    "#263DAB", "#008DA8", "#249C47", "#A9BB2B",
    "#F4CE35", "#EE812B", "#CC3D61", "#8547B1", "#263DAB",
)
WIND_DIRECTION_COLORSCALE = [
    [i/8, color] for i, color in enumerate(WIND_DIRECTION_HEATMAP_COLORS)
]

METRIC_COLORS = {
    "dry_bulb_temperature_c": "#D55E00",
    "dew_point_temperature_c": "#0072B2",
    "wet_bulb_temperature_c": "#009E73",
    "relative_humidity_pct": "#2563EB",
    "humidity_ratio_g_kg": "#0891B2",
    "moist_air_enthalpy_kj_kg": "#7C3AED",
    "specific_volume_m3_kg": "#547C9A",
    "moist_air_density_kg_m3": "#475569",
    "atmospheric_station_pressure_pa": "#92734D",
    **POA_COMPONENT_COLORS,
    **SOURCE_IRRADIATION_COLORS,
    **SOURCE_IRRADIANCE_COLORS,
    "global_horizontal_illuminance_lux": "#F59E0B",
    "direct_normal_illuminance_lux": "#EA580C",
    "diffuse_horizontal_illuminance_lux": "#CA8A04",
    "wind_speed_m_s": "#059669",
    "wind_direction_deg": "#7C3AED",
    "total_sky_cover_tenths": "#475569",
    "opaque_sky_cover_tenths": "#334155",
    "liquid_precipitation_depth_mm": "#2563EB",
    "snow_depth_cm": "#0284C7",
    "precipitation_duration_min": "#2563EB",
    "wind_driven_rain_exposure": "#2563EB",
    "sunshine_duration_s": "#D97706",
    "daylight_duration_h": "#E5B83B",
    "relative_sunshine_pct": "#D97706",
    "zenith_luminance_cd_m2": "#F59E0B",
    "visibility_km": "#547C9A",
    "ceiling_height_m": "#64748B",
    "precipitable_water_mm": "#0891B2",
    "aerosol_optical_depth_thousandths": "#92734D",
    "albedo": "#92734D",
    "days_since_last_snowfall": "#0284C7",
    "absolute_humidity_g_m3": "#0891B2",
    "dynamic_pressure_pa": "#475569",
    "wind_gust_speed_m_s": "#059669",
    "wind_gust_direction_deg": "#7C3AED",
    "diffuse_radiation_fraction_pct": "#CA8A04",
    "extraterrestrial_horizontal_radiation_wh_m2": "#F59E0B",
    "extraterrestrial_direct_normal_radiation_wh_m2": "#EA580C",
    "horizontal_infrared_radiation_intensity_wh_m2": "#D55E00",
    **{column:"#D55E00" for column in TEMPERATURE_HEATMAP_COLUMNS
       if column not in ("dew_point_temperature_c","wet_bulb_temperature_c")},
    "natural_ventilation_suitable": NV_COLOR,
    "night_flushing_suitable": NIGHT_FLUSHING_COLOR,
    "heating_degree_hours_kh": HEATING_COLOR,
    "cooling_degree_hours_kh": COOLING_COLOR,
    "ventilation_heating_kw": HEATING_COLOR,
    "ventilation_cooling_kw": COOLING_COLOR,
}


# Named categories have stable identities independent of trace order.
SKY_CONDITION_COLORS = {"Clear":"#E5B83B","Intermediate":"#94A3B8","Overcast":"#334155"}
EXPOSURE_COLORS = {"Open sun":"#D97706","Direct-beam shade":"#2563EB","Uniform radiant offset":"#64748B"}
PASSIVE_STRATEGY_COLORS = {
    "Comfort":"#84CC16","Comfort without conditioning":"#84CC16",
    "Natural ventilation":NV_COLOR,"Night flushing":NIGHT_FLUSHING_COLOR,
    "Shading":"#D69A24","Solar shading likely useful":"#D69A24",
    "Solar protection screening":"#D69A24",
    "Economizer":"#047857","Air-side economizer":"#047857",
    "Heating":HEATING_COLOR,"Heating likely required":HEATING_COLOR,
    "Cooling":COOLING_COLOR,"Cooling likely required":COOLING_COLOR,
    "Humidification":"#0891B2","Humidification likely useful":"#0891B2",
    "Dehumidification":"#7C3AED","Dehumidification likely useful":"#7C3AED",
}
RAIN_DAY_COLORS = {"1–<10 mm":"#93C5FD","10–<20 mm":"#2563EB","≥20 mm":"#172554"}
DRY_SPELL_COLOR = "#B7791F"
SUNSHINE_COLORSCALE = [[0.,"#FFFFFF"],[.25,"#FEF3C7"],[.5,"#FCD34D"],[.75,"#F59E0B"],[1.,"#D97706"]]
NEUTRAL_COLORSCALE = [[0.,"#FFFFFF"],[.5,"#94A3B8"],[1.,"#334155"]]

# Rejection mechanisms retain the physical quantity palette. Temperature
# colours indicate outdoor exposure (cold/hot), rather than HVAC service.
NV_REJECTION_REASON_COLORS = {
    "Too cold": COOLING_COLOR,
    "Too hot": HEATING_COLOR,
    "Too humid": METRIC_COLORS["humidity_ratio_g_kg"],
    "Wind too weak": WIND_SPEED_COLORS[1],
    "Wind too strong": WIND_SPEED_COLORS[-1],
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
    if column and "temperature" in str(column).lower() and column!="wet_bulb_temperature_c":
        return "#2563EB", METRIC_COLORS["dry_bulb_temperature_c"], "#DC2626", "rgba(107,114,128,0.16)"
    base = metric_color(column)
    return _mix_with_white(base, 0.48), base, _darken(base, 0.22), rgba(base, 0.14)


def semantic_color_from_text(text: str | None) -> str:
    """Infer a semantic colour from a displayed series/title string."""
    value = (text or "").strip().lower()
    if not value:
        return DEFAULT_METRIC_COLOR
    # Threshold-duration charts share a yellow semantic colour, independent
    # of the source component palette. Accept compact and spaced labels.
    compact="".join(value.split()).replace(">=","≥")
    if "≥300lux" in compact:
        return ILLUMINANCE_THRESHOLD_COLOR

    if value in ORIENTATION_COLORS:
        return ORIENTATION_COLORS[value]
    if value in METRIC_COLORS:
        return METRIC_COLORS[value]
    # These named quantities must also resolve correctly in title-driven
    # chart builders that do not receive the canonical column identifier.
    quantity_text = value.replace("-", " ").replace("_", " ")
    for mapping in (PASSIVE_STRATEGY_COLORS,EXPOSURE_COLORS,SKY_CONDITION_COLORS,RAIN_DAY_COLORS):
        for label,colour in mapping.items():
            if value==label.lower():return colour
    if value.startswith(("clear ","intermediate ","overcast ")):
        return SKY_CONDITION_COLORS[value.split()[0].capitalize()]
    if "freeze" in quantity_text or "frost" in value:
        return METRIC_COLORS["humidity_ratio_g_kg"] if "wet" in value else COOLING_COLOR
    if "tropical night" in value:return HEATING_COLOR
    if "wind driven rain" in quantity_text or "precipitation" in value or "rainfall" in value:
        return METRIC_COLORS["liquid_precipitation_depth_mm"]
    if "snow" in value:return METRIC_COLORS["snow_depth_cm"]
    if "sunshine" in value:return METRIC_COLORS["sunshine_duration_s"]
    if "daylight" in value:return METRIC_COLORS["daylight_duration_h"]
    if "enthalpy" in value:return METRIC_COLORS["moist_air_enthalpy_kj_kg"]
    if "relative humidity" in quantity_text:return METRIC_COLORS["relative_humidity_pct"]
    if "dew point" in quantity_text:return METRIC_COLORS["dew_point_temperature_c"]
    if "wet bulb" in quantity_text:return METRIC_COLORS["wet_bulb_temperature_c"]
    if "poa" in quantity_text or "plane of array" in quantity_text:
        if "ground" in quantity_text or "reflected" in quantity_text:return POA_COMPONENT_COLORS["poa_ground_diffuse_wh_m2"]
        if "sky" in quantity_text or "diffuse" in quantity_text:return POA_COMPONENT_COLORS["poa_sky_diffuse_wh_m2"]
        if "direct" in quantity_text:return POA_COMPONENT_COLORS["poa_direct_wh_m2"]
        return POA_COMPONENT_COLORS["poa_global_wh_m2"]
    for tokens, column in (
        (("specific volume",), "specific_volume_m3_kg"),
        (("moist air density", "air density"), "moist_air_density_kg_m3"),
        (("station pressure", "atmospheric pressure", "barometric pressure"), "atmospheric_station_pressure_pa"),
    ):
        if any(token in quantity_text for token in tokens):
            return METRIC_COLORS[column]
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
    if "night flushing" in quantity_text or "night flushing" in value:
        return NIGHT_FLUSHING_COLOR
    if "natural ventilation" in quantity_text or "economizer" in value or "suitable" in value:
        return NV_COLOR
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
    return semantic_color_from_text(fallback_column) if fallback_column else DEFAULT_METRIC_COLOR


def climate_color_map(names: Iterable[str]) -> dict[str, str]:
    """Return deterministic colours by climate order for one comparison view."""
    return {str(name): CLIMATE_COLORS[index % len(CLIMATE_COLORS)] for index, name in enumerate(names)}


def metric_colorscale(column: str | None):
    """Return a continuous colourscale suitable for the selected metric."""
    text = str(column or "").lower()
    if text in ("liquid_precipitation_depth_mm","precipitation_duration_min","wind_driven_rain_exposure"):
        return PRECIPITATION_COLORSCALE
    if text in ("snow_depth_cm","days_since_last_snowfall"):
        return SNOW_DEPTH_COLORSCALE
    if text=="relative_humidity_pct":
        return RELATIVE_HUMIDITY_COLORSCALE
    if text in ("humidity_ratio_g_kg","absolute_humidity_g_m3","precipitable_water_mm"):
        return HUMIDITY_RATIO_COLORSCALE
    if text in TEMPERATURE_HEATMAP_COLUMNS:
        return TEMPERATURE_COMFORT_COLORSCALE
    if text=="moist_air_enthalpy_kj_kg":
        return MOIST_AIR_ENTHALPY_COLORSCALE
    if text=="specific_volume_m3_kg":
        return SPECIFIC_VOLUME_COLORSCALE
    if text=="atmospheric_station_pressure_pa":
        return STATION_PRESSURE_COLORSCALE
    if text=="moist_air_density_kg_m3":
        return MOIST_AIR_DENSITY_COLORSCALE
    if text in ("sunshine_duration_s","daylight_duration_h","relative_sunshine_pct"):return SUNSHINE_COLORSCALE
    if text in ("dynamic_pressure_pa","ceiling_height_m"):return MOIST_AIR_DENSITY_COLORSCALE
    if text in ("visibility_km",):return SPECIFIC_VOLUME_COLORSCALE
    if text in ("aerosol_optical_depth_thousandths","albedo"):return STATION_PRESSURE_COLORSCALE
    if "illuminance" in text or "luminance" in text:
        return ILLUMINANCE_COLORSCALE
    if is_irradiation_metric(text):
        return SOLAR_COLORSCALE
    if "sky_cover" in text:
        return [[0.0, "rgba(255,255,255,0.0)"], [0.25, "#dbeafe"], [1.0, "#0f172a"]]
    if text in WIND_SPEED_COLUMNS:
        return WIND_SPEED_COLORSCALE
    if text in WIND_DIRECTION_COLUMNS:
        return WIND_DIRECTION_COLORSCALE
    if "wind" in text:
        return WIND_SPEED_COLORSCALE
    if "night_flushing" in text or "night flushing" in text:return NIGHT_FLUSHING_COLORSCALE
    if "natural_ventilation" in text or "natural ventilation" in text:return NV_SUITABILITY_COLORSCALE
    if "suitable" in text or "ventilation" in text:
        return BINARY_SUITABILITY_COLORSCALE
    return NEUTRAL_COLORSCALE


def event_color(quantity, above):
    """Colour an event by its physical mechanism rather than sort order."""
    text=str(quantity).lower()
    if "precipitation" in text or "rain" in text or text=="mm":
        return METRIC_COLORS["liquid_precipitation_depth_mm"] if above else DRY_SPELL_COLOR
    if "temperature" in text or "°c" in text:return HEATING_COLOR if above else COOLING_COLOR
    return semantic_color_from_text(quantity)

# Detect in-process modules retained from an earlier Streamlit deployment.
from hashlib import sha256 as _runtime_sha256
from pathlib import Path as _RuntimePath
_RUNTIME_SOURCE_SHA256 = _runtime_sha256(_RuntimePath(__file__).read_bytes()).hexdigest()
