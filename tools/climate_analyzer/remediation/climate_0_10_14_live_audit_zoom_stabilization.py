from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AUDIT_PATH = REPO_ROOT / "deployment" / "live_browser_audit.mjs"
TEST_PATH = REPO_ROOT / "tools" / "climate_analyzer" / "tests" / "test_live_runtime_identity_contract.py"


audit = AUDIT_PATH.read_text(encoding="utf-8")
old = '''        await zoomIn.click({ timeout: 5_000 });\n        const secondZoom = await waitForLeafletTileZoom(frame, (value) => value > levels[1]);\n'''
new = '''        // Seeing the first higher tile level can precede the end of Leaflet's\n        // zoom animation. Give the control a short stabilization interval so a\n        // real second user click is not swallowed by the active transition.\n        await sleep(1_200);\n        await zoomIn.click({ timeout: 5_000 });\n        const secondZoom = await waitForLeafletTileZoom(frame, (value) => value > levels[1]);\n'''
if audit.count(old) != 1:
    raise RuntimeError(f"Expected one second-zoom block, found {audit.count(old)}")
audit = audit.replace(old, new, 1)
AUDIT_PATH.write_text(audit, encoding="utf-8")


test_source = TEST_PATH.read_text(encoding="utf-8")
needle = '''        self.assertIn("waitForLeafletTileZoom", source)\n        self.assertIn("timeoutMs = 45_000", source)\n'''
replacement = '''        self.assertIn("waitForLeafletTileZoom", source)\n        self.assertIn("timeoutMs = 45_000", source)\n        self.assertIn("await sleep(1_200);", source)\n'''
if test_source.count(needle) != 1:
    raise RuntimeError("Could not locate lazy-map audit contract assertions")
test_source = test_source.replace(needle, replacement, 1)
TEST_PATH.write_text(test_source, encoding="utf-8")

print("CLIMATE-0.10.14 zoom stabilization patch applied")
