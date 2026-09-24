"""Streamlit control and rendering bindings for focused-year interannual charts.

The UI layer owns selection and attaches it as dataframe presentation metadata.
Actual Plotly styling is applied at the chart-builder boundary when possible and
again at the final app ``render_plot`` boundary as a defensive presentation
fallback. The final boundary is important because the mature Streamlit runtime
reloads and rebinds chart modules dynamically; a valid UI selection must not
silently lose its visual effect when one intermediate builder wrapper is reset.

For generic variable explorers the focused-year selector belongs to the local
chart-control sequence, after ``Aggregation`` when that control exists. The
legacy interannual renderer already owns that lower slot. The canonical layer
therefore replaces the widget invoked in that slot instead of prepending another
selector or rendering one eagerly from the outer wrapper. This preserves the
established control order and ensures there is exactly one visible focused-year
control backed by the canonical state key.

Streamlit reruns keep imported Python package modules alive. ``importlib.reload``
re-executes module source but retains dictionary entries that are not redefined,
so module-level boolean patch guards can survive a reload even after the wrapped
function itself has been replaced by its source definition. Installation therefore
identifies current function objects instead of trusting stale module/proxy flags.
"""

from __future__ import annotations

from functools import wraps
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
_TIME_BASIS_STATE_KEY = "global_time_basis"
_BUILDER_WRAPPER_MARK = "_interannual_year_highlight_builder_wrapper"
_RENDER_WRAPPER_MARK = "_interannual_year_highlight_render_wrapper"


def _highlight_year_options(df: pd.DataFrame, *, include_none: bool = True) -> list[int | None]:
    """Return canonical focused-year options for a multi-year overlay frame."""
    if time_basis(df) != INTERANNUAL_OVERLAY or not isinstance(df.index, pd.DatetimeIndex):
        return []
    years = sorted({int(value) for value in pd.DatetimeIndex(df.index).year})
    if len(years) < 2:
        return []
    return [None, *years] if include_none else list(years)


def _stored_highlight_year(
    proxy: Any,
    df: pd.DataFrame,
    *,
    include_none: bool = True,
) -> int | None:
    """Return a valid stored focused year without rendering another widget."""
    options = _highlight_year_options(df, include_none=include_none)
    if not options:
        return None
    stored = proxy.st.session_state.get(HIGHLIGHT_STATE_KEY)
    try:
        normalized = None if stored is None else int(stored)
    except (TypeError, ValueError):
        normalized = None
    if normalized not in options:
        normalized = None if include_none else int(options[-1])
        proxy.st.session_state[HIGHLIGHT_STATE_KEY] = normalized
    return normalized


def _selected_highlight_year(
    proxy: Any,
    df: pd.DataFrame,
    *,
    selectbox: Callable[..., Any] | None = None,
    include_none: bool = True,
) -> int | None:
    """Render/read the canonical highlight control for an interannual frame."""
    options = _highlight_year_options(df, include_none=include_none)
    if not options:
        return None

    stored = _stored_highlight_year(proxy, df, include_none=include_none)
    widget = selectbox or proxy.st.selectbox
    selected = widget(
        "Highlight year",
        options,
        index=options.index(stored),
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


def _render_generic_with_positioned_highlight(
    proxy: Any,
    renderer: Callable[..., Any],
    df: pd.DataFrame,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Replace the established lower Highlight-year slot with the canonical widget.

    ``source_parity_ux_followup`` already invokes a Highlight-year selector after
    ``Aggregation``. That call is the required UI position, so this wrapper does
    not render another control after Aggregation. It intercepts the lower call,
    draws the canonical widget under ``overlay_highlight_year``, and returns the
    selected concrete year to the legacy caller so its compatibility state remains
    internally valid. Generic production profiles intentionally expose real years
    only because the legacy renderer assumes a concrete year and calls ``int`` on
    the result. Lightweight renderers without that legacy wrapper retain the
    optional ``None`` entry used by the standalone canonical control contract.
    """
    if not _highlight_year_options(df):
        return renderer(df, *args, **kwargs)

    st = proxy.st
    real_selectbox = st.selectbox
    highlight_rendered = False
    legacy_slot_expected = hasattr(proxy, "_source_parity_original_generic_interannual")
    include_none = not legacy_slot_expected
    selected = _stored_highlight_year(proxy, df, include_none=include_none)
    render_df = _frame_with_highlight_year(df, selected)

    def render_highlight() -> int | None:
        nonlocal selected, highlight_rendered
        if highlight_rendered:
            return selected
        selected = _selected_highlight_year(
            proxy,
            df,
            selectbox=real_selectbox,
            include_none=include_none,
        )
        highlight_rendered = True
        return selected

    def selectbox(label: str, options_arg: Any, *widget_args: Any, **widget_kwargs: Any) -> Any:
        if str(label) == "Highlight year":
            return render_highlight()

        result = real_selectbox(label, options_arg, *widget_args, **widget_kwargs)
        # Lightweight/unit-test renderers may not include the legacy lower-slot
        # wrapper. In that case retain the same visible position by inserting the
        # canonical widget immediately after Aggregation. Production uses the
        # legacy call as the slot trigger and must not render eagerly here.
        if str(label) == "Aggregation" and not highlight_rendered and not legacy_slot_expected:
            render_highlight()
        return result

    st.selectbox = selectbox
    try:
        return renderer(render_df, *args, **kwargs)
    finally:
        st.selectbox = real_selectbox


def _is_current_builder_wrapped(builder: Any) -> bool:
    """Return whether this exact callable is a live highlight builder wrapper."""
    return bool(getattr(builder, _BUILDER_WRAPPER_MARK, False))


def _mark_builder_wrapper(builder: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a builder wrapper on the function object, which reload replaces reliably."""
    setattr(builder, _BUILDER_WRAPPER_MARK, True)
    return builder


def _is_current_render_wrapped(renderer: Any) -> bool:
    """Return whether this exact callable is the live final-render fallback."""
    return bool(getattr(renderer, _RENDER_WRAPPER_MARK, False))


def _mark_render_wrapper(renderer: Callable[..., Any]) -> Callable[..., Any]:
    """Mark the final-render fallback directly on the function object."""
    setattr(renderer, _RENDER_WRAPPER_MARK, True)
    return renderer


def _session_highlight_year(proxy: Any) -> int | None:
    """Return the active focused year only while the global basis is Interannual overlay."""
    state = proxy.st.session_state
    if state.get(_TIME_BASIS_STATE_KEY) != INTERANNUAL_OVERLAY:
        return None
    value = state.get(HIGHLIGHT_STATE_KEY)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _install_builder_styling() -> None:
    """Bind focused-year styling to the actual Plotly chart builders.

    Do not use module-level booleans as the installation authority. Python's
    ``importlib.reload`` preserves names that are absent from reloaded source, so
    a stale ``..._INSTALLED = True`` can outlive the wrapper it described. The
    function-object marker disappears whenever reload restores the source
    function, causing the wrapper to be installed again on the next installer call.
    """
    from . import charts, timeseries

    current_overlay_builder = timeseries.build_overlay_figure
    if not _is_current_builder_wrapped(current_overlay_builder):
        @wraps(current_overlay_builder)
        def build_overlay_figure(df: pd.DataFrame, *args: Any, **kwargs: Any):
            fig, tables = current_overlay_builder(df, *args, **kwargs)
            year = highlight_year_from_frame(df)
            if time_basis(df) == INTERANNUAL_OVERLAY and year is not None:
                fig = apply_interannual_year_highlight(fig, year)
            return fig, tables

        timeseries.build_overlay_figure = _mark_builder_wrapper(build_overlay_figure)
    # Compatibility/diagnostic flag only. It is intentionally not consulted.
    timeseries._INTERANNUAL_HIGHLIGHT_BUILDER_INSTALLED = True

    current_profile = charts.profile_ribbon_chart
    if not _is_current_builder_wrapped(current_profile):
        @wraps(current_profile)
        def profile_ribbon_chart(df: pd.DataFrame, *args: Any, **kwargs: Any):
            fig = current_profile(df, *args, **kwargs)
            year = highlight_year_from_frame(df)
            if time_basis(df) == INTERANNUAL_OVERLAY and year is not None:
                fig = apply_interannual_year_highlight(fig, year)
            return fig

        charts.profile_ribbon_chart = _mark_builder_wrapper(profile_ribbon_chart)

    current_percentile = charts.percentile_band_chart
    if not _is_current_builder_wrapped(current_percentile):
        @wraps(current_percentile)
        def percentile_band_chart(df: pd.DataFrame, *args: Any, **kwargs: Any):
            fig = current_percentile(df, *args, **kwargs)
            year = highlight_year_from_frame(df)
            if time_basis(df) == INTERANNUAL_OVERLAY and year is not None:
                fig = apply_interannual_year_highlight(fig, year)
            return fig

        charts.percentile_band_chart = _mark_builder_wrapper(percentile_band_chart)

    # Compatibility/diagnostic flag only. It is intentionally not consulted.
    charts._INTERANNUAL_HIGHLIGHT_BUILDERS_INSTALLED = True


def _install_final_render_fallback(proxy: Any) -> None:
    """Style the selected year immediately before the app hands a figure to Streamlit.

    The app-level renderer is intentionally a second line of defence. Builder
    styling remains useful for shared overlay figures, but ``render_plot`` is the
    authoritative boundary for canonical profile/percentile pages. Reapplying the
    pure styling helper is idempotent and prevents runtime module rebinding from
    turning a visible Highlight year selector into a no-op.
    """
    if not hasattr(proxy, "render_plot"):
        return
    current_render = proxy.render_plot
    if _is_current_render_wrapped(current_render):
        return

    @wraps(current_render)
    def render_plot(fig: Any, *args: Any, **kwargs: Any) -> Any:
        year = _session_highlight_year(proxy)
        if year is not None:
            fig = apply_interannual_year_highlight(fig, year)
        return current_render(fig, *args, **kwargs)

    proxy.render_plot = _mark_render_wrapper(render_plot)


def install_interannual_year_highlight(proxy: Any) -> None:
    """Install source-neutral focused-year controls and resilient final styling."""
    # These bindings are deliberately refreshed on every installer call. A
    # module reload can restore source-defined builders while proxy-level
    # ``...INSTALLED`` flags remain true. Returning before this point recreates
    # the production failure where the selector survives but its styling does not.
    _install_builder_styling()
    _install_final_render_fallback(proxy)

    # UI wrappers themselves must remain single-install to avoid duplicate
    # Highlight year widgets in one app-script namespace.
    if bool(getattr(proxy, "_INTERANNUAL_YEAR_HIGHLIGHT_INSTALLED", False)):
        return

    original_overlay = proxy.render_time_series_overlay

    def render_time_series_overlay(df: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
        return _render_with_highlight_metadata(proxy, original_overlay, df, *args, **kwargs)

    proxy.render_time_series_overlay = render_time_series_overlay

    if hasattr(proxy, "render_generic_variable_page"):
        original_generic = proxy.render_generic_variable_page

        def render_generic_variable_page(df: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
            return _render_generic_with_positioned_highlight(proxy, original_generic, df, *args, **kwargs)

        proxy.render_generic_variable_page = render_generic_variable_page

    proxy._INTERANNUAL_YEAR_HIGHLIGHT_INSTALLED = True
