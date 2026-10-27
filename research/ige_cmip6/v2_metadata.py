"""Finite metadata-only acquisition and dated V2 source admission.

No model/observation endpoint or target QC series is supported. All failed
metadata candidates are retained; the target frame is never replenished.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request, HTTPRedirectHandler, build_opener
import zipfile
from xml.etree.ElementTree import ParseError

import numpy as np
import pandas as pd

from v2_cohort import (BASE, ROOT, R, COUNTRIES, FIRST, LAST, METADATA_ATTEMPTS_MAX,
    catalogs, discovery, tie_key, json_bytes)
from v1_prepare import metadata as old_metadata, PRODUCT
from v1_time_admission import operator, dwd_geometry
from a12_prepare_history import wmdr_geometry
from epw_climate_analyzer.station_admission import admitted_reference
from epw_climate_analyzer.station_reconstruction import StationReference, distance_km

BRANCH = "research/ige-v2-metadata-exposure-cohort-20261027"
FRAME = "v2_metadata_frame_20261027.json"
PACKET = "v2_dated_metadata_sources_20261027.zip"
ADMISSION = "v2_metadata_admission_20261027.json"
MAX_BODY = 4_000_000
MAX_TOTAL = 50_000_000
WSI_LIMIT = 3
PART_SIZE = 5_500_000


def metadata_url(url):
    p = urlsplit(url)
    if p.scheme != "https" or p.fragment or p.username or p.password:
        return False
    if p.netloc == "oscar.wmo.int":
        if re.fullmatch(r"/surface/rest/api/wmd/download/0-\d+-\d+-[A-Za-z0-9]+", p.path):
            return not p.query
        if p.path == "/surface/rest/api/stations/approvedStations/names":
            q = parse_qs(p.query)
            return set(q) == {"q", "pageSize", "page"} and len(q["q"]) == 1 and bool(q["q"][0]) and q["pageSize"] == ["100"] and q["page"] == ["1"]
    if p.netloc == "opendata.dwd.de" and not p.query:
        return bool(re.fullmatch(r"/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/meta_data/Meta_Daten_zehn_min_tu_\d{5}\.zip", p.path))
    return False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_body(url, body):
    p = urlsplit(url)
    if p.path.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            if len(archive.namelist()) > 40 or any(not Path(n).name.startswith("Metadaten_") for n in archive.namelist()):
                raise ValueError("V2_ONLY_DWD_METADATA_MEMBERS")
            if sum(n.file_size for n in archive.infolist()) > 8_000_000:
                raise ValueError("V2_DWD_METADATA_UNCOMPRESSED_BUDGET")
    elif "/wmd/download/" in p.path:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(body)
        if not root.tag.endswith("WIGOSMetadataRecord"):
            raise ValueError("V2_WMDR_METADATA_REQUIRED")
    else:
        obj = json.loads(body)
        if not isinstance(obj, list) or len(obj) > 100 or any(not isinstance(r, dict) or "text" not in r for r in obj):
            raise ValueError("V2_WMO_NAME_METADATA_REQUIRED")


class MetadataCollector:
    def __init__(self, *, opener=None):
        self.opener = opener or build_opener(NoRedirect).open
        self.attempts = 0; self.bytes = 0; self.bodies = {}; self.receipts = {}; self.seed = {}
        bodies, manifest = old_metadata()
        for row in manifest["source_receipts"]:
            url = row["url"]
            # Only entries allowed by this narrower collector can be reused.
            if not metadata_url(url):
                continue
            candidates = [name for name, raw in bodies.items() if not name.endswith(".receipt.json") and sha256(raw).hexdigest() == row["sha256"]]
            if len(candidates) == 1:
                self.seed[url] = (bodies[candidates[0]], row)

    def get(self, url):
        if not metadata_url(url):
            raise ValueError("V2_WEATHER_OR_UNREGISTERED_ENDPOINT_FORBIDDEN")
        if url in self.receipts:
            row = self.receipts[url]
            if row["status"] != "ORIGINAL_METADATA_RECEIVED":
                raise ValueError("V2_METADATA_SOURCE_BLOCK:" + row["reason"])
            return self.bodies[row["member"]]
        suffix = ".zip" if urlsplit(url).path.endswith(".zip") else ".xml" if "/wmd/download/" in url else ".json"
        member = "metadata_" + sha256(url.encode()).hexdigest() + suffix
        note = {"url": url, "member": member, "observational_values_requested": False, "model_values_requested": False,
            "status": "SOURCE_BLOCKED", "HTTP_attempts": 0, "body_bytes_read": 0}
        self.receipts[url] = note
        try:
            if url in self.seed:
                body, old = self.seed[url]
                note.update(reused_from="v1_metadata_sources_20261026.zip", original_receipt=old)
            else:
                if self.attempts >= METADATA_ATTEMPTS_MAX or self.bytes >= MAX_TOTAL:
                    raise ValueError("V2_TOTAL_METADATA_BUDGET")
                self.attempts += 1; note["HTTP_attempts"] = 1
                note["started_UTC_as_reported_by_runner"] = datetime.now(timezone.utc).isoformat()
                request = Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "IGE-V2-metadata-only-admission/1"})
                with self.opener(request, timeout=45) as response:
                    if response.status != 200 or response.geturl() != url or response.headers.get("Content-Encoding", "identity") != "identity":
                        raise ValueError("V2_ORIGINAL_METADATA_ENDPOINT_REQUIRED")
                    body = response.read(min(MAX_BODY, MAX_TOTAL - self.bytes) + 1)
                    note["body_bytes_read"] = len(body); self.bytes += len(body)
                    note["headers"] = {k: response.headers.get(k) for k in ("Content-Type", "Content-Length", "ETag", "Last-Modified")}
                    self.bodies[member] = body
                    note.update(bytes=len(body), sha256=sha256(body).hexdigest())
                    if not body or len(body) > MAX_BODY or self.bytes > MAX_TOTAL:
                        raise ValueError("V2_METADATA_BODY_BUDGET")
                    declared = int(response.headers.get("Content-Length", "0"))
                    if declared and declared != len(body):
                        raise ValueError("V2_METADATA_TRUNCATED_OR_EXTRA_BODY")
            # Preserve received bytes even on a schema or identity failure.
            self.bodies[member] = body
            note.update(bytes=len(body), sha256=sha256(body).hexdigest())
            validate_body(url, body)
            note["status"] = "ORIGINAL_METADATA_RECEIVED"
            return body
        except (HTTPError, URLError, OSError, ValueError, KeyError, ParseError, zipfile.BadZipFile) as error:
            note["reason"] = type(error).__name__ + ":" + str(error)[:200]
            if isinstance(error, HTTPError):
                note["HTTP_status"] = error.code; error.close()
            raise ValueError("V2_METADATA_SOURCE_BLOCK:" + note["reason"]) from None

    def packet(self, output):
        manifest = {"schema": "IGE_V2_METADATA_ONLY_ORIGINALS_v1", "parent_commit": BASE,
            "new_HTTP_attempts": self.attempts, "new_body_bytes": self.bytes,
            "metadata_attempts_cap": METADATA_ATTEMPTS_MAX, "metadata_bytes_cap": MAX_TOTAL,
            "sources": list(self.receipts.values()), "member_sha256": {n: sha256(b).hexdigest() for n, b in self.bodies.items()},
            "new_observation_or_model_requests": 0, "AT_2018_and_IV1_2022_controls_unopened": True}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, body in sorted({**self.bodies, "manifest.json": json_bytes(manifest)}.items()):
                info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, body)
        raw = buffer.getvalue(); parts = []
        for i, pos in enumerate(range(0, len(raw), PART_SIZE), 1):
            name = PACKET + f".part{i:03d}"; data = raw[pos:pos + PART_SIZE]
            with (output / name).open("xb") as stream: stream.write(data)
            parts.append({"name": name, "bytes": len(data), "sha256": sha256(data).hexdigest()})
        storage = {"schema": "IGE_V2_METADATA_PACKET_PARTS_v1", "packet_name": PACKET,
            "bytes": len(raw), "sha256": sha256(raw).hexdigest(), "parts": parts}
        with (output / (PACKET + ".storage.json")).open("xb") as stream: stream.write(json_bytes(storage))
        return manifest, storage


def normalized_name(name):
    for old, new in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "AE"), ("Ö", "OE"), ("Ü", "UE"), ("ß", "ss")):
        name = name.replace(old, new)
    text = unicodedata.normalize("NFKD", name).encode("ascii", errors="ignore").decode().upper()
    return re.findall(r"[A-Z0-9]+", text)


def lookup_candidates(name, body):
    rows = json.loads(body)
    stop = {"ST", "AN", "DER", "AM", "IN", "IM", "STADT", "STRANDBAD", "AUTOM", "AUTOMATISCH"}
    core = [w for w in normalized_name(name) if w not in stop]
    if not core: raise ValueError("V2_AT_NAME_CORE_REQUIRED")
    candidates = {}
    for row in rows:
        text = row["text"]; match = re.search(r"\((0-\d+-\d+-[A-Za-z0-9]+)\)", text)
        if not match: continue
        label = text[:match.start()]; words = [w for w in normalized_name(label) if w not in stop]
        overlap = len(set(core) & set(words))
        compact = "".join(core); other = "".join(words)
        if compact == other: overlap += 100
        elif compact in other or other in compact: overlap += 10
        if overlap:
            candidates[match.group(1)] = {"WSI": match.group(1), "name": label.strip(), "score": overlap}
    return sorted(candidates.values(), key=lambda r: (-r["score"], r["WSI"]))[:WSI_LIMIT]


def metadata_record(station, collector):
    op = operator(station.country, *PRODUCT[station.country], FIRST, LAST)
    if station.country == "AT":
        op = replace(op, source_QC_stratum="AT_QC10_AUTO_CHECKED_ORIGINALITY_UNKNOWN_PROVIDER_PRODUCT_V2")
    row = {"station_key": station.key, "frozen_station": asdict(station), "resolved_identity_group": station.identity_group,
        "reference_first_UTC": FIRST.isoformat(), "reference_last_UTC": LAST.isoformat(),
        "time_contract": {"operator": op.published_operator, "definition": asdict(op), "true_sensor_filter_known": False},
        "geometry_status": "SOURCE_BLOCKED", "geometry": None, "strict_2m_compatible": False,
        "temperature_source_eligible": False, "source_block_reasons": [], "source_evidence_sha256": {},
        "measurement_QC_and_coverage_verified": False, "new_weather_requests": 0}
    first = FIRST - pd.Timedelta(minutes=50) if station.country == "CH" else FIRST
    try:
        attempts = []
        if station.country == "DE":
            url = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/meta_data/Meta_Daten_zehn_min_tu_" + station.station_id + ".zip"
            body = collector.get(url); geometry, evidence = dwd_geometry(body, station.station_id, first, LAST)
            evidence[url] = sha256(body).hexdigest()
        else:
            if station.country == "CH":
                if not station.identity_group.startswith("CH_WIGOS:"):
                    raise ValueError("V2_CH_PROVIDER_WSI_REQUIRED")
                candidates = [{"WSI": station.identity_group.removeprefix("CH_WIGOS:"), "name": station.name}]
                row["identity_binding"] = "PROVIDER_WSI_CROSSWALK_AND_DATED_GEOMETRY"
            else:
                terms = [w for w in normalized_name(station.name) if w not in {"ST", "AN", "DER", "AM", "IN", "IM"}]
                url = "https://oscar.wmo.int/surface/rest/api/stations/approvedStations/names?" + urlencode({"pageSize": 100, "q": terms[0], "page": 1})
                body = collector.get(url); candidates = lookup_candidates(station.name, body)
                row["source_evidence_sha256"][url] = sha256(body).hexdigest()
                row["identity_binding"] = "INFERRED_UNIQUE_WMO_NAME_AND_DATED_COORDINATES_NOT_PROVIDER_ID_CROSSWALK"
                row["WMO_lookup_candidates"] = candidates
            found = []
            for candidate in candidates:
                url = "https://oscar.wmo.int/surface/rest/api/wmd/download/" + candidate["WSI"]
                try:
                    body = collector.get(url); geometry = wmdr_geometry(body, candidate["WSI"], station.country, first, LAST)
                    point = replace(station, latitude=geometry["latitude"], longitude=geometry["longitude"])
                    if distance_km(station, point) > .5:
                        raise ValueError("V2_DATED_NOMINAL_IDENTITY_SEPARATION_OVER_500M")
                    found.append((geometry, {url: sha256(body).hexdigest()}))
                except ValueError as error:
                    attempts.append({"WSI": candidate["WSI"], "reason": str(error)})
            row["WMO_rejected_metadata_candidates"] = attempts
            if len(found) != 1:
                raise ValueError("V2_UNIQUE_DATED_WMO_IDENTITY_REQUIRED:" + str(len(found)))
            geometry, evidence = found[0]
        point = replace(station, latitude=geometry["latitude"], longitude=geometry["longitude"])
        if distance_km(station, point) > .5:
            raise ValueError("V2_DATED_NOMINAL_IDENTITY_SEPARATION_OVER_500M")
        row.update(geometry=geometry, geometry_status="DATED_TEMPERATURE_SENSOR_CONFIRMED")
        row["source_evidence_sha256"].update(evidence)
        row["strict_2m_compatible"] = geometry["AGL_m"] == 2. and geometry["local_reference_surface"] in ("localGround", "naturalGround")
        if not row["strict_2m_compatible"]:
            raise ValueError("V2_STRICT_DATED_2M_REQUIRED")
        row["temperature_source_eligible"] = True
        admitted_reference(row)
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        row["temperature_source_eligible"] = False
        row["source_block_reasons"].append(type(error).__name__ + ":" + str(error))
    print(station.key, "META_READY" if row["temperature_source_eligible"] else "SOURCE_BLOCKED", flush=True)
    return row


def choose_targets(frame, records):
    if len({s.identity_group for s in frame}) != len(frame):
        raise ValueError("V2_TARGET_FRAME_IDENTITY_ALIAS")
    selected, strata, blocks = [], {}, []
    for country in COUNTRIES:
        eligible = [s for s in frame if s.country == country and records[s.key]["temperature_source_eligible"]]
        eligible.sort(key=lambda s: (s.nominal_site_elevation_m, s.key))
        groups = np.array_split(np.arange(len(eligible)), 3)
        strata[country] = []
        for rank, indices in enumerate(groups):
            pool = [eligible[int(i)] for i in indices]
            ordered = sorted(pool, key=lambda s: (tie_key(s.key), s.key))
            chosen = ordered[:2]
            strata[country].append({"rank_stratum": rank, "metadata_eligible_pool": [s.key for s in pool], "chosen": [s.key for s in chosen]})
            if len(chosen) < 2:
                blocks.append(country + ":INSUFFICIENT_DATED_2M_STRATUM:" + str(rank))
            selected.extend(chosen)
    return selected, strata, blocks


def donor_candidates(target, pool, selected):
    target_identities = {s.identity_group for s in selected}
    candidates = sorted((distance_km(target, s), s.key, s) for s in pool if s.country == target.country
        and s.key not in {t.key for t in selected} and s.identity_group not in target_identities
        and all(distance_km(s, t) >= 5 for t in selected if t.country == s.country)
        and 5 <= distance_km(target, s) <= 150)
    result, seen = [], set()
    for distance, key, station in candidates:
        if station.identity_group in seen: continue
        seen.add(station.identity_group); result.append((distance, station))
        if len(result) == (8 if target.country == "AT" else 4): break
    return result


def acquire(output):
    if output.exists(): raise FileExistsError(output)
    output.mkdir(parents=True)
    frame, _ = discovery()
    if (R / FRAME).read_bytes() != json_bytes(frame):
        raise ValueError("V2_FROZEN_PREMETADATA_FRAME_CHANGED")
    pool, _, _ = catalogs(); by_key = {s.key: s for s in pool}
    chosen_frame = [by_key[r["country"] + ":" + r["station_id"]] for r in frame["metadata_candidates"]]
    collector = MetadataCollector(); records = {}
    for station in chosen_frame:
        records[station.key] = metadata_record(station, collector)
        (output / "partial_records.json").write_bytes(json_bytes(records))
    selected, strata, blocks = choose_targets(chosen_frame, records)
    groups = []
    for target in selected:
        candidates = donor_candidates(target, pool, selected); good = []
        for distance, donor in candidates:
            if donor.key not in records:
                records[donor.key] = metadata_record(donor, collector)
            record = records[donor.key]
            if record["temperature_source_eligible"]:
                d = distance_km(admitted_reference(records[target.key]), admitted_reference(record))
                if 5 <= d <= 150: good.append(donor.key)
        donors = good[:3]
        ready = len(donors) >= 2
        if not ready: blocks.append(target.key + ":FEWER_THAN_TWO_FIXED_METADATA_ADMITTED_DONORS")
        groups.append({"target_key": target.key, "target_name": target.name, "donors": donors,
            "candidate_order": [s.key for _, s in candidates], "metadata_ready": ready})
        (output / "partial_records.json").write_bytes(json_bytes(records))
    manifest, storage = collector.packet(output)
    result = {"schema": "IGE_V2_DATED_METADATA_AND_COHORT_ADMISSION_v1", "parent_commit": BASE,
        "frame_sha256": sha256((R / FRAME).read_bytes()).hexdigest(), "metadata_packet_sha256": storage["sha256"],
        "planned_targets": 18, "planned_cases": 72, "requested_reference_hours": 12096,
        "metadata_target_count": len(selected), "metadata_target_keys": [s.key for s in selected], "height_rank_strata": strata,
        "groups": groups, "records": records, "metadata_ready_cases": 4 * sum(g["metadata_ready"] for g in groups),
        "source_blocks": blocks, "all_fixed_frame_candidates_retained": len(records) >= len(chosen_frame),
        "metadata_HTTP_attempts": collector.attempts, "new_metadata_body_bytes": collector.bytes,
        "status": "METADATA_COHORT_READY_FOR_EXECUTABLE_PREREGISTRATION" if not blocks and len(selected) == 18 else "SOURCE_BLOCKED_RETAINED_NO_UNBLINDING",
        "weather_acquisition_allowed": False, "executable_weather_protocol_published": False,
        "actual_prediction_seal_published": False, "new_observation_model_or_target_QC_requests": 0,
        "AT_2018_and_IV1_2022_controls_unopened": True, "independent_accuracy_qualified": False, "production_ready": False}
    with (output / ADMISSION).open("xb") as stream: stream.write(json_bytes(result))
    (output / "metadata_manifest.json").write_bytes(json_bytes(manifest))
    print(json.dumps({"status": result["status"], "metadata_targets": len(selected), "ready_cases": result["metadata_ready_cases"], "blocks": blocks,
        "new_metadata_HTTP_attempts": collector.attempts, "metadata_packet_sha256": storage["sha256"], "weather_requests": 0}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--out", type=Path, required=True)
    acquire(parser.parse_args().out)
