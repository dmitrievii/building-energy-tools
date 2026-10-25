"""Replay dated source admission, without opening weather or control values.

Frozen A1.1 IDs/windows are inputs, not reselected after an admission failure.
Actual instrument heights are retained even when strict T2m is ineligible.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import csv
import io
import json
import math
from pathlib import Path
import sys
import zipfile
import zlib
from xml.etree import ElementTree as ET

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "research/ige_cmip6"
sys.path.insert(0, str(ROOT / "tools/climate_analyzer"))
from a1_prepare import metadata_sources
from epw_climate_analyzer.station_admission import admitted_reference, physical_identity
from epw_climate_analyzer.station_reconstruction import StationReference, distance_km
from p9_3b3_native_heights import sensor_records, dates, NS, H

PROTOCOL_SHA = "a8a5c3a5898f58058ce1fd2c86e85002fc46249a9e367d1d76e4f8a0fbd05ec4"
PACKET = "a12_history_sources_20261025.zip"
PACKET_SHA = "fba7e6a447dd70b155fafce712a40c7bb2fac498aa6facf2dbdc665c5f699f83"


def verify_metadata_ranges(proof, bodies):
    """Validate the retained range ledger against the ZIP member census.

    Hashes authenticate the pinned receipt; raw HTTP range bytes are not all
    retained. No observation payload is reconstructed to verify this ledger.
    """
    requests = proof["requests"]; total = proof["container_bytes"]
    if not 2 < len(requests) <= 20 or requests[0]["range"] != [total - 22, total - 1]:
        raise ValueError("A12_RANGE_LEDGER_END_OR_BUDGET")
    central_a, central_b = requests[1]["range"]
    if central_b != total - 23: raise ValueError("A12_RANGE_LEDGER_CENTRAL_DIRECTORY")
    members = sorted(proof["members"], key=lambda r: r["offset"])
    metadata_spans = []
    for i, member in enumerate(members):
        name = member["name"]
        if name.startswith(("Metadaten_Parameter", "Metadaten_Geographie", "Metadaten_Geraete")) and name.endswith(".txt"):
            metadata_spans.append((member["offset"], members[i+1]["offset"] if i+1 < len(members) else central_a))
            key = "DE_" + proof["station_id"] + "__" + name
            body = bodies[key]
            if len(body) != member["uncompressed"] or zlib.crc32(body) != member["crc32"]:
                raise ValueError("A12_RETAINED_DWD_MEMBER_CRC_OR_LENGTH")
    for request in requests:
        a, b = request["range"]
        if not (0 <= a <= b < total and b-a+1 == request["bytes"] and request["ETag"] == proof["ETag"]):
            raise ValueError("A12_RANGE_LEDGER_SIZE_OR_ETAG")
        if a >= central_a: continue  # Member directory and EOCD, no products.
        if not any(lo <= a <= b < hi for lo, hi in metadata_spans):
            raise ValueError("A12_RANGE_LEDGER_TOUCHES_NON_METADATA_MEMBER")
    for key in ("whole_archive_body_read", "observation_product_members_requested", "observation_product_members_decompressed"):
        if proof[key] is not False: raise ValueError("A12_OBSERVATION_MEMBER_OPENED")
    return len(requests), sum(r["bytes"] for r in requests)


def history_sources(raw=None):
    raw = (R / PACKET).read_bytes() if raw is None else raw
    if sha256(raw).hexdigest() != PACKET_SHA: raise ValueError("A12_HISTORY_PACKET_HASH")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(Path(n).name != n for n in names):
            raise ValueError("A12_HISTORY_PACKET_NAMES")
        if any(x.file_size > 3_000_000 for x in archive.infolist()): raise ValueError("A12_HISTORY_PACKET_MEMBER_SIZE")
        manifest = json.loads(archive.read("manifest.json"))
        if set(names) != set(manifest["member_sha256"]) | {"manifest.json"}: raise ValueError("A12_HISTORY_MEMBER_CENSUS")
        bodies = {n: archive.read(n) for n in manifest["member_sha256"]}
        for name, digest in manifest["member_sha256"].items():
            if sha256(bodies[name]).hexdigest() != digest: raise ValueError("A12_HISTORY_MEMBER_HASH:" + name)
    assert manifest["raw_2025_measurement_values_opened"] is False
    assert manifest["IV1_observation_values_opened"] is False
    assert manifest["DWD_product_members_requested"] is False
    costs = [verify_metadata_ranges(json.loads(b), bodies) for n, b in bodies.items() if n.endswith("range_proof.json")]
    if len(costs) != 8 or sum(c[0] for c in costs) != manifest["range_requests"] or sum(c[1] for c in costs) != manifest["range_body_bytes"]:
        raise ValueError("A12_RANGE_PACKET_TOTALS")
    return bodies, manifest


def dated_rows(raw, station_id, start_column, end_column, first, last, *, parameter=None):
    """DWD date fields are inclusive calendar dates; blank end is open.

    A row must cover the entire requested support. Gaps/overlaps are never
    resolved by choosing the newest row. Footer/legend lines are not data.
    """
    source = csv.DictReader(io.StringIO(raw.decode("cp1252")), delimiter=";")
    source.fieldnames = [s.strip() for s in source.fieldnames]
    rows = []
    for raw_row in source:
        row = {k: (v or "").strip() for k, v in raw_row.items() if k is not None}
        sid = row.get("Stations_ID", row.get("Stations_id", ""))
        if not sid.isdigit(): continue
        if int(sid) != int(station_id): raise ValueError("A12_DWD_CROSS_STATION_METADATA")
        if parameter is not None and row.get("Parameter") != parameter: continue
        a, b = row.get(start_column, ""), row.get(end_column, "")
        if len(a) != 8 or not a.isdigit() or (b and (len(b) != 8 or not b.isdigit())):
            raise ValueError("A12_DWD_INVALID_METADATA_PERIOD")
        begin = pd.to_datetime(a, format="%Y%m%d", utc=True)
        end = pd.to_datetime(b, format="%Y%m%d", utc=True) + pd.Timedelta(days=1) if b else None
        covers = begin <= first and (end is None or last < end)
        if begin <= last and (end is None or end > first) and not covers:
            raise ValueError("A12_DWD_METADATA_PERIOD_CROSSES_REQUEST_SUPPORT")
        if covers: rows.append(row)
    return rows


def dwd_geometry(bodies, sid, first, last):
    prefix = "DE_" + sid + "__"
    names = [prefix + "Metadaten_" + s + "_" + sid + ".txt" for s in ("Geographie", "Geraete_Lufttemperatur", "Parameter_tu_stunde")]
    geography, devices, parameters = [bodies[n] for n in names]
    geos = dated_rows(geography, sid, "von_datum", "bis_datum", first, last)
    sensors = dated_rows(devices, sid, "Von_Datum", "Bis_Datum", first, last)
    pars = dated_rows(parameters, sid, "Von_Datum", "Bis_Datum", first, last, parameter="TT_TU")
    if len(geos) != 1 or len(sensors) != 1 or len(pars) != 1: raise ValueError("A12_DWD_DATED_GEOMETRY_OR_PARAMETER_NOT_UNIQUE")
    geo, device, parameter = geos[0], sensors[0], pars[0]
    latitude, longitude = float(geo["Geogr.Breite"]), float(geo["Geogr.Laenge"])
    ground, height = float(geo["Stationshoehe"]), float(device["Geberhoehe ueber Grund [m]"])
    if abs(ground - float(device["Stationshoehe [m]"])) > 1e-9:
        raise ValueError("A12_DWD_GEOGRAPHY_DEVICE_GROUND_CONFLICT")
    # Device coordinates in this table are rounded to .01 degree, unlike the
    # dated geography table. Test their rounding cells, not exact equality.
    if (abs(latitude - float(device["Geo. Breite [Grad]"])) > .005000001
            or abs(longitude - float(device["Geo. Laenge [Grad]"])) > .005000001):
        raise ValueError("A12_DWD_DEVICE_GEOGRAPHY_COORDINATE_CONFLICT")
    if parameter["Einheit"] != "°C": raise ValueError("A12_DWD_TEMPERATURE_UNIT")
    return {"latitude": latitude, "longitude": longitude, "AGL_m": height,
        "local_reference_surface": "localGround", "site_altitude_as_reported_m": ground,
        "geospatial_z_as_reported_m": ground + height,
        "height_origin": "DWD_DATED_GROUND_PLUS_SEPARATE_SENSOR_AGL",
        "deployment_period_inclusive_dates": [device["Von_Datum"], device["Bis_Datum"]],
        "geography_period_inclusive_dates": [geo["von_datum"], geo["bis_datum"]],
        "device_type": device["Geraetetyp Name"], "datum_transformation_verified": False,
        "parameter_row": parameter}, {n: sha256(bodies[n]).hexdigest() for n in names}


def wmdr_geometry(raw, wsi, country, first, last):
    # The old parser accepts exact UTC hours. Rounding CH's first H-50 support
    # down to H-1 conservatively requires ten additional minutes of geometry.
    bounds = [first.floor("h").isoformat(), last.ceil("h").isoformat()]
    try:
        # Several Swiss sites also register the separate 5-cm air channel under
        # variable224. Select the source field's documented 2-m channel before
        # examining a non-2-m fallback. An ambiguous 2-m channel stays blocked.
        record = sensor_records(raw, wsi, 224, bounds, "THERMO_SENSOR")
        selection = "UNIQUE_DATED_EXACT_2M_LOCAL_GROUND_CHANNEL; separate 5cm channels excluded"
    except ValueError as exc:
        if str(exc) != "P93N_NO_DATED_SENSOR_REFERENCE:224": raise
        record = sensor_records(raw, wsi, 224, bounds, "TEMPERATURE_SOURCE_ACTUAL_HEIGHT")
        selection = "NO_EXACT_2M_CHANNEL; unique actual height reported, no strict T2m admission"
    # Do not ignore an alternative deployment/location that covers only part
    # of the support. The older single-record parser intentionally selects full
    # spans; this additional A1.2 check makes partial overlap fail closed.
    bound_first, bound_last = map(pd.Timestamp, bounds)
    def complete_or_disjoint(period):
        a, b = period
        if not a: raise ValueError("A12_WMDR_CHANNEL_PERIOD_UNDATED")
        begin = pd.Timestamp(a); end = pd.Timestamp(b) if b else None
        begin = begin.tz_localize("UTC") if begin.tz is None else begin.tz_convert("UTC")
        if end is not None: end = end.tz_localize("UTC") if end.tz is None else end.tz_convert("UTC")
        if begin <= bound_last and (end is None or end > bound_first):
            if begin > bound_first or (end is not None and end <= bound_last):
                raise ValueError("A12_WMDR_PARTIAL_OVERLAP_REQUIRES_SEGMENTED_GEOMETRY")
            return True
        return False
    for obs in ET.fromstring(raw).findall('.//o:OM_Observation', NS):
        prop = obs.find('o:observedProperty', NS)
        if prop is None or prop.get(H) != record['observed_property']: continue
        for dep in obs.findall('.//w:Deployment', NS):
            agl = dep.find('w:heightAboveLocalReferenceSurface', NS)
            ref = dep.find('w:localReferenceSurface', NS)
            if (agl is None or not (agl.text or '').strip() or float(agl.text) != record['AGL_or_reference_distance_m']
                    or ref is None or ref.get(H) != record['local_reference_surface']): continue
            if not complete_or_disjoint(dates(dep.find('w:validPeriod', NS))): continue
            for loc in dep.findall('w:deployedEquipment/w:Equipment/w:geospatialLocation/w:GeospatialLocation', NS):
                period = dates(loc.find('w:validPeriod', NS))
                if period[0]: complete_or_disjoint(period)
    surface = record["local_reference_surface"].rsplit("/", 1)[-1]
    return {"latitude": record["latitude"], "longitude": record["longitude"],
        "AGL_m": record["AGL_or_reference_distance_m"], "local_reference_surface": surface, "channel_selection": selection,
        "geospatial_z_as_reported_m": record["height_MSL_m"],
        "height_origin": "WMDR_EQUIPMENT_GEOPOSITION_Z_AS_REPORTED_AGL_NOT_ADDED_AGAIN",
        "deployment_period_half_open": record["deployment_period"],
        "location_period_half_open": record["equipment_geolocation_period"],
        "location_time_support": record["geolocation_time_support"], "source_WSI": wsi,
        "parser_geometry_check_bounds_UTC": bounds, "datum_transformation_verified": False,
        "equipment_z_to_model_orography_transformation_qualified": False}


def station_window(station, window, bodies, acquisition, old_bodies, identity):
    country, sid = station["country"], station["station_id"]
    key = country + ":" + sid
    first = pd.Timestamp(window["start_UTC"], tz="UTC")
    last = pd.Timestamp(window["end_UTC"], tz="UTC") + pd.Timedelta(hours=23)
    support_first = first - pd.Timedelta(minutes=50) if country == "CH" else first
    operator = {"AT": "published_nominal_node", "CH": "mean_six_10min_nominal_nodes", "DE": "unknown"}[country]
    result = {"station_key": key, "season": window["season"], "frozen_station": station,
        "resolved_identity_group": identity, "reference_first_UTC": first.isoformat(), "reference_last_UTC": last.isoformat(),
        "actual_nominal_sample_support_first_UTC": support_first.isoformat(),
        "time_contract": {"operator": operator, "true_sensor_filter_known": False,
            "basis": {"AT": "A1.1 preserved v1-to-v2 nominal-node definition; sensor filtering unverified",
                "CH": "A1.1 source hourly six ten-minute nodes H-50,...,H; 5/12 previous + 7/12 current model surrogate",
                "DE": "Own dated parameter metadata confirms UTC and SYNOP origin; instantaneous/mean/filter not established"}[country]},
        "geometry_status": "SOURCE_BLOCKED", "geometry": None, "strict_2m_compatible": False,
        "temperature_source_eligible": False, "source_block_reasons": [], "source_evidence_sha256": {}}
    receipt = acquisition[key]
    if receipt["status"] != "ORIGINAL_METADATA_RECEIVED":
        result["source_block_reasons"].append(receipt.get("reason", receipt.get("error", "HISTORY_METADATA_NOT_RECEIVED")))
    else:
        try:
            if country == "DE": geometry, evidence = dwd_geometry(bodies, sid, support_first, last)
            else:
                member = receipt["member"]
                geometry = wmdr_geometry(bodies[member], receipt["WSI"], country, support_first, last)
                evidence = {member: sha256(bodies[member]).hexdigest()}
            point = StationReference(country, sid, station["name"], geometry["latitude"], geometry["longitude"],
                station["nominal_site_elevation_m"], station["source_metadata_sha256"])
            nominal = StationReference(**{k: station[k] for k in StationReference.__dataclass_fields__})
            separation = distance_km(nominal, point)
            if separation > .5: raise ValueError("A12_PROVIDER_WMDR_DATED_LOCATION_MORE_THAN_500M_FROM_FROZEN_IDENTITY")
            result.update({"geometry_status": "DATED_TEMPERATURE_SENSOR_CONFIRMED", "geometry": geometry,
                "source_evidence_sha256": evidence, "nominal_to_dated_sensor_distance_km": separation,
                "strict_2m_compatible": geometry["AGL_m"] == 2. and geometry["local_reference_surface"] in ("localGround", "naturalGround")})
            if not result["strict_2m_compatible"]: result["source_block_reasons"].append("ACTUAL_SENSOR_HEIGHT_NOT_STRICT_2M_NO_QUALIFIED_VERTICAL_TRANSFER")
        except ValueError as exc:
            result["source_block_reasons"].append(str(exc))
    if operator == "unknown": result["source_block_reasons"].append("DWD_HOURLY_TIME_OPERATOR_UNRESOLVED")
    # Operator evidence is preserved in A1.1 metadata, separately from geometry.
    for name in ({"AT": ["AT_hourly_v2_metadata.json"], "CH": ["CH_parameters.csv", "CH_download_documentation.html"], "DE": []}[country]):
        result["source_evidence_sha256"]["A1.1/" + name] = sha256(old_bodies[name]).hexdigest()
    result["temperature_source_eligible"] = not result["source_block_reasons"]
    return result


@lru_cache(maxsize=1)
def prepare():
    protocol_raw = (R / "a1_1_protocol_20261025.json").read_bytes()
    if sha256(protocol_raw).hexdigest() != PROTOCOL_SHA: raise ValueError("A12_FROZEN_PROTOCOL_CHANGED")
    protocol = json.loads(protocol_raw)
    bodies, manifest = history_sources()
    old_bodies, _, _ = metadata_sources()
    acquisition = {r["station"]: r for r in manifest["stations"]}
    source_at = {str(r["id"]): r for r in json.loads(old_bodies["AT_hourly_v2_metadata.json"])["stations"] if r["type"] == "INDIVIDUAL"}
    stations = {s["country"] + ":" + s["station_id"]: s for group in protocol["targets"] for s in [group["target"], *group["donors"]]}
    records, adjustments = {}, []
    for key, station in sorted(stations.items()):
        country, sid = key.split(":")
        identity = physical_identity(country, sid, group_id=source_at[sid].get("group_id") if country == "AT" else None,
            wsi=station["identity_group"].removeprefix("CH_WIGOS:") if country == "CH" else None)
        if identity != station["identity_group"]:
            adjustments.append({"station_key": key, "field": "identity_group", "old": station["identity_group"], "new": identity,
                "reason": "Missing provider group is not a shared physical alias; frozen donor slots/IDs unchanged",
                "source_sha256": sha256(old_bodies["AT_hourly_v2_metadata.json"]).hexdigest()})
        records[key] = {w["season"]: station_window(station, w, bodies, acquisition, old_bodies, identity) for w in protocol["windows"]}
    cases = []
    for group in protocol["targets"]:
        for window in protocol["windows"]:
            season = window["season"]; target = records[group["target_key"]][season]
            admitted, blocked = [], []
            for donor in group["donors"]:
                key = donor["key"]; record = records[key][season]
                (admitted if record["temperature_source_eligible"] else blocked).append(key)
            reasons = ["TARGET:" + s for s in target["source_block_reasons"]]
            if len(admitted) < 2: reasons.append("FEWER_THAN_TWO_METADATA_ADMITTED_FROZEN_DONORS")
            # Check the frozen geometry rules once more with admitted dated xy;
            # this is a veto, never a new donor search or error-based reweighting.
            distances = {}
            if target["temperature_source_eligible"]:
                t = admitted_reference(target)
                held = [g["target"] for g in protocol["targets"]]
                for key in admitted:
                    d = admitted_reference(records[key][season]); distance = distance_km(t, d)
                    distances[key] = distance
                    for h in held:
                        hrow = records[h["country"] + ":" + h["station_id"]][season]
                        geo = hrow["geometry"]
                        anchor = StationReference(h["country"], h["station_id"], h["name"],
                            geo["latitude"] if geo else h["latitude"], geo["longitude"] if geo else h["longitude"],
                            h["nominal_site_elevation_m"], h["source_metadata_sha256"])
                        if distance_km(d, anchor) < 5.: reasons.append("DONOR_WITHIN_5KM_OF_HELDOUT:" + key)
                    if distance > 150. or d.identity_group == t.identity_group: reasons.append("DATED_DONOR_GEOMETRY_OR_IDENTITY_CONFLICT:" + key)
                if len({admitted_reference(records[k][season]).identity_group for k in admitted}) != len(admitted):
                    reasons.append("DUPLICATE_DONOR_PHYSICAL_IDENTITY")
            cases.append({"target_key": group["target_key"], "season": season, "reference_hours": 168,
                "frozen_donor_slots": [d["key"] for d in group["donors"]], "metadata_admitted_donors": admitted,
                "blocked_donor_slots": blocked, "dated_xy_distance_km": distances,
                "strict_T2m_metadata_ready": not reasons, "source_block_reasons": reasons,
                "hourly_QC_and_coverage_verified": False, "ERA5_or_donor_weather_acquired": False,
                "predictions_created_or_sealed": False, "primary_validation_admitted": False})
    first_records = [next(iter(windows.values())) for windows in records.values()]
    ready = [c for c in cases if c["strict_T2m_metadata_ready"]]
    return {"schema": "IGE_A12_DATED_TEMPERATURE_ADMISSION_v1", "date": "2026-10-25", "parent_protocol_sha256": PROTOCOL_SHA,
        "source_packet": {"file": PACKET, "sha256": PACKET_SHA, "bytes": (R / PACKET).stat().st_size},
        "station_windows": records, "cases": cases, "identity_adjustments": adjustments,
        "counts": {"frozen_targets": 6, "frozen_donor_slots": 18, "distinct_sites": len(records), "target_season_cases": len(cases),
            "dated_actual_sensor_geometries": sum(r["geometry_status"] == "DATED_TEMPERATURE_SENSOR_CONFIRMED" for r in first_records),
            "strict_2m_geometries": sum(r["strict_2m_compatible"] for r in first_records),
            "metadata_ready_cases": len(ready), "metadata_ready_prospective_reference_hours": sum(c["reference_hours"] for c in ready),
            "primary_validation_admitted_cases": 0, "new_target_measurements_read": 0, "new_weather_requests": 0},
        "acquisition_cost_retained_packet": {"DWD_HTTP_ranges": manifest["range_requests"], "DWD_range_body_bytes": manifest["range_body_bytes"],
            "WMDR_bodies": sum(s.get("member", "").endswith("WMDR.xml") for s in manifest["stations"]),
            "scope": "retained successful/reused responses only, not all discovery or failed packaging retry traffic"},
        "quality_axes": {"code": "OFFLINE_ACCEPTANCE_REQUIRED", "physical": "ACTUAL_SOURCE_TEMPERATURE_SUPPORT_ONLY; no complete weather-state or datum qualification",
            "independent_accuracy": "UNASSESSED; exposure audit and actual prediction seal still required",
            "operation": "RESEARCH_PREFLIGHT; no UI/default/EPW promotion"},
        "independent_accuracy_qualified": False, "strict_blindness_certified": False, "production_ready": False,
        "IV1_observations_opened": False, "old_results_or_protocol_rewritten": False,
        "frozen_station_or_date_replacements": 0, "global_validation_performed": False}


if __name__ == "__main__":
    print(json.dumps(prepare()["counts"], indent=2))
