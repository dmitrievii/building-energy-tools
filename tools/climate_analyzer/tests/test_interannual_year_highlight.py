from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.interannual_year_highlight import (
    BACKGROUND_OPACITY,
    HIGHLIGHT_COLOR,
    HIGHLIGHT_MARKER_SIZE,
    HIGHLIGHT_STATE_KEY,
    HIGHLIGHT_WIDTH,
    apply_interannual_year_highlight,
    install_interannual_year_highlight,
)
from epw_climate_analyzer.temporal_filtering import INTERANNUAL_OVERLAY, with_time_basis


class InterannualYearHighlightTests(unittest.TestCase):
    @staticmethod
    def _figure(include_envelope: bool = False) -> go.Figure:
        fig = go.Figure()
        for year in (2020, 2021, 2022):
            fig.add_trace(
                go.Scatter(
                    x=[1, 2],
                    y=[float(year), float(year + 1)],
                    mode="lines+markers",
                    name=f"Temperature — {year}",
                    legendgroup=str(year),
                    line={"color": "#2563eb", "width": 2.0},
                    marker={"size": 5.0, "color": "#2563eb"},
                    opacity=0.8,
                )
            )
        if include_envelope:
            fig.add_trace(
                go.Scatter(
                    x=[1, 2],
                    y=[1.0, 2.0],
                    mode="lines",
                    name="Interannual mean",
                    legendgroup="interannual-envelope",
                    line={"color": "#f59e0b", "width": 2.0},
                    opacity=1.0,
                )
            )
        return fig

    def test_selected_year_is_red_thick_opaque_and_drawn_last(self) -> None:
        fig = apply_interannual_year_highlight(self._figure(), 2021)

        self.assertEqual([trace.legendgroup for trace in fig.data], ["2020", "2022", "2021"])
        selected = fig.data[-1]
        self.assertEqual(selected.line.color, HIGHLIGHT_COLOR)
        self.assertGreaterEqual(float(selected.line.width), HIGHLIGHT_WIDTH)
        self.assertEqual(float(selected.opacity), 1.0)
        self.assertEqual(selected.marker.color, HIGHLIGHT_COLOR)
        self.assertGreaterEqual(float(selected.marker.size), HIGHLIGHT_MARKER_SIZE)

        for trace in fig.data[:-1]:
            self.assertLessEqual(float(trace.opacity), BACKGROUND_OPACITY)

    def test_envelope_keeps_style_and_selected_year_is_above_it(self) -> None:
        fig = apply_interannual_year_highlight(self._figure(include_envelope=True), 2022)

        self.assertEqual(fig.data[-1].legendgroup, "2022")
        self.assertEqual(fig.data[-1].line.color, HIGHLIGHT_COLOR)
        envelope = next(trace for trace in fig.data if trace.legendgroup == "interannual-envelope")
        self.assertEqual(envelope.line.color, "#f59e0b")
        self.assertEqual(float(envelope.opacity), 1.0)

        year_traces = [trace for trace in fig.data if str(trace.legendgroup).isdigit()]
        for trace in year_traces[:-1]:
            self.assertLessEqual(float(trace.opacity), BACKGROUND_OPACITY)

    def test_none_keeps_existing_trace_order_and_style(self) -> None:
        fig = self._figure()
        before = [(trace.legendgroup, trace.line.color, trace.line.width, trace.opacity) for trace in fig.data]
        returned = apply_interannual_year_highlight(fig, None)
        after = [(trace.legendgroup, trace.line.color, trace.line.width, trace.opacity) for trace in fig.data]
        self.assertIs(returned, fig)
        self.assertEqual(after, before)

    def test_final_render_boundary_applies_highlight_to_profile_figure(self) -> None:
        class FakeStreamlit:
            def __init__(self):
                self.session_state = {
                    "global_time_basis": INTERANNUAL_OVERLAY,
                    HIGHLIGHT_STATE_KEY: 2021,
                }

            def selectbox(self, label, options, **kwargs):
                self.label = label
                self.options = list(options)
                return self.session_state.get(kwargs.get("key"))

        st = FakeStreamlit()
        proxy = SimpleNamespace(st=st)
        rendered: dict[str, go.Figure] = {}

        def render_plot(fig, *args, **kwargs):
            rendered["fig"] = fig
            return fig

        def render_time_series_overlay(_df):
            return None

        def render_generic_variable_page(df, *args, **kwargs):
            # This mimics the Temperature/interannual profile route: it builds an
            # already-year-grouped figure and sends it through the shared final
            # render boundary rather than through build_overlay_figure.
            return proxy.render_plot(self._figure(include_envelope=True), "text")

        proxy.render_plot = render_plot
        proxy.render_time_series_overlay = render_time_series_overlay
        proxy.render_generic_variable_page = render_generic_variable_page
        install_interannual_year_highlight(proxy)

        index = pd.DatetimeIndex(["2020-01-01", "2021-01-01", "2022-01-01"])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [1.0, 2.0, 3.0]}, index=index)
        frame = with_time_basis(frame, INTERANNUAL_OVERLAY)
        proxy.render_generic_variable_page(frame, ["Dry-bulb temperature"], "Dry-bulb temperature", "Temperature")

        fig = rendered["fig"]
        self.assertEqual(st.label, "Highlight year")
        self.assertEqual(st.options, [None, 2020, 2021, 2022])
        self.assertEqual(fig.data[-1].legendgroup, "2021")
        self.assertEqual(fig.data[-1].line.color, HIGHLIGHT_COLOR)
        envelope = next(trace for trace in fig.data if trace.legendgroup == "interannual-envelope")
        self.assertEqual(float(envelope.opacity), 1.0)


if __name__ == "__main__":
    unittest.main()
