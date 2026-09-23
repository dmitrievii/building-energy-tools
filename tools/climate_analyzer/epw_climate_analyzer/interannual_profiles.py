"""Year-preserving profile/envelope charts for the interannual time basis.

The helpers in this module deliberately consume the explicit intermediate table
from :mod:`timeseries`.  Every real year is aggregated first and remains
inspectable as its own Plotly trace.  Cross-year min/max or percentile envelopes
are presentation statistics calculated only after those yearly values exist.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .chart_theme import metric_band_colors, semantic_color_from_text
from .timeseries import aggregate_interannual_series


_AGGREGATION_TO_RESOLUTION = {
    "Hourly": "1 h",
    "Daily": "Daily",
    "Weekly": "Weekly",
    "Monthly": "Monthly",
    "Seasonal": "Seasonal",
    "Annual": "Annual",
}


def _resolution(aggregation: str) -> str:
    try:
        return _AGGREGATION_TO_RESOLUTION[str(aggregation)]
    except KeyError as exc:
        raise ValueError(f"Interannual profile does not support aggregation: {aggregation}") from exc


def _analysis_bounds(df: pd.DataFrame, resolution: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    index = pd.DatetimeIndex(df.index)
    if index.empty:
        raise ValueError("Interannual profile requires at least one timestamp.")
    start = pd.Timestamp(index.min())
    last = pd.Timestamp(index.max())
    if resolution == "1 h":
        end = last + pd.Timedelta(hours=1)
    elif resolution == "Daily":
        end = last + pd.Timedelta(days=1)
    elif resolution == "Weekly":
        end = last + pd.Timedelta(days=7)
    elif resolution == "Monthly":
        end = last + pd.offsets.MonthBegin(1)
    elif resolution == "Seasonal":
        end = last + pd.DateOffset(months=3)
    elif resolution == "Annual":
        end = last + pd.offsets.YearBegin(1)
    else:
        raise ValueError(f"Unsupported interannual profile resolution: {resolution}")
    return start, end


def interannual_profile_table(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    """Return the auditable ``real_year × calendar_bin`` table for a profile."""
    resolution = _resolution(aggregation)
    start, end = _analysis_bounds(df, resolution)
    return aggregate_interannual_series(df, column, resolution, start, end)


def _year_trace_coordinates(frame: pd.DataFrame) -> tuple[list[object], list[object], list[list[object]]]:
    x: list[object] = []
    y: list[object] = []
    custom: list[list[object]] = []
    for row in frame.sort_values("calendar_bin").itertuples(index=False):
        if bool(row.gap_before) and x:
            x.append(None)
            y.append(None)
            custom.append([None, None])
        x.append(pd.Timestamp(row.calendar_bin))
        y.append(None if pd.isna(row.value) else float(row.value))
        custom.append([int(row.real_year), pd.Timestamp(row.source_timestamp).isoformat()])
    return x, y, custom


def _yearly_traces(fig: go.Figure, table: pd.DataFrame, unit: str) -> None:
    for year, group in table.groupby("real_year", sort=True):
        x, y, custom = _year_trace_coordinates(group)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                customdata=custom,
                mode="lines+markers",
                name=str(int(year)),
                legendgroup=str(int(year)),
                connectgaps=False,
                line=dict(color=semantic_color_from_text(str(int(year))), width=1.15),
                marker=dict(size=3),
                opacity=0.68,
                hovertemplate=(
                    "Year: %{customdata[0]}<br>"
                    "Source bin: %{customdata[1]}<br>"
                    "Value: %{y:.2f} " + unit + "<extra></extra>"
                ),
            )
        )


def _envelope_table(table: pd.DataFrame, kind: str) -> pd.DataFrame:
    clean = table[["calendar_bin", "value"]].copy()
    clean["value"] = pd.to_numeric(clean["value"], errors="coerce")
    grouped = clean.groupby("calendar_bin", sort=True)["value"]
    if kind == "minmax":
        out = grouped.agg(low="min", centre="mean", high="max")
    elif kind == "percentile":
        out = pd.DataFrame(
            {
                "low": grouped.quantile(0.05),
                "centre": grouped.median(),
                "high": grouped.quantile(0.95),
            }
        )
    else:
        raise ValueError(f"Unknown interannual envelope kind: {kind}")
    return out.dropna(how="all")


def interannual_profile_figure(
    df: pd.DataFrame,
    column: str,
    aggregation: str,
    title: str,
    unit: str,
    *,
    kind: str,
) -> go.Figure:
    """Render yearly series plus a cross-year envelope on one calendar axis."""
    table = interannual_profile_table(df, column, aggregation)
    fig = go.Figure()
    if table.empty:
        fig.update_layout(title=title, template="plotly_white")
        return fig

    _yearly_traces(fig, table, unit)
    envelope = _envelope_table(table, kind)
    low_color, centre_color, high_color, band_fill = metric_band_colors(column)
    if not envelope.empty:
        fig.add_trace(
            go.Scatter(
                x=envelope.index,
                y=envelope["high"],
                mode="lines",
                name="Interannual maximum" if kind == "minmax" else "Interannual P95",
                legendgroup="interannual-envelope",
                line=dict(color=high_color, width=1.25),
                hovertemplate=("Maximum" if kind == "minmax" else "P95") + ": %{y:.2f} " + unit + "<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=envelope.index,
                y=envelope["low"],
                mode="lines",
                name="Interannual minimum" if kind == "minmax" else "Interannual P05",
                legendgroup="interannual-envelope",
                line=dict(color=low_color, width=1.25),
                fill="tonexty",
                fillcolor=band_fill,
                hovertemplate=("Minimum" if kind == "minmax" else "P05") + ": %{y:.2f} " + unit + "<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=envelope.index,
                y=envelope["centre"],
                mode="lines",
                name="Interannual mean" if kind == "minmax" else "Interannual median",
                legendgroup="interannual-envelope",
                line=dict(color=centre_color, width=2.0),
                hovertemplate=("Mean" if kind == "minmax" else "Median") + ": %{y:.2f} " + unit + "<extra></extra>",
            )
        )

    fig.update_layout(
        title=title,
        xaxis_title="Calendar position",
        yaxis_title=unit,
        template="plotly_white",
        hovermode="x unified",
        legend_title_text="Real year / envelope",
        margin=dict(l=40, r=20, t=70, b=45),
    )
    fig.update_xaxes(tickformat="%d %b" if aggregation != "Monthly" else "%b")
    return fig


def interannual_minmax_figure(
    df: pd.DataFrame,
    column: str,
    aggregation: str,
    title: str,
    unit: str,
) -> go.Figure:
    return interannual_profile_figure(df, column, aggregation, title, unit, kind="minmax")


def interannual_percentile_figure(
    df: pd.DataFrame,
    column: str,
    aggregation: str,
    title: str,
    unit: str,
) -> go.Figure:
    return interannual_profile_figure(df, column, aggregation, title, unit, kind="percentile")
