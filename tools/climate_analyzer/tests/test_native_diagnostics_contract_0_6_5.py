from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
)
from epw_climate_analyzer.historical import (
    clear_historical_hourly_cache,
    prepare_historical_analysis_frame,
    prepare_historical_native_diagnostic_frame,
)


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def dataset_fixture() -> CanonicalClimateDataset:
    index = pd.date_range("2026-01-01T00:00:00Z", periods=12, freq="10min", name="timestamp")
    frame = pd.DataFrame(
        {
            "dry_bulb_temperature_c": [10.0, 11.0, float("nan"), 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0],
            "relative_humidity_pct": [70.0] * 12,
            "atmospheric_station_pressure_pa": [100000.0] * 12,
            "liquid_precipitation_depth_mm": [0.1] * 12,
        },
        index=index,
    )
    frame.attrs["canonical_native_interval_minutes"] = 10
    frame.attrs["canonical_requested_start"] = str(index[0])
    frame.attrs["canonical_requested_end"] = str(index[-1])
    frame.attrs["canonical_calendar_mode"] = "historical"
    frame.attrs["canonical_timezone_name"] = "UTC"
    return CanonicalClimateDataset(
        climate_id="test:native-quality",
        display_name="Native diagnostics fixture",
        data=frame,
        location=ClimateLocation(
            latitude=47.08,
            longitude=15.45,
            elevation_m=366.0,
            city="Graz",
            country="Austria",
            station_id="test",
        ),
        temporal=ClimateTemporalMetadata(
            native_interval_minutes=10,
            calendar_mode="historical",
            timezone_name="UTC",
            interval_semantics="unknown",
        ),
        provenance=ClimateProvenance(
            provider="test",
            dataset="test native climate",
            source_format="fixture",
            source_name="native diagnostics fixture",
        ),
    )


class NativeDiagnosticsBackend065Tests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_historical_hourly_cache()

    def test_native_diagnostics_preserve_source_resolution_and_missingness(self) -> None:
        dataset = dataset_fixture()
        native = prepare_historical_native_diagnostic_frame(dataset)
        hourly = prepare_historical_analysis_frame(dataset)

        self.assertEqual(len(native), 12)
        self.assertEqual(native.index.tolist(), dataset.data.index.tolist())
        self.assertEqual(int(native.attrs["canonical_native_interval_minutes"]), 10)
        self.assertEqual(int(native.attrs["canonical_source_interval_minutes"]), 10)
        self.assertEqual(int(native.attrs["canonical_analysis_interval_minutes"]), 60)
        self.assertEqual(native.attrs["canonical_frame_role"], "native-diagnostics")
        self.assertEqual(int(native["dry_bulb_temperature_c"].isna().sum()), 1)
        self.assertIn("month_index", native.columns)
        self.assertIn("hour_of_day", native.columns)

        self.assertEqual(len(hourly), 2)
        self.assertEqual(int(hourly.attrs["canonical_native_interval_minutes"]), 60)
        self.assertEqual(int(hourly.attrs["canonical_source_interval_minutes"]), 10)
        self.assertEqual(int(hourly.attrs["canonical_analysis_interval_minutes"]), 60)
        self.assertEqual(hourly.attrs["canonical_frame_role"], "hourly-analysis")
        self.assertTrue(pd.isna(hourly.iloc[0]["dry_bulb_temperature_c"]))
        self.assertFalse(pd.isna(hourly.iloc[1]["dry_bulb_temperature_c"]))

    def test_native_diagnostic_frame_is_identity_cached_without_mutating_source(self) -> None:
        dataset = dataset_fixture()
        source_columns = list(dataset.data.columns)
        first = prepare_historical_native_diagnostic_frame(dataset)
        second = prepare_historical_native_diagnostic_frame(dataset)
        self.assertIs(first, second)
        self.assertEqual(list(dataset.data.columns), source_columns)
        self.assertNotIn("month_index", dataset.data.columns)


class NativeDiagnosticsUi065ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_data_quality_uses_native_frame_and_bypasses_analysis_filter(self) -> None:
        self.assertIn("prepare_historical_native_diagnostic_frame", self.source)
        self.assertIn('if page == "Data Quality":\n            full_df = prepare_historical_native_diagnostic_frame(dataset)', self.source)
        self.assertIn(
            'if page == "Data Quality":\n        # Source-quality diagnostics must not interpret intentionally excluded',
            self.source,
        )
        self.assertIn('filtered_df = full_df\n        st.session_state["_active_filtered_export_df"] = full_df', self.source)
        self.assertIn("global analysis Data filter is intentionally not applied", self.source)

    def test_ui_distinguishes_source_and_analysis_cadence(self) -> None:
        self.assertIn('st.caption(f"Source cadence: {source_interval:g} min")', self.source)
        self.assertIn('st.caption(f"Canonical analysis cadence: {analysis_interval:g} min")', self.source)
        self.assertIn("source {source_interval:g} min → canonical analysis {analysis_interval:g} min", self.source)
        self.assertIn("Source records in loaded interval", self.source)
        self.assertIn("canonical hourly analysis series", self.source)

    def test_precipitation_ui_uses_native_records_only_for_native_occurrence_metrics(self) -> None:
        # 0.6.5 correctly stopped calling *hourly analysis rows* source records.
        # 0.7 adds an explicit dual-resolution route, so source-record wording is
        # again correct for the provider-native occurrence metric only.
        self.assertIn("Precipitation-record occurrence", self.source)
        self.assertIn("Source records meeting threshold", self.source)
        self.assertIn("provider/source records at the active native cadence", self.source)
        self.assertIn("record-occurrence metric, not rainfall duration", self.source)
        self.assertIn("Dual-resolution semantics", self.source)
        self.assertIn("true native-interval precipitation extremes", self.source)
        self.assertNotIn("Precipitation-interval occurrence", self.source)
        self.assertNotIn("Analysis intervals meeting threshold", self.source)


if __name__ == "__main__":
    unittest.main()
