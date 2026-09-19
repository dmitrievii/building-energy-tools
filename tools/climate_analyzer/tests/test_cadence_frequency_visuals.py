"""Regression contract for physical-hour semantics on sub-hourly climate data."""

from __future__ import annotations

import ast
import math
from pathlib import Path
import unittest

import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.aggregations import duration_curve
from epw_climate_analyzer.charts import (
    _add_psychrometric_tile_occupancy,
    duration_chart,
    givoni_milne_zone_table,
    histogram_chart,
)
from epw_climate_analyzer.psychrometric_distribution import psychrometric_density_field


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def sample_frame(*, interval_minutes: int) -> pd.DataFrame:
    freq = f"{interval_minutes}min"
    index = pd.date_range("2025-07-01T00:00:00Z", periods=6, freq=freq)
    df = pd.DataFrame(
        {
            "dry_bulb_temperature_c": [20.0, 21.0, 22.0, 23.0, 24.0, 25.0],
            "relative_humidity_pct": [50.0] * 6,
            "humidity_ratio_g_kg": [7.0] * 6,
            "month_index": [7] * 6,
        },
        index=index,
    )
    df.attrs["canonical_native_interval_minutes"] = interval_minutes
    return df


class CadenceFrequencyVisualTests(unittest.TestCase):
    def test_duration_curve_keeps_record_rank_but_adds_physical_hours(self) -> None:
        ten = duration_curve(sample_frame(interval_minutes=10), "dry_bulb_temperature_c")
        hourly = duration_curve(sample_frame(interval_minutes=60), "dry_bulb_temperature_c")
        self.assertEqual(ten["rank_hour"].tolist(), [1, 2, 3, 4, 5, 6])
        self.assertTrue(math.isclose(float(ten["duration_hours"].iloc[-1]), 1.0))
        self.assertTrue(math.isclose(float(hourly["duration_hours"].iloc[-1]), 6.0))

    def test_duration_chart_uses_physical_duration_axis(self) -> None:
        fig = duration_chart(sample_frame(interval_minutes=10), "dry_bulb_temperature_c", "Duration", "°C")
        x = list(fig.data[0].x)
        self.assertTrue(math.isclose(float(x[-1]), 1.0))
        self.assertEqual(fig.layout.xaxis.title.text, "Sorted duration [h]")
        self.assertIn("Sorted duration", str(fig.data[0].hovertemplate))

    def test_histogram_integrates_record_duration_in_hours(self) -> None:
        ten = histogram_chart(sample_frame(interval_minutes=10), "dry_bulb_temperature_c", "Histogram", "°C", bins=6)
        hourly = histogram_chart(sample_frame(interval_minutes=60), "dry_bulb_temperature_c", "Histogram", "°C", bins=6)
        self.assertEqual(ten.layout.yaxis.title.text, "Hours")
        self.assertEqual(ten.data[0].histfunc, "sum")
        self.assertTrue(math.isclose(sum(float(v) for v in ten.data[0].y), 1.0))
        self.assertTrue(math.isclose(sum(float(v) for v in hourly.data[0].y), 6.0))

    def test_psychrometric_frequency_tiles_report_physical_hours(self) -> None:
        fig = go.Figure()
        frame = sample_frame(interval_minutes=10)
        frame["dry_bulb_temperature_c"] = 22.0
        _add_psychrometric_tile_occupancy(
            fig,
            frame,
            "T-d",
            101325.0,
            None,
            None,
            None,
        )
        tile_traces = [trace for trace in fig.data if getattr(trace, "hovertemplate", None) and "Hours:" in str(trace.hovertemplate)]
        self.assertEqual(len(tile_traces), 1)
        total = 0.0
        for trace in tile_traces:
            marker = "Hours: "
            text = str(trace.hovertemplate)
            value = text.split(marker, 1)[1].split("<br>", 1)[0]
            total += float(value)
        self.assertTrue(math.isclose(total, 1.0, abs_tol=1e-9))

    def test_psychrometric_climate_zone_density_is_duration_weighted(self) -> None:
        ten = psychrometric_density_field(sample_frame(interval_minutes=10), target_share=0.90, grid_shape=(32, 32))
        hourly = psychrometric_density_field(sample_frame(interval_minutes=60), target_share=0.90, grid_shape=(32, 32))
        self.assertTrue(math.isclose(ten.total_hours, 1.0, abs_tol=1e-9))
        self.assertTrue(math.isclose(hourly.total_hours, 6.0, abs_tol=1e-9))
        self.assertGreaterEqual(ten.achieved_share, 0.90)
        self.assertGreaterEqual(hourly.achieved_share, 0.90)

    def test_givoni_zone_hours_scale_with_native_cadence(self) -> None:
        ten = givoni_milne_zone_table(sample_frame(interval_minutes=10)).set_index("zone")
        hourly = givoni_milne_zone_table(sample_frame(interval_minutes=60)).set_index("zone")
        self.assertEqual(set(ten.index), set(hourly.index))
        for zone in ten.index:
            self.assertTrue(
                math.isclose(float(ten.loc[zone, "hours"]) * 6.0, float(hourly.loc[zone, "hours"]), abs_tol=1e-9)
            )
            self.assertTrue(math.isclose(float(ten.loc[zone, "share_pct"]), float(hourly.loc[zone, "share_pct"]), abs_tol=1e-9))

    def test_psychrometric_ui_uses_three_representation_source_neutral_contract(self) -> None:
        source = APP.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('["Points", "Distribution grid", "Climate contour"]', source)
        self.assertIn('["Climate contour", "Distribution grid", "Points"]', source)
        self.assertIn('"Outer contour coverage [%]"', source)
        self.assertIn('"Zone interior"', source)
        self.assertIn('"Year display"', source)
        self.assertNotIn('data_mode != "Distributive grid"', source)
        self.assertNotIn('"Source interval values"', source)


if __name__ == "__main__":
    unittest.main()
