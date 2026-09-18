from pathlib import Path

root = Path(__file__).resolve().parents[3]
smoke_path = root / "deployment" / "geosphere_precip_snow_live_smoke.mjs"
text = smoke_path.read_text(encoding="utf-8")

old_wait = "  appFrame = await waitForFrameContaining(page, 'Precipitation and Snow', 180_000);\n"
new_wait = "  appFrame = await waitForFrameContaining(page, 'Climate — Precipitation & snow', 180_000);\n"
old_click = "  await clickChoice(appFrame, 'Precipitation and Snow');\n"
new_click = "  await clickChoice(appFrame, 'Climate — Precipitation & snow');\n"

if old_wait not in text:
    raise SystemExit("old precipitation wait label not found")
if old_click not in text:
    raise SystemExit("old precipitation click label not found")
text = text.replace(old_wait, new_wait, 1).replace(old_click, new_click, 1)
smoke_path.write_text(text, encoding="utf-8")

test_path = root / "tools" / "climate_analyzer" / "tests" / "test_geosphere_precip_snow_live_smoke_0_7_1.py"
test_text = test_path.read_text(encoding="utf-8")
anchor = "    def test_browser_smoke_exercises_new_0_7_analysis_families(self) -> None:\n"
method = '''    def test_browser_smoke_uses_current_precipitation_navigation_label(self) -> None:\n        self.assertIn("Climate — Precipitation & snow", self.browser)\n        self.assertNotIn("waitForFrameContaining(page, 'Precipitation and Snow'", self.browser)\n        self.assertNotIn("clickChoice(appFrame, 'Precipitation and Snow'", self.browser)\n\n'''
if method not in test_text:
    if anchor not in test_text:
        raise SystemExit("test insertion anchor not found")
    test_text = test_text.replace(anchor, method + anchor, 1)
    test_path.write_text(test_text, encoding="utf-8")
