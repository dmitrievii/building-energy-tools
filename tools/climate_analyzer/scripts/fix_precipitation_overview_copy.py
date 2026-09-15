from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "tools" / "climate_analyzer" / "app.py"

text = APP.read_text(encoding="utf-8")
old = "- Precipitation totals, wet-hour occurrence, snow depth and snow-cover occurrence"
new = "- Precipitation totals, precipitation-record occurrence, snow depth and snow-cover occurrence"
if text.count(old) != 1:
    raise RuntimeError(f"expected exactly one stale precipitation overview label, found {text.count(old)}")
APP.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Precipitation overview terminology corrected")
