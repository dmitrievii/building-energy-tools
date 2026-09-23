"""Resolution-aware time-series aggregation and overlay charts.

Chronological rendering keeps the existing absolute-time implementation.
Interannual overlay is a distinct year-preserving presentation mode: every real
calendar year is aggregated independently first, then aligned on a common leap-
year calendar axis. No cross-year pooling is performed.
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
from .temporal_filtering import (
    INTERANNUAL_OVERLAY,
    interannual_calendar_bin,
    time_basis,
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
    color: str | None = None
    dash: str | None = None
    width: float = 2.0
    opacity: float = 1.0

    @property
    def unit_family(self) -> str:
        return unit_family_for(self.column, self.unit)


def native_resolution_minutes(index: pd.DatetimeIndex) -> int:
    """Compatibility wrapper around the canonical source-resolution inference."""
    return infer_native_resolution_minutes(index)


def available_resolution_labels(source: pd.DatetimeIndex | pd.DataFrame) -> list[str]:
    """Return resolutions at or coarser than the declared source cadence.

    Calendar-native monthly data are not a fixed 30-day cadence.  Their published
    monthly observations therefore expose Monthly/Seasonal/Annual directly while
    still blocking all artificial sub-monthly upsampling.
    """
    if isinstance(source, pd.DataFrame):
        index = pd.DatetimeIndex(source.index)
        native_calendar = str(source.attrs.get("canonical_native_resolution", "")).strip().lower()
        if native_calendar == "monthly":
            return ["Native", "Monthly", "Seasonal", "Annual"]
        declared = source.attrs.get("canonical_native_interval_minutes")
        try:
            native = int(declared) if declared is not None else native_resolution_minutes(index)
        except (TypeError, ValueError):
            native = native_resolution_minutes(index)
    else:
        index = pd.DatetimeIndex(source)
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


def _aggregate_values(values: pd.Series, semantics: str) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    if semantics == "sum":
        return float(numeric.sum(min_count=1))
    if semantics == "min":
        return float(numeric.min())
    if semantics == "max":
        return float(numeric.max())
    if semantics == "circular mean":
        return circular_mean_deg(numeric)
    return float(numeric.mean())


def _interval_end(start: pd.Timestamp, resolution: str, native_minutes: int, *, native_calendar: str | None = None) -> pd.Timestamp:
    if resolution == "Native":
        if str(native_calendar or "").lower() == "monthly":
            return start + pd.offsets.MonthBegin(1)
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
        return resampler.sum(min_count=1)
    if semantics == "min":
        return resampler.min()
    if semantics == "max":
        return resampler.max()
    if semantics == "circular mean":
        return resampler.apply(circular_mean_deg)
    return resampler.mean()


def _validate_resolution(df: pd.DataFrame, resolution: str) -> tuple[int, str]:
    if resolution not in RESOLUTION_BY_LABEL:
        raise ValueError(f"Unknown resolution: {resolution}")
    native_minutes = native_resolution_minutes(pd.DatetimeIndex(df.index))
    native_calendar = str(df.attrs.get("canonical_native_resolution", "")).strip().lower()
    if resolution != "Native":
        target = RESOLUTION_BY_LABEL[resolution].nominal_minutes
        calendar_month_identity = native_calendar == "monthly" and resolution == "Monthly"
        if target < native_minutes and not calendar_month_identity:
            raise ValueError(f"Cannot upsample {native_minutes}-minute source data to {resolution}.")
    return native_minutes, native_calendar


def aggregate_series(
    df: pd.DataFrame,
    column: str,
    resolution: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Aggregate a column on real chronological bins and clip bins to a viewport."""
    if column not in df.columns:
        raise KeyError(column)
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if end <= start:
        raise ValueError("End time must be later than start time.")

    native_minutes, native_calendar = _validate_resolution(df, resolution)
    series = pd.to_numeric(df[column], errors="coerce").copy()
    series.name = column
    values = _resample_values(series, resolution)
    frame = values.rename("value").to_frame()
    frame["interval_start"] = pd.DatetimeIndex(frame.index)
    frame["interval_end"] = [
        _interval_end(pd.Timestamp(ts), resolution, native_minutes, native_calendar=native_calendar)
        for ts in frame["interval_start"]
    ]
    overlap = (frame["interval_end"] > start) & (frame["interval_start"] < end)
    frame = frame.loc[overlap].copy()
    frame["plot_start"] = frame["interval_start"].where(frame["interval_start"] >= start, start)
    frame["plot_end"] = frame["interval_end"].where(frame["interval_end"] <= end, end)
    frame["resolution"] = resolution
    frame["aggregation"] = aggregation_semantics(column)
    return frame


def _weekly_interannual_values(series: pd.Series) -> pd.DataFrame:
    """Aggregate one real year into fixed Jan-1-anchored calendar weeks."""
    semantics = aggregation_semantics(str(series.name))
    bins = interannual_calendar_bin(pd.DatetimeIndex(series.index), "Weekly")
    work = pd.DataFrame({"value": pd.to_numeric(series, errors="coerce").to_numpy()}, index=series.index)
    work["calendar_bin"] = list(bins)
    rows: list[dict[str, object]] = []
    for calendar_bin, group in work.groupby("calendar_bin", sort=True):
        rows.append(
            {
                "calendar_bin": pd.Timestamp(calendar_bin),
                "source_timestamp": pd.Timestamp(group.index.min()),
                "value": _aggregate_values(group["value"], semantics),
            }
        )
    return pd.DataFrame(rows)


def _calendar_label(calendar_bin: pd.Timestamp, resolution: str) -> str:
    stamp = pd.Timestamp(calendar_bin)
    if resolution == "Monthly":
        return stamp.strftime("%b")
    if resolution == "Weekly":
        week = ((stamp.normalize() - pd.Timestamp(2000, 1, 1)).days // 7) + 1
        return f"W{int(week):02d} · {stamp.strftime('%d %b')}"
    if resolution == "Daily":
        return stamp.strftime("%d %b")
    return stamp.strftime("%d %b %H:%M")


def _gap_before_flags(frame: pd.DataFrame, resolution: str, native_minutes: int, native_calendar: str) -> list[bool]:
    if frame.empty:
        return []
    bins = pd.DatetimeIndex(frame["calendar_bin"])
    flags = [False]
    for previous, current in zip(bins[:-1], bins[1:], strict=False):
        if resolution == "Monthly" or (resolution == "Native" and native_calendar == "monthly"):
            delta = (current.year - previous.year) * 12 + current.month - previous.month
            flags.append(delta > 1)
            continue
        if resolution == "Weekly":
            flags.append((current - previous) > pd.Timedelta(days=7, seconds=1))
            continue
        if resolution == "Daily":
            expected = pd.Timedelta(days=1)
        elif resolution == "Native":
            expected = pd.Timedelta(minutes=max(1, native_minutes))
        else:
            expected = pd.Timedelta(minutes=RESOLUTION_BY_LABEL[resolution].nominal_minutes)
        flags.append((current - previous) > expected * 1.01)
    return flags


def aggregate_interannual_series(
    df: pd.DataFrame,
    column: str,
    resolution: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Return an explicit year-preserving intermediate representation.

    Output rows contain ``real_year``, a year-neutral ``calendar_bin`` used only
    for presentation, the real ``source_timestamp`` for provenance/hover, and the
    aggregated ``value``. Aggregation is executed separately for each real year;
    there is no code path that pools years before this table exists.
    """
    if column not in df.columns:
        raise KeyError(column)
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if end <= start:
        raise ValueError("End time must be later than start time.")
    native_minutes, native_calendar = _validate_resolution(df, resolution)

    numeric = pd.to_numeric(df[column], errors="coerce").copy()
    numeric.name = column
    index = pd.DatetimeIndex(df.index)
    frames: list[pd.DataFrame] = []

    for year in sorted({int(value) for value in index.year}):
        mask = index.year == year
        year_series = numeric.loc[mask]
        if year_series.empty:
            continue

        if resolution == "Weekly":
            year_frame = _weekly_interannual_values(year_series)
            if year_frame.empty:
                continue
            year_frame["interval_start"] = year_frame["source_timestamp"]
            year_frame["interval_end"] = year_frame["interval_start"] + pd.Timedelta(days=7)
        else:
            values = _resample_values(year_series, resolution)
            year_frame = values.rename("value").to_frame().reset_index()
            timestamp_column = year_frame.columns[0]
            year_frame = year_frame.rename(columns={timestamp_column: "source_timestamp"})
            year_frame["source_timestamp"] = pd.to_datetime(year_frame["source_timestamp"])
            year_frame["interval_start"] = year_frame["source_timestamp"]
            year_frame["interval_end"] = [
                _interval_end(pd.Timestamp(ts), resolution, native_minutes, native_calendar=native_calendar)
                for ts in year_frame["source_timestamp"]
            ]
            year_frame["calendar_bin"] = list(
                interannual_calendar_bin(pd.DatetimeIndex(year_frame["source_timestamp"]), resolution)
            )

        overlap = (year_frame["interval_end"] > start) & (year_frame["interval_start"] < end)
        year_frame = year_frame.loc[overlap].copy()
        if year_frame.empty:
            continue
        year_frame["real_year"] = int(year)
        year_frame["calendar_bin"] = pd.to_datetime(year_frame["calendar_bin"])
        year_frame = year_frame.sort_values("calendar_bin").reset_index(drop=True)
        year_frame["calendar_label"] = [
            _calendar_label(pd.Timestamp(value), resolution) for value in year_frame["calendar_bin"]
        ]
        year_frame["gap_before"] = _gap_before_flags(year_frame, resolution, native_minutes, native_calendar)
        year_frame["resolution"] = resolution
        year_frame["aggregation"] = aggregation_semantics(column)
        frames.append(year_frame)

    columns = [
        "real_year", "calendar_bin", "calendar_label", "source_timestamp",
        "interval_start", "interval_end", "value", "gap_before", "resolution", "aggregation",
    ]
    if not frames:
        return pd.DataFrame(columns=columns)
    out = pd.concat(frames, ignore_index=True)
    return out[columns]


def _segment_coordinates(frame: pd.DataFrame) -> tuple[list[object], list[object]]:
    x: list[object] = []
    y: list[object] = []
    for row in frame.itertuples():
        if pd.isna(row.value):
            continue
        x.extend([row.plot_start, row.plot_end, None])
        y.extend([row.value, row.value, None])
    return x, y


def _interannual_trace_coordinates(frame: pd.DataFrame) -> tuple[list[object], list[object], list[list[object]]]:
    """Build coordinates with explicit breaks for missing calendar bins."""
    x: list[object] = []
    y: list[object] = []
    custom: list[list[object]] = []
    for row in frame.itertuples(index=False):
        if bool(row.gap_before) and x:
            x.append(None)
            y.append(None)
            custom.append([None, None, None, None])
        source = pd.Timestamp(row.source_timestamp)
        label = str(row.calendar_label)
        value = float(row.value) if pd.notna(row.value) else None
        x.append(pd.Timestamp(row.calendar_bin))
        y.append(value)
        custom.append([int(row.real_year), source.isoformat(), label, str(row.resolution)])
    return x, y, custom


def validate_unit_families(series: Iterable[OverlaySeries]) -> list[str]:
    families: list[str] = []
    for item in series:
        if item.unit_family not in families:
            families.append(item.unit_family)
    if len(families) > 2:
        raise ValueError("An overlay may contain at most two distinct unit families.")
    return families


def _validate_style(spec: OverlaySeries) -> tuple[str, float, float]:
    dash = spec.dash or "solid"
    if dash not in {"solid", "dash", "dot", "dashdot", "longdash", "longdashdot"}:
        raise ValueError(f"Unsupported line dash style: {dash}")
    width = float(spec.width)
    opacity = float(spec.opacity)
    if not np.isfinite(width) or width <= 0.0:
        raise ValueError("Overlay line width must be a finite positive number.")
    if not np.isfinite(opacity) or not 0.0 < opacity <= 1.0:
        raise ValueError("Overlay opacity must be greater than 0 and at most 1.")
    return dash, width, opacity


def _build_interannual_overlay_figure(
    df: pd.DataFrame,
    series: list[OverlaySeries],
    start: pd.Timestamp,
    end: pd.Timestamp,
    title: str,
    families: list[str],
) -> tuple[go.Figure, list[pd.DataFrame]]:
    fig = go.Figure()
    tables: list[pd.DataFrame] = []
    year_dash_cycle = ["solid", "dash", "dot", "dashdot", "longdash", "longdashdot"]
    all_years = sorted({int(year) for year in pd.DatetimeIndex(df.index).year})
    year_dash = {year: year_dash_cycle[index % len(year_dash_cycle)] for index, year in enumerate(all_years)}

    for spec in series:
        table = aggregate_interannual_series(df, spec.column, spec.resolution, start, end)
        table.insert(0, "series", spec.label)
        table.insert(1, "variable", spec.column)
        table.insert(2, "unit", spec.unit)
        tables.append(table)
        axis = "y" if spec.unit_family == families[0] else "y2"
        base_dash, width, opacity = _validate_style(spec)
        represented_years = sorted({int(value) for value in table["real_year"].dropna().tolist()})
        for year in represented_years:
            year_frame = table.loc[table["real_year"] == year].sort_values("calendar_bin").copy()
            x, y, custom = _interannual_trace_coordinates(year_frame)
            if not x:
                continue
            dash = base_dash if len(represented_years) == 1 else year_dash.get(year, base_dash)
            name = f"{spec.label} — {year}"
            mode = "lines+markers" if spec.resolution == "Monthly" else "lines"
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y,
                    customdata=custom,
                    mode=mode,
                    name=name,
                    legendgroup=str(year),
                    yaxis=axis,
                    line={"color": spec.color or metric_color(spec.column), "dash": dash, "width": width},
                    marker={"size": 5} if mode == "lines+markers" else None,
                    opacity=opacity,
                    connectgaps=False,
                    hovertemplate=(
                        f"{spec.label}<br>"
                        "Year: %{customdata[0]}<br>"
                        "Date: %{customdata[2]}<br>"
                        "Source: %{customdata[1]}<br>"
                        f"Value: %{{y:.3g}} {spec.unit}<br>"
                        "Aggregation: %{customdata[3]}<extra></extra>"
                    ),
                )
            )

    left_units = sorted({item.unit for item in series if item.unit_family == families[0]})
    resolutions = {item.resolution for item in series}
    if resolutions == {"Monthly"}:
        tickformat = "%b"
        dtick: object = "M1"
    else:
        tickformat = "%d %b"
        dtick = None
    xaxis: dict[str, object] = {
        "title": "Calendar position",
        "type": "date",
        "tickformat": tickformat,
        "range": [pd.Timestamp(2000, 1, 1), pd.Timestamp(2000, 12, 31, 23, 59, 59)],
    }
    if dtick is not None:
        xaxis["dtick"] = dtick
    fig.update_layout(
        template="plotly_white",
        title=title,
        hovermode="closest",
        xaxis=xaxis,
        yaxis={"title": " / ".join(left_units)},
        legend={
            "orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0.0,
            "groupclick": "togglegroup",
        },
        margin={"r": 70 if len(families) == 2 else 30},
    )
    if len(families) == 2:
        right_units = sorted({item.unit for item in series if item.unit_family == families[1]})
        fig.update_layout(
            yaxis2={"title": " / ".join(right_units), "overlaying": "y", "side": "right", "showgrid": False}
        )
    return fig, tables


def build_overlay_figure(
    df: pd.DataFrame,
    series: list[OverlaySeries],
    start: pd.Timestamp,
    end: pd.Timestamp,
    title: str = "Time series overlay",
) -> tuple[go.Figure, list[pd.DataFrame]]:
    """Build a shared-axis overlay under the dataframe's explicit time basis."""
    if not series:
        raise ValueError("At least one series is required.")
    families = validate_unit_families(series)
    if time_basis(df) == INTERANNUAL_OVERLAY:
        return _build_interannual_overlay_figure(df, series, start, end, title, families)

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
        dash = spec.dash or dash_cycle[index % len(dash_cycle)]
        _dash, width, opacity = _validate_style(spec)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                name=name,
                yaxis=axis,
                line={"color": spec.color or metric_color(spec.column), "dash": dash, "width": width},
                opacity=opacity,
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
            yaxis2={"title": " / ".join(right_units), "overlaying": "y", "side": "right", "showgrid": False}
        )
    return fig, tables


def combined_series_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """Return one tidy export table for the configured overlay series."""
    if not tables:
        return pd.DataFrame()
    return pd.concat(tables, ignore_index=True)
