from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "climate_analyzer"
sys.path.insert(0, str(TOOL))

from epw_climate_analyzer.geosphere import (  # noqa: E402
    GEOSPHERE_RESOURCE_ID,
    fetch_metadata,
    fetch_station_dataset,
    parse_stations,
    supported_parameter_mapping,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame  # noqa: E402
from epw_climate_analyzer.historical_capabilities import (  # noqa: E402
    available_historical_pages,
    historical_coverage_summary,
)
from epw_climate_analyzer.precipitation import (  # noqa: E402
    occurrence_hours,
    occurrence_records,
    precipitation_summary,
)

START = pd.Timestamp("2025-01-15T06:00:00Z")
END = pd.Timestamp("2025-01-15T07:00:00Z")


def station_valid_on(station, when: pd.Timestamp) -> bool:
    start = pd.to_datetime(station.valid_from, utc=True, errors="coerce")
    end = pd.to_datetime(station.valid_to, utc=True, errors="coerce")
    if pd.notna(start) and when < start:
        return False
    if pd.notna(end) and when > end:
        return False
    return True


def numeric_count(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").notna().sum())


def fetch_first_numeric(stations, canonical_variable: str, *, preferred_id: str | None = None):
    ordered = list(stations)
    if preferred_id:
        ordered.sort(key=lambda s: (s.station_id != preferred_id, -(s.elevation_m or -9999.0)))
    else:
        ordered.sort(key=lambda s: -(s.elevation_m or -9999.0))
    errors: list[str] = []
    canonical_column = canonical_variable
    for station in ordered[:40]:
        if not station_valid_on(station, START):
            continue
        try:
            dataset = fetch_station_dataset(
                station=station,
                start=START,
                end=END,
                metadata=metadata,
                canonical_variables=[canonical_variable],
            )
        except Exception as exc:
            errors.append(f"{station.station_id}:{type(exc).__name__}")
            continue
        if numeric_count(dataset.data, canonical_column) > 0:
            return station, dataset, errors
    raise RuntimeError(
        f"No live station with numeric {canonical_variable} observations was found in the bounded candidate set; "
        f"errors={errors[:10]}"
    )


metadata = fetch_metadata()
supported = supported_parameter_mapping(metadata)
assert "rr" in supported, sorted(supported)
assert "sh" in supported, sorted(supported)
stations = parse_stations(metadata)
assert len(stations) >= 500, len(stations)

rr_station, rr_dataset, rr_errors = fetch_first_numeric(
    stations,
    "liquid_precipitation_depth_mm",
    preferred_id="16413",
)
rr_frame = prepare_historical_analysis_frame(rr_dataset, include_psychrometrics=False)
rr_pages = available_historical_pages(rr_frame)
assert "Precipitation and Snow" in rr_pages, rr_pages
rr_series = pd.to_numeric(rr_frame["liquid_precipitation_depth_mm"], errors="coerce")
rr_expected_records = int((rr_series >= 0.1).sum())
rr_records_table = occurrence_records(rr_frame, "liquid_precipitation_depth_mm", 0.1, "Daily")
rr_observed_records = int(round(float(rr_records_table["records"].sum())))
assert rr_observed_records == rr_expected_records, (rr_observed_records, rr_expected_records)

sh_station, sh_dataset, sh_errors = fetch_first_numeric(stations, "snow_depth_cm")
sh_frame = prepare_historical_analysis_frame(sh_dataset, include_psychrometrics=False)
sh_pages = available_historical_pages(sh_frame)
assert "Precipitation and Snow" in sh_pages, sh_pages
sh_series = pd.to_numeric(sh_frame["snow_depth_cm"], errors="coerce")
sh_positive_records = int((sh_series > 0.0).sum())
sh_expected_hours = sh_positive_records / 6.0
sh_hours_table = occurrence_hours(sh_frame, "snow_depth_cm", 0.0, "Daily", inclusive=False)
sh_observed_hours = float(sh_hours_table["hours"].sum())
assert abs(sh_observed_hours - sh_expected_hours) < 1e-12, (sh_observed_hours, sh_expected_hours)
sh_summary = precipitation_summary(sh_frame)
assert abs(float(sh_summary["snow_cover_hours"] or 0.0) - sh_expected_hours) < 1e-12

result = {
    "resource": GEOSPHERE_RESOURCE_ID,
    "live_station_count": len(stations),
    "supported_parameters": sorted(supported),
    "interval": {"start": START.isoformat(), "end": END.isoformat()},
    "precipitation": {
        "station_id": rr_station.station_id,
        "station_name": rr_station.name,
        "rows": len(rr_frame),
        "numeric_records": numeric_count(rr_frame, "liquid_precipitation_depth_mm"),
        "threshold_records_ge_0_1_mm": rr_observed_records,
        "pages": list(rr_pages),
        "coverage": historical_coverage_summary(rr_frame),
        "request_reference": rr_dataset.provenance.source_reference,
        "candidate_fetch_errors": rr_errors,
    },
    "snow": {
        "station_id": sh_station.station_id,
        "station_name": sh_station.name,
        "elevation_m": sh_station.elevation_m,
        "rows": len(sh_frame),
        "numeric_records": numeric_count(sh_frame, "snow_depth_cm"),
        "positive_snow_records": sh_positive_records,
        "snow_cover_hours": sh_observed_hours,
        "pages": list(sh_pages),
        "coverage": historical_coverage_summary(sh_frame),
        "request_reference": sh_dataset.provenance.source_reference,
        "candidate_fetch_errors": sh_errors,
    },
}

out = ROOT / "artifacts" / "geosphere-0.6.2-live-provider-smoke.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("GEOSPHERE_0_6_2_LIVE_PROVIDER_SMOKE=" + json.dumps(result, ensure_ascii=True, separators=(",", ":")))
