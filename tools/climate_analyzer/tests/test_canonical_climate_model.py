from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.climate_model import (
    CANONICAL_VARIABLES,
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
    aggregation_semantics_for,
    build_canonical_dataset,
    canonical_from_epw,
    infer_native_resolution_minutes,
    map_provider_frame,
    unit_family_for,
)
from epw_climate_analyzer.epw_parser import EpwFile, EpwLocation


class CanonicalClimateModelTests(unittest.TestCase):
    def _location(self) -> ClimateLocation:
        return ClimateLocation(
            latitude=47.0707,
            longitude=15.4395,
            elevation_m=353.0,
            city="Graz",
            state="Styria",
            country="Austria",
            station_id="TEST",
        )

    def _provenance(self) -> ClimateProvenance:
        return ClimateProvenance(
            provider="GeoSphere Austria",
            dataset="test observations",
            source_format="API",
            source_name="station-test",
            source_reference="provider:test",
            provider_station_id="TEST",
        )

    def test_canonical_registry_carries_physical_aggregation_semantics(self) -> None:
        self.assertEqual(aggregation_semantics_for("dry_bulb_temperature_c"), "mean")
        self.assertEqual(aggregation_semantics_for("global_horizontal_radiation_wh_m2"), "sum")
        self.assertEqual(aggregation_semantics_for("liquid_precipitation_depth_mm"), "sum")
        self.assertEqual(aggregation_semantics_for("wind_direction_deg"), "circular mean")
        self.assertEqual(unit_family_for("dry_bulb_temperature_c"), "temperature")
        self.assertEqual(unit_family_for("dew_point_temperature_c"), "temperature")
        self.assertIn("atmospheric_station_pressure_pa", CANONICAL_VARIABLES)

    def test_historical_10_minute_dataset_preserves_real_timestamps(self) -> None:
        index = pd.date_range("2024-07-03 12:00", periods=6, freq="10min", tz="Europe/Vienna")
        frame = pd.DataFrame(
            {
                "temp": [25.0, 25.2, 25.5, 25.8, 26.0, 26.1],
                "wind": [1.0, 1.2, 1.1, 1.3, 1.4, 1.2],
            },
            index=index,
        )
        temporal = ClimateTemporalMetadata(
            native_interval_minutes=10,
            calendar_mode="historical",
            timezone_name="Europe/Vienna",
            interval_semantics="instantaneous",
        )
        climate = build_canonical_dataset(
            climate_id="geosphere-test",
            display_name="Graz observations",
            data=frame,
            location=self._location(),
            temporal=temporal,
            provenance=self._provenance(),
            column_map={
                "temp": "dry_bulb_temperature_c",
                "wind": "wind_speed_m_s",
            },
            keep_unmapped=False,
        )
        self.assertEqual(climate.temporal.native_interval_minutes, 10)
        self.assertEqual(infer_native_resolution_minutes(climate.data.index), 10)
        self.assertEqual(climate.start, index[0])
        self.assertEqual(climate.end, index[-1])
        self.assertEqual(climate.data.index.year.tolist(), [2024] * 6)
        self.assertEqual(
            set(climate.available_canonical_variables),
            {"dry_bulb_temperature_c", "wind_speed_m_s"},
        )

    def test_explicit_source_cadence_survives_missing_observations(self) -> None:
        # A measured 10-minute source can contain gaps. The canonical source
        # cadence remains 10 minutes and must not be rewritten to the observed
        # gap spacing.
        index = pd.DatetimeIndex(
            [
                "2024-01-01 00:00",
                "2024-01-01 00:20",
                "2024-01-01 00:40",
            ]
        )
        frame = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 0.5, 1.0]}, index=index)
        temporal = ClimateTemporalMetadata(
            native_interval_minutes=10,
            calendar_mode="historical",
            timezone_name="UTC",
            interval_semantics="instantaneous",
        )
        climate = build_canonical_dataset(
            climate_id="gappy-10min",
            display_name="Gappy 10-minute source",
            data=frame,
            location=self._location(),
            temporal=temporal,
            provenance=self._provenance(),
        )
        self.assertEqual(climate.temporal.native_interval_minutes, 10)
        self.assertEqual(infer_native_resolution_minutes(climate.data.index), 20)

    def test_provider_mapping_rejects_unknown_canonical_targets(self) -> None:
        frame = pd.DataFrame(
            {"T": [20.0]},
            index=pd.DatetimeIndex(["2024-01-01 00:00"]),
        )
        with self.assertRaisesRegex(ValueError, "Unknown canonical climate columns"):
            map_provider_frame(frame, {"T": "made_up_temperature"})

    def test_duplicate_timestamps_fail_closed(self) -> None:
        frame = pd.DataFrame(
            {"dry_bulb_temperature_c": [1.0, 2.0]},
            index=pd.DatetimeIndex(["2024-01-01 00:00", "2024-01-01 00:00"]),
        )
        with self.assertRaisesRegex(ValueError, "timestamps must be unique"):
            CanonicalClimateDataset(
                climate_id="duplicate",
                display_name="Duplicate timestamps",
                data=frame,
                location=self._location(),
                temporal=ClimateTemporalMetadata(
                    native_interval_minutes=60,
                    calendar_mode="historical",
                    timezone_name="UTC",
                    interval_semantics="interval_start",
                ),
                provenance=self._provenance(),
            )

    def test_epw_adapter_marks_typical_year_and_preserves_source_years(self) -> None:
        index = pd.date_range("2026-01-01 00:00", periods=24, freq="h")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": range(24),
                "epw_source_year": [1999] * 24,
            },
            index=index,
        )
        frame.attrs["timezone_name"] = "Etc/GMT-1"
        frame.attrs["typical_year"] = 2026
        frame.attrs["source_years"] = [1999, 2001]
        epw = EpwFile(
            location=EpwLocation(
                city="Graz",
                state="Styria",
                country="Austria",
                source="Synthetic test",
                wmo="112400",
                latitude=47.07,
                longitude=15.44,
                utc_offset=1.0,
                elevation_m=353.0,
            ),
            header_lines=["LOCATION,Graz"],
            data=frame,
            name="graz-test.epw",
        )
        climate = canonical_from_epw(
            epw,
            climate_id="graz-epw",
            display_name="Graz EPW",
            source_reference="Climate.OneBuilding test source",
        )
        self.assertEqual(climate.temporal.calendar_mode, "typical_year")
        self.assertEqual(climate.temporal.canonical_year, 2026)
        self.assertEqual(climate.temporal.source_years, (1999, 2001))
        self.assertEqual(climate.temporal.native_interval_minutes, 60)
        self.assertEqual(climate.temporal.interval_semantics, "interval_start")
        self.assertEqual(climate.location.station_id, "112400")
        self.assertEqual(climate.provenance.source_format, "EPW")
        self.assertIn("Climate.OneBuilding", climate.provenance.source_reference)
        self.assertEqual(climate.data.index.year.unique().tolist(), [2026])


if __name__ == "__main__":
    unittest.main()
