#!/usr/bin/env python3
from pathlib import Path

path = Path("tools/climate_analyzer/app.py")
text = path.read_text(encoding="utf-8")
needle = "        from epw_climate_analyzer.charts import (\n"
replacement = (
    "        # Streamlit may rerun a newly deployed app.py while retaining package modules\n"
    "        # imported by the previous release. Validate and refresh the cross-file\n"
    "        # psychrometric API before binding chart functions into this script run.\n"
    "        from epw_climate_analyzer.runtime_module_guard import ensure_current_psychrometric_runtime\n"
    "        ensure_current_psychrometric_runtime()\n"
    "        from epw_climate_analyzer.charts import (\n"
)
count = text.count(needle)
if count != 1:
    raise SystemExit(f"Expected exactly one charts import anchor, found {count}")
path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
print("Patched app.py psychrometric runtime import guard")
