from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"
text = APP.read_text(encoding="utf-8")

old_historical = 'measured_median = float(valid_pressure.median()) if not valid_pressure.empty else DEFAULT_PRESSURE_PA'
new_historical = '''measured_median = (\n        float(valid_pressure.median())\n        if not valid_pressure.empty\n        else pressure_from_altitude_m(float(dataset.location.elevation_m or 0.0))\n    )'''
if text.count(old_historical) != 1:
    raise RuntimeError(f"Historical pressure fallback anchor count: {text.count(old_historical)}")
text = text.replace(old_historical, new_historical, 1)

old_epw = 'active_pressure = float(valid_pressure.median()) if not valid_pressure.empty else DEFAULT_PRESSURE_PA'
new_epw = '''active_pressure = (\n            float(valid_pressure.median())\n            if not valid_pressure.empty\n            else pressure_from_altitude_m(float(epw.location.elevation_m or 0.0))\n        )'''
if text.count(old_epw) != 1:
    raise RuntimeError(f"EPW active-pressure fallback anchor count: {text.count(old_epw)}")
text = text.replace(old_epw, new_epw, 1)

APP.write_text(text, encoding="utf-8")
print("0.7.4.1 location-specific pressure fallbacks applied")
