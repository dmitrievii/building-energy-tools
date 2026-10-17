#!/usr/bin/env python3
"""P9.1H1 canonical *measured* tower-temperature QC; NOT an inversion predictor.

The canonical CSV is produced by a separately audited native provider adapter.
No native provider flag mapping, sensor height, or local time is guessed here.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

UTC = dt.timezone.utc
INVERSION_EPS_K = 0.10
DRY_ADIABATIC_APPROX_K_KM = 9.8
SCHEMA = ("timestamp_utc", "height_agl_m", "air_temperature_c", "source_qc")
ACCEPTED_CANONICAL_QC = frozenset({"documented_provider_good"})


def strict_utc(text: str) -> dt.datetime:
    """Timestamp always explicit UTC; no silent CET/CEST or timezone conversion."""
    if not text or not (text.endswith("Z") or text.endswith("+00:00")):
        raise ValueError("P9H1_TIMESTAMP_NOT_EXPLICIT_UTC")
    stamp = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if stamp.utcoffset() != dt.timedelta(0):
        raise ValueError("P9H1_TIMESTAMP_NOT_UTC")
    if stamp.second or stamp.microsecond:
        raise ValueError("P9H1_TIMESTAMP_SUBMINUTE_OR_SECONDS_NOT_SUPPORTED")
    return stamp


def load_canonical_csv(original_bytes: bytes, *, provider_id: str,
                       permitted_heights_m: tuple[float, ...]) -> tuple[list[dict], dict]:
    if not provider_id or not permitted_heights_m or len(set(permitted_heights_m)) < 2:
        raise ValueError("P9H1_PROVIDER_OR_HEIGHT_REGISTRY_MISSING")
    if any(not math.isfinite(x) or not 0.1 <= x <= 250 for x in permitted_heights_m):
        raise ValueError("P9H1_HEIGHTS_INVALID")
    if len(original_bytes) > 50 * 1024 * 1024:
        raise ValueError("P9H1_SOURCE_TOO_LARGE")
    text = original_bytes.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or set(reader.fieldnames) != set(SCHEMA):
        raise ValueError("P9H1_CANONICAL_FIELDS_INCOMPLETE_OR_EXTRA")
    records, seen = [], set()
    qc_hist = defaultdict(int)
    rejected = 0
    for line_number, row in enumerate(reader, 2):
        if any(v is None for v in row.values()):
            raise ValueError("P9H1_TRUNCATED_CANONICAL_ROW")
        stamp = strict_utc(row["timestamp_utc"])
        height = float(row["height_agl_m"])
        if not math.isfinite(height) or not any(abs(height - h) < 1e-6 for h in permitted_heights_m):
            raise ValueError("P9H1_UNREGISTERED_NATIVE_SENSOR_HEIGHT")
        key = (stamp, round(height, 5))
        if key in seen:
            raise ValueError("P9H1_DUPLICATE_SOURCE_TIMESTAMP_AND_HEIGHT")
        seen.add(key)
        qc = row["source_qc"].strip()
        qc_hist[qc] += 1
        if qc not in ACCEPTED_CANONICAL_QC:
            rejected += 1
            continue
        temperature = float(row["air_temperature_c"])
        if not (math.isfinite(temperature) and -90 <= temperature <= 60):
            raise ValueError("P9H1_GOOD_QC_T_OUTSIDE_SANITY_RANGE")
        records.append({"time": stamp, "height_m": height, "temperature_c": temperature})
    records.sort(key=lambda x: (x["time"], x["height_m"]))
    provenance = {
        "provider_id": provider_id,
        "sha256_of_canonical_input_NOT_native_original_file": hashlib.sha256(original_bytes).hexdigest(),
        "n_source_records": len(seen),
        "n_accepted_records": len(records),
        "n_rejected_records": rejected,
        "canonical_QC_histogram": dict(sorted(qc_hist.items())),
        "original_native_provider_file_authenticated": False,
        "source_native_qc_mapping_authenticated": False,
        "time_and_height_assumed_verified_by_upstream_provider_adapter": True,
        "production_epw_ready": False,
    }
    return records, provenance


def synchronous_vertical_pairs(records: list[dict], *, z_low: float, z_high: float) -> list[dict]:
    if not (math.isfinite(z_low) and math.isfinite(z_high) and 1 <= z_high-z_low <= 250):
        raise ValueError("P9H1_VERTICAL_PAIR_HEIGHT_RANGE_INVALID")
    grouped = defaultdict(dict)
    for item in records:
        stamp = item["time"]
        height = item["height_m"]
        if abs(height-z_low) < 1e-6 or abs(height-z_high) < 1e-6:
            if height in grouped[stamp]:
                raise ValueError("P9H1_DUPLICATE_PAIR_TIMESTAMP")
            grouped[stamp][height] = item["temperature_c"]
    pairs = []
    for stamp in sorted(grouped):
        measured = grouped[stamp]
        if z_low not in measured or z_high not in measured:
            continue
        delta = measured[z_high] - measured[z_low]
        gradient = delta / (z_high - z_low) * 1000
        pairs.append({
            "time_utc": stamp,
            "low_m": z_low, "high_m": z_high, "dz_m": z_high-z_low,
            "delta_T_K": delta, "temperature_gradient_K_km": gradient,
            "observed_positive_inversion": delta > INVERSION_EPS_K,
            "observed_neutral_band": abs(delta) <= INVERSION_EPS_K,
            "approx_dry_theta_gradient_K_km_NOT_OBSERVED_THETA":
                gradient + DRY_ADIABATIC_APPROX_K_KM
        })
    return pairs


def hourly_paired_observations(pairs: list[dict], *, cadence_minutes: int) -> list[dict]:
    minimum = {1: 45, 10: 4}.get(cadence_minutes)
    if minimum is None:
        raise ValueError("P9H1_UNREGISTERED_RAW_CADENCE")
    hourly = defaultdict(list)
    for item in pairs:
        t = item["time_utc"]
        if t.minute % cadence_minutes:
            raise ValueError("P9H1_UNEXPECTED_RAW_MEASUREMENT_CADENCE_ALIGNMENT")
        hour = t.replace(minute=0)
        hourly[hour].append(item)
    output = []
    for hour in sorted(hourly):
        items = hourly[hour]
        minutes = [x["time_utc"].minute for x in items]
        if len(minutes) != len(set(minutes)):
            raise ValueError("P9H1_DUPLICATE_TIMESTAMPS_WITHIN_HOUR")
        if len(items) < minimum:
            continue
        dT = statistics.fmean(x["delta_T_K"] for x in items)
        output.append({
            "hour_utc": hour.isoformat(),
            "n_original_simultaneous_pairs": len(items),
            "mean_delta_T_K": dT,
            "mean_gradient_K_km": statistics.fmean(
                x["temperature_gradient_K_km"] for x in items),
            "fraction_subhour_original_inversion":
                statistics.fmean(float(x["observed_positive_inversion"]) for x in items),
            "hourly_inversion_on_mean_threshold": dT > INVERSION_EPS_K,
        })
    return output


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--canonical-csv", required=True)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--native-heights-m", type=float, nargs="+", required=True)
    parser.add_argument("--pair-heights-m", type=float, nargs=2, required=True)
    parser.add_argument("--cadence-minutes", type=int, choices=(1,10), required=True)
    parser.add_argument("--out", required=True)
    args=parser.parse_args()
    p=Path(args.canonical_csv)
    records, provenance=load_canonical_csv(p.read_bytes(), provider_id=args.provider_id,
        permitted_heights_m=tuple(args.native_heights_m))
    pairs=synchronous_vertical_pairs(records,z_low=args.pair_heights_m[0],
                                     z_high=args.pair_heights_m[1])
    hours=hourly_paired_observations(pairs,cadence_minutes=args.cadence_minutes)
    summary={"phase":"P9.1H1_CANONICAL_PROFILE_QC_ONLY",
             "provenance":provenance,
             "pair_heights_agl_m":args.pair_heights_m,
             "n_original_simultaneous_quality_pairs":len(pairs),
             "n_qualified_hours":len(hours),
             "hourly_pairs":hours,
             "near_surface_inversion_model_qualified":False,
             "global_arbitrary_point_weather_qualified":False,
             "production_epw_ready":False}
    target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k not in ("hourly_pairs",)}))


if __name__=="__main__":
    main()
