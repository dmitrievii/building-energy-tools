from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.analysis_clock import LOCAL_CIVIL_TIME, prepare_analysis_calendar
from epw_climate_analyzer.canonical_hourly import canonical_hourly_analysis_frame
from epw_climate_analyzer.geosphere import (
    GEOSPHERE_RESOURCES,
    GeoSphereStation,
    build_canonical_station_dataset,
    estimate_request_datapoints,
    parse_code_lists,
    parse_parameters,
    supported_parameter_mapping,
)
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties
from epw_climate_analyzer.solar import (
    derive_direct_normal_radiation,
    ensure_solar_radiation_components,
    surface_irradiance_series,
    variable_origin,
)


class SourceParityEngineTests(unittest.TestCase):
    def test_dni_is_derived_from_horizontal_balance_and_marked_calculated(self) -> None:
        index = pd.date_range("2026-06-21T10:00:00Z", periods=2, freq="h")
        frame = pd.DataFrame(
            {
                "global_horizontal_radiation_wh_m2": [800.0, 500.0],
                "diffuse_horizontal_radiation_wh_m2": [200.0, 100.0],
                "solar_apparent_zenith_deg": [60.0, 0.0],
            },
            index=index,
        )
        derived = derive_direct_normal_radiation(frame)
        self.assertAlmostEqual(float(derived.iloc[0]["direct_normal_radiation_wh_m2"]), 1200.0, places=6)
        self.assertAlmostEqual(float(derived.iloc[1]["direct_normal_radiation_wh_m2"]), 400.0, places=6)
        self.assertTrue(bool(derived["direct_normal_radiation_is_calculated"].all()))
        self.assertIn("calculated", variable_origin(derived, "direct_normal_radiation_wh_m2"))

    def test_measured_dni_is_never_overwritten(self) -> None:
        frame = pd.DataFrame(
            {
                "global_horizontal_radiation_wh_m2": [800.0],
                "diffuse_horizontal_radiation_wh_m2": [200.0],
                "direct_normal_radiation_wh_m2": [777.0],
                "solar_apparent_zenith_deg": [60.0],
            },
            index=pd.date_range("2026-06-21T10:00:00Z", periods=1, freq="h"),
        )
        resolved = derive_direct_normal_radiation(frame)
        self.assertEqual(float(resolved.iloc[0]["direct_normal_radiation_wh_m2"]), 777.0)

    def test_near_horizon_dni_is_left_missing_not_exploded(self) -> None:
        frame = pd.DataFrame(
            {
                "global_horizontal_radiation_wh_m2": [100.0],
                "diffuse_horizontal_radiation_wh_m2": [20.0],
                "solar_apparent_zenith_deg": [89.0],
            },
            index=pd.date_range("2026-06-21T03:00:00Z", periods=1, freq="h"),
        )
        resolved = derive_direct_normal_radiation(frame)
        self.assertTrue(pd.isna(resolved.iloc[0]["direct_normal_radiation_wh_m2"]))

    def test_solar_geometry_operates_on_real_utc_historical_index(self) -> None:
        frame = pd.DataFrame(
            {
                "global_horizontal_radiation_wh_m2": [500.0],
                "diffuse_horizontal_radiation_wh_m2": [100.0],
            },
            index=pd.date_range("2026-07-01T14:00:00Z", periods=1, freq="h"),
        )
        result = ensure_solar_radiation_components(
            frame,
            latitude=47.07,
            longitude=15.44,
            elevation_m=350.0,
            timezone_name="Europe/Vienna",
        )
        self.assertIn("solar_azimuth_deg", result)
        self.assertIn("solar_elevation_deg", result)
        self.assertIn("direct_normal_radiation_wh_m2", result)
        self.assertGreater(float(result.iloc[0]["solar_elevation_deg"]), 0.0)

    def test_source_albedo_is_used_by_poa(self) -> None:
        index = pd.date_range("2026-06-21T12:00:00Z", periods=1, freq="h")
        base = pd.DataFrame(
            {
                "solar_apparent_zenith_deg": [30.0],
                "solar_azimuth_deg": [180.0],
                "direct_normal_radiation_wh_m2": [600.0],
                "global_horizontal_radiation_wh_m2": [700.0],
                "diffuse_horizontal_radiation_wh_m2": [180.0],
            },
            index=index,
        )
        low = base.assign(albedo=0.1)
        high = base.assign(albedo=0.8)
        poa_low = float(surface_irradiance_series(low, 90.0, 180.0).iloc[0])
        poa_high = float(surface_irradiance_series(high, 90.0, 180.0).iloc[0])
        self.assertGreater(poa_high, poa_low)

    def test_missing_dew_point_is_derived_but_source_value_is_preserved(self) -> None:
        index = pd.date_range("2026-01-01", periods=2, freq="h")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [20.0, 20.0],
                "relative_humidity_pct": [50.0, 50.0],
                "atmospheric_station_pressure_pa": [101325.0, 101325.0],
                "dew_point_temperature_c": [5.0, np.nan],
            },
            index=index,
        )
        result = add_psychrometric_properties(frame)
        self.assertEqual(float(result.iloc[0]["dew_point_temperature_c"]), 5.0)
        self.assertFalse(bool(result.iloc[0]["dew_point_temperature_is_calculated"]))
        self.assertTrue(bool(result.iloc[1]["dew_point_temperature_is_calculated"]))
        self.assertGreater(float(result.iloc[1]["dew_point_temperature_c"]), 0.0)

    def test_local_civil_analysis_clock_keeps_instant_and_changes_calendar_hour(self) -> None:
        index = pd.DatetimeIndex([pd.Timestamp("2026-07-01T14:00:00Z")])
        frame = pd.DataFrame({"x": [1.0]}, index=index)
        local = prepare_analysis_calendar(
            frame,
            mode=LOCAL_CIVIL_TIME,
            local_timezone_name="Europe/Vienna",
            source_timezone_name="UTC",
        )
        self.assertEqual(int(local.iloc[0]["hour_of_day"]), 16)
        self.assertEqual(local.index[0].tz_convert("UTC"), index[0])

    def test_hourly_geosphere_resource_uses_hourly_request_cadence_and_fast_path(self) -> None:
        self.assertIn("klima-v2-1h", GEOSPHERE_RESOURCES)
        start = pd.Timestamp("2026-01-01T00:00:00Z")
        end = pd.Timestamp("2026-01-01T03:00:00Z")
        self.assertEqual(
            estimate_request_datapoints(start, end, 2, resource_id="klima-v2-1h"),
            8,
        )
        hourly = pd.DataFrame(
            {"dry_bulb_temperature_c": [1.0, 2.0, 3.0, 4.0]},
            index=pd.date_range(start, periods=4, freq="h"),
        )
        normalized = canonical_hourly_analysis_frame(hourly, source_interval_minutes=60)
        self.assertEqual(len(normalized), 4)
        self.assertEqual(normalized["dry_bulb_temperature_c"].tolist(), [1.0, 2.0, 3.0, 4.0])

    def test_hourly_resource_mapping_uses_ff_and_radiation_scale_one(self) -> None:
        metadata = {
            "parameters": [
                {"name": "tl", "long_name": "Temperature", "unit": "°C"},
                {"name": "rf", "long_name": "RH", "unit": "%"},
                {"name": "ff", "long_name": "Wind", "unit": "m/s"},
                {"name": "cglo", "long_name": "GHI", "unit": "W/m²"},
                {"name": "chim", "long_name": "DHI", "unit": "W/m²"},
            ],
            "stations": [{"id": 1, "name": "Test", "geometry": {"coordinates": [15.0, 47.0]}}],
        }
        mapping = supported_parameter_mapping(metadata, resource_id="klima-v2-1h")
        self.assertEqual(mapping["ff"].canonical_name, "wind_speed_m_s")
        self.assertEqual(mapping["cglo"].scale, 1.0)
        self.assertEqual(mapping["chim"].scale, 1.0)

    def test_quality_code_lists_and_references_are_parsed(self) -> None:
        metadata = {
            "parameters": [
                {"name": "tl", "unit": "°C"},
                {"name": "tl_flag", "unit": "code", "code_list_ref": "quality"},
            ],
            "code_lists": {
                "quality": {
                    "values": [
                        {"code": 0, "description": "unchecked"},
                        {"code": 20, "description": "manually checked"},
                    ]
                }
            },
        }
        parsed = parse_parameters(metadata)
        self.assertEqual(parsed["tl_flag"].code_list_ref, "quality")
        codes = parse_code_lists(metadata)
        self.assertEqual(codes["quality"][20], "manually checked")

    def test_hourly_dataset_provenance_retains_resource_identity(self) -> None:
        metadata = {
            "parameters": [{"name": "tl", "long_name": "Temperature", "unit": "°C"}],
            "stations": [{"id": 1, "name": "Test", "geometry": {"coordinates": [15.0, 47.0]}}],
        }
        mapping = supported_parameter_mapping(metadata, resource_id="klima-v2-1h")
        provider = pd.DataFrame(
            {"tl": [1.0, 2.0]},
            index=pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="h"),
        )
        climate = build_canonical_station_dataset(
            station=GeoSphereStation("1", "Test", 47.0, 15.0),
            provider_frame=provider,
            mapping=mapping,
            resource_id="klima-v2-1h",
            metadata=metadata,
        )
        self.assertEqual(climate.temporal.native_interval_minutes, 60)
        self.assertIn("klima-v2-1h", climate.provenance.dataset)
        self.assertIn("GeoSphere 1 h", climate.display_name)


if __name__ == "__main__":
    unittest.main()
