"""GeoSphere Austria quality-checked 10-minute station-data adapter.

The adapter targets the public historical ``klima-v2-10min`` resource and
terminates at :class:`CanonicalClimateDataset`.  It intentionally does not
pretend measured observations are EPW data: real UTC timestamps, station
identity, provider cadence and provenance remain explicit.

Network access is restricted to the official GeoSphere Austria Dataset API.
Product tests exercise parsing and normalization with fixed fixtures and do not
require internet access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode, urlparse

import pandas as pd
import requests

from .climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
    build_canonical_dataset,
)


GEOSPHERE_API_HOST = "dataset.api.hub.geosphere.at"
GEOSPHERE_API_BASE = f"https://{GEOSPHERE_API_HOST}/v1"
GEOSPHERE_RESOURCE_ID = "klima-v2-10min"
GEOSPHERE_ENDPOINT = f"{GEOSPHERE_API_BASE}/station/historical/{GEOSPHERE_RESOURCE_ID}"
GEOSPHERE_METADATA_ENDPOINT = f"{GEOSPHERE_ENDPOINT}/metadata"
GEOSPHERE_DATASET_PAGE = "https://data.hub.geosphere.at/en/dataset/klima-v2-10min"
GEOSPHERE_DOI = "https://doi.org/10.60669/8fya-7x87"
GEOSPHERE_LICENSE = "Creative Commons Attribution 4.0 International"
GEOSPHERE_NATIVE_INTERVAL_MINUTES = 10

# The official API limit is larger, but a lower local hard cap keeps public app
# requests bounded and leaves margin for provider-side changes and null values.
MAX_REQUEST_DATAPOINTS = 200_000
# Normal planning deliberately stays below the hard cap. Long public requests
# are more reliable as moderately sized batches, while adaptive splitting below
# handles occasional provider-side slow responses without restarting the load.
DEFAULT_BATCH_DATAPOINTS = 100_000
MAX_RESPONSE_BYTES = 24 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60
MAX_TRANSIENT_ATTEMPTS = 2
RETRY_BACKOFF_BASE_SECONDS = 0.5
MAX_ADAPTIVE_SPLIT_DEPTH = 4
TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
USER_AGENT = "Building-Energy-Tools-Climate-Analyzer/0.1 GeoSphere-adapter"


@dataclass(frozen=True)
class GeoSphereStation:
    station_id: str
    name: str
    latitude: float
    longitude: float
    elevation_m: float | None = None
    state: str = ""
    valid_from: str = ""
    valid_to: str = ""
    station_type: str = ""
    is_active: bool | None = None
    has_global_radiation: bool | None = None
    has_sunshine: bool | None = None


@dataclass(frozen=True)
class GeoSphereParameter:
    name: str
    long_name: str
    unit: str
    description: str = ""


@dataclass(frozen=True)
class ProviderFieldSpec:
    provider_name: str
    canonical_name: str
    expected_units: tuple[str, ...]
    scale: float = 1.0
    description: str = ""


# The v2 parameter names below are from the provider metadata. Unit validation
# is part of the contract so a future provider semantic change fails closed.
# Radiation values are 10-minute mean irradiance [W/m²] and are converted to
# interval irradiation [Wh/m²] for the canonical extensive-energy variables.
_PROVIDER_FIELD_SPECS: tuple[ProviderFieldSpec, ...] = (
    ProviderFieldSpec("tl", "dry_bulb_temperature_c", ("°c", "c", "degc"), description="Lufttemperatur 2m"),
    ProviderFieldSpec("tlmin", "dry_bulb_temperature_min_c", ("°c", "c", "degc"), description="Lufttemperatur 2m Minimalwert"),
    ProviderFieldSpec("tlmax", "dry_bulb_temperature_max_c", ("°c", "c", "degc"), description="Lufttemperatur 2m Maximalwert"),
    ProviderFieldSpec("tb10", "ground_temperature_0_10m_c", ("°c", "c", "degc"), description="Bodentemperatur 10 cm"),
    ProviderFieldSpec("tb20", "ground_temperature_0_20m_c", ("°c", "c", "degc"), description="Bodentemperatur 20 cm"),
    ProviderFieldSpec("tb50", "ground_temperature_0_50m_c", ("°c", "c", "degc"), description="Bodentemperatur 50 cm"),
    ProviderFieldSpec("rf", "relative_humidity_pct", ("%",), description="Relative Feuchte"),
    ProviderFieldSpec("p", "atmospheric_station_pressure_pa", ("hpa",), scale=100.0, description="Luftdruck"),
    ProviderFieldSpec("ffam", "wind_speed_m_s", ("m/s", "m s-1", "m s^-1"), description="Windgeschwindigkeit 10m, arithmetischer Mittelwert"),
    ProviderFieldSpec("dd", "wind_direction_deg", ("°", "deg", "degree"), description="Windrichtung"),
    ProviderFieldSpec("ffx", "wind_gust_speed_m_s", ("m/s", "m s-1", "m s^-1"), description="Maximale Windgeschwindigkeit (Spitzenböe)"),
    ProviderFieldSpec("ddx", "wind_gust_direction_deg", ("°", "deg", "degree"), description="Windrichtung zur Spitzenböe"),
    ProviderFieldSpec("rr", "liquid_precipitation_depth_mm", ("mm",), description="Niederschlagssumme"),
    ProviderFieldSpec("rrm", "precipitation_duration_min", ("min",), description="Niederschlagsdauer"),
    ProviderFieldSpec("sh", "snow_depth_cm", ("cm",), description="Gesamtschneehöhe"),
    ProviderFieldSpec("so", "sunshine_duration_s", ("s",), description="Sonnenscheindauer"),
    ProviderFieldSpec("cglo", "global_horizontal_radiation_wh_m2", ("w/m²", "w/m2", "w m-2", "w m^-2"), scale=GEOSPHERE_NATIVE_INTERVAL_MINUTES / 60.0, description="Globalstrahlung Mittelwert"),
    ProviderFieldSpec("chim", "diffuse_horizontal_radiation_wh_m2", ("w/m²", "w/m2", "w m-2", "w m^-2"), scale=GEOSPHERE_NATIVE_INTERVAL_MINUTES / 60.0, description="Himmelsstrahlung Mittelwert"),
)
FIELD_SPEC_BY_PROVIDER = {item.provider_name: item for item in _PROVIDER_FIELD_SPECS}
FIELD_SPEC_BY_CANONICAL = {item.canonical_name: item for item in _PROVIDER_FIELD_SPECS}
DEFAULT_PROVIDER_PARAMETERS = tuple(item.provider_name for item in _PROVIDER_FIELD_SPECS)
QUALITY_FLAG_COLUMN_PREFIX = "quality_flag__"
QUALITY_FLAG_PROVIDER_NAMES = frozenset(f"{name}_flag" for name in FIELD_SPEC_BY_PROVIDER)
SUPPORTED_QUERY_PARAMETERS = frozenset(FIELD_SPEC_BY_PROVIDER) | QUALITY_FLAG_PROVIDER_NAMES


def quality_flag_column(provider_name: str) -> str:
    return f"{QUALITY_FLAG_COLUMN_PREFIX}{str(provider_name).strip()}"


def provider_parameters_with_quality_flags(
    metadata: Mapping[str, Any],
    provider_parameters: Iterable[str],
) -> tuple[str, ...]:
    """Return selected physical parameters plus their live provider quality flags.

    Flags are requested only when the live metadata exposes the exact matching
    ``<parameter>_flag`` field with unit ``code``. They remain native diagnostic
    metadata and are never promoted to physical canonical variables.
    """
    parameters = parse_parameters(metadata)
    result: list[str] = []
    for name in dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()):
        if name not in FIELD_SPEC_BY_PROVIDER:
            raise ValueError(f"Unsupported GeoSphere physical parameter: {name}")
        result.append(name)
        flag_name = f"{name}_flag"
        flag = parameters.get(flag_name)
        if flag is None:
            continue
        if _normalise_unit(flag.unit) != "code":
            raise ValueError(
                f"GeoSphere quality flag '{flag_name}' unit changed: expected 'code', got '{_normalise_unit(flag.unit)}'."
            )
        result.append(flag_name)
    return tuple(result)


def _normalise_unit(unit: object) -> str:
    text = str(unit or "").strip().lower()
    return text.replace(" ", " ").replace("℃", "°c")


def _validate_official_url(url: str) -> str:
    """Accept only HTTPS URLs on the official Dataset API host."""
    parsed = urlparse(str(url).strip())
    if parsed.scheme.lower() != "https":
        raise ValueError("GeoSphere API requests must use HTTPS.")
    if parsed.username or parsed.password:
        raise ValueError("Credential-bearing GeoSphere API URLs are not allowed.")
    if (parsed.hostname or "").rstrip(".").lower() != GEOSPHERE_API_HOST:
        raise ValueError("GeoSphere requests are restricted to dataset.api.hub.geosphere.at.")
    if parsed.port not in (None, 443):
        raise ValueError("Non-standard GeoSphere API ports are not allowed.")
    if not parsed.path.startswith("/v1/"):
        raise ValueError("GeoSphere API requests must use the v1 Dataset API path.")
    return str(url).strip()


def _bounded_get_json(url: str, *, params: Mapping[str, object] | None = None, timeout_s: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Download one bounded JSON response without following external redirects."""
    clean = _validate_official_url(url)
    response = requests.get(
        clean,
        params=params,
        timeout=(10, timeout_s),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        stream=True,
        allow_redirects=False,
    )
    try:
        if 300 <= response.status_code < 400:
            raise ValueError("GeoSphere API redirects are not followed by the public adapter.")
        response.raise_for_status()
        declared = response.headers.get("content-length")
        if declared:
            try:
                if int(declared) > MAX_RESPONSE_BYTES:
                    raise ValueError("GeoSphere response exceeds the local response-size limit.")
            except ValueError as exc:
                if "exceeds" in str(exc):
                    raise
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ValueError("GeoSphere response exceeds the local response-size limit.")
            chunks.append(chunk)
        payload = b"".join(chunks)
        try:
            decoded = response.json() if not payload else requests.models.complexjson.loads(payload.decode("utf-8"))
        except Exception as exc:  # provider boundary: convert parser errors into a stable message
            raise ValueError("GeoSphere API returned invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise ValueError("GeoSphere API JSON root must be an object.")
        return decoded
    finally:
        response.close()


def fetch_metadata(*, timeout_s: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Fetch current metadata for the quality-checked 10-minute resource."""
    return _bounded_get_json(GEOSPHERE_METADATA_ENDPOINT, timeout_s=timeout_s)


def _coalesce(record: Mapping[str, Any], *keys: str, default: object = "") -> object:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return default


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _bool_or_none(value: object) -> bool | None:
    """Return a provider Boolean without inventing truth for missing metadata."""
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def _station_coordinates(record: Mapping[str, Any]) -> tuple[float, float]:
    lat = _float_or_none(_coalesce(record, "lat", "latitude", "y", default=None))
    lon = _float_or_none(_coalesce(record, "lon", "longitude", "x", default=None))
    geometry = record.get("geometry")
    if (lat is None or lon is None) and isinstance(geometry, Mapping):
        coordinates = geometry.get("coordinates")
        if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
            lon = _float_or_none(coordinates[0])
            lat = _float_or_none(coordinates[1])
    if lat is None or lon is None:
        raise ValueError("GeoSphere station metadata are missing latitude/longitude coordinates.")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("GeoSphere station coordinates are outside WGS84 bounds.")
    return lat, lon


def _station_records(metadata: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    stations = metadata.get("stations")
    if isinstance(stations, list):
        return [item for item in stations if isinstance(item, Mapping)]
    if isinstance(stations, Mapping):
        features = stations.get("features")
        if isinstance(features, list):
            records: list[Mapping[str, Any]] = []
            for feature in features:
                if not isinstance(feature, Mapping):
                    continue
                properties = feature.get("properties")
                if isinstance(properties, Mapping):
                    merged = dict(properties)
                    if "geometry" not in merged and isinstance(feature.get("geometry"), Mapping):
                        merged["geometry"] = feature["geometry"]
                    records.append(merged)
            return records
    features = metadata.get("features")
    if isinstance(features, list):
        records = []
        for feature in features:
            if not isinstance(feature, Mapping):
                continue
            properties = feature.get("properties")
            if isinstance(properties, Mapping):
                merged = dict(properties)
                if isinstance(feature.get("geometry"), Mapping):
                    merged["geometry"] = feature["geometry"]
                records.append(merged)
        return records
    return []


def parse_stations(metadata: Mapping[str, Any]) -> list[GeoSphereStation]:
    """Parse station metadata from current Dataset API JSON variants."""
    result: list[GeoSphereStation] = []
    for record in _station_records(metadata):
        station_id = str(_coalesce(record, "id", "station_id", "station", default="")).strip()
        name = str(_coalesce(record, "name", "station_name", default="")).strip()
        if not station_id or not name:
            continue
        lat, lon = _station_coordinates(record)
        elevation = _float_or_none(_coalesce(record, "altitude", "elevation", "elevation_m", default=None))
        result.append(
            GeoSphereStation(
                station_id=station_id,
                name=name,
                latitude=lat,
                longitude=lon,
                elevation_m=elevation,
                state=str(_coalesce(record, "state", "region", default="")).strip(),
                valid_from=str(_coalesce(record, "valid_from", "start", "start_time", default="")).strip(),
                valid_to=str(_coalesce(record, "valid_to", "end", "end_time", default="")).strip(),
                station_type=str(_coalesce(record, "type", "station_type", default="")).strip(),
                is_active=_bool_or_none(record.get("is_active")),
                has_global_radiation=_bool_or_none(record.get("has_global_radiation")),
                has_sunshine=_bool_or_none(record.get("has_sunshine")),
            )
        )
    if not result:
        raise ValueError("GeoSphere metadata contain no usable stations.")
    return result


def parse_parameters(metadata: Mapping[str, Any]) -> dict[str, GeoSphereParameter]:
    """Return provider parameters keyed by exact Dataset API parameter name."""
    raw = metadata.get("parameters")
    if not isinstance(raw, list):
        raise ValueError("GeoSphere metadata contain no parameter list.")
    result: dict[str, GeoSphereParameter] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result[name] = GeoSphereParameter(
            name=name,
            long_name=str(item.get("long_name") or item.get("desc") or "").strip(),
            unit=str(item.get("unit") or "").strip(),
            description=str(item.get("description") or "").strip(),
        )
    if not result:
        raise ValueError("GeoSphere metadata contain no usable parameters.")
    return result


def supported_parameter_mapping(metadata: Mapping[str, Any]) -> dict[str, ProviderFieldSpec]:
    """Resolve supported v2 fields from live metadata with strict unit checks."""
    parameters = parse_parameters(metadata)
    resolved: dict[str, ProviderFieldSpec] = {}
    for provider_name, spec in FIELD_SPEC_BY_PROVIDER.items():
        parameter = parameters.get(provider_name)
        if parameter is None:
            continue
        unit = _normalise_unit(parameter.unit)
        expected = {_normalise_unit(item) for item in spec.expected_units}
        if unit not in expected:
            raise ValueError(
                f"GeoSphere parameter '{provider_name}' unit changed: expected one of {sorted(expected)}, got '{unit}'."
            )
        resolved[provider_name] = spec
    if not resolved:
        raise ValueError("GeoSphere metadata expose none of the supported climate parameters.")
    return resolved


CAPABILITY_RESOURCE_SUPPORTED = "resource-supported"
CAPABILITY_STATION_CONFIRMED = "station-confirmed"
CAPABILITY_STATION_UNAVAILABLE = "station-unavailable"


def station_parameter_capability_index(metadata: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Return O(1) station -> provider-parameter capability lookups.

    GeoSphere currently publishes the full resource parameter list plus a small
    set of station-specific sensor flags.  Only an explicit station flag is
    allowed to disable a parameter.  For fields without station-specific
    metadata, the status remains ``resource-supported`` and actual observations
    for the selected period are still verified after data loading.

    In particular, ``has_global_radiation`` authoritatively qualifies ``cglo``.
    No station-level flag for diffuse radiation is published, so ``chim`` is not
    inferred from the global-radiation flag.
    """
    supported = supported_parameter_mapping(metadata)
    base = {name: CAPABILITY_RESOURCE_SUPPORTED for name in supported}
    result: dict[str, dict[str, str]] = {}
    for record in _station_records(metadata):
        station_id = str(_coalesce(record, "id", "station_id", "station", default="")).strip()
        if not station_id:
            continue
        statuses = dict(base)
        global_radiation = _bool_or_none(record.get("has_global_radiation"))
        if "cglo" in statuses and global_radiation is not None:
            statuses["cglo"] = (
                CAPABILITY_STATION_CONFIRMED if global_radiation else CAPABILITY_STATION_UNAVAILABLE
            )
        result[station_id] = statuses
    if not result:
        raise ValueError("GeoSphere metadata contain no station capability index.")
    return result


def station_parameter_capability_table(metadata: Mapping[str, Any], station_id: str) -> pd.DataFrame:
    """Return a display-ready metadata capability table for one station.

    ``Available`` means selectable from metadata, not guaranteed non-null data
    for every timestamp. Selected-period coverage remains a loaded-data quality
    concern and is intentionally not fabricated from station validity dates.
    """
    station_key = str(station_id).strip()
    index = station_parameter_capability_index(metadata)
    if station_key not in index:
        raise KeyError(f"Unknown GeoSphere station id: {station_key}")
    parameters = parse_parameters(metadata)
    supported = supported_parameter_mapping(metadata)
    statuses = index[station_key]
    rows: list[dict[str, object]] = []
    for provider_name, spec in supported.items():
        parameter = parameters.get(provider_name)
        status = statuses.get(provider_name, CAPABILITY_RESOURCE_SUPPORTED)
        if status == CAPABILITY_STATION_CONFIRMED:
            basis = "Station metadata confirms sensor"
        elif status == CAPABILITY_STATION_UNAVAILABLE:
            basis = "Station metadata reports unavailable"
        else:
            basis = "Resource metadata; period coverage checked after load"
        rows.append(
            {
                "provider": provider_name,
                "canonical": spec.canonical_name,
                "variable": (parameter.long_name if parameter and parameter.long_name else spec.description or spec.canonical_name),
                "unit": parameter.unit if parameter else "",
                "status": status,
                "available": status != CAPABILITY_STATION_UNAVAILABLE,
                "basis": basis,
            }
        )
    return pd.DataFrame(rows)


def station_catalog(metadata: Mapping[str, Any]) -> pd.DataFrame:
    """Return a normalized station table suitable for a later station-map UI."""
    rows = [station.__dict__ for station in parse_stations(metadata)]
    table = pd.DataFrame(rows)
    return table.sort_values(["state", "name", "station_id"], kind="mergesort").reset_index(drop=True)


def estimate_request_datapoints(start: pd.Timestamp, end: pd.Timestamp, parameter_count: int, station_count: int = 1) -> int:
    """Estimate provider request size using the documented cadence formula."""
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if end < start:
        raise ValueError("GeoSphere request end must not be earlier than start.")
    if parameter_count <= 0 or station_count <= 0:
        raise ValueError("GeoSphere requests require at least one parameter and one station.")
    steps = int(math.floor((end - start) / pd.Timedelta(minutes=GEOSPHERE_NATIVE_INTERVAL_MINUTES))) + 1
    return steps * int(parameter_count) * int(station_count)


def _format_utc_query_time(value: pd.Timestamp) -> str:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp.strftime("%Y-%m-%dT%H:%M")


def build_data_query(
    station_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    provider_parameters: Iterable[str],
) -> dict[str, str]:
    """Build a bounded one-station historical query for the v2 10-minute API."""
    station_id = str(station_id).strip()
    if not station_id:
        raise ValueError("GeoSphere station_id must not be empty.")
    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))
    if not parameters:
        raise ValueError("At least one GeoSphere parameter is required.")
    unknown = sorted(set(parameters) - set(SUPPORTED_QUERY_PARAMETERS))
    if unknown:
        raise ValueError(f"Unsupported GeoSphere parameters: {', '.join(unknown)}")
    count = estimate_request_datapoints(pd.Timestamp(start), pd.Timestamp(end), len(parameters), 1)
    if count > MAX_REQUEST_DATAPOINTS:
        raise ValueError(
            f"GeoSphere request would contain about {count:,} datapoints, above the local {MAX_REQUEST_DATAPOINTS:,} limit."
        )
    return {
        "parameters": ",".join(parameters),
        "station_ids": station_id,
        "start": _format_utc_query_time(pd.Timestamp(start)),
        "end": _format_utc_query_time(pd.Timestamp(end)),
    }


def plan_data_queries(
    station_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    provider_parameters: Iterable[str],
    *,
    max_datapoints: int = DEFAULT_BATCH_DATAPOINTS,
) -> list[dict[str, str]]:
    """Split one inclusive station interval into bounded 10-minute requests.

    GeoSphere request size scales with ``timestamps × parameters × stations``.
    The public app requests one station at a time, so this planner partitions a
    long interval along the time axis. Adjacent batches are separated by exactly
    one native 10-minute interval: the first timestamp of a new batch is the
    timestamp after the previous batch's inclusive end. No overlap or synthetic
    interpolation is introduced.
    """
    station_id = str(station_id).strip()
    if not station_id:
        raise ValueError("GeoSphere station_id must not be empty.")
    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))
    if not parameters:
        raise ValueError("At least one GeoSphere parameter is required.")
    unknown = sorted(set(parameters) - set(SUPPORTED_QUERY_PARAMETERS))
    if unknown:
        raise ValueError(f"Unsupported GeoSphere parameters: {', '.join(unknown)}")
    if int(max_datapoints) <= 0:
        raise ValueError("GeoSphere batch datapoint limit must be positive.")
    if int(max_datapoints) > MAX_REQUEST_DATAPOINTS:
        raise ValueError(
            f"GeoSphere batch datapoint limit must not exceed the local hard cap of {MAX_REQUEST_DATAPOINTS:,}."
        )

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if end_ts < start_ts:
        raise ValueError("GeoSphere request end must not be earlier than start.")

    max_steps = int(max_datapoints) // len(parameters)
    if max_steps < 1:
        raise ValueError("GeoSphere batch datapoint limit is too small for the selected parameter set.")

    interval = pd.Timedelta(minutes=GEOSPHERE_NATIVE_INTERVAL_MINUTES)
    queries: list[dict[str, str]] = []
    cursor = start_ts
    while cursor <= end_ts:
        batch_end = min(end_ts, cursor + interval * (max_steps - 1))
        query = build_data_query(station_id, cursor, batch_end, parameters)
        if estimate_request_datapoints(cursor, batch_end, len(parameters), 1) > int(max_datapoints):
            raise RuntimeError("Internal GeoSphere batch planner exceeded its datapoint limit.")
        queries.append(query)
        cursor = batch_end + interval
    return queries


def _query_reference(query: Mapping[str, str]) -> str:
    return f"{GEOSPHERE_ENDPOINT}?{urlencode(dict(query))}"


def _http_status_from_exception(exc: BaseException) -> int | None:
    if not isinstance(exc, requests.HTTPError):
        return None
    response = getattr(exc, "response", None)
    try:
        return int(response.status_code) if response is not None else None
    except (TypeError, ValueError):
        return None


def _is_transient_provider_error(exc: BaseException) -> bool:
    """Classify only retry-safe transport/provider failures as transient."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError)):
        return True
    status = _http_status_from_exception(exc)
    return status in TRANSIENT_HTTP_STATUS_CODES if status is not None else False


def _is_response_size_error(exc: BaseException) -> bool:
    return isinstance(exc, ValueError) and "response exceeds the local response-size limit" in str(exc)


def _split_data_query(query: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]] | None:
    """Bisect one inclusive query on the native 10-minute grid without overlap."""
    parameters = tuple(item for item in str(query.get("parameters", "")).split(",") if item)
    station_id = str(query.get("station_ids", "")).strip()
    if not station_id or not parameters:
        raise ValueError("GeoSphere query is missing station or parameter identity.")
    start = pd.Timestamp(str(query.get("start", "")), tz="UTC")
    end = pd.Timestamp(str(query.get("end", "")), tz="UTC")
    interval = pd.Timedelta(minutes=GEOSPHERE_NATIVE_INTERVAL_MINUTES)
    steps = int(math.floor((end - start) / interval)) + 1
    if steps <= 1:
        return None
    left_steps = max(1, steps // 2)
    left_end = start + interval * (left_steps - 1)
    right_start = left_end + interval
    if right_start > end:
        return None
    return (
        build_data_query(station_id, start, left_end, parameters),
        build_data_query(station_id, right_start, end, parameters),
    )


GeoSphereProgressCallback = Callable[[Mapping[str, object]], None]


def _emit_progress(
    progress_callback: GeoSphereProgressCallback | None,
    *,
    event: str,
    completed_batches: int,
    total_batches: int,
    batch_number: int,
    query: Mapping[str, str],
    attempt: int | None = None,
    split_depth: int = 0,
) -> None:
    """Emit best-effort transport progress without affecting data loading.

    Progress is observational only. A UI callback failure must never alter the
    provider request, scientific data, retry policy or fail-closed behavior.
    The denominator is the original set of planned root batches; adaptive child
    requests remain inside the currently active root batch.
    """
    if progress_callback is None:
        return
    payload: dict[str, object] = {
        "event": str(event),
        "completed_batches": int(completed_batches),
        "total_batches": int(total_batches),
        "batch_number": int(batch_number),
        "split_depth": int(split_depth),
        "start": str(query.get("start", "")),
        "end": str(query.get("end", "")),
    }
    if attempt is not None:
        payload["attempt"] = int(attempt)
    try:
        progress_callback(payload)
    except Exception:
        # Rendering/status reporting is deliberately non-critical.
        return


def _fetch_query_with_resilience(
    query: Mapping[str, str],
    *,
    timeout_s: int,
    split_depth: int = 0,
    progress_callback: GeoSphereProgressCallback | None = None,
    root_batch_number: int = 1,
    root_batch_count: int = 1,
    completed_root_batches: int = 0,
) -> list[tuple[dict[str, Any], dict[str, str]]]:
    """Fetch one planned query, retrying transient failures and splitting only that batch.

    Permanent HTTP 4xx failures, redirects, invalid JSON and malformed provider
    payloads are not retried or hidden. A timeout/connection/429/5xx failure is
    retried once at the same size; if it still fails, the failing query is
    bisected on the native cadence and each child is attempted independently.
    Deterministic local response-size failures skip the same-size retry and go
    directly to adaptive splitting.
    """
    normalized_query = {str(key): str(value) for key, value in query.items()}
    last_error: BaseException | None = None
    for attempt in range(1, MAX_TRANSIENT_ATTEMPTS + 1):
        try:
            payload = _bounded_get_json(GEOSPHERE_ENDPOINT, params=normalized_query, timeout_s=timeout_s)
            return [(payload, normalized_query)]
        except Exception as exc:
            last_error = exc
            transient = _is_transient_provider_error(exc)
            size_error = _is_response_size_error(exc)
            if not transient and not size_error:
                raise
            if size_error:
                break
            if attempt < MAX_TRANSIENT_ATTEMPTS:
                _emit_progress(
                    progress_callback,
                    event="retry",
                    completed_batches=completed_root_batches,
                    total_batches=root_batch_count,
                    batch_number=root_batch_number,
                    query=normalized_query,
                    attempt=attempt + 1,
                    split_depth=split_depth,
                )
                time.sleep(RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                continue
            break

    if split_depth >= MAX_ADAPTIVE_SPLIT_DEPTH:
        raise RuntimeError(
            f"GeoSphere batch failed after retries and {split_depth} adaptive split level(s): "
            f"{normalized_query.get('start')} → {normalized_query.get('end')}."
        ) from last_error

    children = _split_data_query(normalized_query)
    if children is None:
        raise RuntimeError(
            f"GeoSphere single-interval batch failed after retries: "
            f"{normalized_query.get('start')} → {normalized_query.get('end')}."
        ) from last_error

    _emit_progress(
        progress_callback,
        event="split",
        completed_batches=completed_root_batches,
        total_batches=root_batch_count,
        batch_number=root_batch_number,
        query=normalized_query,
        split_depth=split_depth + 1,
    )
    completed: list[tuple[dict[str, Any], dict[str, str]]] = []
    for child in children:
        completed.extend(
            _fetch_query_with_resilience(
                child,
                timeout_s=timeout_s,
                split_depth=split_depth + 1,
                progress_callback=progress_callback,
                root_batch_number=root_batch_number,
                root_batch_count=root_batch_count,
                completed_root_batches=completed_root_batches,
            )
        )
    return completed


def fetch_station_provider_frame(
    *,
    station_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    provider_parameters: Iterable[str],
    timeout_s: int = DEFAULT_TIMEOUT_SECONDS,
    progress_callback: GeoSphereProgressCallback | None = None,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Fetch and concatenate resilient bounded batches for one historical interval.

    Missing observations remain missing. Successful batches are retained when a
    neighbouring batch times out; only the failing batch is retried/split.
    Structural corruption remains fail-closed: duplicate timestamps, an empty
    aggregate response, malformed payloads or permanent provider errors are not
    silently repaired or interpolated.
    """
    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))
    queries = plan_data_queries(station_id, start, end, parameters)
    frames: list[pd.DataFrame] = []
    references: list[str] = []
    total_batches = len(queries)
    for batch_number, query in enumerate(queries, start=1):
        _emit_progress(
            progress_callback,
            event="batch_start",
            completed_batches=batch_number - 1,
            total_batches=total_batches,
            batch_number=batch_number,
            query=query,
        )
        completed = _fetch_query_with_resilience(
            query,
            timeout_s=timeout_s,
            progress_callback=progress_callback,
            root_batch_number=batch_number,
            root_batch_count=total_batches,
            completed_root_batches=batch_number - 1,
        )
        for payload, successful_query in completed:
            frames.append(parse_station_data_response(payload, station_id, parameters))
            references.append(_query_reference(successful_query))
        _emit_progress(
            progress_callback,
            event="batch_complete",
            completed_batches=batch_number,
            total_batches=total_batches,
            batch_number=batch_number,
            query=query,
        )

    if not frames:
        raise ValueError("GeoSphere batching produced no requests.")
    combined = pd.concat(frames, axis=0)
    if combined.empty:
        raise ValueError("GeoSphere returned no timestamps for the selected interval.")
    if combined.index.has_duplicates:
        duplicate_count = int(combined.index.duplicated(keep=False).sum())
        raise ValueError(f"GeoSphere batched response contains {duplicate_count} duplicate timestamps.")
    combined = combined.sort_index(kind="mergesort")
    _emit_progress(
        progress_callback,
        event="load_complete",
        completed_batches=total_batches,
        total_batches=total_batches,
        batch_number=total_batches,
        query=queries[-1],
    )
    return combined, tuple(references)


def _feature_station_id(feature: Mapping[str, Any]) -> str:
    properties = feature.get("properties")
    if not isinstance(properties, Mapping):
        return ""
    station = properties.get("station")
    if isinstance(station, Mapping):
        return str(_coalesce(station, "id", "station_id", default="")).strip()
    return str(station or properties.get("station_id") or "").strip()


def parse_station_data_response(
    payload: Mapping[str, Any],
    station_id: str,
    provider_parameters: Iterable[str],
) -> pd.DataFrame:
    """Parse the Dataset API station JSON response into provider-named columns."""
    timestamps = payload.get("timestamps")
    features = payload.get("features")
    if not isinstance(timestamps, list) or not isinstance(features, list):
        raise ValueError("GeoSphere station response is missing timestamps/features.")
    index = pd.to_datetime(timestamps, utc=True, errors="coerce")
    if index.isna().any():
        raise ValueError("GeoSphere station response contains invalid timestamps.")
    if pd.DatetimeIndex(index).has_duplicates:
        raise ValueError("GeoSphere station response contains duplicate timestamps.")

    wanted = str(station_id).strip()
    candidates = [feature for feature in features if isinstance(feature, Mapping)]
    feature = next((item for item in candidates if _feature_station_id(item) == wanted), None)
    if feature is None and len(candidates) == 1:
        feature = candidates[0]
    if feature is None:
        raise ValueError(f"GeoSphere response does not contain station {wanted}.")
    properties = feature.get("properties")
    if not isinstance(properties, Mapping):
        raise ValueError("GeoSphere station feature has no properties object.")
    parameters = properties.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("GeoSphere station feature has no parameters object.")

    frame = pd.DataFrame(index=pd.DatetimeIndex(index, name="timestamp"))
    for name in provider_parameters:
        entry = parameters.get(name)
        if not isinstance(entry, Mapping):
            frame[name] = pd.NA
            continue
        data = entry.get("data")
        if not isinstance(data, list):
            frame[name] = pd.NA
            continue
        if len(data) != len(frame):
            raise ValueError(
                f"GeoSphere parameter '{name}' has {len(data)} values for {len(frame)} timestamps."
            )
        frame[name] = pd.to_numeric(pd.Series(data, index=frame.index), errors="coerce")
    return frame


def provider_frame_to_canonical(
    provider_frame: pd.DataFrame,
    mapping: Mapping[str, ProviderFieldSpec],
) -> pd.DataFrame:
    """Convert supported provider quantities and units to canonical columns."""
    canonical = pd.DataFrame(index=provider_frame.index.copy())
    for provider_name, spec in mapping.items():
        if provider_name not in provider_frame.columns:
            continue
        values = pd.to_numeric(provider_frame[provider_name], errors="coerce")
        canonical[spec.canonical_name] = values * float(spec.scale)
        flag_name = f"{provider_name}_flag"
        if flag_name in provider_frame.columns:
            canonical[quality_flag_column(provider_name)] = pd.to_numeric(
                provider_frame[flag_name], errors="coerce"
            )
    if canonical.empty:
        raise ValueError("GeoSphere response produced no supported canonical climate variables.")
    return canonical


def build_canonical_station_dataset(
    *,
    station: GeoSphereStation,
    provider_frame: pd.DataFrame,
    mapping: Mapping[str, ProviderFieldSpec],
    request_reference: str = "",
    retrieval_time_utc: str | None = None,
    request_count: int = 1,
) -> CanonicalClimateDataset:
    """Build a historical 10-minute canonical dataset for one station."""
    canonical = provider_frame_to_canonical(provider_frame, mapping)
    temporal = ClimateTemporalMetadata(
        native_interval_minutes=GEOSPHERE_NATIVE_INTERVAL_MINUTES,
        calendar_mode="historical",
        timezone_name="UTC",
        interval_semantics="unknown",
    )
    location = ClimateLocation(
        latitude=station.latitude,
        longitude=station.longitude,
        elevation_m=station.elevation_m,
        city=station.name,
        state=station.state,
        country="Austria",
        station_id=station.station_id,
    )
    provenance = ClimateProvenance(
        provider="GeoSphere Austria",
        dataset="klima-v2-10min — quality-checked station data for Austria",
        source_format="Dataset API JSON",
        source_name=f"GeoSphere station {station.station_id} ({station.name})",
        source_reference=request_reference or GEOSPHERE_DATASET_PAGE,
        provider_station_id=station.station_id,
        retrieval_time_utc=retrieval_time_utc or datetime.now(timezone.utc).isoformat(),
        notes=(
            f"License: CC BY 4.0 ({GEOSPHERE_LICENSE})",
            f"Dataset DOI: {GEOSPHERE_DOI}",
            "Provider timestamps are retained as real UTC historical timestamps.",
            "10-minute mean radiation in W/m² is converted to interval irradiation in Wh/m².",
            f"Historical interval retrieved in {int(request_count)} bounded Dataset API request batch(es).",
        ),
    )
    return build_canonical_dataset(
        climate_id=f"geosphere:{GEOSPHERE_RESOURCE_ID}:{station.station_id}",
        display_name=f"{station.name} — GeoSphere 10 min",
        data=canonical,
        location=location,
        temporal=temporal,
        provenance=provenance,
    )


def fetch_station_dataset(
    *,
    station: GeoSphereStation,
    start: pd.Timestamp,
    end: pd.Timestamp,
    metadata: Mapping[str, Any] | None = None,
    canonical_variables: Iterable[str] | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_SECONDS,
    progress_callback: GeoSphereProgressCallback | None = None,
) -> CanonicalClimateDataset:
    """Fetch one bounded station interval and return canonical historical data."""
    metadata_payload = dict(metadata) if metadata is not None else fetch_metadata(timeout_s=timeout_s)
    supported = supported_parameter_mapping(metadata_payload)
    if canonical_variables is None:
        selected = dict(supported)
    else:
        requested = tuple(dict.fromkeys(str(item).strip() for item in canonical_variables if str(item).strip()))
        selected = {}
        for canonical_name in requested:
            spec = FIELD_SPEC_BY_CANONICAL.get(canonical_name)
            if spec is None:
                raise ValueError(f"Canonical variable '{canonical_name}' is not supported by the GeoSphere adapter.")
            if spec.provider_name not in supported:
                raise ValueError(
                    f"GeoSphere metadata do not currently expose required parameter '{spec.provider_name}'."
                )
            selected[spec.provider_name] = spec
    query_parameters = provider_parameters_with_quality_flags(metadata_payload, selected.keys())
    provider_frame, request_references = fetch_station_provider_frame(
        station_id=station.station_id,
        start=start,
        end=end,
        provider_parameters=query_parameters,
        timeout_s=timeout_s,
        progress_callback=progress_callback,
    )
    dataset = build_canonical_station_dataset(
        station=station,
        provider_frame=provider_frame,
        mapping=selected,
        request_reference="\n".join(request_references),
        request_count=len(request_references),
    )
    dataset.data.attrs["canonical_requested_start"] = pd.Timestamp(start).isoformat()
    dataset.data.attrs["canonical_requested_end"] = pd.Timestamp(end).isoformat()
    return dataset
