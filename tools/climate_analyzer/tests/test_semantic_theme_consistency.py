from __future__ import annotations

import unittest

import epw_climate_analyzer.chart_theme as chart_theme
import epw_climate_analyzer.comparison as comparison


class SemanticThemeConsistencyTests(unittest.TestCase):
    def test_comparison_suitability_scale_comes_from_central_theme(self) -> None:
        self.assertEqual(
            comparison.BINARY_SUITABILITY_COLORSCALE,
            chart_theme.BINARY_SUITABILITY_COLORSCALE,
        )
        self.assertEqual(comparison.BINARY_SUITABILITY_COLORSCALE[-1][1], "#047857")


if __name__ == "__main__":
    unittest.main()
