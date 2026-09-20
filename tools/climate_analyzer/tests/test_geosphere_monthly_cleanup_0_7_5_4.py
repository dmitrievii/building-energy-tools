from __future__ import annotations

import inspect
import unittest

import pandas as pd

from epw_climate_analyzer import chart_theme, timeseries
from epw_climate_analyzer.source_parity_monthly_catalogue import decorate_monthly_parameter_table
from epw_climate_analyzer.source_parity_monthly_cleanup import (
    MONTHLY_GENERIC_AGGREGATIONS,
    _forward_monthly_overlay,
    describe_monthly_parameter,
    monthly_semantics_from_column,
    semantic_analysis_column,
)
from epw_climate_analyzer.source_parity_monthly_visual_contract import monthly_metric_color
from epw_climate_analyzer.source_parity_longterm_followup import temperature_gradient_colorscale


class _NoMetadataParity:
    pass


class _OverlayProbe:
    def __init__(self) -> None:
        self.calls: list[pd.DataFrame] = []

    def render_time_series_overlay(self, frame: pd.DataFrame) -> None:
        self.calls.append(frame)


class GeoSphereMonthlyCleanupTests(unittest.TestCase):
    def test_monthly_and_annual_are_the_only_generic_periods(self) -> None:
        self.assertEqual(MONTHLY_GENERIC_AGGREGATIONS, ("Monthly", "Annual"))

    def test_recommended_core_parameter_has_explicit_statistic_semantics(self) -> None:
        descriptor = describe_monthly_parameter(
            "tl_mittel",
            "Lufttemperatur Monatsmittel",
            "Monatsmittel der Lufttemperatur",
            "°C",
        )
        self.assertTrue(descriptor.recommended)
        self.assertEqual(descriptor.category, "Temperature")
        self.assertEqual(descriptor.annual_semantics, "mean")
        self.assertEqual(descriptor.statistic, "Monthly mean")
        self.assertIn("monthly mean", descriptor.label.lower())

    def test_term_three_is_advanced_and_explains_historical_schedule(self) -> None:
        descriptor = describe_monthly_parameter(
            "tl_termin_iii",
            "Lufttemperatur Termin III",
            "Monatsmittel am Klima-Beobachtungstermin III",
            "°C",
        )
        self.assertFalse(descriptor.recommended)
        self.assertEqual(descriptor.annual_semantics, "mean")
        self.assertIn("Term III", descriptor.statistic)
        self.assertIn("21:00", descriptor.note)
        self.assertIn("19:00", descriptor.note)
        self.assertIn("MOZ", descriptor.note)
        self.assertIn("MEZ", descriptor.note)

    def test_parameter_table_keeps_provider_key_but_uses_human_label(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "Selected": False,
                    "Measured variable": "Lufttemperatur Termin III",
                    "Provider": "tl_termin_iii",
                    "Unit": "°C",
                    "Availability": "Resource-supported",
                    "Canonical field": "tl_termin_iii",
                }
            ]
        )
        decorated = decorate_monthly_parameter_table(_NoMetadataParity(), source)
        self.assertEqual(decorated.loc[0, "Provider"], "tl_termin_iii")
        self.assertEqual(decorated.loc[0, "Original GeoSphere name"], "Lufttemperatur Termin III")
        self.assertEqual(decorated.loc[0, "Category"], "Temperature")
        self.assertIn("Term III", decorated.loc[0, "Statistic"])
        self.assertFalse(bool(decorated.loc[0, "_recommended"]))

    def test_synthetic_semantics_are_machine_readable(self) -> None:
        descriptor = describe_monthly_parameter(
            "tage_frost",
            "Frosttage",
            "Anzahl Frosttage im Monat",
            "d",
        )
        column = semantic_analysis_column("tage_frost", descriptor)
        self.assertEqual(monthly_semantics_from_column(column), "sum")

    def test_calendar_month_is_not_treated_as_fixed_30_day_upsampling(self) -> None:
        index = pd.date_range("2024-01-01", periods=12, freq="MS")
        frame = pd.DataFrame(
            {"liquid_precipitation_depth_mm": [1.0] * 12},
            index=index,
        )
        frame.attrs["canonical_native_resolution"] = "monthly"
        monthly = timeseries.aggregate_series(
            frame,
            "liquid_precipitation_depth_mm",
            "Monthly",
            pd.Timestamp("2024-01-01"),
            pd.Timestamp("2025-01-01"),
        )
        self.assertEqual(len(monthly), 12)
        self.assertEqual(monthly.iloc[0]["interval_end"], pd.Timestamp("2024-02-01"))
        self.assertEqual(monthly.iloc[1]["interval_end"], pd.Timestamp("2024-03-01"))

    def test_annual_overlay_uses_quantity_semantics(self) -> None:
        index = pd.date_range("2024-01-01", periods=12, freq="MS")
        frame = pd.DataFrame(
            {
                "liquid_precipitation_depth_mm": [1.0] * 12,
                "dry_bulb_temperature_min_c": list(range(12)),
                "dry_bulb_temperature_max_c": list(range(12)),
            },
            index=index,
        )
        frame.attrs["canonical_native_resolution"] = "monthly"
        start, end = pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01")

        precipitation = timeseries.aggregate_series(frame, "liquid_precipitation_depth_mm", "Annual", start, end)
        minimum = timeseries.aggregate_series(frame, "dry_bulb_temperature_min_c", "Annual", start, end)
        maximum = timeseries.aggregate_series(frame, "dry_bulb_temperature_max_c", "Annual", start, end)

        self.assertEqual(float(precipitation.iloc[0]["value"]), 12.0)
        self.assertEqual(float(minimum.iloc[0]["value"]), 0.0)
        self.assertEqual(float(maximum.iloc[0]["value"]), 11.0)

    def test_monthly_overlay_route_forwards_to_shared_renderer(self) -> None:
        probe = _OverlayProbe()
        frame = pd.DataFrame({"x": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2024-01-01")]))
        _forward_monthly_overlay(probe, frame, ["ignored"])
        self.assertEqual(len(probe.calls), 1)
        self.assertIs(probe.calls[0], frame)
        self.assertNotIn("go.Scatter", inspect.getsource(_forward_monthly_overlay))

    def test_monthly_semantic_colours_follow_shared_physical_families(self) -> None:
        fallback = chart_theme.metric_color
        self.assertEqual(
            monthly_metric_color("monthly__mean__temperature__x", fallback),
            fallback("dry_bulb_temperature_c"),
        )
        self.assertEqual(
            monthly_metric_color("monthly__mean__humidity_and_psychrometrics__x", fallback),
            fallback("relative_humidity_pct"),
        )
        self.assertEqual(
            monthly_metric_color("monthly__mean__wind_and_ventilation__x", fallback),
            fallback("wind_speed_m_s"),
        )
        self.assertEqual(
            monthly_metric_color("monthly__sum__precipitation_and_snow__x", fallback),
            fallback("liquid_precipitation_depth_mm"),
        )
        self.assertEqual(
            monthly_metric_color("monthly__mean__sky_and_daylight__cloud_x", fallback),
            fallback("total_sky_cover_tenths"),
        )
        self.assertEqual(
            monthly_metric_color("monthly__sum__sky_and_daylight__sunshine_x", fallback),
            chart_theme.SOLAR_COMPONENT_COLORS["GHI"],
        )

    def test_temperature_heatmap_gradient_distinguishes_cold_values(self) -> None:
        scale = temperature_gradient_colorscale([-10.0, 10.0, 20.0, 30.0], (18.0, 26.0))
        blue_colours = [str(item[1]) for item in scale if "blue" in str(item[1]).lower() or str(item[1]).lower() in {"#172554", "#2563eb", "#bfdbfe"}]
        self.assertGreaterEqual(len(set(blue_colours)), 2)


if __name__ == "__main__":
    unittest.main()
