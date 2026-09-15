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
from typing import Any, Iterable, Mapping
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

# The official API limit is larger, but a lower local cap keeps public app
# requests bounded and leaves margin for provider-side changes and null values.
MAX_REQUEST_DATAPOINTS = 200_000
MAX_RESPONSE_BYTES = 24 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60
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
    ProviderFieldSpec("rf", "relative_humidity_pct", ("%",), description="Relative Feuchte"),
    ProviderFieldSpec("p", "atmospheric_station_pressure_pa", ("hpa",), scale=100.0, description="Luftdruck"),
    ProviderFieldSpec("ffam", "wind_speed_m_s", ("m/s", "m s-1", "m s^-1"), description="Windgeschwindigkeit 10m, arithmetischer Mittelwert"),
    ProviderFieldSpec("dd", "wind_direction_deg", ("°", "deg", "degree"), description="Windrichtung"),
    ProviderFieldSpec("rr", "liquid_precipitation_depth_mm", ("mm",), description="Niederschlagssumme"),
    ProviderFieldSpec("sh", "snow_depth_cm", ("cm",), description="Gesamtschneehöhe"),
    ProviderFieldSpec("cglo", "global_horizontal_radiation_wh_m2", ("w/m²", "w/m2", "w m-2", "w m^-2"), scale=GEOSPHERE_NATIVE_INTERVAL_MINUTES / 60.0, description="Globalstrahlung Mittelwert"),
    ProviderFieldSpec("chim", "diffuse_horizontal_radiation_wh_m2", ("w/m²", "w/m2", "w m-2", "w m^-2"), scale=GEOSPHERE_NATIVE_INTERVAL_MINUTES / 60.0, description="Himmelsstrahlung Mittelwert"),
)
FIELD_SPEC_BY_PROVIDER = {item.provider_name: item for item in _PROVIDER_FIELD_SPECS}
FIELD_SPEC_BY_CANONICAL = {item.canonical_name: item for item in _PROVIDER_FIELD_SPECS}
DEFAULT_PROVIDER_PARAMETERS = tuple(item.provider_name for item in _PROVIDER_FIELD_SPECS)


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
    unknown = sorted(set(parameters) - set(FIELD_SPEC_BY_PROVIDER))
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
    query = build_data_query(station.station_id, start, end, selected.keys())
    payload = _bounded_get_json(GEOSPHERE_ENDPOINT, params=query, timeout_s=timeout_s)
    provider_frame = parse_station_data_response(payload, station.station_id, selected.keys())
    request_reference = f"{GEOSPHERE_ENDPOINT}?{urlencode(query)}"
    return build_canonical_station_dataset(
        station=station,
        provider_frame=provider_frame,
        mapping=selected,
        request_reference=request_reference,
    )
