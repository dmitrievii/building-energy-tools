from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.interannual_year_highlight import (
    BACKGROUND_OPACITY,
    HIGHLIGHT_COLOR,
    HIGHLIGHT_MARKER_SIZE,
    HIGHLIGHT_WIDTH,
    apply_interannual_year_highlight,
    install_interannual_year_highlight,
)
from epw_climate_analyzer.temporal_filtering import INTERANNUAL_OVERLAY, with_time_basis


class InterannualYearHighlightTests(unittest.TestCase):
    @staticmethod
    def _figure() -> go.Figure:
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

    def test_none_keeps_existing_trace_order_and_style(self) -> None:
        fig = self._figure()
        before = [(trace.legendgroup, trace.line.color, trace.line.width, trace.opacity) for trace in fig.data]
        returned = apply_interannual_year_highlight(fig, None)
        after = [(trace.legendgroup, trace.line.color, trace.line.width, trace.opacity) for trace in fig.data]
        self.assertIs(returned, fig)
        self.assertEqual(after, before)

    def test_runtime_control_applies_highlight_to_shared_builder(self) -> None:
        class Sidebar:
            def selectbox(self, label, options, **kwargs):
                self.label = label
                self.options = list(options)
                return 2021

        sidebar = Sidebar()
        st = SimpleNamespace(sidebar=sidebar, session_state={})
        proxy = SimpleNamespace(st=st)
        captured: dict[str, go.Figure] = {}

        def builder(*args, **kwargs):
            return self._figure(), []

        proxy.build_overlay_figure = builder

        def render(df):
            fig, _tables = proxy.build_overlay_figure(df, [], pd.Timestamp("2020-01-01"), pd.Timestamp("2023-01-01"))
            captured["fig"] = fig

        proxy.render_time_series_overlay = render
        install_interannual_year_highlight(proxy)

        index = pd.DatetimeIndex(["2020-01-01", "2021-01-01", "2022-01-01"])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [1.0, 2.0, 3.0]}, index=index)
        frame = with_time_basis(frame, INTERANNUAL_OVERLAY)
        proxy.render_time_series_overlay(frame)

        self.assertEqual(sidebar.label, "Highlight year")
        self.assertEqual(sidebar.options, [None, 2020, 2021, 2022])
        self.assertEqual([trace.legendgroup for trace in captured["fig"].data], ["2020", "2022", "2021"])
        self.assertEqual(captured["fig"].data[-1].line.color, HIGHLIGHT_COLOR)
        self.assertIs(proxy.build_overlay_figure, builder)


if __name__ == "__main__":
    unittest.main()
