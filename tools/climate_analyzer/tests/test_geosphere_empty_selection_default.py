from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

import pandas as pd

from epw_climate_analyzer.source_parity_longterm_followup import empty_measured_variable_table
from epw_climate_analyzer.source_parity_monthly_selection_state import (
    _EDITOR_KEY_VERSION,
    _SELECTION_STATE_KEY,
    _editor_key,
    _provider_state,
)


class GeoSphereEmptySelectionDefaultTests(unittest.TestCase):
    def test_generic_measured_variable_table_starts_empty(self) -> None:
        source = pd.DataFrame(
            {
                "Selected": [True, True, True],
                "Provider": ["tl", "rf", "p"],
            }
        )
        empty = empty_measured_variable_table(source)
        self.assertEqual(empty["Selected"].tolist(), [False, False, False])
        self.assertEqual(source["Selected"].tolist(), [True, True, True])

    def test_monthly_provider_state_ignores_legacy_selected_true_default(self) -> None:
        source = pd.DataFrame(
            {
                "Selected": [True, True, True],
                "Provider": ["tl_mittel", "rf_mittel", "p"],
                "Role": ["Core variable", "Core variable", "Core variable"],
            }
        )
        fake_st = SimpleNamespace(session_state={})
        state = _provider_state(
            fake_st,
            _SELECTION_STATE_KEY,
            source,
            "Selected",
            default=False,
        )
        self.assertEqual(
            state,
            {"tl_mittel": False, "rf_mittel": False, "p": False},
        )
        self.assertEqual(fake_st.session_state[_SELECTION_STATE_KEY], state)

    def test_monthly_widget_and_provider_state_versions_invalidate_legacy_checked_snapshots(self) -> None:
        # v4/v2 were the former cross-view-preservation contract. The current
        # contract resets selection whenever Parameter set changes, so both the
        # provider-state namespace and DataEditor widget namespace must be newer.
        state_match = re.search(r"_v(\d+)$", _SELECTION_STATE_KEY)
        editor_match = re.fullmatch(r"v(\d+)", _EDITOR_KEY_VERSION)
        self.assertIsNotNone(state_match)
        self.assertIsNotNone(editor_match)
        assert state_match is not None and editor_match is not None
        self.assertGreaterEqual(int(state_match.group(1)), 5)
        self.assertGreaterEqual(int(editor_match.group(1)), 3)

        key = _editor_key("Core variables", ["tl_mittel", "rf_mittel"])
        self.assertIn(f"__monthly__{_EDITOR_KEY_VERSION}__core__", key)
        self.assertNotIn("__monthly__v2__core__", key)


if __name__ == "__main__":
    unittest.main()
