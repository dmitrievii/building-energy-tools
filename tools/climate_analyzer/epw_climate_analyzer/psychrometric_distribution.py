"""Duration-weighted psychrometric occupancy regions.

The Middle-90% envelope used by Climate Analyzer is a two-dimensional
highest-density occupancy region, not a rectangle made from independent
marginal percentiles.  Psychrometric states are binned in dry-bulb temperature
and relative humidity, weighted by the physical duration represented by each
record, and the densest cells are retained until at least the requested share of
observed duration is covered.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import psychrolib

from .aggregations import native_interval_hours
from .psychrometrics import DEFAULT_PRESSURE_PA

psychrolib.SetUnitSystem(psychrolib.SI)


@dataclass(frozen=True)
class PsychrometricOccupancyEnvelope:
    """A duration-weighted highest-density psychrometric occupancy region."""

    tiles: pd.DataFrame
    target_share: float
    achieved_share: float
    total_hours: float
    selected_hours: float
    temperature_bin_c: float
    rh_bin_pct: float

    @property
    def selected_tiles(self) -> pd.DataFrame:
        return self.tiles[self.tiles["selected"]].copy()


def psychrometric_occupancy_envelope(
    df: pd.DataFrame,
    *,
    target_share: float = 0.90,
    temperature_bin_c: float = 1.0,
    rh_bin_pct: float = 5.0,
) -> PsychrometricOccupancyEnvelope:
    """Return the densest psychrometric cells covering at least ``target_share``.

    Equal-frequency cells at the cutoff are retained together.  The achieved
    share may therefore be slightly greater than the requested share, avoiding
    arbitrary spatial selection among tied cells.
    """
    target = float(target_share)
    t_step = float(temperature_bin_c)
    rh_step = float(rh_bin_pct)
    if not 0.0 < target <= 1.0:
        raise ValueError("target_share must be greater than 0 and at most 1.")
    if not np.isfinite(t_step) or t_step <= 0.0:
        raise ValueError("temperature_bin_c must be a finite positive number.")
    if not np.isfinite(rh_step) or rh_step <= 0.0 or rh_step > 100.0:
        raise ValueError("rh_bin_pct must be finite, positive and at most 100.")

    required = ["dry_bulb_temperature_c", "relative_humidity_pct"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise KeyError(f"Missing psychrometric occupancy columns: {', '.join(missing)}")

    data = df[required].copy()
    data["dry_bulb_temperature_c"] = pd.to_numeric(data["dry_bulb_temperature_c"], errors="coerce")
    data["relative_humidity_pct"] = pd.to_numeric(data["relative_humidity_pct"], errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    data = data[data["relative_humidity_pct"].between(0.0, 100.0, inclusive="both")]
    if data.empty:
        empty = pd.DataFrame(columns=["temperature_bin_c", "rh_bin_pct", "records", "hours", "selected"])
        return PsychrometricOccupancyEnvelope(empty, target, 0.0, 0.0, 0.0, t_step, rh_step)

    data["temperature_bin_c"] = np.floor(data["dry_bulb_temperature_c"] / t_step) * t_step
    rh_floor = np.floor(data["relative_humidity_pct"] / rh_step) * rh_step
    data["rh_bin_pct"] = rh_floor.clip(0.0, max(0.0, 100.0 - rh_step))

    tiles = (
        data.groupby(["temperature_bin_c", "rh_bin_pct"], observed=True)
        .size()
        .reset_index(name="records")
    )
    hours_per_record = float(native_interval_hours(df))
    tiles["hours"] = tiles["records"].astype(float) * hours_per_record
    tiles = tiles.sort_values(
        ["hours", "temperature_bin_c", "rh_bin_pct"],
        ascending=[False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    total_hours = float(tiles["hours"].sum())
    if total_hours <= 0.0:
        tiles["selected"] = False
        return PsychrometricOccupancyEnvelope(tiles, target, 0.0, total_hours, 0.0, t_step, rh_step)

    cumulative = tiles["hours"].cumsum() / total_hours
    cutoff_candidates = np.flatnonzero(cumulative.to_numpy(dtype=float) >= target)
    cutoff_index = int(cutoff_candidates[0]) if cutoff_candidates.size else len(tiles) - 1
    cutoff_hours = float(tiles.iloc[cutoff_index]["hours"])
    tolerance = max(1e-12, abs(cutoff_hours) * 1e-12)
    tiles["selected"] = tiles["hours"] >= cutoff_hours - tolerance
    selected_hours = float(tiles.loc[tiles["selected"], "hours"].sum())
    achieved_share = selected_hours / total_hours

    return PsychrometricOccupancyEnvelope(
        tiles=tiles,
        target_share=target,
        achieved_share=achieved_share,
        total_hours=total_hours,
        selected_hours=selected_hours,
        temperature_bin_c=t_step,
        rh_bin_pct=rh_step,
    )


def _humidity_ratio_g_kg(t_c: float, rh_pct: float, pressure_pa: float) -> float:
    rh = float(np.clip(float(rh_pct) / 100.0, 0.0, 1.0))
    return float(psychrolib.GetHumRatioFromRelHum(float(t_c), rh, float(pressure_pa)) * 1000.0)


def _chart_point(t_c: float, d_g_kg: float, chart_type: str) -> tuple[float, float]:
    if chart_type == "i-d":
        w = max(float(d_g_kg), 0.0) / 1000.0
        h = float(psychrolib.GetMoistAirEnthalpy(float(t_c), w) / 1000.0)
        return float(d_g_kg), h
    return float(t_c), float(d_g_kg)


def envelope_polygon_coordinates(
    envelope: PsychrometricOccupancyEnvelope,
    *,
    chart_type: str = "T-d",
    pressure_pa: float = DEFAULT_PRESSURE_PA,
) -> tuple[list[float | None], list[float | None]]:
    """Return one Plotly-compatible multi-polygon path for selected cells."""
    xs: list[float | None] = []
    ys: list[float | None] = []
    t_step = float(envelope.temperature_bin_c)
    rh_step = float(envelope.rh_bin_pct)
    for _, row in envelope.selected_tiles.iterrows():
        t0 = float(row["temperature_bin_c"])
        t1 = t0 + t_step
        rh0 = float(row["rh_bin_pct"])
        rh1 = min(100.0, rh0 + rh_step)
        corners = [(t0, rh0), (t1, rh0), (t1, rh1), (t0, rh1), (t0, rh0)]
        for t_c, rh_pct in corners:
            d_g_kg = _humidity_ratio_g_kg(t_c, rh_pct, pressure_pa)
            x, y = _chart_point(t_c, d_g_kg, chart_type)
            xs.append(x)
            ys.append(y)
        xs.append(None)
        ys.append(None)
    return xs, ys
