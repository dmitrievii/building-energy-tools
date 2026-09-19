from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd
import psychrolib

from epw_climate_analyzer.chart_theme import climate_color_map, rgba
from epw_climate_analyzer.comparison import ClimateDataset, psychrometric_comparison_chart

psychrolib.SetUnitSystem(psychrolib.SI)


class PsychrometricComparisonOverlays0745Tests(unittest.TestCase):
    def _climate(self, climate_id: str, name: str, temperature_shift: float) -> ClimateDataset:
        index = pd.date_range("2025-01-01", periods=96, freq="h")
        phase = np.linspace(0.0, 4.0 * np.pi, len(index))
        temperature = 20.0 + temperature_shift + 8.0 * np.sin(phase)
        rh = 52.0 + 24.0 * np.cos(phase * 0.75)
        pressure = 93000.0 + (1500.0 if temperature_shift > 0 else 0.0)
        humidity_ratio: list[float] = []
        enthalpy: list[float] = []
        for t_c, rh_pct in zip(temperature, rh, strict=True):
            w = psychrolib.GetHumRatioFromRelHum(float(t_c), float(rh_pct) / 100.0, pressure)
            humidity_ratio.append(w * 1000.0)
            enthalpy.append(psychrolib.GetMoistAirEnthalpy(float(t_c), w) / 1000.0)
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": temperature,
                "relative_humidity_pct": rh,
                "humidity_ratio_g_kg": humidity_ratio,
                "moist_air_enthalpy_kj_kg": enthalpy,
                "atmospheric_station_pressure_pa": pressure,
            },
            index=index,
        )
        frame.attrs["canonical_native_interval_minutes"] = 60.0
        location = SimpleNamespace(
            elevation_m=500.0,
            city=name,
            country="Test",
            latitude=47.0,
            longitude=15.0,
        )
        epw = SimpleNamespace(location=location)
        return ClimateDataset(climate_id, name, "test", epw, frame, [])

    def test_compare_ui_exposes_givoni_and_heat_index_toggles(self) -> None:
        source = Path("tools/climate_analyzer/app.py").read_text(encoding="utf-8")
        self.assertIn('key="compare_psych_show_givoni"', source)
        self.assertIn('key="compare_psych_show_heat_index"', source)
        self.assertIn("show_givoni_overlay=show_givoni", source)
        self.assertIn("show_heat_index_overlay=show_heat_index", source)

    def test_contour_lines_use_climate_hue_not_plotly_contour_colorscale(self) -> None:
        climates = [
            self._climate("a", "Climate A", -2.0),
            self._climate("b", "Climate B", 3.0),
        ]
        colors = climate_color_map([climate.display_name for climate in climates])
        figure = psychrometric_comparison_chart(
            climates,
            data_display="Climate contour",
            zone_interior_style="Contour only",
            zone_coverage=0.90,
            additional_contour_coverages=[0.50, 0.70],
            reference_pressure_pa=95000.0,
        )
        contour_traces = [
            trace
            for trace in figure.data
            if trace.type == "contour" and ("zone" in str(trace.name) or "contour" in str(trace.name))
        ]
        self.assertGreaterEqual(len(contour_traces), 6)
        for trace in contour_traces:
            self.assertEqual(trace.contours.coloring, "none")
            climate_name = "Climate A" if str(trace.name).startswith("Climate A") else "Climate B"
            expected_alpha = 0.98 if str(trace.name).endswith("% zone") else 0.78
            self.assertEqual(trace.line.color, rgba(colors[climate_name], expected_alpha))

    def test_common_pressure_overlays_are_available_without_mutating_sources(self) -> None:
        climates = [
            self._climate("a", "Climate A", -2.0),
            self._climate("b", "Climate B", 3.0),
        ]
        before = [climate.data["humidity_ratio_g_kg"].copy() for climate in climates]
        figure = psychrometric_comparison_chart(
            climates,
            chart_type="T-d",
            data_display="Points",
            reference_pressure_pa=90000.0,
            show_givoni_overlay=True,
            show_heat_index_overlay=True,
        )
        self.assertTrue(
            any(str(getattr(trace, "legendgroup", "")).startswith("givoni_zone_") for trace in figure.data)
        )
        self.assertTrue(any(str(trace.name).startswith("Heat index ") for trace in figure.data))
        self.assertIsNotNone(figure.layout.legend2)
        self.assertEqual(tuple(figure.layout.xaxis.domain), (0.0, 0.72))
        for climate, original in zip(climates, before, strict=True):
            pd.testing.assert_series_equal(climate.data["humidity_ratio_g_kg"], original)


if __name__ == "__main__":
    unittest.main()
