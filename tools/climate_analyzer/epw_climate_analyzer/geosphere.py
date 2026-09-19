"""GeoSphere Austria historical station-data adapter.

One transport/canonical engine serves multiple quality-checked GeoSphere v2
resources.  Resource-specific knowledge is declarative (cadence, DOI, provider
field names and unit conversions); batching, validation, station parsing,
quality metadata and canonical conversion are shared.

Supported resources:
* ``klima-v2-10min`` — high-resolution quality-checked station observations;
* ``klima-v2-1h`` — long-term quality-checked hourly station observations.

Provider timestamps remain real UTC historical instants.  No GeoSphere dataset
is converted to an EPW typical year.
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
GEOSPHERE_LICENSE = "Creative Commons Attribution 4.0 International"
GEOSPHERE_LOCAL_TIMEZONE = "Europe/Vienna"
GEOSPHERE_STANDARD_UTC_OFFSET_HOURS = 1.0

MAX_REQUEST_DATAPOINTS = 200_000
DEFAULT_BATCH_DATAPOINTS = 100_000
MAX_RESPONSE_BYTES = 24 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60
MAX_TRANSIENT_ATTEMPTS = 2
RETRY_BACKOFF_BASE_SECONDS = 0.5
MAX_ADAPTIVE_SPLIT_DEPTH = 4
TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
USER_AGENT = "Building-Energy-Tools-Climate-Analyzer/0.1 GeoSphere-adapter"
QUALITY_FLAG_COLUMN_PREFIX = "quality_flag__"
QUALITY_CODEBOOK_ATTR = "geosphere_quality_codebooks"
QUALITY_LABEL_ATTR = "geosphere_quality_labels"


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
    code_list_ref: str = ""


@dataclass(frozen=True)
class ProviderFieldSpec:
    provider_name: str
    canonical_name: str
    expected_units: tuple[str, ...]
    scale: float = 1.0
    description: str = ""
    interval_semantics: str = "unknown"


@dataclass(frozen=True)
class GeoSphereResourceSpec:
    resource_id: str
    label: str
    native_interval_minutes: int
    doi: str
    dataset_page: str
    field_specs: tuple[ProviderFieldSpec, ...]
    interval_semantics: str = "mixed-provider-defined"

    @property
    def endpoint(self) -> str:
        return f"{GEOSPHERE_API_BASE}/station/historical/{self.resource_id}"

    @property
    def metadata_endpoint(self) -> str:
        return f"{self.endpoint}/metadata"

    @property
    def field_by_provider(self) -> dict[str, ProviderFieldSpec]:
        return {item.provider_name: item for item in self.field_specs}

    @property
    def field_by_canonical(self) -> dict[str, ProviderFieldSpec]:
        # Resource contracts intentionally expose at most one preferred provider
        # field for each canonical variable.
        return {item.canonical_name: item for item in self.field_specs}

    @property
    def quality_flag_provider_names(self) -> frozenset[str]:
        return frozenset(f"{name}_flag" for name in self.field_by_provider)

    @property
    def supported_query_parameters(self) -> frozenset[str]:
        return frozenset(self.field_by_provider) | self.quality_flag_provider_names


def _radiation_spec(provider_name: str, canonical_name: str, cadence_min: int, description: str) -> ProviderFieldSpec:
    return ProviderFieldSpec(
        provider_name,
        canonical_name,
        ("w/m²", "w/m2", "w m-2", "w m^-2"),
        scale=float(cadence_min) / 60.0,
        description=description,
        interval_semantics="mean irradiance converted to interval irradiation",
    )


def _common_specs(*, cadence_min: int, mean_wind_provider: str) -> tuple[ProviderFieldSpec, ...]:
    return (
        ProviderFieldSpec("tl", "dry_bulb_temperature_c", ("°c", "c", "degc"), description="Lufttemperatur 2m", interval_semantics="provider-defined temperature state/mean"),
        ProviderFieldSpec("tlmin", "dry_bulb_temperature_min_c", ("°c", "c", "degc"), description="Lufttemperatur 2m Minimalwert", interval_semantics="minimum"),
        ProviderFieldSpec("tlmax", "dry_bulb_temperature_max_c", ("°c", "c", "degc"), description="Lufttemperatur 2m Maximalwert", interval_semantics="maximum"),
        ProviderFieldSpec("tb10", "ground_temperature_0_10m_c", ("°c", "c", "degc"), description="Bodentemperatur 10 cm"),
        ProviderFieldSpec("tb20", "ground_temperature_0_20m_c", ("°c", "c", "degc"), description="Bodentemperatur 20 cm"),
        ProviderFieldSpec("tb50", "ground_temperature_0_50m_c", ("°c", "c", "degc"), description="Bodentemperatur 50 cm"),
        ProviderFieldSpec("rf", "relative_humidity_pct", ("%",), description="Relative Feuchte"),
        ProviderFieldSpec("p", "atmospheric_station_pressure_pa", ("hpa",), scale=100.0, description="Luftdruck"),
        ProviderFieldSpec(mean_wind_provider, "wind_speed_m_s", ("m/s", "m s-1", "m s^-1"), description="Windgeschwindigkeit 10m"),
        ProviderFieldSpec("dd", "wind_direction_deg", ("°", "deg", "degree"), description="Windrichtung"),
        ProviderFieldSpec("ffx", "wind_gust_speed_m_s", ("m/s", "m s-1", "m s^-1"), description="Maximale Windgeschwindigkeit (Spitzenböe)", interval_semantics="maximum"),
        ProviderFieldSpec("ddx", "wind_gust_direction_deg", ("°", "deg", "degree"), description="Windrichtung zur Spitzenböe", interval_semantics="paired with maximum gust"),
        ProviderFieldSpec("rr", "liquid_precipitation_depth_mm", ("mm",), description="Niederschlagssumme", interval_semantics="sum"),
        ProviderFieldSpec("rrm", "precipitation_duration_min", ("min",), description="Niederschlagsdauer", interval_semantics="duration"),
        ProviderFieldSpec("sh", "snow_depth_cm", ("cm",), description="Gesamtschneehöhe"),
        ProviderFieldSpec("so", "sunshine_duration_s", ("s",), description="Sonnenscheindauer", interval_semantics="duration"),
        _radiation_spec("cglo", "global_horizontal_radiation_wh_m2", cadence_min, "Globalstrahlung Mittelwert"),
        _radiation_spec("chim", "diffuse_horizontal_radiation_wh_m2", cadence_min, "Himmelsstrahlung Mittelwert"),
    )


GEOSPHERE_RESOURCES: dict[str, GeoSphereResourceSpec] = {
    "klima-v2-10min": GeoSphereResourceSpec(
        resource_id="klima-v2-10min",
        label="GeoSphere climate station data — 10 min",
        native_interval_minutes=10,
        doi="https://doi.org/10.60669/8fya-7x87",
        dataset_page="https://data.hub.geosphere.at/en/dataset/klima-v2-10min",
        field_specs=_common_specs(cadence_min=10, mean_wind_provider="ffam"),
    ),
    "klima-v2-1h": GeoSphereResourceSpec(
        resource_id="klima-v2-1h",
        label="GeoSphere climate station data — 1 h (long-term)",
        native_interval_minutes=60,
        doi="https://doi.org/10.60669/9bdm-yq93",
        dataset_page="https://data.hub.geosphere.at/en/dataset/klima-v2-1h",
        # Hourly v2 metadata use ff for the mean wind-speed series. Every field
        # is still live-metadata gated below, so a future provider change fails
        # closed instead of silently reinterpreting another parameter.
        field_specs=_common_specs(cadence_min=60, mean_wind_provider="ff"),
    ),
}

# Backward-compatible default-resource constants used by existing callers/tests.
GEOSPHERE_RESOURCE_ID = "klima-v2-10min"
GEOSPHERE_NATIVE_INTERVAL_MINUTES = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].native_interval_minutes
GEOSPHERE_ENDPOINT = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].endpoint
GEOSPHERE_METADATA_ENDPOINT = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].metadata_endpoint
GEOSPHERE_DATASET_PAGE = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].dataset_page
GEOSPHERE_DOI = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].doi
_PROVIDER_FIELD_SPECS = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].field_specs
FIELD_SPEC_BY_PROVIDER = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].field_by_provider
FIELD_SPEC_BY_CANONICAL = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].field_by_canonical
DEFAULT_PROVIDER_PARAMETERS = tuple(FIELD_SPEC_BY_PROVIDER)
QUALITY_FLAG_PROVIDER_NAMES = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].quality_flag_provider_names
SUPPORTED_QUERY_PARAMETERS = GEOSPHERE_RESOURCES[GEOSPHERE_RESOURCE_ID].supported_query_parameters


def resource_spec(resource_id: str = GEOSPHERE_RESOURCE_ID) -> GeoSphereResourceSpec:
    key = str(resource_id).strip()
    try:
        return GEOSPHERE_RESOURCES[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported GeoSphere historical resource: {key}") from exc


def available_resource_specs() -> tuple[GeoSphereResourceSpec, ...]:
    return tuple(GEOSPHERE_RESOURCES.values())


def quality_flag_column(provider_name: str) -> str:
    return f"{QUALITY_FLAG_COLUMN_PREFIX}{str(provider_name).strip()}"


def _normalise_unit(unit: object) -> str:
    return str(unit or "").strip().lower().replace("℃", "°c")


def _validate_official_url(url: str) -> str:
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
        except Exception as exc:
            raise ValueError("GeoSphere API returned invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise ValueError("GeoSphere API JSON root must be an object.")
        return decoded
    finally:
        response.close()


def fetch_metadata(*, resource_id: str = GEOSPHERE_RESOURCE_ID, timeout_s: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Fetch current metadata for one supported historical resource."""
    return _bounded_get_json(resource_spec(resource_id).metadata_endpoint, timeout_s=timeout_s)


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
            code_list_ref=str(item.get("code_list_ref") or "").strip(),
        )
    if not result:
        raise ValueError("GeoSphere metadata contain no usable parameters.")
    return result


def _code_value_and_label(item: object) -> tuple[int | None, str]:
    if isinstance(item, Mapping):
        raw_code = _coalesce(item, "code", "value", "id", default=None)
        try:
            code = int(raw_code) if raw_code is not None else None
        except (TypeError, ValueError):
            code = None
        label = str(_coalesce(item, "description", "label", "name", "long_name", default="")).strip()
        return code, label
    return None, ""


def parse_code_lists(metadata: Mapping[str, Any]) -> dict[str, dict[int, str]]:
    """Normalize GeoSphere v2 top-level code lists into ``ref -> code -> label``."""
    raw = metadata.get("code_lists")
    result: dict[str, dict[int, str]] = {}
    if isinstance(raw, Mapping):
        iterable = raw.items()
    elif isinstance(raw, list):
        iterable = []
        for entry in raw:
            if isinstance(entry, Mapping):
                ref = str(_coalesce(entry, "id", "name", "ref", default="")).strip()
                iterable.append((ref, entry))
    else:
        return result

    for ref, payload in iterable:
        ref_text = str(ref).strip()
        if not ref_text:
            continue
        values: object = payload
        if isinstance(payload, Mapping):
            values = _coalesce(payload, "values", "codes", "items", "entries", default=payload)
        codebook: dict[int, str] = {}
        if isinstance(values, Mapping):
            for key, value in values.items():
                try:
                    code = int(key)
                except (TypeError, ValueError):
                    item_code, label = _code_value_and_label(value)
                    if item_code is None:
                        continue
                    code = item_code
                    codebook[code] = label or str(value)
                    continue
                if isinstance(value, Mapping):
                    _, label = _code_value_and_label(value)
                    codebook[code] = label or str(value)
                else:
                    codebook[code] = str(value)
        elif isinstance(values, list):
            for value in values:
                code, label = _code_value_and_label(value)
                if code is not None:
                    codebook[code] = label or str(code)
        if codebook:
            result[ref_text] = codebook
    return result


def quality_flag_codebook(metadata: Mapping[str, Any], provider_name: str) -> dict[int, str]:
    parameters = parse_parameters(metadata)
    flag = parameters.get(f"{provider_name}_flag")
    if flag is None or not flag.code_list_ref:
        return {}
    return dict(parse_code_lists(metadata).get(flag.code_list_ref, {}))


def supported_parameter_mapping(
    metadata: Mapping[str, Any],
    *,
    resource_id: str = GEOSPHERE_RESOURCE_ID,
) -> dict[str, ProviderFieldSpec]:
    """Resolve resource fields from live metadata with strict unit checks."""
    parameters = parse_parameters(metadata)
    resolved: dict[str, ProviderFieldSpec] = {}
    for provider_name, spec in resource_spec(resource_id).field_by_provider.items():
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


def provider_parameters_with_quality_flags(
    metadata: Mapping[str, Any],
    provider_parameters: Iterable[str],
    *,
    resource_id: str = GEOSPHERE_RESOURCE_ID,
) -> tuple[str, ...]:
    parameters = parse_parameters(metadata)
    allowed = resource_spec(resource_id).field_by_provider
    result: list[str] = []
    for name in dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()):
        if name not in allowed:
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


CAPABILITY_RESOURCE_SUPPORTED = "resource-supported"
CAPABILITY_STATION_CONFIRMED = "station-confirmed"
CAPABILITY_STATION_UNAVAILABLE = "station-unavailable"


def station_parameter_capability_index(
    metadata: Mapping[str, Any],
    *,
    resource_id: str = GEOSPHERE_RESOURCE_ID,
) -> dict[str, dict[str, str]]:
    supported = supported_parameter_mapping(metadata, resource_id=resource_id)
    base = {name: CAPABILITY_RESOURCE_SUPPORTED for name in supported}
    result: dict[str, dict[str, str]] = {}
    for record in _station_records(metadata):
        station_id = str(_coalesce(record, "id", "station_id", "station", default="")).strip()
        if not station_id:
            continue
        statuses = dict(base)
        global_radiation = _bool_or_none(record.get("has_global_radiation"))
        if "cglo" in statuses and global_radiation is not None:
            statuses["cglo"] = CAPABILITY_STATION_CONFIRMED if global_radiation else CAPABILITY_STATION_UNAVAILABLE
        sunshine = _bool_or_none(record.get("has_sunshine"))
        if "so" in statuses and sunshine is not None:
            statuses["so"] = CAPABILITY_STATION_CONFIRMED if sunshine else CAPABILITY_STATION_UNAVAILABLE
        result[station_id] = statuses
    if not result:
        raise ValueError("GeoSphere metadata contain no station capability index.")
    return result


def station_parameter_capability_table(
    metadata: Mapping[str, Any], station_id: str, *, resource_id: str = GEOSPHERE_RESOURCE_ID
) -> pd.DataFrame:
    station_key = str(station_id).strip()
    index = station_parameter_capability_index(metadata, resource_id=resource_id)
    if station_key not in index:
        raise KeyError(f"Unknown GeoSphere station id: {station_key}")
    parameters = parse_parameters(metadata)
    supported = supported_parameter_mapping(metadata, resource_id=resource_id)
    statuses = index[station_key]
    rows: list[dict[str, object]] = []
    for provider_name, spec in supported.items():
        parameter = parameters.get(provider_name)
        status = statuses.get(provider_name, CAPABILITY_RESOURCE_SUPPORTED)
        basis = (
            "Station metadata confirms sensor" if status == CAPABILITY_STATION_CONFIRMED
            else "Station metadata reports unavailable" if status == CAPABILITY_STATION_UNAVAILABLE
            else "Resource metadata; period coverage checked after load"
        )
        rows.append(
            {
                "provider": provider_name,
                "canonical": spec.canonical_name,
                "variable": parameter.long_name if parameter and parameter.long_name else spec.description or spec.canonical_name,
                "unit": parameter.unit if parameter else "",
                "status": status,
                "available": status != CAPABILITY_STATION_UNAVAILABLE,
                "basis": basis,
            }
        )
    return pd.DataFrame(rows)


def station_catalog(metadata: Mapping[str, Any]) -> pd.DataFrame:
    rows = [station.__dict__ for station in parse_stations(metadata)]
    table = pd.DataFrame(rows)
    return table.sort_values(["state", "name", "station_id"], kind="mergesort").reset_index(drop=True)


def estimate_request_datapoints(
    start: pd.Timestamp,
    end: pd.Timestamp,
    parameter_count: int,
    station_count: int = 1,
    *,
    resource_id: str = GEOSPHERE_RESOURCE_ID,
) -> int:
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if end < start:
        raise ValueError("GeoSphere request end must not be earlier than start.")
    if parameter_count <= 0 or station_count <= 0:
        raise ValueError("GeoSphere requests require at least one parameter and one station.")
    cadence = resource_spec(resource_id).native_interval_minutes
    steps = int(math.floor((end - start) / pd.Timedelta(minutes=cadence))) + 1
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
    *,
    resource_id: str = GEOSPHERE_RESOURCE_ID,
) -> dict[str, str]:
    station_id = str(station_id).strip()
    if not station_id:
        raise ValueError("GeoSphere station_id must not be empty.")
    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))
    if not parameters:
        raise ValueError("At least one GeoSphere parameter is required.")
    unknown = sorted(set(parameters) - set(resource_spec(resource_id).supported_query_parameters))
    if unknown:
        raise ValueError(f"Unsupported GeoSphere parameters: {', '.join(unknown)}")
    count = estimate_request_datapoints(pd.Timestamp(start), pd.Timestamp(end), len(parameters), 1, resource_id=resource_id)
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
    resource_id: str = GEOSPHERE_RESOURCE_ID,
) -> list[dict[str, str]]:
    station_id = str(station_id).strip()
    if not station_id:
        raise ValueError("GeoSphere station_id must not be empty.")
    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))
    if not parameters:
        raise ValueError("At least one GeoSphere parameter is required.")
    unknown = sorted(set(parameters) - set(resource_spec(resource_id).supported_query_parameters))
    if unknown:
        raise ValueError(f"Unsupported GeoSphere parameters: {', '.join(unknown)}")
    if int(max_datapoints) <= 0:
        raise ValueError("GeoSphere batch datapoint limit must be positive.")
    if int(max_datapoints) > MAX_REQUEST_DATAPOINTS:
        raise ValueError(f"GeoSphere batch datapoint limit must not exceed the local hard cap of {MAX_REQUEST_DATAPOINTS:,}.")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if end_ts < start_ts:
        raise ValueError("GeoSphere request end must not be earlier than start.")
    max_steps = int(max_datapoints) // len(parameters)
    if max_steps < 1:
        raise ValueError("GeoSphere batch datapoint limit is too small for the selected parameter set.")
    interval = pd.Timedelta(minutes=resource_spec(resource_id).native_interval_minutes)
    queries: list[dict[str, str]] = []
    cursor = start_ts
    while cursor <= end_ts:
        batch_end = min(end_ts, cursor + interval * (max_steps - 1))
        query = build_data_query(station_id, cursor, batch_end, parameters, resource_id=resource_id)
        if estimate_request_datapoints(cursor, batch_end, len(parameters), 1, resource_id=resource_id) > int(max_datapoints):
            raise RuntimeError("Internal GeoSphere batch planner exceeded its datapoint limit.")
        queries.append(query)
        cursor = batch_end + interval
    return queries


def _query_reference(query: Mapping[str, str], resource_id: str = GEOSPHERE_RESOURCE_ID) -> str:
    return f"{resource_spec(resource_id).endpoint}?{urlencode(dict(query))}"


def _http_status_from_exception(exc: BaseException) -> int | None:
    if not isinstance(exc, requests.HTTPError):
        return None
    response = getattr(exc, "response", None)
    try:
        return int(response.status_code) if response is not None else None
    except (TypeError, ValueError):
        return None


def _is_transient_provider_error(exc: BaseException) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError)):
        return True
    status = _http_status_from_exception(exc)
    return status in TRANSIENT_HTTP_STATUS_CODES if status is not None else False


def _is_response_size_error(exc: BaseException) -> bool:
    return isinstance(exc, ValueError) and "response exceeds the local response-size limit" in str(exc)


def _split_data_query(
    query: Mapping[str, str], *, resource_id: str = GEOSPHERE_RESOURCE_ID
) -> tuple[dict[str, str], dict[str, str]] | None:
    parameters = tuple(item for item in str(query.get("parameters", "")).split(",") if item)
    station_id = str(query.get("station_ids", "")).strip()
    if not station_id or not parameters:
        raise ValueError("GeoSphere query is missing station or parameter identity.")
    start = pd.Timestamp(str(query.get("start", "")), tz="UTC")
    end = pd.Timestamp(str(query.get("end", "")), tz="UTC")
    interval = pd.Timedelta(minutes=resource_spec(resource_id).native_interval_minutes)
    steps = int(math.floor((end - start) / interval)) + 1
    if steps <= 1:
        return None
    left_steps = max(1, steps // 2)
    left_end = start + interval * (left_steps - 1)
    right_start = left_end + interval
    if right_start > end:
        return None
    return (
        build_data_query(station_id, start, left_end, parameters, resource_id=resource_id),
        build_data_query(station_id, right_start, end, parameters, resource_id=resource_id),
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
        return


def _fetch_query_with_resilience(
    query: Mapping[str, str],
    *,
    timeout_s: int,
    resource_id: str = GEOSPHERE_RESOURCE_ID,
    split_depth: int = 0,
    progress_callback: GeoSphereProgressCallback | None = None,
    root_batch_number: int = 1,
    root_batch_count: int = 1,
    completed_root_batches: int = 0,
) -> list[tuple[dict[str, Any], dict[str, str]]]:
    normalized_query = {str(key): str(value) for key, value in query.items()}
    last_error: BaseException | None = None
    for attempt in range(1, MAX_TRANSIENT_ATTEMPTS + 1):
        try:
            payload = _bounded_get_json(
                resource_spec(resource_id).endpoint,
                params=normalized_query,
                timeout_s=timeout_s,
            )
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
    children = _split_data_query(normalized_query, resource_id=resource_id)
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
                resource_id=resource_id,
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
    resource_id: str = GEOSPHERE_RESOURCE_ID,
    timeout_s: int = DEFAULT_TIMEOUT_SECONDS,
    progress_callback: GeoSphereProgressCallback | None = None,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))
    queries = plan_data_queries(station_id, start, end, parameters, resource_id=resource_id)
    frames: list[pd.DataFrame] = []
    references: list[str] = []
    total_batches = len(queries)
    for batch_number, query in enumerate(queries, start=1):
        _emit_progress(progress_callback, event="batch_start", completed_batches=batch_number - 1, total_batches=total_batches, batch_number=batch_number, query=query)
        completed = _fetch_query_with_resilience(
            query,
            timeout_s=timeout_s,
            resource_id=resource_id,
            progress_callback=progress_callback,
            root_batch_number=batch_number,
            root_batch_count=total_batches,
            completed_root_batches=batch_number - 1,
        )
        for payload, successful_query in completed:
            frames.append(parse_station_data_response(payload, station_id, parameters))
            references.append(_query_reference(successful_query, resource_id))
        _emit_progress(progress_callback, event="batch_complete", completed_batches=batch_number, total_batches=total_batches, batch_number=batch_number, query=query)
    if not frames:
        raise ValueError("GeoSphere batching produced no requests.")
    combined = pd.concat(frames, axis=0)
    if combined.empty:
        raise ValueError("GeoSphere returned no timestamps for the selected interval.")
    if combined.index.has_duplicates:
        duplicate_count = int(combined.index.duplicated(keep=False).sum())
        raise ValueError(f"GeoSphere batched response contains {duplicate_count} duplicate timestamps.")
    combined = combined.sort_index(kind="mergesort")
    _emit_progress(progress_callback, event="load_complete", completed_batches=total_batches, total_batches=total_batches, batch_number=total_batches, query=queries[-1])
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
    payload: Mapping[str, Any], station_id: str, provider_parameters: Iterable[str]
) -> pd.DataFrame:
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
        values = entry.get("data")
        if not isinstance(values, list):
            frame[name] = pd.NA
            continue
        if len(values) != len(frame):
            raise ValueError(f"GeoSphere parameter '{name}' has {len(values)} values for {len(frame)} timestamps.")
        frame[name] = pd.to_numeric(pd.Series(values, index=frame.index), errors="coerce")
    return frame


def provider_frame_to_canonical(
    provider_frame: pd.DataFrame, mapping: Mapping[str, ProviderFieldSpec]
) -> pd.DataFrame:
    canonical = pd.DataFrame(index=provider_frame.index.copy())
    for provider_name, spec in mapping.items():
        if provider_name not in provider_frame.columns:
            continue
        values = pd.to_numeric(provider_frame[provider_name], errors="coerce")
        canonical[spec.canonical_name] = values * float(spec.scale)
        flag_name = f"{provider_name}_flag"
        if flag_name in provider_frame.columns:
            canonical[quality_flag_column(provider_name)] = pd.to_numeric(provider_frame[flag_name], errors="coerce")
    if canonical.empty:
        raise ValueError("GeoSphere response produced no supported canonical climate variables.")
    return canonical


def build_canonical_station_dataset(
    *,
    station: GeoSphereStation,
    provider_frame: pd.DataFrame,
    mapping: Mapping[str, ProviderFieldSpec],
    resource_id: str = GEOSPHERE_RESOURCE_ID,
    metadata: Mapping[str, Any] | None = None,
    request_reference: str = "",
    retrieval_time_utc: str | None = None,
    request_count: int = 1,
) -> CanonicalClimateDataset:
    spec = resource_spec(resource_id)
    canonical = provider_frame_to_canonical(provider_frame, mapping)
    canonical.attrs["geosphere_resource_id"] = spec.resource_id
    canonical.attrs["canonical_analysis_timezone_name"] = GEOSPHERE_LOCAL_TIMEZONE
    canonical.attrs["canonical_standard_utc_offset_hours"] = GEOSPHERE_STANDARD_UTC_OFFSET_HOURS
    if metadata is not None:
        codebooks: dict[str, dict[int, str]] = {}
        labels: dict[str, str] = {}
        parameters = parse_parameters(metadata)
        for provider_name in mapping:
            codebook = quality_flag_codebook(metadata, provider_name)
            if codebook:
                codebooks[provider_name] = codebook
                flag = parameters.get(f"{provider_name}_flag")
                labels[provider_name] = flag.long_name if flag else provider_name
        canonical.attrs[QUALITY_CODEBOOK_ATTR] = codebooks
        canonical.attrs[QUALITY_LABEL_ATTR] = labels
    temporal = ClimateTemporalMetadata(
        native_interval_minutes=spec.native_interval_minutes,
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
    notes = [
        f"License: CC BY 4.0 ({GEOSPHERE_LICENSE})",
        f"Dataset DOI: {spec.doi}",
        "Provider timestamps are retained as real UTC historical timestamps.",
        f"Preferred building-analysis timezone: {GEOSPHERE_LOCAL_TIMEZONE}; source UTC remains unchanged.",
    ]
    if any(item.canonical_name.endswith("radiation_wh_m2") for item in mapping.values()):
        notes.append(
            f"{spec.native_interval_minutes:g}-minute mean radiation in W/m² is converted to interval irradiation in Wh/m²."
        )
    notes.append(f"Historical interval retrieved in {int(request_count)} bounded Dataset API request batch(es).")
    provenance = ClimateProvenance(
        provider="GeoSphere Austria",
        dataset=f"{spec.resource_id} — quality-checked station data for Austria",
        source_format="Dataset API JSON",
        source_name=f"GeoSphere station {station.station_id} ({station.name})",
        source_reference=request_reference or spec.dataset_page,
        provider_station_id=station.station_id,
        retrieval_time_utc=retrieval_time_utc or datetime.now(timezone.utc).isoformat(),
        notes=tuple(notes),
    )
    cadence_label = "10 min" if spec.native_interval_minutes == 10 else "1 h" if spec.native_interval_minutes == 60 else f"{spec.native_interval_minutes} min"
    return build_canonical_dataset(
        climate_id=f"geosphere:{spec.resource_id}:{station.station_id}",
        display_name=f"{station.name} — GeoSphere {cadence_label}",
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
    resource_id: str = GEOSPHERE_RESOURCE_ID,
    metadata: Mapping[str, Any] | None = None,
    canonical_variables: Iterable[str] | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_SECONDS,
    progress_callback: GeoSphereProgressCallback | None = None,
) -> CanonicalClimateDataset:
    spec = resource_spec(resource_id)
    metadata_payload = dict(metadata) if metadata is not None else fetch_metadata(resource_id=resource_id, timeout_s=timeout_s)
    supported = supported_parameter_mapping(metadata_payload, resource_id=resource_id)
    if canonical_variables is None:
        selected = dict(supported)
    else:
        requested = tuple(dict.fromkeys(str(item).strip() for item in canonical_variables if str(item).strip()))
        selected: dict[str, ProviderFieldSpec] = {}
        by_canonical = spec.field_by_canonical
        for canonical_name in requested:
            field = by_canonical.get(canonical_name)
            if field is None:
                raise ValueError(f"Canonical variable '{canonical_name}' is not supported by GeoSphere resource {resource_id}.")
            if field.provider_name not in supported:
                raise ValueError(
                    f"GeoSphere metadata for {resource_id} do not currently expose required parameter '{field.provider_name}'."
                )
            selected[field.provider_name] = field
    query_parameters = provider_parameters_with_quality_flags(metadata_payload, selected.keys(), resource_id=resource_id)
    provider_frame, request_references = fetch_station_provider_frame(
        station_id=station.station_id,
        start=start,
        end=end,
        provider_parameters=query_parameters,
        resource_id=resource_id,
        timeout_s=timeout_s,
        progress_callback=progress_callback,
    )
    dataset = build_canonical_station_dataset(
        station=station,
        provider_frame=provider_frame,
        mapping=selected,
        resource_id=resource_id,
        metadata=metadata_payload,
        request_reference="\n".join(request_references),
        request_count=len(request_references),
    )
    dataset.data.attrs["canonical_requested_start"] = pd.Timestamp(start).isoformat()
    dataset.data.attrs["canonical_requested_end"] = pd.Timestamp(end).isoformat()
    return dataset
