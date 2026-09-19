from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.solar import surface_irradiance_series


class SourceParityPoaMissingDataTests(unittest.TestCase):
    def test_missing_mandatory_radiation_inputs_remain_missing(self) -> None:
        index = pd.date_range("2026-06-21 10:00", periods=5, freq="h", tz="UTC")
        frame = pd.DataFrame(
            {
                "solar_apparent_zenith_deg": [30.0, 30.0, 30.0, 30.0, np.nan],
                "solar_azimuth_deg": [180.0, 180.0, 180.0, np.nan, 180.0],
                "direct_normal_radiation_wh_m2": [500.0, np.nan, 500.0, 500.0, 500.0],
                "global_horizontal_radiation_wh_m2": [600.0, 600.0, np.nan, 600.0, 600.0],
                "diffuse_horizontal_radiation_wh_m2": [100.0, 100.0, 100.0, 100.0, np.nan],
            },
            index=index,
        )

        poa = surface_irradiance_series(frame, 90.0, 180.0)

        self.assertTrue(np.isfinite(float(poa.iloc[0])))
        self.assertTrue(poa.iloc[1:].isna().all())


if __name__ == "__main__":
    unittest.main()
