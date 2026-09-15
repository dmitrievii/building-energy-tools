from pathlib import Path

path = Path(__file__).resolve().parent / "epw_climate_analyzer" / "exporting.py"
text = path.read_text(encoding="utf-8")
old = '    text = text.rsplit("/", 1)[-1].rsplit("\\\\", 1)[-1]\n'
new = '    text = text.replace("/", " ").replace("\\\\", " ")\n'
if old not in text:
    raise SystemExit("export filename normalization contract not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("CLIMATE-EXPORT-0.1 filename normalization hotfix applied")
