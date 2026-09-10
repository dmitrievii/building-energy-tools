from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd
import psychrolib

from epw_climate_analyzer.decisions import add_degree_metrics, night_flushing_condition
from epw_climate_analyzer.epw_parser import EpwLocation, build_datetime_index
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties
from epw_climate_analyzer.solar import localized_times, surface_irradiance_series


psychrolib.SetUnitSystem(psychrolib.SI)


def _ashrae_sat_vap_pressure_pa(t_c: float) -> float:
    """Independent ASHRAE 2017 saturation-vapour-pressure equation in SI units."""
    t_k = float(t_c) + 273.15
    if t_c <= 0.01:
        ln_pws = (
            -5.6745359e3 / t_k
            + 6.3925247
            - 9.677843e-3 * t_k
            + 6.2215701e-7 * t_k**2
            + 2.0747825e-9 * t_k**3
            - 9.484024e-13 * t_k**4
            + 4.1635019 * math.log(t_k)
        )
    else:
        ln_pws = (
            -5.8002206e3 / t_k
            + 1.3914993
            - 4.8640239e-2 * t_k
            + 4.1764768e-5 * t_k**2
            - 1.4452093e-8 * t_k**3
            + 6.5459673 * math.log(t_k)
        )
    return math.exp(ln_pws)


def _reference_psychrometric_state(t_c: float, rh_fraction: float, pressure_pa: float) -> dict[str, float]:
    p_ws = _ashrae_sat_vap_pressure_pa(t_c)
    p_v = rh_fraction * p_ws
    w = 0.621945 * p_v / (pressure_pa - p_v)
    h = 1.006 * t_c + w * (2501.0 + 1.86 * t_c)
    v = 287.042 * (t_c + 273.15) * (1.0 + 1.607858 * w) / pressure_pa
    rho = (1.0 + w) / v
    w_sat = 0.621945 * p_ws / (pressure_pa - p_ws)
    return {
        "saturation_vapor_pressure_pa": p_ws,
        "vapor_pressure_pa": p_v,
        "humidity_ratio_kg_kg": w,
        "moist_air_enthalpy_kj_kg": h,
        "specific_volume_m3_kg": v,
        "moist_air_density_kg_m3": rho,
        "degree_of_saturation": w / w_sat,
    }


class PsychrometricReferenceTests(unittest.TestCase):
    def assertClose(self, actual: float, expected: float, rel: float = 1e-8, abs_: float = 1e-8) -> None:
        error = abs(float(actual) - float(expected))
        limit = max(abs_, rel * abs(float(expected)))
        self.assertLessEqual(error, limit, msg=f"actual={actual!r}, expected={expected!r}, error={error}, limit={limit}")

    def test_vectorized_psychrometrics_match_independent_ashrae_reference(self) -> None:
        points = [
            (-10.0, 0.70, 90_000.0),
            (20.0, 0.50, 101_325.0),
            (35.0, 0.70, 95_000.0),
        ]
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [p[0] for p in points],
                "relative_humidity_pct": [p[1] * 100.0 for p in points],
                "atmospheric_station_pressure_pa": [p[2] for p in points],
            }
        )
        calculated = add_psychrometric_properties(frame)

        for row_index, (t_c, rh_fraction, pressure_pa) in enumerate(points):
            reference = _reference_psychrometric_state(t_c, rh_fraction, pressure_pa)
            for field, expected in reference.items():
                self.assertClose(calculated.loc[row_index, field], expected)

            wet_bulb = float(calculated.loc[row_index, "wet_bulb_temperature_c"])
            dew_point = float(psychrolib.GetTDewPointFromRelHum(t_c, rh_fraction))
            self.assertLessEqual(dew_point - 1e-8, wet_bulb)
            self.assertLessEqual(wet_bulb, t_c + 1e-8)

    def test_psychrolib_documented_dew_point_anchor(self) -> None:
        # PsychroLib's published example: 25 C / 80 % RH -> 21.309397163661785 C.
        # Cross-language/runtime floating-point differences are accepted only
        # within the registered WEB-0.4 absolute reference tolerance of 1e-8 C.
        actual = psychrolib.GetTDewPointFromRelHum(25.0, 0.80)
        self.assertAlmostEqual(actual, 21.309397163661785, delta=1e-8)


class SolarReferenceTests(unittest.TestCase):
    @staticmethod
    def _solar_frame() -> tuple[pd.DataFrame, float]:
        zenith_deg = 30.0
        dni = 800.0
        dhi = 100.0
        ghi = dni * math.cos(math.radians(zenith_deg)) + dhi
        frame = pd.DataFrame(
            {
                "solar_apparent_zenith_deg": [zenith_deg],
                "solar_azimuth_deg": [180.0],
                "direct_normal_radiation_wh_m2": [dni],
                "global_horizontal_radiation_wh_m2": [ghi],
                "diffuse_horizontal_radiation_wh_m2": [dhi],
            },
            index=pd.DatetimeIndex(["2025-06-21 12:00:00"]),
        )
        return frame, ghi

    def test_horizontal_poa_equals_consistent_ghi(self) -> None:
        frame, ghi = self._solar_frame()
        poa = surface_irradiance_series(frame, surface_tilt_deg=0.0, surface_azimuth_deg=180.0, albedo=0.2)
        self.assertAlmostEqual(float(poa.iloc[0]), ghi, places=6)

    def test_vertical_south_poa_matches_manual_isotropic_decomposition(self) -> None:
        frame, ghi = self._solar_frame()
        dni = 800.0
        dhi = 100.0
        # sun zenith 30°, sun azimuth 180°, vertical south plane:
        # cos(AOI)=0.5; isotropic sky view factor=0.5; ground view factor=0.5.
        expected = dni * 0.5 + dhi * 0.5 + ghi * 0.2 * 0.5
        poa = surface_irradiance_series(frame, surface_tilt_deg=90.0, surface_azimuth_deg=180.0, albedo=0.2)
        self.assertAlmostEqual(float(poa.iloc[0]), expected, places=6)

    def test_fractional_epw_utc_offset_is_preserved(self) -> None:
        frame = pd.DataFrame(index=pd.DatetimeIndex(["2025-01-01 12:00:00"]))
        location = EpwLocation(
            city="Reference",
            state="",
            country="XX",
            source="TEST",
            wmo="000000",
            latitude=28.6,
            longitude=77.2,
            utc_offset=5.5,
            elevation_m=200.0,
        )
        localized = localized_times(frame, location)
        offset_seconds = localized[0].utcoffset().total_seconds()
        self.assertEqual(offset_seconds, 5.5 * 3600.0)


class EpwTimeSemanticsTests(unittest.TestCase):
    def test_epw_hour_1_and_24_map_to_plotting_hours_0_and_23(self) -> None:
        raw = pd.DataFrame(
            {
                "year": [1999, 2003],
                "month": [1, 1],
                "day": [1, 1],
                "hour": [1, 24],
            }
        )
        index = build_datetime_index(raw, target_year=2025)
        self.assertEqual(index[0], pd.Timestamp("2025-01-01 00:00:00"))
        self.assertEqual(index[1], pd.Timestamp("2025-01-01 23:00:00"))

    def test_source_year_does_not_control_typical_calendar(self) -> None:
        raw = pd.DataFrame(
            {
                "year": [1998, 2017, 2004],
                "month": [1, 6, 12],
                "day": [15, 15, 15],
                "hour": [12, 12, 12],
            }
        )
        index = build_datetime_index(raw, target_year=2025)
        self.assertTrue((index.year == 2025).all())


class DecisionReferenceTests(unittest.TestCase):
    def test_degree_hour_proxies_are_exact_at_and_around_thresholds(self) -> None:
        frame = pd.DataFrame({"dry_bulb_temperature_c": [10.0, 18.0, 22.0, 26.0, 30.0]})
        out = add_degree_metrics(frame, heating_base_c=18.0, cooling_base_c=26.0)
        np.testing.assert_allclose(out["heating_degree_hours_kh"], [8.0, 0.0, 0.0, 0.0, 0.0])
        np.testing.assert_allclose(out["cooling_degree_hours_kh"], [0.0, 0.0, 0.0, 0.0, 4.0])

    @staticmethod
    def _two_day_night_flush_frame() -> pd.DataFrame:
        index = pd.date_range("2025-07-01 00:00:00", periods=48, freq="h")
        temperature = np.full(48, 22.0)
        temperature[15] = 30.0  # hot first day
        temperature[22] = 18.0  # same-day late evening can flush
        temperature[24:31] = 18.0  # early next morning follows the hot first day
        temperature[39] = 22.0  # second-day maximum remains below hot threshold
        temperature[46] = 18.0
        return pd.DataFrame(
            {
                "dry_bulb_temperature_c": temperature,
                "hour_of_day": index.hour,
            },
            index=index,
        )

    def test_night_flushing_early_morning_uses_previous_hot_day(self) -> None:
        frame = self._two_day_night_flush_frame()
        mask = night_flushing_condition(frame)
        self.assertTrue(bool(mask.loc["2025-07-01 22:00:00"]))
        self.assertTrue(bool(mask.loc["2025-07-02 03:00:00"]))
        self.assertFalse(bool(mask.loc["2025-07-02 22:00:00"]))
        self.assertFalse(bool(mask.loc["2025-07-01 03:00:00"]))

    def test_non_crossing_early_night_interval_does_not_select_all_day(self) -> None:
        frame = self._two_day_night_flush_frame()
        mask = night_flushing_condition(frame, night_start_hour=1, night_end_hour=5)
        selected = list(frame.index[mask])
        self.assertEqual(selected, list(pd.date_range("2025-07-02 01:00:00", periods=5, freq="h")))


if __name__ == "__main__":
    unittest.main()
