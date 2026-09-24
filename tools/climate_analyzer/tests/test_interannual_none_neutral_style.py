from __future__ import annotations

from types import SimpleNamespace
import unittest

import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.interannual_presentation import (
    BACKGROUND_OPACITY,
    HIGHLIGHT_COLOR,
    HIGHLIGHT_WIDTH,
)
from epw_climate_analyzer.interannual_year_highlight import (
    HIGHLIGHT_STATE_KEY,
    NEUTRAL_YEAR_COLOR,
    NEUTRAL_YEAR_MARKER_SIZE,
    NEUTRAL_YEAR_WIDTH,
    _style_interannual_year_figure,
    install_interannual_year_highlight,
)
from epw_climate_analyzer.temporal_filtering import INTERANNUAL_OVERLAY, with_time_basis


class InterannualNoneNeutralStyleTests(unittest.TestCase):
    @staticmethod
    def _frame() -> pd.DataFrame:
        index = pd.DatetimeIndex(
            [
                "2020-01-01", "2020-02-01",
                "2021-01-01", "2021-02-01",
                "2022-01-01", "2022-02-01",
            ]
        )
        frame = pd.DataFrame({"dry_bulb_temperature_c": range(6)}, index=index)
        return with_time_basis(frame, INTERANNUAL_OVERLAY)

    @staticmethod
    def _figure() -> go.Figure:
        fig = go.Figure()
        for year in (2020, 2021, 2022):
            fig.add_trace(
                go.Scatter(
                    x=[1, 2],
                    y=[year, year + 1],
                    mode="lines+markers",
                    name=str(year),
                    legendgroup=str(year),
                    line={"color": "#2563eb", "width": 2.0},
                    marker={"color": "#2563eb", "size": 5.0},
                    opacity=0.8,
                )
            )
        fig.add_trace(
            go.Scatter(
                x=[1, 2],
                y=[0, 1],
                mode="lines",
                name="Interannual mean",
                legendgroup="interannual-envelope",
                line={"color": "#f59e0b", "width": 2.0},
                opacity=1.0,
            )
        )
        return fig

    def test_none_is_available_in_production_legacy_slot_without_int_none_failure(self) -> None:
        class FakeStreamlit:
            def __init__(self):
                self.session_state = {
                    HIGHLIGHT_STATE_KEY: None,
                    "global_time_basis": INTERANNUAL_OVERLAY,
                }
                self.calls: list[dict[str, object]] = []

            def selectbox(self, label, options, *args, **kwargs):
                values = list(options)
                self.calls.append(
                    {"label": str(label), "options": values, "key": kwargs.get("key")}
                )
                key = kwargs.get("key")
                if key is not None and key in self.session_state:
                    return self.session_state[key]
                index = int(kwargs.get("index", 0)) if values else 0
                return values[index] if values else None

        st = FakeStreamlit()
        returned: dict[str, object] = {}

        def legacy_renderer(df, *args, **kwargs):
            st.selectbox("Aggregation", ["Monthly", "Annual"], index=0)
            legacy_value = st.selectbox(
                "Highlight year",
                [2020, 2021, 2022],
                index=2,
                key="legacy_profile_highlight_year",
            )
            returned["legacy_value"] = legacy_value
            returned["legacy_int"] = int(legacy_value)
            return None

        proxy = SimpleNamespace(
            st=st,
            render_time_series_overlay=lambda _df, *args, **kwargs: None,
            render_generic_variable_page=legacy_renderer,
            render_plot=lambda fig, *args, **kwargs: fig,
            _source_parity_original_generic_interannual=legacy_renderer,
        )

        install_interannual_year_highlight(proxy)
        proxy.render_generic_variable_page(self._frame())

        highlight_calls = [call for call in st.calls if call["label"] == "Highlight year"]
        self.assertEqual(len(highlight_calls), 1)
        self.assertEqual(highlight_calls[0]["key"], HIGHLIGHT_STATE_KEY)
        self.assertEqual(highlight_calls[0]["options"], [None, 2020, 2021, 2022])
        self.assertIsNone(st.session_state[HIGHLIGHT_STATE_KEY])
        self.assertEqual(returned["legacy_value"], 2022)
        self.assertEqual(returned["legacy_int"], 2022)

    def test_none_renders_all_real_years_thin_light_gray(self) -> None:
        fig = _style_interannual_year_figure(self._figure(), None)
        year_traces = [trace for trace in fig.data if str(trace.legendgroup).isdigit()]

        self.assertEqual(len(year_traces), 3)
        for trace in year_traces:
            self.assertEqual(trace.line.color, NEUTRAL_YEAR_COLOR)
            self.assertEqual(float(trace.line.width), NEUTRAL_YEAR_WIDTH)
            self.assertEqual(float(trace.opacity), BACKGROUND_OPACITY)
            self.assertEqual(trace.marker.color, NEUTRAL_YEAR_COLOR)
            self.assertEqual(float(trace.marker.size), NEUTRAL_YEAR_MARKER_SIZE)

        envelope = next(trace for trace in fig.data if trace.legendgroup == "interannual-envelope")
        self.assertEqual(envelope.line.color, "#f59e0b")
        self.assertEqual(float(envelope.opacity), 1.0)

    def test_selected_year_is_red_over_neutral_gray_background(self) -> None:
        fig = _style_interannual_year_figure(self._figure(), 2021)
        self.assertEqual(fig.data[-1].legendgroup, "2021")
        self.assertEqual(fig.data[-1].line.color, HIGHLIGHT_COLOR)
        self.assertGreaterEqual(float(fig.data[-1].line.width), HIGHLIGHT_WIDTH)
        self.assertEqual(float(fig.data[-1].opacity), 1.0)

        backgrounds = [
            trace for trace in fig.data
            if str(trace.legendgroup).isdigit() and trace.legendgroup != "2021"
        ]
        for trace in backgrounds:
            self.assertEqual(trace.line.color, NEUTRAL_YEAR_COLOR)
            self.assertEqual(float(trace.line.width), NEUTRAL_YEAR_WIDTH)
            self.assertLessEqual(float(trace.opacity), BACKGROUND_OPACITY)


if __name__ == "__main__":
    unittest.main()
