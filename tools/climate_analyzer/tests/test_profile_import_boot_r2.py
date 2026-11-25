"""HF: fail fast on Streamlit startup import regressions in scientific findings."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import unittest

from epw_climate_analyzer.profile_interpretation import canonical_profile_kind


class ProfileImportBootTests(unittest.TestCase):
    def test_all_six_findings_modules_import_fresh(self):
        modules=(
            "temperature_findings",
            "humidity_findings",
            "wind_findings",
            "solar_findings",
            "sky_findings",
            "precipitation_findings",
        )
        for name in modules:
            with self.subTest(name=name):
                result=importlib.import_module("epw_climate_analyzer."+name)
                self.assertIs(result.canonical_profile_kind, canonical_profile_kind)

    def test_clean_python_process_bootstraps_without_circular_import(self):
        code=(
            "from epw_climate_analyzer.temperature_findings import temperature_figure_interpretation\n"
            "from epw_climate_analyzer.humidity_findings import humidity_figure_interpretation\n"
            "from epw_climate_analyzer.wind_findings import wind_figure_interpretation\n"
            "from epw_climate_analyzer.solar_findings import solar_figure_interpretation\n"
            "from epw_climate_analyzer.sky_findings import sky_figure_interpretation\n"
            "from epw_climate_analyzer.precipitation_findings import precipitation_figure_interpretation\n"
            "from epw_climate_analyzer.profile_interpretation import canonical_profile_kind\n"
            "assert canonical_profile_kind('time_series','Hourly · Observed values') == 'time_series'\n"
        )
        # Cloud invokes unittest from the repository root and injects source
        # roots into the parent sys.path. A fresh child cannot inherit sys.path.
        # Use the exact checkout, not an installed or cached package.
        source_root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        env["PYTHONPATH"]=str(source_root)
        code+=(
            "from pathlib import Path\n"
            "import epw_climate_analyzer.profile_interpretation as profile_module\n"
            f"assert Path(profile_module.__file__).resolve().is_relative_to(Path({str(source_root)!r}))\n"
        )
        result=subprocess.run([sys.executable,"-c",code],
                              cwd=source_root.parent.parent,env=env,
                              capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,
                         f"Fresh checkout import failed (exit {result.returncode})\n"
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

    def test_date_format_is_independent_of_profile_classifier(self):
        from epw_climate_analyzer.period_display import format_plotted_time
        self.assertTrue(callable(format_plotted_time))
        self.assertEqual(canonical_profile_kind("Time series / Profile",
                                               "Daily · P05–median–P95"),"percentile")


if __name__=="__main__":
    unittest.main()
