from __future__ import annotations

import unittest
from pathlib import Path

from epw_climate_analyzer.ui_contract import (
    APP_BROWSER_TITLE,
    APP_NAME,
    APP_TAGLINE,
    NAVIGATION_KEY,
    NAVIGATION_LABELS,
    NAVIGATION_PAGES,
    PENDING_NAVIGATION_KEY,
    RESET_NAVIGATION_KEY,
    apply_queued_navigation,
    navigation_label,
    queue_navigation,
    queue_navigation_reset,
)


TOOL_ROOT = Path(__file__).resolve().parents[1]


class PublicUxContractTests(unittest.TestCase):
    def test_public_product_identity(self) -> None:
        self.assertEqual(APP_NAME, "Climate Analyzer")
        self.assertEqual(APP_BROWSER_TITLE, "Climate Analyzer | Building Energy Tools")
        self.assertIn("building design", APP_TAGLINE.lower())

    def test_navigation_contract_is_complete_and_unique(self) -> None:
        self.assertEqual(len(NAVIGATION_PAGES), 11)
        self.assertEqual(len(set(NAVIGATION_PAGES)), len(NAVIGATION_PAGES))
        self.assertEqual(set(NAVIGATION_LABELS), set(NAVIGATION_PAGES))
        labels = [navigation_label(page) for page in NAVIGATION_PAGES]
        self.assertEqual(len(set(labels)), len(labels))

    def test_navigation_exposes_expected_groups(self) -> None:
        labels = [navigation_label(page) for page in NAVIGATION_PAGES]
        self.assertEqual(labels[0], "Start — Climate source")
        for prefix in ("Climate —", "Design —", "Compare —", "Data —"):
            self.assertTrue(any(label.startswith(prefix) for label in labels), prefix)

    def test_navigation_is_queued_before_widget_state_is_changed(self) -> None:
        state: dict[str, object] = {NAVIGATION_KEY: "Climate File Source"}
        queue_navigation(state, "Overview")
        self.assertEqual(state[NAVIGATION_KEY], "Climate File Source")
        self.assertEqual(state[PENDING_NAVIGATION_KEY], "Overview")
        apply_queued_navigation(state)
        self.assertEqual(state[NAVIGATION_KEY], "Overview")
        self.assertNotIn(PENDING_NAVIGATION_KEY, state)

    def test_navigation_reset_is_applied_on_next_render(self) -> None:
        state: dict[str, object] = {NAVIGATION_KEY: "Climate File Source"}
        queue_navigation_reset(state)
        self.assertEqual(state[NAVIGATION_KEY], "Climate File Source")
        self.assertTrue(state[RESET_NAVIGATION_KEY])
        apply_queued_navigation(state)
        self.assertNotIn(NAVIGATION_KEY, state)
        self.assertNotIn(RESET_NAVIGATION_KEY, state)

    def test_unknown_navigation_target_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            queue_navigation({}, "Unknown page")

    def test_climate_source_map_is_lazy_rendered(self) -> None:
        source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('st.tabs(["Upload EPW", "Find climate"])', source)
        self.assertIn('source_mode = st.radio(', source)
        self.assertIn('if source_mode == "Upload EPW":', source)
        upload_branch = source.split('if source_mode == "Upload EPW":', 1)[1].split('st.subheader("Find a climate")', 1)[0]
        self.assertIn("return", upload_branch)

    def test_essential_landing_copy_does_not_use_low_contrast_caption(self) -> None:
        source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("st.caption(APP_RELEASE_LABEL)", source)
        self.assertIn("st.write(APP_RELEASE_LABEL)", source)
        self.assertNotIn(
            'st.caption(\n        "Start with an EPW weather file from your computer or select a climate from the reviewed "',
            source,
        )


if __name__ == "__main__":
    unittest.main()
