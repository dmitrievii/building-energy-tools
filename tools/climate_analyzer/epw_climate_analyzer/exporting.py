"""Tabular export helpers for Plotly charts and filtered climate data."""

from __future__ import annotations

import html
import re
from typing import Any

import pandas as pd


_HTML_RE = re.compile(r"<[^>]+>")
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_export_stem(value: object, default: str = "climate_chart") -> str:
    """Return a conservative file-name stem suitable for browser downloads."""
    text = html.unescape(str(value or ""))
    text = _HTML_RE.sub(" ", text).strip()
    text = text.replace("/", " ").replace("\\", " ")
    if text.lower().endswith(".epw"):
        text = text[:-4]
    text = _SAFE_RE.sub("_", text).strip("._-")
    return text[:120] or default


def figure_export_stem(fig: Any) -> str:
    """Derive a readable CSV filename from the Plotly title when available."""
    title = ""
    try:
        title = fig.layout.title.text or ""
    except Exception:
        pass
    return safe_export_stem(title, default="climate_chart_data")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if hasattr(value, "tolist"):
        value = value.tolist()
    try:
        return list(value)
    except TypeError:
        return [value]


def _trace_name(trace: Any, index: int) -> str:
    name = getattr(trace, "name", None)
    if name:
        return str(name)
    return f"trace_{index + 1}"


def figure_to_dataframe(fig: Any) -> pd.DataFrame:
    """Convert common Plotly trace types to a stable long-form table.

    The export represents the data carried by the rendered Plotly traces. For
    heatmaps the Z matrix is flattened to x/y/value rows; for Cartesian, polar
    and categorical traces the native coordinates are retained. This avoids
    guessing at a page-specific upstream dataframe or aggregation.
    """
    rows: list[dict[str, Any]] = []
    for trace_index, trace in enumerate(getattr(fig, "data", ())):
        trace_type = str(getattr(trace, "type", trace.__class__.__name__))
        trace_name = _trace_name(trace, trace_index)

        z = getattr(trace, "z", None)
        if z is not None:
            matrix = _as_list(z)
            if matrix and not isinstance(matrix[0], (list, tuple)):
                matrix = [matrix]
            xs = _as_list(getattr(trace, "x", None))
            ys = _as_list(getattr(trace, "y", None))
            for row_index, matrix_row in enumerate(matrix):
                values = _as_list(matrix_row)
                y_value = ys[row_index] if row_index < len(ys) else row_index
                for column_index, value in enumerate(values):
                    x_value = xs[column_index] if column_index < len(xs) else column_index
                    rows.append(
                        {
                            "trace": trace_name,
                            "trace_type": trace_type,
                            "x": x_value,
                            "y": y_value,
                            "value": value,
                        }
                    )
            continue

        coordinate_pairs = (
            ("x", "y"),
            ("theta", "r"),
            ("labels", "values"),
        )
        exported = False
        for first_name, second_name in coordinate_pairs:
            first = _as_list(getattr(trace, first_name, None))
            second = _as_list(getattr(trace, second_name, None))
            if not first and not second:
                continue
            count = max(len(first), len(second))
            for point_index in range(count):
                rows.append(
                    {
                        "trace": trace_name,
                        "trace_type": trace_type,
                        "point": point_index,
                        first_name: first[point_index] if point_index < len(first) else None,
                        second_name: second[point_index] if point_index < len(second) else None,
                    }
                )
            exported = True
            break
        if exported:
            continue

        y_values = _as_list(getattr(trace, "y", None))
        if y_values:
            for point_index, value in enumerate(y_values):
                rows.append(
                    {
                        "trace": trace_name,
                        "trace_type": trace_type,
                        "point": point_index,
                        "y": value,
                    }
                )

    return pd.DataFrame(rows)


def figure_to_csv_bytes(fig: Any) -> bytes:
    """Return Plotly trace data as Excel-friendly UTF-8 CSV bytes."""
    table = figure_to_dataframe(fig)
    if table.empty:
        return b""
    return table.to_csv(index=False).encode("utf-8-sig")


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Return the currently filtered analysis dataframe as UTF-8 CSV bytes."""
    out = df.copy()
    if not isinstance(out.index, pd.RangeIndex):
        index_name = out.index.name or "timestamp"
        out = out.reset_index(names=index_name)
    return out.to_csv(index=False).encode("utf-8-sig")
