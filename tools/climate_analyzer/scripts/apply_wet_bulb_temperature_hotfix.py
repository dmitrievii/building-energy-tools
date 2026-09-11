from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
TEST = ROOT / "tests" / "test_wet_bulb_temperature_route.py"

source = APP.read_text(encoding="utf-8")
old_doc = '''    Expensive calculations are controlled by page-level flags. This keeps\n    temperature, wind, sky and data-quality pages responsive because they do not\n    need wet-bulb inversion or solar-position calculations.\n'''
new_doc = '''    Expensive calculations are controlled by page-level flags. This keeps wind,\n    sky and data-quality pages responsive by skipping optional derivations they\n    do not need. The Temperature page opts into psychrometrics because its\n    variable explorer exposes wet-bulb temperature.\n'''
if old_doc not in source:
    raise SystemExit("expected load_epw_from_bytes performance note not found")
source = source.replace(old_doc, new_doc, 1)

old_pages = '''    pages_requiring_psychrometrics = {\n        "Overview",\n        "Humidity and Psychrometrics",\n'''
new_pages = '''    pages_requiring_psychrometrics = {\n        "Overview",\n        "Temperature",\n        "Humidity and Psychrometrics",\n'''
if old_pages not in source:
    raise SystemExit("expected psychrometric page set not found")
source = source.replace(old_pages, new_pages, 1)
APP.write_text(source, encoding="utf-8")

TEST.write_text(r'''from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = TOOL_ROOT / "app.py"


class WetBulbTemperatureRouteTests(unittest.TestCase):
    def test_temperature_page_declares_psychrometric_derivation(self) -> None:
        source = APP_PATH.read_text(encoding="utf-8")
        start = source.index("def page_derivation_flags(page: str)")
        end = source.index("\ndef set_active_climate_file", start)
        block = source[start:end]
        self.assertIn('"Temperature",', block)
        self.assertIn("pages_requiring_psychrometrics", block)

    def test_temperature_route_materializes_wet_bulb_column_and_chart(self) -> None:
        code = textwrap.dedent(
            f"""
            import importlib.util
            from pathlib import Path
            from epw_climate_analyzer.epw_parser import EPW_COLUMNS

            app_path = Path({str(APP_PATH)!r})
            spec = importlib.util.spec_from_file_location("wet_bulb_route_test", app_path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)

            include_psychrometrics, include_solar = module.page_derivation_flags("Temperature")
            assert include_psychrometrics is True
            assert include_solar is False

            module._ensure_analysis_dependencies(include_solar=False, include_comparison=False)

            headers = [
                "LOCATION,Test City,Test State,AUT,TEST,123456,47.07,15.44,1.0,350.0",
                "DESIGN CONDITIONS,0",
                "TYPICAL/EXTREME PERIODS,0",
                "GROUND TEMPERATURES,0",
                "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
                "COMMENTS 1,Wet-bulb route regression fixture",
                "COMMENTS 2,Wet-bulb route regression fixture",
                "DATA PERIODS,1,1,Data,Sunday,1/1,12/31",
            ]
            rows = []
            for index in range(24):
                values = ["0"] * len(EPW_COLUMNS)
                values[0] = "2020"
                values[1] = "1"
                values[2] = "1"
                values[3] = str(index + 1)
                values[4] = "60"
                values[5] = "?9?9?9?9E0?9?9?9*9*9*9*9*9*9*9*9*9*9*9*9*9*9*9"
                values[6] = str(5.0 + index * 0.25)
                values[7] = str(2.0 + index * 0.10)
                values[8] = "80"
                values[9] = "101325"
                values[13] = "100"
                values[14] = "50"
                values[15] = "50"
                values[20] = "180"
                values[21] = "2.0"
                rows.append(",".join(values))
            payload = ("\\n".join(headers + rows) + "\\n").encode("utf-8")

            epw, frame, issues = module.load_epw_from_bytes(
                "wet-bulb-route.epw",
                payload,
                "Normal pressure: 101325 Pa",
                None,
                include_psychrometrics=include_psychrometrics,
                include_solar=include_solar,
            )
            assert epw.location.country == "AUT"
            assert "wet_bulb_temperature_c" in frame.columns
            assert frame["wet_bulb_temperature_c"].notna().any()

            fig = module.profile_ribbon_chart(
                frame,
                "wet_bulb_temperature_c",
                "Hourly",
                "Temperature: Wet-bulb temperature",
                "°C",
            )
            assert len(fig.data) >= 1
            print("WET_BULB_TEMPERATURE_ROUTE=PASS")
            """
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(TOOL_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=TOOL_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + "\n" + result.stdout)
        self.assertIn("WET_BULB_TEMPERATURE_ROUTE=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

print("CLIMATE-0.10.6 wet-bulb temperature hotfix applied")
