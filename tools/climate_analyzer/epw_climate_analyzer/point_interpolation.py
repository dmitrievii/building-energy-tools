"""S1 source admission and replayable point products. Acquisitions are explicit.

GeoSphere years reuse H1's unchanged field/QC/time admission. Uploaded EPWs
need a declared real year and identical fixed-clock coverage; TMY chronology is
not silently aligned. An optional gridded background is separately attributed.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import csv
import gzip
import io
import json
import re
import time
import zipfile

import numpy as np
import pandas as pd

from .climate_model import ClimateLocation
from .engine.contracts import ClimateResult, FieldDefinition, QualityStatus
from .engine.epw import EPW_FIELDS, serialize_epw, validate_epw_bytes
from .engine.historical import json_bytes
from .engine.point_interpolation import (CORE, E, P, RH, T, TD, PointDonor,
    PointRequest, distance_km, interpolate_point, qualify_donor, saturation_buck_hpa)
from .engine.station_epw_admission import StationYearRequest
from . import geosphere as geo
from .geosphere_station_year import (RESOURCE, StationYearProduct, _zip, read_sources,
    run_station_year)

MAX_INPUT_BYTES = 128*1024*1024
MAX_EPW_BYTES = 12*1024*1024


@dataclass(frozen=True)
class PointProduct:
    request: PointRequest
    report: dict
    files: dict[str, bytes]
    archive: bytes


def donor_from_station_year(product: StationYearProduct) -> PointDonor:
    """A station may supply core T/p/RH while its full H1 EPW remains blocked."""
    report = product.report
    r = product.request
    frame = pd.read_csv(io.BytesIO(gzip.decompress(product.files["hourly_states.csv.gz"])), index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    fields = {v["field"]: v for v in report["fields"]}
    blockers = list(report["global_blockers"])
    for name in (T, P, RH):
        if fields.get(name, {}).get("status") != "ADMITTED":
            blockers.append("H1_CORE_NOT_ADMITTED_"+name)
    # Only derive values inside the Buck formula domain. Missing/rejected source
    # values remain missing and cannot qualify via row-count-only screening.
    frame[E] = np.nan
    if T in frame and RH in frame:
        good = np.isfinite(frame[T]) & np.isfinite(frame[RH]) & frame[T].between(-75, 65) & frame[RH].between(0, 105)
        frame.loc[good, E] = frame.loc[good, RH].to_numpy()/100*saturation_buck_hpa(frame.loc[good, T])
    location = ClimateLocation(**report["location"])
    return PointDonor(r.station_id, location, frame, r.year, location.elevation_m, location.elevation_m,
        "GeoSphere published nominal station altitude; sensor elevations and common vertical datum unconfirmed",
        True, report["source_metadata"]["source_packet_sha256"], "GEOSPHERE_H1_ENDPOINTS_BUCK_RH_ASSUMPTION",
        tuple(blockers), source_admission=report, source_gaps_csv_gz=product.files["missing_hours.csv.gz"])


def donor_from_epw(body: bytes, request: PointRequest, *, actual_year_confirmed: bool, name="Uploaded EPW") -> PointDonor:
    if len(body) > MAX_EPW_BYTES: raise ValueError("S1_EPW_SIZE_LIMIT")
    if actual_year_confirmed is not True: raise ValueError("S1_EPW_ACTUAL_YEAR_CONFIRMATION_REQUIRED")
    records = list(csv.reader(io.StringIO(body.decode("utf-8-sig", errors="strict"))))
    header_names = ["LOCATION", "DESIGN CONDITIONS", "TYPICAL/EXTREME PERIODS", "GROUND TEMPERATURES",
        "HOLIDAYS/DAYLIGHT SAVINGS", "COMMENTS 1", "COMMENTS 2", "DATA PERIODS"]
    if len(records) < 8 or [v[0] if v else "" for v in records[:8]] != header_names:
        raise ValueError("S1_EPW_HEADER_CONTRACT")
    headers, rows = records[:8], records[8:]
    descriptor = " ".join(" ".join(row) for row in headers)
    if re.search(r"\b(TMY\w*|TRY|IWEC\w*|CWEC\w*|Meteonorm)\b|REPRESENTATIVE FUTURE", descriptor, re.I):
        raise ValueError("S1_TMY_OR_FUTURE_CHRONOLOGY_NOT_ADMITTED")
    if len(headers[0]) < 10 or len(headers[7]) < 7 or headers[7][1:3] != ["1", "1"]:
        raise ValueError("S1_ONE_HOURLY_EPW_PERIOD_REQUIRED")
    try:
        lat, lon, offset, z = map(float, headers[0][6:10])
    except (ValueError, TypeError) as exc:
        raise ValueError("S1_EPW_LOCATION_REQUIRED") from exc
    if not np.isfinite([lat, lon, offset, z]).all() or not -500 <= z <= 9000:
        raise ValueError("S1_EPW_LOCATION_OR_HEIGHT_INVALID")
    if offset*60 != request.utc_offset_minutes:
        raise ValueError("S1_EPW_OFFSET_MISMATCH_NO_IMPLICIT_BOUNDARY_WRAP")
    if len(rows) != len(request.local_starts) or any(len(row) != 35 for row in rows):
        raise ValueError("S1_EPW_COMPLETE_ACTUAL_YEAR_REQUIRED")
    for row, stamp in zip(rows, request.local_starts):
        try:
            same = list(map(int, row[:5])) == [request.year, stamp.month, stamp.day, stamp.hour+1, 60]
        except ValueError:
            same = False
        if not same: raise ValueError("S1_EPW_YEAR_DATE_ORDER_OR_HOURLY_GRID_MISMATCH")
    frame = pd.DataFrame(index=request.utc_starts)
    for col in (T, P, RH, TD):
        frame[col] = pd.to_numeric(pd.Series([row[EPW_FIELDS[col][0]] for row in rows]), errors="coerce").to_numpy()
    valid_td = np.isfinite(frame[TD]) & frame[TD].between(-75, 65)
    frame[E] = np.nan
    frame.loc[valid_td, E] = saturation_buck_hpa(frame.loc[valid_td, TD])
    digest = sha256(body).hexdigest()
    location = ClimateLocation(lat, lon, z, headers[0][1], headers[0][2], headers[0][3], headers[0][5])
    blockers = []
    if np.any(frame[TD] > frame[T]+.100001): blockers.append("EPW_SOURCE_DEWPOINT_ABOVE_T")
    return PointDonor("EPW:"+digest[:16], location, frame, request.year, z, z,
        "EPW LOCATION altitude; actual sensor heights and vertical datum unconfirmed", True, digest,
        "DECLARED_ACTUAL_YEAR_EPW_BUCK_DEWPOINT_ASSUMPTION", tuple(blockers))


def _source_inputs(request, mode, entries, files):
    manifest = {"schema": "IGE_S1_ORIGINAL_INPUTS_v1", "request": request.to_dict(),
                "mode": mode, "entries": entries,
                "members": {name: {"sha256": sha256(body).hexdigest(), "bytes": len(body)}
                            for name, body in files.items()}}
    return _zip({**files, "manifest.json": json_bytes(manifest)})


def _read_input_packet(body, expected_sha256):
    if not expected_sha256 or sha256(body).hexdigest() != expected_sha256:
        raise ValueError("S1_INPUT_PACKET_HASH_MISMATCH")
    if len(body) > MAX_INPUT_BYTES: raise ValueError("S1_INPUT_PACKET_SIZE_LIMIT")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 64 or sum(v.file_size for v in archive.infolist()) > MAX_INPUT_BYTES:
            raise ValueError("S1_INPUT_PACKET_CENSUS_LIMIT")
        if any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,90}", name) for name in names) or any(
                (v.external_attr >> 16) & 0o170000 == 0o120000 for v in archive.infolist()):
            raise ValueError("S1_INPUT_PACKET_UNSAFE_MEMBER")
        if "manifest.json" not in names: raise ValueError("S1_INPUT_MANIFEST_MISSING")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema") != "IGE_S1_ORIGINAL_INPUTS_v1": raise ValueError("S1_INPUT_SCHEMA")
        if manifest.get("mode") not in ("GEOSPHERE", "EPW"): raise ValueError("S1_INPUT_MODE_NOT_ADMITTED")
        members = manifest["members"]
        if set(names) != set(members) | {"manifest.json"}: raise ValueError("S1_INPUT_PACKET_MEMBER_MISMATCH")
        files = {name: archive.read(name) for name in members}
    for name, value in files.items():
        if len(value) != members[name]["bytes"] or sha256(value).hexdigest() != members[name]["sha256"]:
            raise ValueError("S1_INPUT_MEMBER_HASH_MISMATCH")
    if not 0 <= len(manifest["entries"]) <= 20: raise ValueError("S1_CANDIDATE_LIMIT")
    if {entry["file"] for entry in manifest["entries"]} - set(files): raise ValueError("S1_INPUT_ENTRY_FILE_MISSING")
    return manifest, files


def _replay_donors(request, body, digest):
    manifest, files = _read_input_packet(body, digest)
    if manifest["request"] != request.to_dict(): raise ValueError("S1_REPLAY_REQUEST_MISMATCH")
    donors = []
    mode = manifest["mode"]
    for entry in manifest["entries"]:
        raw = files[entry["file"]]
        if mode == "GEOSPHERE":
            original, _ = read_sources(raw, sha256(raw).hexdigest())
            station_request = StationYearRequest(**original["request"])
            if entry.get("station_id") != station_request.station_id:
                raise ValueError("S1_REPLAY_STATION_IDENTITY_MISMATCH")
            if (station_request.year, station_request.utc_offset_minutes) != (request.year, request.utc_offset_minutes):
                raise ValueError("S1_REPLAY_STATION_YEAR_OR_OFFSET_MISMATCH")
            product = run_station_year(station_request, source_packet=raw, expected_sha256=sha256(raw).hexdigest())
            donors.append(donor_from_station_year(product))
        elif mode == "EPW":
            donors.append(donor_from_epw(raw, request, actual_year_confirmed=entry["actual_year_confirmed"]))
        else:
            raise ValueError("S1_INPUT_MODE_NOT_ADMITTED")
    return donors, manifest


def _acquire_stations(request, progress):
    raw_metadata = []
    def capture(url, query, body): raw_metadata.append(body)
    metadata = geo.fetch_metadata(resource_id=RESOURCE, response_capture=capture)
    sites = sorted(geo.parse_stations(metadata), key=lambda station: (
        distance_km(request.latitude, request.longitude, station.latitude, station.longitude), station.station_id))
    census, selected = [], []
    for station in sites:
        d = distance_km(request.latitude, request.longitude, station.latitude, station.longitude)
        if d > 100: continue
        if station.station_type == "COMBINED":
            census.append({"station_id": station.station_id, "reason": "COMBINED_SERIES_NOT_ONE_FIXED_SITE"})
            continue
        if station.station_id == request.excluded_station_id: continue
        if station.elevation_m is None or not np.isfinite(station.elevation_m) or abs(station.elevation_m-request.elevation_m) > 1500:
            census.append({"station_id": station.station_id, "reason": "METADATA_HEIGHT_UNAVAILABLE_OR_OUTSIDE_OPERATIONAL_DIFFERENCE"})
            continue
        start, end = pd.to_datetime(station.valid_from, utc=True), pd.to_datetime(station.valid_to, utc=True)
        if pd.isna(start) or pd.isna(end) or start > request.utc_starts[0]+pd.Timedelta(hours=1) or end < request.utc_starts[-1]+pd.Timedelta(hours=1):
            census.append({"station_id": station.station_id, "reason": "METADATA_VALIDITY_DOES_NOT_COVER_YEAR"})
            continue
        selected.append(station)
        if len(selected) == 20: break
    donors, entries, files = [], [], {}
    if not raw_metadata: raise ValueError("S1_ORIGINAL_METADATA_CAPTURE_MISSING")
    files["catalog.original.json"] = raw_metadata[0]
    for station in selected:
        progress(f"Checking donor {station.station_id}: {station.name} ({len(donors)+1}/20)")
        station_request = StationYearRequest(station.station_id, request.year, request.utc_offset_minutes,
            station.name.replace(",", ";").replace("\n", " ").replace("\r", " ")[:120])
        try:
            product = run_station_year(station_request)
        except Exception as exc:
            census.append({"station_id": station.station_id, "reason": "SOURCE_ACQUISITION_FAILED",
                           "detail": type(exc).__name__+": "+str(exc)})
            continue
        donor = donor_from_station_year(product)
        donors.append(donor)
        filename = f"station_{station.station_id}.sources.zip"
        files[filename] = product.files["sources.zip"]
        if sum(len(body) for body in files.values()) > MAX_INPUT_BYTES:
            raise ValueError("S1_ORIGINAL_SOURCE_COLLECTION_LIMIT")
        entries.append({"file": filename, "station_id": station.station_id})
        if sum(qualify_donor(request, d)["eligible"] for d in donors) >= 4: break
    extra = {"candidate_metadata_exclusions": census,
        "search_exhaustive_beyond_nearest_twenty_eligible_metadata_sites": False}
    files["search_census.json"] = json_bytes(extra)
    packet = _source_inputs(request, "GEOSPHERE", entries, files)
    return donors, packet, extra


def replay_background(request, packet: bytes, expected_sha256: str):
    """Reassemble background from its original, hash-pinned bodies, without HTTP."""
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from types import SimpleNamespace
    from .engine.historical import read_source_bundle, assemble_historical
    from .engine.contracts import HistoricalRequest
    if not expected_sha256 or sha256(packet).hexdigest() != expected_sha256:
        raise ValueError("S1_BACKGROUND_SOURCE_HASH_MISMATCH")
    if len(packet) > MAX_INPUT_BYTES: raise ValueError("S1_BACKGROUND_PACKET_LIMIT")
    with zipfile.ZipFile(io.BytesIO(packet)) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_INPUT_BYTES:
            raise ValueError("S1_BACKGROUND_EXPANDED_SIZE_LIMIT")
        original = HistoricalRequest(**json.loads(archive.read("manifest.json"))["request"])
    if (original.latitude, original.longitude, original.year, original.utc_offset_minutes) != (
            request.latitude, request.longitude, request.year, request.utc_offset_minutes):
        raise ValueError("S1_BACKGROUND_WEATHER_REQUEST_MISMATCH")
    with TemporaryDirectory(prefix="ige-s1-background-") as folder:
        path = Path(folder)/"sources.zip"; path.write_bytes(packet)
        payloads, receipts = read_source_bundle(path, expected_sha256, original)
    # The original request and bytes remain untouched. Its label/optional site
    # height are metadata only in B0; S1 applies the target height separately.
    climate = assemble_historical(original, payloads, receipts)
    epw, _ = serialize_epw(climate)
    location = climate.location
    geometry = {"requested_point": [request.latitude, request.longitude],
        "background_cell": [location.latitude, location.longitude],
        "requested_to_background_distance_km": distance_km(request.latitude, request.longitude, location.latitude, location.longitude),
        "elevation_m_provider_response_proxy": location.elevation_m,
        "site_elevation_or_native_orography_verified": False, "local_height_correction_applied": False}
    return SimpleNamespace(dataset=climate.to_canonical(),
        report={"calendar_mode": "historical", "source_geometry": geometry,
                "original_background_request": original.to_dict()},
        files={"sources.zip": packet, "climate.epw": epw})


def _composite_epw(request, assessment, background):
    """Explicit mixed-source option; no claim to interpolate all weather fields."""
    base = background.dataset
    if background.report.get("calendar_mode") != "historical": raise ValueError("S1_BACKGROUND_MUST_BE_HISTORICAL")
    f = base.data.copy()
    if f.index.tz is None: raise ValueError("S1_BACKGROUND_EXPLICIT_CLOCK_REQUIRED")
    f.index = f.index.tz_convert("UTC")
    if not f.index.equals(request.utc_starts): raise ValueError("S1_BACKGROUND_ANNUAL_CLOCK_MISMATCH")
    geometry = background.report["source_geometry"]
    requested = geometry["requested_point"]
    if list(requested) != [request.latitude, request.longitude]: raise ValueError("S1_BACKGROUND_REQUESTED_POINT_MISMATCH")
    data = f[list(EPW_FIELDS)].copy()
    for name in (T, P, RH, TD): data[name] = assessment.hourly[name]
    definitions = {name: FieldDefinition(unit, operator,
        "S1" if name in (T, P, RH, TD) else "background",
        f"target {request.elevation_m:g} m; {request.elevation_reference}" if name in (T, P, RH, TD) else "background source geometry retained",
        "Frozen P8.2F-derived Buck liquid-water point state" if name in (T, P, RH, TD) else
        "Inherited unchanged from explicitly selected ERA5-derived / POWER background; not station interpolated")
        for name, (_, unit, operator) in EPW_FIELDS.items()}
    location = ClimateLocation(request.latitude, request.longitude, request.elevation_m, request.label)
    result = ClimateResult(request.background_request(), data, location, definitions,
        ({"id": "S1"}, {"id": "background"}), (), (),
        QualityStatus("COMPLETE_ANNUAL_ASSEMBLY", "T_P_E_RH_TD_CLOSURE", "NOT_INDEPENDENTLY_QUALIFIED", "S1_MIXED_SOURCE_RESEARCH"), {})
    epw, screen = serialize_epw(result)
    records = list(csv.reader(io.StringIO(epw.decode())))
    records[0][1] = request.label+" INTERPOLATED T P MOISTURE RESEARCH"
    records[0][4] = "IGE_S1_STATIONS_OR_EPW_WITH_GRID_BACKGROUND"
    records[5] = ["COMMENTS 1", "S1: T/p/moisture interpolated with active height corrections. Other weather fields retain selected background, its grid geometry and chronology. See report.json and ledgers."]
    records[6] = ["COMMENTS 2", "Buck liquid water at all T; nominal height proxies explicitly accepted. Local wind/radiation/rain accuracy and target solar geometry not independently qualified. Research composite, not a fully observed station year."]
    records[7][3] = f"S1 MIXED SOURCE HISTORICAL {request.year} RESEARCH"
    stream = io.StringIO(newline=""); csv.writer(stream, lineterminator="\n").writerows(records)
    epw = stream.getvalue().encode()
    screen.update(validate_epw_bytes(epw, result))
    return epw, screen, geometry


def run_point_product(request: PointRequest, *, mode="GEOSPHERE", epws=(), actual_year_confirmed=False,
                      input_packet=None, expected_sha256="", include_background=False, background_product=None,
                      background_packet=None, background_sha256="",
                      progress=lambda message: None) -> PointProduct:
    """One explicit request; no acquisition on edits and no implicit saved-city fallback."""
    run_started = time.monotonic()
    if not request.assume_buck_water or not request.allow_nominal_height_proxy:
        raise ValueError("S1_EXPLICIT_PHASE_AND_HEIGHT_PROXY_ACCEPTANCE_REQUIRED_FOR_CURRENT_ADAPTERS")
    if len(epws) > 20 or sum(len(body) for name, body in epws) > MAX_INPUT_BYTES:
        raise ValueError("S1_INPUT_LIMIT")
    replay = input_packet is not None
    extra = {}
    if replay:
        donors, manifest = _replay_donors(request, input_packet, expected_sha256)
        mode = manifest["mode"]
        _, input_files = _read_input_packet(input_packet, expected_sha256)
        if "search_census.json" in input_files: extra = json.loads(input_files["search_census.json"])
    elif mode == "GEOSPHERE":
        donors, input_packet, extra = _acquire_stations(request, progress)
    elif mode == "EPW":
        donors, entries, raw_files = [], [], {}
        for i, (name, body) in enumerate(epws):
            donor = donor_from_epw(body, request, actual_year_confirmed=actual_year_confirmed, name=name)
            donors.append(donor)
            filename = f"donor_{i:02d}.epw"
            raw_files[filename] = body
            entries.append({"file": filename, "original_name": name, "actual_year_confirmed": actual_year_confirmed})
        input_packet = _source_inputs(request, "EPW", entries, raw_files)
    else:
        raise ValueError("S1_UNKNOWN_SOURCE_MODE")
    # Admission and equations are shared by live sources and offline replay.
    started = pd.Timestamp.now(tz="UTC")
    assessment = interpolate_point(request, donors)
    report = {**assessment.report, **extra, "source_mode": mode, "offline_donor_replay": replay,
        "donor_source_packet_sha256": sha256(input_packet).hexdigest(),
        "background_requested": include_background, "background_status": "NOT_REQUESTED",
        "EPW_status": "BLOCKED_MISSING_NONTHERMODYNAMIC_FIELDS", "EPW_blockers": [],
        "future_base_status": "NOT_YET_ADMITTED_FOR_F1; local reference period and GCM signals must be admitted separately",
        "core_calculation_seconds": (pd.Timestamp.now(tz="UTC")-started).total_seconds(),
        "offline_core_and_replay_make_no_weather_requests": replay}
    files = {"inputs.zip": input_packet,
        "hourly.csv.gz": gzip.compress(assessment.hourly.to_csv(index_label="interval_start_utc").encode(), mtime=0),
        "adjustments.csv.gz": gzip.compress(assessment.adjustments.to_csv(index_label="interval_start_utc").encode(), mtime=0),
        "donor_months.csv": assessment.donor_months.to_csv(index=False).encode()}
    report["donor_source_reports"] = []
    for i, donor in enumerate(donors):
        if donor.source_admission:
            name = f"source_admission_{i:02d}.json"
            gaps = f"source_missing_hours_{i:02d}.csv.gz"
            files[name] = json_bytes(donor.source_admission)
            files[gaps] = donor.source_gaps_csv_gz
            report["donor_source_reports"].append({"station_id": donor.station_id,
                                                 "admission": name, "gap_ledger": gaps})
    if len(assessment.hourly.columns) == 0:
        report["EPW_status"] = "BLOCKED_INCOMPLETE_THERMODYNAMIC_POINT_YEAR"
        report["EPW_blockers"].extend(report["global_blockers"])
        report["background_status"] = "NOT_ACQUIRED_CORE_BLOCKED" if include_background else "NOT_REQUESTED"
    elif include_background:
        try:
            if background_packet is not None:
                background_product = replay_background(request, background_packet, background_sha256)
            elif background_product is None:
                from .engine_application import run_historical_product
                progress("Loading the explicitly selected grid background for non-thermodynamic fields")
                background_product = run_historical_product(request.background_request(), use_saved_pilot=False, progress=progress)
            epw, screen, geometry = _composite_epw(request, assessment, background_product)
            files["climate.epw"] = epw
            files["background.sources.zip"] = background_product.files["sources.zip"]
            files["background.epw"] = background_product.files["climate.epw"]
            files["background.report.json"] = json_bytes(background_product.report)
            report.update(EPW_status="ADMITTED_MIXED_SOURCE_RESEARCH", background_status="ADMITTED",
                background_source_geometry=geometry, EPW_screen=screen,
                background_EPW_sha256=sha256(background_product.files["climate.epw"]).hexdigest())
            report["field_sources"] = {name: "S1_P82F_DERIVED_POINT" if name in (T, P, RH, TD)
                                      else "UNCHANGED_GRID_BACKGROUND" for name in EPW_FIELDS}
        except Exception as exc:
            report["background_status"] = "BLOCKED"
            report["EPW_blockers"].append(type(exc).__name__+": "+str(exc))
    else:
        report["EPW_blockers"] = ["NO_ADMITTED_SOURCE_FOR_"+name for name in EPW_FIELDS if name not in (T, P, RH, TD)]
    report["EPW_sha256"] = sha256(files["climate.epw"]).hexdigest() if "climate.epw" in files else None
    report["total_calculation_seconds"] = time.monotonic()-run_started
    report["timing_and_acquisition_diagnostics_are_not_part_of_the_stable_weather_identity"] = True
    report["selected_base_sha256"] = report["EPW_sha256"] or sha256(files["hourly.csv.gz"]).hexdigest()
    files["report.json"] = json_bytes(report)
    files["files.json"] = json_bytes({name: {"bytes": len(body), "sha256": sha256(body).hexdigest()} for name, body in files.items()})
    return PointProduct(request, report, files, _zip(files))


def main():
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, help="PointRequest JSON for a live GeoSphere acquisition")
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--background", action="store_true", help="Explicitly request grid background; not an offline operation")
    parser.add_argument("--background-replay", type=Path, help="Replay the separate original background source packet without HTTP")
    parser.add_argument("--background-sha256")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.replay:
        packet = args.replay.read_bytes(); manifest, _ = _read_input_packet(packet, args.sha256)
        request = PointRequest(**manifest["request"])
        product = run_point_product(request, input_packet=packet, expected_sha256=args.sha256,
            include_background=args.background or args.background_replay is not None,
            background_packet=args.background_replay.read_bytes() if args.background_replay else None,
            background_sha256=args.background_sha256 or "")
    else:
        if not args.request: parser.error("Choose --request or --replay with --sha256")
        request = PointRequest(**json.loads(args.request.read_bytes()))
        product = run_point_product(request, include_background=args.background, progress=print)
    args.out.mkdir(parents=True, exist_ok=False)
    for name, body in product.files.items(): (args.out/name).write_bytes(body)
    (args.out/"point-year.zip").write_bytes(product.archive)
    print(json.dumps({key: product.report[key] for key in ("status", "selected_donors", "EPW_status", "EPW_sha256")}))


if __name__ == "__main__":
    main()
