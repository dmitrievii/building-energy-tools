from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import psychrolib

from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.psychrometric_distribution import add_climate_zone_traces, psychrometric_density_field
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties

psychrolib.SetUnitSystem(psychrolib.SI)
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def sample_frame() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=24 * 40, freq="h")
    phase = np.linspace(0.0, 8.0 * np.pi, len(index))
    t = 16.0 + 12.0 * np.sin(phase)
    rh = np.clip(68.0 + 26.0 * np.cos(phase * 0.73), 10.0, 99.0)
    pressure = np.full(len(index), 94000.0)
    base = pd.DataFrame(
        {
            "dry_bulb_temperature_c": t,
            "relative_humidity_pct": rh,
            "atmospheric_station_pressure_pa": pressure,
            "month_index": index.month,
            "month_name": index.strftime("%b"),
            "hour_of_day": index.hour,
        },
        index=index,
    )
    base.attrs["native_interval_minutes"] = 60.0
    return add_psychrometric_properties(base, fallback_pressure_pa=94000.0)


class PsychrometricRepresentation0743Tests(unittest.TestCase):
    def test_distribution_grid_is_restored_as_peer_representation(self) -> None:
        frame = sample_frame()
        fig = psychrometric_chart(
            frame,
            data_mode="Distribution grid",
            pressure_pa=94000.0,
            color_mode="Frequency",
            color_metric_column=None,
            color_metric_label="Frequency [h]",
        )
        filled = [trace for trace in fig.data if getattr(trace, "fill", None) == "toself"]
        self.assertGreater(len(filled), 5)
        self.assertTrue(any(getattr(getattr(trace, "marker", None), "showscale", False) for trace in fig.data))

    def test_smoothed_density_is_zero_above_saturation_curve(self) -> None:
        frame = sample_frame()
        field = psychrometric_density_field(frame, chart_type="T-d", target_share=0.90, pressure_pa=94000.0)
        for ix, t_c in enumerate(field.x):
            try:
                saturation = psychrolib.GetSatHumRatio(float(t_c), 94000.0) * 1000.0
            except Exception:
                continue
            impossible = field.y > saturation + max(1e-7, abs(saturation) * 1e-7)
            if impossible.any():
                self.assertTrue(np.allclose(field.mass_hours[ix, impossible], 0.0))

    def test_multiple_nested_contours_are_user_configurable(self) -> None:
        frame = sample_frame()
        fig = go.Figure()
        add_climate_zone_traces(
            fig,
            frame,
            chart_type="T-d",
            label="Test climate",
            color="#2563eb",
            coverage=0.90,
            interior_style="Contour only",
            additional_coverages=[0.50, 0.70],
            pressure_pa=94000.0,
        )
        names = [str(getattr(trace, "name", "")) for trace in fig.data]
        self.assertTrue(any("50% contour" in name for name in names))
        self.assertTrue(any("70% contour" in name for name in names))
        self.assertTrue(any("90% zone" in name for name in names))

    def test_app_exposes_points_grid_and_contour_without_fixed_core_checkbox(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('["Points", "Distribution grid", "Climate contour"]', source)
        self.assertIn('["Climate contour", "Distribution grid", "Points"]', source)
        self.assertIn('"Additional contour levels [%]"', source)
        self.assertNotIn('"Show 50% core contour"', source)
        self.assertIn('"Distribution grid"', source)


if __name__ == "__main__":
    unittest.main()
