from __future__ import annotations

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

    def test_monthly_widget_and_provider_state_versions_invalidate_old_checked_snapshot(self) -> None:
        self.assertTrue(_SELECTION_STATE_KEY.endswith("_v4"))
        self.assertEqual(_EDITOR_KEY_VERSION, "v2")
        key = _editor_key("Core variables", ["tl_mittel", "rf_mittel"])
        self.assertIn("__monthly__v2__core__", key)


if __name__ == "__main__":
    unittest.main()
