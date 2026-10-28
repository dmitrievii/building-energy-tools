"""A0: bounded source acquisition -> explicit common result -> annual EPW.

ERA5 derivatives delivered by Open-Meteo are a grid background. POWER supplies
only the missing longwave field; its different spatial/processing chain is
retained. No stations, holdout observations, native pressure profiles or C2.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import numpy as np
import pandas as pd

from ..climate_model import ClimateLocation
from .contracts import ClimateResult, FieldDefinition, HistoricalRequest, QualityStatus
from .epw import serialize_epw, validate_weather, write_exclusive


OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"
POWER = "https://power.larc.nasa.gov/api/temporal/hourly/point"
SCHEMA = "IGE_I1_A0_20261025_v1"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
DOCS = {
    "open_meteo": "https://open-meteo.com/en/docs/historical-weather-api",
    "power_time": "https://power.larc.nasa.gov/docs/faqs/other/",
    "power_hourly": "https://power.larc.nasa.gov/docs/services/api/temporal/hourly/",
    "epw": "https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v24.1.0/AuxiliaryPrograms.pdf",
    "provider_RH": "https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Helper/Meteorology.swift",
}

# provider field: canonical field, source unit, target unit, multiplier, operator
MAPPING = {
    "temperature_2m": ("dry_bulb_temperature_c", "°C", "°C", 1, "instant_at_interval_end"),
    "dew_point_2m": ("dew_point_temperature_c", "°C", "°C", 1, "instant_at_interval_end"),
    "relative_humidity_2m": ("relative_humidity_pct", "%", "%", 1, "instant_at_interval_end"),
    "surface_pressure": ("atmospheric_station_pressure_pa", "hPa", "Pa", 100, "instant_at_interval_end"),
    "precipitation": ("total_precipitation_depth_mm", "mm", "mm", 1, "interval_amount"),
    "rain": ("liquid_precipitation_depth_mm", "mm", "mm", 1, "interval_amount"),
    "cloud_cover": ("total_sky_cover_tenths", "%", "tenths", 0.1, "instant_at_interval_end"),
    "shortwave_radiation": ("global_horizontal_radiation_wh_m2", "W/m²", "Wh/m²", 1, "interval_energy"),
    "direct_radiation": ("direct_horizontal_radiation_wh_m2", "W/m²", "Wh/m²", 1, "interval_energy"),
    "diffuse_radiation": ("diffuse_horizontal_radiation_wh_m2", "W/m²", "Wh/m²", 1, "interval_energy"),
    "direct_normal_irradiance": ("direct_normal_radiation_wh_m2", "W/m²", "Wh/m²", 1, "interval_energy"),
    "wind_speed_10m": ("wind_speed_m_s", "m/s", "m/s", 1, "instant_at_interval_end"),
    "wind_direction_10m": ("wind_direction_deg", "°", "deg", 1, "instant_at_interval_end"),
}


def json_bytes(obj: dict | list) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_plan(request: HistoricalRequest) -> dict:
    # POWER is the limiting source. Keep the availability policy versioned;
    # do not silently switch datasets when an early/recent year is requested.
    if not 2002 <= request.year <= 2025:
        raise ValueError("IGE_A0_SOURCE_POLICY_SUPPORTS_2002_THROUGH_2025_ONLY")
    starts, ends = request.utc_starts, request.utc_ends
    met = dict(latitude=f"{request.latitude:.6f}", longitude=f"{request.longitude:.6f}",
        start_date=str(ends[0].date()), end_date=str(ends[-1].date()), hourly=",".join(MAPPING),
        models="era5", elevation="nan", cell_selection="nearest", timezone="GMT", timeformat="iso8601",
        wind_speed_unit="ms", temperature_unit="celsius", precipitation_unit="mm")
    lw = dict(latitude=f"{request.latitude:.6f}", longitude=f"{request.longitude:.6f}",
        start=starts[0].strftime("%Y%m%d"), end=starts[-1].strftime("%Y%m%d"),
        parameters="ALLSKY_SFC_LW_DWN", community="SB", format="JSON", **{"time-standard": "UTC"})
    return {
        "open_meteo": {"url": OPEN_METEO + "?" + urllib.parse.urlencode(met), "parameters": met,
            "provider": "Open-Meteo", "dataset": "fixed ERA5, provider derivatives, not native CDS GRIB"},
        "nasa_power": {"url": POWER + "?" + urllib.parse.urlencode(lw), "parameters": lw,
            "provider": "NASA POWER", "dataset": "hourly surface downwelling longwave; verify sources in response"},
    }


def fetch_original(source_id: str, spec: dict) -> tuple[bytes, dict]:
    parsed = urllib.parse.urlsplit(spec["url"])
    expected = urllib.parse.urlsplit(OPEN_METEO if source_id == "open_meteo" else POWER)
    if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path):
        raise ValueError("IGE_SOURCE_ENDPOINT_NOT_ALLOWED")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError("IGE_SOURCE_REDIRECT_NOT_ALLOWED")

    opener = urllib.request.build_opener(NoRedirect)
    clock = time.monotonic()
    for attempt in range(4):
        try:
            req = urllib.request.Request(spec["url"], headers={"User-Agent": "IGE-I1-A0-research/1", "Accept": "application/json"})
            with opener.open(req, timeout=45) as response:
                if response.headers.get("Content-Length") and int(response.headers["Content-Length"]) > MAX_RESPONSE_BYTES:
                    raise ValueError("IGE_SOURCE_TOO_LARGE")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("IGE_SOURCE_TOO_LARGE")
            receipt = {"id": source_id, "url": spec["url"], "provider": spec["provider"], "dataset": spec["dataset"],
                "retrieved_utc": datetime.now(timezone.utc).isoformat(), "bytes": len(raw), "sha256": digest(raw),
                "http_attempts": attempt + 1, "wall_seconds": time.monotonic() - clock,
                "retry_policy": "max4; only429/5xx/connection/timeout; timeout45s; backoff2/4/8s; no fallback"}
            return raw, receipt
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 3:
                raise
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError("IGE_SOURCE_EXHAUSTED")


def make_source_bundle(request: HistoricalRequest, payloads: dict[str, bytes], receipts: list[dict]) -> bytes:
    manifest = {"schema": SCHEMA, "request": request.to_dict(), "sources": receipts}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in [("manifest.json", json_bytes(manifest)), *[(key + ".json", payloads[key]) for key in sorted(payloads)]]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return stream.getvalue()


def read_source_bundle(path: Path, expected_sha256: str, request: HistoricalRequest) -> tuple[dict[str, bytes], list[dict]]:
    if not expected_sha256 or not path.is_file() or path.stat().st_size > 2 * MAX_RESPONSE_BYTES:
        raise ValueError("IGE_SOURCE_BUNDLE_REQUIRES_PINNED_SHA_AND_BOUNDED_FILE")
    raw = path.read_bytes()
    if digest(raw) != expected_sha256:
        raise ValueError("IGE_SOURCE_BUNDLE_SHA_MISMATCH")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != 3 or set(names) != {"manifest.json", "open_meteo.json", "nasa_power.json"}:
            raise ValueError("IGE_SOURCE_BUNDLE_UNSAFE_DUPLICATE_OR_UNEXPECTED_MEMBERS")
        for info in archive.infolist():
            if info.file_size > MAX_RESPONSE_BYTES or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("IGE_SOURCE_BUNDLE_EXPANDED_SIZE_OR_SYMLINK")
        manifest = json.loads(archive.read("manifest.json"))
        payloads = {key: archive.read(key + ".json") for key in ("open_meteo", "nasa_power")}
    if manifest.get("schema") != SCHEMA or manifest.get("request") != request.to_dict():
        raise ValueError("IGE_SOURCE_BUNDLE_REQUEST_OR_SCHEMA_MISMATCH")
    receipts = manifest.get("sources", [])
    plan = source_plan(request)
    if len(receipts) != 2 or {s["id"] for s in receipts} != set(plan):
        raise ValueError("IGE_SOURCE_BUNDLE_LINEAGE_MISSING")
    for receipt in receipts:
        key = receipt["id"]
        if receipt["url"] != plan[key]["url"] or receipt["sha256"] != digest(payloads[key]) or receipt["bytes"] != len(payloads[key]):
            raise ValueError("IGE_SOURCE_BUNDLE_ORIGINAL_BYTES_OR_REQUEST_CHANGED")
    return payloads, receipts


def _numbers(values: list, n: int, name: str) -> np.ndarray:
    if not isinstance(values, list) or len(values) != n or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("IGE_MISSING_NONFINITE_OR_NONNUMERIC_SOURCE_" + name)
    return np.asarray(values, dtype=float)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    d = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(d)))


def assemble_historical(request: HistoricalRequest, payloads: dict[str, bytes], receipts: list[dict]) -> ClimateResult:
    plan = source_plan(request)
    if len(receipts) != 2 or {r["id"] for r in receipts} != set(plan):
        raise ValueError("IGE_ORIGINAL_SOURCE_RECEIPTS_MISSING")
    for receipt in receipts:
        key = receipt["id"]
        if receipt["url"] != plan[key]["url"] or digest(payloads[key]) != receipt["sha256"] or len(payloads[key]) != receipt["bytes"]:
            raise ValueError("IGE_ORIGINAL_SOURCE_HASH_OR_REQUEST_MISMATCH")
    met, power = (json.loads(payloads[k]) for k in ("open_meteo", "nasa_power"))
    if met.get("error") or met.get("utc_offset_seconds") != 0 or met.get("timezone") not in ("UTC", "GMT"):
        raise ValueError("IGE_OPEN_METEO_ERROR_OR_NON_UTC_TIME")
    start, end = plan["open_meteo"]["parameters"]["start_date"], plan["open_meteo"]["parameters"]["end_date"]
    labels = pd.date_range(start, pd.Timestamp(end) + pd.Timedelta(days=1), inclusive="left", freq="h", tz="UTC")
    expected_labels = labels.strftime("%Y-%m-%dT%H:%M").tolist()
    if met.get("hourly", {}).get("time") != expected_labels:
        raise ValueError("IGE_OPEN_METEO_MISSING_DUPLICATE_REORDERED_OR_SHIFTED_TIME")
    selector = labels.get_indexer(request.utc_ends)
    if np.any(selector < 0):
        raise ValueError("IGE_OPEN_METEO_CROSSYEAR_ENDPOINT_MISSING")
    frame = pd.DataFrame(index=request.utc_starts)
    fields, transformations = {}, []
    for source, (target, source_unit, target_unit, factor, operator) in MAPPING.items():
        if met.get("hourly_units", {}).get(source) != source_unit:
            raise ValueError("IGE_OPEN_METEO_UNIT_CHANGED_" + source)
        frame[target] = _numbers(met["hourly"].get(source), len(labels), source)[selector] * factor
        vertical = "2m above model surface" if source in ("temperature_2m", "dew_point_2m", "relative_humidity_2m") else (
            "10m above model surface" if source.startswith("wind_") else "model surface or atmospheric column as provided")
        definition = "Provider ERA5-derived " + source
        if source == "surface_pressure":
            definition += "; absolute model-surface pressure, never sea-level-reduced pressure; not moved to 2m"
        if source == "relative_humidity_2m":
            definition += "; liquid-water Magnus 17.625/243.04, integer percent; NOT NASA water/ice daily RH"
        if source == "rain":
            definition += "; liquid rain only, excludes snowfall; total precipitation retained separately"
        fields[target] = FieldDefinition(target_unit, operator, "open_meteo", vertical, definition)
        transformations.append({"field": target, "source_field": source, "operation": "unit_and_support_mapping",
            "factor": factor, "source_unit": source_unit, "target_unit": target_unit,
            "time_rule": "instantaneous source at interval end" if operator == "instant_at_interval_end" else "preceding-hour source at interval end",
            "duration_hours": 1, "records": len(frame), "physical_values_adjusted": False})
    header = power.get("header", {})
    if power.get("messages") or header.get("time_standard") != "UTC" or not header.get("sources"):
        raise ValueError("IGE_POWER_ERROR_TIME_STANDARD_OR_SOURCE_METADATA")
    if header["sources"] != ["SYN1DEG"]:
        raise ValueError("IGE_POWER_LONGWAVE_SOURCE_CHAIN_CHANGED_REQUIRES_NEW_POLICY")
    geometry = power.get("geometry", {})
    coordinates = geometry.get("coordinates", [])
    if (geometry.get("type") != "Point" or len(coordinates) < 2
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in coordinates[:2])
            or abs(coordinates[0] - request.longitude) > .02 or abs(coordinates[1] - request.latitude) > .02):
        raise ValueError("IGE_POWER_RESPONSE_WRONG_GEOGRAPHIC_POINT")
    pp = plan["nasa_power"]["parameters"]
    if header.get("start") != pp["start"] or header.get("end") != pp["end"]:
        raise ValueError("IGE_POWER_RESPONSE_DATE_RANGE_MISMATCH")
    units = power.get("parameters", {}).get("ALLSKY_SFC_LW_DWN", {}).get("units")
    if units not in ("W m-2", "W/m^2", "W/m²"):
        raise ValueError("IGE_POWER_LONGWAVE_UNIT_CHANGED")
    series = power.get("properties", {}).get("parameter", {}).get("ALLSKY_SFC_LW_DWN", {})
    power_labels = pd.date_range(datetime.strptime(pp["start"], "%Y%m%d"),
        datetime.strptime(pp["end"], "%Y%m%d") + timedelta(days=1), inclusive="left", freq="h", tz="UTC")
    if set(series) != set(power_labels.strftime("%Y%m%d%H")):
        raise ValueError("IGE_POWER_MISSING_OR_UNEXPECTED_UTC_HOURS")
    lw = _numbers([series[x] for x in request.utc_starts.strftime("%Y%m%d%H")], len(frame), "POWER_LONGWAVE")
    if np.any(lw == header.get("fill_value", -999)):
        raise ValueError("IGE_POWER_LONGWAVE_PROVIDER_FILL_NO_FALLBACK")
    key = "horizontal_infrared_radiation_intensity_wh_m2"
    frame[key] = lw  # W/m2 * 1 hour; POWER labels interval start, unlike Open-Meteo
    fields[key] = FieldDefinition("Wh/m²", "interval_energy", "nasa_power", "surface downward hemispheric flux",
        "POWER original hourly longwave; separate gridded column/processing chain: " + ",".join(header["sources"]))
    transformations.append({"field": key, "operation": "flux_to_interval_energy_and_align_start_label",
        "source_unit": units, "target_unit": "Wh/m²", "duration_hours": 1,
        "POWER_source_label": "interval_start", "EPW_label": "interval_end",
        "records": len(frame), "physical_values_adjusted": False})
    try:
        lat, lon, elevation = (float(met[k]) for k in ("latitude", "longitude", "elevation"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("IGE_PROVIDER_CELL_OR_ELEVATION_PROXY_MISSING") from exc
    if not all(math.isfinite(v) for v in (lat, lon, elevation)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("IGE_INVALID_PROVIDER_CELL_METADATA")
    distance = _haversine(request.latitude, request.longitude, lat, lon)
    if distance > 150:
        raise ValueError("IGE_UNEXPECTED_DISTANT_PROVIDER_CELL")
    diagnostics = {
        "source_scope": "OPEN_METEO_DERIVED_ERA5_NOT_NATIVE_CDS_GRIB",
        "requested_point": [request.latitude, request.longitude], "background_cell": [lat, lon],
        "requested_to_background_distance_km": distance,
        "EPW_location_coordinates": "provider selected cell; requested point retained separately",
        "elevation_m_provider_response_proxy": elevation, "native_model_height_verified": False,
        "site_height_m_requested": request.site_elevation_m, "site_height_used_for_weather_correction": False,
        "provider_downscaling": "DISABLED elevation=nan; nearest cell",
        "pressure_vertical_reference": "absolute model-surface proxy; not collocated with 2m T/RH",
        "pressure_reduced_to_sea_level": False, "pressure_adjusted_to_2m": False,
        "POWER_reported_sources": header["sources"], "POWER_geometry": power.get("geometry"),
        "mixed_source_cross_variable_consistency_qualified": False,
        "specific_humidity_generated": False,
        "humidity_definition_limit": "Provider rounded water-Magnus T/Td/RH retained; no NASA phase operator or exact T-p-q-RH closure claimed",
        "source_row_time_support": {"open_meteo": "instant at end or preceding-hour integral", "nasa_power_LW": "hourly mean, label at start"},
        "IV1_station_observations_opened": False,
        "independent_station_validation": "NOT_RUN", "local_reconstruction_complete": False,
        "future_generator_executed": False,
    }
    result = ClimateResult(request, frame, ClimateLocation(lat, lon, elevation, city=request.label), fields,
        tuple(receipts), tuple(transformations), (),
        QualityStatus("SOURCE_AND_CALENDAR_CHECKS_PASS", "BOUNDS_SCREEN_PENDING",
            "NOT_INDEPENDENTLY_VALIDATED", "RESEARCH_GRID_BACKGROUND_CLI; UI_NOT_CONNECTED"), diagnostics)
    diagnostics["weather_screen"] = validate_weather(result)
    # Return an explicit assessed result; no physical weather values are altered.
    return ClimateResult(request, frame, result.location, fields, tuple(receipts), tuple(transformations), (),
        QualityStatus("SOURCE_AND_CALENDAR_CHECKS_PASS", "BOUNDS_AND_SOURCE_ROUNDING_SCREEN_PASS_WITH_DECLARED_LIMITS",
            "NOT_INDEPENDENTLY_VALIDATED", "RESEARCH_GRID_BACKGROUND_CLI; UI_NOT_CONNECTED"), diagnostics)


def run_historical(request: HistoricalRequest, output: Path, *, source_bundle: Path | None = None,
                   source_bundle_sha256: str | None = None) -> ClimateResult:
    """One callable route. A fresh directory is mandatory, even for a replay."""
    plan = source_plan(request)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    try:
        if source_bundle is None:
            payloads, receipts = {}, []
            for key, spec in plan.items():
                print(f"IGE_A0_ACQUIRE {key}", flush=True)
                raw, receipt = fetch_original(key, spec)
                payloads[key] = raw
                receipts.append(receipt)
            source_zip = make_source_bundle(request, payloads, receipts)
        else:
            payloads, receipts = read_source_bundle(Path(source_bundle), source_bundle_sha256 or "", request)
            source_zip = Path(source_bundle).read_bytes()
        write_exclusive(output / "sources.zip", source_zip)
        result = assemble_historical(request, payloads, receipts)
        epw, epw_report = serialize_epw(result)
        write_exclusive(output / "climate.epw", epw)
        csv_frame = result.data.copy()
        csv_frame.insert(0, "interval_end_utc", request.utc_ends)
        csv_frame.insert(0, "interval_start_local_standard", request.local_starts)
        csv_data = gzip.compress(csv_frame.to_csv(index_label="interval_start_utc", float_format="%.12g").encode(), mtime=0)
        write_exclusive(output / "hourly.csv.gz", csv_data)
        ledger = {"schema": SCHEMA, "physical_adjustments": list(result.adjustments),
            "source_and_unit_transformations": list(result.transformations),
            "export_quantization": [{"field": "total_sky_cover_tenths", "operation": "nearest_whole_tenth",
                "maximum_error_tenths": 0.5, "records": len(result.data)}],
            "missing_values_filled": 0, "opaque_cloud_or_photometry_invented": False}
        write_exclusive(output / "ledger.json", json_bytes(ledger))
        local_frame = result.data.copy()
        local_frame.index = request.local_starts
        monthly = []
        for month, group in local_frame.groupby(local_frame.index.month):
            monthly.append({"month": int(month), "hours": len(group),
                "T_endpoint_sample_mean_c": float(group["dry_bulb_temperature_c"].mean()),
                "T_endpoint_sample_min_c": float(group["dry_bulb_temperature_c"].min()),
                "T_endpoint_sample_max_c": float(group["dry_bulb_temperature_c"].max()),
                "GHI_kWh_m2": float(group["global_horizontal_radiation_wh_m2"].sum() / 1000),
                "liquid_rain_mm": float(group["liquid_precipitation_depth_mm"].sum()),
                "total_precipitation_mm": float(group["total_precipitation_depth_mm"].sum())})
        write_exclusive(output / "monthly_summary.json", json_bytes(monthly))
        canonical = result.to_canonical()
        # Smoke-test the actual existing importer, while preserving historical
        # dates through the direct canonical route above. Existing uploads keep
        # their established typical-year behavior.
        from ..epw_parser import parse_epw
        parsed = parse_epw(output / "climate.epw")
        if len(parsed.data) != len(result.data):
            raise ValueError("IGE_EXISTING_ANALYZER_IMPORT_LOST_ROWS")
        files = {p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
            for p in (output / "sources.zip", output / "climate.epw", output / "hourly.csv.gz", output / "ledger.json", output / "monthly_summary.json")}
        manifest = {"schema": SCHEMA, "request": request.to_dict(), "quality": asdict(result.quality),
            "sources": receipts, "source_bundle_sha256": digest(source_zip),
            "fields": {k: asdict(v) for k, v in result.fields.items()}, "diagnostics": result.diagnostics,
            "EPW": epw_report, "files": files, "documentation": DOCS,
            "canonical_adapter": {"calendar_mode": canonical.temporal.calendar_mode,
                "records": len(canonical.data), "first": canonical.start.isoformat(), "last": canonical.end.isoformat(),
                "state_sample_offset_minutes": 60, "existing_EPW_upload_route_is_typical_year": True},
            "existing_Analyzer_EPW_import_records": len(parsed.data),
            "weather_provider_requests_this_run": sum(r["http_attempts"] for r in receipts) if source_bundle is None else 0,
            "weather_provider_response_bytes_this_run": sum(r["bytes"] for r in receipts) if source_bundle is None else 0,
            "wall_seconds": time.monotonic() - start,
            "implementation_sha256": {p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))},
            "independent_station_accuracy_qualified": False, "production_ready": False,
            "IV1_station_observations_opened": False,
        }
        write_exclusive(output / "manifest.json", json_bytes(manifest))
        return result
    except Exception as exc:
        write_exclusive(output / "failed.json", json_bytes({"schema": SCHEMA, "request": request.to_dict(),
            "status": "BLOCKED_NO_COMPLETE_RESULT", "error": type(exc).__name__ + ": " + str(exc),
            "wall_seconds": time.monotonic() - start, "production_ready": False}))
        raise
