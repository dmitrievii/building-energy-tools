from __future__ import annotations

import os
from pathlib import Path


if os.environ.get("GITHUB_ACTOR") == "github-actions[bot]":
    raise SystemExit(0)


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


app = Path("tools/climate_analyzer/app.py")
comparison = Path("tools/climate_analyzer/epw_climate_analyzer/comparison.py")
guard = Path("tools/climate_analyzer/epw_climate_analyzer/runtime_module_guard.py")
guard_test = Path("tools/climate_analyzer/tests/test_psychrometric_runtime_guard_0_7_4_2.py")

replace_once(
    app,
    '''        elif representation == "Distribution grid":
            st.caption(
                "Distribution-grid comparison uses the original 1 °C × 5 %RH psychrometric cells. Climate hue identifies the dataset; cell opacity follows represented hours on one shared scale."
            )

        reference = next((climate for climate in climates if climate.display_name == reference_name), climates[0])
''',
    '''        elif representation == "Distribution grid":
            st.caption(
                "Distribution-grid comparison uses the original 1 °C × 5 %RH psychrometric cells. Climate hue identifies the dataset; cell opacity follows represented hours on one shared scale."
            )

        with st.expander("Chart overlays", expanded=True):
            overlay_c1, overlay_c2 = st.columns(2)
            show_givoni = overlay_c1.checkbox(
                "Show Givoni-Milne bioclimatic overlay",
                value=True,
                key="compare_psych_show_givoni",
            )
            show_heat_index = overlay_c2.checkbox(
                "Show heat-index overlay",
                value=False,
                key="compare_psych_show_heat_index",
            )
            st.caption(
                "Givoni-Milne zones and heat-index isolines use the same common psychrometric reference pressure as the compared climate representations."
            )

        reference = next((climate for climate in climates if climate.display_name == reference_name), climates[0])
''',
)

replace_once(
    app,
    '''            additional_contour_coverages=additional_contour_coverages,
            reference_pressure_pa=float(reference_grid_pressure),
        )
''',
    '''            additional_contour_coverages=additional_contour_coverages,
            reference_pressure_pa=float(reference_grid_pressure),
            show_givoni_overlay=show_givoni,
            show_heat_index_overlay=show_heat_index,
        )
''',
)

replace_once(
    comparison,
    '''from .psychrometric_distribution import add_climate_zone_traces, psychrometric_axis_ranges
from .solar import orientation_annual_radiation, orientation_tilt_matrix, surface_irradiance_series
''',
    '''from .psychrometric_distribution import add_climate_zone_traces, psychrometric_axis_ranges
from .charts import _add_givoni_milne_overlay, _add_heat_index_overlay
from .solar import orientation_annual_radiation, orientation_tilt_matrix, surface_irradiance_series
''',
)

replace_once(
    comparison,
    '''    additional_contour_coverages: list[float] | None = None,
    reference_pressure_pa: float | None = None,
) -> go.Figure:
''',
    '''    additional_contour_coverages: list[float] | None = None,
    reference_pressure_pa: float | None = None,
    show_givoni_overlay: bool = False,
    show_heat_index_overlay: bool = False,
) -> go.Figure:
''',
)

replace_once(
    comparison,
    '''                fig.add_trace(
                    go.Scattergl(
                        x=data[x_col],
                        y=data[y_col],
                        mode="markers",
                        name=climate.display_name,
                        marker=dict(size=3.5, opacity=0.22, color=color),
                        hovertemplate=f"{climate.display_name}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",
                    )
                )

    title_mode = {
''',
    '''                fig.add_trace(
                    go.Scattergl(
                        x=data[x_col],
                        y=data[y_col],
                        mode="markers",
                        name=climate.display_name,
                        marker=dict(size=3.5, opacity=0.22, color=color),
                        hovertemplate=f"{climate.display_name}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",
                    )
                )

    # These overlays are common reference layers rather than climate-specific
    # datasets, so they use the same selected display pressure as all climates.
    if show_givoni_overlay:
        _add_givoni_milne_overlay(fig, chart_type, grid_pressure, None)
    if show_heat_index_overlay:
        heat_t_range = (t_min, t_max)
        heat_d_range = shared_ranges[1] if chart_type == "T-d" else shared_ranges[0]
        heat_h_range = None if chart_type == "T-d" else shared_ranges[1]
        _add_heat_index_overlay(
            fig,
            chart_type,
            grid_pressure,
            heat_t_range,
            heat_d_range,
            heat_h_range,
        )

    title_mode = {
''',
)

replace_once(
    comparison,
    '''    fig.update_xaxes(range=list(shared_ranges[0]), autorange=False)
    fig.update_yaxes(range=list(shared_ranges[1]), autorange=False)
    return fig
''',
    '''    fig.update_xaxes(range=list(shared_ranges[0]), autorange=False)
    fig.update_yaxes(range=list(shared_ranges[1]), autorange=False)
    if show_givoni_overlay or show_heat_index_overlay:
        fig.update_layout(
            legend=dict(
                title=dict(text="Climate", font=dict(size=13)),
                orientation="v",
                yanchor="bottom",
                y=0.0,
                xanchor="left",
                x=0.755,
                itemsizing="constant",
                font=dict(size=12),
                groupclick="toggleitem",
            ),
            legend2=dict(
                title=dict(text="Bioclimatic / thermal overlays", font=dict(size=13)),
                orientation="v",
                yanchor="top",
                y=1.0,
                xanchor="left",
                x=0.755,
                itemsizing="constant",
                font=dict(size=12),
                groupclick="togglegroup",
                traceorder="normal",
            ),
            margin=dict(l=55, r=25, t=70, b=70),
        )
        fig.update_xaxes(domain=[0.0, 0.72])
    return fig
''',
)

replace_once(
    guard,
    '_REQUIRED_COMPARISON_PARAMETERS = frozenset({"additional_contour_coverages"})\n',
    '_REQUIRED_COMPARISON_PARAMETERS = frozenset({"additional_contour_coverages", "show_givoni_overlay", "show_heat_index_overlay"})\n',
)

replace_once(
    guard,
    '''    charts = importlib.import_module("epw_climate_analyzer.charts")
    missing_parameters = _missing_psychrometric_chart_parameters(charts)
    if distribution_was_reloaded or missing_parameters:
        charts = importlib.reload(charts)
        missing_parameters = _missing_psychrometric_chart_parameters(charts)
''',
    '''    charts = importlib.import_module("epw_climate_analyzer.charts")
    missing_parameters = _missing_psychrometric_chart_parameters(charts)
    charts_was_reloaded = False
    if distribution_was_reloaded or missing_parameters:
        charts = importlib.reload(charts)
        charts_was_reloaded = True
        missing_parameters = _missing_psychrometric_chart_parameters(charts)
''',
)

replace_once(
    guard,
    '''    if missing_compare:
        comparison = importlib.reload(comparison)
        missing_compare = _missing_callable_parameters(
''',
    '''    if distribution_was_reloaded or charts_was_reloaded or missing_compare:
        comparison = importlib.reload(comparison)
        missing_compare = _missing_callable_parameters(
''',
)

replace_once(
    guard_test,
    '''import epw_climate_analyzer.charts as charts
import epw_climate_analyzer.psychrometric_distribution as distribution
''',
    '''import epw_climate_analyzer.charts as charts
import epw_climate_analyzer.comparison as comparison
import epw_climate_analyzer.psychrometric_distribution as distribution
''',
)

replace_once(
    guard_test,
    'REQUIRED_DISTRIBUTION_PARAMETERS = {"additional_coverages", "pressure_pa"}\n',
    '''REQUIRED_DISTRIBUTION_PARAMETERS = {"additional_coverages", "pressure_pa"}
REQUIRED_COMPARISON_PARAMETERS = {"additional_contour_coverages", "show_givoni_overlay", "show_heat_index_overlay"}
''',
)

replace_once(
    guard_test,
    '''        self.assertTrue(
            REQUIRED_DISTRIBUTION_PARAMETERS.issubset(
                inspect.signature(current_distribution.add_climate_zone_traces).parameters
            )
        )
''',
    '''        self.assertTrue(
            REQUIRED_DISTRIBUTION_PARAMETERS.issubset(
                inspect.signature(current_distribution.add_climate_zone_traces).parameters
            )
        )
        self.assertTrue(
            REQUIRED_COMPARISON_PARAMETERS.issubset(
                inspect.signature(comparison.psychrometric_comparison_chart).parameters
            )
        )
''',
)

marker = '''    def test_stale_distribution_helper_signature_is_reloaded_and_rebound(self) -> None:
'''
insertion = '''    def test_stale_comparison_signature_is_reloaded(self) -> None:
        def stale_comparison_chart(
            climates,
            chart_type="T-d",
            mode="Overlay",
            pressure_pa=101325.0,
            data_display="Climate zones",
            zone_coverage=0.90,
            zone_interior_style="Density gradient",
            show_core_zone=False,
            additional_contour_coverages=None,
            reference_pressure_pa=None,
        ):
            return None

        comparison.psychrometric_comparison_chart = stale_comparison_chart
        ensure_current_psychrometric_runtime()

        self.assertIsNot(comparison.psychrometric_comparison_chart, stale_comparison_chart)
        self.assertTrue(
            REQUIRED_COMPARISON_PARAMETERS.issubset(
                inspect.signature(comparison.psychrometric_comparison_chart).parameters
            )
        )

'''
text = guard_test.read_text(encoding="utf-8")
if text.count(marker) != 1:
    raise RuntimeError("runtime guard test insertion point not unique")
guard_test.write_text(text.replace(marker, insertion + marker, 1), encoding="utf-8")
