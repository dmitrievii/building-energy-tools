from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.geosphere import plan_data_queries
from epw_climate_analyzer.historical_capabilities import (
    available_historical_pages,
    historical_coverage_summary,
    historical_variable_coverage,
)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class GeoSphere061CoverageTests(unittest.TestCase):
    def irregular_frame(self) -> pd.DataFrame:
        idx = pd.to_datetime([
            "2025-01-01T00:00:00Z",
            "2025-01-01T00:10:00Z",
            "2025-01-01T00:30:00Z",
        ])
        df = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [1.0, 2.0, 4.0],
                "relative_humidity_pct": [80.0, None, 70.0],
            },
            index=idx,
        )
        df.attrs["canonical_native_interval_minutes"] = 10
        df.attrs["canonical_requested_start"] = "2025-01-01T00:00:00+00:00"
        df.attrs["canonical_requested_end"] = "2025-01-01T00:40:00+00:00"
        return df

    def test_timeline_coverage_uses_requested_bounds_and_keeps_gaps_missing(self) -> None:
        summary = historical_coverage_summary(self.irregular_frame())
        self.assertEqual(summary["expected_records"], 5)
        self.assertEqual(summary["observed_records"], 3)
        self.assertEqual(summary["missing_timestamp_intervals"], 2)
        self.assertAlmostEqual(float(summary["timeline_coverage_pct"]), 60.0)
        self.assertEqual(summary["gap_count"], 2)
        self.assertAlmostEqual(float(summary["longest_missing_gap_minutes"]), 10.0)
        self.assertAlmostEqual(float(summary["observed_duration_hours"]), 0.5)
        self.assertAlmostEqual(float(summary["expected_duration_hours"]), 5.0 / 6.0)

    def test_variable_coverage_uses_same_requested_timeline_denominator(self) -> None:
        coverage = historical_variable_coverage(
            self.irregular_frame(),
            ["dry_bulb_temperature_c", "relative_humidity_pct"],
        ).set_index("variable")
        self.assertEqual(int(coverage.loc["dry_bulb_temperature_c", "valid_records"]), 3)
        self.assertAlmostEqual(float(coverage.loc["dry_bulb_temperature_c", "coverage_pct"]), 60.0)
        self.assertEqual(int(coverage.loc["relative_humidity_pct", "valid_records"]), 2)
        self.assertAlmostEqual(float(coverage.loc["relative_humidity_pct", "coverage_pct"]), 40.0)

    def test_overview_is_always_available_but_temperature_remains_observation_gated(self) -> None:
        no_temp = self.irregular_frame().copy()
        no_temp["dry_bulb_temperature_c"] = pd.NA
        pages = available_historical_pages(no_temp)
        self.assertIn("Overview", pages)
        self.assertNotIn("Temperature", pages)
        self.assertIn("Time Series and Overlay", pages)
        self.assertIn("Data Quality", pages)

    def test_multi_year_interval_is_split_into_bounded_requests(self) -> None:
        start = pd.Timestamp("2020-01-01T00:00:00Z")
        end = pd.Timestamp("2022-12-31T23:50:00Z")
        queries = plan_data_queries("16413", start, end, ["tl", "rf", "p"] )
        self.assertGreater(len(queries), 1)
        self.assertEqual(queries[0]["start"], "2020-01-01T00:00")
        self.assertEqual(queries[-1]["end"], "2022-12-31T23:50")

    def test_public_ui_contract_contains_overview_variable_selection_and_from_direction(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('def render_historical_overview(dataset, df: pd.DataFrame)', source)
        self.assertIn('st.markdown("#### Measured variables to load")', source)
        self.assertIn("edited_variables = st.data_editor(", source)
        self.assertIn('st.column_config.CheckboxColumn("Load"', source)
        self.assertNotIn('key="geosphere_provider_parameters"', source)
        self.assertNotIn('selected_days > 366', source)
        self.assertIn('meteorological FROM convention', source)
        self.assertIn('st.caption(WIND_DIRECTION_FROM_NOTE)', source)
        self.assertIn('preferred = "Overview"', source)


class GeoSphere061RuntimeCapabilityTests(unittest.TestCase):
    def test_temperature_only_runtime_does_not_require_humidity(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("can_derive_psychrometrics = (", source)
        self.assertIn('has_numeric_observations(dataset.data, "dry_bulb_temperature_c")', source)
        self.assertIn('has_numeric_observations(dataset.data, "relative_humidity_pct")', source)
        self.assertIn("include_psychrometrics = can_derive_psychrometrics", source)

    def test_generic_explorer_filters_to_actual_numeric_columns(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("available_labels = [", source)
        self.assertIn("VARIABLES[label][0] in df.columns", source)
        self.assertIn("selected_default = default_variable if default_variable in available_labels", source)

    def test_temperature_only_historical_preparation_is_valid_without_psychrometrics(self) -> None:
        from epw_climate_analyzer.climate_model import (
            CanonicalClimateDataset,
            ClimateLocation,
            ClimateProvenance,
            ClimateTemporalMetadata,
        )
        from epw_climate_analyzer.historical import prepare_historical_analysis_frame

        index = pd.date_range("2025-01-01T00:00:00Z", periods=6, freq="10min")
        data = pd.DataFrame({"dry_bulb_temperature_c": [1, 2, 3, 4, 5, 6]}, index=index)
        data.attrs["canonical_native_interval_minutes"] = 10
        dataset = CanonicalClimateDataset(
            climate_id="temp-only",
            display_name="Temperature only",
            data=data,
            location=ClimateLocation(47.0, 15.0, 350.0, "Test", "", "Austria", "1"),
            temporal=ClimateTemporalMetadata(10, "historical", "UTC", "unknown"),
            provenance=ClimateProvenance("GeoSphere Austria", "test", "Dataset API JSON", "test"),
        )
        prepared = prepare_historical_analysis_frame(dataset, include_psychrometrics=False)
        self.assertIn("dry_bulb_temperature_c", prepared.columns)
        self.assertNotIn("humidity_ratio_g_kg", prepared.columns)
        self.assertIn("Temperature", available_historical_pages(prepared))



if __name__ == "__main__":
    unittest.main()

# CLIMATE_GEOSPHERE_0_6_1_PERMANENT
