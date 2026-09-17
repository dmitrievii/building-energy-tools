"""Reproducible synthetic benchmark for the Climate 0.6.5 hourly pipeline.

This benchmark measures Python-side canonical 10-minute -> hourly normalization
and representative dataframe preparation only. It deliberately does not claim
to measure GeoSphere network latency, Streamlit rerun latency or browser Plotly
rendering.
"""

from __future__ import annotations

import gc
import time

import numpy as np
import pandas as pd

from epw_climate_analyzer.canonical_hourly import canonical_hourly_analysis_frame


YEARS = (1, 5, 10, 30)


def synthetic_frame(years: int, *, all_variables: bool) -> pd.DataFrame:
    rows = int(years) * 365 * 24 * 6
    index = pd.date_range("1990-01-01T00:00:00Z", periods=rows, freq="10min")
    x = np.arange(rows, dtype="float64")
    columns: dict[str, np.ndarray] = {
        "dry_bulb_temperature_c": 10.0 + 10.0 * np.sin(x / 10000.0),
    }
    if all_variables:
        columns.update(
            {
                "relative_humidity_pct": 60.0 + 20.0 * np.sin(x / 3000.0),
                "atmospheric_station_pressure_pa": 95000.0 + 500.0 * np.sin(x / 5000.0),
                "wind_speed_m_s": 3.0 + np.abs(np.sin(x / 700.0)) * 4.0,
                "wind_direction_deg": np.mod(x * 7.0, 360.0),
                "liquid_precipitation_depth_mm": np.where((x % 1000.0) < 3.0, 0.1, 0.0),
                "snow_depth_cm": np.maximum(0.0, 10.0 * np.sin(x / 50000.0)),
                "global_horizontal_radiation_wh_m2": np.maximum(
                    0.0, 100.0 * np.sin(np.mod(x, 144.0) / 144.0 * np.pi)
                ),
                "diffuse_horizontal_radiation_wh_m2": np.maximum(
                    0.0, 30.0 * np.sin(np.mod(x, 144.0) / 144.0 * np.pi)
                ),
            }
        )
    frame = pd.DataFrame(columns, index=index)
    frame.attrs["canonical_native_interval_minutes"] = 10
    return frame


def representative_preparation_ms(frame: pd.DataFrame) -> dict[str, float]:
    values = frame["dry_bulb_temperature_c"]
    start = time.perf_counter()
    values.groupby([frame.index.month, frame.index.hour]).mean()
    heatmap_ms = (time.perf_counter() - start) * 1000.0

    start = time.perf_counter()
    np.histogram(values.dropna().to_numpy(), bins=60)
    histogram_ms = (time.perf_counter() - start) * 1000.0

    start = time.perf_counter()
    np.sort(values.dropna().to_numpy())[::-1]
    duration_ms = (time.perf_counter() - start) * 1000.0

    start = time.perf_counter()
    values.resample("D").agg(["min", "mean", "max"])
    daily_ms = (time.perf_counter() - start) * 1000.0
    return {
        "heatmap_ms": heatmap_ms,
        "histogram_ms": histogram_ms,
        "duration_ms": duration_ms,
        "daily_profile_ms": daily_ms,
    }


def main() -> None:
    print("years,variables,native_rows,hourly_rows,reduction,normalize_s,native_mib,hourly_mib")
    for variable_mode in ("temperature-only", "all-9"):
        for years in YEARS:
            native = synthetic_frame(years, all_variables=variable_mode == "all-9")
            start = time.perf_counter()
            hourly = canonical_hourly_analysis_frame(native, source_interval_minutes=10)
            normalize_s = time.perf_counter() - start
            native_mib = native.memory_usage(deep=True).sum() / (1024.0**2)
            hourly_mib = hourly.memory_usage(deep=True).sum() / (1024.0**2)
            print(
                f"{years},{variable_mode},{len(native)},{len(hourly)},"
                f"{len(native) / max(len(hourly), 1):.3f},{normalize_s:.6f},{native_mib:.3f},{hourly_mib:.3f}"
            )
            if variable_mode == "temperature-only":
                native_ops = representative_preparation_ms(native)
                hourly_ops = representative_preparation_ms(hourly)
                print(
                    "prep_ms,"
                    f"years={years},"
                    f"native={native_ops},"
                    f"hourly={hourly_ops}"
                )
            del native, hourly
            gc.collect()


if __name__ == "__main__":
    main()
