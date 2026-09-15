from __future__ import annotations

import ast
from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.degree_metrics import degree_metric_table


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class DegreeMetricCalculationTests(unittest.TestCase):
    def test_hgt_kgt_use_independent_indoor_and_limit_temperatures(self) -> None:
        index = pd.date_range("2026-01-01 00:00", periods=4, freq="h")
        df = pd.DataFrame({"dry_bulb_temperature_c": [10.0, 15.0, 19.0, 22.0]}, index=index)
        table = degree_metric_table(
            df,
            heating_indoor_c=20.0,
            heating_limit_c=12.0,
            cooling_indoor_c=20.0,
            cooling_limit_c=18.3,
            metric="Degree-hours",
            aggregation="Daily",
            interval_minutes=60,
        )
        self.assertAlmostEqual(float(table["Heating degree-hours (HGT)"].sum()), 10.0)
        self.assertAlmostEqual(float(table["Cooling degree-hours (KGT)"].sum()), 1.0)
        self.assertEqual(table.attrs["heating_notation"], "HGT 20/12")
        self.assertEqual(table.attrs["cooling_notation"], "KGT 20/18.3")

    def test_all_four_inputs_have_independent_effects(self) -> None:
        index = pd.date_range("2026-01-01 00:00", periods=4, freq="h")
        df = pd.DataFrame({"dry_bulb_temperature_c": [10.0, 13.0, 19.0, 22.0]}, index=index)

        def calc(**overrides):
            args = dict(
                heating_indoor_c=20.0,
                heating_limit_c=12.0,
                cooling_indoor_c=20.0,
                cooling_limit_c=18.3,
                metric="Degree-hours",
                aggregation="Daily",
            )
            args.update(overrides)
            return degree_metric_table(df, **args)

        base = calc()
        h = "Heating degree-hours (HGT)"
        c = "Cooling degree-hours (KGT)"
        self.assertNotEqual(float(base[h].sum()), float(calc(heating_indoor_c=21.0)[h].sum()))
        self.assertNotEqual(float(base[h].sum()), float(calc(heating_limit_c=14.0)[h].sum()))
        self.assertNotEqual(float(base[c].sum()), float(calc(cooling_indoor_c=21.0)[c].sum()))
        self.assertNotEqual(float(base[c].sum()), float(calc(cooling_limit_c=20.0)[c].sum()))

    def test_degree_days_use_daily_mean_and_four_input_selection(self) -> None:
        index = pd.date_range("2026-01-01 00:00", periods=4 * 24, freq="h")
        values = [10.0] * 24 + [15.0] * 24 + [19.0] * 24 + [22.0] * 24
        df = pd.DataFrame({"dry_bulb_temperature_c": values}, index=index)
        table = degree_metric_table(
            df,
            heating_indoor_c=20.0,
            heating_limit_c=12.0,
            cooling_indoor_c=20.0,
            cooling_limit_c=18.3,
            metric="Degree-days",
            aggregation="Daily",
        )
        self.assertAlmostEqual(float(table["Heating degree-days (HGT)"].sum()), 10.0)
        self.assertAlmostEqual(float(table["Cooling degree-days (KGT)"].sum()), 1.0)

    def test_degree_days_are_not_degree_hours_divided_by_24(self) -> None:
        index = pd.date_range("2026-01-01 00:00", periods=24, freq="h")
        df = pd.DataFrame({"dry_bulb_temperature_c": [10.0] * 12 + [30.0] * 12}, index=index)
        hours = degree_metric_table(
            df,
            heating_indoor_c=20.0,
            heating_limit_c=12.0,
            cooling_indoor_c=20.0,
            cooling_limit_c=18.3,
            metric="Degree-hours",
            aggregation="Daily",
        )
        days = degree_metric_table(
            df,
            heating_indoor_c=20.0,
            heating_limit_c=12.0,
            cooling_indoor_c=20.0,
            cooling_limit_c=18.3,
            metric="Degree-days",
            aggregation="Daily",
        )
        self.assertAlmostEqual(float(hours["Heating degree-hours (HGT)"].sum()), 120.0)
        self.assertAlmostEqual(float(days["Heating degree-days (HGT)"].sum()), 0.0)
        self.assertNotAlmostEqual(
            float(hours["Heating degree-hours (HGT)"].sum()) / 24.0,
            float(days["Heating degree-days (HGT)"].sum()),
        )

    def test_ten_minute_source_cadence_scales_degree_hours(self) -> None:
        index = pd.date_range("2026-01-01 00:00", periods=6, freq="10min")
        df = pd.DataFrame({"dry_bulb_temperature_c": [10.0] * 6}, index=index)
        df.attrs["canonical_native_interval_minutes"] = 10
        table = degree_metric_table(
            df,
            heating_indoor_c=20.0,
            heating_limit_c=12.0,
            cooling_indoor_c=20.0,
            cooling_limit_c=18.3,
            metric="Degree-hours",
            aggregation="Daily",
        )
        self.assertAlmostEqual(float(table["Heating degree-hours (HGT)"].sum()), 10.0)

    def test_heating_limit_above_heating_indoor_reference_fails_closed(self) -> None:
        df = pd.DataFrame(
            {"dry_bulb_temperature_c": [20.0]},
            index=pd.DatetimeIndex(["2026-01-01 00:00"]),
        )
        with self.assertRaisesRegex(ValueError, "Heating limit"):
            degree_metric_table(
                df,
                heating_indoor_c=20.0,
                heating_limit_c=21.0,
                cooling_indoor_c=20.0,
                cooling_limit_c=18.3,
                metric="Degree-days",
                aggregation="Daily",
            )

    def test_degree_metrics_support_all_display_aggregations(self) -> None:
        index = pd.date_range("2026-01-01 00:00", "2026-12-31 23:00", freq="h")
        df = pd.DataFrame({"dry_bulb_temperature_c": [10.0] * len(index)}, index=index)
        for aggregation in ("Daily", "Weekly", "Monthly", "Seasonal", "Annual"):
            table = degree_metric_table(
                df,
                heating_indoor_c=20.0,
                heating_limit_c=12.0,
                cooling_indoor_c=20.0,
                cooling_limit_c=18.3,
                metric="Degree-days",
                aggregation=aggregation,
            )
            self.assertFalse(table.empty, aggregation)
            self.assertAlmostEqual(float(table["Heating degree-days (HGT)"].sum()), 10.0 * 365.0)


class DegreeMetricUiContractTests(unittest.TestCase):
    def test_degree_days_ui_exposes_four_temperatures_method_and_aggregation(self) -> None:
        source = APP.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_temperature"
        )
        text = ast.get_source_segment(source, function) or ""
        for label in (
            "Heating indoor air temperature [°C]",
            "Heating limit [°C]",
            "Cooling indoor air temperature [°C]",
            "Cooling limit [°C]",
        ):
            self.assertIn(label, text)
        self.assertIn("20.0", text)
        self.assertIn("12.0", text)
        self.assertIn("18.3", text)
        self.assertIn("HGT", text)
        self.assertIn("KGT", text)
        self.assertIn("Degree-hours", text)
        self.assertIn("Degree-days", text)
        self.assertIn("Annual", text)
        self.assertIn("degree_metric_table", text)
        self.assertNotIn("Heating base/reference temperature [°C]", text)
        self.assertNotIn("Cooling base/reference temperature [°C]", text)


if __name__ == "__main__":
    unittest.main()
