from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "climate-analyzer-geosphere-precip-snow-live-smoke.yml"
PROBE = ROOT / "deployment" / "geosphere_precip_snow_provider_probe.py"
BROWSER = ROOT / "deployment" / "geosphere_precip_snow_live_smoke.mjs"
CORE_CI = ROOT / ".github" / "workflows" / "climate-analyzer-ci.yml"
DOC = ROOT / "tools" / "climate_analyzer" / "CLIMATE_CORE_0_7_1.md"


class GeoSpherePrecipSnowLiveSmoke071ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.probe = PROBE.read_text(encoding="utf-8")
        cls.browser = BROWSER.read_text(encoding="utf-8")
        cls.core_ci = CORE_CI.read_text(encoding="utf-8")
        cls.doc = DOC.read_text(encoding="utf-8")

    def test_provider_smoke_is_isolated_from_core_ci(self) -> None:
        self.assertIn("Climate Analyzer GeoSphere Precipitation Snow Live Smoke", self.workflow)
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("schedule:", self.workflow)
        self.assertIn("branches:\n      - main", self.workflow)
        self.assertNotIn("geosphere_precip_snow_provider_probe.py", self.core_ci)
        self.assertNotIn("geosphere_precip_snow_live_smoke.mjs", self.core_ci)
        self.assertIn("GeoSphere availability", self.doc)

    def test_probe_requires_rr_rrm_sh_through_production_adapter(self) -> None:
        self.assertIn('"liquid_precipitation_depth_mm"', self.probe)
        self.assertIn('"precipitation_duration_min"', self.probe)
        self.assertIn('"snow_depth_cm"', self.probe)
        self.assertIn("fetch_metadata", self.probe)
        self.assertIn("fetch_station_dataset", self.probe)
        self.assertIn("prepare_historical_analysis_frame", self.probe)
        self.assertIn("annual_precipitation_indices", self.probe)
        self.assertIn("snow_season_indices", self.probe)
        self.assertIn("PREFERRED_STATION_NAMES", self.probe)
        self.assertIn("MAX_TOTAL_INTERVAL_ATTEMPTS", self.probe)

    def test_probe_uses_bounded_winter_windows_not_current_default_period(self) -> None:
        self.assertIn("def _winter_intervals", self.probe)
        self.assertIn("WINTER_WINDOW_DAYS", self.probe)
        self.assertIn("WINTER_YEARS_BACK", self.probe)
        self.assertIn("historical winter", self.doc)
        self.assertIn('"hourly_snow_available"', self.probe)
        self.assertIn("HOURLY_REQUIRED_CANONICAL", self.probe)
        self.assertNotIn('PREFERRED_STATION_IDS = ("11240",)', self.probe)

    def test_browser_smoke_supports_streamlit_segmented_date_fields(self) -> None:
        self.assertIn("async function dateControl", self.browser)
        self.assertIn("role === 'group'", self.browser)
        self.assertIn("[role=\"spinbutton\"]", self.browser)
        self.assertIn("async function setSegmentedDate", self.browser)
        self.assertIn("aria-valuenow", self.browser)

    def test_browser_smoke_explicitly_selects_filtered_station(self) -> None:
        self.assertIn("async function selectStationFromList", self.browser)
        self.assertIn("Search-result stations", self.browser)
        self.assertIn("Use station from list", self.browser)
        self.assertIn("station_selection_option", self.browser)
        self.assertNotIn("await waitForText(appFrame, `ID ${fixture.station_id}`);", self.browser)

    def test_browser_smoke_drives_exact_fixture_dates(self) -> None:
        self.assertIn("async function setDateInput", self.browser)
        self.assertIn("From date (UTC)", self.browser)
        self.assertIn("Through date (UTC)", self.browser)
        self.assertIn("fixture.ui_start_date", self.browser)
        self.assertIn("fixture.ui_end_date", self.browser)
        self.assertIn("rendered_start", self.browser)
        self.assertIn("rendered_end", self.browser)

    def test_browser_smoke_exercises_new_0_7_analysis_families(self) -> None:
        expected = (
            "Annual precipitation indices",
            "Measured precipitation duration",
            "Precipitation-record occurrence",
            "Snow-cover duration",
            "Snow-season indices",
            "Dual-resolution semantics:",
            "never inferred from precipitation depth rr",
            "source-state cadence",
            "July–June analysis year",
        )
        for text in expected:
            self.assertIn(text, self.browser)
        self.assertIn("Load measured GeoSphere interval", self.browser)
        self.assertIn("provider-fixture.json", self.workflow)
        self.assertIn("retention-days: 14", self.workflow)

    def test_hourly_snow_explorer_is_conditional_but_native_snow_routes_are_required(self) -> None:
        self.assertIn("if (fixture.hourly_snow_available) expectedOptions.push('Snow depth explorer')", self.browser)
        self.assertIn("Snow-cover duration", self.browser)
        self.assertIn("Snow-season indices", self.browser)
        self.assertIn("strict-complete hourly `sh`", self.doc)

    def test_smoke_does_not_freeze_provider_measurements(self) -> None:
        self.assertNotIn("expected_precipitation_mm", self.probe)
        self.assertNotIn("expected_snow_depth_cm", self.probe)
        self.assertIn("No measured provider values are committed as golden data", self.doc)


if __name__ == "__main__":
    unittest.main()
