from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from epw_climate_analyzer.climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
)
from epw_climate_analyzer.historical import clear_historical_hourly_cache, prepare_historical_analysis_frame


class CanonicalHourlyCache065Tests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_historical_hourly_cache()

    @staticmethod
    def _dataset() -> CanonicalClimateDataset:
        index = pd.date_range("2026-01-01T00:00:00Z", periods=12, freq="10min", name="timestamp")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": list(range(12)),
                "relative_humidity_pct": [60.0] * 12,
            },
            index=index,
        )
        frame.attrs["canonical_native_interval_minutes"] = 10
        return CanonicalClimateDataset(
            climate_id="test:cache",
            display_name="Cache fixture",
            data=frame,
            location=ClimateLocation(latitude=47.0, longitude=15.0, city="Graz", country="Austria"),
            temporal=ClimateTemporalMetadata(
                native_interval_minutes=10,
                calendar_mode="historical",
                timezone_name="UTC",
                interval_semantics="unknown",
            ),
            provenance=ClimateProvenance(
                provider="test",
                dataset="test",
                source_format="fixture",
                source_name="cache fixture",
                retrieval_time_utc="2026-09-16T17:00:00Z",
            ),
        )

    def test_same_active_dataset_is_hourly_normalized_only_once(self) -> None:
        clear_historical_hourly_cache()
        dataset = self._dataset()

        from epw_climate_analyzer import historical

        original = historical.canonical_hourly_analysis_frame
        with patch(
            "epw_climate_analyzer.historical.canonical_hourly_analysis_frame",
            wraps=original,
        ) as normalizer:
            first = prepare_historical_analysis_frame(dataset)
            second = prepare_historical_analysis_frame(dataset)

        self.assertEqual(normalizer.call_count, 1)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(first.attrs["canonical_native_interval_minutes"], 60)
        self.assertEqual(second.attrs["canonical_native_interval_minutes"], 60)


if __name__ == "__main__":
    unittest.main()
