from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.interannual_presentation import HIGHLIGHT_ATTR
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

    @staticmethod
    def _monthly_frame() -> pd.DataFrame:
        index = pd.DatetimeIndex(
            [
                "2020-01-01", "2020-02-01",
                "2021-01-01", "2021-02-01",
                "2022-01-01", "2022-02-01",
            ]
        )
        frame = pd.DataFrame(
            {"dry_bulb_temperature_c": [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]},
            index=index,
        )
        frame.attrs["canonical_native_resolution"] = "monthly"
        return with_time_basis(frame, INTERANNUAL_OVERLAY)

    @staticmethod
    def _proxy(selected_year: int | None = None) -> SimpleNamespace:
        class FakeStreamlit:
            def __init__(self):
                self.session_state = {HIGHLIGHT_STATE_KEY: selected_year}

            def selectbox(self, label, options, **kwargs):
                self.label = label
                self.options = list(options)
                return self.session_state.get(kwargs.get("key"))

        return SimpleNamespace(
            st=FakeStreamlit(),
            render_time_series_overlay=lambda _df: None,
            render_generic_variable_page=lambda _df, *args, **kwargs: None,
        )

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

    def test_trace_name_is_defensive_year_fallback(self) -> None:
        fig = self._figure()
        for trace in fig.data:
            trace.legendgroup = None
        styled = apply_interannual_year_highlight(fig, 2021)
        self.assertEqual(styled.data[-1].name, "Temperature — 2021")
        self.assertEqual(styled.data[-1].line.color, HIGHLIGHT_COLOR)

    def test_envelope_keeps_style_and_selected_year_is_above_it(self) -> None:
        fig = apply_interannual_year_highlight(self._figure(include_envelope=True), 2022)

        self.assertEqual(fig.data[-1].legendgroup, "2022")
        self.assertEqual(fig.data[-1].line.color, HIGHLIGHT_COLOR)
        envelope = next(trace for trace in fig.data if trace.legendgroup == "interannual-envelope")
        self.assertEqual(envelope.line.color, "#f59e0b")
        self.assertEqual(float(envelope.opacity), 1.0)

    def test_missing_selected_year_does_not_mutate_unrelated_figure(self) -> None:
        fig = self._figure(include_envelope=True)
        before = [
            (trace.legendgroup, trace.line.color, trace.line.width, trace.opacity)
            for trace in fig.data
        ]
        returned = apply_interannual_year_highlight(fig, 2026)
        after = [
            (trace.legendgroup, trace.line.color, trace.line.width, trace.opacity)
            for trace in fig.data
        ]
        self.assertIs(returned, fig)
        self.assertEqual(after, before)

    def test_none_keeps_existing_trace_order_and_style(self) -> None:
        fig = self._figure()
        before = [(trace.legendgroup, trace.line.color, trace.line.width, trace.opacity) for trace in fig.data]
        returned = apply_interannual_year_highlight(fig, None)
        after = [(trace.legendgroup, trace.line.color, trace.line.width, trace.opacity) for trace in fig.data]
        self.assertIs(returned, fig)
        self.assertEqual(after, before)

    def test_temperature_profile_builder_receives_highlight_metadata(self) -> None:
        proxy = self._proxy(2021)
        st = proxy.st
        rendered: dict[str, go.Figure] = {}
        metadata: dict[str, object] = {}

        def render_generic_variable_page(df, *args, **kwargs):
            from epw_climate_analyzer import charts

            metadata["highlight"] = df.attrs.get(HIGHLIGHT_ATTR)
            rendered["fig"] = charts.profile_ribbon_chart(
                df,
                "dry_bulb_temperature_c",
                "Monthly",
                "Temperature and extremes: Dry-bulb temperature",
                "°C",
            )
            return rendered["fig"]

        proxy.render_generic_variable_page = render_generic_variable_page
        install_interannual_year_highlight(proxy)
        proxy.render_generic_variable_page(
            self._monthly_frame(),
            ["Dry-bulb temperature"],
            "Dry-bulb temperature",
            "Temperature",
        )

        fig = rendered["fig"]
        self.assertEqual(metadata["highlight"], 2021)
        self.assertEqual(st.label, "Highlight year")
        self.assertEqual(st.options, [None, 2020, 2021, 2022])
        self.assertEqual(fig.data[-1].legendgroup, "2021")
        self.assertEqual(fig.data[-1].line.color, HIGHLIGHT_COLOR)
        self.assertGreaterEqual(float(fig.data[-1].line.width), HIGHLIGHT_WIDTH)
        self.assertEqual(float(fig.data[-1].opacity), 1.0)
        envelope = next(trace for trace in fig.data if trace.legendgroup == "interannual-envelope")
        self.assertEqual(float(envelope.opacity or 1.0), 1.0)

    def test_shared_overlay_builder_consumes_highlight_metadata(self) -> None:
        from epw_climate_analyzer import timeseries

        frame = self._monthly_frame().copy(deep=False)
        frame.attrs = dict(frame.attrs)
        frame.attrs[HIGHLIGHT_ATTR] = 2022

        proxy = self._proxy()
        install_interannual_year_highlight(proxy)

        fig, _tables = timeseries.build_overlay_figure(
            frame,
            [
                timeseries.OverlaySeries(
                    label="Dry-bulb temperature",
                    column="dry_bulb_temperature_c",
                    unit="°C",
                    resolution="Native",
                )
            ],
            pd.Timestamp("2020-01-01"),
            pd.Timestamp("2023-01-01"),
        )
        self.assertEqual(fig.data[-1].legendgroup, "2022")
        self.assertEqual(fig.data[-1].line.color, HIGHLIGHT_COLOR)
        self.assertGreaterEqual(float(fig.data[-1].line.width), HIGHLIGHT_WIDTH)

    def test_stale_module_flags_cannot_suppress_repatch_after_reload(self) -> None:
        """Reproduce Streamlit reload semantics that caused the production bug.

        importlib.reload restores source-defined builder functions but preserves
        dynamically added module names. Simulate that state by restoring each
        wrapper's ``__wrapped__`` source callable while deliberately leaving the
        old module-level ``...INSTALLED`` flags set to True. A fresh app-script
        proxy must still cause all three builders to be wrapped again.
        """
        from epw_climate_analyzer import charts, timeseries

        first_proxy = self._proxy(2021)
        install_interannual_year_highlight(first_proxy)

        wrapped_profile = charts.profile_ribbon_chart
        wrapped_percentile = charts.percentile_band_chart
        wrapped_overlay = timeseries.build_overlay_figure
        self.assertTrue(getattr(wrapped_profile, "_interannual_year_highlight_builder_wrapper", False))
        self.assertTrue(getattr(wrapped_percentile, "_interannual_year_highlight_builder_wrapper", False))
        self.assertTrue(getattr(wrapped_overlay, "_interannual_year_highlight_builder_wrapper", False))

        # This is the important reload state: source functions are back, while
        # old dynamically-added module guards survive as True.
        charts.profile_ribbon_chart = wrapped_profile.__wrapped__
        charts.percentile_band_chart = wrapped_percentile.__wrapped__
        timeseries.build_overlay_figure = wrapped_overlay.__wrapped__
        charts._INTERANNUAL_HIGHLIGHT_BUILDERS_INSTALLED = True
        timeseries._INTERANNUAL_HIGHLIGHT_BUILDER_INSTALLED = True

        self.assertFalse(getattr(charts.profile_ribbon_chart, "_interannual_year_highlight_builder_wrapper", False))
        self.assertFalse(getattr(timeseries.build_overlay_figure, "_interannual_year_highlight_builder_wrapper", False))

        fresh_proxy = self._proxy(2021)
        install_interannual_year_highlight(fresh_proxy)

        self.assertTrue(getattr(charts.profile_ribbon_chart, "_interannual_year_highlight_builder_wrapper", False))
        self.assertTrue(getattr(charts.percentile_band_chart, "_interannual_year_highlight_builder_wrapper", False))
        self.assertTrue(getattr(timeseries.build_overlay_figure, "_interannual_year_highlight_builder_wrapper", False))

        frame = self._monthly_frame().copy(deep=False)
        frame.attrs = dict(frame.attrs)
        frame.attrs[HIGHLIGHT_ATTR] = 2021
        fig = charts.profile_ribbon_chart(
            frame,
            "dry_bulb_temperature_c",
            "Monthly",
            "Temperature and extremes: Dry-bulb temperature",
            "°C",
        )
        self.assertEqual(fig.data[-1].legendgroup, "2021")
        self.assertEqual(fig.data[-1].line.color, HIGHLIGHT_COLOR)
        self.assertGreaterEqual(float(fig.data[-1].line.width), HIGHLIGHT_WIDTH)


if __name__ == "__main__":
    unittest.main()
