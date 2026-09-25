from __future__ import annotations

from types import SimpleNamespace
import unittest

import pandas as pd

from epw_climate_analyzer.comparison import ClimateDataset
from epw_climate_analyzer.comparison_memory_hotfix import (
    COMPARISON_SECTIONS,
    _filter_comparison_climates,
    _install_safe_dataclass_equality,
)
from epw_climate_analyzer.epw_parser import EpwFile, EpwLocation


def _location() -> EpwLocation:
    return EpwLocation(
        city="Test",
        state="",
        country="AT",
        source="unit",
        wmo="00000",
        latitude=47.0,
        longitude=15.0,
        utc_offset=1.0,
        elevation_m=350.0,
    )


class EpwMultiClimateMemoryHotfixTests(unittest.TestCase):
    def test_dataframe_bearing_dataclasses_are_safe_for_streamlit_inequality(self) -> None:
        legacy = SimpleNamespace(ClimateDataset=ClimateDataset)
        _install_safe_dataclass_equality(legacy)

        epw_a = EpwFile(_location(), ["LOCATION"], pd.DataFrame({"x": [1.0]}), "a.epw")
        epw_b = EpwFile(_location(), ["LOCATION"], pd.DataFrame({"x": [2.0]}), "a.epw")
        self.assertIsInstance(epw_a != epw_b, bool)
        self.assertFalse(epw_a != epw_b)

        climate_a = ClimateDataset(
            "id-1", "Climate A", "local", epw_a, pd.DataFrame({"x": [1.0]}), []
        )
        climate_b = ClimateDataset(
            "id-1", "Climate A", "local", epw_b, pd.DataFrame({"x": [2.0]}), []
        )
        changed = climate_a != climate_b
        self.assertIsInstance(changed, bool)
        self.assertFalse(changed)

    def test_default_full_period_filter_is_zero_copy(self) -> None:
        sentinel = [object(), object(), object()]

        class Legacy:
            @staticmethod
            def filter_comparison_climates(*args, **kwargs):
                raise AssertionError("default filter must not clone climate DataFrames")

        result = _filter_comparison_climates(
            Legacy(),
            sentinel,
            months=list(range(1, 13)),
            hours=list(range(24)),
        )
        self.assertIs(result, sentinel)

    def test_partial_filter_delegates_to_existing_scientific_filter(self) -> None:
        sentinel = [object()]
        expected = [object()]
        calls = []

        class Legacy:
            @staticmethod
            def filter_comparison_climates(climates, *, months, hours):
                calls.append((climates, months, hours))
                return expected

        result = _filter_comparison_climates(
            Legacy(),
            sentinel,
            months=[1, 2],
            hours=[8, 9, 10],
        )
        self.assertIs(result, expected)
        self.assertEqual(calls, [(sentinel, [1, 2], [8, 9, 10])])

    def test_comparison_surface_is_one_explicit_section_not_nine_eager_tabs(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "epw_climate_analyzer"
            / "comparison_memory_hotfix.py"
        ).read_text(encoding="utf-8")

        self.assertEqual(len(COMPARISON_SECTIONS), 9)
        self.assertIn('key="comparison_analysis_section"', source)
        self.assertNotIn("st.tabs(", source)

    def test_large_station_catalogue_is_opt_in(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "epw_climate_analyzer"
            / "comparison_memory_hotfix.py"
        ).read_text(encoding="utf-8")

        flag = source.index("if enable_station_browser:")
        catalogue = source.index("legacy.cached_station_catalog()")
        self.assertLess(flag, catalogue)
        self.assertIn(
            'key="comparison_enable_station_browser"',
            source,
        )


if __name__ == "__main__":
    unittest.main()
