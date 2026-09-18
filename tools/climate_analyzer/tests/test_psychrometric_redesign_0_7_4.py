from __future__ import annotations

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
