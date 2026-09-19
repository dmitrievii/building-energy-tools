from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.epw_extended import clean_extended_epw_fields
from epw_climate_analyzer.epw_header import parse_epw_ground_temperatures, parse_epw_header
from epw_climate_analyzer.quality_policy import (
    PROVIDER_TO_CANONICAL_ATTR,
    QUALITY_POLICY_ALL,
    QUALITY_POLICY_CHECKED,
    QUALITY_POLICY_MANUAL,
    apply_quality_policy,
)


class SourceParityMetadataQualityTests(unittest.TestCase):
    def test_epw_ground_temperature_header_is_typed(self) -> None:
        line = (
            "GROUND TEMPERATURES,1,0.5,1.8,1900,900,"
            "1,2,3,4,5,6,7,8,9,10,11,12"
        )
        profiles = parse_epw_ground_temperatures(line)
        self.assertEqual(len(profiles), 1)
        profile = profiles[0]
        self.assertAlmostEqual(profile.depth_m, 0.5)
        self.assertAlmostEqual(float(profile.conductivity_w_mk), 1.8)
        self.assertEqual(profile.monthly_temperature_c[0], 1.0)
        self.assertEqual(profile.monthly_temperature_c[-1], 12.0)
        frame = profile.as_monthly_frame()
        self.assertEqual(len(frame), 12)
        self.assertEqual(frame.iloc[0]["source"], "EPW header ground temperature")

    def test_epw_header_parses_typical_period_and_context(self) -> None:
        header = [
            "LOCATION,Graz,Styria,AUT,Source,12345,47.1,15.4,1.0,350",
            "DESIGN CONDITIONS,1,Test design condition",
            "TYPICAL/EXTREME PERIODS,1,Summer Week,Typical,7/1,7/7",
            "GROUND TEMPERATURES,0",
            "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
            "COMMENTS 1,Example comment",
            "COMMENTS 2,Second comment",
            "DATA PERIODS,1,1,Data,Sunday,1/1,12/31",
        ]
        metadata = parse_epw_header(header)
        self.assertEqual(len(metadata.typical_extreme_periods), 1)
        self.assertEqual(metadata.typical_extreme_periods[0].name, "Summer Week")
        self.assertIn("Test design condition", metadata.design_conditions_tokens)
        self.assertEqual(metadata.comments_1, "Example comment")
        self.assertTrue(metadata.data_periods_tokens)

    def test_extended_epw_sentinels_are_removed(self) -> None:
        frame = pd.DataFrame(
            {
                "visibility_km": [10.0, 9999.0],
                "ceiling_height_m": [1000.0, 99999.0],
                "aerosol_optical_depth_thousandths": [0.2, 0.999],
                "days_since_last_snowfall": [4.0, 99.0],
                "albedo": [0.7, 999.0],
            },
            index=pd.date_range("2026-01-01", periods=2, freq="h"),
        )
        clean = clean_extended_epw_fields(frame)
        self.assertEqual(float(clean.iloc[0]["visibility_km"]), 10.0)
        self.assertTrue(pd.isna(clean.iloc[1]["visibility_km"]))
        self.assertTrue(pd.isna(clean.iloc[1]["ceiling_height_m"]))
        self.assertTrue(pd.isna(clean.iloc[1]["aerosol_optical_depth_thousandths"]))
        self.assertTrue(pd.isna(clean.iloc[1]["days_since_last_snowfall"]))
        self.assertTrue(pd.isna(clean.iloc[1]["albedo"]))

    def test_quality_policy_masks_only_affected_physical_variable(self) -> None:
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [1.0, 2.0, 3.0, 4.0],
                "relative_humidity_pct": [50.0, 51.0, 52.0, 53.0],
                "quality_flag__tl": [0, 10, 20, 22],
            },
            index=pd.date_range("2026-01-01", periods=4, freq="h"),
        )
        frame.attrs[PROVIDER_TO_CANONICAL_ATTR] = {"tl": "dry_bulb_temperature_c"}

        all_data = apply_quality_policy(frame, QUALITY_POLICY_ALL)
        self.assertEqual(all_data["dry_bulb_temperature_c"].notna().sum(), 4)

        checked = apply_quality_policy(frame, QUALITY_POLICY_CHECKED)
        self.assertTrue(pd.isna(checked.iloc[0]["dry_bulb_temperature_c"]))
        self.assertEqual(checked["dry_bulb_temperature_c"].notna().sum(), 3)
        self.assertEqual(checked["relative_humidity_pct"].notna().sum(), 4)

        manual = apply_quality_policy(frame, QUALITY_POLICY_MANUAL)
        self.assertTrue(pd.isna(manual.iloc[0]["dry_bulb_temperature_c"]))
        self.assertTrue(pd.isna(manual.iloc[1]["dry_bulb_temperature_c"]))
        self.assertEqual(manual["dry_bulb_temperature_c"].notna().sum(), 2)
        self.assertEqual(manual["relative_humidity_pct"].notna().sum(), 4)


if __name__ == "__main__":
    unittest.main()
