from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
import psychrolib

from epw_climate_analyzer.comparison import ClimateDataset, psychrometric_comparison_chart
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties

psychrolib.SetUnitSystem(psychrolib.SI)


def _same_state_frame(pressure_pa: float) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=240, freq="h")
    phase = np.linspace(0.0, 5.0 * np.pi, len(index))
    t = 14.0 + 10.0 * np.sin(phase)
    rh = np.clip(55.0 + 30.0 * np.cos(phase * 0.67), 8.0, 98.0)
    frame = pd.DataFrame(
        {
            "dry_bulb_temperature_c": t,
            "relative_humidity_pct": rh,
            "atmospheric_station_pressure_pa": pressure_pa,
            "month_index": index.month,
            "month_name": index.strftime("%b"),
            "hour_of_day": index.hour,
        },
        index=index,
    )
    frame.attrs["native_interval_minutes"] = 60.0
    return add_psychrometric_properties(frame, fallback_pressure_pa=pressure_pa)


class PsychrometricReferencePressure0743Tests(unittest.TestCase):
    def test_same_t_rh_states_overlay_after_projection_despite_different_source_pressures(self) -> None:
        sea_source = _same_state_frame(101325.0)
        mountain_source = _same_state_frame(82000.0)
        sea_before = sea_source["humidity_ratio_g_kg"].copy()
        mountain_before = mountain_source["humidity_ratio_g_kg"].copy()
        climates = [
            ClimateDataset("sea", "Sea source", "test", None, sea_source, []),
            ClimateDataset("mountain", "Mountain source", "test", None, mountain_source, []),
        ]
        fig = psychrometric_comparison_chart(
            climates, data_display="Points", reference_pressure_pa=95000.0
        )
        points = {str(trace.name): trace for trace in fig.data if trace.type == "scattergl"}
        np.testing.assert_allclose(
            np.asarray(points["Sea source"].x, dtype=float),
            np.asarray(points["Mountain source"].x, dtype=float),
            rtol=0.0, atol=1e-12,
        )
        np.testing.assert_allclose(
            np.asarray(points["Sea source"].y, dtype=float),
            np.asarray(points["Mountain source"].y, dtype=float),
            rtol=1e-12, atol=1e-12,
        )
        pd.testing.assert_series_equal(sea_source["humidity_ratio_g_kg"], sea_before)
        pd.testing.assert_series_equal(mountain_source["humidity_ratio_g_kg"], mountain_before)

    def test_contour_trace_has_no_numeric_density_above_100_percent_rh(self) -> None:
        source = _same_state_frame(85000.0)
        climate = ClimateDataset("a", "A", "test", None, source, [])
        reference_pressure = 93000.0
        fig = psychrometric_comparison_chart(
            [climate],
            data_display="Climate contour",
            reference_pressure_pa=reference_pressure,
            zone_interior_style="Contour only",
            zone_coverage=0.90,
            additional_contour_coverages=[0.50, 0.70],
        )
        zone = next(trace for trace in fig.data if trace.type == "contour" and "90% zone" in str(trace.name))
        x = np.asarray(zone.x, dtype=float)
        y = np.asarray(zone.y, dtype=float)
        z = np.asarray(zone.z, dtype=float)
        for ix, t_c in enumerate(x):
            saturation = psychrolib.GetSatHumRatio(float(t_c), reference_pressure) * 1000.0
            impossible = y > saturation + max(1e-8, abs(saturation) * 1e-8)
            if impossible.any():
                self.assertTrue(np.isnan(z[impossible, ix]).all())


if __name__ == "__main__":
    unittest.main()
