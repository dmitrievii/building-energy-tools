"""Focused-year styling for the shared interannual time-series overlay.

The scientific interannual representation remains unchanged.  This module only
adds a presentation control that can focus one real source year: background
years are dimmed, while every trace belonging to the selected year is rendered
red, thicker, fully opaque, and last so Plotly paints it above the other years.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .temporal_filtering import INTERANNUAL_OVERLAY, time_basis


HIGHLIGHT_COLOR = "#dc2626"
HIGHLIGHT_WIDTH = 4.0
HIGHLIGHT_MARKER_SIZE = 7.0
BACKGROUND_OPACITY = 0.32


def _trace_real_year(trace: Any) -> int | None:
    """Return the real year encoded by the interannual trace legend group."""
    value = getattr(trace, "legendgroup", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def apply_interannual_year_highlight(fig: Any, year: int | None) -> Any:
    """Style and reorder an interannual Plotly figure around one selected year.

    Plotly draws later traces above earlier traces.  The selected year's traces
    are therefore moved to the end after styling.  The operation is presentation
    only; x/y/customdata and the auditable year-preserving tables are untouched.
    """
    if year is None:
        return fig

    selected_year = int(year)
    background: list[Any] = []
    highlighted: list[Any] = []

    for trace in tuple(fig.data):
        if _trace_real_year(trace) == selected_year:
            line = getattr(trace, "line", None)
            if line is not None:
                line.color = HIGHLIGHT_COLOR
                current_width = getattr(line, "width", None)
                try:
                    current_width_value = float(current_width) if current_width is not None else 0.0
                except (TypeError, ValueError):
                    current_width_value = 0.0
                line.width = max(HIGHLIGHT_WIDTH, current_width_value)

            mode = str(getattr(trace, "mode", "") or "")
            marker = getattr(trace, "marker", None)
            if marker is not None and "markers" in mode:
                marker.color = HIGHLIGHT_COLOR
                current_size = getattr(marker, "size", None)
                try:
                    current_size_value = float(current_size) if current_size is not None else 0.0
                except (TypeError, ValueError):
                    current_size_value = 0.0
                marker.size = max(HIGHLIGHT_MARKER_SIZE, current_size_value)

            trace.opacity = 1.0
            highlighted.append(trace)
        else:
            current_opacity = getattr(trace, "opacity", None)
            try:
                opacity = float(current_opacity) if current_opacity is not None else 1.0
            except (TypeError, ValueError):
                opacity = 1.0
            trace.opacity = min(opacity, BACKGROUND_OPACITY)
            background.append(trace)

    if highlighted:
        fig.data = tuple(background + highlighted)
    return fig


def install_interannual_year_highlight(proxy: Any) -> None:
    """Add the source-neutral ``Highlight year`` control to the shared overlay.

    The mature Streamlit app keeps the overlay renderer in ``app.py``.  The
    source-parity runtime is installed before the lazy analysis imports are bound,
    so this wrapper resolves ``build_overlay_figure`` only when the page is
    actually rendered.  No provider-specific chart engine is introduced.
    """
    if bool(getattr(proxy, "_INTERANNUAL_YEAR_HIGHLIGHT_INSTALLED", False)):
        return

    original_render = proxy.render_time_series_overlay

    def render_time_series_overlay(df: pd.DataFrame) -> Any:
        if time_basis(df) != INTERANNUAL_OVERLAY or not isinstance(df.index, pd.DatetimeIndex):
            return original_render(df)

        years = sorted({int(value) for value in pd.DatetimeIndex(df.index).year})
        if len(years) < 2:
            return original_render(df)

        options: list[int | None] = [None, *years]
        key = "overlay_highlight_year"
        stored = proxy.st.session_state.get(key)
        if stored not in options:
            proxy.st.session_state[key] = None

        selected = proxy.st.sidebar.selectbox(
            "Highlight year",
            options,
            index=0,
            key=key,
            format_func=lambda value: "None" if value is None else str(int(value)),
            help=(
                "Focus one real source year in the Interannual overlay. The selected year is drawn red, thicker, "
                "fully opaque, and above the other yearly traces; the underlying data and aggregation do not change."
            ),
        )
        highlight_year = None if selected is None else int(selected)
        if highlight_year is None:
            return original_render(df)

        original_builder = proxy.build_overlay_figure

        def build_overlay_figure(*args: Any, **kwargs: Any):
            fig, tables = original_builder(*args, **kwargs)
            return apply_interannual_year_highlight(fig, highlight_year), tables

        proxy.build_overlay_figure = build_overlay_figure
        try:
            return original_render(df)
        finally:
            proxy.build_overlay_figure = original_builder

    proxy.render_time_series_overlay = render_time_series_overlay
    proxy._INTERANNUAL_YEAR_HIGHLIGHT_INSTALLED = True
