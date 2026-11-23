"""R2.1 scientific regressions for temperature-specific interpretation."""
from __future__ import annotations

import unittest

import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.temperature_findings import temperature_figure_interpretation
from epw_climate_analyzer.interpretations import temperature_interpretation


class TemperatureR21Tests(unittest.TestCase):
    def setUp(self):
        index = pd.date_range("2026-07-01", periods=72, freq="h")
        self.df = pd.DataFrame(
            {"dry_bulb_temperature_c": [19.] * 72},
            index=index,
        )

    def test_profile_interprets_plotted_aggregation(self):
        fig = go.Figure()
        fig.add_scatter(x=["Jan", "Feb"], y=[12., 28.], name="Mean")
        value = temperature_figure_interpretation(self.df, fig, "profile")
        self.assertIn("Feb (28.0 °C)", value)
        self.assertIn("Jan (12.0 °C)", value)
        self.assertIn("seasonal envelope and passive-control priorities", value)

    def test_heatmap_interprets_selected_cells(self):
        fig = go.Figure(go.Heatmap(
            x=["Jan", "Feb"], y=[0, 12], z=[[10., 20.], [5., 30.]]
        ))
        value = temperature_figure_interpretation(self.df, fig, "heatmap")
        self.assertIn("5.0 °C (Jan, hour 12)", value)
        self.assertIn("30.0 °C (Feb, hour 12)", value)
        self.assertIn("seasonal concentration of outdoor temperatures", value)

    def test_duration_is_climate_screen_only(self):
        fig = go.Figure(go.Scatter(x=[1, 2], y=[26., 10.]))
        value = temperature_figure_interpretation(self.df, fig, "duration")
        self.assertIn("without preserving chronology", value)
        self.assertIn("P05", value)
        self.assertIn("seasonal envelope and passive-control priorities", value)

    def test_amplitude_explicitly_distinguishes_period_lengths(self):
        fig = go.Figure(go.Scatter(x=["W01", "W02"], y=[7., 19.]))
        value = temperature_figure_interpretation(
            self.df, fig, "amplitude", title="Amplitude · Weekly"
        )
        self.assertIn("weekly amplitude", value)
        self.assertIn("19.0 K at W02", value)
        self.assertIn("longer aggregation amplitudes", value)

    def test_occurrence_reports_actual_dominant_class(self):
        fig = go.Figure()
        fig.add_bar(x=["Jan", "Feb"], y=[40., 20.], name="< 15 °C")
        fig.add_bar(x=["Jan", "Feb"], y=[5., 3.], name="≥ 25 °C")
        value = temperature_figure_interpretation(
            self.df, fig, "occurrence", title="Temperature occurrence · Hours"
        )
        self.assertIn("most frequent plotted temperature class is < 15 °C", value)
        self.assertIn("mutually exclusive", value)

    def test_degree_day_is_not_degree_hour_equivalent(self):
        fig = go.Figure()
        fig.add_bar(x=["Jan"], y=[42.], name="Heating degree-days (HGT)")
        fig.add_bar(x=["Jan"], y=[11.], name="Cooling degree-days (KGT)")
        value = temperature_figure_interpretation(
            self.df, fig, "degree", title="Degree-days · Monthly"
        )
        self.assertIn("42.0 K·d", value)
        self.assertIn("daily mean outdoor temperatures", value)
        self.assertIn("climatic temperature sums", value)

    def test_overnight_calendar_boundary_is_correct(self):
        warm = (self.df.index >= pd.Timestamp("2026-07-01 20:00")) & (
            self.df.index <= pd.Timestamp("2026-07-02 06:00")
        )
        self.df.loc[warm, "dry_bulb_temperature_c"] = 21.
        value = temperature_interpretation(self.df, 18., 26.)
        self.assertIn("overnight periods with sampled night minimum ≥20 °C: 1", value)
        self.assertIn("prolonged warm nights", value)


if __name__ == "__main__":
    unittest.main()
