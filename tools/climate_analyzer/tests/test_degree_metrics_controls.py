from __future__ import annotations

import ast
from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.degree_metrics import degree_metric_table


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class DegreeMetricCalculationTests(unittest.TestCase):
    def test_degree_hours_use_selected_heating_and_cooling_bases(self) -> None:
        index = pd.date_range("2026-01-01 00:00", periods=3, freq="h")
        df = pd.DataFrame({"dry_bulb_temperature_c": [10.0, 20.0, 30.0]}, index=index)
        table = degree_metric_table(
            df,
            heating_base_c=18.0,
            cooling_base_c=26.0,
            metric="Degree-hours",
            aggregation="Daily",
            interval_minutes=60,
        )
        self.assertAlmostEqual(float(table["Heating degree-hours"].sum()), 8.0)
        self.assertAlmostEqual(float(table["Cooling degree-hours"].sum()), 4.0)

        changed = degree_metric_table(
            df,
            heating_base_c=20.0,
            cooling_base_c=28.0,
            metric="Degree-hours",
            aggregation="Daily",
            interval_minutes=60,
        )
        self.assertAlmostEqual(float(changed["Heating degree-hours"].sum()), 10.0)
        self.assertAlmostEqual(float(changed["Cooling degree-hours"].sum()), 2.0)

    def test_degree_days_use_daily_mean_not_degree_hours_divided_by_24(self) -> None:
        index = pd.date_range("2026-01-01 00:00", periods=24, freq="h")
        # Daily mean is 20 °C: HDD18 = 0 K·d. Hour-by-hour cold periods still
        # create 96 K·h, so simply dividing degree-hours by 24 would be wrong.
        df = pd.DataFrame(
            {"dry_bulb_temperature_c": [10.0] * 12 + [30.0] * 12},
            index=index,
        )
        hours = degree_metric_table(
            df,
            heating_base_c=18.0,
            cooling_base_c=26.0,
            metric="Degree-hours",
            aggregation="Daily",
        )
        days = degree_metric_table(
            df,
            heating_base_c=18.0,
            cooling_base_c=26.0,
            metric="Degree-days",
            aggregation="Daily",
        )
        self.assertAlmostEqual(float(hours["Heating degree-hours"].sum()), 96.0)
        self.assertAlmostEqual(float(days["Heating degree-days"].sum()), 0.0)
        self.assertAlmostEqual(float(days["Cooling degree-days"].sum()), 0.0)

    def test_ten_minute_source_cadence_scales_degree_hours(self) -> None:
        index = pd.date_range("2026-01-01 00:00", periods=6, freq="10min")
        df = pd.DataFrame({"dry_bulb_temperature_c": [17.0] * 6}, index=index)
        df.attrs["canonical_native_interval_minutes"] = 10
        table = degree_metric_table(
            df,
            heating_base_c=18.0,
            cooling_base_c=26.0,
            metric="Degree-hours",
            aggregation="Daily",
        )
        self.assertAlmostEqual(float(table["Heating degree-hours"].sum()), 1.0)

    def test_heating_base_above_cooling_base_fails_closed(self) -> None:
        df = pd.DataFrame(
            {"dry_bulb_temperature_c": [20.0]},
            index=pd.DatetimeIndex(["2026-01-01 00:00"]),
        )
        with self.assertRaisesRegex(ValueError, "must not exceed"):
            degree_metric_table(
                df,
                heating_base_c=27.0,
                cooling_base_c=25.0,
                metric="Degree-hours",
                aggregation="Daily",
            )

    def test_degree_metrics_support_daily_weekly_monthly_seasonal_and_annual_display_aggregation(self) -> None:
        index = pd.date_range("2026-01-01 00:00", "2026-12-31 23:00", freq="h")
        df = pd.DataFrame({"dry_bulb_temperature_c": [10.0] * len(index)}, index=index)
        for aggregation in ("Daily", "Weekly", "Monthly", "Seasonal", "Annual"):
            table = degree_metric_table(
                df,
                heating_base_c=18.0,
                cooling_base_c=26.0,
                metric="Degree-days",
                aggregation=aggregation,
            )
            self.assertFalse(table.empty, aggregation)
            self.assertAlmostEqual(float(table["Heating degree-days"].sum()), 8.0 * 365.0)


class DegreeMetricUiContractTests(unittest.TestCase):
    def test_degree_days_ui_exposes_reference_temperatures_method_and_aggregation(self) -> None:
        source = APP.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_temperature"
        )
        text = ast.get_source_segment(source, function) or ""
        self.assertIn("Heating base/reference temperature [°C]", text)
        self.assertIn("Cooling base/reference temperature [°C]", text)
        self.assertIn("Degree-hours", text)
        self.assertIn("Degree-days", text)
        self.assertIn("Annual", text)
        self.assertIn("degree_metric_table", text)
        self.assertNotIn('aggregate_sum(df, "heating_degree_hours_kh", "Monthly")', text)


if __name__ == "__main__":
    unittest.main()
