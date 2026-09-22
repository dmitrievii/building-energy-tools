from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.source_parity_variable_form import _apply_submitted_editor_state


class _ReadOnlyEditorState:
    """Minimal dictionary-like stand-in for Streamlit DataEditorState."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def get(self, key: str, default=None):
        return self._payload.get(key, default)


class DataEditorStateProtocolTests(unittest.TestCase):
    def test_read_only_dictionary_like_state_applies_selected_rows(self) -> None:
        source = pd.DataFrame(
            {
                "Selected": [False, False, False],
                "Provider": ["rf_mittel", "p", "tl_mittel"],
                "Measured variable": ["RH", "Pressure", "Temperature"],
            }
        )
        state = _ReadOnlyEditorState(
            {
                "edited_rows": {
                    0: {"Selected": True},
                    1: {"Selected": True},
                    2: {"Selected": True},
                }
            }
        )

        result = _apply_submitted_editor_state(source, state)

        self.assertEqual(int(result["Selected"].sum()), 3)
        self.assertFalse(bool(source["Selected"].any()))

    def test_invalid_or_empty_state_leaves_frame_unchanged(self) -> None:
        source = pd.DataFrame({"Selected": [False], "Provider": ["tl"]})
        result = _apply_submitted_editor_state(source, _ReadOnlyEditorState({"edited_rows": {}}))
        self.assertIs(result, source)


if __name__ == "__main__":
    unittest.main()
