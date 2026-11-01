"""Investigate Hohe Warte 2023–2026 humidity regression near 2**15 rows.

The fixture reproduces the exact two hourly horizon sizes reported in the live
app. Its suffix-invariance contract catches row-count-dependent corruption in
the native-hourly -> psychrometric -> hourly-aggregation chain.
"""

from __future__ import annotations

from dataclasses import replace
import unittest

import numpy as np
import pandas as pd
import psychrolib

from epw_climate_analyzer.aggregations import aggregate_summary
from epw_climate_analyzer.geosphere import (
    GeoSphereStation,
    build_canonical_station_dataset,
    supported_parameter_mapping,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame


class HoheWarteHourlyRowCountTests(unittest.TestCase):
    @staticmethod
    def _dataset() -> object:
        index = pd.date_range(
            "2023-01-01T00:00:00Z", "2026-10-08T23:00:00Z", freq="h"
        )
        phase = np.arange(len(index), dtype=float)
        frame = pd.DataFrame(
            {
                "tl": 12.0 + 12.0 * np.sin(2.0 * np.pi * phase / 8766.0),
                "rf": 65.0 + 20.0 * np.sin(2.0 * np.pi * phase / 24.0),
                "p": 985.0 + 12.0 * np.sin(2.0 * np.pi * phase / 180.0),
            },
            index=index,
        )
        metadata = {
            "parameters": [
                {"name": "tl", "long_name": "Temperature", "unit": "°C"},
                {"name": "rf", "long_name": "Relative humidity", "unit": "%"},
                {"name": "p", "long_name": "Pressure", "unit": "hPa"},
            ],
            "stations": [],
        }
        mapping = supported_parameter_mapping(metadata, resource_id="klima-v2-1h")
        return build_canonical_station_dataset(
            station=GeoSphereStation(
                station_id="HOHE_WARTE_TEST", name="Wien Hohe Warte",
                latitude=48.248, longitude=16.356, elevation_m=200.0,
            ),
            provider_frame=frame,
            mapping=mapping,
            metadata=metadata,
            resource_id="klima-v2-1h",
        )

    def test_2023_addition_above_32768_preserves_every_overlapping_hour(self) -> None:
        full_dataset = self._dataset()
        self.assertEqual(len(full_dataset.data), 33048)
        later = full_dataset.data.loc["2024-01-01":].copy()
        self.assertEqual(len(later), 24288)
        short_dataset = replace(full_dataset, data=later)

        full = prepare_historical_analysis_frame(
            full_dataset,
            include_psychrometrics=True,
            pressure_override_pa=101325.0,
        )
        short = prepare_historical_analysis_frame(
            short_dataset,
            include_psychrometrics=True,
            pressure_override_pa=101325.0,
        )
        self.assertEqual(len(full), 33048)
        self.assertEqual(len(short), 24288)
        for column in (
            "dry_bulb_temperature_c", "relative_humidity_pct",
            "atmospheric_station_pressure_pa", "vapor_pressure_pa",
            "humidity_ratio_kg_kg", "humidity_ratio_g_kg",
            "moist_air_enthalpy_kj_kg", "wet_bulb_temperature_c",
        ):
            np.testing.assert_allclose(
                full.loc[short.index, column].to_numpy(dtype=float),
                short[column].to_numpy(dtype=float),
                rtol=1e-10, atol=1e-8,
                err_msg=f"Hourly property {column!r} changed simply because 2023 was included",
            )
        ratio = full["humidity_ratio_g_kg"].to_numpy(dtype=float)
        enthalpy = full["moist_air_enthalpy_kj_kg"].to_numpy(dtype=float)
        temp = full["dry_bulb_temperature_c"].to_numpy(dtype=float)
        self.assertGreater(float(np.nanmin(ratio)), 0.0)
        self.assertLess(float(np.nanmax(ratio)), 30.0)
        expected_h = 1.006 * temp + (ratio / 1000.0) * (2501.0 + 1.86 * temp)
        np.testing.assert_allclose(enthalpy, expected_h, rtol=1e-9, atol=1e-6)

        hourly_agg = aggregate_summary(full, "humidity_ratio_g_kg", "Hourly")
        self.assertEqual(len(hourly_agg), len(full))
        np.testing.assert_allclose(
            hourly_agg["mean"].to_numpy(dtype=float), ratio,
            rtol=0.0, atol=1e-8,
            err_msg="Hourly aggregation must never sum humidity ratios",
        )
        print(
            "32768 boundary check: full hours =", len(full),
            "short hours =", len(short),
            "mean humidity [g/kg] =", round(float(np.nanmean(ratio)), 3),
            "mean enthalpy [kJ/kg] =", round(float(np.nanmean(enthalpy)), 3),
        )


if __name__ == "__main__":
    unittest.main()
