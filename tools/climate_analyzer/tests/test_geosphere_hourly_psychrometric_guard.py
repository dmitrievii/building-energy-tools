"""Numerical/source-parity regression for the GeoSphere hourly humidity incident."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import psychrolib

from epw_climate_analyzer import psychrometrics, psychrometric_consistency, runtime_module_guard
from epw_climate_analyzer.geosphere import (
    GeoSphereStation,
    build_canonical_station_dataset,
    supported_parameter_mapping,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties


psychrolib.SetUnitSystem(psychrolib.SI)


def _geosphere_dataset(resource_id: str):
    metadata = {
        "parameters": [
            {"name": "tl", "long_name": "Temperature", "unit": "°C"},
            {"name": "rf", "long_name": "Relative humidity", "unit": "%"},
            {"name": "p", "long_name": "Station pressure", "unit": "hPa"},
        ],
        "stations": [
            {"id": "11240", "name": "Graz test", "geometry": {"coordinates": [15.45, 47.08]}}
        ],
    }
    ten_min = resource_id == "klima-v2-10min"
    count = 6 if ten_min else 1
    cadence = "10min" if ten_min else "h"
    frame = pd.DataFrame(
        {"tl": [20.0] * count, "rf": [50.0] * count, "p": [1013.25] * count},
        index=pd.date_range("2026-07-01T00:00:00Z", periods=count, freq=cadence),
    )
    mapping = supported_parameter_mapping(metadata, resource_id=resource_id)
    return build_canonical_station_dataset(
        station=GeoSphereStation("11240", "Graz test", 47.08, 15.45, 350.0),
        provider_frame=frame,
        mapping=mapping,
        resource_id=resource_id,
        metadata=metadata,
    )


class GeoSphereHourlyPsychrometricRegressionTests(unittest.TestCase):
    def test_1h_native_fields_to_finite_physical_humidity_ratio(self) -> None:
        climate = _geosphere_dataset("klima-v2-1h")
        self.assertAlmostEqual(float(climate.data.iloc[0]["atmospheric_station_pressure_pa"]), 101325.0)
        self.assertAlmostEqual(float(climate.data.iloc[0]["relative_humidity_pct"]), 50.0)
        result = prepare_historical_analysis_frame(
            climate, include_psychrometrics=True, fallback_pressure_pa=101325.0,
        )
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(float(result.iloc[0]["vapor_pressure_pa"]), 1169.4, delta=1.0)
        self.assertAlmostEqual(float(result.iloc[0]["humidity_ratio_g_kg"]), 7.2617, delta=0.02)
        self.assertAlmostEqual(
            float(result.iloc[0]["humidity_ratio_g_kg"]),
            1000.0 * psychrolib.GetHumRatioFromRelHum(20.0, 0.5, 101325.0),
            delta=1e-5,
        )
        self.assertLess(float(result.iloc[0]["humidity_ratio_g_kg"]), 50.0)
        self.assertTrue(np.isfinite(float(result.iloc[0]["moist_air_enthalpy_kj_kg"])))
        self.assertTrue(np.isfinite(float(result.iloc[0]["wet_bulb_temperature_c"])))

    def test_derived_variable_provenance_is_materialized(self) -> None:
        """A missing helper formerly caused a NameError after valid physics."""
        hourly = prepare_historical_analysis_frame(
            _geosphere_dataset("klima-v2-1h"), include_psychrometrics=True,
        )
        origins = hourly.attrs.get("canonical_variable_origin", {})
        self.assertIn("humidity_ratio_g_kg", origins)
        self.assertIn("dew_point_temperature_c", origins)
        self.assertIn("wet_bulb_temperature_c", origins)
        self.assertIn("calculated", str(origins["humidity_ratio_g_kg"]))

    def test_1h_and_10min_sources_have_identical_physical_hourly_state(self) -> None:
        hourly = prepare_historical_analysis_frame(
            _geosphere_dataset("klima-v2-1h"), include_psychrometrics=True
        )
        ten_min = prepare_historical_analysis_frame(
            _geosphere_dataset("klima-v2-10min"), include_psychrometrics=True
        )
        self.assertEqual(len(hourly), 1)
        self.assertEqual(len(ten_min), 1)
        for name in (
            "dry_bulb_temperature_c", "relative_humidity_pct",
            "atmospheric_station_pressure_pa", "vapor_pressure_pa",
            "humidity_ratio_kg_kg", "humidity_ratio_g_kg",
            "moist_air_enthalpy_kj_kg",
        ):
            self.assertAlmostEqual(float(hourly.iloc[0][name]), float(ten_min.iloc[0][name]), places=10)

    def test_corrupt_psychrolib_saturation_cannot_corrupt_derived_humidity(self) -> None:
        # The foundational saturation pressure is now calculated directly from
        # the ASHRAE equations, independently of mutable PsychroLib state.
        frame = pd.DataFrame({
            "dry_bulb_temperature_c": [20.0],
            "relative_humidity_pct": [50.0],
            "atmospheric_station_pressure_pa": [101325.0],
        })
        with patch.object(psychrolib, "GetSatVapPres", return_value=100000.0):
            result = add_psychrometric_properties(frame)
        self.assertAlmostEqual(float(result.iloc[0]["saturation_vapor_pressure_pa"]), 2338.8037, delta=0.1)
        self.assertAlmostEqual(float(result.iloc[0]["humidity_ratio_g_kg"]), 7.2617, delta=0.02)

    def test_near_zero_vapor_pressure_denominator_is_not_clamped(self) -> None:
        frame = pd.DataFrame({
            "dry_bulb_temperature_c": [85.0],
            "relative_humidity_pct": [100.0],
            "atmospheric_station_pressure_pa": [30000.0],
        })
        with self.assertRaisesRegex(ValueError, "vapour pressure equals"):
            add_psychrometric_properties(frame)

    def test_bad_relative_humidity_is_missing_not_saturated(self) -> None:
        frame = pd.DataFrame({
            "dry_bulb_temperature_c": [20.0, 20.0],
            "relative_humidity_pct": [150.0, 50.0],
            "atmospheric_station_pressure_pa": [101325.0, 101325.0],
        })
        result = add_psychrometric_properties(frame)
        self.assertTrue(np.isnan(result.iloc[0]["humidity_ratio_g_kg"]))
        self.assertAlmostEqual(float(result.iloc[1]["humidity_ratio_g_kg"]), 7.2617, delta=0.02)

    def test_bounded_saturation_bypasses_corruption_triggered_by_32768_elements(self) -> None:
        # The previously reported full dataset contains 33,045 hourly slots.
        t = np.resize(np.array([-9.8, 0.0, 4.8, 24.1, 39.5], dtype=float), 33045)
        reference = psychrometric_consistency._ashrae_saturation_pressure_pa(t)
        original = psychrometric_consistency._ashrae_saturation_pressure_pa
        calls = []

        def long_array_corruption(temps):
            calls.append(len(temps))
            out = original(temps).copy()
            if len(out) >= 32768:
                out[32768:] = 100000.0
            return out

        with patch.object(psychrometric_consistency, "_ashrae_saturation_pressure_pa", side_effect=long_array_corruption):
            repaired, count = psychrometric_consistency.stable_saturation_pressure_pa(t)
        self.assertEqual(count, 0)
        self.assertEqual(sum(calls), len(t))
        self.assertLessEqual(max(calls), 8192)
        np.testing.assert_allclose(repaired, reference, rtol=0, atol=1e-8)

        shorter, short_recovery = psychrometric_consistency.stable_saturation_pressure_pa(t[:32709])
        self.assertEqual(short_recovery, 0)
        np.testing.assert_allclose(shorter, reference[:32709], rtol=0, atol=1e-8)

    def test_scalar_recovery_in_a_long_series_uses_local_reference_only(self) -> None:
        t = np.resize(np.array([-9.8, 0.0, 4.8, 24.1, 39.5], dtype=float), 33045)
        reference = psychrometric_consistency._ashrae_saturation_pressure_pa(t)
        original = psychrometric_consistency._ashrae_saturation_pressure_pa

        def corrupt_one_per_chunk(temps):
            out = original(temps).copy()
            out[0] = 100000.0
            return out

        with patch.object(psychrometric_consistency, "_ashrae_saturation_pressure_pa", side_effect=corrupt_one_per_chunk):
            repaired, count = psychrometric_consistency.stable_saturation_pressure_pa(t)
        self.assertEqual(count, 5)
        np.testing.assert_allclose(repaired, reference, rtol=0, atol=1e-8)

    def test_scalar_recovery_occurs_before_humidity_ratio_and_reports_rows(self) -> None:
        frame = pd.DataFrame({
            "dry_bulb_temperature_c": [4.8, 5.1, 4.6],
            "relative_humidity_pct": [95.0, 94.0, 96.0],
            "atmospheric_station_pressure_pa": [99770.0, 99780.0, 99760.0],
        })
        expected = add_psychrometric_properties(frame)
        original = psychrometric_consistency._ashrae_saturation_pressure_pa
        with patch.object(
            psychrometric_consistency, "_ashrae_saturation_pressure_pa",
            side_effect=lambda t: np.full(len(t), 100000.0),
        ):
            observed = add_psychrometric_properties(frame)
        np.testing.assert_allclose(
            observed["humidity_ratio_g_kg"], expected["humidity_ratio_g_kg"], rtol=0, atol=1e-9,
        )
        self.assertEqual(observed.attrs["psychrometric_saturation_integrity"]["recovered_rows"], 3)
        self.assertLess(float(observed["humidity_ratio_g_kg"].max()), 20.0)
        self.assertAlmostEqual(float(observed["humidity_ratio_g_kg"].iloc[0]), 5.137, delta=0.03)
        self.assertNotIn("psychrometric_saturation_integrity", expected.attrs)

    def test_stale_consistency_module_reloads_all_bound_psychrometric_functions(self) -> None:
        from epw_climate_analyzer import historical, psychrometric_consistency
        old_function = psychrometric_consistency._ashrae_saturation_pressure_pa
        with patch.object(psychrometric_consistency, "_RUNTIME_SOURCE_SHA256", "obsolete"):
            runtime_module_guard.ensure_current_psychrometric_runtime()
            self.assertFalse(runtime_module_guard._stale_source(psychrometric_consistency))
            self.assertFalse(runtime_module_guard._stale_source(psychrometrics))
            self.assertFalse(runtime_module_guard._stale_source(historical))
            self.assertIsNot(psychrometric_consistency._ashrae_saturation_pressure_pa, old_function)
            self.assertIs(
                psychrometrics.stable_saturation_pressure_pa,
                psychrometric_consistency.stable_saturation_pressure_pa,
            )
            self.assertIs(
                historical.reconcile_historical_psychrometrics,
                psychrometric_consistency.reconcile_historical_psychrometrics,
            )

    def test_stale_source_fingerprint_refreshes_core_and_historical_binding(self) -> None:
        # A redeploy changes the source on disk while an old Python module stays
        # in sys.modules. The live guard must correct the imported function too.
        self.assertFalse(runtime_module_guard._stale_source(psychrometrics))
        with patch.object(psychrometrics, "_RUNTIME_SOURCE_SHA256", "obsolete"):
            runtime_module_guard.ensure_current_psychrometric_runtime()
            from epw_climate_analyzer import historical
            self.assertFalse(runtime_module_guard._stale_source(psychrometrics))
            self.assertFalse(runtime_module_guard._stale_source(historical))
            self.assertIs(historical.add_psychrometric_properties, psychrometrics.add_psychrometric_properties)


if __name__ == "__main__":
    unittest.main()
