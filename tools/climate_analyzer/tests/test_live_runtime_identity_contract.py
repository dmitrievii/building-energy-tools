from __future__ import annotations

import re
import unittest
from pathlib import Path

from epw_climate_analyzer.chart_theme import metric_color
from epw_climate_analyzer.runtime_identity import RUNTIME_BUILD_ID, runtime_source_files


TOOL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = TOOL_ROOT / "app.py"
AUDIT_PATH = REPO_ROOT / "deployment" / "live_browser_audit.mjs"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "climate-analyzer-live-audit.yml"


class LiveRuntimeIdentityContractTests(unittest.TestCase):
    def test_runtime_build_id_is_deterministic_sha256_shape(self) -> None:
        self.assertRegex(RUNTIME_BUILD_ID, r"^[0-9a-f]{64}$")

    def test_runtime_fingerprint_covers_executable_source_surface(self) -> None:
        relative = {path.relative_to(TOOL_ROOT).as_posix() for path in runtime_source_files(TOOL_ROOT)}
        self.assertIn("app.py", relative)
        self.assertIn("requirements.txt", relative)
        self.assertIn("epw_climate_analyzer/chart_theme.py", relative)
        self.assertIn("epw_climate_analyzer/charts.py", relative)
        self.assertIn("epw_climate_analyzer/comparison.py", relative)
        self.assertIn("epw_climate_analyzer/runtime_identity.py", relative)

    def test_live_app_exposes_runtime_build_and_active_ghi_colour_marker(self) -> None:
        app_source = APP_PATH.read_text(encoding="utf-8")
        self.assertIn('id="climate-analyzer-runtime-build"', app_source)
        self.assertIn('data-runtime-build=', app_source)
        self.assertIn('data-ghi-color=', app_source)
        self.assertIn('metric_color("global_horizontal_radiation_wh_m2")', app_source)
        self.assertEqual(metric_color("global_horizontal_radiation_wh_m2"), "#F59E0B")

    def test_live_audit_is_v4_and_fails_closed_on_stale_runtime(self) -> None:
        source = AUDIT_PATH.read_text(encoding="utf-8")
        self.assertIn("building-energy-tools-live-audit-v4", source)
        self.assertIn("EXPECTED_RUNTIME_BUILD_ID", source)
        self.assertIn("EXPECTED_GHI_COLOR", source)
        self.assertIn("climate-analyzer-runtime-build", source)
        self.assertIn("waitForExpectedRuntimeBuild", source)
        self.assertRegex(source, r"runtime[^\n]*build[^\n]*does not match|runtime_preflight")

    def test_live_audit_runs_automatically_after_main_climate_changes(self) -> None:
        source = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("push:", source)
        self.assertRegex(source, r"branches:\s*\n\s*- main")
        self.assertIn("tools/climate_analyzer/**", source)
        self.assertIn("deployment/live_browser_audit.mjs", source)


if __name__ == "__main__":
    unittest.main()
