"""One-shot source remediation for VIS-0.1 semantic chart colours.

This script is intentionally removed by the remediation workflow after it has
patched and validated the production sources.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHARTS = ROOT / "tools/climate_analyzer/epw_climate_analyzer/charts.py"
COMPARISON = ROOT / "tools/climate_analyzer/epw_climate_analyzer/comparison.py"


def function_block(text: str, name: str, next_name: str | None) -> tuple[int, int, str]:
    start = text.index(f"def {name}(")
    end = text.index(f"def {next_name}(", start) if next_name else len(text)
    return start, end, text[start:end]


def edit_function(text: str, name: str, next_name: str | None, editor) -> str:
    start, end, block = function_block(text, name, next_name)
    new_block = editor(block)
    if new_block == block:
        raise RuntimeError(f"VIS-0.1 patch made no change in {name}")
    return text[:start] + new_block + text[end:]


def replace_once(block: str, old: str, new: str, label: str) -> str:
    if old not in block:
        raise RuntimeError(f"VIS-0.1 anchor missing: {label}")
    return block.replace(old, new, 1)


def patch_charts() -> None:
    text = CHARTS.read_text(encoding="utf-8")
    anchor = "from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves\n"
    theme_import = """from .chart_theme import (\n    BINARY_SUITABILITY_COLORSCALE,\n    CLIMATE_COLORS,\n    DEFAULT_METRIC_COLOR,\n    WIND_SPEED_COLOR_MAP,\n    WIND_SPEED_LABELS,\n    metric_band_colors,\n    metric_color,\n    metric_colorscale,\n    rgba,\n    semantic_color_from_text,\n)\n"""
    if theme_import not in text:
        if anchor not in text:
            raise RuntimeError("charts.py theme import anchor missing")
        text = text.replace(anchor, anchor + theme_import, 1)
    text = text.replace("return BINARY_BLUE_COLORSCALE", "return BINARY_SUITABILITY_COLORSCALE")

    def profile(block: str) -> str:
        block = replace_once(block, "    fig = go.Figure()\n    if aggregation == \"Hourly\":", "    low_color, central_color, high_color, band_fill = metric_band_colors(column)\n    fig = go.Figure()\n    if aggregation == \"Hourly\":", "profile band colours")
        block = replace_once(block, "                name=f\"Hourly {unit}\",\n                hovertemplate=", "                name=f\"Hourly {unit}\",\n                line=dict(color=central_color, width=1.6),\n                hovertemplate=", "hourly line colour")
        block = replace_once(block, 'line=dict(color="red", width=1.4)', 'line=dict(color=high_color, width=1.4)', "profile maximum")
        block = replace_once(block, 'line=dict(color="blue", width=1.4)', 'line=dict(color=low_color, width=1.4)', "profile minimum")
        block = replace_once(block, 'fillcolor="rgba(120,120,120,0.18)"', 'fillcolor=band_fill', "profile fill")
        block = replace_once(block, "            line=dict(width=2.2),", "            line=dict(color=central_color, width=2.2),", "profile centre")
        return block

    text = edit_function(text, "profile_ribbon_chart", "percentile_band_chart", profile)

    def percentile(block: str) -> str:
        block = replace_once(block, "    fig = go.Figure()\n", "    low_color, central_color, high_color, band_fill = metric_band_colors(column)\n    fig = go.Figure()\n", "percentile palette")
        block = replace_once(block, 'name="P95", hovertemplate=', 'name="P95", line=dict(color=high_color, width=1.4), hovertemplate=', "P95 colour")
        block = replace_once(block, '            name="P05",\n            fill="tonexty",', '            name="P05",\n            line=dict(color=low_color, width=1.4),\n            fill="tonexty",', "P05 colour")
        block = replace_once(block, 'fillcolor="rgba(120,120,120,0.18)"', 'fillcolor=band_fill', "percentile fill")
        block = replace_once(block, 'name="Median", hovertemplate=', 'name="Median", line=dict(color=central_color, width=2.2), hovertemplate=', "median colour")
        return block

    text = edit_function(text, "percentile_band_chart", "heatmap_chart", percentile)

    def duration(block: str) -> str:
        return replace_once(block, 'fig.update_traces(hovertemplate=', 'fig.update_traces(line_color=metric_color(column), hovertemplate=', "duration colour")

    text = edit_function(text, "duration_chart", "histogram_chart", duration)

    def histogram(block: str) -> str:
        return replace_once(block, 'fig = px.histogram(data, x=column, nbins=bins, title=title, labels={column: unit})', 'fig = px.histogram(data, x=column, nbins=bins, title=title, labels={column: unit}, color_discrete_sequence=[metric_color(column)])', "histogram colour")

    text = edit_function(text, "histogram_chart", "monthly_box_chart", histogram)

    def monthly_box(block: str) -> str:
        block = replace_once(block, '    data["month_name"] = pd.Categorical(data["month_name"], MONTH_LABELS, ordered=True)\n', '    data["month_name"] = pd.Categorical(data["month_name"], MONTH_LABELS, ordered=True)\n    base_color = metric_color(column)\n', "box base colour")
        block = replace_once(block, '        fig = px.violin(data, x="month_name", y=column, box=True, points=False, title=title)\n', '        fig = px.violin(data, x="month_name", y=column, box=True, points=False, title=title)\n        fig.update_traces(marker_color=base_color, line_color=base_color, fillcolor=rgba(base_color, 0.24))\n', "violin colour")
        block = replace_once(block, '        fig = px.box(data, x="month_name", y=column, title=title)\n', '        fig = px.box(data, x="month_name", y=column, title=title)\n        fig.update_traces(marker_color=base_color, line_color=base_color)\n', "box colour")
        return block

    text = edit_function(text, "monthly_box_chart", "threshold_bar_chart", monthly_box)

    def threshold(block: str) -> str:
        return replace_once(block, 'fig = px.bar(data, x="Period", y=column, title=title)', 'fig = px.bar(data, x="Period", y=column, title=title, color_discrete_sequence=[semantic_color_from_text(title)])', "threshold colour")

    text = edit_function(text, "threshold_bar_chart", "scatter_chart", threshold)

    def metric_scale(block: str) -> str:
        start = block.index('    """')
        # Keep the public helper but make the centralized theme authoritative.
        return 'def _metric_colorscale(column: str | None) -> object:\n    """Return the central semantic colorscale for psychrometric metric mapping."""\n    return metric_colorscale(column)\n\n\n'

    text = edit_function(text, "_metric_colorscale", "_unique_existing_columns", metric_scale)

    def wind(block: str) -> str:
        block = replace_once(block, 'labels=["0-1", "1-2", "2-4", "4-6", "6-8", "8-12", ">12"],', 'labels=WIND_SPEED_LABELS,', "wind labels")
        block = replace_once(block, '        labels={"hours": "Hours", "direction_sector_deg": "Wind direction [deg]", "speed_bin": "Speed [m/s]"},\n    )', '        labels={"hours": "Hours", "direction_sector_deg": "Wind direction [deg]", "speed_bin": "Speed [m/s]"},\n        category_orders={"speed_bin": WIND_SPEED_LABELS},\n        color_discrete_map=WIND_SPEED_COLOR_MAP,\n    )', "wind palette")
        return block

    text = edit_function(text, "wind_rose_chart", "_representative_sun_day", wind)

    def orientation(block: str) -> str:
        return replace_once(block, 'fig = px.bar(data, x="orientation", y="annual_kwh_m2", title=title, labels={"annual_kwh_m2": "Annual irradiation [kWh/m²]"})', 'fig = px.bar(data, x="orientation", y="annual_kwh_m2", title=title, labels={"annual_kwh_m2": "Annual irradiation [kWh/m²]"}, color_discrete_sequence=[metric_color("global_horizontal_radiation_wh_m2")])', "orientation solar colour")

    text = edit_function(text, "orientation_bar_chart", "matrix_heatmap", orientation)

    def stacked(block: str) -> str:
        return '''def stacked_monthly_bar(df: pd.DataFrame, title: str, y_label: str = "Hours") -> go.Figure:\n    """Create semantic monthly bars; solar components are grouped, never stacked."""\n    series_names = [str(column) for column in df.columns]\n    data = df.reset_index().melt(id_vars=df.index.name or "index", var_name="series", value_name="value")\n    x_column = df.index.name or "index"\n    color_map: dict[str, str] = {}\n    for index, name in enumerate(series_names):\n        inferred = semantic_color_from_text(name)\n        color_map[name] = inferred if inferred != DEFAULT_METRIC_COLOR else CLIMATE_COLORS[index % len(CLIMATE_COLORS)]\n    solar_tokens = ("global horizontal", "direct normal", "diffuse horizontal", "ghi", "dni", "dhi")\n    solar_series = [name for name in series_names if any(token in name.lower() for token in solar_tokens)]\n    is_solar_components = len(solar_series) >= 2 and any(token in title.lower() for token in ("solar", "radiation", "irradiation"))\n    barmode = "group" if is_solar_components else "stack"\n    fig = px.bar(data, x=x_column, y="value", color="series", title=title, barmode=barmode, category_orders={"series": series_names}, color_discrete_map=color_map)\n    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Month", yaxis_title=y_label, barmode=barmode, margin=dict(l=40, r=20, t=70, b=45))\n    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)\n    return fig\n\n\n'''

    text = edit_function(text, "stacked_monthly_bar", "multi_line_monthly", stacked)

    def multi_line(block: str) -> str:
        return '''def multi_line_monthly(df: pd.DataFrame, title: str, y_label: str) -> go.Figure:\n    """Create multi-line monthly charts with semantic series colours."""\n    fig = go.Figure()\n    for index, column in enumerate(df.columns):\n        name = str(column)\n        inferred = semantic_color_from_text(name)\n        color = inferred if inferred != DEFAULT_METRIC_COLOR else CLIMATE_COLORS[index % len(CLIMATE_COLORS)]\n        fig.add_trace(go.Scatter(x=df.index, y=df[column], mode="lines+markers", name=name, line=dict(color=color)))\n    fig = apply_common_layout(fig, title, "Month", y_label)\n    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)\n    return fig\n'''

    text = edit_function(text, "multi_line_monthly", None, multi_line)
    CHARTS.write_text(text, encoding="utf-8")


def patch_comparison() -> None:
    text = COMPARISON.read_text(encoding="utf-8")
    anchor = "from .solar import orientation_annual_radiation, orientation_tilt_matrix, surface_irradiance_series\n"
    theme_import = """from .chart_theme import (\n    BINARY_SUITABILITY_COLORSCALE,\n    COOLING_COLOR,\n    HEATING_COLOR,\n    WIND_SPEED_COLOR_MAP,\n    WIND_SPEED_LABELS,\n    climate_color_map,\n    metric_color,\n    semantic_color_from_text,\n)\n"""
    if theme_import not in text:
        if anchor not in text:
            raise RuntimeError("comparison.py theme import anchor missing")
        text = text.replace(anchor, anchor + theme_import, 1)
    text = text.replace("BINARY_BLUE_COLORSCALE", "BINARY_SUITABILITY_COLORSCALE")

    def ranked(block: str) -> str:
        return replace_once(block, 'fig = px.bar(data, x=metric, y="Climate", orientation="h", title=title or f"Climate ranking: {metric}")', 'fig = px.bar(data, x=metric, y="Climate", orientation="h", title=title or f"Climate ranking: {metric}", color_discrete_sequence=[semantic_color_from_text(metric)])', "ranked metric colour")

    text = edit_function(text, "ranked_metric_chart", "monthly_profile_table", ranked)

    def overlay(block: str) -> str:
        block = replace_once(block, "    fig = go.Figure()\n    for column in table.columns:", "    fig = go.Figure()\n    colors = climate_color_map(table.columns)\n    for column in table.columns:", "overlay climate map")
        block = replace_once(block, 'fig.add_trace(go.Scatter(x=table.index, y=table[column], mode="lines+markers", name=str(column)))', 'fig.add_trace(go.Scatter(x=table.index, y=table[column], mode="lines+markers", name=str(column), line=dict(color=colors[str(column)])))', "overlay climate colour")
        return block

    text = edit_function(text, "overlay_monthly_chart", "small_multiple_monthly_chart", overlay)

    def small(block: str) -> str:
        block = replace_once(block, "    columns = list(table.columns)\n", "    columns = list(table.columns)\n    colors = climate_color_map(columns)\n", "small-multiple climate map")
        block = replace_once(block, 'fig.add_trace(go.Scatter(x=table.index, y=table[column], mode="lines+markers", name=column, showlegend=False), row=row, col=1)', 'fig.add_trace(go.Scatter(x=table.index, y=table[column], mode="lines+markers", name=column, showlegend=False, line=dict(color=colors[str(column)])), row=row, col=1)', "small-multiple climate colour")
        return block

    text = edit_function(text, "small_multiple_monthly_chart", "monthly_difference_chart", small)

    def duration(block: str) -> str:
        block = replace_once(block, "    fig = go.Figure()\n    for climate in climates:", "    fig = go.Figure()\n    colors = climate_color_map([climate.display_name for climate in climates])\n    for climate in climates:", "duration climate map")
        block = replace_once(block, 'fig.add_trace(go.Scatter(x=x, y=values, mode="lines", name=climate.display_name))', 'fig.add_trace(go.Scatter(x=x, y=values, mode="lines", name=climate.display_name, line=dict(color=colors[climate.display_name])))', "duration climate colour")
        return block

    text = edit_function(text, "duration_comparison_chart", "heatmap_small_multiples", duration)

    def hdd(block: str) -> str:
        return replace_once(block, 'fig = px.bar(data, x="Climate", y="K·h", color="Metric", barmode="group", title="Heating and cooling degree-hour comparison")', 'fig = px.bar(data, x="Climate", y="K·h", color="Metric", barmode="group", title="Heating and cooling degree-hour comparison", color_discrete_map={"HDD18 [K·h]": HEATING_COLOR, "CDD26 [K·h]": COOLING_COLOR})', "HDD/CDD colours")

    text = edit_function(text, "hdd_cdd_grouped_chart", "heating_cooling_season_timeline", hdd)

    def box(block: str) -> str:
        block = replace_once(block, 'fig = px.box(frame, x="Climate", y="Value", title=f"{title}: month {selected_month}")', 'fig = px.box(frame, x="Climate", y="Value", color="Climate", color_discrete_map=climate_color_map([climate.display_name for climate in climates]), title=f"{title}: month {selected_month}")', "comparison box climate colours")
        block = replace_once(block, 'fig = px.box(frame, x="month_name", y=column, title=f"{title}: {climate.display_name}")', 'fig = px.box(frame, x="month_name", y=column, title=f"{title}: {climate.display_name}", color_discrete_sequence=[metric_color(column)])', "single comparison box colour")
        return block

    text = edit_function(text, "monthly_box_compare_chart", "psychrometric_comparison_chart", box)

    def psych(block: str) -> str:
        block = replace_once(block, "    if mode == \"Overlay\" and len(climates) <= 3:\n        fig = go.Figure()", "    colors = climate_color_map([climate.display_name for climate in climates])\n    if mode == \"Overlay\" and len(climates) <= 3:\n        fig = go.Figure()", "psych climate map")
        block = replace_once(block, 'marker=dict(size=4, opacity=0.22)', 'marker=dict(size=4, opacity=0.22, color=colors[climate.display_name])', "psych climate colour")
        return block

    text = edit_function(text, "psychrometric_comparison_chart", "sun_path_comparison_chart", psych)

    def sun(block: str) -> str:
        block = replace_once(block, '    if mode == "Overlay" and len(climates) <= 4:\n        fig = go.Figure()', '    colors = climate_color_map([climate.display_name for climate in climates])\n    if mode == "Overlay" and len(climates) <= 4:\n        fig = go.Figure()', "sun-path climate map")
        block = replace_once(block, 'fig.add_trace(go.Scatter(x=data["solar_azimuth_deg"], y=data["solar_elevation_deg"], mode="lines+markers", name=climate.display_name, marker=dict(size=4)))', 'fig.add_trace(go.Scatter(x=data["solar_azimuth_deg"], y=data["solar_elevation_deg"], mode="lines+markers", name=climate.display_name, line=dict(color=colors[climate.display_name]), marker=dict(size=4, color=colors[climate.display_name])))', "sun overlay colour")
        block = replace_once(block, 'fig.add_trace(go.Scatter(x=data["solar_azimuth_deg"], y=data["solar_elevation_deg"], mode="lines+markers", name=climate.display_name, showlegend=False, marker=dict(size=4)), row=idx, col=1)', 'fig.add_trace(go.Scatter(x=data["solar_azimuth_deg"], y=data["solar_elevation_deg"], mode="lines+markers", name=climate.display_name, showlegend=False, line=dict(color=colors[climate.display_name]), marker=dict(size=4, color=colors[climate.display_name])), row=idx, col=1)', "sun small colour")
        return block

    text = edit_function(text, "sun_path_comparison_chart", "solar_monthly_comparison", sun)

    def facade(block: str) -> str:
        return replace_once(block, 'fig = px.line(data, x="Orientation", y="Annual irradiation [kWh/m²]", color="Climate", markers=True, title=f"Annual façade irradiation comparison, tilt {tilt_deg:.0f}°")', 'fig = px.line(data, x="Orientation", y="Annual irradiation [kWh/m²]", color="Climate", markers=True, title=f"Annual façade irradiation comparison, tilt {tilt_deg:.0f}°", color_discrete_map=climate_color_map([climate.display_name for climate in climates]))', "facade climate colours")

    text = edit_function(text, "facade_radiation_comparison_chart", "tilt_radiation_comparison_chart", facade)

    def tilt(block: str) -> str:
        return replace_once(block, 'fig = px.line(data, x="Tilt [deg]", y="Annual irradiation [kWh/m²]", color="Climate", markers=True, title=f"Tilt sensitivity at azimuth {azimuth_deg:.0f}°")', 'fig = px.line(data, x="Tilt [deg]", y="Annual irradiation [kWh/m²]", color="Climate", markers=True, title=f"Tilt sensitivity at azimuth {azimuth_deg:.0f}°", color_discrete_map=climate_color_map([climate.display_name for climate in climates]))', "tilt climate colours")

    text = edit_function(text, "tilt_radiation_comparison_chart", "orientation_tilt_small_multiples", tilt)

    def wind_multi(block: str) -> str:
        block = replace_once(block, 'labels = ["0-1", "1-2", "2-4", "4-6", "6-8", "8-12", ">12"]\n', '', "remove local wind labels")
        block = block.replace('labels=labels', 'labels=WIND_SPEED_LABELS')
        block = block.replace('for label in labels:', 'for label in WIND_SPEED_LABELS:')
        block = replace_once(block, 'fig.add_trace(go.Barpolar(r=subset["hours"], theta=subset["direction_sector_deg"], name=label, showlegend=i == 0), row=row, col=col)', 'fig.add_trace(go.Barpolar(r=subset["hours"], theta=subset["direction_sector_deg"], name=label, marker_color=WIND_SPEED_COLOR_MAP[label], showlegend=i == 0), row=row, col=col)', "comparison wind colour")
        return block

    text = edit_function(text, "wind_rose_small_multiples", "natural_ventilation_monthly_table", wind_multi)
    COMPARISON.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_charts()
    patch_comparison()
    print("VIS-0.1 semantic chart colour patch applied")
