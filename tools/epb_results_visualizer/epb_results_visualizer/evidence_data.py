"""Read-only V3 evidence tables for the EPB Results Visualizer.

No results are calculated or synthesized here. Every chart draws from a named
export table. The ZIP gate is shared with the established bundle importer.
"""
from __future__ import annotations

from io import BytesIO
import json
import zipfile

import numpy as np
import pandas as pd

from .bundle import BundleValidationError, _validate_archive, MAX_ROWS

EVIDENCE_FILES = {
    "building": "visualization/building.json",
    "zones": "visualization/zones.csv",
    "surfaces": "visualization/surface-inventory.csv",
    "windows": "visualization/opening-inventory.csv",
    "orientation": "visualization/orientation-buckets.csv",
    "zone_physics": "visualization/monthly-physical-zones.csv",
    "surface_physics": "visualization/monthly-physical-surfaces.csv",
    "signals": "visualization/signal-catalog.csv",
    "monthly_thermal": "visualization/monthly-thermal.csv",
    "monthly_metrics": "monthly-metrics.csv",
    "carrier": "carrier-ledger.csv",
    "scenarios": "scenario-summary.csv",
    "compliance": "compliance.csv",
}
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_AXIS = list(range(1, 13))
NON_ADDITIVE_UNITS = {"1", "%", "°C", "C", "K", "W/m2K", "W/(m²·K)"}


def load_evidence(payload: bytes) -> dict:
    """Load whitelisted source evidence, preserving missing data as missing.

    Archive safety limits are imposed by the shared EAW ZIP importer. Only the
    explicit source files listed above are read; embedded code is never executed.
    """
    result = {}
    with _validate_archive(payload) as archive:
        known = set(archive.namelist())
        for key, name in EVIDENCE_FILES.items():
            if name not in known:
                result[key] = {} if name.endswith(".json") else pd.DataFrame()
                continue
            item = archive.getinfo(name)
            if name.endswith(".json"):
                data = json.loads(archive.read(name))
                if not isinstance(data, dict):
                    raise BundleValidationError(name + " must contain an object.")
                result[key] = data
                continue
            if item.file_size == 0:
                result[key] = pd.DataFrame()
                continue
            try:
                frame = pd.read_csv(BytesIO(archive.read(name)),
                                    low_memory=False, nrows=MAX_ROWS + 1)
            except (pd.errors.ParserError, ValueError) as exc:
                raise BundleValidationError("Malformed evidence CSV: " + name) from exc
            if len(frame) > MAX_ROWS:
                raise BundleValidationError("Evidence table exceeds row limit: " + name)
            for column in ("month", "value", "value_kwh", "area_m2",
                           "floor_area_m2", "opening_gross_m2",
                           "facade_total_m2", "opaque_net_wall_m2",
                           "wwr_fraction", "azimuth_deg", "tilt_deg",
                           "u_value_w_m2k", "solar_g_value"):
                if column in frame:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
            result[key] = frame
    return result


def is_present(data: dict, key: str) -> bool:
    value = data.get(key)
    return bool(value) if isinstance(value, dict) else isinstance(value, pd.DataFrame) and not value.empty


def available_quantities(frame: pd.DataFrame, *, unit: str | None = None) -> list[str]:
    if frame.empty or not {"quantity", "unit"}.issubset(frame.columns):
        return []
    subset = frame if unit is None else frame[frame.unit.astype(str) == unit]
    return sorted(subset.quantity.dropna().astype(str).unique().tolist())


def quantity_unit(frame: pd.DataFrame, quantity: str) -> str | None:
    if frame.empty or not {"quantity", "unit"}.issubset(frame.columns):
        return None
    units = frame.loc[frame.quantity == quantity, "unit"].dropna().astype(str).unique()
    return str(units[0]) if len(units) == 1 else None


def monthly_series(frame: pd.DataFrame, quantities: list[str], *,
                   group: str | None = None, zones: list[str] | None = None,
                   mode: str = "sum") -> pd.DataFrame:
    """Return month/series/value for source quantities of a single unit.

    Energy is additive across selected physical zones/surfaces. Ratios are not:
    caller must choose mean and the UI identifies this as an unweighted average.
    """
    if frame.empty or not {"month", "quantity", "value", "unit"}.issubset(frame):
        return pd.DataFrame(columns=["month", "series", "value"])
    selected = frame.loc[frame.quantity.isin(quantities)].copy()
    if zones is not None and "zone_id" in selected:
        selected = selected[selected.zone_id.astype(str).isin(zones)]
    units = selected.unit.dropna().astype(str).unique()
    if len(units) > 1:
        raise BundleValidationError("Cannot combine quantities with different units.")
    if units.size and units[0] in NON_ADDITIVE_UNITS and mode == "sum":
        raise BundleValidationError("Ratios and state quantities must not be summed.")
    selected = selected[selected.month.isin(MONTH_AXIS)].dropna(subset=["value"])
    if selected.empty:
        return pd.DataFrame(columns=["month", "series", "value"])
    selected["series"] = selected.quantity.astype(str)
    if group and group in selected.columns:
        selected["series"] = selected[group].fillna("Unclassified").astype(str) + " · " + selected["series"]
    operation = "mean" if mode == "mean" else "sum"
    return (selected.groupby(["month", "series"], as_index=False)
            .value.agg(operation).sort_values(["month", "series"]))


def orientation_summary(data: dict) -> pd.DataFrame:
    """Select source aggregate-or-zone orientation buckets, never both.

    A source can export 8 building aggregate rows as well as per-zone rows.
    Adding both would double-count glazing and wall areas.
    """
    frame = data.get("orientation", pd.DataFrame())
    if frame.empty or "direction" not in frame:
        return pd.DataFrame()
    frame = frame.copy()
    if "zone_id" in frame and frame.zone_id.isna().any():
        frame = frame.loc[frame.zone_id.isna()].copy()
    area_cols = [c for c in ("opening_gross_m2", "opaque_net_wall_m2",
                             "facade_total_m2") if c in frame]
    if not area_cols:
        return pd.DataFrame()
    summary = frame.groupby("direction", as_index=False)[area_cols].sum(min_count=1)
    if {"opening_gross_m2", "facade_total_m2"}.issubset(summary):
        with np.errstate(divide="ignore", invalid="ignore"):
            summary["wwr_fraction"] = (summary.opening_gross_m2 /
                                        summary.facade_total_m2.where(summary.facade_total_m2 > 0))
    order = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    summary["order"] = summary.direction.map({d: i for i, d in enumerate(order)}).fillna(99)
    return summary.sort_values("order").drop(columns="order")


def building_area(data: dict) -> float | None:
    building = data.get("building", {})
    try:
        value = float(building.get("conditioned_gross_floor_area_m2"))
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) and value > 0 else None


def zone_annual_intensity(data: dict, quantity: str) -> pd.DataFrame:
    frame = data.get("zone_physics", pd.DataFrame())
    zones = data.get("zones", pd.DataFrame())
    if frame.empty or zones.empty or quantity not in frame.quantity.values:
        return pd.DataFrame()
    if not {"zone_id", "floor_area_m2"}.issubset(zones):
        return pd.DataFrame()
    unit = quantity_unit(frame, quantity)
    if unit in NON_ADDITIVE_UNITS:
        return pd.DataFrame()
    totals = (frame.loc[frame.quantity == quantity].groupby("zone_id", as_index=False)
              .value.sum(min_count=1))
    joined = totals.merge(zones[["zone_id", "floor_area_m2"] +
                                (["zone_name"] if "zone_name" in zones else [])],
                          on="zone_id", how="left", validate="one_to_one")
    joined["intensity"] = joined.value / joined.floor_area_m2.where(joined.floor_area_m2 > 0)
    return joined.replace([np.inf, -np.inf], np.nan).dropna(subset=["intensity"])


def coverage_table(data: dict) -> pd.DataFrame:
    rows = []
    for key, member in EVIDENCE_FILES.items():
        value = data.get(key)
        count = len(value) if isinstance(value, pd.DataFrame) else int(bool(value))
        rows.append({"Dataset": key, "ZIP member": member,
                     "Rows": count, "Available": count > 0})
    return pd.DataFrame(rows)
