from __future__ import annotations

import ast
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from epw_climate_analyzer.precipitation import (
    aggregate_liquid_precipitation,
    occurrence_hours,
    occurrence_records,
)
from epw_climate_analyzer.ui_contract import NAVIGATION_LABELS, NAVIGATION_PAGES

TOOL_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = TOOL_ROOT / "app.py"


class PressureAndPrecipitationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_epw_station_pressure_is_the_default_ui_mode(self) -> None:
        # The physical default is still specified by the EPW route, now
        # through a contextual selector rather than a global sidebar widget.
        matches = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "pressure_selection" or len(node.args)<3:
                continue
            try:
                options=ast.literal_eval(node.args[2])
            except (ValueError,TypeError):
                continue
            if "EPW station pressure with fallback median" in options:
                matches.append((node,options))
        self.assertEqual(len(matches),1)
        node,options=matches[0]
        keywords={kw.arg:ast.literal_eval(kw.value) for kw in node.keywords if kw.arg in ("source","default")}
        self.assertEqual(keywords["source"],"epw")
        self.assertEqual(options[keywords["default"]],"EPW station pressure with fallback median")
        from epw_climate_analyzer.sidebar_layout import pressure_selection
        from unittest.mock import Mock
        ui=Mock()
        ui.session_state={}
        mode,custom=pressure_selection(ui,"Temperature",options,source="epw",default=keywords["default"])
        self.assertEqual(mode,"EPW station pressure with fallback median")
        self.assertIsNone(custom)
        ui.selectbox.assert_not_called()
        self.assertIn("atmospheric station pressure stored in the EPW", self.source)
        self.assertIn("hourly EPW station values; fallback median", self.source)

    def test_precipitation_has_a_first_class_navigation_page(self) -> None:
        self.assertIn("Precipitation and Snow", NAVIGATION_PAGES)
        self.assertEqual(NAVIGATION_LABELS["Precipitation and Snow"], "Climate — Precipitation & snow")
        self.assertIn('elif page == "Precipitation and Snow":', self.source)
        self.assertIn("render_precipitation(filtered_df)", self.source)

    def test_liquid_precipitation_accumulation_stays_in_dedicated_totals_route(self) -> None:
        function = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "render_precipitation"
        )
        source = ast.get_source_segment(self.source, function) or ""
        # The dedicated precipitation totals route now delegates to the same
        # extensive-total panel used by the Atlas and standard report.
        self.assertIn('extensive_total_panel(df,render_plot,columns=("liquid_precipitation_depth_mm",))', source)
        from epw_climate_analyzer.residual_findings import extensive_total_figure
        for period in ("Monthly", "Weekly", "Daily", "Seasonal", "Annual"):
            with self.subTest(period=period):
                df = self._fixture()
                expected = aggregate_liquid_precipitation(df, period)
                figure, interpretation = extensive_total_figure(df, "liquid_precipitation_depth_mm", period)
                np.testing.assert_allclose(np.asarray(figure.data[0].y, dtype=float),
                                           expected.iloc[:, 0].to_numpy(dtype=float),
                                           rtol=1e-12, atol=1e-12)
                self.assertTrue(interpretation.strip())
        self.assertIn('"Precipitation totals"', source)
        self.assertIn('["Snow depth"]', source)
        self.assertNotIn('column.endswith("_mm")', self.source)

    def _fixture(self) -> pd.DataFrame:
        index = pd.to_datetime(
            [
                "2026-01-31 22:00",
                "2026-01-31 23:00",
                "2026-02-01 00:00",
                "2026-02-01 01:00",
                "2026-02-01 02:00",
            ]
        )
        return pd.DataFrame(
            {
                "liquid_precipitation_depth_mm": [1.0, 2.0, np.nan, 4.0, 0.0],
                "snow_depth_cm": [0.0, 1.0, np.nan, 3.0, 0.0],
                "season": ["Winter"] * 5,
            },
            index=index,
        )

    def test_precipitation_totals_sum_valid_records_and_preserve_missingness(self) -> None:
        totals = aggregate_liquid_precipitation(self._fixture(), "Monthly")
        self.assertAlmostEqual(float(totals.iloc[0, 0]), 3.0)
        self.assertAlmostEqual(float(totals.iloc[1, 0]), 4.0)

        missing = self._fixture().copy()
        missing["liquid_precipitation_depth_mm"] = np.nan
        self.assertTrue(aggregate_liquid_precipitation(missing, "Monthly").empty)

    def test_occurrence_counts_do_not_treat_missing_as_events(self) -> None:
        df = self._fixture()
        wet = occurrence_records(df, "liquid_precipitation_depth_mm", 0.1, "Monthly")
        self.assertEqual(float(wet.iloc[0, 0]), 2.0)
        self.assertEqual(float(wet.iloc[1, 0]), 1.0)
        snow = occurrence_hours(df, "snow_depth_cm", 0.0, "Monthly", inclusive=False)
        self.assertEqual(float(snow.iloc[0, 0]), 1.0)
        self.assertEqual(float(snow.iloc[1, 0]), 1.0)

    def test_liquid_precipitation_explorer_never_mixes_period_sum_with_record_min_max(self) -> None:
        function = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "render_generic_variable_page"
        )
        source = ast.get_source_segment(self.source, function) or ""
        self.assertIn('if column == "liquid_precipitation_depth_mm" and chart_type in', source)
        self.assertIn("render_profile_controls(df,column,unit",source)
        self.assertNotIn("extensive=extensive",source)
        # The consolidated explorer allows interval statistics and totals as
        # separate representations. A ribbon must use interval mean, not total.
        from epw_climate_analyzer.charts import time_series_profile_chart
        from epw_climate_analyzer.aggregations import profile_representation_options
        df=self._fixture();column="liquid_precipitation_depth_mm"
        options=profile_representation_options(df,column,"Monthly")
        self.assertIn("Total",options)
        self.assertIn("Min–mean–max",options)
        ribbon=time_series_profile_chart(df,column,"Monthly","test","mm","Min–mean–max")
        self.assertEqual({t.name for t in ribbon.data},{"Minimum","Mean","Maximum"})
        np.testing.assert_allclose(next(t.y for t in ribbon.data if t.name=="Mean"),[1.5,2.])
        total=time_series_profile_chart(df,column,"Monthly","test","mm","Total")
        np.testing.assert_allclose(total.data[0].y,[3.,4.])

    def test_precipitation_page_uses_chart_first_layout_without_kpi_strip(self) -> None:
        function = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "render_precipitation"
        )
        source = ast.get_source_segment(self.source, function) or ""
        self.assertNotIn(".metric(", source)
        self.assertNotIn("metric_cols", source)
        self.assertNotIn("Max precipitation record", source)
        self.assertNotIn("Max snow depth", source)
        self.assertIn('chart_group = st.selectbox("Analysis type", options)', source)


if __name__ == "__main__":
    unittest.main()
