"""Calculated and measured ground-temperature analysis helpers.

The calculated profile implements the one-dimensional periodic semi-infinite
solid solution used by the user-provided ``Klimate.xlsx`` reference workbook.
The annual outdoor-air harmonic is fitted from hourly dry-bulb temperature, then
monthly mean ground temperature is integrated analytically over each month.

GeoSphere shallow-soil measurements remain observations.  Calculated deep
profiles are always labelled as calculated and are never presented as measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import calendar
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from PIL import Image, ImageDraw, ImageFont

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MEASURED_GROUND_DEPTHS_M = {
    "ground_temperature_0_10m_c": 0.10,
    "ground_temperature_0_20m_c": 0.20,
    "ground_temperature_0_50m_c": 0.50,
}


@dataclass(frozen=True)
class AnnualHarmonic:
    mean_c: float
    sin_c: float
    cos_c: float
    amplitude_c: float
    period_days: float = 365.0


def fit_annual_harmonic(temperature: pd.Series, period_days: float = 365.0) -> AnnualHarmonic:
    """Fit mean + first annual sine/cosine harmonic to a timestamped series."""
    if not isinstance(temperature.index, pd.DatetimeIndex):
        raise TypeError("Ground-temperature harmonic fit requires a DatetimeIndex.")
    values = pd.to_numeric(temperature, errors="coerce")
    valid = values.notna()
    if int(valid.sum()) < 24:
        raise ValueError("At least 24 valid outdoor-temperature records are required.")
    idx = pd.DatetimeIndex(values.index[valid])
    represented_day_of_year = set(int(day) for day in idx.dayofyear)
    if len(represented_day_of_year) < 300:
        raise ValueError(
            "Calculated annual ground profile requires at least 300 represented calendar days; "
            "use a near-full-year Data filter or measured ground temperatures instead."
        )
    y = values.loc[valid].to_numpy(dtype=float)
    # Use annual phase within each represented calendar year so multi-year
    # historical data contribute to one climatological annual harmonic.
    year_days = np.where(idx.is_leap_year, 366.0, 365.0)
    day_fraction = (
        idx.dayofyear.to_numpy(dtype=float) - 1.0
        + idx.hour.to_numpy(dtype=float) / 24.0
        + idx.minute.to_numpy(dtype=float) / 1440.0
        + idx.second.to_numpy(dtype=float) / 86400.0
    )
    phase = 2.0 * np.pi * day_fraction / year_days
    design = np.column_stack([np.ones(len(y)), np.sin(phase), np.cos(phase)])
    mean_c, sin_c, cos_c = np.linalg.lstsq(design, y, rcond=None)[0]
    return AnnualHarmonic(
        mean_c=float(mean_c),
        sin_c=float(sin_c),
        cos_c=float(cos_c),
        amplitude_c=float(math.hypot(sin_c, cos_c)),
        period_days=float(period_days),
    )


def soil_diffusivity_m2_day(conductivity_w_mk: float, density_kg_m3: float, heat_capacity_j_kgk: float) -> float:
    values = (float(conductivity_w_mk), float(density_kg_m3), float(heat_capacity_j_kgk))
    if any(value <= 0.0 or not math.isfinite(value) for value in values):
        raise ValueError("Soil conductivity, density and heat capacity must be finite positive values.")
    return values[0] / (values[1] * values[2]) * 86400.0


def damping_depth_m(
    conductivity_w_mk: float,
    density_kg_m3: float,
    heat_capacity_j_kgk: float,
    period_days: float = 365.0,
) -> float:
    alpha = soil_diffusivity_m2_day(conductivity_w_mk, density_kg_m3, heat_capacity_j_kgk)
    omega = 2.0 * math.pi / float(period_days)
    return math.sqrt(2.0 * alpha / omega)


def _month_bounds_days(year: int = 2025) -> list[tuple[float, float]]:
    starts: list[float] = []
    cursor = 0.0
    for month in range(1, 13):
        starts.append(cursor)
        cursor += float(calendar.monthrange(year, month)[1])
    return [(starts[m - 1], starts[m] if m < 12 else 365.0) for m in range(1, 13)]


def monthly_ground_profile(
    harmonic: AnnualHarmonic,
    depths_m: np.ndarray,
    conductivity_w_mk: float = 2.0,
    density_kg_m3: float = 2000.0,
    heat_capacity_j_kgk: float = 1000.0,
) -> pd.DataFrame:
    """Return analytically integrated monthly mean temperature versus depth."""
    z = np.asarray(depths_m, dtype=float)
    if z.ndim != 1 or len(z) == 0 or np.any(z < 0.0):
        raise ValueError("Depths must be a non-empty one-dimensional array with z >= 0.")
    omega = 2.0 * math.pi / harmonic.period_days
    delta = damping_depth_m(conductivity_w_mk, density_kg_m3, heat_capacity_j_kgk, harmonic.period_days)
    phase_depth = z / delta
    attenuation = np.exp(-phase_depth)
    columns: dict[str, np.ndarray] = {}
    for month_index, (t1, t2) in enumerate(_month_bounds_days(), start=1):
        duration = t2 - t1
        sine_mean = (
            np.cos(omega * t1 - phase_depth) - np.cos(omega * t2 - phase_depth)
        ) / (omega * duration)
        cosine_mean = (
            np.sin(omega * t2 - phase_depth) - np.sin(omega * t1 - phase_depth)
        ) / (omega * duration)
        columns[MONTH_LABELS[month_index - 1]] = (
            harmonic.mean_c
            + attenuation * (harmonic.sin_c * sine_mean + harmonic.cos_c * cosine_mean)
        )
    frame = pd.DataFrame(columns, index=z)
    frame.index.name = "depth_m"
    frame.attrs.update(
        {
            "mean_c": harmonic.mean_c,
            "sin_c": harmonic.sin_c,
            "cos_c": harmonic.cos_c,
            "amplitude_c": harmonic.amplitude_c,
            "damping_depth_m": delta,
            "soil_diffusivity_m2_day": soil_diffusivity_m2_day(conductivity_w_mk, density_kg_m3, heat_capacity_j_kgk),
        }
    )
    return frame


def measured_monthly_ground(df: pd.DataFrame) -> pd.DataFrame:
    """Return GeoSphere measured monthly means by fixed sensor depth."""
    rows: list[dict[str, float | int]] = []
    for column, depth in MEASURED_GROUND_DEPTHS_M.items():
        if column not in df.columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        monthly = values.groupby(pd.DatetimeIndex(df.index).month).mean()
        for month, value in monthly.items():
            if pd.notna(value):
                rows.append({"month_index": int(month), "depth_m": depth, "temperature_c": float(value)})
    return pd.DataFrame(rows)


def shared_temperature_range(
    profile: pd.DataFrame,
    measured: pd.DataFrame | None = None,
    *,
    pad_fraction: float = 0.08,
    minimum_pad_c: float = 1.0,
) -> tuple[float, float]:
    '''Return one temperature axis range that contains all monthly/observed states.'''
    calculated = profile.to_numpy(dtype=float).ravel()
    calculated = calculated[np.isfinite(calculated)]
    observed = np.array([], dtype=float)
    if measured is not None and not measured.empty and "temperature_c" in measured.columns:
        observed = pd.to_numeric(measured["temperature_c"], errors="coerce").dropna().to_numpy(dtype=float)
    values = np.concatenate([calculated, observed]) if observed.size else calculated
    if values.size == 0:
        raise ValueError("Ground-temperature visualization requires finite temperature values.")
    t_min = float(np.min(values))
    t_max = float(np.max(values))
    pad = max(float(minimum_pad_c), float(pad_fraction) * max(t_max - t_min, 1.0))
    return t_min - pad, t_max + pad


def profile_figure(profile: pd.DataFrame, measured: pd.DataFrame | None = None, title: str = "Monthly ground-temperature profiles") -> go.Figure:
    fig = go.Figure()
    for month_index, month in enumerate(MONTH_LABELS, start=1):
        if month not in profile.columns:
            continue
        fig.add_trace(go.Scatter(x=profile[month], y=profile.index, mode="lines", name=month))
        if measured is not None and not measured.empty:
            points = measured[measured["month_index"] == month_index].sort_values("depth_m")
            if not points.empty:
                fig.add_trace(
                    go.Scatter(
                        x=points["temperature_c"], y=points["depth_m"], mode="markers",
                        name=f"{month} observed", showlegend=False,
                        marker={"size": 7, "symbol": "circle-open"},
                    )
                )
    x_range = shared_temperature_range(profile, measured)
    fig.update_layout(
        template="plotly_white",
        title=title,
        xaxis_title="Ground temperature [°C]",
        yaxis_title="Depth below ground [m]",
        legend_title="Month",
        height=650,
        margin=dict(l=55, r=25, t=70, b=55),
    )
    fig.update_xaxes(range=list(x_range))
    fig.update_yaxes(autorange="reversed")
    return fig


def animated_profile_figure(profile: pd.DataFrame, measured: pd.DataFrame | None = None) -> go.Figure:
    """Return a loopable month-by-month Plotly animation."""
    months = [month for month in MONTH_LABELS if month in profile.columns]
    if not months:
        return go.Figure()
    traces = []
    first = months[0]
    traces.append(go.Scatter(x=profile[first], y=profile.index, mode="lines", name="Calculated profile"))
    if measured is not None and not measured.empty:
        points = measured[measured["month_index"] == 1].sort_values("depth_m")
        traces.append(go.Scatter(x=points.get("temperature_c", []), y=points.get("depth_m", []), mode="markers", name="GeoSphere observed", marker={"size": 9, "symbol": "circle-open"}))
    frames = []
    for month_index, month in enumerate(months, start=1):
        frame_data = [go.Scatter(x=profile[month], y=profile.index)]
        if measured is not None and not measured.empty:
            points = measured[measured["month_index"] == month_index].sort_values("depth_m")
            frame_data.append(go.Scatter(x=points.get("temperature_c", []), y=points.get("depth_m", [])))
        frames.append(go.Frame(name=month, data=frame_data))
    fig = go.Figure(data=traces, frames=frames)
    steps = [{"args": [[m], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}], "label": m, "method": "animate"} for m in months]
    x_range = shared_temperature_range(profile, measured)
    fig.update_layout(
        template="plotly_white",
        title=f"Ground-temperature profile — {first}",
        xaxis_title="Ground temperature [°C]",
        yaxis_title="Depth below ground [m]",
        xaxis_range=list(x_range),
        height=650,
        updatemenus=[{"type": "buttons", "showactive": False, "buttons": [
            {"label": "Play", "method": "animate", "args": [None, {"frame": {"duration": 700, "redraw": True}, "transition": {"duration": 250}, "fromcurrent": True, "mode": "immediate"}]},
            {"label": "Pause", "method": "animate", "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}]},
        ]}],
        sliders=[{"active": 0, "steps": steps, "currentvalue": {"prefix": "Month: "}}],
    )
    fig.update_yaxes(autorange="reversed")
    return fig



def animated_profile_gif_bytes(
    profile: pd.DataFrame,
    measured: pd.DataFrame | None = None,
    *,
    duration_ms: int = 700,
    width: int = 900,
    height: int = 650,
) -> bytes:
    """Render a fixed-axis, infinitely looping 12-month GIF.

    The raster export is a presentation layer only: it consumes the already
    calculated monthly profile and optional measured shallow-soil points. It
    performs no additional climate or ground-temperature calculation.
    """
    months = [month for month in MONTH_LABELS if month in profile.columns]
    if not months:
        raise ValueError("Ground-temperature GIF requires at least one monthly profile.")
    if int(duration_ms) < 100:
        raise ValueError("GIF frame duration must be at least 100 ms.")
    if int(width) < 400 or int(height) < 300:
        raise ValueError("GIF canvas is too small for labelled axes.")

    depth = profile.index.to_numpy(dtype=float)
    if len(depth) < 2 or not np.isfinite(depth).all():
        raise ValueError("GIF export requires a finite ground-depth profile.")
    calculated_values = profile[months].to_numpy(dtype=float)
    finite = calculated_values[np.isfinite(calculated_values)]
    if finite.size == 0:
        raise ValueError("GIF export requires finite calculated temperatures.")

    x_min, x_max = shared_temperature_range(profile, measured)
    z_min, z_max = float(np.min(depth)), float(np.max(depth))
    if z_max <= z_min:
        raise ValueError("GIF export requires a non-zero depth range.")

    left, right, top, bottom = 105, 45, 70, 85
    plot_left, plot_right = left, int(width) - right
    plot_top, plot_bottom = top, int(height) - bottom
    font = ImageFont.load_default()

    def map_x(value: float) -> int:
        return int(round(plot_left + (float(value) - x_min) / (x_max - x_min) * (plot_right - plot_left)))

    def map_y(value: float) -> int:
        return int(round(plot_top + (float(value) - z_min) / (z_max - z_min) * (plot_bottom - plot_top)))

    background = (255, 255, 255)
    grid = (220, 224, 228)
    axis = (55, 60, 65)
    inactive = (220, 223, 226)
    active = (35, 95, 165)
    observed = (170, 55, 55)

    frames: list[Image.Image] = []
    x_ticks = np.linspace(x_min, x_max, 6)
    z_ticks = np.linspace(z_min, z_max, 6)
    for month_index, month in enumerate(months, start=1):
        image = Image.new("RGB", (int(width), int(height)), background)
        draw = ImageDraw.Draw(image)
        draw.text((left, 20), f"Ground-temperature profile — {month}", fill=axis, font=font)

        for tick in x_ticks:
            x = map_x(float(tick))
            draw.line((x, plot_top, x, plot_bottom), fill=grid, width=1)
            draw.text((x - 18, plot_bottom + 12), f"{tick:.1f}", fill=axis, font=font)
        for tick in z_ticks:
            y = map_y(float(tick))
            draw.line((plot_left, y, plot_right, y), fill=grid, width=1)
            draw.text((25, y - 6), f"{tick:.1f}", fill=axis, font=font)

        draw.line((plot_left, plot_top, plot_left, plot_bottom), fill=axis, width=2)
        draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill=axis, width=2)
        draw.text(((plot_left + plot_right) // 2 - 72, int(height) - 32), "Ground temperature [degC]", fill=axis, font=font)
        draw.text((8, 45), "Depth [m]", fill=axis, font=font)

        # Keep the annual context faintly visible while the active month moves.
        for background_month in months:
            vals = pd.to_numeric(profile[background_month], errors="coerce").to_numpy(dtype=float)
            pts = [(map_x(v), map_y(z)) for v, z in zip(vals, depth) if np.isfinite(v) and np.isfinite(z)]
            if len(pts) >= 2:
                draw.line(pts, fill=inactive, width=1)

        vals = pd.to_numeric(profile[month], errors="coerce").to_numpy(dtype=float)
        pts = [(map_x(v), map_y(z)) for v, z in zip(vals, depth) if np.isfinite(v) and np.isfinite(z)]
        if len(pts) >= 2:
            draw.line(pts, fill=active, width=4)

        if measured is not None and not measured.empty:
            points = measured[measured["month_index"] == month_index]
            for record in points.to_dict("records"):
                try:
                    tx = float(record["temperature_c"])
                    zz = float(record["depth_m"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not (math.isfinite(tx) and math.isfinite(zz)):
                    continue
                x, y = map_x(tx), map_y(zz)
                radius = 5
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=observed, width=3)

        draw.line((plot_right - 210, 35, plot_right - 175, 35), fill=active, width=4)
        draw.text((plot_right - 165, 29), "Calculated", fill=axis, font=font)
        if measured is not None and not measured.empty:
            x0, y0 = plot_right - 85, 35
            draw.ellipse((x0 - 4, y0 - 4, x0 + 4, y0 + 4), outline=observed, width=2)
            draw.text((x0 + 10, 29), "Observed", fill=axis, font=font)
        frames.append(image)

    output = BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=int(duration_ms),
        loop=0,
        disposal=2,
        optimize=False,
    )
    return output.getvalue()


def measured_vs_calculated_table(profile: pd.DataFrame, measured: pd.DataFrame) -> pd.DataFrame:
    if measured.empty:
        return pd.DataFrame()
    rows: list[dict[str, float | int | str]] = []
    for record in measured.to_dict("records"):
        month_index = int(record["month_index"])
        depth = float(record["depth_m"])
        month = MONTH_LABELS[month_index - 1]
        calculated = float(np.interp(depth, profile.index.to_numpy(dtype=float), profile[month].to_numpy(dtype=float)))
        observed = float(record["temperature_c"])
        rows.append({"month": month, "month_index": month_index, "depth_m": depth, "observed_c": observed, "calculated_c": calculated, "error_c": calculated - observed})
    return pd.DataFrame(rows).sort_values(["month_index", "depth_m"]).reset_index(drop=True)
