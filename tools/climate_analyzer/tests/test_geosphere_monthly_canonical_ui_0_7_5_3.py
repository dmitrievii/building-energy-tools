from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from epw_climate_analyzer import geosphere
from epw_climate_analyzer.geosphere_monthly import build_monthly_dataset
from epw_climate_analyzer.source_parity_monthly_canonical import (
    MONTHLY_ALLOWED_AGGREGATIONS,
    MONTHLY_ALLOWED_GENERIC_CHART_TYPES,
    MONTHLY_COMPARE_DIMENSIONS,
    MONTHLY_HEATMAP_PERIODS,
    monthly_analysis_frame,
    monthly_page_names,
    monthly_variable_registry,
)


class GeoSphereMonthlyCanonicalUiTests(unittest.TestCase):
    @staticmethod
    def metadata() -> dict:
        return {
            "parameters": [
                {"name": "tl_mittel", "long_name": "Lufttemperatur Monatsmittel", "unit": "°C"},
                {"name": "tlmin", "long_name": "Absolutes Temperaturminimum", "unit": "°C"},
                {"name": "rf_mittel", "long_name": "Relative Feuchte Monatsmittel", "unit": "%"},
                {"name": "rr", "long_name": "Niederschlagssumme", "unit": "mm"},
                {"name": "so_h", "long_name": "Sonnenscheindauer", "unit": "h"},
                {"name": "tage_frost", "long_name": "Frosttage", "unit": "d"},
                {"name": "sicht1", "long_name": "Tage mit Sichtklasse 1", "unit": "d"},
            ],
            "stations": [
                {
                    "id": "105",
                    "name": "Wien Hohe Warte",
                    "lat": 48.2486,
                    "lon": 16.3564,
                    "altitude": 198,
                    "state": "Wien",
                    "valid_from": "1872-01-01T00:00+00:00",
                    "valid_to": "2026-09-01T00:00+00:00",
                }
            ],
        }

    def dataset(self):
        metadata = self.metadata()
        station = geosphere.parse_stations(metadata)[0]
        index = pd.date_range("1941-01-01", periods=4, freq="MS", tz="UTC")
        provider = pd.DataFrame(
            {
                "tl_mittel": [0.5, 1.0, 5.0, 9.0],
                "tlmin": [-12.0, -10.0, -5.0, -1.0],
                "rf_mittel": [82.0, 79.0, 72.0, 68.0],
                "rr": [35.0, 28.0, 42.0, 50.0],
                "so_h": [60.0, 75.0, 120.0, 150.0],
                "tage_frost": [20.0, 15.0, 5.0, 1.0],
                "sicht1": [3.0, 2.0, 1.0, 1.0],
            },
            index=index,
        )
        return build_monthly_dataset(
            station=station,
            provider_frame=provider,
            metadata=metadata,
            physical_parameters=list(provider.columns),
            requested_start=index[0],
            requested_end=index[-1],
        )

    def test_monthly_frame_keeps_native_fields_and_adds_safe_canonical_aliases(self) -> None:
        frame = monthly_analysis_frame(self.dataset())
        self.assertIn("tl_mittel", frame.columns)
        self.assertIn("dry_bulb_temperature_c", frame.columns)
        self.assertIn("dry_bulb_temperature_min_c", frame.columns)
        self.assertIn("relative_humidity_pct", frame.columns)
        self.assertIn("liquid_precipitation_depth_mm", frame.columns)
        self.assertIn("sunshine_duration_s", frame.columns)
        self.assertAlmostEqual(float(frame["sunshine_duration_s"].iloc[0]), 60.0 * 3600.0)

    def test_monthly_temporal_controls_are_locked_to_monthly_semantics(self) -> None:
        self.assertEqual(MONTHLY_ALLOWED_AGGREGATIONS, ("Monthly",))
        self.assertEqual(MONTHLY_HEATMAP_PERIODS, ("Month",))
        self.assertEqual(MONTHLY_COMPARE_DIMENSIONS, ("Year",))
        self.assertNotIn("Duration curve", MONTHLY_ALLOWED_GENERIC_CHART_TYPES)

    def test_monthly_resource_uses_canonical_pages_not_monthly_explorer(self) -> None:
        dataset = self.dataset()
        frame = monthly_analysis_frame(dataset)
        legacy = SimpleNamespace(
            VARIABLES={
                "Dry-bulb temperature": ("dry_bulb_temperature_c", "°C"),
                "Dry-bulb temperature minimum": ("dry_bulb_temperature_min_c", "°C"),
                "Relative humidity": ("relative_humidity_pct", "%"),
                "Liquid precipitation depth": ("liquid_precipitation_depth_mm", "mm"),
                "Sunshine duration": ("sunshine_duration_s", "s"),
            }
        )
        groups, _ = monthly_variable_registry(legacy, dataset, frame)
        pages = monthly_page_names(groups)
        self.assertIn("Temperature", pages)
        self.assertIn("Humidity and Psychrometrics", pages)
        self.assertIn("Sky and Daylight", pages)
        self.assertIn("Precipitation and Snow", pages)
        self.assertIn("Time Series and Overlay", pages)
        self.assertIn("Data Quality", pages)
        self.assertNotIn("Monthly Explorer", pages)
        self.assertIn("Frosttage", groups["Temperature"])
        self.assertIn("Tage mit Sichtklasse 1", groups["Sky and Daylight"])


if __name__ == "__main__":
    unittest.main()
