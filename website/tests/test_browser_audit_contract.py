from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class BrowserAuditContractTests(unittest.TestCase):
    def test_browser_audit_harness_is_versioned(self) -> None:
        script = REPO_ROOT / "website" / "scripts" / "browser_audit.mjs"
        workflow = REPO_ROOT / ".github" / "workflows" / "website-browser-audit.yml"
        self.assertTrue(script.is_file())
        self.assertTrue(workflow.is_file())
        script_text = script.read_text(encoding="utf-8")
        workflow_text = workflow.read_text(encoding="utf-8")
        for token in ["desktop", "tablet", "mobile", "desktop-200pct-layout-proxy", "axe-core", "skip-link", "externalRequests"]:
            self.assertIn(token, script_text)
        self.assertIn("puppeteer-core@24.16.0", workflow_text)
        self.assertIn("axe-core@4.10.3", workflow_text)
        self.assertIn("actions/upload-artifact@v4", workflow_text)

    def test_audit_covers_all_public_routes(self) -> None:
        script_text = (REPO_ROOT / "website" / "scripts" / "browser_audit.mjs").read_text(encoding="utf-8")
        for route in ["/", "/tools/", "/teaching/", "/research/", "/documentation/", "/about/", "/privacy/", "/accessibility/", "/legal/"]:
            self.assertIn(repr(route), script_text)

    def test_visual_audit_does_not_become_runtime_dependency(self) -> None:
        site_root = REPO_ROOT / "website" / "site"
        for html in site_root.rglob("*.html"):
            source = html.read_text(encoding="utf-8").lower()
            self.assertNotIn("puppeteer", source, html)
            self.assertNotIn("axe-core", source, html)
            self.assertNotIn("<script", source, html)


if __name__ == "__main__":
    unittest.main()
