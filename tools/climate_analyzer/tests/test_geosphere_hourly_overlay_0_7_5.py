from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.geosphere import provider_frame_to_canonical, resource_spec
from epw_climate_analyzer.geosphere_resource_overlay import apply_geosphere_resource_overlay


class GeoSphereHourlyOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apply_geosphere_resource_overlay()

    def test_hourly_provider_vocabulary_maps_sunshine_and_deep_ground(self) -> None:
        spec = resource_spec("klima-v2-1h")
        mapping = spec.field_by_provider
        self.assertEqual(mapping["so_h"].canonical_name, "sunshine_duration_s")
        self.assertEqual(mapping["so_h"].scale, 3600.0)
        self.assertEqual(mapping["tb100"].canonical_name, "ground_temperature_1_00m_c")
        self.assertEqual(mapping["tb200"].canonical_name, "ground_temperature_2_00m_c")

    def test_hourly_sunshine_hours_convert_to_canonical_seconds(self) -> None:
        index = pd.date_range("2026-07-15T10:00:00Z", periods=2, freq="h")
        provider = pd.DataFrame(
            {
                "so_h": [0.25, 1.0],
                "tb100": [13.5, 13.6],
                "tb200": [11.2, 11.2],
            },
            index=index,
        )
        mapping = resource_spec("klima-v2-1h").field_by_provider
        selected = {name: mapping[name] for name in provider.columns}
        canonical = provider_frame_to_canonical(provider, selected)
        self.assertEqual(canonical["sunshine_duration_s"].tolist(), [900.0, 3600.0])
        self.assertEqual(canonical["ground_temperature_1_00m_c"].tolist(), [13.5, 13.6])
        self.assertEqual(canonical["ground_temperature_2_00m_c"].tolist(), [11.2, 11.2])


if __name__ == "__main__":
    unittest.main()
