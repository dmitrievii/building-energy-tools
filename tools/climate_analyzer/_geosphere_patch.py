from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "epw_climate_analyzer" / "geosphere.py"
text = TARGET.read_text(encoding="utf-8")

old = '        interval_semantics="interval_end",\n'
new = '        interval_semantics="unknown",\n'
if old not in text:
    raise SystemExit("GeoSphere interval-semantics anchor not found")
text = text.replace(old, new, 1)

old = '            f"License: {GEOSPHERE_LICENSE}",\n'
new = '            f"License: CC BY 4.0 ({GEOSPHERE_LICENSE})",\n'
if old not in text:
    raise SystemExit("GeoSphere licence-note anchor not found")
text = text.replace(old, new, 1)

TARGET.write_text(text, encoding="utf-8")
print("CLIMATE-GEOSPHERE-0.1 semantic cleanup applied")
