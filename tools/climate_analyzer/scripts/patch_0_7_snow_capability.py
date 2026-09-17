from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "tools/climate_analyzer/app.py"
TEST = ROOT / "tools/climate_analyzer/tests/test_precipitation_snow_ui_contract_0_7.py"

source = APP.read_text(encoding="utf-8")
old = '''    snow_available = (\n        "snow_depth_cm" in source_df.columns\n        and pd.to_numeric(source_df["snow_depth_cm"], errors="coerce").notna().any()\n    )\n\n    options: list[str] = []\n'''
new = '''    hourly_snow_available = (\n        "snow_depth_cm" in df.columns\n        and pd.to_numeric(df["snow_depth_cm"], errors="coerce").notna().any()\n    )\n    native_snow_available = (\n        "snow_depth_cm" in source_df.columns\n        and pd.to_numeric(source_df["snow_depth_cm"], errors="coerce").notna().any()\n    )\n\n    options: list[str] = []\n'''
if source.count(old) != 1:
    raise SystemExit(f"expected snow availability block once, found {source.count(old)}")
source = source.replace(old, new, 1)
old = '''    if snow_available:\n        options.extend(["Snow depth explorer", "Snow-cover duration", "Snow-season indices"])\n'''
new = '''    if hourly_snow_available:\n        options.append("Snow depth explorer")\n    if native_snow_available:\n        options.extend(["Snow-cover duration", "Snow-season indices"])\n'''
if source.count(old) != 1:
    raise SystemExit(f"expected snow options block once, found {source.count(old)}")
source = source.replace(old, new, 1)
APP.write_text(source, encoding="utf-8")

test_source = TEST.read_text(encoding="utf-8")
anchor = '''    def test_rrm_duration_is_explicitly_not_inferred_from_rr(self) -> None:\n'''
addition = '''    def test_snow_explorer_and_native_snow_metrics_have_separate_capabilities(self) -> None:\n        self.assertIn("hourly_snow_available", self.source)\n        self.assertIn("native_snow_available", self.source)\n        self.assertIn('if hourly_snow_available:\\n        options.append("Snow depth explorer")', self.source)\n        self.assertIn(\n            'if native_snow_available:\\n        options.extend(["Snow-cover duration", "Snow-season indices"])',\n            self.source,\n        )\n\n'''
if anchor not in test_source:
    raise SystemExit("UI contract insertion anchor not found")
if "test_snow_explorer_and_native_snow_metrics_have_separate_capabilities" not in test_source:
    test_source = test_source.replace(anchor, addition + anchor, 1)
TEST.write_text(test_source, encoding="utf-8")
