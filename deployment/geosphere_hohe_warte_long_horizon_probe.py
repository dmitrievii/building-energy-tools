#!/usr/bin/env python3
"""Live GeoSphere Hohe Warte 1h humidity regression across the 32768-row boundary.

A *diagnostic*, not a synthetic physical fix. Reproduces the reported
2023-01-01 vs 2023-01-14 cutoff against REAL 1h data, including separate API
downloads, physical source field inspection, canonical hourly transformations,
fixed-pressure vs measured-pressure psychrometrics, and hourly aggregation.
Writes aggregate statistics and reproducible diagnostic evidence as JSON.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import traceback

import numpy as np
import pandas as pd

from epw_climate_analyzer.aggregations import aggregate_summary
from epw_climate_analyzer.geosphere import (
    fetch_metadata, fetch_station_dataset, parse_stations,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame
from epw_climate_analyzer.interpretations import psychrometric_interpretation


RESOURCE = "klima-v2-1h"
FULL_START = pd.Timestamp("2023-01-01T00:00:00Z")
SHORT_START = pd.Timestamp("2023-01-14T00:00:00Z")
END = pd.Timestamp("2026-10-07T23:00:00Z")
FIELDS = (
    "dry_bulb_temperature_c",
    "relative_humidity_pct",
    "atmospheric_station_pressure_pa",
)
RESULT_COLS = FIELDS + (
    "vapor_pressure_pa",
    "humidity_ratio_g_kg",
    "moist_air_enthalpy_kj_kg",
    "wet_bulb_temperature_c",
)


def _stats(frame: pd.DataFrame, name: str) -> dict[str, object]:
    if name not in frame:
        return {"present": False}
    series = pd.to_numeric(frame[name], errors="coerce")
    finite = series.replace([np.inf, -np.inf], np.nan).dropna()
    if finite.empty:
        return {"present": True, "count": 0}
    return {
        "present": True, "count": int(len(finite)),
        "min": float(finite.min()), "mean": float(finite.mean()),
        "max": float(finite.max()), "p95": float(finite.quantile(0.95)),
    }


def _frame_evidence(frame: pd.DataFrame) -> dict[str, object]:
    return {"rows": len(frame), "first": str(frame.index.min()),
            "last": str(frame.index.max()),
            "columns": {k: _stats(frame, k) for k in RESULT_COLS},
            "naive_hourly_gap_count": int(len(pd.date_range(frame.index.min(), frame.index.max(), freq="h")) - len(frame))}


def _run_physical(ds: object, *, fixed_pressure: bool) -> tuple[pd.DataFrame, dict[str, object]]:
    result = prepare_historical_analysis_frame(
        ds, include_psychrometrics=True,
        pressure_override_pa=101325.0 if fixed_pressure else None,
        fallback_pressure_pa=101325.0,
    )
    evidence = _frame_evidence(result)
    if "humidity_ratio_g_kg" in result:
        w = pd.to_numeric(result["humidity_ratio_g_kg"], errors="coerce").to_numpy(dtype=float)
        h = pd.to_numeric(result["moist_air_enthalpy_kj_kg"], errors="coerce").to_numpy(dtype=float)
        t = pd.to_numeric(result["dry_bulb_temperature_c"], errors="coerce").to_numpy(dtype=float)
        expected_h = 1.006 * t + w / 1000.0 * (2501.0 + 1.86 * t)
        diff = np.abs(h - expected_h)
        evidence["max_enthalpy_closure_error_kj_kg"] = (
            float(np.nanmax(diff)) if np.isfinite(diff).any() else None
        )
        evidence["humidity_ratio_over_100_g_kg"] = int(np.count_nonzero(w > 100.0))
        hourly = aggregate_summary(result, "humidity_ratio_g_kg", "Hourly")
        same_hour = result["humidity_ratio_g_kg"].reindex(hourly.index)
        evidence["hourly_mean_max_difference_g_kg"] = float(
            np.nanmax(np.abs(hourly["mean"].to_numpy(dtype=float) - same_hour.to_numpy(dtype=float)))
        )
        evidence["psychrometric_interpretation"] = psychrometric_interpretation(result)[:600]
    return result, evidence


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="artifacts/geosphere-hohe-warte-long-horizon/evidence.json")
    args = ap.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    output: dict[str, object] = {
        "resource": RESOURCE, "station": "Wien Hohe Warte", "end": str(END),
        "start_full": str(FULL_START), "start_short": str(SHORT_START),
        "python_version": sys.version,
        "cases": {}, "status": "started",
    }
    try:
        metadata = fetch_metadata(resource_id=RESOURCE)
        station = next(s for s in parse_stations(metadata) if s.station_id == "105")
        output["station_id"] = station.station_id
        frames = {}
        for key, start in (("full", FULL_START), ("short", SHORT_START)):
            print(f"Querying {key} live 1h GeoSphere {station.name} {start}..{END}", flush=True)
            ds = fetch_station_dataset(
                station=station, start=start, end=END,
                resource_id=RESOURCE, metadata=metadata, canonical_variables=FIELDS,
                timeout_s=60,
            )
            entry: dict[str, object] = {
                "raw_canonical": _frame_evidence(ds.data),
                "provider_request_count": len(ds.provenance.source_reference.splitlines()),
            }
            frames[key] = ds
            output["cases"][key] = entry
            for pressure_mode in ("fixed", "measured"):
                print(f"Computing {key}, {pressure_mode}, {len(ds.data)} source rows", flush=True)
                result, evidence = _run_physical(ds, fixed_pressure=(pressure_mode == "fixed"))
                entry[pressure_mode] = evidence
                frames[key + "_" + pressure_mode] = result

        # Isolate a dataset-size effect from the actual provider request response.
        short = frames["short"]
        full = frames["full"]
        common = full.data.loc[short.data.index]
        discrepancies = {}
        for column in FIELDS:
            x = common[column].to_numpy(dtype=float)
            y = short.data[column].to_numpy(dtype=float)
            same = np.isclose(x, y, rtol=0, atol=1e-10, equal_nan=True)
            discrepancies[column] = int((~same).sum())
        output["source_overlapping_hour_differences"] = discrepancies
        output["overlap_same_timestamps"] = bool(common.index.equals(short.data.index))

        for pressure_mode in ("fixed", "measured"):
            x = frames["full_" + pressure_mode].loc[frames["short_" + pressure_mode].index]
            y = frames["short_" + pressure_mode]
            output["derived_overlapping_hour_max_diff_" + pressure_mode] = {}
            for col in ("humidity_ratio_g_kg", "moist_air_enthalpy_kj_kg", "vapor_pressure_pa"):
                xv = x[col].to_numpy(dtype=float)
                yv = y[col].to_numpy(dtype=float)
                diff = np.abs(xv - yv)
                output["derived_overlapping_hour_max_diff_" + pressure_mode][col] = (
                    float(np.nanmax(diff)) if np.isfinite(diff).any() else None
                )

        output["status"] = "complete"
    except Exception as exc:
        output["status"] = "failed"
        output["exception"] = repr(exc)
        output["traceback"] = traceback.format_exc()[-8000:]
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=False), flush=True)
    return 0 if output["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
