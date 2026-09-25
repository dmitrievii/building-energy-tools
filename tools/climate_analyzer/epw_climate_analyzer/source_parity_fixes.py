"""Small runtime fixes for the source-parity Streamlit migration layer.

Kept separate from the large UI adapter so the stable migration shell remains
reviewable and edge-case fixes stay independently testable.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st

from .analysis_clock import LOCAL_CIVIL_TIME, LOCAL_STANDARD_TIME, SOURCE_TIME, UTC_TIME, add_calendar_columns
from .climate_model import aggregation_semantics_for
from .comparison_memory_hotfix import install_comparison_memory_hotfix
from .epw_header import parse_epw_header
from .quality_policy import QUALITY_POLICY_ALL


def _calendar_mean_year(climate: Any) -> Any:
    """Return one representative calendar year for a real multi-year climate.

    Each equivalent month/day/hour position is averaged across represented real
    years.  Extensive interval quantities are averaged per equivalent interval,
    so summing the resulting representative year yields a mean annual total.
    Circular variables use vector means.
    """
    df = climate.data
    if not isinstance(df.index, pd.DatetimeIndex):
        return climate
    years = sorted({int(value) for value in pd.DatetimeIndex(df.index).year})
    if len(years) <= 1:
        return climate

    keys = pd.MultiIndex.from_arrays(
        [df.index.month, df.index.day, df.index.hour],
        names=["month", "day", "hour"],
    )
    unique_keys = keys.unique().sort_values()
    grouped = pd.DataFrame(index=unique_keys)
    numeric_columns = [column for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]
    for column in numeric_columns:
        values = pd.to_numeric(df[column], errors="coerce")
        semantics = aggregation_semantics_for(column)
        indexed = pd.Series(values.to_numpy(), index=keys, dtype="float64")
        if semantics == "circular mean":
            radians = np.deg2rad(indexed)
            sin_mean = pd.Series(np.sin(radians), index=keys).groupby(level=[0, 1, 2]).mean()
            cos_mean = pd.Series(np.cos(radians), index=keys).groupby(level=[0, 1, 2]).mean()
            series = pd.Series(
                np.mod(np.rad2deg(np.arctan2(sin_mean, cos_mean)), 360.0),
                index=sin_mean.index,
                dtype="float64",
            )
        elif semantics == "max":
            # Source interval extrema should remain extrema when comparing a
            # representative calendar position across years.
            series = indexed.groupby(level=[0, 1, 2]).max()
        elif semantics == "min":
            series = indexed.groupby(level=[0, 1, 2]).min()
        else:
            series = indexed.groupby(level=[0, 1, 2]).mean()
        grouped[column] = series.reindex(unique_keys)

    timestamps: list[pd.Timestamp] = []
    valid_keys: list[tuple[int, int, int]] = []
    # 2024 is deliberately leap-capable so a real February 29 is not discarded.
    for month, day, hour in unique_keys:
        try:
            timestamps.append(pd.Timestamp(year=2024, month=int(month), day=int(day), hour=int(hour)))
            valid_keys.append((int(month), int(day), int(hour)))
        except ValueError:
            continue
    grouped = grouped.loc[valid_keys].copy()
    grouped.index = pd.DatetimeIndex(timestamps, name="timestamp")
    grouped.attrs.update(df.attrs)
    grouped = add_calendar_columns(grouped)
    grouped.attrs.update(df.attrs)
    grouped.attrs["comparison_historical_basis"] = "calendar mean year"
    grouped.attrs["canonical_native_interval_minutes"] = 60
    grouped.attrs["canonical_analysis_interval_minutes"] = 60
    return replace(climate, data=grouped, display_name=f"{climate.display_name} · mean year")


def _analysis_clock_without_duplicate_widget(parity: Any, dataset: Any):
    """Avoid instantiating the same sidebar widget twice on Compare Climates."""
    if st.session_state.get("climate_analyzer_navigation") == "Compare Climates":
        local_timezone = str(dataset.data.attrs.get("canonical_analysis_timezone_name") or "").strip() or None
        standard_offset = dataset.data.attrs.get("canonical_standard_utc_offset_hours")
        try:
            standard_offset = float(standard_offset) if standard_offset is not None else None
        except (TypeError, ValueError):
            standard_offset = None
        selected = str(st.session_state.get("historical_analysis_clock", LOCAL_CIVIL_TIME if local_timezone else SOURCE_TIME))
        if selected not in {SOURCE_TIME, LOCAL_CIVIL_TIME, LOCAL_STANDARD_TIME, UTC_TIME}:
            selected = LOCAL_CIVIL_TIME if local_timezone else SOURCE_TIME
        if selected == LOCAL_STANDARD_TIME and standard_offset is None:
            selected = LOCAL_CIVIL_TIME if local_timezone else SOURCE_TIME
        return selected, local_timezone, standard_offset
    return parity._source_parity_unfixed_analysis_clock(dataset)


def _quality_without_duplicate_widget(parity: Any, dataset: Any) -> str:
    if st.session_state.get("climate_analyzer_navigation") == "Compare Climates":
        return str(st.session_state.get("historical_quality_policy", QUALITY_POLICY_ALL))
    return parity._source_parity_unfixed_quality_policy(dataset)


def _append_epw_header_metadata(legacy: Any, original: Any, epw: Any, df: pd.DataFrame, issues: list[object]) -> None:
    """Render structured EPW metadata after the existing diagnostics page."""
    original(epw, df, issues)
    try:
        metadata = parse_epw_header(epw.header_lines)
    except Exception as exc:
        st.caption(f"Structured EPW header metadata could not be parsed: {exc}")
        return

    if metadata.typical_extreme_periods:
        st.subheader("Typical and extreme periods")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Name": item.name,
                        "Type": item.period_type,
                        "Start": item.start,
                        "End": item.end,
                    }
                    for item in metadata.typical_extreme_periods
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    with st.expander("Structured EPW header metadata", expanded=False):
        if metadata.design_conditions_tokens:
            st.markdown("**Design conditions**")
            st.write(list(metadata.design_conditions_tokens))
        if metadata.holidays_daylight_savings_tokens:
            st.markdown("**Holidays / daylight savings**")
            st.write(list(metadata.holidays_daylight_savings_tokens))
        if metadata.data_periods_tokens:
            st.markdown("**Data periods**")
            st.write(list(metadata.data_periods_tokens))
        if metadata.comments_1:
            st.markdown("**Comments 1**")
            st.write(metadata.comments_1)
        if metadata.comments_2:
            st.markdown("**Comments 2**")
            st.write(metadata.comments_2)


def apply_source_parity_fixes(legacy: Any, parity: Any) -> None:
    """Patch migration-layer edge cases after ``install_source_parity_ui``."""
    parity._calendar_mean_year = _calendar_mean_year

    if not hasattr(parity, "_source_parity_unfixed_analysis_clock"):
        parity._source_parity_unfixed_analysis_clock = parity._analysis_clock_contract
        parity._analysis_clock_contract = lambda dataset: _analysis_clock_without_duplicate_widget(parity, dataset)
    if not hasattr(parity, "_source_parity_unfixed_quality_policy"):
        parity._source_parity_unfixed_quality_policy = parity._quality_policy_control
        parity._quality_policy_control = lambda dataset: _quality_without_duplicate_widget(parity, dataset)

    if not hasattr(legacy, "_source_parity_original_epw_data_quality"):
        legacy._source_parity_original_epw_data_quality = legacy.render_data_quality
        legacy.render_data_quality = lambda epw, df, issues: _append_epw_header_metadata(
            legacy,
            legacy._source_parity_original_epw_data_quality,
            epw,
            df,
            issues,
        )

    install_comparison_memory_hotfix(legacy)
