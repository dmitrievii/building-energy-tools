"""Multi-climate comparison calculations and Plotly chart builders.

This module compares several normalized EPW-derived climate DataFrames. It does
not parse or depend on companion climate-package files. Every metric is derived
from the active EPW hourly data and the same calculated columns used by the
single-climate pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .aggregations import SEASON_ORDER, aggregate_summary, aggregate_sum, calendar_matrix, monthly_hour_matrix
from .decisions import (
    comfort_condition,
    dehumidification_condition,
    economizer_condition,
    humidification_condition,
    natural_ventilation_condition,
    night_flushing_condition,
    passive_strategy_monthly,
    passive_strategy_table,
    shading_condition,
)
from .epw_parser import DataQualityIssue, EpwFile
from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves
from .solar import orientation_annual_radiation, orientation_tilt_matrix, surface_irradiance_series
from .chart_theme import (
    BINARY_SUITABILITY_COLORSCALE,
    COOLING_COLOR,
    HEATING_COLOR,
    WIND_SPEED_COLOR_MAP,
    WIND_SPEED_LABELS,
    climate_color_map,
    metric_color,
    semantic_color_from_text,
)

PLOT_TEMPLATE = "plotly_white"
MONTH_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ORIENTATION_ORDER = ["North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West"]
SOLAR_COLORSCALE = [[0.0, "#4c1d95"], [0.45, "#f97316"], [1.0, "#fef08a"]]
TEMPERATURE_COLORSCALE = [[0.0, "#1d4ed8"], [0.45, "#22c55e"], [0.55, "#22c55e"], [1.0, "#dc2626"]]


DisplayMode = Literal["Auto", "Overlay", "Small multiples", "Difference to reference", "Ranked summary"]


@dataclass(frozen=True)
class ClimateDataset:
    """Container for one EPW-derived climate used in comparison charts."""

    climate_id: str
    display_name: str
    source: str
    epw: EpwFile
    data: pd.DataFrame
    issues: list[DataQualityIssue]


def choose_display_mode(chart_name: str, requested_mode: DisplayMode, climate_count: int) -> str:
    """Return a readable display mode for a chart and number of climates.

    Heavy visual chart types such as heatmaps, wind roses and psychrometric point
    clouds are forced to small multiples in automatic mode. Simple line charts
    can remain overlaid for a small number of climates.
    """
    if requested_mode != "Auto":
        return requested_mode
    small_multiple_charts = {
        "Temperature heatmap",
        "Temperature difference heatmap",
        "Psychrometric density",
        "Sun path",
        "Solar orientation-tilt heatmap",
        "Wind rose",
        "Natural ventilation heatmap",
        "Natural ventilation difference heatmap",
        "Passive strategy calendar",
    }
    if chart_name in small_multiple_charts:
        return "Small multiples"
    if climate_count <= 4:
        return "Overlay"
    if climate_count <= 8:
        return "Small multiples"
    return "Ranked summary"


def climate_summary_metrics(climates: list[ClimateDataset]) -> pd.DataFrame:
    """Calculate annual decision metrics for each climate."""
    rows: list[dict[str, object]] = []
    for climate in climates:
        df = climate.data
        t = df["dry_bulb_temperature_c"]
        ghi = df.get("global_horizontal_radiation_wh_m2", pd.Series(dtype=float)).fillna(0)
        dni = df.get("direct_normal_radiation_wh_m2", pd.Series(dtype=float)).fillna(0)
        dhi = df.get("diffuse_horizontal_radiation_wh_m2", pd.Series(dtype=float)).fillna(0)
        d = df.get("humidity_ratio_g_kg", pd.Series(dtype=float))
        h = df.get("moist_air_enthalpy_kj_kg", pd.Series(dtype=float))
        twb = df.get("wet_bulb_temperature_c", pd.Series(dtype=float))
        wind = df.get("wind_speed_m_s", pd.Series(dtype=float))
        daily_min = t.resample("D").min()
        tropical_nights = int((daily_min > 20.0).sum())
        diffuse_share = float(dhi.sum() / ghi.sum() * 100.0) if float(ghi.sum()) > 0 else np.nan
        issue_count = len(climate.issues)
        error_count = sum(1 for issue in climate.issues if issue.severity == "error")
        rows.append(
            {
                "Climate": climate.display_name,
                "City": climate.epw.location.city,
                "Country": climate.epw.location.country,
                "Latitude [deg]": climate.epw.location.latitude,
                "Longitude [deg]": climate.epw.location.longitude,
                "Elevation [m]": climate.epw.location.elevation_m,
                "Annual mean T [°C]": float(t.mean()),
                "Annual min T [°C]": float(t.min()),
                "Annual max T [°C]": float(t.max()),
                "T P01 [°C]": float(t.quantile(0.01)),
                "T P99 [°C]": float(t.quantile(0.99)),
                "HDD18 [K·h]": float((18.0 - t).clip(lower=0).sum()),
                "CDD26 [K·h]": float((t - 26.0).clip(lower=0).sum()),
                "Frost hours [h]": int((t < 0.0).sum()),
                "Hot hours >30 °C [h]": int((t > 30.0).sum()),
                "Tropical nights [d]": tropical_nights,
                "Mean humidity ratio [g/kg]": float(d.mean()),
                "Humidity ratio P95 [g/kg]": float(d.quantile(0.95)),
                "Hours d >10 g/kg [h]": int((d > 10.0).sum()),
                "Hours d <3 g/kg [h]": int((d < 3.0).sum()),
                "Enthalpy P95 [kJ/kg]": float(h.quantile(0.95)),
                "Maximum wet-bulb [°C]": float(twb.max()),
                "Annual GHI [kWh/m²]": float(ghi.sum() / 1000.0),
                "Annual DNI [kWh/m²]": float(dni.sum() / 1000.0),
                "Annual DHI [kWh/m²]": float(dhi.sum() / 1000.0),
                "Diffuse share [%]": diffuse_share,
                "Mean wind speed [m/s]": float(wind.mean()),
                "Wind speed P95 [m/s]": float(wind.quantile(0.95)),
                "Calm hours <1 m/s [h]": int((wind < 1.0).sum()),
                "Strong wind hours >8 m/s [h]": int((wind > 8.0).sum()),
                "Comfort hours [h]": int(comfort_condition(df).sum()),
                "Natural ventilation hours [h]": int(natural_ventilation_condition(df).sum()),
                "Night flushing hours [h]": int(night_flushing_condition(df).sum()),
                "Shading indicator hours [h]": int(shading_condition(df).sum()),
                "Economizer hours [h]": int(economizer_condition(df).sum()),
                "Dehumidification hours [h]": int(dehumidification_condition(df).sum()),
                "Humidification hours [h]": int(humidification_condition(df).sum()),
                "Data-quality issue count": issue_count,
                "Data-quality error count": error_count,
            }
        )
    return pd.DataFrame(rows)


def comparison_interpretation(metrics: pd.DataFrame, reference: str | None = None) -> str:
    """Create a compact automatic interpretation for the selected climates."""
    if metrics.empty:
        return "No comparison metrics are available."
    warm = metrics.loc[metrics["Annual mean T [°C]"].idxmax()]
    cold = metrics.loc[metrics["Annual mean T [°C]"].idxmin()]
    heat = metrics.loc[metrics["HDD18 [K·h]"].idxmax()]
    cool = metrics.loc[metrics["CDD26 [K·h]"].idxmax()]
    solar = metrics.loc[metrics["Annual GHI [kWh/m²]"].idxmax()]
    nv = metrics.loc[metrics["Natural ventilation hours [h]"].idxmax()]
    parts = [
        f"{warm['Climate']} is the warmest climate by annual mean dry-bulb temperature ({warm['Annual mean T [°C]']:.1f} °C), while {cold['Climate']} is the coldest ({cold['Annual mean T [°C]']:.1f} °C).",
        f"Heating severity is highest for {heat['Climate']} ({heat['HDD18 [K·h]']:.0f} K·h); cooling severity is highest for {cool['Climate']} ({cool['CDD26 [K·h]']:.0f} K·h).",
        f"The highest annual global horizontal irradiation is {solar['Climate']} ({solar['Annual GHI [kWh/m²]']:.0f} kWh/m²), and the highest default natural-ventilation availability is {nv['Climate']} ({nv['Natural ventilation hours [h]']:.0f} h/year).",
    ]
    if reference and reference in set(metrics["Climate"]):
        ref = metrics[metrics["Climate"] == reference].iloc[0]
        delta_rows = metrics[metrics["Climate"] != reference].copy()
        if not delta_rows.empty:
            delta_rows["Delta mean T"] = delta_rows["Annual mean T [°C]"] - float(ref["Annual mean T [°C]"])
            max_delta = delta_rows.iloc[delta_rows["Delta mean T"].abs().argmax()]
            parts.append(
                f"Relative to the reference climate {reference}, the largest annual mean-temperature offset is {max_delta['Climate']} ({max_delta['Delta mean T']:+.1f} K)."
            )
    return " ".join(parts)


def ranked_metric_chart(metrics: pd.DataFrame, metric: str, title: str | None = None) -> go.Figure:
    """Create a horizontal ranked bar chart for one comparison metric."""
    data = metrics[["Climate", metric]].dropna().sort_values(metric, ascending=True)
    fig = px.bar(data, x=metric, y="Climate", orientation="h", title=title or f"Climate ranking: {metric}", color_discrete_sequence=[semantic_color_from_text(metric)])
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title=metric, yaxis_title="Climate", margin=dict(l=40, r=20, t=70, b=45))
    return fig


def monthly_profile_table(climates: list[ClimateDataset], column: str, statistic: str = "mean", extensive: bool = False) -> pd.DataFrame:
    """Return a climate-by-month table for one variable and statistic."""
    out = pd.DataFrame(index=range(1, 13))
    for climate in climates:
        df = climate.data
        if extensive:
            series = df.groupby("month_index")[column].sum()
        elif statistic == "p05":
            series = df.groupby("month_index")[column].quantile(0.05)
        elif statistic == "p95":
            series = df.groupby("month_index")[column].quantile(0.95)
        elif statistic == "min":
            series = df.groupby("month_index")[column].min()
        elif statistic == "max":
            series = df.groupby("month_index")[column].max()
        else:
            series = df.groupby("month_index")[column].mean()
        out[climate.display_name] = series
    out.index.name = "Month"
    return out


def overlay_monthly_chart(table: pd.DataFrame, title: str, y_label: str) -> go.Figure:
    """Create an overlaid monthly line chart from a climate-by-month table."""
    fig = go.Figure()
    colors = climate_color_map(table.columns)
    for column in table.columns:
        fig.add_trace(go.Scatter(x=table.index, y=table[column], mode="lines+markers", name=str(column), line=dict(color=colors[str(column)])))
    fig.update_layout(template=PLOT_TEMPLATE, title=title, xaxis_title="Month", yaxis_title=y_label, hovermode="x unified", margin=dict(l=40, r=20, t=70, b=45))
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_ORDER, range=[1, 12], autorangeoptions=dict(minallowed=1, maxallowed=12))
    return fig

def small_multiple_monthly_chart(table: pd.DataFrame, title: str, y_label: str) -> go.Figure:
    """Create small multiples for monthly climate profiles."""
    columns = list(table.columns)
    colors = climate_color_map(columns)
    fig = make_subplots(rows=len(columns), cols=1, shared_xaxes=True, subplot_titles=columns, vertical_spacing=0.03)
    for row, column in enumerate(columns, start=1):
        fig.add_trace(go.Scatter(x=table.index, y=table[column], mode="lines+markers", name=column, showlegend=False, line=dict(color=colors[str(column)])), row=row, col=1)
    fig.update_layout(template=PLOT_TEMPLATE, title=title, height=max(320, 210 * len(columns)), hovermode="x unified", margin=dict(l=40, r=20, t=70, b=45))
    fig.update_yaxes(title_text=y_label)
    fig.update_xaxes(title_text="Month", row=len(columns), col=1, tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_ORDER, range=[1, 12], autorangeoptions=dict(minallowed=1, maxallowed=12))
    return fig

def monthly_difference_chart(table: pd.DataFrame, reference: str, title: str, y_label: str) -> go.Figure:
    """Create a monthly difference chart relative to a reference climate."""
    if reference not in table.columns:
        return overlay_monthly_chart(table, title, y_label)
    diff = table.subtract(table[reference], axis=0).drop(columns=[reference], errors="ignore")
    return overlay_monthly_chart(diff, f"{title} — difference to {reference}", f"Δ {y_label}")


def duration_comparison_chart(climates: list[ClimateDataset], column: str, title: str, y_label: str, ascending: bool = False) -> go.Figure:
    """Create overlaid duration curves for several climates."""
    fig = go.Figure()
    colors = climate_color_map([climate.display_name for climate in climates])
    for climate in climates:
        values = climate.data[column].dropna().sort_values(ascending=ascending).reset_index(drop=True)
        x = np.arange(1, len(values) + 1)
        fig.add_trace(go.Scatter(x=x, y=values, mode="lines", name=climate.display_name, line=dict(color=colors[climate.display_name])))
    fig.update_layout(template=PLOT_TEMPLATE, title=title, xaxis_title="Sorted hour", yaxis_title=y_label, hovermode="x unified", margin=dict(l=40, r=20, t=70, b=45))
    return fig


def heatmap_small_multiples(climates: list[ClimateDataset], column: str, row_group: str, title: str, color_label: str, temperature_thresholds: tuple[float, float] | None = None) -> go.Figure:
    """Create small-multiple period-by-hour heatmaps for climates."""
    rows = len(climates)
    fig = make_subplots(rows=rows, cols=1, subplot_titles=[c.display_name for c in climates], vertical_spacing=0.04)
    zmin = None
    zmax = None
    matrices: list[pd.DataFrame] = []
    for climate in climates:
        matrix = calendar_matrix(climate.data, column, row_group=row_group).T
        matrices.append(matrix)
        values = matrix.to_numpy(dtype=float)
        current_min = np.nanmin(values) if np.isfinite(values).any() else np.nan
        current_max = np.nanmax(values) if np.isfinite(values).any() else np.nan
        zmin = current_min if zmin is None or current_min < zmin else zmin
        zmax = current_max if zmax is None or current_max > zmax else zmax
    if column in ["global_horizontal_radiation_wh_m2", "direct_normal_radiation_wh_m2", "diffuse_horizontal_radiation_wh_m2"]:
        colorscale = SOLAR_COLORSCALE
        zmin = max(0.0, float(zmin or 0.0))
    elif column == "dry_bulb_temperature_c":
        if temperature_thresholds is not None and zmax is not None and zmin is not None and zmax > zmin:
            heat_t, cool_t = temperature_thresholds
            green_start = max(0.0, min(1.0, (heat_t - zmin) / (zmax - zmin)))
            green_end = max(green_start + 1e-6, min(1.0, (cool_t - zmin) / (zmax - zmin)))
            colorscale = [[0.0, "#1d4ed8"], [green_start, "#22c55e"], [green_end, "#22c55e"], [1.0, "#dc2626"]]
        else:
            colorscale = TEMPERATURE_COLORSCALE
    elif column in {"natural_ventilation_suitable", "night_flushing_suitable", "nv"} or "suitable" in column:
        colorscale = BINARY_SUITABILITY_COLORSCALE
        zmin = 0.0 if zmin is None else min(0.0, float(zmin))
        zmax = 1.0 if zmax is None else max(1.0, float(zmax))
    else:
        colorscale = "Viridis"
    for idx, matrix in enumerate(matrices, start=1):
        fig.add_trace(
            go.Heatmap(z=matrix.values, x=matrix.columns, y=matrix.index, coloraxis="coloraxis", hovertemplate="Period: %{x}<br>Hour: %{y}<br>Value: %{z:.2f}<extra></extra>"),
            row=idx,
            col=1,
        )
    fig.update_layout(template=PLOT_TEMPLATE, title=title, height=max(360, 260 * rows), coloraxis=dict(colorscale=colorscale, cmin=zmin, cmax=zmax, colorbar=dict(title=color_label)), margin=dict(l=40, r=20, t=70, b=45))
    fig.update_xaxes(title_text=row_group.capitalize(), row=rows, col=1)
    fig.update_yaxes(title_text="Hour of day", range=[23, 0], autorangeoptions=dict(minallowed=0, maxallowed=23))
    return fig

def difference_heatmap_chart(reference: ClimateDataset, target: ClimateDataset, column: str, row_group: str, title: str, color_label: str) -> go.Figure:
    """Create a heatmap of target minus reference for a selected variable."""
    ref = calendar_matrix(reference.data, column, row_group=row_group)
    tgt = calendar_matrix(target.data, column, row_group=row_group)
    diff = tgt.subtract(ref, fill_value=np.nan).T
    fig = px.imshow(diff, aspect="auto", color_continuous_scale="RdBu_r", labels=dict(x=row_group.capitalize(), y="Hour of day", color=color_label), title=title)
    fig.update_yaxes(range=[23, 0], autorangeoptions=dict(minallowed=0, maxallowed=23))
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return fig

def hdd_cdd_grouped_chart(metrics: pd.DataFrame) -> go.Figure:
    """Create grouped bars for annual heating and cooling degree-hours."""
    data = metrics[["Climate", "HDD18 [K·h]", "CDD26 [K·h]"]].melt(id_vars="Climate", var_name="Metric", value_name="K·h")
    fig = px.bar(data, x="Climate", y="K·h", color="Metric", barmode="group", title="Heating and cooling degree-hour comparison", color_discrete_map={"HDD18 [K·h]": HEATING_COLOR, "CDD26 [K·h]": COOLING_COLOR})
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Climate", yaxis_title="K·h", margin=dict(l=40, r=20, t=70, b=45))
    fig.update_yaxes(range=[0, max(float(data["K·h"].max()) * 1.05, 1.0)], autorangeoptions=dict(minallowed=0))
    return fig


def heating_cooling_season_timeline(climates: list[ClimateDataset], heat_base_c: float = 18.0, cool_base_c: float = 26.0) -> go.Figure:
    """Create a climate-by-day matrix for heating, neutral and cooling periods."""
    rows = []
    for climate in climates:
        daily = climate.data["dry_bulb_temperature_c"].resample("D").mean()
        for day, value in enumerate(daily, start=1):
            if pd.isna(value):
                status = 0
            elif value < heat_base_c:
                status = -1
            elif value > cool_base_c:
                status = 1
            else:
                status = 0
            rows.append({"Climate": climate.display_name, "Day of year": day, "Status": status})
    data = pd.DataFrame(rows)
    matrix = data.pivot(index="Climate", columns="Day of year", values="Status")
    fig = px.imshow(matrix, aspect="auto", color_continuous_scale=[(0, "#2563eb"), (0.5, "#e5e7eb"), (1, "#dc2626")], zmin=-1, zmax=1, labels=dict(x="Day of year", y="Climate", color="Class"), title="Heating, neutral and cooling season timeline")
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return fig


def monthly_box_compare_chart(climates: list[ClimateDataset], column: str, mode: str, selected_month: int, selected_climate: str, title: str, y_label: str) -> go.Figure:
    """Create monthly boxplots either by climate for one month or by month for one climate."""
    rows = []
    if mode == "Compare climates for selected month":
        for climate in climates:
            data = climate.data[climate.data["month_index"] == selected_month][column].dropna()
            rows.extend({"Climate": climate.display_name, "Value": value} for value in data)
        frame = pd.DataFrame(rows)
        fig = px.box(frame, x="Climate", y="Value", color="Climate", color_discrete_map=climate_color_map([climate.display_name for climate in climates]), title=f"{title}: month {selected_month}")
        x_label = "Climate"
    else:
        climate = next((c for c in climates if c.display_name == selected_climate), climates[0])
        frame = climate.data[[column, "month_name", "month_index"]].dropna().sort_values("month_index")
        fig = px.box(frame, x="month_name", y=column, title=f"{title}: {climate.display_name}", color_discrete_sequence=[metric_color(column)])
        x_label = "Month"
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title=x_label, yaxis_title=y_label, margin=dict(l=40, r=20, t=70, b=45))
    return fig


def psychrometric_comparison_chart(climates: list[ClimateDataset], chart_type: str = "T-d", mode: str = "Small multiples", pressure_pa: float = DEFAULT_PRESSURE_PA) -> go.Figure:
    """Create psychrometric comparison as overlay or small-multiple density plots."""
    colors = climate_color_map([climate.display_name for climate in climates])
    if mode == "Overlay" and len(climates) <= 3:
        fig = go.Figure()
        for climate in climates:
            df = climate.data.sample(min(len(climate.data), 2500), random_state=7) if len(climate.data) > 2500 else climate.data
            if chart_type == "i-d":
                x = df["humidity_ratio_g_kg"]
                y = df["moist_air_enthalpy_kj_kg"]
                x_label = "Moisture content d [g/kg dry air]"
                y_label = "Enthalpy i [kJ/kg dry air]"
            else:
                x = df["dry_bulb_temperature_c"]
                y = df["humidity_ratio_g_kg"]
                x_label = "Dry-bulb temperature [°C]"
                y_label = "Moisture content d [g/kg dry air]"
            fig.add_trace(go.Scattergl(x=x, y=y, mode="markers", name=climate.display_name, marker=dict(size=4, opacity=0.22, color=colors[climate.display_name])))
        fig.update_layout(template=PLOT_TEMPLATE, title=f"Psychrometric comparison ({chart_type})", xaxis_title=x_label, yaxis_title=y_label, margin=dict(l=40, r=20, t=70, b=45))
        return fig

    rows = len(climates)
    fig = make_subplots(rows=rows, cols=1, subplot_titles=[c.display_name for c in climates], vertical_spacing=0.04)
    for idx, climate in enumerate(climates, start=1):
        df = climate.data
        if chart_type == "i-d":
            x = df["humidity_ratio_g_kg"]
            y = df["moist_air_enthalpy_kj_kg"]
            x_label = "Moisture content d [g/kg dry air]"
            y_label = "Enthalpy i [kJ/kg dry air]"
        else:
            x = df["dry_bulb_temperature_c"]
            y = df["humidity_ratio_g_kg"]
            x_label = "Dry-bulb temperature [°C]"
            y_label = "Moisture content d [g/kg dry air]"
        fig.add_trace(go.Histogram2dContour(x=x, y=y, contours=dict(coloring="heatmap"), showscale=idx == 1, coloraxis="coloraxis", name=climate.display_name), row=idx, col=1)
        if chart_type == "T-d":
            for curve in psychrometric_rh_curves("T-d", pressure_pa=pressure_pa):
                fig.add_trace(go.Scatter(x=curve["x"], y=curve["y"], mode="lines", line=dict(width=0.5), showlegend=False, hoverinfo="skip"), row=idx, col=1)
    fig.update_layout(template=PLOT_TEMPLATE, title=f"Psychrometric density comparison ({chart_type})", height=max(360, 280 * rows), coloraxis=dict(colorscale="Viridis", colorbar=dict(title="Density")), margin=dict(l=40, r=20, t=70, b=45))
    fig.update_xaxes(title_text=x_label, row=rows, col=1)
    fig.update_yaxes(title_text=y_label)
    return fig


def sun_path_comparison_chart(climates: list[ClimateDataset], mode: str, selected_dates: list[str]) -> go.Figure:
    """Create overlay or small-multiple sun-path comparison for selected calendar dates."""
    colors = climate_color_map([climate.display_name for climate in climates])
    if mode == "Overlay" and len(climates) <= 4:
        fig = go.Figure()
        for climate in climates:
            data = climate.data[climate.data.index.strftime("%m-%d").isin(selected_dates) & climate.data["is_daylight"]]
            fig.add_trace(go.Scatter(x=data["solar_azimuth_deg"], y=data["solar_elevation_deg"], mode="lines+markers", name=climate.display_name, line=dict(color=colors[climate.display_name]), marker=dict(size=4, color=colors[climate.display_name])))
        fig.update_layout(template=PLOT_TEMPLATE, title="Sun-path comparison for selected dates", xaxis_title="Solar azimuth [deg]", yaxis_title="Solar altitude [deg]", margin=dict(l=40, r=20, t=70, b=45))
        return fig
    rows = len(climates)
    fig = make_subplots(rows=rows, cols=1, subplot_titles=[c.display_name for c in climates], vertical_spacing=0.04)
    for idx, climate in enumerate(climates, start=1):
        data = climate.data[climate.data.index.strftime("%m-%d").isin(selected_dates) & climate.data["is_daylight"]]
        fig.add_trace(go.Scatter(x=data["solar_azimuth_deg"], y=data["solar_elevation_deg"], mode="lines+markers", name=climate.display_name, showlegend=False, line=dict(color=colors[climate.display_name]), marker=dict(size=4, color=colors[climate.display_name])), row=idx, col=1)
    fig.update_layout(template=PLOT_TEMPLATE, title="Sun-path comparison for selected dates", height=max(360, 230 * rows), margin=dict(l=40, r=20, t=70, b=45))
    fig.update_xaxes(title_text="Solar azimuth [deg]", row=rows, col=1)
    fig.update_yaxes(title_text="Solar altitude [deg]")
    return fig


def solar_monthly_comparison(climates: list[ClimateDataset], radiation_column: str = "global_horizontal_radiation_wh_m2") -> pd.DataFrame:
    """Return monthly solar-radiation sums for several climates."""
    table = pd.DataFrame(index=range(1, 13))
    for climate in climates:
        table[climate.display_name] = climate.data.groupby("month_index")[radiation_column].sum() / 1000.0
    table.index.name = "Month"
    return table


def facade_radiation_comparison_chart(climates: list[ClimateDataset], tilt_deg: float = 90.0) -> go.Figure:
    """Compare annual plane-of-array irradiation by façade orientation."""
    rows = []
    for climate in climates:
        table = orientation_annual_radiation(climate.data, tilt_deg=tilt_deg)
        for _, row in table.iterrows():
            rows.append({"Climate": climate.display_name, "Orientation": row["orientation"], "Annual irradiation [kWh/m²]": row["annual_kwh_m2"]})
    data = pd.DataFrame(rows)
    data["Orientation"] = pd.Categorical(data["Orientation"], ORIENTATION_ORDER, ordered=True)
    data = data.sort_values("Orientation")
    fig = px.line(data, x="Orientation", y="Annual irradiation [kWh/m²]", color="Climate", markers=True, title=f"Annual façade irradiation comparison, tilt {tilt_deg:.0f}°", color_discrete_map=climate_color_map([climate.display_name for climate in climates]))
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Orientation", yaxis_title="Annual irradiation [kWh/m²]", margin=dict(l=40, r=20, t=70, b=45))
    return fig


def tilt_radiation_comparison_chart(climates: list[ClimateDataset], azimuth_deg: float = 180.0) -> go.Figure:
    """Compare annual irradiation across surface tilts for one azimuth."""
    rows = []
    for climate in climates:
        for tilt in range(0, 91, 5):
            poa = surface_irradiance_series(climate.data, float(tilt), azimuth_deg)
            rows.append({"Climate": climate.display_name, "Tilt [deg]": tilt, "Annual irradiation [kWh/m²]": poa.sum() / 1000.0})
    data = pd.DataFrame(rows)
    fig = px.line(data, x="Tilt [deg]", y="Annual irradiation [kWh/m²]", color="Climate", markers=True, title=f"Tilt sensitivity at azimuth {azimuth_deg:.0f}°", color_discrete_map=climate_color_map([climate.display_name for climate in climates]))
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Surface tilt [deg]", yaxis_title="Annual irradiation [kWh/m²]", margin=dict(l=40, r=20, t=70, b=45))
    return fig


def orientation_tilt_small_multiples(climates: list[ClimateDataset]) -> go.Figure:
    """Create small-multiple orientation-tilt irradiation heatmaps."""
    rows = len(climates)
    fig = make_subplots(rows=rows, cols=1, subplot_titles=[c.display_name for c in climates], vertical_spacing=0.04)
    matrices = [orientation_tilt_matrix(climate.data) for climate in climates]
    zmin = min(float(np.nanmin(m.values)) for m in matrices if np.isfinite(m.values).any())
    zmax = max(float(np.nanmax(m.values)) for m in matrices if np.isfinite(m.values).any())
    for idx, matrix in enumerate(matrices, start=1):
        fig.add_trace(go.Heatmap(z=matrix.values, x=matrix.columns, y=matrix.index, coloraxis="coloraxis", hovertemplate="Azimuth: %{x}°<br>Tilt: %{y}°<br>Irradiation: %{z:.0f} kWh/m²<extra></extra>"), row=idx, col=1)
    fig.update_layout(template=PLOT_TEMPLATE, title="Orientation-tilt annual irradiation comparison", height=max(360, 300 * rows), coloraxis=dict(colorscale=SOLAR_COLORSCALE, cmin=zmin, cmax=zmax, colorbar=dict(title="kWh/m²")), margin=dict(l=40, r=20, t=70, b=45))
    fig.update_xaxes(title_text="Azimuth [deg]", row=rows, col=1)
    fig.update_yaxes(title_text="Tilt [deg]")
    return fig


def wind_rose_small_multiples(climates: list[ClimateDataset]) -> go.Figure:
    """Create small-multiple polar wind roses with shared speed bins."""
    rows = int(np.ceil(len(climates) / 2))
    cols = 2 if len(climates) > 1 else 1
    specs = [[{"type": "polar"} for _ in range(cols)] for _ in range(rows)]
    fig = make_subplots(rows=rows, cols=cols, specs=specs, subplot_titles=[c.display_name for c in climates], vertical_spacing=0.12)
    bins = [0, 1, 2, 4, 6, 8, 12, np.inf]
    for i, climate in enumerate(climates):
        row = i // cols + 1
        col = i % cols + 1
        data = climate.data[["wind_direction_deg", "wind_speed_m_s"]].dropna().copy()
        data["direction_sector_deg"] = (np.round(data["wind_direction_deg"] / 22.5) * 22.5) % 360
        data["speed_bin"] = pd.cut(data["wind_speed_m_s"], bins=bins, labels=WIND_SPEED_LABELS, include_lowest=True)
        rose = data.groupby(["direction_sector_deg", "speed_bin"], observed=False).size().reset_index(name="hours")
        for label in WIND_SPEED_LABELS:
            subset = rose[rose["speed_bin"] == label]
            fig.add_trace(go.Barpolar(r=subset["hours"], theta=subset["direction_sector_deg"], name=label, marker_color=WIND_SPEED_COLOR_MAP[label], showlegend=i == 0), row=row, col=col)
    fig.update_layout(template=PLOT_TEMPLATE, title="Wind rose comparison", height=max(420, 360 * rows), margin=dict(l=40, r=20, t=70, b=45))
    return fig


def natural_ventilation_monthly_table(climates: list[ClimateDataset], t_min_c: float, t_max_c: float, d_max_g_kg: float) -> pd.DataFrame:
    """Return monthly natural-ventilation eligible hours for climates."""
    table = pd.DataFrame(index=range(1, 13))
    for climate in climates:
        mask = natural_ventilation_condition(climate.data, t_min_c=t_min_c, t_max_c=t_max_c, d_max_g_kg=d_max_g_kg)
        series = pd.Series(mask.astype(int).values, index=climate.data.index).groupby(climate.data["month_index"]).sum()
        table[climate.display_name] = series
    table.index.name = "Month"
    return table.fillna(0)


def natural_ventilation_difference_heatmap(reference: ClimateDataset, target: ClimateDataset, t_min_c: float, t_max_c: float, d_max_g_kg: float) -> go.Figure:
    """Create a target-minus-reference heatmap for natural-ventilation eligibility."""
    ref = reference.data.copy()
    tgt = target.data.copy()
    ref["nv"] = natural_ventilation_condition(ref, t_min_c=t_min_c, t_max_c=t_max_c, d_max_g_kg=d_max_g_kg).astype(int)
    tgt["nv"] = natural_ventilation_condition(tgt, t_min_c=t_min_c, t_max_c=t_max_c, d_max_g_kg=d_max_g_kg).astype(int)
    return difference_heatmap_chart(ClimateDataset(reference.climate_id, reference.display_name, reference.source, reference.epw, ref, reference.issues), ClimateDataset(target.climate_id, target.display_name, target.source, target.epw, tgt, target.issues), "nv", "day", f"Natural-ventilation eligibility difference: {target.display_name} minus {reference.display_name}", "Δ eligibility")


def passive_strategy_stacked_comparison(climates: list[ClimateDataset]) -> go.Figure:
    """Create stacked bars of annual passive/HVAC strategy hours by climate."""
    rows = []
    for climate in climates:
        table = passive_strategy_table(climate.data)
        for _, row in table.iterrows():
            rows.append({"Climate": climate.display_name, "Strategy": row["strategy"], "Hours": row["hours"]})
    data = pd.DataFrame(rows)
    fig = px.bar(data, x="Climate", y="Hours", color="Strategy", title="Annual passive and HVAC strategy comparison", barmode="stack")
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Climate", yaxis_title="Hours/year", margin=dict(l=40, r=20, t=70, b=45))
    return fig


def passive_strategy_calendar_small_multiples(climates: list[ClimateDataset]) -> go.Figure:
    """Create small-multiple calendars of dominant passive/HVAC strategy class."""
    rows = len(climates)
    fig = make_subplots(rows=rows, cols=1, subplot_titles=[c.display_name for c in climates], vertical_spacing=0.04)
    for idx, climate in enumerate(climates, start=1):
        df = climate.data.copy()
        status = pd.Series(0, index=df.index, dtype=int)
        status[df["dry_bulb_temperature_c"] < 18.0] = -2
        status[df["dry_bulb_temperature_c"] > 26.0] = 2
        status[natural_ventilation_condition(df)] = 1
        status[night_flushing_condition(df)] = -1
        temp = df.copy()
        temp["strategy_class"] = status
        matrix = calendar_matrix(temp, "strategy_class", row_group="day").T
        fig.add_trace(go.Heatmap(z=matrix.values, x=matrix.columns, y=matrix.index, coloraxis="coloraxis", hovertemplate="Day: %{x}<br>Hour: %{y}<br>Class: %{z}<extra></extra>"), row=idx, col=1)
    fig.update_layout(template=PLOT_TEMPLATE, title="Dominant passive/HVAC strategy calendar", height=max(360, 260 * rows), coloraxis=dict(colorscale="RdBu_r", cmin=-2, cmax=2, colorbar=dict(title="Class")), margin=dict(l=40, r=20, t=70, b=45))
    fig.update_xaxes(title_text="Day of year", row=rows, col=1)
    fig.update_yaxes(title_text="Hour of day", range=[23, 0], autorangeoptions=dict(minallowed=0, maxallowed=23))
    return fig


def data_quality_matrix(climates: list[ClimateDataset]) -> pd.DataFrame:
    """Return a matrix summarizing missing values and diagnostic issues."""
    rows = []
    core_columns = [
        "dry_bulb_temperature_c",
        "relative_humidity_pct",
        "global_horizontal_radiation_wh_m2",
        "direct_normal_radiation_wh_m2",
        "diffuse_horizontal_radiation_wh_m2",
        "wind_speed_m_s",
        "wind_direction_deg",
    ]
    for climate in climates:
        row = {"Climate": climate.display_name, "Rows": len(climate.data), "Diagnostic issues": len(climate.issues)}
        for column in core_columns:
            row[f"Missing {column}"] = int(climate.data[column].isna().sum()) if column in climate.data.columns else len(climate.data)
        rows.append(row)
    return pd.DataFrame(rows)
