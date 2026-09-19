from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd
import psychrolib

from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.comparison import ClimateDataset, psychrometric_comparison_chart
from epw_climate_analyzer.psychrometric_distribution import psychrometric_axis_ranges, psychrometric_density_field
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis

psychrolib.SetUnitSystem(psychrolib.SI)
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
DIST = ROOT / "epw_climate_analyzer" / "psychrometric_distribution.py"


def _psych_frame(year: int = 2026, *, offset_c: float = 0.0, pressure_pa: float = 101325.0) -> pd.DataFrame:
    rng = np.random.default_rng(year)
    n = 720
    t = np.concatenate([
        rng.normal(8.0 + offset_c, 3.0, n // 3),
        rng.normal(19.0 + offset_c, 3.2, n // 3),
        rng.normal(28.0 + offset_c, 2.8, n - 2 * (n // 3)),
    ])
    rh = np.clip(72.0 - 0.9 * t + rng.normal(0.0, 8.0, n), 20.0, 98.0)
    index = pd.date_range(f"{year}-01-01", periods=n, freq="h")
    w = np.array([psychrolib.GetHumRatioFromRelHum(float(tt), float(rr) / 100.0, pressure_pa) for tt, rr in zip(t, rh, strict=True)])
    d = w * 1000.0
    h = np.array([psychrolib.GetMoistAirEnthalpy(float(tt), float(ww)) / 1000.0 for tt, ww in zip(t, w, strict=True)])
    frame = pd.DataFrame(
        {
            "dry_bulb_temperature_c": t,
            "relative_humidity_pct": rh,
            "humidity_ratio_g_kg": d,
            "moist_air_enthalpy_kj_kg": h,
            "atmospheric_station_pressure_pa": pressure_pa,
            "month_index": index.month,
            "month_name": index.strftime("%b"),
            "hour_of_day": index.hour,
        },
        index=index,
    )
    return with_time_basis(frame, CHRONOLOGICAL)


class PsychrometricRedesign0741Tests(unittest.TestCase):
    def test_zone_is_smooth_joint_density_with_requested_coverage(self) -> None:
        frame = _psych_frame()
        field = psychrometric_density_field(frame, target_share=0.90)
        self.assertGreater(field.threshold_hours, 0.0)
        self.assertGreaterEqual(field.achieved_share, 0.90)
        self.assertLess(field.achieved_share, 0.94)
        self.assertEqual(field.mass_hours.shape, (140, 120))
        self.assertFalse(hasattr(field, "selected_tiles"))
        self.assertGreater(np.count_nonzero((field.mass_hours > 0) & (field.mass_hours < field.max_mass_hours)), 100)

    def test_climate_zone_uses_contours_not_selected_cell_polygons(self) -> None:
        fig = psychrometric_chart(
            _psych_frame(),
            chart_type="T-d",
            show_comfort_zone=False,
            metric_layers=[],
            data_mode="Climate zone",
            zone_coverage=0.90,
            zone_interior_style="Density gradient",
        )
        contour_traces = [trace for trace in fig.data if trace.type == "contour"]
        self.assertGreaterEqual(len(contour_traces), 2)
        self.assertFalse(any(getattr(trace, "fill", None) == "toself" for trace in fig.data))
        self.assertIsNotNone(fig.layout.xaxis.range)
        self.assertIsNotNone(fig.layout.yaxis.range)

    def test_multiyear_compare_selected_years_draws_independent_zones_on_fixed_axes(self) -> None:
        frame = pd.concat([_psych_frame(2024), _psych_frame(2025, offset_c=1.5)])
        frame = with_time_basis(frame, CHRONOLOGICAL)
        fig = psychrometric_chart(
            frame,
            chart_type="T-d",
            show_comfort_zone=False,
            metric_layers=[],
            data_mode="Climate zone",
            year_mode="Compare selected years",
            selected_years=[2024, 2025],
        )
        legend_names = {str(trace.name) for trace in fig.data if trace.type == "scatter" and trace.showlegend}
        self.assertIn("2024", legend_names)
        self.assertIn("2025", legend_names)
        self.assertFalse(bool(fig.layout.xaxis.autorange))
        self.assertFalse(bool(fig.layout.yaxis.autorange))

    def test_reference_pressure_moves_all_comparison_coordinates_consistently(self) -> None:
        climate_a = _psych_frame(2026, pressure_pa=101325.0)
        climate_b = _psych_frame(2026, offset_c=3.0, pressure_pa=85000.0)
        climates = [
            ClimateDataset("a", "Climate A", "test", None, climate_a, []),
            ClimateDataset("b", "Climate B", "test", None, climate_b, []),
        ]
        sea = psychrometric_comparison_chart(climates, data_display="Points", reference_pressure_pa=101325.0)
        high = psychrometric_comparison_chart(climates, data_display="Points", reference_pressure_pa=85000.0)
        sea_points = {str(trace.name): trace for trace in sea.data if trace.type == "scattergl"}
        high_points = {str(trace.name): trace for trace in high.data if trace.type == "scattergl"}
        self.assertEqual(set(sea_points), {"Climate A", "Climate B"})
        self.assertEqual(set(high_points), {"Climate A", "Climate B"})
        for name in sea_points:
            np.testing.assert_allclose(np.asarray(sea_points[name].x, dtype=float), np.asarray(high_points[name].x, dtype=float))
            sea_y = np.asarray(sea_points[name].y, dtype=float)
            high_y = np.asarray(high_points[name].y, dtype=float)
            self.assertGreater(float(np.nanmean(high_y)), float(np.nanmean(sea_y)))
            self.assertFalse(np.allclose(sea_y, high_y))

    def test_comparison_has_one_shared_axis_and_climate_zone_identity(self) -> None:
        climates = [
            ClimateDataset("a", "Climate A", "test", None, _psych_frame(2026), []),
            ClimateDataset("b", "Climate B", "test", None, _psych_frame(2026, offset_c=4.0), []),
        ]
        fig = psychrometric_comparison_chart(climates, data_display="Climate zones")
        legend_names = {str(trace.name) for trace in fig.data if trace.type == "scatter" and trace.showlegend}
        self.assertEqual(legend_names, {"Climate A", "Climate B"})
        self.assertEqual(fig.layout.legend.title.text, "Climate")
        self.assertFalse(any(str(key).startswith("xaxis2") or str(key).startswith("yaxis2") for key in fig.layout))
        self.assertFalse(bool(fig.layout.xaxis.autorange))
        self.assertFalse(bool(fig.layout.yaxis.autorange))

    def test_shared_axis_helper_spans_all_climates(self) -> None:
        a = _psych_frame(2026)
        b = _psych_frame(2026, offset_c=8.0)
        (x0, x1), (y0, y1) = psychrometric_axis_ranges([a, b], "T-d")
        self.assertLessEqual(x0, float(min(a["dry_bulb_temperature_c"].min(), b["dry_bulb_temperature_c"].min())))
        self.assertGreaterEqual(x1, float(max(a["dry_bulb_temperature_c"].max(), b["dry_bulb_temperature_c"].max())))
        self.assertLessEqual(y0, float(min(a["humidity_ratio_g_kg"].min(), b["humidity_ratio_g_kg"].min())))
        self.assertGreaterEqual(y1, float(max(a["humidity_ratio_g_kg"].max(), b["humidity_ratio_g_kg"].max())))

    def test_ui_contract_removes_cell_90_and_exposes_zone_controls(self) -> None:
        source = APP.read_text(encoding="utf-8")
        distribution_source = DIST.read_text(encoding="utf-8")
        self.assertIn('["Points", "Distribution grid", "Climate contour"]', source)
        self.assertIn('["Climate contour", "Distribution grid", "Points"]', source)
        self.assertIn('"Outer contour coverage [%]"', source)
        self.assertIn('"Zone interior"', source)
        self.assertIn('"Density gradient"', source)
        self.assertIn('"Additional contour levels [%]"', source)
        self.assertNotIn('"Show 50% core contour"', source)
        self.assertIn('"Year display"', source)
        self.assertIn('"Compare selected years"', source)
        self.assertIn('"Reference psychrometric pressure"', source)
        self.assertNotIn("highest-density 1 °C × 5 %RH occupancy cells", source)
        self.assertNotIn("PsychrometricOccupancyEnvelope", distribution_source)
        self.assertNotIn("selected_tiles", distribution_source)


if __name__ == "__main__":
    unittest.main()
