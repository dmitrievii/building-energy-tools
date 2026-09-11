from __future__ import annotations

import ast
from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.charts import GIVONI_MILNE_ZONES, GIVONI_ZONE_NAMES, psychrometric_chart


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


class Climate0103RegressionTests(unittest.TestCase):
    def test_catalog_cache_loaders_are_page_independent_local_imports(self) -> None:
        source = APP_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        expected = {
            "_cached_station_catalog_by_identity": "load_production_station_catalog",
            "cached_station_catalog": "load_station_catalog_manifest",
        }
        for function_name, imported_name in expected.items():
            with self.subTest(function=function_name):
                node = functions[function_name]
                local_imports = {
                    alias.name
                    for child in ast.walk(node)
                    if isinstance(child, ast.ImportFrom)
                    and child.module == "epw_climate_analyzer.catalog_runtime"
                    for alias in child.names
                }
                self.assertIn(imported_name, local_imports)

    def test_psychrometric_chart_is_responsive_and_legend_is_split_and_sorted(self) -> None:
        data = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [8.0, 18.0, 28.0],
                "humidity_ratio_g_kg": [3.0, 7.0, 11.0],
                "month_index": [12, 1, 2],
            }
        )
        fig = psychrometric_chart(
            data,
            chart_type="T-d",
            show_rh_curves=False,
            show_comfort_zone=True,
            metric_layers=[],
            shown_bioclimatic_zones=[GIVONI_ZONE_NAMES[3], GIVONI_ZONE_NAMES[1], GIVONI_ZONE_NAMES[2]],
            selected_months=[12, 2, 1],
            color_mode="Month",
        )

        self.assertTrue(fig.layout.autosize)
        self.assertIsNone(fig.layout.width)
        self.assertGreaterEqual(fig.layout.legend.font.size, 12)
        self.assertGreaterEqual(fig.layout.legend2.font.size, 12)
        self.assertEqual(fig.layout.legend.title.text, "Month")
        self.assertEqual(fig.layout.legend2.title.text, "Zones")

        month_traces = [
            trace
            for trace in fig.data
            if getattr(trace, "legendgroup", None) == "months" and trace.showlegend is not False
        ]
        self.assertEqual([trace.name for trace in month_traces], ["Jan", "Feb", "Dec"])
        self.assertTrue(all(getattr(trace, "legend", None) == "legend" for trace in month_traces))

        zone_traces = [
            trace
            for trace in fig.data
            if str(getattr(trace, "legendgroup", "")).startswith("givoni_zone_") and trace.showlegend is True
        ]
        self.assertTrue(all(getattr(trace, "legend", None) == "legend2" for trace in zone_traces))
        ordered_zone_ids = [
            int(trace.name.split(".", 1)[0])
            for trace in sorted(zone_traces, key=lambda trace: float(trace.legendrank))
        ]
        self.assertEqual(ordered_zone_ids, [1, 2, 3])

    def test_public_givoni_zone_options_are_numeric_order(self) -> None:
        zone_ids = [int(zone["zone_id"]) for zone in GIVONI_MILNE_ZONES]
        self.assertEqual(zone_ids, sorted(zone_ids))


if __name__ == "__main__":
    unittest.main()
