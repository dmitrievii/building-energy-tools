"""H1 native-hourly GeoSphere acquisition, byte-preserved sources and replay.

This is a source-year inventory. Missing radiation is not borrowed from another
site/model, precipitation phase is not guessed, and means are not inverted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import zipfile

import pandas as pd

from . import geosphere as geo
from .climate_model import ClimateLocation
from .quality_policy import GEOSPHERE_AUTOMATIC_OR_MANUAL_CODES
from .engine.historical import json_bytes
from .engine.station_epw_admission import (StationField, StationYearRequest,
    assess_station_year)

RESOURCE = "klima-v2-1h"
SCHEMA = "IGE_H1_GEOSPHERE_ORIGINAL_SOURCES_v1"
MAX_PACKET_BYTES = 64 * 1024 * 1024
SOURCE_DOC = "https://data.hub.geosphere.at/dataset/klima-v2-1h"
QC_DOC = "https://public.hub.geosphere.at/public/resources/misc/klima/DataHub-DE-Qualitaetsindikatoren.pdf"
QC_PROFILE = "H1_GEOSPHERE_PROVIDER_REVIEWED_v1_NOT_V2_QC10"

# Native descriptions and units are admitted, not inferred from short names.
# rr is intentionally kept separate from EPW liquid precipitation.
BINDINGS = {
    "tl": ("dry_bulb_temperature_c", "°C", "°C", 1., "published_nominal_node",
           "Lufttemperatur in 2m Höhe, Stunden-Messwert", "2m above local ground", "provider_temperature"),
    "rf": ("relative_humidity_pct", "%", "%", 1., "published_nominal_node",
           "Relative Feuchte, Stunden-Messwert", "provider RH sensor; height not confirmed", "provider_RH_phase_unspecified"),
    "p": ("atmospheric_station_pressure_pa", "hPa", "Pa", 100., "published_nominal_node",
          "Luftdruck in Stationsniveau, Stunden-Messwert", "station barometer; sensor ASL not confirmed", "absolute_station_pressure"),
    "ff": ("wind_speed_m_s", "m/s", "m/s", 1., "mean_over_preceding_hour",
           "Windgeschwindigkeit, vektorieller Stundenmittelwert", "provider wind sensor; height not confirmed", "vector_mean_wind_speed"),
    "dd": ("wind_direction_deg", "°", "deg", 1., "mean_over_preceding_hour",
           "Windrichtung [360°], vektorieller Stunden-Mittelwert", "provider wind sensor; height not confirmed", "vector_mean_wind_direction"),
    "cglo": ("global_horizontal_radiation_wh_m2", "W/m²", "Wh/m²", 1., "interval_energy",
             "Globalstrahlung, kalibrierter Stunden-Mittelwert", "horizontal pyranometer", "hourly_GHI"),
    "rr": ("total_precipitation_depth_mm", "mm", "mm", 1., "interval_amount",
           "Niederschlag, Stundensumme", "precipitation gauge", "total_precipitation_phase_not_separated"),
    "sh": ("snow_depth_cm", "cm", "cm", 1., "published_nominal_node",
           "Gesamtschneehöhe aus Schneepegelmessung, Offset korrigiert", "snow gauge", "snow_depth"),
}
QC_LABELS = {10: "automatisch geprüft", 11: "automatisch geprüft (verändert)",
             12: "automatisch geprüft (original)", 20: "manuell geprüft (unbekannt)",
             21: "manuell geprüft (verändert)", 22: "manuell geprüft (original)"}


@dataclass(frozen=True)
class StationYearProduct:
    request: StationYearRequest
    report: dict
    files: dict[str, bytes]
    archive: bytes


def _normal(value):
    return " ".join(str(value).casefold().split())


def _zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, body)
    return output.getvalue()


def _station(metadata, station_id):
    stations = {str(s.station_id): s for s in geo.parse_stations(metadata)}
    if station_id not in stations:
        raise ValueError("H1_SELECTED_STATION_NOT_IN_HOURLY_RESOURCE")
    return stations[station_id]


def _parameters(metadata):
    parameters = geo.parse_parameters(metadata)
    selected = []
    for name in BINDINGS:
        if name not in parameters:
            continue
        selected.append(name)
        if name + "_flag" in parameters:
            selected.append(name + "_flag")
    return tuple(selected)


def _canonical(frame, metadata):
    parameters = geo.parse_parameters(metadata)
    canonical = pd.DataFrame(index=frame.index)
    definitions = {}
    for provider, (name, native_unit, unit, factor, operator, description, height, quantity) in BINDINGS.items():
        if provider not in parameters:
            continue
        parameter = parameters[provider]
        errors = []
        if _normal(parameter.unit) != _normal(native_unit): errors.append("PROVIDER_UNIT_CHANGED")
        if _normal(parameter.description) != _normal(description): errors.append("PROVIDER_DEFINITION_CHANGED")
        codebook = geo.quality_flag_codebook(metadata, provider)
        if any(_normal(codebook.get(code, "")) != _normal(label) for code, label in QC_LABELS.items()):
            errors.append("PROVIDER_QC_CODEBOOK_NOT_ADMITTED")
        flag = parameters.get(provider + "_flag")
        if flag is None or flag.unit != "code": errors.append("PROVIDER_QC_FIELD_MISSING_OR_CHANGED")
        definition = StationField(unit, provider, operator, height,
            geo.resource_spec(RESOURCE).metadata_endpoint + " :: parameters[" + provider + "]",
            "quality_flag__" + provider, "measured", quantity, ";".join(errors),
            tuple(sorted(GEOSPHERE_AUTOMATIC_OR_MANUAL_CODES)), QC_PROFILE)
        definitions[name] = definition
        if provider in frame:
            # Unknown units are retained in native.csv, never silently converted.
            if "PROVIDER_UNIT_CHANGED" not in errors:
                canonical[name] = pd.to_numeric(frame[provider], errors="coerce") * factor
            if provider + "_flag" in frame:
                canonical[definition.quality_column] = pd.to_numeric(frame[provider + "_flag"], errors="coerce")
    return canonical, definitions


def _source_packet(request, captured, *, transport_error=None):
    files, receipts = {}, []
    for i, (url, query, body) in enumerate(captured):
        name = f"responses/{i:03d}.json"
        files[name] = body
        receipts.append({"path": name, "url": url, "query": query, "bytes": len(body),
                         "sha256": sha256(body).hexdigest()})
    files["manifest.json"] = json_bytes({"schema": SCHEMA, "request": request.to_dict(),
        "resource": RESOURCE, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "transport_error": transport_error, "responses": receipts,
        "raw_HTTP_response_bytes_preserved": True})
    return _zip(files)


def read_sources(packet: bytes, expected_sha256: str):
    if not expected_sha256 or sha256(packet).hexdigest() != expected_sha256 or len(packet) > MAX_PACKET_BYTES:
        raise ValueError("H1_SOURCE_PACKET_HASH_OR_SIZE")
    with zipfile.ZipFile(io.BytesIO(packet)) as archive:
        members = archive.infolist()
        if len(members) > 65 or len({item.filename for item in members}) != len(members):
            raise ValueError("H1_SOURCE_PACKET_MEMBER_CENSUS")
        if sum(item.file_size for item in members) > MAX_PACKET_BYTES:
            raise ValueError("H1_SOURCE_PACKET_EXPANDED_SIZE")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema") != SCHEMA or manifest.get("resource") != RESOURCE:
            raise ValueError("H1_SOURCE_PACKET_SCHEMA")
        receipts = manifest.get("responses", [])
        if {item.filename for item in members} != {"manifest.json", *[r["path"] for r in receipts]}:
            raise ValueError("H1_SOURCE_PACKET_UNREGISTERED_MEMBER")
        captured = []
        for receipt in receipts:
            path = receipt["path"]
            if not path.startswith("responses/") or Path(path).name != path.split("/", 1)[1]:
                raise ValueError("H1_SOURCE_PACKET_UNSAFE_PATH")
            body = archive.read(path)
            if len(body) != receipt["bytes"] or sha256(body).hexdigest() != receipt["sha256"]:
                raise ValueError("H1_SOURCE_BODY_HASH_MISMATCH")
            captured.append((receipt["url"], receipt["query"], body))
    return manifest, captured


def _parse_capture(request, captured):
    metadata_url, data_url = geo.resource_spec(RESOURCE).metadata_endpoint, geo.resource_spec(RESOURCE).endpoint
    metadata_bodies = [body for url, query, body in captured if url == metadata_url and not query]
    if len(metadata_bodies) != 1:
        raise ValueError("H1_EXACTLY_ONE_ORIGINAL_METADATA_BODY_REQUIRED")
    metadata = json.loads(metadata_bodies[0])
    params = _parameters(metadata)
    frames = []
    for url, query, body in captured:
        if url == metadata_url and not query:
            continue
        if (url != data_url or set(query) != {"parameters", "station_ids", "start", "end"}
                or query.get("station_ids") != request.station_id or query.get("parameters") != ",".join(params)):
            raise ValueError("H1_SOURCE_REQUEST_IDENTITY_MISMATCH")
        # The established GeoSphere planner serializes UTC query bounds without
        # a suffix. Response timestamps, unlike these known query bounds, must
        # retain an explicit timezone below.
        first, last = pd.to_datetime(query["start"], utc=True), pd.to_datetime(query["end"], utc=True)
        if (pd.isna(first) or pd.isna(last) or first > last or first < request.utc_ends[0]
                or last > request.utc_ends[-1]):
            raise ValueError("H1_SOURCE_REQUEST_OUTSIDE_YEAR")
        payload = json.loads(body)
        features = payload.get("features", [])
        if not any(geo._feature_station_id(feature) == request.station_id for feature in features):
            raise ValueError("H1_WRONG_STATION_RESPONSE_NO_SINGLE_FEATURE_FALLBACK")
        for stamp in payload.get("timestamps", []):
            time = pd.Timestamp(stamp)
            if time.tz is None or time < first or time > last:
                raise ValueError("H1_UNDECLARED_OR_WRONG_RESPONSE_CLOCK")
        frames.append(geo.parse_station_data_response(payload, request.station_id, params))
    frame = pd.concat(frames) if frames else pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    return metadata, frame


def run_station_year(request: StationYearRequest, *, source_packet: bytes | None = None,
                     expected_sha256: str = "", progress=lambda event: None) -> StationYearProduct:
    """One explicit annual request or an entirely offline, hash-pinned replay."""
    if not request.station_id.isascii() or not request.station_id.isdigit():
        raise ValueError("H1_GEOSPHERE_REQUIRES_NUMERIC_PROVIDER_ID")
    replay = source_packet is not None
    captured = []
    transport_error = None
    if source_packet is None:
        def capture(url, query, body):
            if sum(len(item[2]) for item in captured) + len(body) > MAX_PACKET_BYTES or len(captured) >= 64:
                raise ValueError("H1_SOURCE_COLLECTION_LIMIT")
            captured.append((url, query, body))
        metadata = geo.fetch_metadata(resource_id=RESOURCE, response_capture=capture)
        station = _station(metadata, request.station_id)
        today = pd.Timestamp.now(tz="UTC")
        if request.utc_ends[-1] >= today:
            transport_error = "REQUESTED_CALENDAR_YEAR_IS_NOT_COMPLETE"
        elif metadata.get("frequency") != "PT1H":
            transport_error = "SOURCE_FREQUENCY_CHANGED"
        else:
            try:
                geo.fetch_station_provider_frame(station_id=station.station_id,
                    start=request.utc_ends[0], end=request.utc_ends[-1],
                    provider_parameters=_parameters(metadata), resource_id=RESOURCE,
                    progress_callback=progress, response_capture=capture)
            except Exception as exc:
                transport_error = type(exc).__name__ + ": " + str(exc)
        source_packet = _source_packet(request, captured, transport_error=transport_error)
        expected_sha256 = sha256(source_packet).hexdigest()
    manifest, captured = read_sources(source_packet, expected_sha256)
    if manifest["request"] != request.to_dict():
        raise ValueError("H1_REPLAY_REQUEST_MISMATCH")
    metadata, native = _parse_capture(request, captured)
    station = _station(metadata, request.station_id)
    canonical, definitions = _canonical(native, metadata)
    blockers = []
    if manifest.get("transport_error"): blockers.append("SOURCE_REQUEST_FAILED: " + manifest["transport_error"])
    if metadata.get("frequency") != "PT1H": blockers.append("SOURCE_FREQUENCY_CHANGED")
    start, stop = pd.to_datetime(station.valid_from, utc=True), pd.to_datetime(station.valid_to, utc=True)
    if pd.isna(start) or pd.isna(stop) or start > request.utc_ends[0] or stop < request.utc_ends[-1]:
        blockers.append("STATION_VALIDITY_DOES_NOT_COVER_YEAR")
    location = ClimateLocation(station.latitude, station.longitude, station.elevation_m,
        station.name, station.state, "Austria", station.station_id)
    assessment = assess_station_year(request, location, canonical, definitions,
        source_id="GeoSphere:" + RESOURCE, blockers=tuple(blockers),
        source_metadata={"resource": RESOURCE, "station_type": station.station_type,
            "provider_station": station.__dict__, "source_packet_sha256": expected_sha256,
            "documentation": [SOURCE_DOC, QC_DOC],
            "pressure": "Only p (station level); pred is never substituted.",
            "precipitation": "rr retained as total precipitation; not mapped to liquid rain.",
            "nominal_station_height_is_not_confirmed_sensor_height": True,
            "RH_phase": "UNSPECIFIED_BY_THIS_RESOURCE; no derived dew point or q",
            "hourly_mean_wind_is_not_relabelled_as_an_endpoint_instant": True,
            "original_metadata_sha256": sha256(next(body for url, query, body in captured
                if url == geo.resource_spec(RESOURCE).metadata_endpoint and not query)).hexdigest()})
    report = dict(assessment.report)
    report["weather_provider_responses_this_run"] = 0 if replay else sum(
        url == geo.resource_spec(RESOURCE).endpoint for url, query, body in captured)
    report["metadata_provider_responses_this_run"] = 0 if replay else 1
    report["offline_replay"] = replay
    report["HTTP_attempts_including_failed_attempts"] = "Not counted; original successful response bodies and query identities are retained."
    report["source_responses_in_packet"] = len(captured)
    report["transport_complete"] = not bool(manifest.get("transport_error"))
    report["additional_source_fields"] = [asdict_source(name, definition, canonical)
        for name, definition in definitions.items() if name not in assessment.hourly]
    files = {"admission.json": json_bytes(report), "sources.zip": source_packet,
             "coverage.csv": pd.DataFrame(assessment.report["fields"]).to_csv(index=False).encode(),
             "missing_hours.csv.gz": gzip.compress(assessment.gaps.to_csv(index=False).encode(), mtime=0),
             "native.csv.gz": gzip.compress(native.to_csv(index_label="source_timestamp_utc").encode(), mtime=0),
             "hourly_states.csv.gz": gzip.compress(assessment.hourly.to_csv(index_label="interval_start_utc").encode(), mtime=0)}
    if assessment.epw is not None:
        files["climate.epw"] = assessment.epw
    files["files.json"] = json_bytes({name: {"sha256": sha256(body).hexdigest(), "bytes": len(body)}
                                      for name, body in files.items()})
    return StationYearProduct(request, report, files, _zip(files))


def asdict_source(name, definition, canonical):
    flags = canonical.get(definition.quality_column, pd.Series(dtype=float))
    return {"field": name, "provider_field": definition.provider_field,
            "definition": definition.quantity_definition,
            "numeric_records": int(pd.to_numeric(canonical.get(name, pd.Series(dtype=float)), errors="coerce").notna().sum()),
            "quality_histogram": {str(k): int(v) for k, v in flags.value_counts().items()}}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station")
    parser.add_argument("--year", type=int)
    parser.add_argument("--label")
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--sha256", default="")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.replay:
        packet = args.replay.read_bytes()
        manifest, _ = read_sources(packet, args.sha256)
        request = StationYearRequest(**manifest["request"])
        if ((args.station and args.station != request.station_id)
                or (args.year and args.year != request.year)):
            parser.error("Replay station/year differs from the retained request.")
        product = run_station_year(request, source_packet=packet, expected_sha256=args.sha256)
    else:
        if not args.station or args.year is None:
            parser.error("An online request requires --station and --year.")
        request = StationYearRequest(args.station, args.year, 60, args.label or f"Station {args.station}")
        product = run_station_year(request, progress=lambda e: print(json.dumps(e), flush=True))
    args.out.mkdir(parents=True, exist_ok=False)
    for name, body in product.files.items():
        (args.out / name).write_bytes(body)
    (args.out / "station-year.zip").write_bytes(product.archive)
    print(json.dumps({"status": product.report["status"], "expected_hours": product.report["expected_hours"],
                      "source_rows": product.report["source_rows"], "EPW_written": "climate.epw" in product.files}))


if __name__ == "__main__": main()
