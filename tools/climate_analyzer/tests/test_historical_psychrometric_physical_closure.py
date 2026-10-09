"""Post-materialization physical-closure regression for the 32,768-hour boundary.

The reported incident: full GeoSphere hourly export has 33,045 timestamps
(32,941 valid psychrometric states), an apparently good short period starts
15 January 2023 with 32,709 timestamps, and contaminated long output has
humidity_ratio_kg_kg == degree_of_saturation over all 32,941 valid rows.
"""

from __future__ import annotations

from pathlib import Path
import ast
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import psychrolib

from epw_climate_analyzer import psychrometric_consistency
from epw_climate_analyzer import psychrometric_consistency
from epw_climate_analyzer.charts import profile_ribbon_chart
from epw_climate_analyzer.psychrometric_consistency import reconcile_historical_psychrometrics
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties


psychrolib.SetUnitSystem(psychrolib.SI)


def climate_source(count: int) -> pd.DataFrame:
    times = pd.date_range("2023-01-01T00:00:00Z", periods=count, freq="h")
    tick = np.arange(count)
    return pd.DataFrame(
        {
            "dry_bulb_temperature_c": 4.8 + (tick % 14) * 0.5,
            "relative_humidity_pct": 95.0 - (tick % 65),
            "atmospheric_station_pressure_pa": 99770.0 + (tick % 30) * 5.0,
        },
        index=times,
    )


class PsychrometricPhysicalClosureTests(unittest.TestCase):
    def test_uncontaminated_33045_record_frame_is_unchanged(self) -> None:
        frame = add_psychrometric_properties(climate_source(33045))
        self.assertEqual(len(frame), 33045)
        self.assertIs(reconcile_historical_psychrometrics(frame), frame)
        self.assertNotIn("psychrometric_physical_closure", frame.attrs)

    def test_33045_hours_and_104_missing_rh_do_not_run_a_second_reference_check(self) -> None:
        # Actual full export: 33045 hours, 32941 valid T/RH states. A
        # redundant second Magnus check used the differently sized 32941-row
        # mask; simulated length-sensitive reference state raised ValueError.
        # Missing provider RH must be set BEFORE calculating any derived
        # properties. Previously this test created finite derived values and
        # *then* removed RH, correctly triggering repair instead of identity.
        source = climate_source(33045)
        source.iloc[:104, source.columns.get_loc("relative_humidity_pct")] = np.nan
        frame = add_psychrometric_properties(source, calculate_inverse=False)
        self.assertEqual(len(frame), 33045)
        self.assertEqual(int(frame["relative_humidity_pct"].notna().sum()), 32941)
        self.assertTrue(frame["humidity_ratio_g_kg"].iloc[:104].isna().all())
        # The authoritative scalar closure must not call the old vector
        # Magnus reference at all, regardless of valid-row count. It must
        # also preserve a clean frame by identity and retain missing RH.
        with patch.object(
            psychrometric_consistency, "_reference_saturation_pa",
            side_effect=AssertionError("obsolete vector Magnus called during scalar closure"),
        ) as old_reference:
            repaired = reconcile_historical_psychrometrics(frame)
        self.assertIs(repaired, frame)
        old_reference.assert_not_called()
        self.assertNotIn("psychrometric_physical_closure", repaired.attrs)
        self.assertTrue(repaired["humidity_ratio_g_kg"].iloc[:104].isna().all())
        self.assertTrue(np.isfinite(repaired["humidity_ratio_g_kg"].iloc[104:]).all())
        self.assertLess(float(repaired["humidity_ratio_g_kg"].max()), 20.0)

    def test_reproduces_long_export_corruption_and_repairs_all_derived_fields(self) -> None:
        for count in (32709, 32768, 33045):
            with self.subTest(count=count):
                source = climate_source(count)
                # Use the same saturation convention as the production engine,
                # without executing 2 x 33k wet-bulb/dewpoint inversions per case.
                sat = np.array([
                    psychrolib.GetSatVapPres(float(tv))
                    for tv in source["dry_bulb_temperature_c"].to_numpy()
                ])
                rh = source["relative_humidity_pct"].to_numpy() / 100.0
                pressure = source["atmospheric_station_pressure_pa"].to_numpy()
                vapor = rh * sat
                w = 0.621945 * vapor / (pressure - vapor)
                frame = source.copy()
                frame["saturation_vapor_pressure_pa"] = sat
                frame["vapor_pressure_pa"] = vapor
                frame["humidity_ratio_kg_kg"] = w
                frame["humidity_ratio_g_kg"] = w * 1000
                frame["moist_air_enthalpy_kj_kg"] = (
                    1.006 * frame["dry_bulb_temperature_c"] +
                    w * (2501.0 + 1.86 * frame["dry_bulb_temperature_c"])
                )
                frame["specific_volume_m3_kg"] = (
                    287.042 * (frame["dry_bulb_temperature_c"] + 273.15)
                    * (1.0 + 1.607858 * w) / pressure
                )
                frame["moist_air_density_kg_m3"] = (
                    (1.0 + w) / frame["specific_volume_m3_kg"]
                )
                frame["degree_of_saturation"] = (
                    w / (0.621945 * sat / (pressure - sat))
                )
                expected = frame.copy(deep=True)
                self.assertIs(reconcile_historical_psychrometrics(frame), frame)

                # Reproduce the exact cross-column symptom: both W_kg/kg and
                # degree of saturation contain the same thousands-scale value.
                corrupted = frame.copy()
                bad_kg = (40.0 + np.arange(count) % 6) * rh * 100.0
                corrupted["humidity_ratio_kg_kg"] = bad_kg
                corrupted["humidity_ratio_g_kg"] = bad_kg * 1000
                corrupted["degree_of_saturation"] = bad_kg
                corrupted["specific_volume_m3_kg"] = 17.5246711
                result = reconcile_historical_psychrometrics(corrupted)
                self.assertEqual(result.attrs["psychrometric_physical_closure"]["repaired_rows"], count)
                by_field = result.attrs["psychrometric_physical_closure"]["field_reconciliation_counts"]
                for corrupted_field in (
                    "humidity_ratio_kg_kg", "humidity_ratio_g_kg",
                    "degree_of_saturation", "specific_volume_m3_kg",
                ):
                    self.assertEqual(by_field[corrupted_field], count)
                # A repaired row need not imply every derived quantity was wrong.
                self.assertNotIn("moist_air_enthalpy_kj_kg", by_field)
                for field in (
                    "humidity_ratio_kg_kg", "humidity_ratio_g_kg",
                    "degree_of_saturation", "specific_volume_m3_kg",
                    "moist_air_enthalpy_kj_kg", "moist_air_density_kg_m3",
                    "vapor_pressure_pa",
                ):
                    np.testing.assert_allclose(result[field], expected[field], rtol=0, atol=1e-9)
                for name in source.columns:
                    pd.testing.assert_series_equal(result[name], source[name])
                self.assertGreater(result.attrs["psychrometric_physical_closure"]["maximum_humidity_ratio_deviation_g_kg"], 1e5)

    def test_corrupted_saturation_is_reconstructed_from_measured_temperature(self) -> None:
        good = add_psychrometric_properties(climate_source(3))
        tampered = good.copy()
        tampered["saturation_vapor_pressure_pa"] = 100000.0
        tampered["humidity_ratio_g_kg"] = 3_983_884.0
        repaired = reconcile_historical_psychrometrics(tampered)
        report = repaired.attrs["psychrometric_physical_closure"]
        self.assertEqual(report["reconstructed_saturation_pressure_rows"], 3)
        self.assertEqual(report["repaired_rows"], 3)
        for field in (
            "saturation_vapor_pressure_pa", "humidity_ratio_g_kg", "humidity_ratio_kg_kg",
            "vapor_pressure_pa", "moist_air_enthalpy_kj_kg", "specific_volume_m3_kg",
            "moist_air_density_kg_m3", "degree_of_saturation",
        ):
            np.testing.assert_allclose(repaired[field], good[field], rtol=0, atol=1e-8)
        for source_field in ("dry_bulb_temperature_c", "relative_humidity_pct", "atmospheric_station_pressure_pa"):
            pd.testing.assert_series_equal(repaired[source_field], good[source_field])

    def test_corrupted_saturation_just_beyond_32768_hour_boundary_recovers(self) -> None:
        # Use a large but vectorized fixture with no expensive wet-bulb loop.
        original = add_psychrometric_properties(climate_source(2))
        frame = pd.concat([original] * 16523, ignore_index=True).iloc[:33045].copy()
        good = frame.copy()
        frame.loc[32768:, "saturation_vapor_pressure_pa"] = 100000.0
        frame.loc[32768:, "humidity_ratio_g_kg"] = 3_983_884.0
        result = reconcile_historical_psychrometrics(frame)
        self.assertEqual(len(result), 33045)
        self.assertEqual(result.attrs["psychrometric_physical_closure"]["reconstructed_saturation_pressure_rows"], 277)
        for field in ("saturation_vapor_pressure_pa", "humidity_ratio_g_kg", "humidity_ratio_kg_kg"):
            np.testing.assert_allclose(result[field], good[field], atol=1e-8, rtol=0)
        self.assertEqual(len(frame), len(result))

    def test_impossible_measured_temperature_fails_closed(self) -> None:
        good = add_psychrometric_properties(climate_source(3))
        tampered = good.copy()
        tampered.iloc[1, tampered.columns.get_loc("dry_bulb_temperature_c")] = 300.0
        with self.assertRaisesRegex(ValueError, "outside ASHRAE"):
            reconcile_historical_psychrometrics(tampered)

    def test_missing_source_rows_not_invented(self) -> None:
        source = climate_source(3)
        source.loc[source.index[1], "relative_humidity_pct"] = np.nan
        frame = add_psychrometric_properties(source)
        recovered = reconcile_historical_psychrometrics(frame)
        self.assertIs(recovered, frame)
        self.assertTrue(np.isnan(recovered["humidity_ratio_g_kg"].iloc[1]))

    def test_actual_long_series_failure_signature_yields_physical_monthly_profile(self) -> None:
        # Reproduce the user's full exported 33,045 hourly slots, including
        # exactly 104 missing psychrometric rows. In the broken deployment,
        # humidity_ratio_kg_kg and degree_of_saturation were identical on
        # all 32,941 valid records and measured millions of g/kg dry air.
        source = climate_source(33045)
        source.iloc[:104, source.columns.get_loc("relative_humidity_pct")] = np.nan
        valid_count = source["relative_humidity_pct"].notna().sum()
        self.assertEqual(valid_count, 32941)
        clean = add_psychrometric_properties(source, calculate_inverse=False)
        bad = clean.copy()
        bad_kg = np.where(source["relative_humidity_pct"].notna(), 3983.883638, np.nan)
        bad["humidity_ratio_kg_kg"] = bad_kg
        bad["humidity_ratio_g_kg"] = bad_kg * 1000.0
        bad["degree_of_saturation"] = bad_kg
        bad["specific_volume_m3_kg"] = 17.5246711
        with patch.object(
            psychrometric_consistency, "_ashrae_saturation_pressure_pa",
            side_effect=AssertionError("A long vector saturation is not an independent scalar closure"),
        ):
            recovered = reconcile_historical_psychrometrics(bad)
        self.assertEqual(recovered.attrs["psychrometric_physical_closure"]["repaired_rows"], 33045)
        self.assertEqual(recovered.attrs["psychrometric_physical_closure"]["valid_source_rows"], 32941)
        for field in (
            "humidity_ratio_g_kg", "humidity_ratio_kg_kg", "vapor_pressure_pa",
            "saturation_vapor_pressure_pa", "moist_air_enthalpy_kj_kg",
            "specific_volume_m3_kg", "moist_air_density_kg_m3", "degree_of_saturation",
        ):
            np.testing.assert_allclose(recovered[field], clean[field], rtol=0, atol=1e-8, equal_nan=True)
        self.assertLess(float(recovered["humidity_ratio_g_kg"].max()), 20.0)
        chart = profile_ribbon_chart(
            recovered, "humidity_ratio_g_kg", "Monthly",
            "Humidity: Humidity ratio", "g/kg dry air",
        )
        for trace in chart.data:
            if trace.y is not None:
                values = pd.to_numeric(pd.Series(trace.y), errors="coerce").dropna()
                if not values.empty:
                    self.assertLess(float(values.max()), 20.0)
        months = pd.Series(
            recovered["humidity_ratio_g_kg"].to_numpy(),
            index=pd.date_range("2023-01-01", periods=len(recovered), freq="h"),
        ).resample("MS").agg(["min", "mean", "max"])
        self.assertTrue((months["max"].dropna() < 20.0).all())
        pd.testing.assert_series_equal(recovered["dry_bulb_temperature_c"], source["dry_bulb_temperature_c"])
        pd.testing.assert_series_equal(recovered["relative_humidity_pct"], source["relative_humidity_pct"])

    def test_hourly_humidity_only_does_not_call_expensive_inverse_functions(self) -> None:
        with (
            patch.object(psychrolib, "GetTWetBulbFromHumRatio", side_effect=AssertionError("wet-bulb inverse called")),
            patch.object(psychrolib, "GetTDewPointFromRelHum", side_effect=AssertionError("dew-point inverse called")),
        ):
            output = add_psychrometric_properties(climate_source(33045), calculate_inverse=False)
        self.assertEqual(len(output), 33045)
        self.assertLess(float(output["humidity_ratio_g_kg"].max()), 20.0)
        self.assertTrue(output["wet_bulb_temperature_c"].isna().all())
        self.assertTrue(output["dew_point_temperature_c"].isna().all())

    def test_native_hourly_and_final_ui_paths_carry_physical_guard(self) -> None:
        root = Path(__file__).resolve().parents[1]
        historical = (root / "epw_climate_analyzer" / "historical.py").read_text(encoding="utf-8")
        ui = (root / "epw_climate_analyzer" / "source_parity_ui.py").read_text(encoding="utf-8")
        ast.parse(historical)
        ast.parse(ui)
        self.assertEqual(historical.count("data = reconcile_historical_psychrometrics("), 2)
        self.assertIn("filtered_df = reconcile_historical_psychrometrics(", ui)
        self.assertIn('st.session_state["_active_filtered_export_df"] = filtered_df', ui)
        self.assertIn("field_reconciliation_counts", ui)
        self.assertIn("_render_psychrometric_integrity_footer(", ui)
        self.assertIn('with st.expander("Psychrometric data integrity", expanded=False):', ui)
        self.assertNotIn("Psychrometric physical-closure guard: derived quantities were", ui)
        self.assertLess(
            ui.index('legacy.render_time_series_overlay(filtered_df)'),
            ui.index('_render_psychrometric_integrity_footer(\n            closure_report,'),
        )
        self.assertIn('preferred_id = "klima-v2-1h"', ui)
        self.assertIn("calculate_inverse_psychrometrics=not fast_humidity_explorer", ui)
        self.assertIn('st.session_state.get("humidity_explorer_variable", "Humidity ratio")', ui)
        psychrometrics = (root / "epw_climate_analyzer" / "psychrometrics.py").read_text(encoding="utf-8")
        self.assertIn("if calculate_inverse:", psychrometrics)


if __name__ == "__main__":
    unittest.main()
