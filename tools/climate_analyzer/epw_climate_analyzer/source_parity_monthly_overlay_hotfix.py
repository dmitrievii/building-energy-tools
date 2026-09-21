"""Timezone-safe native-monthly time-series overlay boundary handling.

Native GeoSphere monthly aggregation intentionally represents calendar periods
with timezone-naive month/season/year starts. The shared time-series UI can pass
UTC-aware filter bounds. Pandas refuses direct comparisons between those two
representations even though they refer to the same UTC calendar boundary.

This final runtime guard keeps the published monthly values and aggregation
semantics unchanged and normalizes only the comparison/plot bounds to UTC-naive
timestamps before clipping interval bars.
"""
from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

import pandas as pd


def _current_contract() -> ModuleType:
    """Resolve the active contract module after Streamlit runtime reloads."""
    return importlib.import_module(f"{__package__}.source_parity_contract_closure")


def _utc_naive(value: Any) -> pd.Timestamp:
    """Return a Timestamp comparable with native-monthly calendar period keys."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _monthly_overlay_table_timezone_safe(
    contract: ModuleType,
    df: pd.DataFrame,
    column: str,
    resolution: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    values = contract.monthly_period_values(df, column, resolution)
    frame = values.rename("value").to_frame()
    frame["interval_start"] = pd.DatetimeIndex(frame.index).tz_localize(None)

    if resolution == "Monthly":
        frame["interval_end"] = [pd.Timestamp(ts) + pd.offsets.MonthBegin(1) for ts in frame["interval_start"]]
    elif resolution == "Seasonal":
        frame["interval_end"] = [pd.Timestamp(ts) + pd.DateOffset(months=3) for ts in frame["interval_start"]]
    elif resolution == "Annual":
        frame["interval_end"] = [pd.Timestamp(ts) + pd.offsets.YearBegin(1) for ts in frame["interval_start"]]
    else:
        raise ValueError(f"Unsupported native-monthly overlay resolution: {resolution}")

    start_bound = _utc_naive(start)
    end_bound = _utc_naive(end)
    if end_bound < start_bound:
        raise ValueError("Time-series overlay end must not be earlier than start.")

    frame = frame.loc[
        (frame["interval_end"] > start_bound)
        & (frame["interval_start"] < end_bound)
    ].copy()
    frame["plot_start"] = frame["interval_start"].where(
        frame["interval_start"] >= start_bound,
        start_bound,
    )
    frame["plot_end"] = frame["interval_end"].where(
        frame["interval_end"] <= end_bound,
        end_bound,
    )
    frame["resolution"] = resolution
    frame["aggregation"] = contract._monthly_semantics(column)
    return frame


def install_monthly_overlay_timezone_guard() -> None:
    """Install the timezone-safe overlay implementation on the active contract."""
    contract = _current_contract()
    current = contract._monthly_overlay_table
    if bool(getattr(current, "_MONTHLY_OVERLAY_TIMEZONE_SAFE", False)):
        return

    def monthly_overlay_table(
        df: pd.DataFrame,
        column: str,
        resolution: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:
        return _monthly_overlay_table_timezone_safe(
            contract,
            df,
            column,
            resolution,
            start,
            end,
        )

    monthly_overlay_table._MONTHLY_OVERLAY_TIMEZONE_SAFE = True
    contract._monthly_overlay_table = monthly_overlay_table
