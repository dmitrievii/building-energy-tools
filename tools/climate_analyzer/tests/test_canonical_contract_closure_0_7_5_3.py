from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from epw_climate_analyzer import source_parity_contract_closure as contract
from epw_climate_analyzer.source_parity_contract_guard import install_contract_guards


class CanonicalContractClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_contract_guards()

    def test_native_monthly_mean_is_weighted_by_real_calendar_days(self) -> None:
        index = pd.DatetimeIndex(["2025-01-01", "2025-02-01"])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 28.0]}, index=index)
        annual = contract.monthly_period_values(frame, "dry_bulb_temperature_c", "Annual")
        expected = (0.0 * 31.0 + 28.0 * 28.0) / (31.0 + 28.0)
        self.assertEqual(len(annual), 1)
        self.assertAlmostEqual(float(annual.iloc[0]), expected, places=10)

    def test_native_monthly_sum_and_extrema_keep_quantity_semantics(self) -> None:
        index = pd.DatetimeIndex(["2025-01-01", "2025-02-01", "2025-03-01"])
        frame = pd.DataFrame(
            {
                "liquid_precipitation_depth_mm": [10.0, 20.0, 30.0],
                "dry_bulb_temperature_min_c": [-5.0, -10.0, -3.0],
                "dry_bulb_temperature_max_c": [12.0, 15.0, 18.0],
            },
            index=index,
        )
        self.assertAlmostEqual(
            float(contract.monthly_period_values(frame, "liquid_precipitation_depth_mm", "Annual").iloc[0]),
            60.0,
        )
        self.assertAlmostEqual(
            float(contract.monthly_period_values(frame, "dry_bulb_temperature_min_c", "Annual").iloc[0]),
            -10.0,
        )
        self.assertAlmostEqual(
            float(contract.monthly_period_values(frame, "dry_bulb_temperature_max_c", "Annual").iloc[0]),
            18.0,
        )

    def test_native_monthly_seasonal_groups_real_calendar_seasons(self) -> None:
        index = pd.DatetimeIndex(["2024-12-01", "2025-01-01", "2025-02-01", "2025-03-01"])
        frame = pd.DataFrame(
            {"liquid_precipitation_depth_mm": [10.0, 20.0, 30.0, 40.0]},
            index=index,
        )
        seasonal = contract.monthly_period_values(frame, "liquid_precipitation_depth_mm", "Seasonal")
        self.assertEqual(len(seasonal), 2)
        self.assertAlmostEqual(float(seasonal.iloc[0]), 60.0)
        self.assertAlmostEqual(float(seasonal.iloc[1]), 40.0)

    def test_native_monthly_direction_uses_weighted_circular_mean(self) -> None:
        index = pd.DatetimeIndex(["2025-01-01", "2025-02-01"])
        column = "monthly__circular_mean__wind_and_ventilation__dd"
        frame = pd.DataFrame({column: [350.0, 10.0]}, index=index)
        annual = contract.monthly_period_values(frame, column, "Annual")
        value = float(annual.iloc[0])
        self.assertTrue(value >= 350.0 or value <= 10.0)

    def test_unknown_provider_statistic_stays_native_monthly_only(self) -> None:
        column = "monthly__unknown__other__foo"
        self.assertIsNone(contract._monthly_semantics(column))
        frame = pd.DataFrame(
            {column: [1.0, 2.0]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-02-01"]),
        )
        self.assertEqual(contract.monthly_period_values(frame, column, "Monthly").tolist(), [1.0, 2.0])
        with self.assertRaises(ValueError):
            contract.monthly_period_values(frame, column, "Seasonal")
        with self.assertRaises(ValueError):
            contract.monthly_period_values(frame, column, "Annual")

    def test_monthly_psychrometric_properties_are_representative_state_properties(self) -> None:
        index = pd.DatetimeIndex(["2025-01-01", "2025-02-01"])
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [0.0, 10.0],
                "relative_humidity_pct": [80.0, 60.0],
                "atmospheric_station_pressure_pa": [95000.0, 95200.0],
                "dew_point_temperature_c": [-3.0, 2.0],
            },
            index=index,
        )
        dataset = SimpleNamespace(location=SimpleNamespace(elevation_m=350.0))
        out = contract.monthly_psychrometric_frame(dataset, frame)
        for column in (
            "humidity_ratio_g_kg",
            "moist_air_enthalpy_kj_kg",
            "wet_bulb_temperature_c",
            "specific_volume_m3_kg",
            "moist_air_density_kg_m3",
        ):
            self.assertIn(column, out.columns)
            self.assertTrue(pd.to_numeric(out[column], errors="coerce").notna().all())
        np.testing.assert_allclose(out["dew_point_temperature_c"].to_numpy(dtype=float), [-3.0, 2.0])
        self.assertIn(
            "representative monthly states",
            out.attrs["canonical_monthly_psychrometric_semantics"],
        )

    def test_monthly_psychrometric_profile_collapses_multiyear_data_to_twelve_calendar_points(self) -> None:
        index = pd.date_range("2024-01-01", periods=24, freq="MS")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": np.tile(np.arange(12, dtype=float), 2),
                "relative_humidity_pct": np.full(24, 60.0),
                "atmospheric_station_pressure_pa": np.full(24, 100000.0),
            },
            index=index,
        )
        profile = contract.monthly_psychrometric_profile(frame, 100000.0)
        self.assertEqual(len(profile), 12)
        self.assertEqual(profile["month_index"].tolist(), list(range(1, 13)))
        self.assertTrue(profile["humidity_ratio_g_kg"].notna().all())

    def test_monthly_psychrometric_profile_uses_only_coincident_temperature_and_rh(self) -> None:
        index = pd.DatetimeIndex(["2024-01-01", "2025-01-01"])
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [0.0, 20.0],
                "relative_humidity_pct": [50.0, np.nan],
                "atmospheric_station_pressure_pa": [100000.0, 100000.0],
            },
            index=index,
        )
        profile = contract.monthly_psychrometric_profile(frame, 100000.0)
        self.assertEqual(len(profile), 1)
        self.assertAlmostEqual(float(profile["dry_bulb_temperature_c"].iloc[0]), 0.0)
        self.assertAlmostEqual(float(profile["relative_humidity_pct"].iloc[0]), 50.0)

    def test_catalogue_roles_distinguish_core_additional_and_other(self) -> None:
        core = SimpleNamespace(
            provider="tl_mittel",
            recommended=True,
            category="Temperature",
            annual_semantics="mean",
        )
        additional = SimpleNamespace(
            provider="frost_days",
            recommended=False,
            category="Temperature",
            annual_semantics="sum",
        )
        other = SimpleNamespace(
            provider="mystery",
            recommended=False,
            category="Other monthly parameters",
            annual_semantics=None,
        )
        self.assertEqual(contract.monthly_catalogue_role(core), "Core variable")
        self.assertEqual(contract.monthly_catalogue_role(additional), "Additional statistic")
        self.assertEqual(contract.monthly_catalogue_role(other), "Other provider parameter")


if __name__ == "__main__":
    unittest.main()
