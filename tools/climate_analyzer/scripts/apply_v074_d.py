from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()
APP = ROOT / "app.py"
CHARTS = ROOT / "epw_climate_analyzer" / "charts.py"
COMPARISON = ROOT / "epw_climate_analyzer" / "comparison.py"
DOC = ROOT / "CLIMATE_CORE_0_7_4.md"
TEST = ROOT / "tests" / "test_psychrometric_redesign_0_7_4.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one anchor, found {count}: {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: Path, start_marker: str, end_marker: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{path}: start marker not found: {start_marker!r}")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{path}: end marker not found: {end_marker!r}")
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


# charts.py — one central psychrometric frequency palette and single-climate envelopes.
replace_once(
    CHARTS,
    'from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves\nfrom .chart_theme import (\n',
    'from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves\nfrom .psychrometric_distribution import envelope_polygon_coordinates, psychrometric_occupancy_envelope\nfrom .chart_theme import (\n',
)
replace_once(
    CHARTS,
    '    BINARY_SUITABILITY_COLORSCALE,\n    CLIMATE_COLORS,\n',
    '    BINARY_SUITABILITY_COLORSCALE,\n    CLIMATE_COLORS,\n    PSYCHROMETRIC_TILE_COLORSCALE,\n',
)
replace_once(
    CHARTS,
    'PSYCHROMETRIC_TILE_COLORSCALE = [\n    [0.00, "rgba(255,255,255,0.0)"],\n    [0.10, "#dbeafe"],\n    [0.35, "#60a5fa"],\n    [0.70, "#2563eb"],\n    [1.00, "#172554"],\n]\n',
    '',
)
replace_once(
    CHARTS,
    '    vmin, vmax = _finite_min_max(tiles["value"])\n    vmin = float(vmin if vmin is not None else 0.0)\n    vmax = float(vmax if vmax is not None else max(float(tiles["value"].max()), 1.0))\n    colorscale = _metric_colorscale(color_metric_column)\n',
    '    vmin, vmax = _finite_min_max(tiles["value"])\n    vmin = float(vmin if vmin is not None else 0.0)\n    vmax = float(vmax if vmax is not None else max(float(tiles["value"].max()), 1.0))\n    if color_metric_column is None:\n        # Frequency is a duration density: keep the scale anchored at zero and\n        # use the dedicated pale-to-saturated blue psychrometric palette.\n        vmin = 0.0\n        colorscale = PSYCHROMETRIC_TILE_COLORSCALE\n    else:\n        colorscale = _metric_colorscale(color_metric_column)\n',
)
replace_once(
    CHARTS,
    '    data_mode = "Hourly values" if data_mode in {"Monthly points", "Hourly values"} else "Distributive grid"\n',
    '    if data_mode in {"Monthly points", "Hourly values", "Source interval values"}:\n        data_mode = "Hourly values"\n    elif data_mode == "Middle 90% envelopes":\n        data_mode = "Middle 90% envelopes"\n    else:\n        data_mode = "Distributive grid"\n',
)
replace_once(
    CHARTS,
    '    if data_mode == "Distributive grid":\n        metric_col = None if color_mode == "Frequency" else color_metric_column\n        _add_psychrometric_tile_occupancy(fig, plot_df, chart_type, pressure_pa, t_range, d_range, h_range, metric_col, color_metric_label)\n    else:\n',
    '''    if data_mode == "Middle 90% envelopes":
        if time_basis(plot_df) == CHRONOLOGICAL and is_multiyear(plot_df):
            envelope_groups: list[tuple[str, pd.DataFrame]] = []
            for year in sorted({int(value) for value in pd.DatetimeIndex(plot_df.index).year}):
                group = plot_df[pd.DatetimeIndex(plot_df.index).year == year].copy()
                group.attrs.update(plot_df.attrs)
                envelope_groups.append((str(year), group))
        else:
            envelope_groups = [("Middle 90% occupancy", plot_df)]
        for index, (label, group) in enumerate(envelope_groups):
            envelope = psychrometric_occupancy_envelope(group, target_share=0.90)
            if envelope.selected_tiles.empty:
                continue
            xs, ys = envelope_polygon_coordinates(envelope, chart_type=chart_type, pressure_pa=pressure_pa)
            color = CLIMATE_COLORS[index % len(CLIMATE_COLORS)]
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    name=label,
                    legend="legend",
                    line=dict(color=rgba(color, 0.78), width=0.55),
                    fill="toself",
                    fillcolor=rgba(color, 0.14),
                    connectgaps=False,
                    hovertemplate=(
                        f"{label}<br>Highest-density occupancy region<br>"
                        f"Covered duration: {envelope.achieved_share * 100.0:.1f}%<br>"
                        f"Selected: {envelope.selected_hours:.1f} h of {envelope.total_hours:.1f} h<extra></extra>"
                    ),
                )
            )
    elif data_mode == "Distributive grid":
        metric_col = None if color_mode == "Frequency" else color_metric_column
        _add_psychrometric_tile_occupancy(fig, plot_df, chart_type, pressure_pa, t_range, d_range, h_range, metric_col, color_metric_label)
    else:
''',
)
replace_once(
    CHARTS,
    '            title=dict(text="Month", font=dict(size=13)),\n',
    '            title=dict(text=("Year" if data_mode == "Middle 90% envelopes" and time_basis(plot_df) == CHRONOLOGICAL and is_multiyear(plot_df) else ("Envelope" if data_mode == "Middle 90% envelopes" else "Month")), font=dict(size=13)),\n',
)

# comparison.py — one shared psychrometric chart and the same 90% occupancy definition.
replace_once(
    COMPARISON,
    'from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves\n',
    'from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves\nfrom .psychrometric_distribution import envelope_polygon_coordinates, psychrometric_occupancy_envelope\n',
)
replace_once(
    COMPARISON,
    '    metric_color,\n    semantic_color_from_text,\n',
    '    metric_color,\n    rgba,\n    semantic_color_from_text,\n',
)
comparison_function = '''def psychrometric_comparison_chart(
    climates: list[ClimateDataset],
    chart_type: str = "T-d",
    mode: str = "Overlay",
    pressure_pa: float = DEFAULT_PRESSURE_PA,
    data_display: str = "All observations",
) -> go.Figure:
    """Create one shared psychrometric comparison chart for all climates.

    ``All observations`` preserves the observed joint distribution as WebGL
    points. ``Middle 90% envelopes`` draws duration-weighted highest-density
    occupancy regions on the same psychrometric axes. The global comparison
    display mode is accepted for API compatibility but this chart deliberately
    remains shared so climate envelopes are directly comparable.
    """
    del mode
    if data_display not in {"All observations", "Middle 90% envelopes"}:
        raise ValueError(f"Unsupported psychrometric comparison display: {data_display}")
    chart_type = "i-d" if chart_type == "i-d" else "T-d"
    colors = climate_color_map([climate.display_name for climate in climates])
    fig = go.Figure()
    if chart_type == "i-d":
        x_col = "humidity_ratio_g_kg"
        y_col = "moist_air_enthalpy_kj_kg"
        x_label = "Moisture content d [g/kg dry air]"
        y_label = "Enthalpy i [kJ/kg dry air]"
    else:
        x_col = "dry_bulb_temperature_c"
        y_col = "humidity_ratio_g_kg"
        x_label = "Dry-bulb temperature [°C]"
        y_label = "Moisture content d [g/kg dry air]"

    for climate in climates:
        color = colors[climate.display_name]
        if data_display == "Middle 90% envelopes":
            envelope = psychrometric_occupancy_envelope(climate.data, target_share=0.90)
            if envelope.selected_tiles.empty:
                continue
            xs, ys = envelope_polygon_coordinates(envelope, chart_type=chart_type, pressure_pa=pressure_pa)
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    name=climate.display_name,
                    line=dict(color=rgba(color, 0.88), width=0.8),
                    fill="toself",
                    fillcolor=rgba(color, 0.12),
                    connectgaps=False,
                    hovertemplate=(
                        f"{climate.display_name}<br>Middle 90% highest-density occupancy region<br>"
                        f"Covered duration: {envelope.achieved_share * 100.0:.1f}%<br>"
                        f"Selected: {envelope.selected_hours:.1f} h of {envelope.total_hours:.1f} h<extra></extra>"
                    ),
                )
            )
        else:
            data = climate.data[[x_col, y_col]].replace([np.inf, -np.inf], np.nan).dropna()
            fig.add_trace(
                go.Scattergl(
                    x=data[x_col],
                    y=data[y_col],
                    mode="markers",
                    name=climate.display_name,
                    marker=dict(size=3.5, opacity=0.20, color=color),
                    hovertemplate=f"{climate.display_name}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",
                )
            )

    if chart_type == "T-d":
        for curve in psychrometric_rh_curves("T-d", pressure_pa=pressure_pa):
            fig.add_trace(
                go.Scatter(
                    x=curve["x"], y=curve["y"], mode="lines",
                    line=dict(width=0.55, color="rgba(75,85,99,0.34)"),
                    showlegend=False, hoverinfo="skip",
                )
            )
    fig.update_layout(
        template=PLOT_TEMPLATE,
        title=f"Psychrometric climate comparison — {data_display} ({chart_type})",
        xaxis_title=x_label,
        yaxis_title=y_label,
        hovermode="closest",
        height=720,
        legend_title_text="Climate",
        margin=dict(l=55, r=25, t=70, b=55),
    )
    return fig


'''
replace_between(COMPARISON, 'def psychrometric_comparison_chart(', 'def sun_path_comparison_chart(', comparison_function)

# app.py — expose the same two-dimensional envelope semantics in both routes.
replace_once(
    APP,
    '        data_mode = st.radio("Loaded climate data mode", [source_interval_mode, "Distributive grid"], horizontal=True)\n        st.caption("Distributive grid uses 1 °C × 5 %RH cells drawn on the real psychrometric chart geometry.")\n',
    '        data_mode = st.radio("Loaded climate data mode", [source_interval_mode, "Distributive grid", "Middle 90% envelopes"], horizontal=True)\n        if data_mode == "Distributive grid":\n            st.caption("Distributive grid uses 1 °C × 5 %RH cells drawn on the real psychrometric chart geometry; frequency is mapped from pale to saturated blue.")\n        elif data_mode == "Middle 90% envelopes":\n            st.caption("Middle 90% uses the highest-density 1 °C × 5 %RH occupancy cells covering at least 90% of represented physical duration. It is not an independent T/d percentile rectangle.")\n',
)
replace_once(
    APP,
    '            metric_options = list(PSYCHROMETRIC_COLOR_METRICS.keys())\n            default_metric = "Frequency" if data_mode == "Distributive grid" else "Month"\n            color_mode = st.selectbox("Colour mapped metric", metric_options, index=metric_options.index(default_metric))\n            color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]\n            if data_mode != "Distributive grid" and color_mode == "Frequency":\n                st.caption("Frequency is only meaningful for the distributive grid. Source interval values will be shown by month.")\n                color_mode = "Month"\n                color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]\n',
    '''            metric_options = list(PSYCHROMETRIC_COLOR_METRICS.keys())
            if data_mode == "Middle 90% envelopes":
                color_mode = "Month"
                color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]
                if time_basis(df) == CHRONOLOGICAL and is_multiyear(df):
                    st.caption("Chronological multi-year mode draws one Middle-90% occupancy envelope per real source year; years are not folded together.")
                else:
                    st.caption("The active filtered climate interval is represented by one duration-weighted Middle-90% occupancy envelope.")
            else:
                default_metric = "Frequency" if data_mode == "Distributive grid" else "Month"
                color_mode = st.selectbox("Colour mapped metric", metric_options, index=metric_options.index(default_metric))
                color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]
                if data_mode != "Distributive grid" and color_mode == "Frequency":
                    st.caption("Frequency is only meaningful for the distributive grid. Source interval values will be shown by month.")
                    color_mode = "Month"
                    color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]
''',
)
replace_once(
    APP,
    '    elif chart == "Psychrometric density":\n        chart_type = st.radio("Psychrometric axes", ["T-d", "i-d"], horizontal=True)\n        fig = psychrometric_comparison_chart(climates, chart_type=chart_type, mode=mode, pressure_pa=pressure_pa)\n        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))\n',
    '''    elif chart == "Psychrometric density":
        chart_type = st.radio("Psychrometric axes", ["T-d", "i-d"], horizontal=True)
        distribution_display = st.radio(
            "Climate distribution",
            ["All observations", "Middle 90% envelopes"],
            horizontal=True,
            key="compare_psychrometric_distribution",
        )
        st.caption(
            "All selected climates use one shared psychrometric axis. Middle 90% retains the densest 1 °C × 5 %RH cells containing at least 90% of each climate's represented duration."
        )
        fig = psychrometric_comparison_chart(
            climates,
            chart_type=chart_type,
            mode=mode,
            pressure_pa=pressure_pa,
            data_display=distribution_display,
        )
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
''',
)

replace_once(
    DOC,
    '## D — Psychrometric redesign\n\nPlanned:\n\n- Chronological multi-year yearly climate envelopes.\n- Frequency palette: low frequency pale blue, high frequency saturated blue.\n- One common psychrometric comparison chart for all selected climates.\n- Envelope extent selector: **All observations** or **Middle 90%**.\n',
    '''## D — Psychrometric redesign

Implemented in D1/D2:

- Chronological multi-year psychrometric analysis draws one envelope per real source year; year identity is never folded away in Chronological mode.
- Psychrometric frequency tiles use the dedicated blue duration scale: zero is transparent/white, low occupancy is pale blue and high occupancy is saturated dark blue.
- **Middle 90%** is a two-dimensional highest-density occupancy region based on 1 °C × 5 %RH cells weighted by represented physical duration. It is not a rectangle from independent marginal T/d percentiles.
- Ties at the 90% cutoff are retained together, so the achieved coverage may be slightly above 90% rather than arbitrarily dropping spatially equivalent cells.
- Compare Climates uses one shared psychrometric axis for every selected climate with **All observations** and **Middle 90% envelopes** modes.
- Comparison envelope colours retain the stable per-climate identity palette.
''',
)

TEST.write_text(r'''from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd
import psychrolib

from epw_climate_analyzer.chart_theme import PSYCHROMETRIC_TILE_COLORSCALE
from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.comparison import ClimateDataset, psychrometric_comparison_chart
from epw_climate_analyzer.psychrometric_distribution import psychrometric_occupancy_envelope
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis

psychrolib.SetUnitSystem(psychrolib.SI)
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def _psych_frame(year: int = 2026, *, offset_c: float = 0.0) -> pd.DataFrame:
    states = [(20.2 + offset_c, 47.0)] * 60 + [(25.2 + offset_c, 57.0)] * 30 + [(30.2 + offset_c, 77.0)] * 10
    index = pd.date_range(f"{year}-01-01", periods=len(states), freq="h")
    t = np.array([item[0] for item in states], dtype=float)
    rh = np.array([item[1] for item in states], dtype=float)
    pressure = 101325.0
    w = np.array([psychrolib.GetHumRatioFromRelHum(float(tt), float(rr) / 100.0, pressure) for tt, rr in states])
    d = w * 1000.0
    h = np.array([psychrolib.GetMoistAirEnthalpy(float(tt), float(ww)) / 1000.0 for tt, ww in zip(t, w, strict=True)])
    frame = pd.DataFrame(
        {
            "dry_bulb_temperature_c": t,
            "relative_humidity_pct": rh,
            "humidity_ratio_g_kg": d,
            "moist_air_enthalpy_kj_kg": h,
            "month_index": index.month,
            "month_name": index.strftime("%b"),
            "hour_of_day": index.hour,
        },
        index=index,
    )
    return with_time_basis(frame, CHRONOLOGICAL)


class PsychrometricRedesign074Tests(unittest.TestCase):
    def test_middle_90_is_duration_weighted_joint_highest_density_region(self) -> None:
        envelope = psychrometric_occupancy_envelope(_psych_frame(), target_share=0.90)
        self.assertAlmostEqual(envelope.total_hours, 100.0)
        self.assertAlmostEqual(envelope.selected_hours, 90.0)
        self.assertAlmostEqual(envelope.achieved_share, 0.90)
        selected = envelope.selected_tiles
        self.assertEqual(len(selected), 2)
        self.assertFalse(np.isclose(selected["temperature_bin_c"].to_numpy(dtype=float), 30.0).any())

    def test_frequency_tiles_use_zero_anchored_blue_scale(self) -> None:
        fig = psychrometric_chart(
            _psych_frame(),
            chart_type="T-d",
            show_comfort_zone=False,
            metric_layers=[],
            data_mode="Distributive grid",
            color_mode="Frequency",
        )
        scale_traces = [trace for trace in fig.data if getattr(getattr(trace, "marker", None), "showscale", False)]
        self.assertEqual(len(scale_traces), 1)
        marker = scale_traces[0].marker
        self.assertAlmostEqual(float(marker.cmin), 0.0)
        self.assertEqual(str(marker.colorscale[0][1]).lower(), str(PSYCHROMETRIC_TILE_COLORSCALE[0][1]).lower())
        self.assertEqual(str(marker.colorscale[-1][1]).lower(), str(PSYCHROMETRIC_TILE_COLORSCALE[-1][1]).lower())

    def test_chronological_multiyear_single_climate_keeps_real_year_envelopes(self) -> None:
        frame = pd.concat([_psych_frame(2024), _psych_frame(2025, offset_c=1.0)])
        frame = with_time_basis(frame, CHRONOLOGICAL)
        fig = psychrometric_chart(
            frame,
            chart_type="T-d",
            show_comfort_zone=False,
            metric_layers=[],
            data_mode="Middle 90% envelopes",
        )
        names = {str(trace.name) for trace in fig.data if getattr(trace, "fill", None) == "toself"}
        self.assertIn("2024", names)
        self.assertIn("2025", names)

    def test_compare_climates_middle_90_uses_one_shared_axis_and_climate_identity(self) -> None:
        climates = [
            ClimateDataset("a", "Climate A", "test", None, _psych_frame(2026), []),
            ClimateDataset("b", "Climate B", "test", None, _psych_frame(2026, offset_c=3.0), []),
        ]
        fig = psychrometric_comparison_chart(climates, data_display="Middle 90% envelopes")
        envelope_traces = [trace for trace in fig.data if getattr(trace, "fill", None) == "toself"]
        self.assertEqual({trace.name for trace in envelope_traces}, {"Climate A", "Climate B"})
        self.assertEqual(fig.layout.legend.title.text, "Climate")
        self.assertEqual(len(fig.layout.xaxis.domain or ()), 0)

    def test_ui_exposes_common_all_observations_and_middle_90_contract(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('[source_interval_mode, "Distributive grid", "Middle 90% envelopes"]', source)
        self.assertIn('"Climate distribution"', source)
        self.assertIn('["All observations", "Middle 90% envelopes"]', source)
        self.assertIn("highest-density 1 °C × 5 %RH occupancy cells", source)
        self.assertIn("one Middle-90% occupancy envelope per real source year", source)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

print("0.7.4-D psychrometric redesign patch applied")
