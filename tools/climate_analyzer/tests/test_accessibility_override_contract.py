from __future__ import annotations

from pathlib import Path
import unittest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AccessibilityOverrideContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding="utf-8")

    def test_file_uploader_hint_uses_stable_streamlit_testid_selector(self) -> None:
        selector = '[data-testid="stFileUploaderDropzoneInstructions"] span'
        self.assertIn(selector, self.source)
        self.assertIn("color: inherit !important;", self.source)

    def test_override_does_not_depend_on_ephemeral_emotion_class(self) -> None:
        marker = '[data-testid="stFileUploaderDropzoneInstructions"] span'
        start = self.source.index(marker)
        snippet = self.source[max(0, start - 300) : start + 500]
        self.assertNotIn("st-emotion-cache-", snippet)


if __name__ == "__main__":
    unittest.main()
