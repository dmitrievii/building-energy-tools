from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.geosphere_monthly_request_surface import (
    _clamp,
    _selected_payload,
)


class MonthlyRequestSurfacePureTests(unittest.TestCase):
    def test_selected_payload_keeps_only_checked_physical_fields_and_matching_flag_choices(self) -> None:
        edited = pd.DataFrame(
            {
                "Selected": [True, True, False],
                "Quality flag": [True, False, True],
                "Provider": ["rf_mittel", "p", "tl_mittel"],
            }
        )
        providers, flags = _selected_payload(edited)
        self.assertEqual(providers, ("rf_mittel", "p"))
        self.assertEqual(flags, ("rf_mittel_flag",))

    def test_request_dates_are_clamped_to_station_validity(self) -> None:
        low = date(1900, 1, 1)
        high = date(2026, 9, 24)
        fallback = date(2021, 9, 24)
        self.assertEqual(_clamp(date(1800, 1, 1), low, high, fallback), low)
        self.assertEqual(_clamp(date(2030, 1, 1), low, high, fallback), high)
        self.assertEqual(_clamp(None, low, high, fallback), fallback)


class MonthlyRequestSurfaceArchitectureTests(unittest.TestCase):
    def test_fragment_owns_request_tail_but_not_station_browser_or_map(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "epw_climate_analyzer"
            / "geosphere_monthly_request_surface.py"
        ).read_text(encoding="utf-8")
        self.assertIn("fragment_factory", source)
        self.assertIn("with st.form(form_key", source)
        self.assertIn('"Parameter set"', source)
        self.assertIn('"From date (UTC)"', source)
        self.assertIn('"Through date (UTC)"', source)
        self.assertIn('"Measured variables to load"', source)
        self.assertIn('st.form_submit_button(', source)
        self.assertIn("raise _MonthlyRequestBoundary()", source)
        self.assertNotIn("Search GeoSphere station", source)
        self.assertNotIn("st_folium", source)
        self.assertNotIn("Manual station selection", source)

    def test_runtime_installs_fragment_after_request_state_and_before_selector_freeze(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "epw_climate_analyzer"
            / "source_parity_runtime.py"
        ).read_text(encoding="utf-8")
        request_pos = source.index("install_geosphere_request_form(parity)")
        monthly_fragment_pos = source.index("install_monthly_request_surface(parity)")
        freeze_pos = source.index("_freeze_session_geosphere_selector(proxy, parity)")
        self.assertLess(request_pos, monthly_fragment_pos)
        self.assertLess(monthly_fragment_pos, freeze_pos)
        self.assertEqual(source.count("install_monthly_request_surface(parity)"), 1)


if __name__ == "__main__":
    unittest.main()
