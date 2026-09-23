"""Streamlit control that attaches focused-year presentation metadata.

The UI layer owns only selection. Actual Plotly styling is performed by the
interannual chart builders from :mod:`interannual_presentation`, so the visual
contract cannot be bypassed by later Streamlit/runtime wrappers.
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


def install_interannual_year_highlight(proxy: Any) -> None:
    """Install source-neutral focused-year controls for interannual chart routes."""
    if bool(getattr(proxy, "_INTERANNUAL_YEAR_HIGHLIGHT_INSTALLED", False)):
        return

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
