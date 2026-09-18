from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.geosphere import FIELD_SPEC_BY_PROVIDER
from epw_climate_analyzer.historical_capabilities import available_historical_pages


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
DOC = ROOT / "CLIMATE_CORE_0_7_3.md"

EXPECTED_MAPPED = {
    "cglo", "chim", "dd", "ddx", "ffam", "ffx", "p", "rf", "rr", "rrm", "sh", "so", "tl", "tlmax", "tlmin"
}
EXPLICITLY_DEFERRED = {"ff", "pred", "tb10", "tb20", "tb50", "ts", "tsmax", "tsmin", "zeitx"}


class SourceParityClosure073Tests(unittest.TestCase):
    def test_priority_a_mapping_boundary_is_closed_and_secondary_fields_remain_explicitly_deferred(self) -> None:
        self.assertEqual(set(FIELD_SPEC_BY_PROVIDER), EXPECTED_MAPPED)
        self.assertTrue(EXPLICITLY_DEFERRED.isdisjoint(FIELD_SPEC_BY_PROVIDER))
        doc = DOC.read_text(encoding="utf-8")
        for provider_name in sorted(EXPLICITLY_DEFERRED):
            self.assertIn(f"`{provider_name}`", doc)

    def test_remaining_page_gaps_are_source_contract_decisions_not_silent_failures(self) -> None:
        index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
        frame = pd.DataFrame(
            {spec.canonical_name: [1.0] * len(index) for spec in FIELD_SPEC_BY_PROVIDER.values()},
            index=index,
        )
        pages = set(available_historical_pages(frame))
        self.assertNotIn("Sky and Daylight", pages)
        self.assertNotIn("Compare Climates", pages)
        self.assertIn("Natural Ventilation", pages)
        self.assertIn("HVAC and Passive Design", pages)

    def test_compare_climates_remains_explicitly_epw_only_in_0_7_3(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("Add two or more EPW climates. All comparison metrics are calculated from EPW hourly data only.", source)
        self.assertIn("Compare several EPW climates", source)
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("explicitly EPW-only", doc)

    def test_sky_daylight_gap_does_not_trigger_fabricated_provider_fields(self) -> None:
        mapped_canonical = {spec.canonical_name for spec in FIELD_SPEC_BY_PROVIDER.values()}
        forbidden_fabrication = {
            "direct_normal_radiation_wh_m2",
            "global_horizontal_illuminance_lux",
            "direct_normal_illuminance_lux",
            "diffuse_horizontal_illuminance_lux",
            "total_sky_cover_tenths",
            "opaque_sky_cover_tenths",
        }
        self.assertTrue(forbidden_fabrication.isdisjoint(mapped_canonical))


if __name__ == "__main__":
    unittest.main()
