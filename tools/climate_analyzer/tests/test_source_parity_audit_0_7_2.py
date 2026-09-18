from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.geosphere import FIELD_SPEC_BY_PROVIDER
from epw_climate_analyzer.historical_capabilities import available_historical_pages
from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
DOC = ROOT / "CLIMATE_SOURCE_PARITY_0_7_2.md"


class SourceParityAudit072Tests(unittest.TestCase):
    def test_current_geosphere_adapter_field_boundary_is_explicit(self) -> None:
        self.assertEqual(
            set(FIELD_SPEC_BY_PROVIDER),
            {"tl", "rf", "p", "ffam", "dd", "rr", "rrm", "sh", "cglo", "chim"},
        )

    def test_page_gap_reflects_0_7_3_supported_functional_closure(self) -> None:
        index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
        frame = pd.DataFrame(
            {
                spec.canonical_name: [1.0] * len(index)
                for spec in FIELD_SPEC_BY_PROVIDER.values()
            },
            index=index,
        )
        pages = set(available_historical_pages(frame))
        expected_missing = {
            "Sky and Daylight",
            "Compare Climates",
        }
        self.assertEqual(set(NAVIGATION_PAGES) - pages, expected_missing)

    def test_natural_ventilation_and_hvac_are_wired_for_historical_data(self) -> None:
        mapped = {spec.canonical_name for spec in FIELD_SPEC_BY_PROVIDER.values()}
        self.assertIn("dry_bulb_temperature_c", mapped)
        self.assertIn("relative_humidity_pct", mapped)
        self.assertIn("wind_speed_m_s", mapped)
        source = APP.read_text(encoding="utf-8")
        self.assertIn('render_natural_ventilation(filtered_df, pressure_pa=active_pressure)', source)
        self.assertIn('render_hvac_passive(filtered_df)', source)
        self.assertIn('"Wind during natural-ventilation hours"', source)
        self.assertIn("GeoSphere natural-ventilation suitability uses canonical hourly", source)

    def test_comparison_is_still_explicitly_epw_only(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("Add two or more EPW climates. All comparison metrics are calculated from EPW hourly data only.", source)

    def test_priority_a_provider_fields_remain_next_0_7_3_increment(self) -> None:
        self.assertTrue({"ffx", "ddx", "so", "tlmin", "tlmax"}.isdisjoint(FIELD_SPEC_BY_PROVIDER))
        doc = DOC.read_text(encoding="utf-8")
        for name in ("ffx", "ddx", "so", "tlmin", "tlmax", "*_flag"):
            self.assertIn(name, doc)


if __name__ == "__main__":
    unittest.main()
