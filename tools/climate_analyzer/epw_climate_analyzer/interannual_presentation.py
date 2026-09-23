"""Pure presentation contract for focused-year interannual charts.

This module is intentionally Streamlit-free. The active focused year is carried
on the dataframe as presentation metadata and applied by the chart builders when
they create Plotly traces. This avoids late runtime monkey-patching of render
functions and makes the visual contract testable at the same layer that produces
the figure sent to the browser.
"""

from __future__ import annotations

import re
from typing import Any


HIGHLIGHT_ATTR = "interannual_highlight_year"
HIGHLIGHT_COLOR = "#dc2626"
HIGHLIGHT_WIDTH = 4.0
HIGHLIGHT_MARKER_SIZE = 7.0
BACKGROUND_OPACITY = 0.32


def highlight_year_from_frame(frame: Any) -> int | None:
    """Return the focused real year encoded in dataframe presentation metadata."""
    attrs = getattr(frame, "attrs", {}) or {}
    value = attrs.get(HIGHLIGHT_ATTR)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def trace_real_year(trace: Any) -> int | None:
    """Resolve a real year from a Plotly trace without relying on one encoding."""
    value = getattr(trace, "legendgroup", None)
    try:
        if value is not None:
            return int(value)
    except (TypeError, ValueError):
        pass

    name = str(getattr(trace, "name", "") or "")
    matches = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", name)
    if len(matches) == 1:
        return int(matches[0])
    return None


def apply_interannual_year_highlight(fig: Any, year: int | None) -> Any:
    """Style one real year and place all of its traces above the other traces."""
    if year is None:
        return fig

    selected_year = int(year)
    traces = tuple(getattr(fig, "data", ()) or ())
    trace_years = [trace_real_year(trace) for trace in traces]
    if selected_year not in trace_years:
        return fig

    background_years: list[Any] = []
    neutral: list[Any] = []
    highlighted: list[Any] = []

    for trace, trace_year in zip(traces, trace_years, strict=True):
        if trace_year is None:
            neutral.append(trace)
            continue

        if trace_year == selected_year:
            line = getattr(trace, "line", None)
            if line is not None:
                line.color = HIGHLIGHT_COLOR
                try:
                    current_width = float(getattr(line, "width", None) or 0.0)
                except (TypeError, ValueError):
                    current_width = 0.0
                line.width = max(HIGHLIGHT_WIDTH, current_width)

            mode = str(getattr(trace, "mode", "") or "")
            marker = getattr(trace, "marker", None)
            if marker is not None and "markers" in mode:
                marker.color = HIGHLIGHT_COLOR
                try:
                    current_size = float(getattr(marker, "size", None) or 0.0)
                except (TypeError, ValueError):
                    current_size = 0.0
                marker.size = max(HIGHLIGHT_MARKER_SIZE, current_size)

            trace.opacity = 1.0
            highlighted.append(trace)
            continue

        try:
            current_opacity = float(getattr(trace, "opacity", None) or 1.0)
        except (TypeError, ValueError):
            current_opacity = 1.0
        trace.opacity = min(current_opacity, BACKGROUND_OPACITY)
        background_years.append(trace)

    # Plotly paints later traces above earlier ones. Neutral analytical traces
    # retain their relative order and the selected real year is painted last.
    fig.data = tuple(background_years + neutral + highlighted)
    return fig
