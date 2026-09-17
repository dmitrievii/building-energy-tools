from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "CLIMATE_CORE_0_7.md"


class PrecipitationSnowDocs07Tests(unittest.TestCase):
    def test_release_contract_documents_dual_resolution_and_missingness(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("Dual-resolution contract", text)
        self.assertIn("fully unobserved days break a dry spell", text)
        self.assertIn("duration is never inferred from `rr`", text)
        self.assertIn("July–June", text)


if __name__ == "__main__":
    unittest.main()
