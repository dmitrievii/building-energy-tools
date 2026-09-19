from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis


def sample_frame() -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=24 * 60, freq="h")
    phase = np.linspace(0.0, 4.0 * np.pi, len(index))
    t = 10.0 + 12.0 * np.sin(phase)
    rh = 60.0 - 20.0 * np.sin(phase)
    d = 6.0 + 3.0 * np.sin(phase + 0.6)
    h = 25.0 + 1.006 * t + 2.0 * d
    frame = pd.DataFrame(
        {
            "dry_bulb_temperature_c": t,
            "relative_humidity_pct": rh,
            "humidity_ratio_g_kg": d,
            "moist_air_enthalpy_kj_kg": h,
            "month_index": index.month,
            "month_name": index.strftime("%b"),
            "hour_of_day": index.hour,
        },
        index=index,
    )
    return with_time_basis(frame, CHRONOLOGICAL)


class PsychrometricRuntimeSmoke0742Tests(unittest.TestCase):
    def test_default_climate_zone_runtime_call_builds_figure(self) -> None:
        df = sample_frame()
        fig = psychrometric_chart(
            df,
            chart_type="T-d",
            pressure_pa=101325.0,
            show_rh_curves=True,
            show_comfort_zone=False,
            data_mode="Climate zone",
            selected_months=list(range(1, 13)),
            zone_coverage=0.90,
            zone_interior_style="Density gradient",
            show_core_zone=True,
            year_mode="All years combined",
            selected_years=None,
        )
        self.assertGreater(len(fig.data), 0)
        fig.to_plotly_json()

    def test_i_d_climate_zone_runtime_call_builds_figure(self) -> None:
        df = sample_frame()
        fig = psychrometric_chart(
            df,
            chart_type="i-d",
            pressure_pa=101325.0,
            show_rh_curves=True,
            show_comfort_zone=False,
            data_mode="Climate zone",
            selected_months=list(range(1, 13)),
            zone_coverage=0.90,
            zone_interior_style="Density gradient",
            show_core_zone=True,
            year_mode="All years combined",
            selected_years=None,
        )
        self.assertGreater(len(fig.data), 0)
        fig.to_plotly_json()


if __name__ == "__main__":
    unittest.main()
