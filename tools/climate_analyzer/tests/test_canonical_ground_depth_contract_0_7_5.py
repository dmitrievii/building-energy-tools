from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from epw_climate_analyzer import ground_temperature, source_parity_ground
from epw_climate_analyzer.historical_capabilities import available_historical_pages


class CanonicalGroundDepthContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_depths = dict(ground_temperature.MEASURED_GROUND_DEPTHS_M)

    def tearDown(self) -> None:
        ground_temperature.MEASURED_GROUND_DEPTHS_M.clear()
        ground_temperature.MEASURED_GROUND_DEPTHS_M.update(self.original_depths)

    def _legacy(self):
        calls: list[tuple[str, object]] = []

        def original_temperature(df, **kwargs):
            calls.append(("temperature", kwargs))

        def ground_page(df, **kwargs):
            calls.append(("ground", kwargs))

        return SimpleNamespace(
            VARIABLES={},
            render_temperature=original_temperature,
            render_ground_temperature_page=ground_page,
        ), calls

    def test_install_registers_one_and_two_metre_depths_and_labels(self) -> None:
        legacy, _calls = self._legacy()
        source_parity_ground.install_ground_depth_contract(legacy)
        self.assertEqual(ground_temperature.MEASURED_GROUND_DEPTHS_M["ground_temperature_1_00m_c"], 1.0)
        self.assertEqual(ground_temperature.MEASURED_GROUND_DEPTHS_M["ground_temperature_2_00m_c"], 2.0)
        self.assertEqual(legacy.VARIABLES["Ground temperature 1.00 m"][0], "ground_temperature_1_00m_c")
        self.assertEqual(legacy.VARIABLES["Ground temperature 2.00 m"][0], "ground_temperature_2_00m_c")

    def test_measured_monthly_ground_uses_same_engine_for_deep_depths(self) -> None:
        legacy, _calls = self._legacy()
        source_parity_ground.install_ground_depth_contract(legacy)
        index = pd.date_range("2026-01-01", periods=4, freq="15D", tz="UTC")
        frame = pd.DataFrame(
            {
                "ground_temperature_1_00m_c": [8.0, 8.2, 8.4, 8.6],
                "ground_temperature_2_00m_c": [9.0, 9.1, 9.2, 9.3],
            },
            index=index,
        )
        measured = ground_temperature.measured_monthly_ground(frame)
        self.assertEqual(set(measured["depth_m"].tolist()), {1.0, 2.0})
        self.assertTrue(measured["temperature_c"].notna().all())

    def test_deep_ground_only_dataset_unlocks_temperature_page(self) -> None:
        index = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        frame = pd.DataFrame({"ground_temperature_2_00m_c": [9.0, 9.1, 9.2]}, index=index)
        self.assertIn("Temperature", available_historical_pages(frame))

    def test_deep_ground_only_render_routes_directly_to_common_ground_page(self) -> None:
        legacy, calls = self._legacy()
        fake_streamlit = SimpleNamespace(header=lambda *_args, **_kwargs: None)
        with patch.object(source_parity_ground, "st", fake_streamlit):
            source_parity_ground.install_ground_depth_contract(legacy)
            index = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
            frame = pd.DataFrame({"ground_temperature_2_00m_c": [9.0, 9.1, 9.2]}, index=index)
            legacy.render_temperature(frame, ground_source_label="Measured canonical ground")
        self.assertEqual([item[0] for item in calls], ["ground"])
        self.assertEqual(calls[0][1]["source_label"], "Measured canonical ground")

    def test_normal_air_temperature_path_remains_mature_renderer(self) -> None:
        legacy, calls = self._legacy()
        source_parity_ground.install_ground_depth_contract(legacy)
        index = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        frame = pd.DataFrame({"dry_bulb_temperature_c": [1.0, 2.0, 3.0]}, index=index)
        legacy.render_temperature(frame, interval_count_metrics=False)
        self.assertEqual([item[0] for item in calls], ["temperature"])
        self.assertFalse(calls[0][1]["interval_count_metrics"])


if __name__ == "__main__":
    unittest.main()
