from __future__ import annotations

import unittest
from pathlib import Path

from epw_climate_analyzer.release_info import (
    ACADEMIC_AFFILIATION,
    AUTHOR_NAME,
    ENGINEERING_DISCLAIMER,
    INDEPENDENCE_NOTICE,
    PROJECT_NAME,
    PUBLICATION_STATUS,
    RELEASE_CHANNEL,
    TOOL_NAME,
    TOOL_VERSION,
)
from epw_climate_analyzer.ui_contract import (
    APP_ENGINEERING_DISCLAIMER,
    APP_INDEPENDENCE_NOTICE,
    APP_RELEASE_LABEL,
    PUBLIC_UX_STAGE,
)

TOOL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]


class PublicationContractTests(unittest.TestCase):
    def test_release_identity_is_explicit_beta_candidate(self) -> None:
        self.assertEqual(PROJECT_NAME, "Building Energy Tools")
        self.assertEqual(TOOL_NAME, "Climate Analyzer")
        self.assertRegex(TOOL_VERSION, r"^\d+\.\d+\.\d+-beta\.\d+$")
        self.assertEqual(RELEASE_CHANNEL, "public-beta-candidate")
        self.assertEqual(PUBLICATION_STATUS, "BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED")
        self.assertIn(TOOL_VERSION, APP_RELEASE_LABEL)
        self.assertEqual(PUBLIC_UX_STAGE, "WEB-0.7")

    def test_identity_does_not_claim_official_tu_graz_status(self) -> None:
        self.assertEqual(AUTHOR_NAME, "Ivan Dmitriev")
        self.assertIn("Graz University of Technology", ACADEMIC_AFFILIATION)
        self.assertIn("not an official", INDEPENDENCE_NOTICE.lower())
        self.assertEqual(APP_INDEPENDENCE_NOTICE, INDEPENDENCE_NOTICE)

    def test_engineering_disclaimer_rejects_certification_claim(self) -> None:
        self.assertIn("not a substitute", ENGINEERING_DISCLAIMER.lower())
        self.assertIn("certification", ENGINEERING_DISCLAIMER.lower())
        self.assertEqual(APP_ENGINEERING_DISCLAIMER, ENGINEERING_DISCLAIMER)

    def test_required_publication_documents_exist(self) -> None:
        paths = [
            REPO_ROOT / "docs" / "PUBLICATION_POLICY.md",
            REPO_ROOT / "website" / "PUBLICATION_CHECKLIST.md",
            REPO_ROOT / "website" / "content" / "about.md",
            REPO_ROOT / "website" / "content" / "privacy.md",
            REPO_ROOT / "website" / "content" / "legal-notice.template.md",
            TOOL_ROOT / "METHODOLOGY.md",
            TOOL_ROOT / "ATTRIBUTION.md",
        ]
        for path in paths:
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 200, path)

    def test_publication_gate_stays_blocked_until_contact_fields_are_approved(self) -> None:
        checklist = (REPO_ROOT / "website" / "PUBLICATION_CHECKLIST.md").read_text(encoding="utf-8")
        privacy = (REPO_ROOT / "website" / "content" / "privacy.md").read_text(encoding="utf-8")
        legal_template = (REPO_ROOT / "website" / "content" / "legal-notice.template.md").read_text(encoding="utf-8")
        self.assertIn("PUBLICATION BLOCKED", checklist)
        self.assertIn("geographic address", checklist.lower())
        self.assertIn("to be approved before publication", privacy.lower())
        self.assertIn("DO NOT DEPLOY", legal_template)
        self.assertIn("PUBLICATION REQUIRED", legal_template)

    def test_public_app_exposes_beta_and_disclaimer_contract(self) -> None:
        app_source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("APP_RELEASE_LABEL", app_source)
        self.assertIn('st.expander("About this beta"', app_source)
        self.assertIn("APP_ENGINEERING_DISCLAIMER", app_source)
        self.assertIn("APP_INDEPENDENCE_NOTICE", app_source)


if __name__ == "__main__":
    unittest.main()
