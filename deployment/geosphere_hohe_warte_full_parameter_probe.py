#!/usr/bin/env python3
"""Diagnose Hohe Warte humidity with ALL supported GeoSphere hourly provider fields.

Unlike the basic three-field incident probe, this one makes the same full
parameter/quality-flag batch requests permitted by the public UI and derives
properties in the default Streamlit local-civil analysis clock.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

import numpy as np
import pandas as pd

from epw_climate_analyzer.analysis_clock import LOCAL_CIVIL_TIME, UTC_TIME
from epw_climate_analyzer.geosphere import (
    fetch_metadata, fetch_station_dataset, parse_stations, supported_parameter_mapping,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame
from epw_climate_analyzer.quality_policy import apply_quality_policy, QUALITY_POLICY_ALL
from geosphere_hohe_warte_long_horizon_probe import _frame_evidence


STARTS = {
    "long": pd.Timestamp("2023-01-01T00:00:00Z"),
    "short": pd.Timestamp("2023-01-14T00:00:00Z"),
}
END = pd.Timestamp("2026-10-07T23:00:00Z")
COLUMNS = (
    "dry_bulb_temperature_c",
    "relative_humidity_pct",
    "atmospheric_station_pressure_pa",
    "humidity_ratio_g_kg",
    "moist_air_enthalpy_kj_kg",
)


def _closure(frame: pd.DataFrame) -> dict[str, object]:
    w = pd.to_numeric(frame["humidity_ratio_g_kg"], errors="coerce").to_numpy(dtype=float)
    h = pd.to_numeric(frame["moist_air_enthalpy_kj_kg"], errors="coerce").to_numpy(dtype=float)
    t = pd.to_numeric(frame["dry_bulb_temperature_c"], errors="coerce").to_numpy(dtype=float)
    expected = 1.006 * t + w / 1000.0 * (2501.0 + 1.86 * t)
    dif = np.abs(expected - h)
    return {
        "ratio_over_100_g_kg": int(np.count_nonzero(w > 100)),
        "ratio_mean_g_kg": float(np.nanmean(w)),
        "ratio_max_g_kg": float(np.nanmax(w)),
        "enthalpy_max_closure_error": float(np.nanmax(dif)),
        "nan_count": int(np.count_nonzero(~np.isfinite(w))),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/geosphere-hohe-warte-full-fields/evidence.json")
    args = parser.parse_args()
    output = {"start_dates": {k: str(v) for k, v in STARTS.items()},
              "end": str(END), "cases": {}, "status": "started"}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        metadata = fetch_metadata(resource_id="klima-v2-1h")
        station = next(s for s in parse_stations(metadata) if s.station_id == "105")
        fields = tuple(field.canonical_name for field in supported_parameter_mapping(
            metadata, resource_id="klima-v2-1h"
        ).values())
        output["supported_fields"] = fields
        results = {}
        for key, start in STARTS.items():
            print(f"Loading ALL {len(fields)} fields: {key} {start}..{END}", flush=True)
            ds = fetch_station_dataset(
                station=station, start=start, end=END,
                resource_id="klima-v2-1h", metadata=metadata,
                canonical_variables=fields, timeout_s=60,
            )
            case = {"source": _frame_evidence(ds.data),
                    "column_names": list(ds.data.columns),
                    "request_batch_count": len(ds.provenance.source_reference.splitlines()),
                    "clocks": {}}
            for clock in (UTC_TIME, LOCAL_CIVIL_TIME):
                for mode in ("measured", "fixed"):
                    name = clock + "_" + mode
                    print(f"Deriving {key} {name} {len(ds.data)} rows", flush=True)
                    source = apply_quality_policy(ds.data, QUALITY_POLICY_ALL)
                    from dataclasses import replace
                    prepared = replace(ds, data=source)
                    frame = prepare_historical_analysis_frame(
                        prepared, include_psychrometrics=True,
                        fallback_pressure_pa=101325.0,
                        pressure_override_pa=101325.0 if mode == "fixed" else None,
                        analysis_clock_mode=clock,
                        local_timezone_name="Europe/Vienna",
                        standard_utc_offset_hours=1.0,
                    )
                    results[key, name] = frame
                    case["clocks"][name] = {
                        "statistics": _frame_evidence(frame),
                        "physical_closure": _closure(frame),
                    }
            output["cases"][key] = case
        full = results["long", LOCAL_CIVIL_TIME + "_measured"]
        short = results["short", LOCAL_CIVIL_TIME + "_measured"]
        subset = full.loc[short.index]
        output["overlap_civil_clock_equal"] = bool(subset.index.equals(short.index))
        output["max_overlap_differences"] = {
            col: float(np.nanmax(np.abs(
                subset[col].to_numpy(dtype=float) -
                short[col].to_numpy(dtype=float)
            ))) for col in COLUMNS
        }
        output["status"] = "complete"
    except Exception as exc:
        output["status"] = "failed"
        output["exception"] = repr(exc)
        output["traceback"] = traceback.format_exc()[-8000:]
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "status": output["status"],
        "supported_fields_count": len(output.get("supported_fields", [])),
        "cases": {k: {"rows": v["source"]["rows"],
                      "request_batch_count": v["request_batch_count"],
                      "closure": {name: entry["physical_closure"] for name, entry in v["clocks"].items()}}
                  for k, v in output["cases"].items()},
        "max_overlap_differences": output.get("max_overlap_differences"),
        "exception": output.get("exception"),
    }, indent=2), flush=True)
    return 0 if output["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
