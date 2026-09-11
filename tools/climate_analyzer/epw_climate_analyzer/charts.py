"""Plotly chart factory functions for EPW climate analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
import psychrolib

from .aggregations import aggregate_summary, aggregate_sum, calendar_matrix, duration_curve, monthly_box_data, monthly_hour_matrix
from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves

psychrolib.SetUnitSystem(psychrolib.SI)


PLOT_TEMPLATE = "plotly_white"
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
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
BINARY_BLUE_COLORSCALE = [
    [0.00, "rgba(255,255,255,0.0)"],
    [0.01, "#eff6ff"],
    [1.00, "#1d4ed8"],
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

PHYSICAL_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "relative_humidity_pct": (0.0, 100.0),
    "humidity_ratio_g_kg": (0.0, None),
    "specific_volume_m3_kg": (0.0, None),
    "moist_air_density_kg_m3": (0.0, None),
    "atmospheric_station_pressure_pa": (30000.0, 120000.0),
    "global_horizontal_radiation_wh_m2": (0.0, None),
    "direct_normal_radiation_wh_m2": (0.0, None),
    "diffuse_horizontal_radiation_wh_m2": (0.0, None),
    "global_horizontal_illuminance_lux": (0.0, None),
    "direct_normal_illuminance_lux": (0.0, None),
    "diffuse_horizontal_illuminance_lux": (0.0, None),
    "wind_speed_m_s": (0.0, None),
    "wind_direction_deg": (0.0, 360.0),
    "total_sky_cover_tenths": (0.0, 10.0),
    "opaque_sky_cover_tenths": (0.0, 10.0),
    "liquid_precipitation_depth_mm": (0.0, None),
    "snow_depth_cm": (0.0, None),
    "natural_ventilation_suitable": (0.0, 1.0),
    "night_flushing_suitable": (0.0, 1.0),
}


def _finite_min_max(values) -> tuple[float | None, float | None]:
    """Return finite minimum and maximum for a vector-like object."""
    arr = np.asarray(values, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None, None
    return float(np.nanmin(arr)), float(np.nanmax(arr))


def _axis_limits_for_column(column: str, values=None, pad_fraction: float = 0.05) -> tuple[float | None, float | None]:
    """Return readable axis limits constrained by physical bounds where known."""
    physical_min, physical_max = PHYSICAL_BOUNDS.get(column, (None, None))
    data_min, data_max = _finite_min_max(values) if values is not None else (None, None)
    if data_min is None or data_max is None:
        return physical_min, physical_max
    span = max(data_max - data_min, 1e-9)
    lo = data_min - span * pad_fraction
    hi = data_max + span * pad_fraction
    if physical_min is not None:
        lo = max(lo, physical_min)
    if physical_max is not None:
        hi = min(hi, physical_max)
    if abs(hi - lo) < 1e-9:
        hi = lo + 1.0
    return lo, hi


def _apply_axis_constraints(fig: go.Figure, column: str | None = None, x_values=None, y_values=None, y_column: str | None = None) -> go.Figure:
    """Apply initial ranges and allowed autorange limits without disabling zoom."""
    if y_column or column:
        lo, hi = _axis_limits_for_column(y_column or column or "", y_values)
        if lo is not None or hi is not None:
            fig.update_yaxes(range=[lo, hi], autorangeoptions=dict(minallowed=lo, maxallowed=hi))
    if x_values is not None:
        try:
            finite = pd.Series(x_values).dropna()
            if not finite.empty and not pd.api.types.is_string_dtype(finite):
                fig.update_xaxes(range=[finite.min(), finite.max()], autorangeoptions=dict(minallowed=finite.min(), maxallowed=finite.max()))
        except Exception:
            pass
    return fig


def _period_x(summary: pd.DataFrame, aggregation: str) -> list:
    """Return human-readable x values for an aggregated summary table."""
    idx = summary.index
    if aggregation == "Monthly":
        if isinstance(idx, pd.DatetimeIndex):
            return [MONTH_LABELS[i - 1] for i in idx.month]
        return [MONTH_LABELS[int(i) - 1] if str(i).isdigit() and 1 <= int(i) <= 12 else str(i) for i in idx]
    if aggregation == "Weekly":
        if isinstance(idx, pd.DatetimeIndex):
            return [f"W{int(i.isocalendar().week):02d}" for i in idx]
        return [f"W{int(i):02d}" if str(i).isdigit() else str(i) for i in idx]
    if aggregation == "Daily":
        if isinstance(idx, pd.DatetimeIndex):
            return [int(i.dayofyear) for i in idx]
        return list(idx)
    return list(idx)


def _heatmap_colorscale(column: str, values=None, temperature_thresholds: tuple[float, float] | None = None):
    """Return a colorscale suitable for the selected climate variable."""
    if column == "dry_bulb_temperature_c" and temperature_thresholds is not None:
        heat_t, cool_t = temperature_thresholds
        vmin, vmax = _finite_min_max(values)
        if vmin is None or vmax is None or abs(vmax - vmin) < 1e-9:
            return TEMPERATURE_COMFORT_COLORSCALE
        green_start = max(0.0, min(1.0, (heat_t - vmin) / (vmax - vmin)))
        green_end = max(green_start + 1e-6, min(1.0, (cool_t - vmin) / (vmax - vmin)))
        return [[0.0, "#1d4ed8"], [green_start, "#22c55e"], [green_end, "#22c55e"], [1.0, "#dc2626"]]
    if column in {"natural_ventilation_suitable", "night_flushing_suitable"} or "suitable" in column:
        return BINARY_BLUE_COLORSCALE
    if "sky_cover" in column:
        return [[0.0, "rgba(255,255,255,0.0)"], [0.25, "#dbeafe"], [1.0, "#0f172a"]]
    if "radiation" in column or "irradiance" in column or "illuminance" in column:
        return SOLAR_COLORSCALE
    return "Viridis"


def apply_common_layout(fig: go.Figure, title: str, x_label: str, y_label: str) -> go.Figure:
    """Apply a consistent layout to all figures."""
    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title=y_label,
        template=PLOT_TEMPLATE,
        hovermode="x unified",
        legend_title_text="Series",
        margin=dict(l=40, r=20, t=70, b=45),
    )
    return fig


def profile_ribbon_chart(
    df: pd.DataFrame,
    column: str,
    aggregation: str,
    title: str,
    unit: str,
    extensive: bool = False,
) -> go.Figure:
    """Create an hourly line or aggregated min/mean/max ribbon chart.

    The aggregated mode exposes minimum, central and maximum values at the
    same x-position through Plotly's unified hover. This makes the ribbon useful
    for copying exact min/mean/max values without searching separate points.
    """
    if extensive:
        summary = aggregate_sum(df, column, aggregation)
        central = "sum" if aggregation != "Hourly" else "mean"
    else:
        summary = aggregate_summary(df, column, aggregation)
        central = "mean"

    fig = go.Figure()
    if aggregation == "Hourly":
        x = summary.index
        fig.add_trace(
            go.Scatter(
                x=x,
                y=summary[central],
                mode="lines",
                name=f"Hourly {unit}",
                hovertemplate="%{x}<br>Value: %{y:.2f} " + unit + "<extra></extra>",
            )
        )
        fig = apply_common_layout(fig, title, "Time", unit)
        return _apply_axis_constraints(fig, column=column, x_values=x, y_values=summary[central])

    x = _period_x(summary, aggregation)
    fig.add_trace(
        go.Scatter(
            x=x,
            y=summary["max"],
            mode="lines+markers",
            name="Maximum",
            line=dict(color="red", width=1.4),
            hovertemplate="Maximum: %{y:.2f} " + unit + "<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=summary["min"],
            mode="lines+markers",
            name="Minimum",
            line=dict(color="blue", width=1.4),
            fill="tonexty",
            fillcolor="rgba(120,120,120,0.18)",
            hovertemplate="Minimum: %{y:.2f} " + unit + "<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=summary[central],
            mode="lines+markers",
            name="Mean" if central == "mean" else "Sum",
            line=dict(width=2.2),
            hovertemplate=("Mean: %{y:.2f} " + unit + "<extra></extra>") if central == "mean" else ("Sum: %{y:.2f} " + unit + "<extra></extra>"),
        )
    )
    fig = apply_common_layout(fig, title, "Period", unit)
    if aggregation == "Monthly":
        fig.update_xaxes(categoryorder="array", categoryarray=MONTH_LABELS)
    return _apply_axis_constraints(fig, column=column, y_values=pd.concat([summary["min"], summary[central], summary["max"]]))

def percentile_band_chart(df: pd.DataFrame, column: str, aggregation: str, title: str, unit: str) -> go.Figure:
    """Create a percentile-band chart using P05, median and P95."""
    summary = aggregate_summary(df, column, aggregation)
    x = _period_x(summary, aggregation)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=summary["p95"], mode="lines+markers", name="P95", hovertemplate="P95: %{y:.2f} " + unit + "<extra></extra>"))
    fig.add_trace(
        go.Scatter(
            x=x,
            y=summary["p05"],
            mode="lines+markers",
            name="P05",
            fill="tonexty",
            fillcolor="rgba(120,120,120,0.18)",
            hovertemplate="P05: %{y:.2f} " + unit + "<extra></extra>",
        )
    )
    fig.add_trace(go.Scatter(x=x, y=summary["median"], mode="lines+markers", name="Median", hovertemplate="Median: %{y:.2f} " + unit + "<extra></extra>"))
    fig = apply_common_layout(fig, title, "Period", unit)
    if aggregation == "Monthly":
        fig.update_xaxes(categoryorder="array", categoryarray=MONTH_LABELS)
    return _apply_axis_constraints(fig, column=column, y_values=pd.concat([summary["p05"], summary["median"], summary["p95"]]))

def heatmap_chart(
    df: pd.DataFrame,
    column: str,
    row_group: str,
    title: str,
    unit: str,
    temperature_thresholds: tuple[float, float] | None = None,
) -> go.Figure:
    """Create a period-by-hour heatmap with period on x-axis and hour on y-axis."""
    matrix = calendar_matrix(df, column, row_group=row_group)
    z = matrix.T
    colorscale = _heatmap_colorscale(column, z.values, temperature_thresholds)
    zmin, zmax = _axis_limits_for_column(column, z.values, pad_fraction=0.0)
    fig = px.imshow(
        z,
        aspect="auto",
        color_continuous_scale=colorscale,
        zmin=zmin,
        zmax=zmax,
        labels=dict(x=row_group.capitalize(), y="Hour of day", color=unit),
        title=title,
    )
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    fig.update_yaxes(range=[23, 0], autorangeoptions=dict(minallowed=0, maxallowed=23))
    return fig


def month_hour_heatmap(
    df: pd.DataFrame,
    column: str,
    title: str,
    unit: str,
    aggfunc: str = "mean",
    temperature_thresholds: tuple[float, float] | None = None,
) -> go.Figure:
    """Create a month-by-hour heatmap with month on x-axis and hour on y-axis."""
    matrix = monthly_hour_matrix(df, column, aggfunc=aggfunc)
    z = matrix.T
    colorscale = _heatmap_colorscale(column, z.values, temperature_thresholds)
    zmin, zmax = _axis_limits_for_column(column, z.values, pad_fraction=0.0)
    fig = px.imshow(
        z,
        aspect="auto",
        color_continuous_scale=colorscale,
        zmin=zmin,
        zmax=zmax,
        labels=dict(x="Month", y="Hour of day", color=unit),
        title=title,
    )
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)
    fig.update_yaxes(range=[23, 0], autorangeoptions=dict(minallowed=0, maxallowed=23))
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return fig

def duration_chart(df: pd.DataFrame, column: str, title: str, unit: str, ascending: bool = False) -> go.Figure:
    """Create a sorted duration curve."""
    values = duration_curve(df, column, ascending=ascending)
    fig = px.line(values, x="rank_hour", y=column, title=title, labels={"rank_hour": "Sorted hour", column: unit})
    fig.update_traces(hovertemplate="Sorted hour: %{x}<br>Value: %{y:.2f} " + unit + "<extra></extra>")
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return _apply_axis_constraints(fig, column=column, x_values=values["rank_hour"], y_values=values[column])

def histogram_chart(df: pd.DataFrame, column: str, title: str, unit: str, bins: int = 40) -> go.Figure:
    """Create an interactive histogram."""
    data = df[[column]].dropna()
    fig = px.histogram(data, x=column, nbins=bins, title=title, labels={column: unit})
    fig.update_layout(template=PLOT_TEMPLATE, yaxis_title="Hours", margin=dict(l=40, r=20, t=70, b=45))
    lo, hi = _axis_limits_for_column(column, data[column], pad_fraction=0.03)
    if lo is not None or hi is not None:
        fig.update_xaxes(range=[lo, hi], autorangeoptions=dict(minallowed=lo, maxallowed=hi))
    return fig

def monthly_box_chart(df: pd.DataFrame, column: str, title: str, unit: str, violin: bool = False) -> go.Figure:
    """Create monthly boxplot or violin plot."""
    data = monthly_box_data(df, column)
    data["month_name"] = pd.Categorical(data["month_name"], MONTH_LABELS, ordered=True)
    if violin:
        fig = px.violin(data, x="month_name", y=column, box=True, points=False, title=title)
    else:
        fig = px.box(data, x="month_name", y=column, title=title)
    fig = apply_common_layout(fig, title, "Month", unit)
    fig.update_xaxes(categoryorder="array", categoryarray=MONTH_LABELS)
    return _apply_axis_constraints(fig, column=column, y_values=data[column])

def threshold_bar_chart(counts: pd.DataFrame, title: str, unit: str = "hours") -> go.Figure:
    """Create a bar chart for threshold-hour counts with readable period labels."""
    column = counts.columns[0]
    data = counts.copy()
    # Preserve correct period order while avoiding unreadable month-end datetime
    # labels such as "Mar 2026" for a typical-year monthly chart.
    if isinstance(data.index, pd.DatetimeIndex):
        if len(data) <= 12 and data.index.to_series().dt.is_month_end.all():
            data = data.copy()
            data["Period"] = [MONTH_LABELS[int(i.month) - 1] for i in data.index]
            categoryarray = MONTH_LABELS
        elif len(data) <= 60:
            data = data.copy()
            data["Period"] = [f"W{int(i.isocalendar().week):02d}" for i in data.index]
            categoryarray = None
        else:
            data = data.copy()
            data["Period"] = [int(i.dayofyear) for i in data.index]
            categoryarray = None
    else:
        data = data.reset_index().rename(columns={data.index.name or "index": "Period"})
        categoryarray = MONTH_LABELS if set(data["Period"].astype(str)).issubset(set(MONTH_LABELS)) else None
    if "Period" not in data.columns:
        data = data.reset_index().rename(columns={data.index.name or "index": "Period"})
    fig = px.bar(data, x="Period", y=column, title=title)
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Period", yaxis_title=unit, margin=dict(l=40, r=20, t=70, b=45))
    if categoryarray is not None:
        fig.update_xaxes(categoryorder="array", categoryarray=categoryarray)
    fig.update_yaxes(range=[0, max(float(data[column].max()) * 1.05, 1.0)], autorangeoptions=dict(minallowed=0))
    return fig

def scatter_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str | None,
    title: str,
    x_label: str,
    y_label: str,
) -> go.Figure:
    """Create a general scatter chart for climate-variable relationships."""
    data = df[[x, y] + ([color] if color else [])].dropna()
    fig = px.scatter(data, x=x, y=y, color=color, opacity=0.65, title=title, render_mode="webgl")
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title=x_label, yaxis_title=y_label, margin=dict(l=40, r=20, t=70, b=45))
    lo, hi = _axis_limits_for_column(x, data[x])
    if lo is not None or hi is not None:
        fig.update_xaxes(range=[lo, hi], autorangeoptions=dict(minallowed=lo, maxallowed=hi))
    return _apply_axis_constraints(fig, y_column=y, y_values=data[y])


def _psychrometric_point_from_td(t_c: float, d_g_kg: float, chart_type: str) -> tuple[float, float]:
    """Return chart coordinates for a dry-bulb temperature and humidity-ratio point."""
    w = max(float(d_g_kg), 0.0) / 1000.0
    if chart_type == "i-d":
        return float(d_g_kg), psychrolib.GetMoistAirEnthalpy(float(t_c), w) / 1000.0
    return float(t_c), float(d_g_kg)


def _humidity_ratio_from_t_rh(t_c: float, rh_pct: float, pressure_pa: float) -> float:
    """Return humidity ratio in g/kg dry air for temperature and relative humidity."""
    rh = max(0.0, min(1.0, float(rh_pct) / 100.0))
    return psychrolib.GetHumRatioFromRelHum(float(t_c), rh, float(pressure_pa)) * 1000.0


def _sat_humidity_ratio_g_kg(t_c: float, pressure_pa: float) -> float:
    """Return saturated humidity ratio in g/kg dry air for a dry-bulb temperature."""
    return psychrolib.GetSatHumRatio(float(t_c), float(pressure_pa)) * 1000.0


def _humidity_ratio_from_enthalpy_t(h_kj_kg: float, t_c: float) -> float:
    """Return humidity ratio in g/kg from moist-air enthalpy and dry-bulb temperature."""
    denominator = 2501.0 + 1.86 * float(t_c)
    if abs(denominator) < 1e-9:
        return np.nan
    return (float(h_kj_kg) - 1.006 * float(t_c)) / denominator * 1000.0


def _heat_index_celsius(t_c: float, rh_pct: float) -> float:
    """Return heat index in °C using the NOAA/Rothfusz regression.

    The regression is evaluated in IP units and converted back to SI. It is used
    here as a screening overlay for hot-humid outdoor-air conditions.
    """
    t_f = float(t_c) * 9.0 / 5.0 + 32.0
    rh = float(rh_pct)
    hi_f = (
        -42.379
        + 2.04901523 * t_f
        + 10.14333127 * rh
        - 0.22475541 * t_f * rh
        - 0.00683783 * t_f * t_f
        - 0.05481717 * rh * rh
        + 0.00122874 * t_f * t_f * rh
        + 0.00085282 * t_f * rh * rh
        - 0.00000199 * t_f * t_f * rh * rh
    )
    return (hi_f - 32.0) * 5.0 / 9.0



GIVONI_ZONE_NAMES: dict[int, str] = {
    1: "Comfort zone",
    2: "Permissible comfort zone",
    3: "Heating by internal gains",
    4: "Passive solar heating",
    5: "Active solar heating",
    6: "Humidification",
    7: "Conventional heating",
    8: "Solar protection",
    9: "Cooling by high thermal mass",
    10: "Evaporative cooling",
    11: "Cooling by high thermal mass with night ventilation",
    12: "Cooling by natural and mechanical ventilation",
    13: "Air conditioning",
    14: "Conventional dehumidification",
}

GIVONI_ZONE_STRATEGIES: dict[int, str] = {
    1: "Core comfort region where passive operation may be sufficient if indoor conditions can be kept close to outdoor psychrometric conditions.",
    2: "Extended comfort region; acceptable conditions become more likely with acclimatization, adaptive behaviour or low-energy support.",
    3: "Cool conditions where internal gains from people, equipment and lighting may move indoor conditions toward comfort.",
    4: "Cold-to-mild conditions where useful passive solar gains can extend the comfort period.",
    5: "Colder conditions where active solar or auxiliary heating support is usually required.",
    6: "Very dry conditions where humidification may be relevant if indoor humidity targets are important.",
    7: "Cold conditions outside passive-solar reach; conventional heating or strong heat recovery is typically indicated.",
    8: "Warm-to-hot conditions where solar protection is a primary envelope and façade strategy.",
    9: "Warm conditions where high thermal mass can dampen daytime peaks if the diurnal range is useful.",
    10: "Hot-dry conditions where evaporative cooling has climatic potential.",
    11: "Hot conditions where high thermal mass combined with night ventilation can extend comfort.",
    12: "Warm conditions where natural or mechanical air movement can extend comfort.",
    13: "Hot or hot-humid conditions where mechanical cooling is likely.",
    14: "Very humid conditions where dehumidification is likely to be required.",
}

# Manual Givoni-Milne zone definitions supplied by the user.  Points are
# expressed in dry-bulb temperature and either relative humidity, humidity ratio,
# or a humidity-ratio reference point.  They are resolved using the active chart
# pressure, then converted to the selected chart axes.
GIVONI_ZONE_DATA: dict[int, dict[str, object]] = {
    1: {
        "points": [
            (21.0, {"rh_percent": 20.0}),
            (26.0, {"rh_percent": 20.0}),
            (26.0, {"rh_percent": 50.0}),
            (24.0, {"rh_percent": 75.0}),
            (21.0, {"rh_percent": 75.0}),
        ],
        "edges": ["constant_rh", "constant_t", "straight", "constant_rh", "constant_t"],
        "spline": False,
    },
    2: {
        "points": [
            (20.0, {"rh_percent": 20.0}),
            (27.0, {"rh_percent": 20.0}),
            (27.0, {"rh_percent": 50.0}),
            (24.5, {"rh_percent": 80.0}),
            (20.0, {"rh_percent": 80.0}),
        ],
        "edges": ["constant_rh", "constant_t", "straight", "constant_rh", "constant_t"],
        "spline": False,
    },
    3: {
        "points": [
            (13.5, {"w_g_per_kg": 0.0}),
            (13.5, {"rh_percent": 100.0}),
            (20.0, {"rh_percent": 100.0}),
            (20.0, {"w_g_per_kg": 0.0}),
        ],
        "edges": ["constant_t", "saturation_curve", "constant_t", "constant_w"],
        "spline": False,
    },
    4: {
        "points": [
            (13.5, {"w_g_per_kg": 0.0}),
            (13.5, {"rh_percent": 100.0}),
            (7.0, {"rh_percent": 100.0}),
            (7.0, {"w_g_per_kg": 0.0}),
        ],
        "edges": ["constant_t", "saturation_curve", "constant_t", "constant_w"],
        "spline": False,
    },
    5: {
        "points": [
            (1.5, {"w_g_per_kg": 0.0}),
            (1.5, {"rh_percent": 100.0}),
            (7.0, {"rh_percent": 100.0}),
            (7.0, {"w_g_per_kg": 0.0}),
        ],
        "edges": ["constant_t", "saturation_curve", "constant_t", "constant_w"],
        "spline": False,
    },
    6: {
        "points": [
            (-10.0, {"w_g_per_kg": 0.0}),
            (-10.0, {"rh_percent": 20.0}),
            (1.5, {"rh_percent": 20.0}),
            (7.0, {"rh_percent": 40.0}),
            (12.0, {"rh_percent": 40.0}),
            (14.0, {"same_w_as": (12.0, 40.0)}),
            (15.0, {"rh_percent": 20.0}),
            (20.0, {"rh_percent": 10.0}),
            (23.0, {"rh_percent": 0.0}),
        ],
        "edges": None,
        "spline": True,
    },
    7: {
        "points": [
            (1.5, {"w_g_per_kg": 0.0}),
            (1.5, {"rh_percent": 100.0}),
            (-10.0, {"rh_percent": 100.0}),
            (-10.0, {"w_g_per_kg": 0.0}),
        ],
        "edges": ["constant_t", "saturation_curve", "constant_t", "constant_w"],
        "spline": False,
    },
    8: {
        "points": [
            (20.0, {"w_g_per_kg": 0.0}),
            (20.0, {"rh_percent": 100.0}),
            (50.0, {"rh_percent": 100.0}),
            (50.0, {"w_g_per_kg": 0.0}),
        ],
        "edges": ["constant_t", "saturation_curve", "constant_t", "constant_w"],
        "spline": False,
    },
    9: {
        "points": [
            (20.0, {"rh_percent": 20.0}),
            (27.0, {"rh_percent": 20.0}),
            (27.0, {"rh_percent": 50.0}),
            (24.5, {"rh_percent": 80.0}),
            (31.5, {"same_w_as": (24.5, 80.0)}),
            (32.0, {"rh_percent": 50.0}),
            (36.0, {"rh_percent": 30.0}),
            (36.0, {"same_w_as": (20.0, 20.0)}),
        ],
        "edges": ["constant_rh", "constant_t", "straight", "constant_w", "straight", "straight", "constant_t", "constant_w"],
        "spline": False,
    },
    10: {
        "points": [
            (20.0, {"rh_percent": 20.0}),
            (27.0, {"rh_percent": 20.0}),
            (27.0, {"rh_percent": 50.0}),
            (24.5, {"rh_percent": 80.0}),
            (38.5, {"rh_percent": 20.0}),
            (40.5, {"rh_percent": 10.0}),
            (40.5, {"w_g_per_kg": 0.0}),
            (26.0, {"w_g_per_kg": 0.0}),
        ],
        "edges": ["constant_rh", "constant_t", "straight", "straight", "straight", "constant_t", "constant_w", "straight"],
        "spline": False,
    },
    11: {
        "points": [
            (32.0, {"rh_percent": 50.0}),
            (40.0, {"same_w_as": (32.0, 50.0)}),
            (43.5, {"rh_percent": 20.0}),
            (43.5, {"same_w_as": (20.0, 20.0)}),
            (36.0, {"same_w_as": (20.0, 20.0)}),
            (36.0, {"rh_percent": 30.0}),
        ],
        "edges": ["constant_w", "straight", "constant_t", "constant_w", "constant_t", "straight"],
        "spline": False,
    },
    12: {
        "points": [
            (27.0, {"rh_percent": 20.0}),
            (27.0, {"rh_percent": 50.0}),
            (24.5, {"rh_percent": 80.0}),
            (20.0, {"rh_percent": 80.0}),
            (20.0, {"rh_percent": 100.0}),
            (27.0, {"rh_percent": 100.0}),
            (29.0, {"rh_percent": 80.0}),
            (32.0, {"rh_percent": 50.0}),
            (32.0, {"rh_percent": 20.0}),
        ],
        "edges": ["constant_t", "straight", "constant_rh", "constant_t", "saturation_curve", "straight", "straight", "constant_t", "constant_rh"],
        "spline": False,
    },
    13: {
        "points": [
            (32.0, {"rh_percent": 50.0}),
            (29.0, {"rh_percent": 80.0}),
            (50.0, {"rh_percent": 80.0}),
            (50.0, {"w_g_per_kg": 0.0}),
            (40.5, {"w_g_per_kg": 0.0}),
            (40.5, {"same_w_as": (20.0, 20.0)}),
            (43.5, {"same_w_as": (20.0, 20.0)}),
            (43.5, {"rh_percent": 20.0}),
            (40.0, {"same_w_as": (32.0, 50.0)}),
        ],
        "edges": ["straight", "constant_rh", "constant_t", "constant_w", "constant_t", "constant_w", "constant_t", "straight", "constant_w"],
        "spline": False,
    },
    14: {
        "points": [
            (29.0, {"rh_percent": 80.0}),
            (27.0, {"rh_percent": 100.0}),
            (50.0, {"rh_percent": 100.0}),
            (50.0, {"rh_percent": 80.0}),
        ],
        "edges": ["straight", "saturation_curve", "constant_t", "constant_rh"],
        "spline": False,
    },
}

GIVONI_DRAW_ORDER: list[int] = [8, 7, 5, 4, 3, 6, 2, 1, 9, 10, 11, 12, 13, 14]
GIVONI_LABEL_POSITIONS: dict[int, tuple[float, float]] = {
    1: (23.5, 8.0),
    2: (24.0, 9.1),
    3: (16.8, 6.1),
    4: (10.2, 4.1),
    5: (4.2, 2.6),
    6: (9.2, 1.2),
    7: (-4.2, 1.5),
    8: (35.0, 14.7),
    9: (28.7, 8.9),
    10: (34.6, 5.8),
    11: (38.3, 9.7),
    12: (26.1, 12.5),
    13: (40.9, 12.0),
    14: (38.9, 27.1),
}

GIVONI_ZONE_COLORS: dict[int, tuple[str, str, str]] = {
    1: ("#16a34a", "rgba(22,163,74,0.12)", "Comfort"),
    2: ("#059669", "rgba(5,150,105,0.08)", "Permissible"),
    3: ("#f97316", "rgba(249,115,22,0.08)", "Internal gains"),
    4: ("#eab308", "rgba(234,179,8,0.08)", "Passive solar"),
    5: ("#3b82f6", "rgba(59,130,246,0.07)", "Active solar"),
    6: ("#d946ef", "rgba(217,70,239,0.07)", "Humidification"),
    7: ("#7e22ce", "rgba(126,34,206,0.07)", "Heating"),
    8: ("#f59e0b", "rgba(245,158,11,0.055)", "Solar protection"),
    9: ("#6366f1", "rgba(99,102,241,0.075)", "High thermal mass"),
    10: ("#ef4444", "rgba(239,68,68,0.085)", "Evaporative cooling"),
    11: ("#f43f5e", "rgba(244,63,94,0.08)", "Mass + night vent."),
    12: ("#0ea5e9", "rgba(14,165,233,0.075)", "Ventilation"),
    13: ("#be123c", "rgba(190,18,60,0.06)", "Air conditioning"),
    14: ("#9d174d", "rgba(157,23,77,0.06)", "Dehumidification"),
}

GIVONI_OUTLINE_COLOR = "rgba(30,58,138,0.92)"

# Backwards-compatible list used by the report and by any earlier call sites.
GIVONI_MILNE_ZONES: list[dict[str, object]] = [
    {
        "zone_id": zone_id,
        "name": GIVONI_ZONE_NAMES[zone_id],
        "label": GIVONI_ZONE_COLORS[zone_id][2],
        "strategy": GIVONI_ZONE_STRATEGIES[zone_id],
    }
    for zone_id in sorted(GIVONI_ZONE_NAMES)
]


def _resolve_givoni_point(point_spec: tuple[float, object], pressure_pa: float) -> tuple[float, float]:
    """Resolve a Givoni point specification to dry-bulb temperature and humidity ratio."""
    t_c, spec = point_spec
    if isinstance(spec, (int, float)):
        return float(t_c), _humidity_ratio_from_t_rh(float(t_c), float(spec), pressure_pa)
    if not isinstance(spec, dict):
        raise ValueError(f"Unsupported Givoni point specification: {point_spec}")
    if "rh_percent" in spec:
        return float(t_c), _humidity_ratio_from_t_rh(float(t_c), float(spec["rh_percent"]), pressure_pa)
    if "w_g_per_kg" in spec:
        return float(t_c), float(spec["w_g_per_kg"])
    if "same_w_as" in spec:
        ref_t, ref_rh = spec["same_w_as"]
        return float(t_c), _humidity_ratio_from_t_rh(float(ref_t), float(ref_rh), pressure_pa)
    raise ValueError(f"Unsupported Givoni point specification: {point_spec}")


def _sample_givoni_segment(
    point_a: tuple[float, object],
    point_b: tuple[float, object],
    edge_type: str,
    pressure_pa: float,
    n: int = 120,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample a Givoni boundary segment while preserving RH and saturation curves."""
    t_a, w_a = _resolve_givoni_point(point_a, pressure_pa)
    t_b, w_b = _resolve_givoni_point(point_b, pressure_pa)
    if edge_type == "constant_rh":
        spec = point_a[1]
        rh = float(spec["rh_percent"] if isinstance(spec, dict) else spec)
        t = np.linspace(t_a, t_b, n)
        w = np.array([_humidity_ratio_from_t_rh(float(tt), rh, pressure_pa) for tt in t], dtype=float)
        return t, w
    if edge_type == "saturation_curve":
        t = np.linspace(t_a, t_b, n)
        w = np.array([_sat_humidity_ratio_g_kg(float(tt), pressure_pa) for tt in t], dtype=float)
        return t, w
    if edge_type == "constant_t":
        w = np.linspace(w_a, w_b, n)
        t = np.full_like(w, t_a, dtype=float)
        return t, w
    if edge_type == "constant_w":
        t = np.linspace(t_a, t_b, n)
        w = np.full_like(t, w_a, dtype=float)
        return t, w
    if edge_type == "straight":
        t = np.linspace(t_a, t_b, n)
        w = np.linspace(w_a, w_b, n)
        return t, w
    raise ValueError(f"Unsupported Givoni edge type: {edge_type}")


def _build_givoni_zone_path(zone_id: int, pressure_pa: float, use_clip: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Build a dense dry-bulb / humidity-ratio path for a Givoni zone."""
    zone = GIVONI_ZONE_DATA[zone_id]
    points = list(zone["points"])
    if bool(zone.get("spline", False)):
        left_bottom = points[0]
        upper_points = points[1:]
        left_t, _ = _resolve_givoni_point(left_bottom, pressure_pa)
        upper_xy = np.array([_resolve_givoni_point(p, pressure_pa) for p in upper_points], dtype=float)
        upper_t = upper_xy[:, 0]
        upper_w = upper_xy[:, 1]
        dense_t = np.linspace(float(np.min(upper_t)), float(np.max(upper_t)), 450)
        dense_w = np.interp(dense_t, upper_t, upper_w)
        left_vertical_t = np.array([left_t, left_t], dtype=float)
        left_vertical_w = np.array([0.0, upper_w[0]], dtype=float)
        bottom_t = np.linspace(dense_t[-1], left_t, 160)
        bottom_w = np.zeros_like(bottom_t)
        t_path = np.concatenate([left_vertical_t, dense_t, bottom_t])
        w_path = np.concatenate([left_vertical_w, dense_w, bottom_w])
    else:
        edge_types = list(zone["edges"])
        all_t: list[float] = []
        all_w: list[float] = []
        for idx, edge_type in enumerate(edge_types):
            p0 = points[idx]
            p1 = points[(idx + 1) % len(points)]
            t, w = _sample_givoni_segment(p0, p1, str(edge_type), pressure_pa, n=120)
            if idx > 0:
                t = t[1:]
                w = w[1:]
            all_t.extend(t.tolist())
            all_w.extend(w.tolist())
        t_path = np.asarray(all_t, dtype=float)
        w_path = np.asarray(all_w, dtype=float)
    if use_clip:
        w_sat = np.array([_sat_humidity_ratio_g_kg(float(t), pressure_pa) for t in t_path], dtype=float)
        w_path = np.minimum(np.maximum(w_path, 0.0), np.maximum(0.0, w_sat * 0.998))
    return t_path, w_path


def _zone_path_for_chart(zone_id: int, chart_type: str, pressure_pa: float) -> tuple[list[float], list[float]]:
    """Convert a Givoni zone path to the current psychrometric chart axes."""
    t_path, w_path = _build_givoni_zone_path(zone_id, pressure_pa, use_clip=True)
    xs: list[float] = []
    ys: list[float] = []
    for t_c, d_g_kg in zip(t_path, w_path, strict=False):
        x, y = _psychrometric_point_from_td(float(t_c), float(d_g_kg), chart_type)
        xs.append(x)
        ys.append(y)
    return xs, ys


def _add_givoni_milne_overlay(
    fig: go.Figure,
    chart_type: str,
    pressure_pa: float,
    shown_zone_names: list[str] | None = None,
) -> None:
    """Add the manually mapped Givoni-Milne bioclimatic zones.

    Every zone is drawn as a Plotly legend item.  Clicking a zone name in the
    legend toggles the fill/outline and its numerical label as a group.
    """
    allowed_names = set(shown_zone_names or [])
    use_name_filter = bool(shown_zone_names)
    for draw_idx, zone_id in enumerate(GIVONI_DRAW_ORDER):
        zone_name = GIVONI_ZONE_NAMES[zone_id]
        if use_name_filter and zone_name not in allowed_names:
            continue
        line_color, fill_color, short_label = GIVONI_ZONE_COLORS[zone_id]
        xs, ys = _zone_path_for_chart(zone_id, chart_type, pressure_pa)
        legend_group = f"givoni_zone_{zone_id}"
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                name=f"{zone_id}. {zone_name}",
                legend="legend2",
                legendgroup=legend_group,
                legendrank=zone_id,
                showlegend=True,
                line=dict(width=1.65, color=GIVONI_OUTLINE_COLOR, dash="dash"),
                fill="toself",
                fillcolor=fill_color,
                hovertemplate=(
                    f"{zone_id}. {zone_name}<br>"
                    + GIVONI_ZONE_STRATEGIES[zone_id]
                    + "<extra></extra>"
                ),
            )
        )
        t_label, w_label = GIVONI_LABEL_POSITIONS[zone_id]
        label_x, label_y = _psychrometric_point_from_td(t_label, w_label, chart_type)
        fig.add_trace(
            go.Scatter(
                x=[label_x],
                y=[label_y],
                mode="markers+text",
                marker=dict(size=19, color="white", line=dict(color=GIVONI_OUTLINE_COLOR, width=1.3)),
                text=[str(zone_id)],
                textfont=dict(size=9, color=line_color),
                textposition="middle center",
                name=f"{zone_id}. {short_label} label",
                legend="legend2",
                legendgroup=legend_group,
                legendrank=zone_id,
                showlegend=False,
                hovertemplate=f"{zone_id}. {zone_name}<extra></extra>",
            )
        )


def _point_in_polygon(x: np.ndarray, y: np.ndarray, polygon: list[tuple[float, float]]) -> np.ndarray:
    """Return a Boolean mask indicating whether points lie inside a polygon."""
    poly = np.asarray(polygon, dtype=float)
    px = poly[:, 0]
    py = poly[:, 1]
    inside = np.zeros_like(x, dtype=bool)
    j = len(poly) - 1
    for i in range(len(poly)):
        intersects = ((py[i] > y) != (py[j] > y)) & (x < (px[j] - px[i]) * (y - py[i]) / ((py[j] - py[i]) + 1e-12) + px[i])
        inside ^= intersects
        j = i
    return inside


def givoni_milne_zone_table(df: pd.DataFrame) -> pd.DataFrame:
    """Return hourly counts for each manually mapped Givoni-Milne zone.

    The zones overlap by design.  Therefore percentages are not mutually
    exclusive and should be read as strategy-potential counts, not as a sum to
    100 percent.
    """
    data = df[["dry_bulb_temperature_c", "humidity_ratio_g_kg"]].dropna()
    if data.empty:
        return pd.DataFrame(columns=["zone", "hours", "share_pct", "design_response"])
    x = data["dry_bulb_temperature_c"].to_numpy(dtype=float)
    y = data["humidity_ratio_g_kg"].to_numpy(dtype=float)
    rows = []
    for zone_id in GIVONI_DRAW_ORDER:
        t_path, w_path = _build_givoni_zone_path(zone_id, DEFAULT_PRESSURE_PA, use_clip=True)
        mask = _point_in_polygon(x, y, list(zip(t_path, w_path, strict=False)))
        hours = int(mask.sum())
        rows.append(
            {
                "zone": f"{zone_id}. {GIVONI_ZONE_NAMES[zone_id]}",
                "hours": hours,
                "share_pct": hours / max(len(data), 1) * 100.0,
                "design_response": GIVONI_ZONE_STRATEGIES[zone_id],
            }
        )
    return pd.DataFrame(rows).sort_values("hours", ascending=False)


def _add_line(fig: go.Figure, xs: list[float], ys: list[float], name: str, dash: str = "dot", width: float = 0.55) -> None:
    """Add a low-emphasis psychrometric construction line."""
    if len(xs) < 2 or len(ys) < 2:
        return
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            name=name,
            legendgroup="Chart metrics",
            line=dict(width=width, color="rgba(75,85,99,0.38)", dash=dash),
            hoverinfo="skip",
            showlegend=False,
        )
    )


def _add_psychrometric_metric_layers(
    fig: go.Figure,
    chart_type: str,
    pressure_pa: float,
    t_range: tuple[float, float] | None,
    d_range: tuple[float, float] | None,
    h_range: tuple[float, float] | None,
    metric_layers: list[str] | None,
) -> None:
    """Add selectable psychrometric metric lines to the chart."""
    layers = set(metric_layers or [])
    t_min, t_max = t_range or (-10.0, 50.0)
    d_min, d_max = d_range or (0.0, 35.0)
    h_min, h_max = h_range or (-20.0, 130.0)
    t_values = np.arange(t_min, t_max + 0.01, 0.75)

    if "Relative humidity" in layers:
        internal_type = "i-d" if chart_type == "i-d" else "T-d"
        for curve in psychrometric_rh_curves(internal_type, pressure_pa=pressure_pa, t_min_c=t_min, t_max_c=t_max):
            _add_line(fig, list(curve["x"]), list(curve["y"]), str(curve["label"]), dash="dash", width=0.75)

    if "Dry-bulb temperature" in layers:
        for t in np.arange(np.floor(t_min / 5) * 5, np.ceil(t_max / 5) * 5 + 0.1, 5):
            d_stop = min(d_max, _sat_humidity_ratio_g_kg(float(t), pressure_pa))
            d_values = np.linspace(max(0.0, d_min), max(d_stop, max(0.0, d_min)), 32)
            points = [_psychrometric_point_from_td(float(t), float(d), chart_type) for d in d_values]
            _add_line(fig, [p[0] for p in points], [p[1] for p in points], f"T {t:g} °C", dash="dot")

    if "Humidity ratio" in layers:
        for d in np.arange(np.floor(d_min / 5) * 5, np.ceil(d_max / 5) * 5 + 0.1, 5):
            if d < 0:
                continue
            points = []
            for t in t_values:
                if d <= _sat_humidity_ratio_g_kg(float(t), pressure_pa):
                    points.append(_psychrometric_point_from_td(float(t), float(d), chart_type))
            if points:
                _add_line(fig, [p[0] for p in points], [p[1] for p in points], f"d {d:g} g/kg", dash="dot")

    if "Wet-bulb temperature" in layers:
        for twb in np.arange(np.floor(t_min / 5) * 5, min(35.0, t_max) + 0.1, 5):
            points = []
            for t in t_values:
                if t < twb:
                    continue
                try:
                    w = psychrolib.GetHumRatioFromTWetBulb(float(t), float(twb), pressure_pa)
                    d = w * 1000.0
                except Exception:
                    continue
                if d_min <= d <= d_max and d <= _sat_humidity_ratio_g_kg(float(t), pressure_pa):
                    points.append(_psychrometric_point_from_td(float(t), float(d), chart_type))
            if points:
                _add_line(fig, [p[0] for p in points], [p[1] for p in points], f"Twb {twb:g} °C", dash="dash")

    if "Vapour pressure" in layers:
        for pv_kpa in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
            pv = pv_kpa * 1000.0
            if pv >= pressure_pa:
                continue
            d = 0.621945 * pv / (pressure_pa - pv) * 1000.0
            points = []
            for t in t_values:
                if d_min <= d <= d_max and d <= _sat_humidity_ratio_g_kg(float(t), pressure_pa):
                    points.append(_psychrometric_point_from_td(float(t), float(d), chart_type))
            if points:
                _add_line(fig, [p[0] for p in points], [p[1] for p in points], f"Pv {pv_kpa:g} kPa", dash="dashdot")

    if "Specific volume" in layers:
        for volume in [0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05]:
            points = []
            for t in t_values:
                t_k = float(t) + 273.15
                d = ((volume * pressure_pa) / (287.042 * t_k) - 1.0) / 1.607858 * 1000.0
                if d_min <= d <= d_max and d <= _sat_humidity_ratio_g_kg(float(t), pressure_pa):
                    points.append(_psychrometric_point_from_td(float(t), float(d), chart_type))
            if points:
                _add_line(fig, [p[0] for p in points], [p[1] for p in points], f"v {volume:g}", dash="longdash")

    if "Enthalpy" in layers:
        for enthalpy in np.arange(np.floor(h_min / 10) * 10, np.ceil(h_max / 10) * 10 + 0.1, 10):
            points = []
            for t in t_values:
                d = _humidity_ratio_from_enthalpy_t(float(enthalpy), float(t))
                if d_min <= d <= d_max and d <= _sat_humidity_ratio_g_kg(float(t), pressure_pa):
                    points.append(_psychrometric_point_from_td(float(t), float(d), chart_type))
            if points:
                _add_line(fig, [p[0] for p in points], [p[1] for p in points], f"h {enthalpy:g}", dash="dash")


def _add_heat_index_overlay(
    fig: go.Figure,
    chart_type: str,
    pressure_pa: float,
    t_range: tuple[float, float] | None,
    d_range: tuple[float, float] | None,
    h_range: tuple[float, float] | None,
) -> None:
    """Add heat-index contour lines to the psychrometric chart."""
    t_min, t_max = t_range or (20.0, 50.0)
    d_min, d_max = d_range or (0.0, 35.0)
    h_min, h_max = h_range or (-20.0, 130.0)
    levels = [27.0, 32.0, 41.0, 54.0]
    t_values = np.arange(max(20.0, t_min), min(55.0, t_max) + 0.001, 0.25)
    for level in levels:
        points = []
        for t in t_values:
            rhs = np.arange(1.0, 101.0, 1.0)
            hi = np.array([_heat_index_celsius(float(t), float(rh)) for rh in rhs], dtype=float)
            if not (np.nanmin(hi) <= level <= np.nanmax(hi)):
                continue
            try:
                rh = float(np.interp(level, hi, rhs))
                d = _humidity_ratio_from_t_rh(float(t), rh, pressure_pa)
            except Exception:
                continue
            x, y = _psychrometric_point_from_td(float(t), float(d), chart_type)
            if chart_type == "T-d" and not (d_min <= y <= d_max):
                continue
            if chart_type == "i-d" and not (d_min <= x <= d_max and h_min <= y <= h_max):
                continue
            points.append((x, y))
        if points:
            fig.add_trace(
                go.Scatter(
                    x=[p[0] for p in points],
                    y=[p[1] for p in points],
                    mode="lines",
                    name=f"Heat index {level:.0f} °C",
                    legend="legend2",
                    legendgroup="Heat index",
                    legendrank=1000 + int(level),
                    line=dict(width=1.1, color="rgba(185,28,28,0.75)", dash="dash"),
                    hovertemplate=f"Heat index {level:.0f} °C<extra></extra>",
                )
            )


def _metric_colorscale(column: str | None) -> object:
    """Return a suitable colorscale for mapping a weather metric on psychrometric data."""
    if not column:
        return "Viridis"
    if "radiation" in column or "illuminance" in column or "irradiance" in column:
        return SOLAR_COLORSCALE
    if "sky_cover" in column:
        return [[0.0, "rgba(255,255,255,0.0)"], [1.0, "#0f172a"]]
    if "wind" in column:
        return "Turbo"
    return "Viridis"


def _unique_existing_columns(columns: list[str | None], df: pd.DataFrame) -> list[str]:
    """Return existing DataFrame column names while preserving order and removing duplicates."""
    unique: list[str] = []
    for column in columns:
        if column and column in df.columns and column not in unique:
            unique.append(column)
    return unique


def _sample_metric_color(value: float, vmin: float, vmax: float, colorscale: object) -> str:
    """Return an RGBA colour sampled from a Plotly colorscale."""
    if not np.isfinite(value):
        return "rgba(180,180,180,0.12)"
    if vmax <= vmin:
        pos = 0.5
    else:
        pos = max(0.0, min(1.0, (float(value) - vmin) / (vmax - vmin)))
    try:
        return sample_colorscale(colorscale, [pos])[0]
    except Exception:
        return sample_colorscale("Viridis", [pos])[0]


def _add_psychrometric_tile_occupancy(
    fig: go.Figure,
    df: pd.DataFrame,
    chart_type: str,
    pressure_pa: float,
    t_range: tuple[float, float] | None,
    d_range: tuple[float, float] | None,
    h_range: tuple[float, float] | None,
    color_metric_column: str | None = None,
    color_metric_label: str = "Frequency [h]",
) -> None:
    """Draw 1 °C × 5 %RH tiles on the psychrometric chart layout.

    If ``color_metric_column`` is supplied, tile colour represents the average
    value of that metric in the cell. Otherwise it represents cell frequency.
    """
    base_columns = _unique_existing_columns(["dry_bulb_temperature_c", "relative_humidity_pct", color_metric_column], df)
    data = df[base_columns].dropna(subset=["dry_bulb_temperature_c", "relative_humidity_pct"]).copy()
    if data.empty:
        return
    data["temperature_bin_c"] = np.floor(data["dry_bulb_temperature_c"]).astype(int)
    data["rh_bin_pct"] = (np.floor(data["relative_humidity_pct"] / 5.0) * 5.0).clip(0, 95).astype(int)
    group_cols = ["temperature_bin_c", "rh_bin_pct"]
    if color_metric_column and color_metric_column in data.columns:
        tiles = data.groupby(group_cols, observed=True).agg(hours=("dry_bulb_temperature_c", "size"), value=(color_metric_column, "mean")).reset_index()
    else:
        tiles = data.groupby(group_cols, observed=True).size().reset_index(name="hours")
        tiles["value"] = tiles["hours"]
        color_metric_label = "Frequency [h]"
    if t_range is not None:
        tiles = tiles[(tiles["temperature_bin_c"] >= t_range[0] - 1) & (tiles["temperature_bin_c"] <= t_range[1])]
    if tiles.empty:
        return
    vmin, vmax = _finite_min_max(tiles["value"])
    vmin = float(vmin if vmin is not None else 0.0)
    vmax = float(vmax if vmax is not None else max(float(tiles["value"].max()), 1.0))
    colorscale = _metric_colorscale(color_metric_column)
    for _, row in tiles.iterrows():
        t0 = float(row["temperature_bin_c"])
        t1 = t0 + 1.0
        rh0 = float(row["rh_bin_pct"])
        rh1 = min(rh0 + 5.0, 100.0)
        corners_td = [
            (t0, _humidity_ratio_from_t_rh(t0, rh0, pressure_pa)),
            (t1, _humidity_ratio_from_t_rh(t1, rh0, pressure_pa)),
            (t1, _humidity_ratio_from_t_rh(t1, rh1, pressure_pa)),
            (t0, _humidity_ratio_from_t_rh(t0, rh1, pressure_pa)),
            (t0, _humidity_ratio_from_t_rh(t0, rh0, pressure_pa)),
        ]
        xs: list[float] = []
        ys: list[float] = []
        for t_c, d_g_kg in corners_td:
            x, y = _psychrometric_point_from_td(t_c, d_g_kg, chart_type)
            xs.append(x)
            ys.append(y)
        if d_range is not None and chart_type == "T-d" and (max(ys) < d_range[0] or min(ys) > d_range[1]):
            continue
        if h_range is not None and chart_type == "i-d" and (max(ys) < h_range[0] or min(ys) > h_range[1]):
            continue
        fill = _sample_metric_color(float(row["value"]), vmin, vmax, colorscale)
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line=dict(width=0.28, color="rgba(30,64,175,0.28)"),
                fill="toself",
                fillcolor=fill,
                showlegend=False,
                hovertemplate=(
                    f"Temperature bin: {t0:.0f}...{t1:.0f} °C<br>"
                    f"RH bin: {rh0:.0f}...{rh1:.0f} %<br>"
                    f"Hours: {int(row['hours'])}<br>"
                    f"{color_metric_label}: {float(row['value']):.2f}<extra></extra>"
                ),
            )
        )
    # Invisible marker used only to render a compact colorbar.
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            showlegend=False,
            marker=dict(
                color=[vmin, vmax],
                colorscale=colorscale,
                cmin=vmin,
                cmax=vmax,
                showscale=True,
                colorbar=dict(title=color_metric_label, orientation="h", x=0.5, y=-0.08, len=0.42, thickness=10),
            ),
            hoverinfo="skip",
        )
    )


def psychrometric_chart(
    df: pd.DataFrame,
    chart_type: str = "T-d",
    pressure_pa: float = DEFAULT_PRESSURE_PA,
    show_rh_curves: bool = True,
    show_comfort_zone: bool = True,
    data_mode: str = "Hourly values",
    t_range: tuple[float, float] | None = None,
    d_range: tuple[float, float] | None = None,
    h_range: tuple[float, float] | None = None,
    metric_layers: list[str] | None = None,
    shown_bioclimatic_zones: list[str] | None = None,
    show_heat_index_overlay: bool = False,
    selected_months: list[int] | None = None,
    color_metric_column: str | None = None,
    color_metric_label: str = "Month",
    color_mode: str = "Month",
) -> go.Figure:
    """Create an EPW psychrometric chart with selectable metric layers.

    Data modes:
        - ``Hourly values``: plot hourly EPW states as points.
        - ``Distributive grid``: plot 1 °C × 5 %RH tiles on the same chart
          geometry and colour them by frequency or another weather metric.
    """
    fig = go.Figure()
    chart_type = "i-d" if chart_type == "i-d" else "T-d"
    data_mode = "Hourly values" if data_mode in {"Monthly points", "Hourly values"} else "Distributive grid"
    if selected_months is None:
        selected_months = list(range(1, 13))

    if metric_layers is None:
        metric_layers = ["Relative humidity"] if show_rh_curves else []
    _add_psychrometric_metric_layers(fig, chart_type, pressure_pa, t_range, d_range, h_range, metric_layers)

    if chart_type == "i-d":
        x_label = "Moisture content d [g/kg dry air]"
        y_label = "Enthalpy i [kJ/kg dry air]"
        x_col = "humidity_ratio_g_kg"
        y_col = "moist_air_enthalpy_kj_kg"
        hover_base = "d: %{x:.2f} g/kg<br>i: %{y:.2f} kJ/kg"
    else:
        x_label = "Dry-bulb temperature [°C]"
        y_label = "Moisture content d [g/kg dry air]"
        x_col = "dry_bulb_temperature_c"
        y_col = "humidity_ratio_g_kg"
        hover_base = "T: %{x:.2f} °C<br>d: %{y:.2f} g/kg"

    plot_df = df[df["month_index"].isin(selected_months)].copy() if "month_index" in df.columns else df.copy()
    data_for_limits = plot_df[[x_col, y_col]].dropna().copy()

    if data_mode == "Distributive grid":
        metric_col = None if color_mode == "Frequency" else color_metric_column
        _add_psychrometric_tile_occupancy(fig, plot_df, chart_type, pressure_pa, t_range, d_range, h_range, metric_col, color_metric_label)
    else:
        base_cols = _unique_existing_columns([x_col, y_col, "month_index", "month_name", "hour_of_day", color_metric_column], plot_df)
        data = plot_df[base_cols].dropna(subset=[x_col, y_col]).copy()
        if color_mode == "Month" or color_metric_column not in data.columns:
            for month in sorted(set(selected_months)):
                subset = data[data["month_index"] == month]
                if subset.empty:
                    continue
                fig.add_trace(
                    go.Scattergl(
                        x=subset[x_col],
                        y=subset[y_col],
                        mode="markers",
                        name=MONTH_LABELS[month - 1],
                        legend="legend",
                        legendgroup="months",
                        legendrank=month,
                        marker=dict(size=3.5, opacity=0.42, color=MONTH_COLORS[month - 1]),
                        customdata=np.repeat(MONTH_LABELS[month - 1], len(subset)),
                        hovertemplate="Month: %{customdata}<br>" + hover_base + "<extra></extra>",
                    )
                )
        else:
            values = pd.Series(data[color_metric_column]).to_numpy(dtype=float)
            cmin, cmax = _finite_min_max(values)
            fig.add_trace(
                go.Scattergl(
                    x=data[x_col],
                    y=data[y_col],
                    mode="markers",
                    name=color_metric_label,
                    showlegend=False,
                    marker=dict(
                        size=3.8,
                        opacity=0.58,
                        color=values,
                        colorscale=_metric_colorscale(color_metric_column),
                        cmin=cmin,
                        cmax=cmax,
                        showscale=True,
                        colorbar=dict(title=color_metric_label, orientation="h", x=0.5, y=-0.08, len=0.42, thickness=10),
                    ),
                    hovertemplate=hover_base + f"<br>{color_metric_label}: %{{marker.color:.2f}}<extra></extra>",
                )
            )
        data_for_limits = data[[x_col, y_col]] if not data.empty else data_for_limits

    # Draw comfort/process overlays after loaded data so their outlines remain visible.
    if show_comfort_zone:
        _add_givoni_milne_overlay(fig, chart_type, pressure_pa, shown_bioclimatic_zones)
    if show_heat_index_overlay:
        _add_heat_index_overlay(fig, chart_type, pressure_pa, t_range, d_range, h_range)

    fig = apply_common_layout(fig, f"Psychrometric chart ({chart_type})", x_label, y_label)
    fig.update_layout(
        height=900,
        autosize=True,
        hovermode="closest",
        legend=dict(
            title=dict(text="Month", font=dict(size=13)),
            orientation="h",
            yanchor="top",
            y=-0.12,
            xanchor="left",
            x=0.0,
            itemsizing="constant",
            font=dict(size=12),
            groupclick="toggleitem",
            traceorder="normal",
        ),
        legend2=dict(
            title=dict(text="Zones", font=dict(size=13)),
            orientation="h",
            yanchor="top",
            y=-0.28,
            xanchor="left",
            x=0.0,
            itemsizing="constant",
            font=dict(size=12),
            groupclick="togglegroup",
            traceorder="normal",
        ),
        margin=dict(l=64, r=44, t=74, b=340),
    )
    if chart_type == "T-d":
        if t_range is not None:
            fig.update_xaxes(range=list(t_range), autorangeoptions=dict(minallowed=t_range[0], maxallowed=t_range[1]), constrain="domain")
        if d_range is not None:
            fig.update_yaxes(range=list(d_range), autorangeoptions=dict(minallowed=d_range[0], maxallowed=d_range[1]))
        elif not data_for_limits.empty:
            fig = _apply_axis_constraints(fig, y_column="humidity_ratio_g_kg", y_values=data_for_limits[y_col])
    else:
        if d_range is not None:
            fig.update_xaxes(range=list(d_range), autorangeoptions=dict(minallowed=d_range[0], maxallowed=d_range[1]), constrain="domain")
        elif not data_for_limits.empty:
            lo, hi = _axis_limits_for_column("humidity_ratio_g_kg", data_for_limits[x_col])
            fig.update_xaxes(range=[lo, hi], autorangeoptions=dict(minallowed=lo, maxallowed=hi), constrain="domain")
        if h_range is not None:
            fig.update_yaxes(range=list(h_range), autorangeoptions=dict(minallowed=h_range[0], maxallowed=h_range[1]))
    return fig

def wind_rose_chart(df: pd.DataFrame, title: str = "Wind rose") -> go.Figure:
    """Create a wind rose grouped by direction sectors and wind-speed bins."""
    data = df[["wind_direction_deg", "wind_speed_m_s"]].dropna().copy()
    if data.empty:
        return go.Figure().update_layout(title="No wind data available")
    direction_bin = (np.round(data["wind_direction_deg"] / 22.5) * 22.5) % 360
    data["direction_sector_deg"] = direction_bin
    data["speed_bin"] = pd.cut(
        data["wind_speed_m_s"],
        bins=[0, 1, 2, 4, 6, 8, 12, np.inf],
        labels=["0-1", "1-2", "2-4", "4-6", "6-8", "8-12", ">12"],
        include_lowest=True,
    )
    rose = data.groupby(["direction_sector_deg", "speed_bin"], observed=False).size().reset_index(name="hours")
    fig = px.bar_polar(
        rose,
        r="hours",
        theta="direction_sector_deg",
        color="speed_bin",
        title=title,
        labels={"hours": "Hours", "direction_sector_deg": "Wind direction [deg]", "speed_bin": "Speed [m/s]"},
    )
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return fig


def _representative_sun_day(df: pd.DataFrame, preferred_month: int = 6, preferred_day: int = 21) -> pd.DataFrame:
    """Return a representative daylight slice for sun-path annotations."""
    daylight = df[df.get("is_daylight", False)].copy()
    if daylight.empty:
        return daylight
    if {"month_index", "day"}.issubset(daylight.columns):
        preferred = daylight[(daylight["month_index"] == preferred_month) & (daylight["day"] == preferred_day)]
        if not preferred.empty:
            return preferred.sort_values("hour_of_day")
        month_only = daylight[daylight["month_index"] == preferred_month]
        if not month_only.empty:
            available_days = sorted(set(int(v) for v in month_only["day"].dropna().tolist()))
            if available_days:
                closest_day = min(available_days, key=lambda value: abs(value - preferred_day))
                return month_only[month_only["day"] == closest_day].sort_values("hour_of_day")
    # Fallback: use the day with the highest solar elevation sum.
    if {"month_index", "day", "solar_elevation_deg"}.issubset(daylight.columns):
        grouped = daylight.groupby(["month_index", "day"], dropna=False)["solar_elevation_deg"].sum()
        if not grouped.empty:
            month_value, day_value = grouped.idxmax()
            return daylight[(daylight["month_index"] == month_value) & (daylight["day"] == day_value)].sort_values("hour_of_day")
    return daylight.sort_values("hour_of_day")


def sun_path_chart(
    df: pd.DataFrame,
    title: str = "Sun path with DNI",
    invert_zenith_axis: bool = False,
    hide_zero_radiation: bool = False,
) -> go.Figure:
    """Create a larger polar sun-path chart colored by direct normal radiation.

    The chart also shows hour labels based on a representative summer day so the
    user can identify the local daytime movement of the sun.
    """
    required = ["solar_azimuth_deg", "solar_elevation_deg", "direct_normal_radiation_wh_m2", "month_index", "hour_of_day"]
    data = df[df.get("is_daylight", False)][required].dropna().copy()
    if hide_zero_radiation:
        data = data[data["direct_normal_radiation_wh_m2"] > 0.0]
    if data.empty:
        message = "No daylight radiation values available" if hide_zero_radiation else "No daylight data available"
        return go.Figure().update_layout(title=message)
    data["zenith_angle_deg"] = 90.0 - data["solar_elevation_deg"]
    fig = px.scatter_polar(
        data,
        theta="solar_azimuth_deg",
        r="zenith_angle_deg",
        color="direct_normal_radiation_wh_m2",
        hover_data={
            "month_index": True,
            "hour_of_day": True,
            "solar_elevation_deg": ":.1f",
            "direct_normal_radiation_wh_m2": ":.1f",
            "zenith_angle_deg": False,
        },
        title=title,
        labels={"direct_normal_radiation_wh_m2": "DNI [Wh/m²]", "solar_azimuth_deg": "Solar azimuth [deg]"},
        render_mode="webgl",
        color_continuous_scale=SOLAR_COLORSCALE,
    )
    representative = _representative_sun_day(df)
    if not representative.empty and {"solar_azimuth_deg", "solar_elevation_deg", "hour_of_day"}.issubset(representative.columns):
        representative = representative.dropna(subset=["solar_azimuth_deg", "solar_elevation_deg", "hour_of_day"]).copy()
        representative["zenith_angle_deg"] = 90.0 - representative["solar_elevation_deg"]
        representative = representative[(representative["hour_of_day"] >= 5) & (representative["hour_of_day"] <= 20)]
        if not representative.empty:
            fig.add_trace(
                go.Scatterpolar(
                    theta=representative["solar_azimuth_deg"],
                    r=representative["zenith_angle_deg"],
                    mode="lines+text",
                    text=[f"{int(h):02d}:00" for h in representative["hour_of_day"]],
                    textposition="top center",
                    textfont=dict(size=11, color="#111827"),
                    line=dict(color="rgba(17,24,39,0.75)", width=1.2, dash="dot"),
                    marker=dict(size=5, color="#111827"),
                    name="Representative hours",
                    showlegend=False,
                    hovertemplate="Hour %{text}<br>Solar azimuth %{theta:.1f}°<br>Solar elevation %{customdata:.1f}°<extra></extra>",
                    customdata=representative["solar_elevation_deg"],
                )
            )
    fig.update_layout(
        template=PLOT_TEMPLATE,
        height=600,
        margin=dict(l=40, r=40, t=70, b=35),
        coloraxis_colorbar=dict(title="DNI [Wh/m²]", len=0.8),
        polar=dict(
            radialaxis=dict(
                title="Zenith angle [deg]",
                range=[90, 0] if invert_zenith_axis else [0, 90],
                tickmode="array",
                tickvals=[90, 75, 60, 45, 30, 15, 0] if invert_zenith_axis else [0, 15, 30, 45, 60, 75, 90],
                ticktext=["90°", "75°", "60°", "45°", "30°", "15°", "0°"] if invert_zenith_axis else ["0°", "15°", "30°", "45°", "60°", "75°", "90°"],
            ),
            angularaxis=dict(direction="clockwise", rotation=90),
        ),
    )
    return fig


def sun_position_diagram(df: pd.DataFrame, title: str = "Sun-path diagram") -> go.Figure:
    """Create a cartesian sun-path diagram with month paths and hour lines.

    The x-axis shows solar azimuth and the y-axis shows solar elevation. Monthly
    curves are plotted for the first day of each month and hour lines connect the
    same local hour across months.
    """
    required = ["month_index", "day", "hour_of_day", "solar_azimuth_deg", "solar_elevation_deg", "is_daylight"]
    daylight = df[required].dropna().copy()
    daylight = daylight[daylight["is_daylight"]]
    if daylight.empty:
        return go.Figure().update_layout(title="No daylight data available")

    month_data: dict[int, pd.DataFrame] = {}
    for month in range(1, 13):
        monthly = daylight[daylight["month_index"] == month]
        if monthly.empty:
            continue
        # Use the first calendar day available for this month, matching the user reference diagram.
        first_day = int(monthly["day"].min())
        day_slice = monthly[monthly["day"] == first_day].sort_values("hour_of_day")
        day_slice = day_slice[(day_slice["solar_elevation_deg"] >= 0.0)]
        if not day_slice.empty:
            month_data[month] = day_slice

    fig = go.Figure()
    line_months = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    for month in line_months:
        day_slice = month_data.get(month)
        if day_slice is None or day_slice.empty:
            continue
        line_style = dict(color="rgba(17,24,39,0.85)", width=1.2)
        if month not in [1, 3, 6, 9, 12]:
            line_style["dash"] = "dash"
        fig.add_trace(
            go.Scatter(
                x=day_slice["solar_azimuth_deg"],
                y=day_slice["solar_elevation_deg"],
                mode="lines",
                line=line_style,
                name=MONTH_LABELS[month - 1],
                showlegend=False,
                hovertemplate=(
                    f"{MONTH_LABELS[month - 1]} 1"
                    "<br>Solar azimuth %{x:.1f}°"
                    "<br>Solar elevation %{y:.1f}°<extra></extra>"
                ),
            )
        )
        noon_row = day_slice.iloc[(day_slice["solar_elevation_deg"] - day_slice["solar_elevation_deg"].max()).abs().argsort()[:1]]
        if not noon_row.empty:
            x = float(noon_row["solar_azimuth_deg"].iloc[0])
            y = float(noon_row["solar_elevation_deg"].iloc[0])
            fig.add_annotation(
                x=x,
                y=y,
                text=f"1 {MONTH_LABELS[month - 1]}",
                showarrow=False,
                font=dict(size=10, color="#374151"),
                yshift=10,
            )

    for hour in range(5, 21):
        xs=[]; ys=[]
        for month in line_months:
            day_slice = month_data.get(month)
            if day_slice is None or day_slice.empty:
                continue
            matches = day_slice[(day_slice["hour_of_day"] >= hour) & (day_slice["hour_of_day"] < hour + 1)]
            if matches.empty:
                continue
            row = matches.iloc[(matches["solar_elevation_deg"] - matches["solar_elevation_deg"].max()).abs().argsort()[:1]]
            xs.append(float(row["solar_azimuth_deg"].iloc[0]))
            ys.append(float(row["solar_elevation_deg"].iloc[0]))
        if len(xs) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    line=dict(color="rgba(107,114,128,0.65)", width=1.0),
                    name=f"{hour}:00",
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            # Put the label at the point with the highest elevation.
            max_idx = int(np.argmax(ys))
            fig.add_annotation(
                x=xs[max_idx],
                y=ys[max_idx],
                text=f"{hour}:00",
                showarrow=False,
                font=dict(size=11, color="#111827"),
                yshift=12,
            )

    # Cardinal directions along the bottom edge.
    fig.add_annotation(x=90, y=0, text="East", showarrow=False, yshift=-20, font=dict(size=12, color="#111827"))
    fig.add_annotation(x=180, y=0, text="South", showarrow=False, yshift=-20, font=dict(size=12, color="#111827"))
    fig.add_annotation(x=270, y=0, text="West", showarrow=False, yshift=-20, font=dict(size=12, color="#111827"))

    fig.update_layout(
        template=PLOT_TEMPLATE,
        title=title,
        height=900,
        margin=dict(l=60, r=40, t=80, b=70),
        xaxis=dict(
            title="Solar azimuth [deg]",
            range=[55, 305],
            tickmode="array",
            tickvals=list(range(60, 301, 10)),
            gridcolor="rgba(107,114,128,0.35)",
            zeroline=False,
        ),
        yaxis=dict(
            title="Solar elevation [deg]",
            range=[0, 85],
            tickmode="array",
            tickvals=list(range(0, 81, 10)),
            ticksuffix="°",
            gridcolor="rgba(107,114,128,0.35)",
            zeroline=False,
        ),
    )
    return fig


def orientation_bar_chart(data: pd.DataFrame, title: str) -> go.Figure:
    """Create a bar chart for annual radiation by façade orientation."""
    fig = px.bar(data, x="orientation", y="annual_kwh_m2", title=title, labels={"annual_kwh_m2": "Annual irradiation [kWh/m²]"})
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return fig


def matrix_heatmap(matrix: pd.DataFrame, title: str, x_label: str, y_label: str, color_label: str) -> go.Figure:
    """Create a generic matrix heatmap with domain-specific colour scales."""
    use_solar_scale = any(token in (title + " " + color_label).lower() for token in ["radiation", "irradiation", "solar", "kwh/m²", "wh/m²"])
    fig = px.imshow(
        matrix,
        aspect="auto",
        color_continuous_scale=SOLAR_COLORSCALE if use_solar_scale else "Viridis",
        labels=dict(x=x_label, y=y_label, color=color_label),
        title=title,
    )
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return fig


def stacked_monthly_bar(df: pd.DataFrame, title: str, y_label: str = "Hours") -> go.Figure:
    """Create a stacked monthly bar chart from a month-indexed table."""
    data = df.reset_index().melt(id_vars=df.index.name or "index", var_name="series", value_name="value")
    x_column = df.index.name or "index"
    fig = px.bar(data, x=x_column, y="value", color="series", title=title)
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Month", yaxis_title=y_label, barmode="stack", margin=dict(l=40, r=20, t=70, b=45))
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)
    return fig


def multi_line_monthly(df: pd.DataFrame, title: str, y_label: str) -> go.Figure:
    """Create a multi-line monthly chart from a month-indexed table."""
    fig = go.Figure()
    for column in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df[column], mode="lines+markers", name=str(column)))
    fig = apply_common_layout(fig, title, "Month", y_label)
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)
    return fig
