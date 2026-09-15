"""Resolution-aware time-series aggregation and overlay charts.

The module deliberately separates *display range* from *aggregation range*.
Aggregated values are calculated from complete calendar bins first and only then
clipped to the requested viewport.  A monthly mean shown over a three-day
viewport therefore remains the mean of the complete month rather than silently
becoming a three-day mean.

No temporal upsampling is performed.  Resolutions finer than the native source
timestep are unavailable by contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .chart_theme import metric_color
from .climate_model import (
    aggregation_semantics_for,
    infer_native_resolution_minutes,
    unit_family_for,
)


@dataclass(frozen=True)
class ResolutionSpec:
    label: str
    rule: str | None
    nominal_minutes: int


RESOLUTIONS: tuple[ResolutionSpec, ...] = (
    ResolutionSpec("Native", None, 0),
    ResolutionSpec("10 min", "10min", 10),
    ResolutionSpec("30 min", "30min", 30),
    ResolutionSpec("1 h", "1h", 60),
    ResolutionSpec("3 h", "3h", 180),
    ResolutionSpec("6 h", "6h", 360),
    ResolutionSpec("Daily", "D", 1440),
    ResolutionSpec("Weekly", "W-MON", 10080),
    ResolutionSpec("Monthly", "MS", 43200),
    ResolutionSpec("Seasonal", "QS-DEC", 129600),
    ResolutionSpec("Annual", "YS", 525600),
)
RESOLUTION_BY_LABEL = {item.label: item for item in RESOLUTIONS}


@dataclass(frozen=True)
class OverlaySeries:
    label: str
    column: str
    unit: str
    resolution: str

    @property
    def unit_family(self) -> str:
        return unit_family_for(self.column, self.unit)



def native_resolution_minutes(index: pd.DatetimeIndex) -> int:
    """Compatibility wrapper around the canonical source-resolution inference."""
    return infer_native_resolution_minutes(index)



def available_resolution_labels(index: pd.DatetimeIndex) -> list[str]:
    """Return only resolutions at or coarser than the native source timestep."""
    native = native_resolution_minutes(index)
    labels = ["Native"]
    labels.extend(spec.label for spec in RESOLUTIONS[1:] if spec.nominal_minutes >= native)
    return labels



def aggregation_semantics(column: str) -> str:
    """Compatibility wrapper around canonical quantity aggregation semantics."""
    return aggregation_semantics_for(column)



def circular_mean_deg(values: pd.Series) -> float:
    """Return a NaN-safe circular mean in degrees on [0, 360)."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return float("nan")
    radians = np.deg2rad(clean.to_numpy(dtype=float) % 360.0)
    sin_mean = float(np.sin(radians).mean())
    cos_mean = float(np.cos(radians).mean())
    if np.isclose(sin_mean, 0.0) and np.isclose(cos_mean, 0.0):
        return float("nan")
    return float(np.rad2deg(np.arctan2(sin_mean, cos_mean)) % 360.0)



def _interval_end(start: pd.Timestamp, resolution: str, native_minutes: int) -> pd.Timestamp:
    if resolution == "Native":
        return start + pd.Timedelta(minutes=native_minutes)
    if resolution == "10 min":
        return start + pd.Timedelta(minutes=10)
    if resolution == "30 min":
        return start + pd.Timedelta(minutes=30)
    if resolution == "1 h":
        return start + pd.Timedelta(hours=1)
    if resolution == "3 h":
        return start + pd.Timedelta(hours=3)
    if resolution == "6 h":
        return start + pd.Timedelta(hours=6)
    if resolution == "Daily":
        return start + pd.Timedelta(days=1)
    if resolution == "Weekly":
        return start + pd.Timedelta(days=7)
    if resolution == "Monthly":
        return start + pd.offsets.MonthBegin(1)
    if resolution == "Seasonal":
        return start + pd.DateOffset(months=3)
    if resolution == "Annual":
        return start + pd.offsets.YearBegin(1)
    raise ValueError(f"Unsupported resolution: {resolution}")



def _resample_values(series: pd.Series, resolution: str) -> pd.Series:
    spec = RESOLUTION_BY_LABEL[resolution]
    if spec.rule is None:
        return series

    kwargs: dict[str, object] = {"label": "left", "closed": "left"}
    if resolution in {"10 min", "30 min", "1 h", "3 h", "6 h", "Daily"}:
        kwargs["origin"] = "start_day"
    resampler = series.resample(spec.rule, **kwargs)
    semantics = aggregation_semantics(str(series.name))
    if semantics == "sum":
        # min_count=1 prevents an all-missing interval from becoming a false zero.
        return resampler.sum(min_count=1)
    if semantics == "circular mean":
        return resampler.apply(circular_mean_deg)
    return resampler.mean()



def aggregate_series(
    df: pd.DataFrame,
    column: str,
    resolution: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Aggregate a column on calendar-aligned bins and clip bins to a viewport.

    ``start`` and ``end`` define the visible range.  Aggregation is intentionally
    executed on the complete input dataframe before overlap clipping, preserving
    the meaning of complete daily/monthly/seasonal means and totals.
    """
    if resolution not in RESOLUTION_BY_LABEL:
        raise ValueError(f"Unknown resolution: {resolution}")
    if column not in df.columns:
        raise KeyError(column)
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if end <= start:
        raise ValueError("End time must be later than start time.")

    native_minutes = native_resolution_minutes(pd.DatetimeIndex(df.index))
    if resolution != "Native":
        target = RESOLUTION_BY_LABEL[resolution].nominal_minutes
        if target < native_minutes:
            raise ValueError(
                f"Cannot upsample {native_minutes}-minute source data to {resolution}."
            )

    series = pd.to_numeric(df[column], errors="coerce").copy()
    series.name = column
    values = _resample_values(series, resolution)
    frame = values.rename("value").to_frame()
    frame["interval_start"] = pd.DatetimeIndex(frame.index)
    frame["interval_end"] = [
        _interval_end(pd.Timestamp(ts), resolution, native_minutes)
        for ts in frame["interval_start"]
    ]
    overlap = (frame["interval_end"] > start) & (frame["interval_start"] < end)
    frame = frame.loc[overlap].copy()
    frame["plot_start"] = frame["interval_start"].where(frame["interval_start"] >= start, start)
    frame["plot_end"] = frame["interval_end"].where(frame["interval_end"] <= end, end)
    frame["resolution"] = resolution
    frame["aggregation"] = aggregation_semantics(column)
    return frame



def _segment_coordinates(frame: pd.DataFrame) -> tuple[list[object], list[object]]:
    x: list[object] = []
    y: list[object] = []
    for row in frame.itertuples():
        if pd.isna(row.value):
            continue
        x.extend([row.plot_start, row.plot_end, None])
        y.extend([row.value, row.value, None])
    return x, y



def validate_unit_families(series: Iterable[OverlaySeries]) -> list[str]:
    families: list[str] = []
    for item in series:
        if item.unit_family not in families:
            families.append(item.unit_family)
    if len(families) > 2:
        raise ValueError("An overlay may contain at most two distinct unit families.")
    return families



def build_overlay_figure(
    df: pd.DataFrame,
    series: list[OverlaySeries],
    start: pd.Timestamp,
    end: pd.Timestamp,
    title: str = "Time series overlay",
) -> tuple[go.Figure, list[pd.DataFrame]]:
    """Build one shared-X-axis overlay with at most two physical Y-axis families."""
    if not series:
        raise ValueError("At least one series is required.")
    families = validate_unit_families(series)
    fig = go.Figure()
    tables: list[pd.DataFrame] = []
    dash_cycle = ["solid", "dash", "dot", "dashdot", "longdash", "longdashdot"]

    for index, spec in enumerate(series):
        table = aggregate_series(df, spec.column, spec.resolution, start, end)
        table.insert(0, "series", spec.label)
        table.insert(1, "variable", spec.column)
        table.insert(2, "unit", spec.unit)
        tables.append(table)
        axis = "y" if spec.unit_family == families[0] else "y2"
        name = f"{spec.label} · {spec.resolution}"
        if spec.resolution == "Native":
            visible = table.dropna(subset=["value"])
            x = visible["interval_start"].tolist()
            y = visible["value"].tolist()
        else:
            x, y = _segment_coordinates(table)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                name=name,
                yaxis=axis,
                line={"color": metric_color(spec.column), "dash": dash_cycle[index % len(dash_cycle)]},
                connectgaps=False,
                hovertemplate=f"{name}<br>%{{x|%Y-%m-%d %H:%M}}<br>%{{y:.3g}} {spec.unit}<extra></extra>",
            )
        )

    left_units = sorted({item.unit for item in series if item.unit_family == families[0]})
    fig.update_layout(
        template="plotly_white",
        title=title,
        hovermode="x unified",
        xaxis={"title": "Time", "type": "date", "range": [pd.Timestamp(start), pd.Timestamp(end)]},
        yaxis={"title": " / ".join(left_units)},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0.0},
        margin={"r": 70 if len(families) == 2 else 30},
    )
    if len(families) == 2:
        right_units = sorted({item.unit for item in series if item.unit_family == families[1]})
        fig.update_layout(
            yaxis2={
                "title": " / ".join(right_units),
                "overlaying": "y",
                "side": "right",
                "showgrid": False,
            }
        )
    return fig, tables



def combined_series_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """Return one tidy export table for the configured overlay series."""
    if not tables:
        return pd.DataFrame()
    return pd.concat(tables, ignore_index=True)
