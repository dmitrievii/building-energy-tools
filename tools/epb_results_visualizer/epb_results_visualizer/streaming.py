"""Bounded-memory streaming of one zone or a building aggregate from EPB ZIPs.

Never materializes all zones, all trace rows or result.json. Missing zone-hours
are NaN, not zeros. Source timestamps are not used as a chronological axis.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import zipfile

import numpy as np
import pandas as pd

from .bundle import (
    BundleValidationError, METRICS, _validate_archive, _json, YEAR_8760, YEAR_8784,
)

CHUNK = 40_000
SOURCES = {
    "thermal": "visualization/hourly-thermal.csv",
    "trace": "visualization/validation-trace.csv",
    "ventilation": "visualization/ventilation-hourly.csv",
}
BUILDING_UNITS = {"W", "m3/s", "W/K"}
BOOLEAN_UNIT = "bool"
TEMP_UNITS = {"degC", "°C", "C", "K", "%"}
THERMAL_BUILDING = {k for k, spec in METRICS.items() if spec[1] == "power"}


@dataclass
class StreamResult:
    frame: pd.DataFrame
    units: dict[str, str]
    scope: str
    n_zones: int
    missing: dict[str, int]
    annual_hours: int
    scanned_rows: int


def _context(z: zipfile.ZipFile) -> tuple[int, int, list[str]]:
    vm = _json(z, "visualization/manifest.json")
    hours = int(vm.get("annual_hours", 8760))
    initialization = int(vm.get("initialization_hours", 0))
    if hours not in (8760, 8784) or not 0 <= initialization <= 20000:
        raise BundleValidationError("Unsupported reporting or initialization hour count.")
    zones = _json(z, "visualization/zone-metadata.json")
    ids = list(zones)
    if not ids:
        data = z.read("visualization/zones.csv") if "visualization/zones.csv" in z.namelist() else b""
        if data:
            ids = pd.read_csv(BytesIO(data), usecols=["zone_id"]).zone_id.dropna().astype(str).tolist()
    if not ids or len(ids) != len(set(ids)):
        raise BundleValidationError("Zone inventory is absent or duplicated.")
    return hours, initialization, ids


def available_source_signals(payload: bytes, source: str, scope: str) -> dict[str, str]:
    """Authoritative options obtained from the source header/catalog/manifest."""
    if source not in SOURCES or scope not in ("zone", "building"):
        raise BundleValidationError("Unknown source or scope.")
    with _validate_archive(payload, selective=True) as z:
        path = SOURCES[source]
        if source == "thermal":
            if scope == "building" and "visualization/building-hourly.csv" in z.namelist():
                path = "visualization/building-hourly.csv"
            elif scope == "zone" and "visualization/zone-index.csv" in z.namelist():
                index = pd.read_csv(z.open("visualization/zone-index.csv"))
                if not index.empty:
                    path = str(index.iloc[0].hourly_thermal_path)
        if path not in z.namelist() or not z.getinfo(path).file_size:
            if source not in ("trace", "ventilation") or "visualization/trace-zone-index.csv" not in z.namelist():
                return {}
        if source == "thermal":
            with z.open(path) as f:
                header = pd.read_csv(f, nrows=0).columns
            return {k: METRICS[k][2] for k in METRICS if k in header and
                    (scope == "zone" or k in THERMAL_BUILDING)}
        catalog = pd.read_csv(z.open("visualization/signal-catalog.csv")) if (
            "visualization/signal-catalog.csv" in z.namelist()) else pd.DataFrame()
        if catalog.empty:
            manifest = _json(z, "visualization/validation-trace-manifest.json")
            keys = manifest.get("availableQuantities") or []
            catalog = pd.DataFrame({"quantity_id": ["trace." + q for q in keys], "unit": [""] * len(keys)})
        if not {"quantity_id", "unit"}.issubset(catalog.columns):
            return {}
        result = {}
        for row in catalog.itertuples(index=False):
            q = str(row.quantity_id)
            unit = str(row.unit)
            if not q.startswith("trace."):
                continue
            q = q[6:]
            if source == "ventilation" and not q.startswith("ventilation."):
                continue
            if source == "trace" and q.startswith("ventilation."):
                # Faster, separate ventilation source avoids rescanning 2.14 GB.
                continue
            if unit in ("nan", "", "None"):
                continue
            if scope == "building" and unit not in BUILDING_UNITS | {BOOLEAN_UNIT}:
                continue
            # Per-zone solver maxima are local limits, not simultaneously
            # available installed equipment powers. Never sum them by building.
            if scope == "building" and q in ("load.maximum_heating_w",
                                            "load.maximum_cooling_w"):
                continue
            result[q] = unit
        return dict(sorted(result.items()))


def select_series(payload: bytes, *, source: str, scope: str,
                  quantities: list[str], zone_id: str | None = None) -> StreamResult:
    """Stream one source into at most reporting_hours × requested quantities.

    A building result needs one native observation for each zone/hour/quantity.
    If any observation is missing or duplicated, that hour is NaN. This avoids
    reporting partial building sums as physically complete totals.
    """
    if source not in SOURCES or scope not in ("zone", "building"):
        raise BundleValidationError("Unknown streaming source/scope.")
    if not quantities or len(quantities) > 4 or len(set(quantities)) != len(quantities):
        raise BundleValidationError("Select between one and four distinct quantities.")
    options = available_source_signals(payload, source, scope)
    if not set(quantities).issubset(options):
        raise BundleValidationError("Selected signals are unavailable for this scope.")
    if scope == "building" and zone_id is not None:
        raise BundleValidationError("Building scope cannot also select a zone.")
    with _validate_archive(payload, selective=True) as z:
        annual, init, zone_ids = _context(z)
        if scope == "zone" and zone_id not in zone_ids:
            raise BundleValidationError("Selected zone is absent in this evidence bundle.")
        path = SOURCES[source]
        partitioned = False
        building_summary = False
        if scope == "building" and source == "thermal" and "visualization/building-hourly.csv" in z.namelist():
            path = "visualization/building-hourly.csv"
            building_summary = True
        elif scope == "zone":
            indexed = ("visualization/zone-index.csv" if source == "thermal"
                       else "visualization/trace-zone-index.csv")
            if indexed in z.namelist():
                index = pd.read_csv(z.open(indexed))
                key = "hourly_thermal_path" if source == "thermal" else "validation_trace_path"
                if {"zone_id", key}.issubset(index.columns):
                    found = index.loc[index.zone_id.astype(str) == zone_id, key]
                    if len(found) > 1:
                        raise BundleValidationError("Ambiguous zone partition index.")
                    if len(found) == 1:
                        direct = str(found.iloc[0])
                        if not direct.startswith("visualization/zones/") or direct not in z.namelist():
                            raise BundleValidationError("Unsafe or missing indexed zone partition.")
                        path = direct
                        partitioned = True
                    elif not index.empty:
                        raise BundleValidationError("This zone has no captured source partition.")
        if path not in z.namelist():
            raise BundleValidationError("The requested source table is not in the ZIP.")
        totals = {q: np.zeros(annual, dtype=np.float64) for q in quantities}
        counts = {q: np.zeros(annual, dtype=np.int64) for q in quantities}
        selections = []
        scanned = 0
        if source == "thermal":
            columns = {"zone_id", "hour_index", *quantities}
        else:
            columns = {"step", "hour_index", "zone_id", "initialization",
                       "category", "quantity", "numeric_value", "value"}
        with z.open(path) as f:
            for chunk in pd.read_csv(f, chunksize=CHUNK,
                                     usecols=lambda col: col in columns,
                                     low_memory=False):
                scanned += len(chunk)
                if scope == "zone" and not partitioned:
                    chunk = chunk.loc[chunk.zone_id.astype(str) == zone_id]
                    if chunk.empty:
                        continue
                if source == "thermal":
                    hour = pd.to_numeric(chunk.hour_index, errors="coerce")
                    valid = hour.notna() & hour.between(1, annual)
                    chunk = chunk.loc[valid]
                    if chunk.empty:
                        continue
                    hour = hour.loc[valid].astype("int64").to_numpy()
                    if scope == "zone":
                        part = chunk[["hour_index", *quantities]].copy()
                        for q in quantities:
                            part[q] = pd.to_numeric(part[q], errors="coerce")
                        selections.append(part)
                    else:
                        for q in quantities:
                            value = pd.to_numeric(chunk[q], errors="coerce").to_numpy(dtype=float)
                            good = np.isfinite(value)
                            np.add.at(totals[q], hour[good] - 1, value[good])
                            np.add.at(counts[q], hour[good] - 1, 1)
                    continue
                # Native EPW timestamps may jump between years. The new zone
                # partitions already contain the consecutive reporting hour.
                if partitioned:
                    hour = pd.to_numeric(chunk.hour_index, errors="coerce")
                    valid = hour.notna() & hour.between(1, annual)
                    chunk = chunk.loc[valid].copy()
                    if chunk.empty:
                        continue
                    chunk["hour_index"] = hour.loc[valid].astype("int64")
                else:
                    steps = pd.to_numeric(chunk.step, errors="coerce")
                    included = (chunk.initialization.astype(str).str.lower() == "false")
                    valid = included & steps.notna() & steps.between(init, init + annual - 1)
                    chunk = chunk.loc[valid].copy()
                    if chunk.empty:
                        continue
                    chunk["hour_index"] = (steps.loc[valid].astype("int64") - init + 1)
                chunk["signal"] = chunk.category.astype(str) + "." + chunk.quantity.astype(str)
                chunk = chunk[chunk.signal.isin(quantities)]
                if chunk.empty:
                    continue
                col = "numeric_value" if partitioned or source == "trace" else "value"
                chunk["value"] = pd.to_numeric(chunk[col], errors="coerce")
                chunk = chunk.dropna(subset=["value"])
                if chunk.empty:
                    continue
                if scope == "zone":
                    selections.append(chunk[["hour_index", "signal", "value"]].copy())
                else:
                    h = chunk.hour_index.to_numpy(dtype="int64") - 1
                    v = chunk.value.to_numpy(dtype=float)
                    signals = chunk.signal.to_numpy()
                    for q in quantities:
                        matched = (signals == q) & np.isfinite(v)
                        np.add.at(totals[q], h[matched], v[matched])
                        np.add.at(counts[q], h[matched], 1)

        if scope == "zone":
            if not selections:
                out = pd.DataFrame({"hour_index": np.arange(1, annual + 1)})
            else:
                src = pd.concat(selections, ignore_index=True)
                if source == "thermal":
                    if src.hour_index.duplicated().any():
                        raise BundleValidationError("Duplicated zone-hour thermal rows.")
                    out = src
                else:
                    if src[["hour_index", "signal"]].duplicated().any():
                        raise BundleValidationError("Duplicated zone-hour trace signal.")
                    out = src.pivot(index="hour_index", columns="signal", values="value").reset_index()
            out = pd.DataFrame({"hour_index": np.arange(1, annual + 1)}).merge(
                out, on="hour_index", how="left", validate="one_to_one")
            for q in quantities:
                if q not in out:
                    out[q] = np.nan
            out = out[["hour_index", *quantities]]
            missing = {q: int(out[q].isna().sum()) for q in quantities}
        else:
            expected = 1 if building_summary else len(zone_ids)
            out = pd.DataFrame({"hour_index": np.arange(1, annual + 1)})
            missing = {}
            for q in quantities:
                good = counts[q] == expected
                values = totals[q].copy()
                if options[q] == BOOLEAN_UNIT:
                    # Explicit proportion of captured zone states, not an
                    # additive physical quantity.
                    values = values / expected * 100
                values[~good] = np.nan
                out[q] = values
                missing[q] = int((~good).sum())
        out.attrs['scope'] = scope
        out.attrs['annual_hours'] = annual
        return StreamResult(out, {q: options[q] for q in quantities},
                            scope, len(zone_ids), missing, annual, scanned)


def time_aggregate(frame: pd.DataFrame, units: dict[str, str],
                   cadence: str = "Hour", power_mode: str = "Energy") -> tuple[pd.DataFrame, dict[str, str]]:
    """Integrate W over hourly intervals, average states/flows, preserve gaps.

    Only thermal/ventilation power in W is converted to kWh. For daily/monthly
    interval energy, any missing source hour yields NaN instead of a partial sum.
    """
    if cadence not in ("Hour", "Day", "Month", "Year"):
        raise BundleValidationError("Unknown time resolution.")
    if power_mode not in ("Energy", "Mean", "Peak"):
        raise BundleValidationError("Unknown power display convention.")
    if frame.empty:
        return frame, units
    data = frame.copy()
    annual = int(frame.attrs.get('annual_hours', data.hour_index.max()))
    if annual not in (8760, 8784):
        raise BundleValidationError("Unknown annual reference calendar.")
    refyear = YEAR_8760 if annual == 8760 else YEAR_8784
    data["time"] = pd.Timestamp(refyear, 1, 1) + pd.to_timedelta(data.hour_index - 1, unit="h")
    if cadence == "Hour":
        key = data.time
    elif cadence == "Day":
        key = data.time.dt.floor("D")
    elif cadence == "Month":
        key = data.time.dt.to_period("M").dt.to_timestamp()
    else:
        key = data.time.dt.to_period("Y").dt.to_timestamp()
    result = pd.DataFrame({"time": pd.Index(key).drop_duplicates().sort_values()})
    out_units = {}
    for q, unit in units.items():
        values = pd.to_numeric(data[q], errors="coerce")
        temp = pd.DataFrame({"time": key, "value": values})
        grouped = temp.groupby("time", sort=True).value
        if unit == "W":
            if power_mode == "Energy":
                series = grouped.sum(min_count=1) / 1000
                out_units[q] = "kWh"
            elif power_mode == "Peak":
                series = grouped.max()
                out_units[q] = "W"
            else:
                series = grouped.mean()
                out_units[q] = "W"
        else:
            series = grouped.mean()
            out_units[q] = "%" if unit == BOOLEAN_UNIT and frame.attrs.get("scope") == "building" else unit
        # Do not claim a complete day/month/year when any reporting hour is
        # missing, or when the user selected only part of the interval.
        if cadence == "Hour":
            expected = pd.Series(1, index=series.index)
        elif cadence == "Day":
            expected = pd.Series(24, index=series.index)
        elif cadence == "Month":
            expected = pd.Series(series.index.days_in_month * 24, index=series.index)
        else:
            expected = pd.Series(annual, index=series.index)
        series = series.where(grouped.count() == expected)
        result[q] = result.time.map(series)
    return result, out_units
