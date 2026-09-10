from __future__ import annotations

import unittest

from epw_climate_analyzer.ui_contract import (
    APP_BROWSER_TITLE,
    APP_NAME,
    APP_TAGLINE,
    NAVIGATION_LABELS,
    NAVIGATION_PAGES,
    navigation_label,
)


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


if __name__ == "__main__":
    unittest.main()
