import ast
import unittest
from pathlib import Path

import pandas as pd

from epw_climate_analyzer.charts import psychrometric_chart


ROOT = Path(__file__).resolve().parents[1]


class Climate0104RegressionTests(unittest.TestCase):
    def test_compare_catalog_helpers_are_page_local(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_comparison_basket_manager")
        imported = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
        self.assertTrue({"catalog_runtime_summary", "station_provenance_text", "download_station_epw", "filter_station_catalog"}.issubset(imported))

    def _frame(self):
        rows = []
        for month in range(1, 13):
            rows.append({
                "dry_bulb_temperature_c": float(month + 5),
                "relative_humidity_pct": 40.0 + month,
                "humidity_ratio_g_kg": 4.0 + month * 0.25,
                "moist_air_enthalpy_kj_kg": 20.0 + month,
                "month_index": month,
                "month_name": str(month),
                "hour_of_day": 12,
            })
        return pd.DataFrame(rows)

    def test_psychrometric_domain_uses_page_width_with_zones_at_right(self):
        fig = psychrometric_chart(
            self._frame(),
            chart_type="T-d",
            show_comfort_zone=True,
            shown_bioclimatic_zones=["Comfort zone", "Permissible comfort zone"],
            color_mode="Month",
        )
        self.assertTrue(fig.layout.autosize)
        self.assertIsNone(fig.layout.width)
        self.assertEqual(list(fig.layout.xaxis.domain), [0.0, 0.72])
        self.assertEqual(fig.layout.legend.orientation, "h")
        self.assertAlmostEqual(fig.layout.legend.x, 0.36)
        self.assertEqual(fig.layout.legend2.orientation, "v")
        self.assertGreaterEqual(fig.layout.legend2.x, 0.75)
        zone_traces = [trace for trace in fig.data if getattr(trace, "legend", None) == "legend2" and getattr(trace, "showlegend", False)]
        self.assertEqual(sorted(trace.legendrank for trace in zone_traces), [1, 2])

    def test_default_climate_zone_uses_density_gradient_without_frequency_colorbar(self):
        fig = psychrometric_chart(
            self._frame(),
            chart_type="T-d",
            show_comfort_zone=False,
            data_mode="Climate zone",
            zone_coverage=0.90,
            zone_interior_style="Density gradient",
        )
        contour_traces = [trace for trace in fig.data if trace.type == "contour"]
        self.assertGreaterEqual(len(contour_traces), 2)
        self.assertTrue(all(getattr(trace, "showscale", False) is False for trace in contour_traces))
        self.assertFalse(bool(fig.layout.xaxis.autorange))
        self.assertFalse(bool(fig.layout.yaxis.autorange))
        self.assertIsNotNone(fig.layout.xaxis.range)
        self.assertIsNotNone(fig.layout.yaxis.range)


if __name__ == "__main__":
    unittest.main()
