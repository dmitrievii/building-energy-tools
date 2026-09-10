from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_ROOT = REPO_ROOT / "website" / "site"
sys.path.insert(0, str(REPO_ROOT / "website" / "scripts"))

from check_static_site import EXPECTED_PAGES, validate_site  # noqa: E402


class StaticSiteContractTests(unittest.TestCase):
    def test_full_static_site_contract_passes(self) -> None:
        self.assertEqual(validate_site(), [])

    def test_information_architecture_is_complete(self) -> None:
        manifest = json.loads((SITE_ROOT / "site-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["sections"],
            ["Home", "Tools", "Teaching", "Research", "Documentation", "About"],
        )
        self.assertEqual(
            manifest["support_pages"],
            ["Privacy", "Accessibility", "Legal / disclosure"],
        )
        self.assertEqual(len(EXPECTED_PAGES), 9)

    def test_site_0_2_manifest_is_bound_to_browser_audit_evidence(self) -> None:
        manifest = json.loads((SITE_ROOT / "site-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["stage"], "SITE-0.2")
        browser_audit = manifest["browser_audit"]
        self.assertEqual(browser_audit["stage"], "SITE-0.2")
        self.assertEqual(browser_audit["status"], "PASS")
        self.assertEqual(browser_audit["desktop_viewport"], "1440x1000")
        self.assertEqual(browser_audit["tablet_viewport"], "820x1180")
        self.assertEqual(browser_audit["mobile_viewport"], "390x844")
        self.assertEqual(browser_audit["compact_layout_breakpoint_px"], 800)
        evidence = REPO_ROOT / browser_audit["evidence"]
        self.assertTrue(evidence.is_file(), evidence)
        self.assertIn("8442a23111c72af5abfce78b28b853c16c3c09ec8c60ec48db0068c76ca3e54d", evidence.read_text(encoding="utf-8"))

    def test_static_layer_has_no_runtime_dependency_or_javascript_contract(self) -> None:
        manifest = json.loads((SITE_ROOT / "site-manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["build_required"])
        self.assertFalse(manifest["javascript_required"])
        self.assertEqual(manifest["runtime_dependencies"], [])
        self.assertEqual(manifest["external_runtime_assets"], [])
        for page in SITE_ROOT.rglob("*.html"):
            self.assertNotIn("<script", page.read_text(encoding="utf-8").lower(), page)

    def test_local_favicon_exists(self) -> None:
        favicon = SITE_ROOT / "favicon.ico"
        self.assertTrue(favicon.is_file())
        self.assertGreater(favicon.stat().st_size, 100)

    def test_climate_analyzer_is_integrated_as_separate_runtime(self) -> None:
        climate_url = "https://building-climate-analyzer.streamlit.app/"
        self.assertIn(climate_url, (SITE_ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertIn(climate_url, (SITE_ROOT / "tools" / "index.html").read_text(encoding="utf-8"))

    def test_publication_pages_remain_fail_closed(self) -> None:
        privacy = (SITE_ROOT / "privacy" / "index.html").read_text(encoding="utf-8").lower()
        legal = (SITE_ROOT / "legal" / "index.html").read_text(encoding="utf-8").lower()
        manifest = json.loads((SITE_ROOT / "site-manifest.json").read_text(encoding="utf-8"))
        self.assertIn("not yet cleared", privacy)
        self.assertIn("not publication-cleared", legal)
        self.assertEqual(
            manifest["publication_status"],
            "BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED",
        )


if __name__ == "__main__":
    unittest.main()
