"""Streamlit control and builder binding for focused-year interannual charts.

The UI layer owns selection and attaches it as dataframe presentation metadata.
Actual Plotly styling is applied at the chart-builder boundary, before the figure
is handed to Streamlit. This avoids late runtime monkey-patching of render_plot
and makes the visual contract independent of nested source-parity UI wrappers.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from .interannual_presentation import (
    BACKGROUND_OPACITY,
    HIGHLIGHT_ATTR,
    HIGHLIGHT_COLOR,
    HIGHLIGHT_MARKER_SIZE,
    HIGHLIGHT_WIDTH,
    apply_interannual_year_highlight,
    highlight_year_from_frame,
)
from .temporal_filtering import INTERANNUAL_OVERLAY, time_basis


HIGHLIGHT_STATE_KEY = "overlay_highlight_year"


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


def _frame_with_highlight_year(df: pd.DataFrame, year: int | None) -> pd.DataFrame:
    """Return a shallow presentation copy carrying the focused-year metadata."""
    if year is None:
        return df
    out = df.copy(deep=False)
    out.attrs = dict(df.attrs)
    out.attrs[HIGHLIGHT_ATTR] = int(year)
    return out


def _render_with_highlight_metadata(
    proxy: Any,
    renderer: Callable[..., Any],
    df: pd.DataFrame,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Attach selection metadata before the chart builder sees the dataframe."""
    selected = _selected_highlight_year(proxy, df)
    return renderer(_frame_with_highlight_year(df, selected), *args, **kwargs)


def _install_builder_styling() -> None:
    """Bind focused-year styling to the actual Plotly chart builders.

    The wrappers consume only dataframe presentation metadata. They therefore
    work regardless of which Streamlit/source-parity wrapper invoked the builder.
    """
    from . import charts, timeseries

    if not bool(getattr(timeseries, "_INTERANNUAL_HIGHLIGHT_BUILDER_INSTALLED", False)):
        original_overlay_builder = timeseries.build_overlay_figure

        def build_overlay_figure(df: pd.DataFrame, *args: Any, **kwargs: Any):
            fig, tables = original_overlay_builder(df, *args, **kwargs)
            year = highlight_year_from_frame(df)
            if time_basis(df) == INTERANNUAL_OVERLAY and year is not None:
                fig = apply_interannual_year_highlight(fig, year)
            return fig, tables

        timeseries.build_overlay_figure = build_overlay_figure
        timeseries._INTERANNUAL_HIGHLIGHT_BUILDER_INSTALLED = True

    if not bool(getattr(charts, "_INTERANNUAL_HIGHLIGHT_BUILDERS_INSTALLED", False)):
        original_profile = charts.profile_ribbon_chart
        original_percentile = charts.percentile_band_chart

        def profile_ribbon_chart(df: pd.DataFrame, *args: Any, **kwargs: Any):
            fig = original_profile(df, *args, **kwargs)
            year = highlight_year_from_frame(df)
            if time_basis(df) == INTERANNUAL_OVERLAY and year is not None:
                fig = apply_interannual_year_highlight(fig, year)
            return fig

        def percentile_band_chart(df: pd.DataFrame, *args: Any, **kwargs: Any):
            fig = original_percentile(df, *args, **kwargs)
            year = highlight_year_from_frame(df)
            if time_basis(df) == INTERANNUAL_OVERLAY and year is not None:
                fig = apply_interannual_year_highlight(fig, year)
            return fig

        charts.profile_ribbon_chart = profile_ribbon_chart
        charts.percentile_band_chart = percentile_band_chart
        charts._INTERANNUAL_HIGHLIGHT_BUILDERS_INSTALLED = True


def install_interannual_year_highlight(proxy: Any) -> None:
    """Install source-neutral focused-year controls and builder-level styling."""
    if bool(getattr(proxy, "_INTERANNUAL_YEAR_HIGHLIGHT_INSTALLED", False)):
        return

    _install_builder_styling()

    original_overlay = proxy.render_time_series_overlay

    def render_time_series_overlay(df: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
        return _render_with_highlight_metadata(proxy, original_overlay, df, *args, **kwargs)

    proxy.render_time_series_overlay = render_time_series_overlay

    if hasattr(proxy, "render_generic_variable_page"):
        original_generic = proxy.render_generic_variable_page

        def render_generic_variable_page(df: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
            return _render_with_highlight_metadata(proxy, original_generic, df, *args, **kwargs)

        proxy.render_generic_variable_page = render_generic_variable_page

    proxy._INTERANNUAL_YEAR_HIGHLIGHT_INSTALLED = True
