"""Focused-year styling for rendered interannual charts.

The scientific interannual representation remains unchanged. This module adds a
presentation control that can focus one real source year: background *year*
traces are dimmed, while every trace belonging to the selected year is rendered
red, thicker, fully opaque, and last so Plotly paints it above the other traces.
Non-year analytical traces such as the interannual mean/min/max envelope keep
their original styling.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from .temporal_filtering import INTERANNUAL_OVERLAY, time_basis


HIGHLIGHT_COLOR = "#dc2626"
HIGHLIGHT_WIDTH = 4.0
HIGHLIGHT_MARKER_SIZE = 7.0
BACKGROUND_OPACITY = 0.32
HIGHLIGHT_STATE_KEY = "overlay_highlight_year"


def _trace_real_year(trace: Any) -> int | None:
    """Return the real year encoded by an interannual trace legend group."""
    value = getattr(trace, "legendgroup", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def apply_interannual_year_highlight(fig: Any, year: int | None) -> Any:
    """Style and reorder an interannual Plotly figure around one selected year.

    Plotly draws later traces above earlier traces. The selected year's traces
    are therefore moved to the end after styling. Only traces whose
    ``legendgroup`` is a real year participate in dimming/highlighting. Envelope,
    reference and other analytical traces are left visually unchanged.
    """
    if year is None:
        return fig

    selected_year = int(year)
    trace_years = [_trace_real_year(trace) for trace in tuple(fig.data)]
    if selected_year not in trace_years:
        # A stale widget selection must never alter an unrelated chart.
        return fig

    background_years: list[Any] = []
    neutral: list[Any] = []
    highlighted: list[Any] = []

    for trace, trace_year in zip(tuple(fig.data), trace_years, strict=True):
        if trace_year is None:
            neutral.append(trace)
            continue

        if trace_year == selected_year:
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
            background_years.append(trace)

    # Neutral analytical traces preserve their relative order, while the
    # highlighted real-year trace is deliberately painted above everything.
    fig.data = tuple(background_years + neutral + highlighted)
    return fig


def _selected_highlight_year(proxy: Any, df: pd.DataFrame) -> int | None:
    """Render/read the highlight control for a multi-year interannual frame."""
    if time_basis(df) != INTERANNUAL_OVERLAY or not isinstance(df.index, pd.DatetimeIndex):
        return None

    years = sorted({int(value) for value in pd.DatetimeIndex(df.index).year})
    if len(years) < 2:
        return None

    options: list[int | None] = [None, *years]
    stored = proxy.st.session_state.get(HIGHLIGHT_STATE_KEY)
    if stored not in options:
        proxy.st.session_state[HIGHLIGHT_STATE_KEY] = None

    selected = proxy.st.selectbox(
        "Highlight year",
        options,
        index=0,
        key=HIGHLIGHT_STATE_KEY,
        format_func=lambda value: "None" if value is None else str(int(value)),
        help=(
            "Focus one real source year in the Interannual overlay. The selected year is drawn red, thicker, "
            "fully opaque, and above the other yearly traces; the underlying data and aggregation do not change."
        ),
    )
    return None if selected is None else int(selected)


def _render_with_highlight_context(
    proxy: Any,
    renderer: Callable[..., Any],
    df: pd.DataFrame,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Apply the selected year only while this interannual renderer is active.

    This deliberately does not depend on a sidebar/session-state copy of the time
    basis. ``time_basis(df)`` is the authoritative contract. Temporarily wrapping
    ``render_plot`` keeps the styling local to the current page and prevents a
    stale year selection from leaking into unrelated charts.
    """
    selected = _selected_highlight_year(proxy, df)
    if selected is None or not hasattr(proxy, "render_plot"):
        return renderer(df, *args, **kwargs)

    original_render_plot = proxy.render_plot

    def highlighted_render_plot(fig: Any, *plot_args: Any, **plot_kwargs: Any) -> Any:
        styled = apply_interannual_year_highlight(fig, selected)
        return original_render_plot(styled, *plot_args, **plot_kwargs)

    proxy.render_plot = highlighted_render_plot
    try:
        return renderer(df, *args, **kwargs)
    finally:
        proxy.render_plot = original_render_plot


def install_interannual_year_highlight(proxy: Any) -> None:
    """Install source-neutral focused-year controls for interannual chart routes."""
    if bool(getattr(proxy, "_INTERANNUAL_YEAR_HIGHLIGHT_INSTALLED", False)):
        return

    original_overlay = proxy.render_time_series_overlay

    def render_time_series_overlay(df: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
        return _render_with_highlight_context(proxy, original_overlay, df, *args, **kwargs)

    proxy.render_time_series_overlay = render_time_series_overlay

    # Generic variable pages (Temperature, Humidity, etc.) use the interannual
    # profile/envelope builders rather than build_overlay_figure. Bind the same
    # final-render context around that route too.
    if hasattr(proxy, "render_generic_variable_page"):
        original_generic = proxy.render_generic_variable_page

        def render_generic_variable_page(df: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
            return _render_with_highlight_context(proxy, original_generic, df, *args, **kwargs)

        proxy.render_generic_variable_page = render_generic_variable_page

    proxy._INTERANNUAL_YEAR_HIGHLIGHT_INSTALLED = True
