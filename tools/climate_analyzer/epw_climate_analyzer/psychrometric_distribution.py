"""Smooth duration-weighted psychrometric climate zones.

Climate zones are continuous two-dimensional density regions in the coordinates
that are actually displayed (T-d or i-d).  They are not rectangles made from
independent marginal percentiles and they are not mosaics of selected histogram
cells.  A duration-weighted 2-D histogram is smoothed with a deterministic
Gaussian kernel, then an iso-density threshold is chosen so the enclosed smooth
density represents at least the requested share of observed physical duration.

This module intentionally has no SciPy dependency.  The production scientific
stack already contains NumPy, which is sufficient for the modest regular grids
used by the interactive chart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import psychrolib

from .aggregations import native_interval_hours

psychrolib.SetUnitSystem(psychrolib.SI)
from .chart_theme import rgba


@dataclass(frozen=True)
class PsychrometricDensityField:
    """One smooth psychrometric density field and its cumulative-density zone."""

    x: np.ndarray
    y: np.ndarray
    mass_hours: np.ndarray
    threshold_hours: float
    target_share: float
    achieved_share: float
    total_hours: float
    chart_type: str

    @property
    def mask(self) -> np.ndarray:
        return self.mass_hours >= float(self.threshold_hours)

    @property
    def max_mass_hours(self) -> float:
        return float(np.nanmax(self.mass_hours)) if self.mass_hours.size else 0.0


def _psychrometric_columns(chart_type: str) -> tuple[str, str]:
    if chart_type == "i-d":
        return "humidity_ratio_g_kg", "moist_air_enthalpy_kj_kg"
    return "dry_bulb_temperature_c", "humidity_ratio_g_kg"


def psychrometric_coordinates(df: pd.DataFrame, chart_type: str = "T-d") -> pd.DataFrame:
    """Return finite chart coordinates while preserving the source index."""
    chart_type = "i-d" if chart_type == "i-d" else "T-d"
    x_col, y_col = _psychrometric_columns(chart_type)
    missing = [column for column in (x_col, y_col) if column not in df.columns]
    if missing:
        raise KeyError(f"Missing psychrometric coordinate columns: {', '.join(missing)}")
    frame = pd.DataFrame(
        {
            "x": pd.to_numeric(df[x_col], errors="coerce"),
            "y": pd.to_numeric(df[y_col], errors="coerce"),
        },
        index=df.index,
    ).replace([np.inf, -np.inf], np.nan).dropna()
    return frame


def _padded_range(values: np.ndarray, *, clamp_zero: bool = False) -> tuple[float, float]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return (0.0, 1.0)
    lo = float(np.min(finite))
    hi = float(np.max(finite))
    span = max(hi - lo, 1.0)
    pad = max(0.5, 0.055 * span)
    lower = lo - pad
    upper = hi + pad
    if clamp_zero:
        lower = max(0.0, lower)
    if upper <= lower:
        upper = lower + 1.0
    return lower, upper


def psychrometric_axis_ranges(
    frames: Iterable[pd.DataFrame],
    chart_type: str = "T-d",
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return one stable axis domain spanning every supplied climate frame."""
    chart_type = "i-d" if chart_type == "i-d" else "T-d"
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    for frame in frames:
        try:
            coords = psychrometric_coordinates(frame, chart_type)
        except (KeyError, ValueError):
            continue
        if coords.empty:
            continue
        xs.append(coords["x"].to_numpy(dtype=float))
        ys.append(coords["y"].to_numpy(dtype=float))
    if not xs:
        return (0.0, 1.0), (0.0, 1.0)
    x = np.concatenate(xs)
    y = np.concatenate(ys)
    x_range = _padded_range(x, clamp_zero=(chart_type == "i-d"))
    y_range = _padded_range(y, clamp_zero=(chart_type == "T-d"))
    return x_range, y_range


def _gaussian_kernel(sigma_cells: float) -> np.ndarray:
    sigma = float(np.clip(sigma_cells, 0.8, 8.0))
    radius = max(2, int(np.ceil(3.0 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= float(kernel.sum())
    return kernel


def _smooth_2d(values: np.ndarray, sigma_x: float, sigma_y: float) -> np.ndarray:
    """Separable Gaussian smoothing with zero padding and mass renormalization."""
    source = np.asarray(values, dtype=float)
    kx = _gaussian_kernel(sigma_x)
    ky = _gaussian_kernel(sigma_y)

    pad_x = len(kx) // 2
    padded_x = np.pad(source, ((pad_x, pad_x), (0, 0)), mode="constant")
    smooth_x = np.empty_like(source, dtype=float)
    for j in range(source.shape[1]):
        smooth_x[:, j] = np.convolve(padded_x[:, j], kx, mode="valid")

    pad_y = len(ky) // 2
    padded_y = np.pad(smooth_x, ((0, 0), (pad_y, pad_y)), mode="constant")
    smoothed = np.empty_like(source, dtype=float)
    for i in range(source.shape[0]):
        smoothed[i, :] = np.convolve(padded_y[i, :], ky, mode="valid")

    smoothed = np.clip(smoothed, 0.0, None)
    original_mass = float(source.sum())
    smooth_mass = float(smoothed.sum())
    if original_mass > 0.0 and smooth_mass > 0.0:
        smoothed *= original_mass / smooth_mass
    return smoothed


def _physical_psychrometric_mask(
    x: np.ndarray,
    y: np.ndarray,
    *,
    chart_type: str,
    pressure_pa: float,
) -> np.ndarray:
    """Return grid cells that represent physically possible 0...100% RH states.

    Gaussian smoothing is performed on a rectangular numerical domain. Without
    this mask, a small amount of smoothed density can leak above the saturation
    curve even though every source observation is physically valid.
    """
    xx, yy = np.meshgrid(np.asarray(x, dtype=float), np.asarray(y, dtype=float), indexing="ij")
    if chart_type == "i-d":
        d_g_kg = xx
        w = d_g_kg / 1000.0
        denominator = 1.006 + 1.86 * w
        t_c = (yy - 2501.0 * w) / np.maximum(denominator, 1e-12)
    else:
        t_c = xx
        d_g_kg = yy

    valid = np.isfinite(t_c) & np.isfinite(d_g_kg) & (d_g_kg >= 0.0)
    saturation = np.full(t_c.shape, np.nan, dtype=float)
    flat_t = t_c.ravel()
    flat_sat = saturation.ravel()
    flat_valid = valid.ravel()
    for idx in np.where(flat_valid)[0]:
        try:
            flat_sat[idx] = psychrolib.GetSatHumRatio(float(flat_t[idx]), float(pressure_pa)) * 1000.0
        except Exception:
            flat_valid[idx] = False
    saturation = flat_sat.reshape(t_c.shape)
    valid = flat_valid.reshape(t_c.shape) & np.isfinite(saturation)
    tolerance = np.maximum(1e-9, np.abs(saturation) * 1e-8)
    return valid & (d_g_kg <= saturation + tolerance)


def psychrometric_density_field(
    df: pd.DataFrame,
    *,
    chart_type: str = "T-d",
    target_share: float = 0.90,
    axis_ranges: tuple[tuple[float, float], tuple[float, float]] | None = None,
    grid_shape: tuple[int, int] = (140, 120),
    pressure_pa: float = 101325.0,
) -> PsychrometricDensityField:
    """Build a smooth duration-weighted field and cumulative-density climate zone.

    The contour threshold is found on the *smoothed joint distribution*: grid
    cells are sorted by density from high to low until the requested cumulative
    represented duration is reached.  Equal-valued cells at the threshold are
    retained together, so achieved coverage can be slightly above the target.
    """
    target = float(target_share)
    if not 0.0 < target <= 1.0:
        raise ValueError("target_share must be greater than 0 and at most 1.")
    nx, ny = (int(grid_shape[0]), int(grid_shape[1]))
    if nx < 24 or ny < 24:
        raise ValueError("Psychrometric density grid must be at least 24 × 24.")

    chart_type = "i-d" if chart_type == "i-d" else "T-d"
    coords = psychrometric_coordinates(df, chart_type)
    if coords.empty:
        x = np.linspace(0.0, 1.0, nx)
        y = np.linspace(0.0, 1.0, ny)
        return PsychrometricDensityField(x, y, np.zeros((nx, ny)), 0.0, target, 0.0, 0.0, chart_type)

    if axis_ranges is None:
        axis_ranges = psychrometric_axis_ranges([df], chart_type)
    (x_min, x_max), (y_min, y_max) = axis_ranges
    if not np.isfinite([x_min, x_max, y_min, y_max]).all() or x_max <= x_min or y_max <= y_min:
        raise ValueError("Psychrometric density axis ranges must be finite and increasing.")

    x_edges = np.linspace(float(x_min), float(x_max), nx + 1)
    y_edges = np.linspace(float(y_min), float(y_max), ny + 1)
    x_centers = (x_edges[:-1] + x_edges[1:]) * 0.5
    y_centers = (y_edges[:-1] + y_edges[1:]) * 0.5

    hours_per_record = float(native_interval_hours(df))
    weights = np.full(len(coords), hours_per_record, dtype=float)
    raw_mass, _, _ = np.histogram2d(
        coords["x"].to_numpy(dtype=float),
        coords["y"].to_numpy(dtype=float),
        bins=[x_edges, y_edges],
        weights=weights,
    )
    total_hours = float(raw_mass.sum())
    if total_hours <= 0.0:
        return PsychrometricDensityField(x_centers, y_centers, raw_mass, 0.0, target, 0.0, 0.0, chart_type)

    x_values = coords["x"].to_numpy(dtype=float)
    y_values = coords["y"].to_numpy(dtype=float)
    scott = max(len(coords), 2) ** (-1.0 / 6.0)
    dx = float(x_edges[1] - x_edges[0])
    dy = float(y_edges[1] - y_edges[0])
    std_x = max(float(np.nanstd(x_values, ddof=1)) if len(x_values) > 1 else dx, dx)
    std_y = max(float(np.nanstd(y_values, ddof=1)) if len(y_values) > 1 else dy, dy)
    sigma_x = np.clip((std_x * scott) / max(dx, 1e-12), 1.0, 7.0)
    sigma_y = np.clip((std_y * scott) / max(dy, 1e-12), 1.0, 7.0)
    smooth_mass = _smooth_2d(raw_mass, float(sigma_x), float(sigma_y))

    # Remove the purely numerical Gaussian tail outside the physical
    # psychrometric domain (RH > 100% or negative humidity ratio). The removed
    # mass is smoothing leakage, not observed duration, so renormalize the
    # remaining physical field back to the represented source duration.
    physical_mask = _physical_psychrometric_mask(
        x_centers,
        y_centers,
        chart_type=chart_type,
        pressure_pa=float(pressure_pa),
    )
    smooth_mass = np.where(physical_mask, smooth_mass, 0.0)
    physical_mass = float(smooth_mass.sum())
    if physical_mass > 0.0:
        smooth_mass *= total_hours / physical_mass

    flat = smooth_mass.ravel()
    positive = flat[flat > 0.0]
    if positive.size == 0:
        return PsychrometricDensityField(x_centers, y_centers, smooth_mass, 0.0, target, 0.0, total_hours, chart_type)
    ordered = np.sort(positive)[::-1]
    cumulative = np.cumsum(ordered)
    cutoff_index = int(np.searchsorted(cumulative, target * float(cumulative[-1]), side="left"))
    cutoff_index = min(cutoff_index, len(ordered) - 1)
    threshold = float(ordered[cutoff_index])
    tolerance = max(1e-14, abs(threshold) * 1e-12)
    selected = smooth_mass >= threshold - tolerance
    selected_hours = float(smooth_mass[selected].sum())
    achieved = selected_hours / float(smooth_mass.sum()) if float(smooth_mass.sum()) > 0.0 else 0.0
    return PsychrometricDensityField(
        x=x_centers,
        y=y_centers,
        mass_hours=smooth_mass,
        threshold_hours=threshold,
        target_share=target,
        achieved_share=achieved,
        total_hours=total_hours,
        chart_type=chart_type,
    )


def _nearest_density_mask(coords: pd.DataFrame, field: PsychrometricDensityField) -> np.ndarray:
    if coords.empty or field.mass_hours.size == 0:
        return np.zeros(len(coords), dtype=bool)
    ix = np.abs(field.x[:, None] - coords["x"].to_numpy(dtype=float)[None, :]).argmin(axis=0)
    iy = np.abs(field.y[:, None] - coords["y"].to_numpy(dtype=float)[None, :]).argmin(axis=0)
    return field.mass_hours[ix, iy] >= float(field.threshold_hours)


def add_climate_zone_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    *,
    chart_type: str,
    label: str,
    color: str,
    coverage: float = 0.90,
    interior_style: str = "Density gradient",
    axis_ranges: tuple[tuple[float, float], tuple[float, float]] | None = None,
    show_core: bool = False,
    core_coverage: float = 0.50,
    additional_coverages: list[float] | tuple[float, ...] | None = None,
    pressure_pa: float = 101325.0,
    legendgroup: str | None = None,
) -> PsychrometricDensityField:
    """Render one smooth climate zone on a shared psychrometric figure.

    ``Density gradient`` is the recommended presentation: frequency intensity is
    shown continuously inside the requested iso-density contour. ``Sparse
    points`` displays only real observations that fall inside the contour.
    ``Solid fill`` and ``Contour only`` are provided for cleaner report graphics.
    """
    allowed_styles = {"Density gradient", "Sparse points", "Solid fill", "Contour only"}
    if interior_style not in allowed_styles:
        raise ValueError(f"Unsupported climate-zone interior style: {interior_style}")

    field = psychrometric_density_field(
        df,
        chart_type=chart_type,
        target_share=coverage,
        axis_ranges=axis_ranges,
        pressure_pa=float(pressure_pa),
    )
    if field.total_hours <= 0.0 or field.threshold_hours <= 0.0:
        return field

    group = legendgroup or label
    physical_mask = _physical_psychrometric_mask(
        field.x, field.y, chart_type=chart_type, pressure_pa=float(pressure_pa)
    )
    mask = field.mask & physical_mask
    max_mass = max(field.max_mass_hours, float(field.threshold_hours))
    relative = (field.mass_hours - float(field.threshold_hours)) / max(max_mass - float(field.threshold_hours), 1e-12)
    relative = np.clip(relative, 0.0, 1.0)
    masked_relative = np.where(mask, relative, np.nan)

    if interior_style == "Density gradient":
        fig.add_trace(
            go.Contour(
                x=field.x,
                y=field.y,
                z=masked_relative.T,
                contours=dict(coloring="heatmap", showlines=False, start=0.0, end=1.0, size=0.08),
                colorscale=[
                    [0.0, rgba(color, 0.04)],
                    [0.30, rgba(color, 0.14)],
                    [0.65, rgba(color, 0.32)],
                    [1.0, rgba(color, 0.68)],
                ],
                showscale=False,
                hoverinfo="skip",
                connectgaps=False,
                name=f"{label} density",
                legendgroup=group,
                showlegend=False,
            )
        )
    elif interior_style == "Solid fill":
        solid = np.where(mask, 1.0, np.nan)
        fig.add_trace(
            go.Contour(
                x=field.x,
                y=field.y,
                z=solid.T,
                contours=dict(coloring="heatmap", showlines=False, start=1.0, end=1.0, size=1.0),
                colorscale=[[0.0, rgba(color, 0.15)], [1.0, rgba(color, 0.15)]],
                showscale=False,
                hoverinfo="skip",
                connectgaps=False,
                name=f"{label} fill",
                legendgroup=group,
                showlegend=False,
            )
        )
    elif interior_style == "Sparse points":
        coords = psychrometric_coordinates(df, chart_type)
        inside = _nearest_density_mask(coords, field)
        selected = coords.loc[inside]
        if len(selected) > 1600:
            step = int(np.ceil(len(selected) / 1600.0))
            selected = selected.iloc[::step]
        fig.add_trace(
            go.Scattergl(
                x=selected["x"],
                y=selected["y"],
                mode="markers",
                marker=dict(size=3.2, color=rgba(color, 0.36)),
                name=f"{label} observations",
                legendgroup=group,
                showlegend=False,
                hovertemplate=f"{label}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",
            )
        )

    contour_size = max(float(field.threshold_hours) * 0.02, 1e-12)
    fig.add_trace(
        go.Contour(
            x=field.x,
            y=field.y,
            z=np.where(physical_mask, field.mass_hours, np.nan).T,
            autocontour=False,
            contours=dict(
                start=float(field.threshold_hours),
                end=float(field.threshold_hours),
                size=contour_size,
                coloring="lines",
                showlabels=False,
            ),
            line=dict(color=rgba(color, 0.98), width=2.5),
            showscale=False,
            hoverinfo="skip",
            connectgaps=False,
            name=f"{label} {coverage * 100.0:.0f}% zone",
            legendgroup=group,
            showlegend=False,
        )
    )

    contour_levels: list[float] = []
    if additional_coverages is not None:
        contour_levels.extend(float(value) for value in additional_coverages)
    elif show_core:
        # Backward-compatible API only; current UI supplies explicit levels.
        contour_levels.append(float(core_coverage))
    contour_levels = sorted({value for value in contour_levels if 0.0 < value < float(coverage)})
    dash_cycle = ["dot", "dash", "dashdot", "longdash"]
    for level_index, contour_coverage in enumerate(contour_levels):
        inner = psychrometric_density_field(
            df,
            chart_type=chart_type,
            target_share=float(contour_coverage),
            axis_ranges=axis_ranges,
            pressure_pa=float(pressure_pa),
        )
        if inner.threshold_hours <= 0.0:
            continue
        inner_physical_mask = _physical_psychrometric_mask(
            inner.x, inner.y, chart_type=chart_type, pressure_pa=float(pressure_pa)
        )
        fig.add_trace(
            go.Contour(
                x=inner.x,
                y=inner.y,
                z=np.where(inner_physical_mask, inner.mass_hours, np.nan).T,
                autocontour=False,
                contours=dict(
                    start=float(inner.threshold_hours),
                    end=float(inner.threshold_hours),
                    size=max(float(inner.threshold_hours) * 0.02, 1e-12),
                    coloring="lines",
                    showlabels=False,
                ),
                line=dict(
                    color=rgba(color, 0.78),
                    width=1.35,
                    dash=dash_cycle[level_index % len(dash_cycle)],
                ),
                showscale=False,
                hoverinfo="skip",
                connectgaps=False,
                name=f"{label} {contour_coverage * 100.0:.0f}% contour",
                legendgroup=group,
                showlegend=False,
            )
        )

    # One explicit legend item keeps the comparison readable even though the
    # actual zone is composed of Contour traces.
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="lines",
            name=label,
            line=dict(color=color, width=3.0),
            legendgroup=group,
            hoverinfo="skip",
            showlegend=True,
        )
    )
    return field
