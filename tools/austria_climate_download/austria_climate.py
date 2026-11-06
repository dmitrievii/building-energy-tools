#!/usr/bin/env python3
"""Download native GeoSphere hourly station data; Python 3.10+, stdlib only.

No gap filling, QC masking, interpolation, unit conversion or EPW admission.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
from email.utils import parsedate_to_datetime
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0.0"
RESOURCE = "klima-v2-1h"
BASE = "https://dataset.api.hub.geosphere.at/v1/station/historical/" + RESOURCE
UTC = dt.timezone.utc
HOUR = dt.timedelta(hours=1)
MIN_INTERVAL = 16.0  # <=225 requests/hour; published limit is 240/hour.
MAX_VALUES = 800_000  # Conservative margin below the published 1,000,000.
MAX_BYTES = 64 * 1024 * 1024
DEFAULT_CATALOG = Path(__file__).resolve().parent / "catalog" / "metadata.original.json"
FIELDS = ("station_id", "name", "station_type", "group_id", "latitude_deg",
          "longitude_deg", "elevation_m", "state", "valid_from_utc", "valid_to_utc",
          "is_active_provider", "has_global_radiation", "has_sunshine",
          "coordinate_crs", "elevation_role", "metadata_sha256")
KINDS = {"individual": "INDIVIDUAL", "combined": "COMBINED"}


class SourceError(ValueError):
    """Source content or request contract is not usable."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def utc_now():
    return dt.datetime.now(UTC).isoformat()


def atomic_write(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    with temporary.open("wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2,
                                 allow_nan=False).encode("utf-8") + b"\n")


def parse_time(value, *, end_of_date=False, metadata=False):
    """User dates denote UTC; explicit datetimes must carry a UTC offset."""
    text = str(value)
    if len(text) == 10:
        stamp = dt.datetime.combine(dt.date.fromisoformat(text), dt.time(), UTC)
        return stamp + (dt.timedelta(hours=23) if end_of_date else dt.timedelta())
    stamp = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        if not metadata:
            raise SourceError("Datetime requires an explicit UTC offset: " + text)
        # Dataset documentation declares UTC; some metadata end_time omit it.
        stamp = stamp.replace(tzinfo=UTC)
    stamp = stamp.astimezone(UTC)
    if not metadata and (stamp.minute or stamp.second or stamp.microsecond):
        raise SourceError("Hourly bounds must be on a full UTC hour")
    return stamp


def iso(stamp):
    return stamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ceil_hour(stamp):
    floor = stamp.replace(minute=0, second=0, microsecond=0)
    return floor if floor == stamp else floor + HOUR


def numeric(value, label):
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise SourceError("Invalid " + label) from exc
    if not math.isfinite(number):
        raise SourceError("Non-finite " + label)
    return number


def load_metadata(raw):
    obj = json.loads(raw)
    if (not isinstance(obj, dict) or obj.get("frequency") != "PT1H"
            or obj.get("type") != "station" or obj.get("mode") != "historical"):
        raise SourceError("Expected native hourly historical station metadata")
    if not obj.get("stations") or not obj.get("parameters"):
        raise SourceError("Empty station/parameter metadata")
    ids = [str(s["id"]) for s in obj["stations"]]
    if len(ids) != len(set(ids)):
        raise SourceError("Duplicate station IDs")
    names = [p["name"] for p in obj["parameters"]]
    if len(names) != len(set(names)):
        raise SourceError("Duplicate parameter names")
    return obj


def station_rows(metadata, metadata_sha):
    rows = []
    for station in metadata["stations"]:
        lat, lon = numeric(station.get("lat"), "latitude"), numeric(station.get("lon"), "longitude")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise SourceError("Coordinates outside WGS84 bounds")
        if station.get("type") not in KINDS.values():
            raise SourceError("Unknown station type")
        first = parse_time(station["valid_from"], metadata=True)
        last = parse_time(station["valid_to"], metadata=True)
        if first > last:
            raise SourceError("Reversed station validity interval")
        altitude = station.get("altitude")
        rows.append(dict(zip(FIELDS, (
            str(station["id"]), station["name"], station["type"], station.get("group_id"),
            lat, lon, None if altitude is None else numeric(altitude, "elevation"),
            station.get("state"), iso(first), iso(last), station.get("is_active"),
            station.get("has_global_radiation"), station.get("has_sunshine"),
            "EPSG:4326", "published_station_altitude_not_sensor_elevation", metadata_sha,
        ))))
    return sorted(rows, key=lambda s: int(s["station_id"]))


def csv_bytes(rows, fields):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def make_catalog(raw, output):
    metadata = load_metadata(raw)
    sha = digest(raw)
    rows = station_rows(metadata, sha)
    root = Path(output)
    # Preserve previous exact metadata snapshots if the current index is refreshed.
    snapshot = root / "snapshots" / (sha + ".json")
    atomic_write(snapshot, raw)
    atomic_write(root / "metadata.original.json", raw)
    atomic_write(root / "stations.csv", csv_bytes(rows, FIELDS))
    features = []
    for row in rows:
        features.append({"type": "Feature", "id": row["station_id"],
                         "geometry": {"type": "Point", "coordinates": [row["longitude_deg"], row["latitude_deg"]]},
                         "properties": row})
    write_json(root / "stations.geojson", {"type": "FeatureCollection", "features": features})
    write_json(root / "parameters.json", {"parameters": metadata["parameters"],
                                         "code_lists": metadata.get("code_lists", {})})
    manifest = {"schema": "IGE_AT_CATALOG_v1", "resource": RESOURCE,
                "source": BASE + "/metadata", "retrieved_at_utc": utc_now(),
                "source_metadata_sha256": sha, "station_records": len(rows),
                "station_types": dict(collections.Counter(s["station_type"] for s in rows)),
                "license": "CC BY 4.0", "attribution": "GeoSphere Austria, klima-v2-1h, DOI 10.60669/9bdm-yq93",
                "coordinates": "WGS84; GeoJSON uses longitude, latitude",
                "validity_is_not_observation_completeness": True,
                "altitude_is_not_confirmed_sensor_elevation": True}
    write_json(root / "catalog_manifest.json", manifest)
    return manifest


def haversine_km(lat1, lon1, lat2, lon2):
    a, b = map(math.radians, (lat1, lat2))
    dlat, dlon = b - a, math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def nearest_stations(metadata, lat, lon, *, when, limit=10, radius_km=None,
                     elevation_m=None, max_height_difference_m=None,
                     station_kind="individual", exclude_ids=(), exclude_group=None,
                     metadata_sha=""):
    lat, lon = numeric(lat, "query latitude"), numeric(lon, "query longitude")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or limit < 1:
        raise SourceError("Invalid nearest-station query")
    if radius_km is not None and (not math.isfinite(radius_km) or radius_km < 0):
        raise SourceError("Invalid radius")
    if max_height_difference_m is not None and (elevation_m is None or max_height_difference_m < 0):
        raise SourceError("Height filter needs a target elevation and nonnegative tolerance")
    if elevation_m is not None:
        elevation_m = numeric(elevation_m, "target elevation")
    if station_kind not in (*KINDS, "all"):
        raise SourceError("Invalid station kind")
    result = []
    for row in station_rows(metadata, metadata_sha):
        if station_kind != "all" and row["station_type"] != KINDS[station_kind]:
            continue
        if row["station_id"] in set(map(str, exclude_ids)):
            continue
        if exclude_group is not None and (str(row["group_id"]) == str(exclude_group)
                                          or row["station_id"] == str(exclude_group)):
            continue
        if not parse_time(row["valid_from_utc"], metadata=True) <= when <= parse_time(row["valid_to_utc"], metadata=True):
            continue
        distance = haversine_km(lat, lon, row["latitude_deg"], row["longitude_deg"])
        height = None if elevation_m is None or row["elevation_m"] is None else row["elevation_m"] - elevation_m
        if radius_km is not None and distance > radius_km:
            continue
        if max_height_difference_m is not None and (height is None or abs(height) > max_height_difference_m):
            continue
        result.append({**row, "distance_km": distance, "station_minus_target_elevation_m": height})
    result.sort(key=lambda s: (s["distance_km"], int(s["station_id"])))
    return result[:limit]


def periods(first, last, months):
    cursor = first
    while cursor <= last:
        # Calendar blocks never cross a year, simplifying annual exports.
        next_month = min(13, ((cursor.month - 1) // months + 1) * months + 1)
        following = (dt.datetime(cursor.year + 1, 1, 1, tzinfo=UTC) if next_month == 13
                     else dt.datetime(cursor.year, next_month, 1, tzinfo=UTC))
        end = min(last, following - HOUR)
        yield cursor, end
        cursor = end + HOUR


def resolve_parameters(metadata, wanted):
    available = {p["name"]: p for p in metadata["parameters"]}
    names = list(available) if wanted == "all" else list(wanted)
    if not names or any(name not in available for name in names):
        raise SourceError("Unknown or empty parameter selection; inspect catalog/parameters.json")
    selected = set(names)
    # Never omit QC merely because the user requested just the physical field.
    for name in names:
        if not name.endswith("_flag") and name + "_flag" in available:
            selected.add(name + "_flag")
    return sorted(selected)


def build_plan(raw, config, *, now=None):
    metadata = load_metadata(raw)
    unknown = set(config) - {"start", "end", "station_ids", "station_kind", "parameters", "chunk_months", "max_values", "min_interval_seconds"}
    if unknown:
        raise SourceError("Unknown configuration keys: " + ", ".join(sorted(unknown)))
    first = parse_time(config["start"])
    last = parse_time(config["end"], end_of_date=True)
    if first > last:
        raise SourceError("Start is later than end")
    if last > (now or dt.datetime.now(UTC)).replace(minute=0, second=0, microsecond=0):
        raise SourceError("Historical request extends into the future")
    if first < ceil_hour(parse_time(metadata["start_time"], metadata=True)):
        raise SourceError("Request precedes the published dataset start")
    months = config.get("chunk_months", 3)
    cap = config.get("max_values", MAX_VALUES)
    interval = config.get("min_interval_seconds", MIN_INTERVAL)
    if type(months) is not int or months not in (1, 3, 6, 12):
        raise SourceError("chunk_months must be 1, 3, 6 or 12")
    if type(cap) is not int or not 1 <= cap <= MAX_VALUES:
        raise SourceError("max_values must be between 1 and 800000")
    if not math.isfinite(interval) or interval < MIN_INTERVAL:
        raise SourceError("min_interval_seconds must be at least 16")
    kind = config.get("station_kind", "individual")
    if kind not in (*KINDS, "all"):
        raise SourceError("Unknown station_kind")
    rows = station_rows(metadata, digest(raw))
    wanted = config.get("station_ids", "all")
    selected_ids = None if wanted == "all" else set(map(str, wanted))
    known_ids = {s["station_id"] for s in rows}
    if selected_ids is not None and (not selected_ids or selected_ids - known_ids):
        raise SourceError("Unknown/empty station_ids")
    selected = [s for s in rows if (selected_ids is None or s["station_id"] in selected_ids)
                and (kind == "all" or s["station_type"] == KINDS[kind])]
    if selected_ids is not None and {s["station_id"] for s in selected} != selected_ids:
        raise SourceError("Requested station IDs do not match station_kind")
    parameters = resolve_parameters(metadata, config.get("parameters", "all"))
    jobs = []
    used = set()
    for block_start, block_end in periods(first, last, months):
        groups = collections.defaultdict(list)
        for station in selected:
            left = max(block_start, ceil_hour(parse_time(station["valid_from_utc"], metadata=True)))
            right = min(block_end, parse_time(station["valid_to_utc"], metadata=True).replace(minute=0, second=0, microsecond=0))
            if left <= right:
                groups[(left, right)].append(station["station_id"])
        for (left, right), ids in sorted(groups.items()):
            hours = int((right - left) / HOUR) + 1
            per_batch = cap // (hours * len(parameters))
            if per_batch < 1:
                raise SourceError("One station exceeds max_values; choose a shorter calendar block")
            for offset in range(0, len(ids), per_batch):
                batch = ids[offset:offset + per_batch]
                job = {"start": iso(left), "end": iso(right), "station_ids": batch,
                       "parameters": parameters, "expected_hours": hours,
                       "requested_values": hours * len(batch) * len(parameters)}
                job["job_id"] = digest(job)[:24]
                jobs.append(job)
                used.update(batch)
    if not jobs:
        raise SourceError("No selected station validity intervals overlap the requested period")
    plan = {"schema": "IGE_AT_DOWNLOAD_PLAN_v1", "tool_version": VERSION,
            "resource": RESOURCE, "endpoint": BASE, "start": iso(first), "end": iso(last),
            "metadata_original_utf8": raw.decode("utf-8"), "metadata_sha256": digest(raw),
            "station_ids": sorted(used, key=int), "parameters": parameters,
            "min_interval_seconds": float(interval), "chunk_months": months,
            "jobs": jobs, "total_requested_values": sum(j["requested_values"] for j in jobs),
            "minimum_pacing_seconds": max(0, len(jobs) - 1) * interval,
            "no_data_or_qc_completeness_inferred_from_metadata": True}
    plan["plan_id"] = digest(plan)
    return plan


def load_plan(path):
    plan = json.loads(Path(path).read_bytes())
    unsigned = {k: v for k, v in plan.items() if k != "plan_id"}
    if plan.get("schema") != "IGE_AT_DOWNLOAD_PLAN_v1" or plan.get("plan_id") != digest(unsigned):
        raise SourceError("Plan schema/hash mismatch")
    if plan["endpoint"] != BASE or digest(plan["metadata_original_utf8"].encode("utf-8")) != plan["metadata_sha256"]:
        raise SourceError("Plan source identity mismatch")
    return plan


class _OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(BASE).hostname:
            raise SourceError("Refusing redirect outside the official Dataset API")
        if not newurl.startswith("https://"):
            raise SourceError("Refusing non-HTTPS redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, *, interval=MIN_INTERVAL, timeout=90, attempts=4, clock_file=None,
                 opener=None, clock=time.time, sleep=time.sleep):
        if not math.isfinite(interval) or interval < MIN_INTERVAL or not math.isfinite(timeout) or timeout <= 0 or attempts < 1:
            raise SourceError("Invalid transport configuration")
        self.interval, self.timeout, self.attempts = interval, timeout, attempts
        self.clock_file = Path(clock_file) if clock_file else None
        self.clock, self.sleep = clock, sleep
        self.open = opener or urllib.request.build_opener(_OfficialRedirect()).open
        self.next_request = 0.0
        if self.clock_file and self.clock_file.exists():
            self.next_request = float(json.loads(self.clock_file.read_bytes())["next_request_unix"])

    def _wait(self):
        while self.clock() < self.next_request:
            self.sleep(min(30.0, self.next_request - self.clock()))
        self.next_request = self.clock() + self.interval
        if self.clock_file:
            write_json(self.clock_file, {"next_request_unix": self.next_request})

    def get(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != urllib.parse.urlsplit(BASE).hostname or parsed.username or parsed.password:
            raise SourceError("Only the official HTTPS Dataset API is allowed")
        request = urllib.request.Request(url, headers={"User-Agent": "IGE-Austria-Climate-Downloader/" + VERSION,
                                                      "Accept": "application/json"})
        for attempt in range(self.attempts):
            self._wait()
            try:
                with self.open(request, timeout=self.timeout) as response:
                    raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise SourceError("Response exceeds the 64 MiB local limit")
                return raw
            except urllib.error.HTTPError as exc:
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt + 1 == self.attempts:
                    raise
                retry = exc.headers.get("Retry-After", "0")
                try:
                    self.next_request = max(self.next_request, self.clock() + float(retry))
                except ValueError:
                    try:
                        self.next_request = max(self.next_request, parsedate_to_datetime(retry).timestamp())
                    except (TypeError, ValueError):
                        pass
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt + 1 == self.attempts:
                    raise
            self.next_request = max(self.next_request, self.clock() + min(60, 2 ** (attempt + 1)))
        raise RuntimeError("Retry loop exhausted")


def request_url(job):
    query = {"station_ids": ",".join(job["station_ids"]), "parameters": ",".join(job["parameters"]),
             "start": job["start"], "end": job["end"], "output_format": "geojson"}
    return BASE + "?" + urllib.parse.urlencode(query)


def decode_response(raw, job, metadata):
    obj = json.loads(raw)
    if not isinstance(obj, dict) or obj.get("type") != "FeatureCollection" or not isinstance(obj.get("features"), list):
        raise SourceError("Expected FeatureCollection")
    stamps = [parse_time(t) for t in obj.get("timestamps", [])]
    expected = [parse_time(job["start"]) + i * HOUR for i in range(job["expected_hours"])]
    if stamps != expected:
        raise SourceError("Source hourly axis is truncated, duplicated, shifted or incomplete")
    units = {p["name"]: p.get("unit") for p in metadata["parameters"]}
    features = {}
    for feature in obj.get("features", []):
        props = feature["properties"]
        identity = props["station"]
        sid = str(identity["id"] if isinstance(identity, dict) else identity)
        if sid in features or sid not in job["station_ids"]:
            raise SourceError("Unexpected or duplicate station in response")
        params = props.get("parameters", {})
        for name in job["parameters"]:
            item = params.get(name)
            if (not isinstance(item, dict) or item.get("unit") != units[name]
                    or not isinstance(item.get("data"), list) or len(item["data"]) != len(stamps)):
                raise SourceError("Parameter/unit/length mismatch: " + sid + " / " + name)
            for value in item["data"]:
                if value is not None and (isinstance(value, bool) or not isinstance(value, (float, int, str))
                                          or isinstance(value, (float, int)) and not math.isfinite(value)):
                    raise SourceError("Unsupported/non-finite source value")
        features[sid] = params
    if set(features) != set(job["station_ids"]):
        raise SourceError("Response is missing a requested station")
    # Some API responses label [latitude, longitude] as GeoJSON coordinates.
    # The coordinate catalogue is generated from explicit metadata lat/lon instead.
    return [iso(t) for t in stamps], features


def coverage(parameters, expected):
    result = {}
    for name, item in parameters.items():
        if name.endswith("_flag"):
            continue
        values = item["data"]
        flags = parameters.get(name + "_flag", {}).get("data", [None] * expected)
        valid_flags = collections.Counter(str(int(f)) if isinstance(f, (float, int)) and float(f).is_integer() else str(f)
                                          for value, f in zip(values, flags) if value is not None)
        present = sum(value is not None for value in values)
        result[name] = {"unit": item["unit"], "requested_hours": expected, "non_null_hours": present,
                        "null_hours": expected - present, "qc_counts_on_non_null": dict(valid_flags)}
    return result


def run_root(output, plan):
    return Path(output) / plan["plan_id"][:20]


def receipt_is_complete(root, job):
    path = root / "receipts" / (job["job_id"] + ".json")
    try:
        receipt = json.loads(path.read_bytes())
        if receipt.get("status") != "complete" or receipt.get("request_sha256") != digest(job):
            return False
        source_sha = receipt["original_response_sha256"]
        expected = {f"raw/{job['job_id']}/{source_sha}.json.gz"}
        expected.update(f"csv/{sid}/{job['start'][:4]}/{job['job_id']}.csv.gz" for sid in job["station_ids"])
        if (len(receipt["artifacts"]) != len(expected)
                or {a["path"] for a in receipt["artifacts"]} != expected):
            return False
        for artifact in receipt["artifacts"]:
            relative = Path(artifact["path"])
            if relative.is_absolute() or ".." in relative.parts:
                return False
            if digest((root / relative).read_bytes()) != artifact["file_sha256"]:
                return False
        return bool(receipt["artifacts"])
    except (OSError, ValueError, KeyError):
        return False


def save_job(root, job, raw, metadata):
    source_sha = digest(raw)
    raw_path = Path("raw") / job["job_id"] / (source_sha + ".json.gz")
    compressed = gzip.compress(raw, mtime=0)
    atomic_write(root / raw_path, compressed)
    stamps, features = decode_response(raw, job, metadata)
    artifacts = [{"path": raw_path.as_posix(), "file_sha256": digest(compressed),
                  "original_response_sha256": source_sha}]
    summaries = {}
    for sid, params in features.items():
        # Use only requested fields, with original values and blank cells for null.
        rows = ({"timestamp_utc": stamp, "station_id": sid,
                 **{name: params[name]["data"][i] for name in job["parameters"]}}
                for i, stamp in enumerate(stamps))
        body = gzip.compress(csv_bytes(rows, ["timestamp_utc", "station_id", *job["parameters"]]), mtime=0)
        csv_path = Path("csv") / sid / job["start"][:4] / (job["job_id"] + ".csv.gz")
        atomic_write(root / csv_path, body)
        artifacts.append({"path": csv_path.as_posix(), "file_sha256": digest(body)})
        summaries[sid] = coverage({n: params[n] for n in job["parameters"]}, len(stamps))
    receipt = {"status": "complete", "request_sha256": digest(job), "retrieved_at_utc": utc_now(),
               "url": request_url(job), "original_response_sha256": source_sha,
               "artifacts": artifacts, "stations": summaries,
               "complete_means_transfer_and_structure_only": True}
    write_json(root / "receipts" / (job["job_id"] + ".json"), receipt)
    return receipt


def download(plan, output, client, *, max_jobs=None):
    root = run_root(output, plan)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".download.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SourceError("Run already locked. After a killed process, confirm it stopped and remove " + str(lock)) from exc
    os.write(fd, str(os.getpid()).encode("ascii"))
    os.close(fd)
    try:
        write_json(root / "plan.json", plan)
        atomic_write(root / "metadata.original.json", plan["metadata_original_utf8"].encode("utf-8"))
        metadata = load_metadata(plan["metadata_original_utf8"])
        processed, failed = 0, []
        for index, job in enumerate(plan["jobs"], 1):
            if receipt_is_complete(root, job):
                continue
            if max_jobs is not None and processed >= max_jobs:
                break
            processed += 1
            print(f"[{index}/{len(plan['jobs'])}] {job['start']}..{job['end']} stations={','.join(job['station_ids'])}", flush=True)
            try:
                raw = client.get(request_url(job))
                receipt = save_job(root, job, raw, metadata)
                for sid, values in receipt["stations"].items():
                    if values and all(v["non_null_hours"] == 0 for v in values.values()):
                        print("  NO_OBSERVATIONS: station " + sid, flush=True)
            except (OSError, ValueError, KeyError) as exc:
                message = f"{type(exc).__name__}: {exc}"
                failed.append({"job_id": job["job_id"], "error": message})
                with (root / "errors.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"at_utc": utc_now(), **failed[-1]}, ensure_ascii=False) + "\n")
                print("  FAILED: " + message, file=sys.stderr, flush=True)
        completed = sum(receipt_is_complete(root, job) for job in plan["jobs"])
        summary = {"plan_id": plan["plan_id"], "planned_jobs": len(plan["jobs"]),
                   "completed_jobs": completed, "remaining_jobs": len(plan["jobs"]) - completed,
                   "attempted_this_invocation": processed, "failures_this_invocation": failed,
                   "all_transfers_complete": completed == len(plan["jobs"]),
                   "meteorological_completeness_or_epw_admission_assessed": False}
        write_json(root / "download_summary.json", summary)
        return summary
    finally:
        lock.unlink(missing_ok=True)


def export_station(plan, output, sid, year, *, plain=False):
    sid = str(sid)
    root = run_root(output, plan)
    jobs = [j for j in plan["jobs"] if sid in j["station_ids"] and int(j["start"][:4]) == year]
    jobs.sort(key=lambda j: j["start"])
    if not jobs or any(not receipt_is_complete(root, j) for j in jobs):
        raise SourceError("Selected station/year has missing or corrupt download chunks")
    target = root / "stations" / sid / (str(year) + (".csv" if plain else ".csv.gz"))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    opener = (lambda p: p.open("wt", encoding="utf-8", newline="")) if plain else (
        lambda p: gzip.open(p, "wt", encoding="utf-8", newline=""))
    count, last_stamp = 0, None
    fields = ["timestamp_utc", "station_id", *plan["parameters"]]
    non_null = collections.Counter()
    try:
        with opener(temporary) as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for job in jobs:
                path = root / "csv" / sid / str(year) / (job["job_id"] + ".csv.gz")
                with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
                    reader = csv.DictReader(source)
                    if reader.fieldnames != fields:
                        raise SourceError("CSV field identity mismatch")
                    for row in reader:
                        if row["station_id"] != sid or not row["timestamp_utc"].startswith(str(year) + "-"):
                            raise SourceError("Export row belongs to another station/year")
                        stamp = parse_time(row["timestamp_utc"])
                        if last_stamp is not None and stamp <= last_stamp:
                            raise SourceError("Duplicate or unsorted export timestamps")
                        last_stamp = stamp
                        writer.writerow(row)
                        count += 1
                        non_null.update(name for name in plan["parameters"] if row[name] != "")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    annual = int((dt.datetime(year + 1, 1, 1, tzinfo=UTC) - dt.datetime(year, 1, 1, tzinfo=UTC)) / HOUR)
    expected = sum(j["expected_hours"] for j in jobs)
    report = {"station_id": sid, "year": year, "rows": count, "planned_hours_for_station": expected,
              "calendar_year_hours": annual, "full_calendar_axis": count == annual,
              "non_null_by_parameter": {name: non_null[name] for name in plan["parameters"]},
              "file_sha256": digest(target.read_bytes()),
              "epw_admission_assessed": False, "qc_filter_applied": False, "gap_filling_applied": False}
    write_json(target.with_name(str(year) + ".coverage.json"), report)
    return target, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    cat = commands.add_parser("catalog", help="Refresh coordinate, period and parameter files")
    cat.add_argument("--out", type=Path, required=True)
    near = commands.add_parser("nearest", help="Find physical site candidates, not admitted donors")
    near.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    near.add_argument("--lat", type=float, required=True)
    near.add_argument("--lon", type=float, required=True)
    near.add_argument("--date", required=True, help="Historical date in UTC")
    near.add_argument("--limit", type=int, default=10)
    near.add_argument("--radius-km", type=float)
    near.add_argument("--elevation-m", type=float)
    near.add_argument("--max-height-difference-m", type=float)
    near.add_argument("--kind", choices=[*KINDS, "all"], default="individual")
    near.add_argument("--exclude-ids", default="")
    near.add_argument("--exclude-group")
    near.add_argument("--csv", type=Path)
    plan_cmd = commands.add_parser("plan", help="Freeze request plan; no observation downloads")
    plan_cmd.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    plan_cmd.add_argument("--config", type=Path, required=True)
    plan_cmd.add_argument("--out", type=Path, required=True)
    down = commands.add_parser("download", help="Run/resume a frozen plan")
    down.add_argument("--plan", type=Path, required=True)
    down.add_argument("--out", type=Path, required=True)
    down.add_argument("--max-jobs", type=int)
    down.add_argument("--timeout", type=float, default=90)
    exp = commands.add_parser("export", help="Join downloaded chunks for one station/year")
    exp.add_argument("--plan", type=Path, required=True)
    exp.add_argument("--out", type=Path, required=True)
    exp.add_argument("--station-id", required=True)
    exp.add_argument("--year", type=int, required=True)
    exp.add_argument("--plain-csv", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            result = make_catalog(Client(clock_file=args.out / ".request_clock.json").get(BASE + "/metadata"), args.out)
        elif args.command == "nearest":
            raw = args.catalog.read_bytes()
            result = nearest_stations(load_metadata(raw), args.lat, args.lon, when=parse_time(args.date),
                                      limit=args.limit, radius_km=args.radius_km, elevation_m=args.elevation_m,
                                      max_height_difference_m=args.max_height_difference_m, station_kind=args.kind,
                                      exclude_ids=args.exclude_ids.split(","), exclude_group=args.exclude_group,
                                      metadata_sha=digest(raw))
            if args.csv:
                atomic_write(args.csv, csv_bytes(result, [*FIELDS, "distance_km", "station_minus_target_elevation_m"]))
        elif args.command == "plan":
            result = build_plan(args.catalog.read_bytes(), json.loads(args.config.read_bytes()))
            write_json(args.out, result)
            result = {k: result[k] for k in ("plan_id", "station_ids", "parameters", "total_requested_values", "minimum_pacing_seconds")}
            result["station_count"] = len(result.pop("station_ids"))
            result["request_count"] = len(json.loads(args.out.read_bytes())["jobs"])
        elif args.command == "download":
            if args.max_jobs is not None and args.max_jobs < 1:
                raise SourceError("max-jobs must be positive")
            plan = load_plan(args.plan)
            result = download(plan, args.out, Client(interval=plan["min_interval_seconds"], timeout=args.timeout,
                              clock_file=args.out / ".request_clock.json"), max_jobs=args.max_jobs)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["failures_this_invocation"] else 0
        else:
            path, report = export_station(load_plan(args.plan), args.out, args.station_id, args.year, plain=args.plain_csv)
            result = {"path": str(path), **report}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
