"""Canonical measured-ground-depth migration contract.

The ground-temperature engine is source-neutral: provider adapters expose depth-
specific canonical columns and this contract registers their physical depths for
the existing measured-vs-calculated profile/animation engine.  No GeoSphere-
specific renderer or calculation is introduced.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from . import ground_temperature


CANONICAL_GROUND_DEPTHS_M = {
    "ground_temperature_0_10m_c": 0.10,
    "ground_temperature_0_20m_c": 0.20,
    "ground_temperature_0_50m_c": 0.50,
    "ground_temperature_1_00m_c": 1.00,
    "ground_temperature_2_00m_c": 2.00,
}

GROUND_VARIABLE_LABELS = {
    "Ground temperature 0.10 m": ("ground_temperature_0_10m_c", "°C"),
    "Ground temperature 0.20 m": ("ground_temperature_0_20m_c", "°C"),
    "Ground temperature 0.50 m": ("ground_temperature_0_50m_c", "°C"),
    "Ground temperature 1.00 m": ("ground_temperature_1_00m_c", "°C"),
    "Ground temperature 2.00 m": ("ground_temperature_2_00m_c", "°C"),
}


def _numeric(df: pd.DataFrame, column: str) -> bool:
    return column in df.columns and pd.to_numeric(df[column], errors="coerce").notna().any()


def install_ground_depth_contract(legacy: Any) -> None:
    """Register all canonical measured ground depths in the common UI/engine."""
    # The production runtime passes the mature app proxy, including its Streamlit
    # surface. Lightweight unit tests intentionally use a minimal namespace; do
    # not make this ground-depth contract depend on those optional UX installers.
    if hasattr(legacy, "st"):
        from . import source_parity_ui as parity
        from .source_parity_ux_followup import install_geosphere_variable_form, install_interannual_overlay

        install_geosphere_variable_form(parity)
        install_interannual_overlay(legacy)

    ground_temperature.MEASURED_GROUND_DEPTHS_M.update(CANONICAL_GROUND_DEPTHS_M)
    legacy.VARIABLES.update(GROUND_VARIABLE_LABELS)

    if hasattr(legacy, "_source_parity_original_temperature_ground_depths"):
        return

    original = legacy.render_temperature
    legacy._source_parity_original_temperature_ground_depths = original

    def render_temperature_all_ground_depths(
        df: pd.DataFrame,
        *,
        interval_count_metrics: bool = True,
        ground_source_label: str | None = None,
        ground_native_df: pd.DataFrame | None = None,
    ) -> None:
        """Preserve the mature page and handle a canonical deep-ground-only set."""
        measured = ground_native_df if ground_native_df is not None else df
        has_air = _numeric(df, "dry_bulb_temperature_c")
        has_shallow = any(
            _numeric(measured, column)
            for column in (
                "ground_temperature_0_10m_c",
                "ground_temperature_0_20m_c",
                "ground_temperature_0_50m_c",
            )
        )
        has_any_ground = any(_numeric(measured, column) for column in CANONICAL_GROUND_DEPTHS_M)

        # The mature renderer already handles all normal air/shallow-ground
        # combinations. Its internal availability check predates the 1/2 m
        # canonical depths, so only the deep-ground-only edge case needs routing.
        if has_any_ground and not has_air and not has_shallow:
            st.header("Temperature and extremes")
            legacy.render_ground_temperature_page(
                df,
                source_label=ground_source_label or "Measured ground temperature",
                native_df=ground_native_df,
            )
            return

        original(
            df,
            interval_count_metrics=interval_count_metrics,
            ground_source_label=ground_source_label,
            ground_native_df=ground_native_df,
        )

    legacy.render_temperature = render_temperature_all_ground_depths
