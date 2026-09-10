from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.aggregations import aggregate_sum, duration_curve
from epw_climate_analyzer.decisions import (
    add_degree_metrics,
    comfort_condition,
    dehumidification_condition,
    economizer_condition,
    humidification_condition,
    natural_ventilation_condition,
    night_flushing_condition,
    passive_strategy_table,
    shading_condition,
)


REFERENCE_PATH = Path(__file__).resolve().parents[1] / "validation" / "scientific_reference_register.json"


def _synthetic_annual_climate() -> pd.DataFrame:
    """Return deterministic analytical 8760-hour climate WEB-0.4-SYNTH-1."""
    index = pd.date_range("2025-01-01 00:00:00", "2025-12-31 23:00:00", freq="h")
    day_of_year = index.dayofyear.to_numpy(dtype=float)
    hour_of_day = index.hour.to_numpy(dtype=float)

    seasonal = np.cos(2.0 * np.pi * (day_of_year - 200.0) / 365.0)
    diurnal = np.cos(2.0 * np.pi * (hour_of_day - 15.0) / 24.0)

    temperature_c = 12.0 + 11.0 * seasonal + 4.0 * diurnal
    humidity_ratio_g_kg = np.clip(6.5 + 3.0 * seasonal - 1.0 * diurnal, 1.5, 13.0)
    relative_humidity_pct = np.clip(65.0 - 15.0 * seasonal - 10.0 * diurnal, 25.0, 95.0)
    wind_speed_m_s = np.clip(
        2.8
        + np.sin(2.0 * np.pi * hour_of_day / 24.0)
        + 0.5 * np.cos(2.0 * np.pi * day_of_year / 7.0),
        0.0,
        None,
    )

    daylight_shape = np.maximum(0.0, np.sin(np.pi * (hour_of_day - 6.0) / 12.0))
    ghi_wh_m2 = daylight_shape * np.maximum(0.0, 600.0 + 200.0 * seasonal)

    humidity_ratio_kg_kg = humidity_ratio_g_kg / 1000.0
    enthalpy_kj_kg = 1.006 * temperature_c + humidity_ratio_kg_kg * (2501.0 + 1.86 * temperature_c)

    season = pd.Series(index.month, index=index).map(
        {
            12: "Winter",
            1: "Winter",
            2: "Winter",
            3: "Spring",
            4: "Spring",
            5: "Spring",
            6: "Summer",
            7: "Summer",
            8: "Summer",
            9: "Autumn",
            10: "Autumn",
            11: "Autumn",
        }
    )

    frame = pd.DataFrame(
        {
            "dry_bulb_temperature_c": temperature_c,
            "humidity_ratio_g_kg": humidity_ratio_g_kg,
            "relative_humidity_pct": relative_humidity_pct,
            "wind_speed_m_s": wind_speed_m_s,
            "global_horizontal_radiation_wh_m2": ghi_wh_m2,
            "moist_air_enthalpy_kj_kg": enthalpy_kj_kg,
            "hour_of_day": index.hour,
            "month_index": index.month,
            "season": season.to_numpy(),
        },
        index=index,
    )
    return add_degree_metrics(frame)


class AnnualScientificRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))["synthetic_annual_regression"]
        cls.expected = cls.reference["expected"]
        cls.df = _synthetic_annual_climate()

    def test_generator_identity_and_calendar(self) -> None:
        self.assertEqual(self.reference["generator_id"], "WEB-0.4-SYNTH-1")
        self.assertEqual(len(self.df), 8760)
        self.assertEqual(self.df.index[0], pd.Timestamp("2025-01-01 00:00:00"))
        self.assertEqual(self.df.index[-1], pd.Timestamp("2025-12-31 23:00:00"))

    def test_annual_numeric_fingerprint(self) -> None:
        df = self.df
        calculated = {
            "hours": len(df),
            "mean_temp_c": float(df["dry_bulb_temperature_c"].mean()),
            "min_temp_c": float(df["dry_bulb_temperature_c"].min()),
            "max_temp_c": float(df["dry_bulb_temperature_c"].max()),
            "heating_degree_hours_kh": float(df["heating_degree_hours_kh"].sum()),
            "cooling_degree_hours_kh": float(df["cooling_degree_hours_kh"].sum()),
            "annual_ghi_kwh_m2": float(df["global_horizontal_radiation_wh_m2"].sum() / 1000.0),
            "mean_humidity_ratio_g_kg": float(df["humidity_ratio_g_kg"].mean()),
            "mean_wind_m_s": float(df["wind_speed_m_s"].mean()),
            "natural_ventilation_hours": int(natural_ventilation_condition(df).sum()),
            "night_flushing_hours": int(night_flushing_condition(df).sum()),
            "shading_hours": int(shading_condition(df).sum()),
            "comfort_hours": int(comfort_condition(df).sum()),
            "economizer_hours": int(economizer_condition(df).sum()),
            "dehumidification_hours": int(dehumidification_condition(df).sum()),
            "humidification_hours": int(humidification_condition(df).sum()),
        }

        for key, expected in self.expected.items():
            actual = calculated[key]
            if isinstance(expected, int):
                self.assertEqual(actual, expected, msg=key)
            else:
                self.assertAlmostEqual(float(actual), float(expected), delta=1e-6, msg=key)

    def test_monthly_ghi_fingerprint_and_energy_conservation(self) -> None:
        monthly = aggregate_sum(self.df, "global_horizontal_radiation_wh_m2", "Monthly")
        monthly_kwh_m2 = monthly["sum"].to_numpy(dtype=float) / 1000.0
        expected = np.asarray(self.reference["monthly_ghi_kwh_m2"], dtype=float)
        np.testing.assert_allclose(monthly_kwh_m2, expected, rtol=0.0, atol=1e-6)
        self.assertAlmostEqual(
            float(monthly_kwh_m2.sum()),
            float(self.df["global_horizontal_radiation_wh_m2"].sum() / 1000.0),
            delta=1e-9,
        )

    def test_duration_curve_is_monotonic_and_complete(self) -> None:
        curve = duration_curve(self.df, "dry_bulb_temperature_c", ascending=False)
        self.assertEqual(len(curve), 8760)
        values = curve["dry_bulb_temperature_c"].to_numpy(dtype=float)
        self.assertTrue(np.all(values[:-1] >= values[1:]))
        self.assertAlmostEqual(float(curve["exceedance_fraction"].iloc[-1]), 1.0, places=12)

    def test_passive_strategy_summary_matches_direct_masks(self) -> None:
        table = passive_strategy_table(self.df).set_index("strategy")
        expected_counts = {
            "Comfort without conditioning": int(comfort_condition(self.df).sum()),
            "Natural ventilation": int(natural_ventilation_condition(self.df).sum()),
            "Night flushing": int(night_flushing_condition(self.df).sum()),
            "Solar shading likely useful": int(shading_condition(self.df).sum()),
            "Air-side economizer": int(economizer_condition(self.df).sum()),
            "Dehumidification likely useful": int(dehumidification_condition(self.df).sum()),
            "Humidification likely useful": int(humidification_condition(self.df).sum()),
        }
        for strategy, count in expected_counts.items():
            self.assertEqual(int(table.loc[strategy, "hours"]), count, msg=strategy)


if __name__ == "__main__":
    unittest.main()
