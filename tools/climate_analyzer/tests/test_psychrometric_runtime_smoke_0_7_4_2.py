from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis


DEFAULT_METRIC_LAYERS = ["Dry-bulb temperature", "Humidity ratio", "Relative humidity"]


def sample_frame(*, multiyear: bool = False) -> pd.DataFrame:
    periods = 24 * (420 if multiyear else 60)
    index = pd.date_range("2025-01-01", periods=periods, freq="h")
    phase = np.linspace(0.0, 8.0 * np.pi if multiyear else 4.0 * np.pi, len(index))
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


def render_like_streamlit(
    df: pd.DataFrame,
    *,
    chart_type: str = "T-d",
    representation: str = "Climate zone",
    zone_interior_style: str = "Density gradient",
    show_givoni: bool = True,
    year_mode: str = "All years combined",
    selected_years: list[int] | None = None,
):
    return psychrometric_chart(
        df,
        chart_type=chart_type,
        pressure_pa=101325.0,
        show_rh_curves=True,
        show_comfort_zone=show_givoni,
        data_mode=representation,
        t_range=(-20.0, 40.0),
        d_range=(0.0, 25.0),
        h_range=(-20.0, 100.0),
        metric_layers=DEFAULT_METRIC_LAYERS,
        shown_bioclimatic_zones=None,
        show_heat_index_overlay=False,
        selected_months=list(range(1, 13)),
        color_metric_column=None,
        color_metric_label="Month",
        color_mode="Month",
        zone_coverage=0.90,
        zone_interior_style=zone_interior_style,
        show_core_zone=True,
        year_mode=year_mode,
        selected_years=selected_years,
    )


class PsychrometricRuntimeSmoke0742Tests(unittest.TestCase):
    def assert_runtime_figure(self, fig) -> None:
        self.assertGreater(len(fig.data), 0)
        fig.to_plotly_json()

    def test_exact_default_t_d_ui_state_builds_figure(self) -> None:
        self.assert_runtime_figure(render_like_streamlit(sample_frame(), chart_type="T-d"))

    def test_exact_default_i_d_ui_state_builds_figure(self) -> None:
        self.assert_runtime_figure(render_like_streamlit(sample_frame(), chart_type="i-d"))

    def test_all_zone_interior_styles_build(self) -> None:
        df = sample_frame()
        for style in ("Density gradient", "Sparse points", "Solid fill", "Contour only"):
            with self.subTest(style=style):
                self.assert_runtime_figure(render_like_streamlit(df, zone_interior_style=style))

    def test_points_mode_builds(self) -> None:
        self.assert_runtime_figure(render_like_streamlit(sample_frame(), representation="Points"))

    def test_multiyear_single_year_and_compare_years_build(self) -> None:
        df = sample_frame(multiyear=True)
        years = sorted({int(value) for value in df.index.year})
        self.assertGreaterEqual(len(years), 2)
        self.assert_runtime_figure(
            render_like_streamlit(df, year_mode="Single year", selected_years=[years[-1]])
        )
        self.assert_runtime_figure(
            render_like_streamlit(df, year_mode="Compare selected years", selected_years=years[-2:])
        )


if __name__ == "__main__":
    unittest.main()
