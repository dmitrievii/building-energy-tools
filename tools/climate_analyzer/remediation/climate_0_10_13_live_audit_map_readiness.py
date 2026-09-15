from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AUDIT_PATH = REPO_ROOT / "deployment" / "live_browser_audit.mjs"
TEST_PATH = REPO_ROOT / "tools" / "climate_analyzer" / "tests" / "test_live_runtime_identity_contract.py"


def replace_once(text: str, pattern: str, replacement: str, *, flags: int = 0) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"Expected exactly one replacement for pattern: {pattern!r}; got {count}")
    return updated


audit = AUDIT_PATH.read_text(encoding="utf-8")
new_zoom_function = r'''async function waitForLeafletTileZoom(frame, predicate, timeoutMs = 8_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const level = await leafletTileZoom(frame);
    if (Number.isInteger(level) && predicate(level)) return level;
    await sleep(250);
  }
  return null;
}

async function exerciseLeafletZoom(page, appFrame, timeoutMs = 45_000) {
  const started = performance.now();
  let anchorScrolled = false;
  let anchorError = null;

  // The Folium component is below the fold, especially on mobile. Scroll the
  // Streamlit application frame to the map section before waiting for the
  // component iframe; otherwise a valid lazily-rendered map can be missed.
  try {
    const mapAnchor = appFrame.getByText('Clustered overview is active.', { exact: false }).first();
    await mapAnchor.waitFor({ state: 'attached', timeout: Math.min(timeoutMs, 30_000) });
    await mapAnchor.scrollIntoViewIfNeeded({ timeout: 5_000 });
    anchorScrolled = true;
  } catch (error) {
    anchorError = String(error);
  }

  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if (!frame.url().includes('streamlit_folium.st_folium')) continue;
      const zoomIn = frame.locator('.leaflet-control-zoom-in').first();
      if (!(await zoomIn.count().catch(() => 0))) continue;

      // A mounted iframe is not yet an interactive map: wait for at least one
      // OSM tile with a real zoom level before clicking controls.
      const initialLevel = await waitForLeafletTileZoom(frame, () => true);
      if (!Number.isInteger(initialLevel)) continue;

      try {
        const levels = [initialLevel];
        await zoomIn.click({ timeout: 5_000 });
        const firstZoom = await waitForLeafletTileZoom(frame, (value) => value > levels[0]);
        levels.push(firstZoom);
        if (!Number.isInteger(firstZoom)) {
          return {
            attempted: true,
            frame_url: frame.url(),
            levels,
            monotonic: false,
            anchor_scrolled: anchorScrolled,
            anchor_error: anchorError,
            wait_ms: Math.round(performance.now() - started),
            error: 'First Leaflet zoom-in did not produce a higher loaded tile zoom level.',
          };
        }

        await zoomIn.click({ timeout: 5_000 });
        const secondZoom = await waitForLeafletTileZoom(frame, (value) => value > levels[1]);
        levels.push(secondZoom);
        const monotonic = levels.every((value) => Number.isInteger(value))
          && levels[1] > levels[0]
          && levels[2] > levels[1];
        return {
          attempted: true,
          frame_url: frame.url(),
          levels,
          monotonic,
          anchor_scrolled: anchorScrolled,
          anchor_error: anchorError,
          wait_ms: Math.round(performance.now() - started),
        };
      } catch (error) {
        return {
          attempted: true,
          frame_url: frame.url(),
          levels: [],
          monotonic: false,
          anchor_scrolled: anchorScrolled,
          anchor_error: anchorError,
          wait_ms: Math.round(performance.now() - started),
          error: String(error),
        };
      }
    }
    await sleep(500);
  }
  return {
    attempted: false,
    frame_url: null,
    levels: [],
    monotonic: false,
    anchor_scrolled: anchorScrolled,
    anchor_error: anchorError,
    wait_ms: Math.round(performance.now() - started),
  };
}

async function runViewportAudit'''

audit = replace_once(
    audit,
    r"async function exerciseLeafletZoom\(page, timeoutMs = 15_000\) \{.*?\n\}\n\nasync function runViewportAudit",
    new_zoom_function,
    flags=re.DOTALL,
)
audit = replace_once(
    audit,
    r"findClimate\.zoom_sequence = await exerciseLeafletZoom\(page\);",
    "findClimate.zoom_sequence = await exerciseLeafletZoom(page, appFrame);",
)
AUDIT_PATH.write_text(audit, encoding="utf-8")


test_source = TEST_PATH.read_text(encoding="utf-8")
needle = "    def test_live_audit_runs_automatically_after_main_climate_changes(self) -> None:\n"
if needle not in test_source:
    raise RuntimeError("Could not locate live-audit workflow contract test insertion point")
new_test = '''    def test_live_audit_scrolls_to_lazy_map_and_waits_for_real_leaflet_tiles(self) -> None:\n        source = AUDIT_PATH.read_text(encoding="utf-8")\n        self.assertIn("exerciseLeafletZoom(page, appFrame", source)\n        self.assertIn("scrollIntoViewIfNeeded", source)\n        self.assertIn("streamlit_folium.st_folium", source)\n        self.assertIn("waitForLeafletTileZoom", source)\n        self.assertIn("timeoutMs = 45_000", source)\n        self.assertNotIn("exerciseLeafletZoom(page);", source)\n\n'''
test_source = test_source.replace(needle, new_test + needle, 1)
TEST_PATH.write_text(test_source, encoding="utf-8")

print("CLIMATE-0.10.13 live-audit map-readiness patch applied")
