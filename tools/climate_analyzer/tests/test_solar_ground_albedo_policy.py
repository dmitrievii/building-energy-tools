"""Ground-albedo policy, scientific provenance and source-vs-design regression.

This regression intentionally reproduces an EPW with albedo 0.60 during
8705/8760 hours while preserving GHI, DNI and DHI across scenarios.
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.solar import (
    DEFAULT_ALBEDO,
    albedo_source_diagnostics,
    monthly_orientation_radiation,
    orientation_annual_radiation,
    orientation_tilt_matrix,
    source_ground_albedo,
    surface_irradiance_components,
    surface_irradiance_series,
)


def epw_like_year() -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=8760, freq="h", tz="UTC")
    frame = pd.DataFrame(index=index)
    frame["solar_apparent_zenith_deg"] = 50.0
    frame["solar_azimuth_deg"] = 60.0
    frame["direct_normal_radiation_wh_m2"] = 1199.3 * 1000.0 / 8760.0
    frame["global_horizontal_radiation_wh_m2"] = 1358.5 * 1000.0 / 8760.0
    frame["diffuse_horizontal_radiation_wh_m2"] = 627.6 * 1000.0 / 8760.0
    frame["albedo"] = np.r_[[0.60] * 8705, [0.20] * 55]
    frame["month_index"] = index.month
    return frame


class GroundAlbedoContractTests(unittest.TestCase):
    def test_default_standard_ground_ignores_suspicious_source(self) -> None:
        df = epw_like_year()
        snapshot = df["albedo"].copy()
        direct_default = surface_irradiance_components(df, 90, 60)
        direct_explicit = surface_irradiance_components(df, 90, 60, albedo=DEFAULT_ALBEDO)
        source = surface_irradiance_components(df, 90, 60, albedo=source_ground_albedo(df))
        np.testing.assert_allclose(
            direct_default["poa_global_wh_m2"],
            direct_explicit["poa_global_wh_m2"],
            rtol=0, atol=1e-12,
        )
        for col in ("poa_direct_wh_m2", "poa_sky_diffuse_wh_m2"):
            np.testing.assert_allclose(direct_default[col], source[col], rtol=0, atol=1e-10)
        ground_diff = source["poa_ground_diffuse_wh_m2"] - direct_default["poa_ground_diffuse_wh_m2"]
        expected = (df["albedo"] - 0.20) * df["global_horizontal_radiation_wh_m2"] * 0.5
        np.testing.assert_allclose(ground_diff, expected, rtol=0, atol=1e-8)
        self.assertAlmostEqual(
            float((source["poa_global_wh_m2"] - direct_default["poa_global_wh_m2"]).sum()),
            float(expected.sum()),
            delta=1e-7,
        )
        self.assertIn("standard ground 0.20", direct_default.attrs["albedo_origin"])
        pd.testing.assert_series_equal(df["albedo"], snapshot)

    def test_annual_and_monthly_and_tilt_share_identical_ground_assumption(self) -> None:
        df = epw_like_year().iloc[:48].copy()
        source = source_ground_albedo(df)
        annual_standard = orientation_annual_radiation(df, tilt_deg=90)
        annual_source = orientation_annual_radiation(df, tilt_deg=90, albedo=source)
        self.assertTrue((annual_source["annual_kwh_m2"] > annual_standard["annual_kwh_m2"]).all())
        matrix = orientation_tilt_matrix(
            df, tilt_values=[0.0, 90.0], azimuth_values=[0.0, 60.0],
            albedo=source,
        )
        north = float(annual_source.loc[annual_source["orientation"] == "North", "annual_kwh_m2"].iloc[0])
        self.assertAlmostEqual(float(matrix.loc[90.0, 0.0]), north, places=10)
        self.assertAlmostEqual(
            float(matrix.loc[90.0, 60.0]),
            float(surface_irradiance_series(df, 90, 60, albedo=source).sum() / 1000.0),
            places=10,
        )
        monthly = monthly_orientation_radiation(df, tilt_deg=90, albedo=source)
        self.assertAlmostEqual(float(monthly["North"].sum()), north, places=10)
        self.assertAlmostEqual(
            float(matrix.loc[0.0, 60.0]),
            float(surface_irradiance_series(df, 0, 60, albedo=source).sum() / 1000.0),
            places=10,
        )

    def test_source_diagnostics_flags_high_modal_value_without_modifying_data(self) -> None:
        df = epw_like_year()
        report = albedo_source_diagnostics(df)
        self.assertIsNotNone(report)
        self.assertEqual(report["valid_count"], 8760)
        self.assertEqual(report["dominant_value"], 0.6)
        self.assertEqual(report["dominant_count"], 8705)
        self.assertEqual(report["high_count"], 8705)
        self.assertGreater(report["high_fraction"], 0.99)
        self.assertAlmostEqual(report["mean"], (8705 * 0.6 + 55 * 0.2) / 8760, places=10)

    def test_invalid_values_rejected_in_source_mode_not_clipped(self) -> None:
        df = epw_like_year().iloc[:4].copy()
        df.iloc[0, df.columns.get_loc("albedo")] = 1.2
        self.assertEqual(albedo_source_diagnostics(df)["invalid_count"], 1)
        with self.assertRaisesRegex(ValueError, "outside 0..1"):
            source_ground_albedo(df)
        # Default/standard does not adopt source values and remains valid.
        self.assertTrue(surface_irradiance_series(df, 90, 60).notna().all())
        with self.assertRaises(ValueError):
            surface_irradiance_series(df, 90, 60, albedo=1.1)

    def test_missing_albedo_falls_back_only_in_explicit_source_mode(self) -> None:
        df = epw_like_year().iloc[:3].copy()
        df.loc[df.index[1], "albedo"] = np.nan
        selected = source_ground_albedo(df)
        self.assertEqual(float(selected.loc[df.index[1]]), 0.2)
        self.assertEqual(float(selected.loc[df.index[0]]), 0.6)
        self.assertEqual(albedo_source_diagnostics(df)["missing_count"], 1)

    def test_component_mask_and_energy_closure(self) -> None:
        df = epw_like_year().iloc[:3].copy()
        df.loc[df.index[0], "direct_normal_radiation_wh_m2"] = np.nan
        components = surface_irradiance_components(df, 90, 60)
        self.assertTrue(components.iloc[0].isna().all())
        numeric = components.iloc[1:]
        np.testing.assert_allclose(
            numeric["poa_global_wh_m2"],
            numeric["poa_direct_wh_m2"] + numeric["poa_sky_diffuse_wh_m2"] + numeric["poa_ground_diffuse_wh_m2"],
            rtol=0, atol=1e-10,
        )

    def test_ui_all_poa_routes_explicitly_receive_ground_mode(self) -> None:
        path = Path(__file__).resolve().parents[1] / "app.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('key="solar_ground_albedo_mode"', source)
        self.assertIn('ground_albedo = _solar_ground_albedo_selection(df)', source)
        self.assertIn("orientation_annual_radiation(df, tilt_deg=tilt, albedo=ground_albedo)", source)
        self.assertIn("orientation_tilt_matrix(df, albedo=ground_albedo)", source)
        self.assertIn("monthly_orientation_radiation(df, tilt_deg=tilt, albedo=ground_albedo)", source)
        self.assertIn("surface_irradiance_components(", source)


if __name__ == "__main__":
    unittest.main()
