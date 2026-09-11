from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.chart_theme import (
    COOLING_COLOR,
    HEATING_COLOR,
    SOLAR_COMPONENT_COLORS,
    WIND_SPEED_COLOR_MAP,
    climate_color_map,
    metric_color,
)
from epw_climate_analyzer.charts import profile_ribbon_chart, stacked_monthly_bar, wind_rose_chart
from epw_climate_analyzer.comparison import hdd_cdd_grouped_chart, overlay_monthly_chart


def _hourly_frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=48, freq="h")
    return pd.DataFrame(
        {
            "dry_bulb_temperature_c": [float(i % 24) for i in range(48)],
            "global_horizontal_radiation_wh_m2": [max(0.0, 700.0 - abs((i % 24) - 12) * 100.0) for i in range(48)],
        },
        index=index,
    )


class SemanticChartColorTests(unittest.TestCase):
    def test_hourly_profiles_use_physical_variable_colors(self) -> None:
        frame = _hourly_frame()
        solar = profile_ribbon_chart(frame, "global_horizontal_radiation_wh_m2", "Hourly", "Solar", "Wh/m²")
        temp = profile_ribbon_chart(frame, "dry_bulb_temperature_c", "Hourly", "Temperature", "°C")

        self.assertEqual(solar.data[0].line.color, SOLAR_COMPONENT_COLORS["GHI"])
        self.assertEqual(temp.data[0].line.color, metric_color("dry_bulb_temperature_c"))
        self.assertNotEqual(solar.data[0].line.color, temp.data[0].line.color)

    def test_monthly_solar_components_are_grouped_not_stacked(self) -> None:
        monthly = pd.DataFrame(
            {
                "Global horizontal radiation": [100.0, 120.0],
                "Direct normal radiation": [80.0, 90.0],
                "Diffuse horizontal radiation": [40.0, 45.0],
            },
            index=pd.Index([1, 2], name="Month"),
        )
        fig = stacked_monthly_bar(monthly, "Monthly solar radiation components", "kWh/m²")

        self.assertEqual(fig.layout.barmode, "group")
        colors = {trace.name: trace.marker.color for trace in fig.data}
        self.assertEqual(colors["Global horizontal radiation"], SOLAR_COMPONENT_COLORS["GHI"])
        self.assertEqual(colors["Direct normal radiation"], SOLAR_COMPONENT_COLORS["DNI"])
        self.assertEqual(colors["Diffuse horizontal radiation"], SOLAR_COMPONENT_COLORS["DHI"])

    def test_heating_and_cooling_keep_engineering_service_colors(self) -> None:
        monthly = pd.DataFrame(
            {
                "Heating degree-hours": [100.0, 80.0],
                "Cooling degree-hours": [20.0, 30.0],
            },
            index=pd.Index([1, 2], name="Month"),
        )
        fig = stacked_monthly_bar(monthly, "Monthly heating and cooling degree-hours", "K·h")
        colors = {trace.name: trace.marker.color for trace in fig.data}

        self.assertEqual(fig.layout.barmode, "stack")
        self.assertEqual(colors["Heating degree-hours"], HEATING_COLOR)
        self.assertEqual(colors["Cooling degree-hours"], COOLING_COLOR)

    def test_hdd_cdd_comparison_uses_same_service_colors(self) -> None:
        metrics = pd.DataFrame(
            {
                "Climate": ["A", "B"],
                "HDD18 [K·h]": [100.0, 200.0],
                "CDD26 [K·h]": [50.0, 25.0],
            }
        )
        fig = hdd_cdd_grouped_chart(metrics)
        colors = {trace.name: trace.marker.color for trace in fig.data}

        self.assertEqual(colors["HDD18 [K·h]"], HEATING_COLOR)
        self.assertEqual(colors["CDD26 [K·h]"], COOLING_COLOR)

    def test_wind_rose_speed_bins_use_ordered_sequential_palette(self) -> None:
        frame = pd.DataFrame(
            {
                "wind_direction_deg": [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0],
                "wind_speed_m_s": [0.5, 1.5, 3.0, 5.0, 7.0, 10.0, 13.0],
            }
        )
        fig = wind_rose_chart(frame)
        colors = {trace.name: trace.marker.color for trace in fig.data}

        self.assertEqual(colors, WIND_SPEED_COLOR_MAP)

    def test_comparison_overlay_uses_stable_climate_identity_colors(self) -> None:
        table = pd.DataFrame(
            {"Graz": [1.0, 2.0], "Vienna": [2.0, 3.0], "Madrid": [3.0, 4.0]},
            index=pd.Index([1, 2], name="Month"),
        )
        fig = overlay_monthly_chart(table, "Monthly profile", "Value")
        expected = climate_color_map(table.columns)

        self.assertEqual({trace.name: trace.line.color for trace in fig.data}, expected)


if __name__ == "__main__":
    unittest.main()
