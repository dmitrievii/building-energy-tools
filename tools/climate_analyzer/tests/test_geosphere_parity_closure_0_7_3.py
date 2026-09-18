from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
)
from epw_climate_analyzer.decisions import passive_strategy_monthly, passive_strategy_table
from epw_climate_analyzer.historical import prepare_historical_analysis_frame
from epw_climate_analyzer.historical_capabilities import available_historical_pages


class GeoSphereParityClosure073Tests(unittest.TestCase):
    @staticmethod
    def _dataset(*, include_ghi: bool = False) -> CanonicalClimateDataset:
        index = pd.date_range("2026-07-01T00:00:00Z", periods=12, freq="10min", name="timestamp")
        data: dict[str, list[float]] = {
            "dry_bulb_temperature_c": [20.0, 21.0, 22.0, 23.0, 24.0, 25.0] * 2,
            "relative_humidity_pct": [60.0, 61.0, 62.0, 63.0, 64.0, 65.0] * 2,
            "atmospheric_station_pressure_pa": [100000.0] * 12,
            "wind_speed_m_s": [2.0] * 12,
            "wind_direction_deg": [180.0] * 12,
        }
        if include_ghi:
            data["global_horizontal_radiation_wh_m2"] = [50.0] * 12
        frame = pd.DataFrame(data, index=index)
        frame.attrs["canonical_native_interval_minutes"] = 10
        frame.attrs["canonical_calendar_mode"] = "historical"
        frame.attrs["canonical_timezone_name"] = "UTC"
        return CanonicalClimateDataset(
            climate_id="test:geosphere-073",
            display_name="GeoSphere 0.7.3 fixture",
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
                source_years=(2026,),
            ),
            provenance=ClimateProvenance(
                provider="GeoSphere Austria",
                dataset="klima-v2-10min",
                source_format="fixture",
                source_name="0.7.3 parity fixture",
            ),
        )

    def test_historical_pages_expose_nv_and_hvac_when_temperature_and_humidity_exist(self) -> None:
        pages = set(available_historical_pages(self._dataset().data))
        self.assertIn("Natural Ventilation", pages)
        self.assertIn("HVAC and Passive Design", pages)

    def test_historical_pages_fail_closed_without_humidity(self) -> None:
        dataset = self._dataset()
        frame = dataset.data.drop(columns=["relative_humidity_pct"])
        pages = set(available_historical_pages(frame))
        self.assertNotIn("Natural Ventilation", pages)
        self.assertNotIn("HVAC and Passive Design", pages)

    def test_historical_hourly_preparation_supplies_psychrometrics_and_degree_metrics(self) -> None:
        prepared = prepare_historical_analysis_frame(
            self._dataset(),
            include_psychrometrics=True,
            fallback_pressure_pa=100000.0,
        )
        self.assertEqual(len(prepared), 2)
        for column in (
            "humidity_ratio_g_kg",
            "moist_air_enthalpy_kj_kg",
            "moist_air_density_kg_m3",
            "heating_degree_hours_kh",
            "cooling_degree_hours_kh",
        ):
            self.assertIn(column, prepared.columns)
            self.assertTrue(pd.to_numeric(prepared[column], errors="coerce").notna().all())
        self.assertEqual(prepared.attrs["canonical_native_interval_minutes"], 60)
        self.assertEqual(prepared.attrs["canonical_source_interval_minutes"], 10)

    def test_passive_strategy_table_omits_solar_shading_without_ghi(self) -> None:
        prepared = prepare_historical_analysis_frame(
            self._dataset(include_ghi=False),
            include_psychrometrics=True,
            fallback_pressure_pa=100000.0,
        )
        table = passive_strategy_table(prepared)
        monthly = passive_strategy_monthly(prepared)
        self.assertNotIn("Solar shading likely useful", set(table["strategy"]))
        self.assertNotIn("Shading", monthly.columns)

    def test_passive_strategy_table_restores_solar_shading_when_measured_ghi_exists(self) -> None:
        prepared = prepare_historical_analysis_frame(
            self._dataset(include_ghi=True),
            include_psychrometrics=True,
            fallback_pressure_pa=100000.0,
        )
        table = passive_strategy_table(prepared)
        monthly = passive_strategy_monthly(prepared)
        self.assertIn("Solar shading likely useful", set(table["strategy"]))
        self.assertIn("Shading", monthly.columns)


if __name__ == "__main__":
    unittest.main()
