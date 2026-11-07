#!/usr/bin/env python3
"""Reproducible DWD CDC hourly observations downloader. Python 3.10+, stdlib.

Preserves native values, QC, ZIPs and station metadata. No gap filling or EPW admission.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import csv
import datetime as dt
from email.utils import parsedate_to_datetime
import gzip
import hashlib
from html.parser import HTMLParser
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

VERSION = "1.0.0"
BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/"
UTC = dt.timezone.utc
HOUR = dt.timedelta(hours=1)
DEFAULT_CATALOG = Path(__file__).resolve().parent / "catalog" / "catalog.json.gz"
GROUPS = {
    "air_temperature": "TU", "dew_point": "TD", "moisture": "TF",
    "pressure": "P0", "wind": "FF", "precipitation": "RR",
    "cloudiness": "N", "sun": "SD", "solar": "ST", "visibility": "VV",
}
MAX_HTTP_BYTES = 128 * 1024 * 1024
MAX_UNPACKED_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
SNAPSHOT_FIELDS = ["station_id", "name", "latitude_deg", "longitude_deg", "elevation_m",
                   "state", "groups", "availability_start", "availability_end",
                   "coordinate_role", "coordinate_variants", "coordinate_crs"]
GROUP_FIELDS = ["station_id", "group", "tier", "availability_start", "availability_end",
                "name", "latitude_deg", "longitude_deg", "elevation_m", "state",
                "coordinate_role", "source_url", "source_sha256"]
TIME_FIELDS = ["timestamp_source", "timestamp_utc", "time_basis", "utc_status"]


class SourceError(ValueError):
    """Input, source structure or provenance is inconsistent."""


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def now():
    return dt.datetime.now(UTC).isoformat()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_json(path, obj):
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False).encode() + b"\n")


def csv_bytes(rows, fields):
    f = io.StringIO(newline="")
    writer = csv.DictWriter(f, fields, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return f.getvalue().encode("utf-8")


def sid(value):
    text = str(value)
    if not re.fullmatch(r"[0-9]{1,5}", text) or int(text) == 0:
        raise SourceError("DWD station ID must contain 1..5 digits and be positive")
    return text.zfill(5)


def finite(value):
    try:
        result = float(value)
    except (ValueError, TypeError) as e:
        raise SourceError("Expected a finite number") from e
    if not math.isfinite(result):
        raise SourceError("Expected a finite number")
    return result


def parse_bound(value, *, end=False):
    text = str(value)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            result = dt.datetime.combine(dt.date.fromisoformat(text), dt.time(), UTC)
            if end:
                result += dt.timedelta(days=1)
            return result
        result = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise SourceError("Invalid date or datetime: " + text) from e
    if result.tzinfo is None:
        raise SourceError("Datetime requires an explicit UTC offset")
    result = result.astimezone(UTC)
    if result.minute or result.second or result.microsecond:
        raise SourceError("Selection bounds must lie on a full UTC hour")
    return result


def iso(stamp):
    return stamp.astimezone(UTC).isoformat(timespec="minutes").replace("+00:00", "Z")


def source_stamp(value):
    text = value.strip()
    for pattern, fmt in [(r"\d{10}", "%Y%m%d%H"), (r"\d{12}", "%Y%m%d%H%M"),
                         (r"\d{10}:\d{2}", "%Y%m%d%H:%M")]:
        if re.fullmatch(pattern, text):
            try:
                return dt.datetime.strptime(text, fmt)
            except ValueError as e:
                raise SourceError("Invalid source timestamp: " + text) from e
    raise SourceError("Unsupported source timestamp: " + text)


def safe_url(url):
    p = urllib.parse.urlsplit(url)
    if (p.scheme != "https" or p.netloc != "opendata.dwd.de" or p.query or p.fragment
            or not p.path.startswith("/climate_environment/CDC/")
            or any(x in (".", "..") for x in urllib.parse.unquote(p.path).split("/"))):
        raise SourceError("Expected an official HTTPS DWD CDC URL")
    return url


class Client:
    """Sequential, bounded and retryable requests; interval is a courtesy policy."""
    def __init__(self, interval=1.0, retries=3, timeout=60):
        self.interval = finite(interval)
        if self.interval < 0 or retries < 1:
            raise SourceError("Invalid request policy")
        self.retries, self.timeout, self.last = retries, timeout, 0.0

    def get(self, url):
        safe_url(url)
        for attempt in range(self.retries):
            pause = self.interval - (time.monotonic() - self.last)
            if pause > 0:
                time.sleep(pause)
            self.last = time.monotonic()
            request = urllib.request.Request(url, headers={"User-Agent": "IGE-DWD-Climate/" + VERSION})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    safe_url(response.url)
                    raw = response.read(MAX_HTTP_BYTES + 1)
                    if len(raw) > MAX_HTTP_BYTES:
                        raise SourceError("HTTP response exceeds size limit")
                    return raw
            except urllib.error.HTTPError as exc:
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt + 1 == self.retries:
                    raise
                retry = exc.headers.get("Retry-After", "")
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(retry) - dt.datetime.now(UTC)).total_seconds()
                    except (TypeError, ValueError, OverflowError):
                        delay = 2 ** (attempt + 1)
                # A long server-requested pause is surfaced, never silently shortened.
                if delay > 60:
                    raise SourceError("DWD requests retry after %.0f seconds; resume later" % delay) from exc
                time.sleep(max(0, delay))
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt + 1 == self.retries:
                    raise
                time.sleep(2 ** (attempt + 1))


class ListingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href and "/" not in href and not any(c in href for c in "?#\\"):
                self.links.append(href)


def listing(raw):
    parser = ListingParser()
    parser.feed(raw.decode("utf-8"))
    text = raw.decode("utf-8")
    sizes = {}
    for line in text.splitlines():
        m = re.search(r'href="([^\"]+)".*?</a>\s+([\w:-]+\s+[\d:]+)\s+(\d+)\s*$', line)
        if m:
            sizes[m[1]] = {"listing_last_modified": m[2], "listing_bytes": int(m[3])}
    return sorted(set(parser.links)), sizes


def parse_stations(raw, group, tier, url):
    rows = []
    # DWD lists are fixed width after six whitespace-separated numerical fields.
    pattern = re.compile(r"^\s*(\d{1,5})\s+(\d{8})\s+(\d{8})\s+(-?\d+(?:\.\d+)?)\s+"
                         r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(.*)$")
    for line in raw.decode("cp1252").splitlines()[2:]:
        if not line.strip():
            continue
        match = pattern.match(line)
        if not match:
            raise SourceError("Malformed DWD station list row")
        station, start, end, elev, lat, lon, tail = match.groups()
        start = dt.datetime.strptime(start, "%Y%m%d").date().isoformat()
        end = dt.datetime.strptime(end, "%Y%m%d").date().isoformat()
        lat, lon, elev = finite(lat), finite(lon), finite(elev)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or start > end:
            raise SourceError("Invalid station geography or interval")
        rows.append({"station_id": sid(station), "group": group, "tier": tier,
                     "availability_start": start, "availability_end": end,
                     "name": tail[:41].strip(), "state": tail[41:82].strip(),
                     "latitude_deg": lat, "longitude_deg": lon, "elevation_m": elev,
                     "coordinate_role": "latest_published_position_not_dated_history",
                     "source_url": url, "source_sha256": digest(raw)})
    if not rows or len({r["station_id"] for r in rows}) != len(rows):
        raise SourceError("Empty or duplicate station list")
    return rows


def parse_archive_name(name, group, tier):
    product = GROUPS[group]
    match = re.fullmatch(r"stundenwerte_" + product + r"_(\d{5})_(?:(\d{8})_(\d{8})_hist|akt|row)\.zip", name)
    if not match:
        return None
    station, start, end = match.groups()
    if (tier == "historical" and not start or tier == "recent" and not name.endswith("_akt.zip")
            or tier == "row" and not name.endswith("_row.zip")):
        raise SourceError("Archive name/tier mismatch")
    return {"station_id": sid(station), "filename": name, "group": group, "tier": tier,
            "archive_start": dt.datetime.strptime(start, "%Y%m%d").date().isoformat() if start else None,
            "archive_end": dt.datetime.strptime(end, "%Y%m%d").date().isoformat() if end else None}


def station_union(rows):
    grouped = collections.defaultdict(list)
    for row in rows:
        grouped[row["station_id"]].append(row)
    result = []
    for station, values in sorted(grouped.items()):
        latest = sorted(values, key=lambda r: (r["availability_end"], r["availability_start"], r["group"], r["tier"]))[-1]
        coords = {(r["latitude_deg"], r["longitude_deg"], r["elevation_m"]) for r in values}
        result.append({k: latest[k] for k in ("station_id", "name", "latitude_deg", "longitude_deg", "elevation_m", "state", "coordinate_role")} | {
            "groups": ";".join(sorted({r["group"] for r in values})),
            "availability_start": min(r["availability_start"] for r in values),
            "availability_end": max(r["availability_end"] for r in values),
            "coordinate_variants": len(coords), "coordinate_crs": "EPSG:4326"})
    return result


def build_catalog(output, client, *, groups=None):
    groups = list(GROUPS) if groups is None else groups
    if not groups or len(set(groups)) != len(groups) or any(g not in GROUPS for g in groups):
        raise SourceError("Unknown or duplicate group")
    output = Path(output)
    sources, station_rows, archives = [], [], []

    def capture(url, role):
        raw = client.get(url)
        sha = digest(raw)
        extension = Path(urllib.parse.urlsplit(url).path).suffix or ".html"
        compressed = extension != ".pdf"
        relative = "sources/" + sha + extension + (".gz" if compressed else "")
        stored = gzip.compress(raw, mtime=0) if compressed else raw
        atomic_write(output / relative, stored)
        sources.append({"url": url, "sha256": sha, "path": relative,
                        "stored_sha256": digest(stored), "compression": "gzip" if compressed else "none",
                        "retrieved_at_utc": now(), "role": role, "bytes": len(raw)})
        return raw

    for group in groups:
        print("Catalogue: " + group, flush=True)
        root = BASE + group + "/"
        pdf = "DESCRIPTION_obsgermany_climate_hourly_" + group + "_en.pdf"
        capture(root + pdf, "dataset_description")
        for tier in (["row"] if group == "solar" else ["historical", "recent"]):
            url = root if tier == "row" else root + tier + "/"
            raw = capture(url, "directory_listing")
            links, sizes = listing(raw)
            names = [n for n in links if n.endswith("_Stundenwerte_Beschreibung_Stationen.txt")]
            if len(names) != 1:
                raise SourceError("Station list missing/ambiguous: " + url)
            stations = parse_stations(capture(url + names[0], "station_list"), group, tier, url + names[0])
            station_rows.extend(stations)
            lookup = {r["station_id"]: r for r in stations}
            count = 0
            for name in links:
                archive = parse_archive_name(name, group, tier)
                if not archive:
                    continue
                if archive["station_id"] not in lookup:
                    raise SourceError("Archive has no station-list record: " + name)
                entry = lookup[archive["station_id"]]
                archive.update({"url": url + name, "listing_sha256": digest(raw),
                                "station_list_sha256": entry["source_sha256"],
                                "availability_start": entry["availability_start"],
                                "availability_end": entry["availability_end"], **sizes.get(name, {})})
                if "listing_bytes" not in archive:
                    raise SourceError("Archive size missing from directory listing")
                archives.append(archive)
                count += 1
            if not count:
                raise SourceError("No supported ZIP archives: " + url)
    capture("https://opendata.dwd.de/climate_environment/CDC/Terms_of_use.pdf", "terms_of_use")
    stations = station_union(station_rows)
    payload = {"schema": "ige-dwd-catalog-v1", "created_at_utc": now(), "provider": "Deutscher Wetterdienst, CDC",
               "groups": groups, "sources": sources, "stations": stations,
               "station_groups": station_rows, "archives": archives,
               "coordinate_warning": "Station descriptions provide latest positions, not historical coordinates. Archive geography metadata is required for dated donor admission."}
    payload["catalog_id"] = digest(payload)
    atomic_write(output / "catalog.json.gz", gzip.compress(canonical(payload), mtime=0))
    atomic_write(output / "stations.csv", csv_bytes(stations, SNAPSHOT_FIELDS))
    atomic_write(output / "station_groups.csv.gz", gzip.compress(csv_bytes(station_rows, GROUP_FIELDS), mtime=0))
    archive_fields = list(archives[0])
    atomic_write(output / "archives.csv.gz", gzip.compress(csv_bytes(archives, archive_fields), mtime=0))
    atomic_write(output / "stations.geojson", canonical({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["longitude_deg"], s["latitude_deg"]]},
         "properties": s} for s in stations]}))
    write_json(output / "catalog_manifest.json", {"catalog_id": payload["catalog_id"],
               "created_at_utc": payload["created_at_utc"], "station_ids": len(stations),
               "group_records": len(station_rows), "archives": len(archives),
               "sources": sources, "license": "CC BY 4.0; Quelle: Deutscher Wetterdienst",
               "files": {p.name: digest(p.read_bytes()) for p in output.iterdir()
                         if p.name in ("catalog.json.gz", "stations.csv", "station_groups.csv.gz", "archives.csv.gz", "stations.geojson")}})
    return payload


def load_catalog(path):
    raw = Path(path).read_bytes()
    obj = json.loads(gzip.decompress(raw) if str(path).endswith(".gz") else raw)
    if obj.get("schema") != "ige-dwd-catalog-v1" or obj.get("catalog_id") != digest({k: v for k, v in obj.items() if k != "catalog_id"}):
        raise SourceError("Catalogue identity/schema mismatch")
    return obj


def distance_km(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def nearest(catalog, latitude, longitude, date, *, groups=None, limit=10,
            radius_km=None, elevation_m=None, height_difference_m=None, exclude_ids=()):
    latitude, longitude = finite(latitude), finite(longitude)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180) or limit < 1:
        raise SourceError("Invalid coordinates or limit")
    date = dt.date.fromisoformat(date).isoformat()
    groups = catalog["groups"] if groups is None else groups
    if not groups or any(g not in catalog["groups"] for g in groups):
        raise SourceError("Unknown nearest group")
    if radius_km is not None and finite(radius_km) < 0:
        raise SourceError("Radius must be nonnegative")
    if height_difference_m is not None:
        if elevation_m is None or finite(height_difference_m) < 0:
            raise SourceError("Height filter requires elevation and nonnegative difference")
    excluded = {sid(s) for s in exclude_ids}
    candidates = collections.defaultdict(list)
    for row in catalog["station_groups"]:
        if (row["group"] in groups and row["station_id"] not in excluded
                and row["availability_start"] <= date <= row["availability_end"]):
            candidates[row["station_id"]].append(row)
    result = []
    for station, records in candidates.items():
        # Include only requested groups at this date; no claim of complete data.
        if not set(groups).issubset({r["group"] for r in records}):
            continue
        row = station_union(records)[0]
        d = distance_km(latitude, longitude, row["latitude_deg"], row["longitude_deg"])
        delta = None if elevation_m is None else row["elevation_m"] - finite(elevation_m)
        if radius_km is not None and d > radius_km or height_difference_m is not None and abs(delta) > height_difference_m:
            continue
        result.append(row | {"distance_km": round(d, 6), "height_difference_m": delta,
                             "selection_date": date, "donor_admission": "not_assessed"})
    return sorted(result, key=lambda r: (r["distance_km"], r["station_id"]))[:limit]


def build_plan(catalog, config):
    allowed = {"start", "end", "groups", "station_ids", "tiers", "min_interval_seconds"}
    if set(config) - allowed:
        raise SourceError("Unknown config keys: " + ", ".join(sorted(set(config) - allowed)))
    start, end = parse_bound(config["start"]), parse_bound(config["end"], end=True)
    if start >= end:
        raise SourceError("Start must precede the exclusive end")
    groups = config.get("groups", "all")
    groups = list(catalog["groups"]) if groups == "all" else groups
    if not isinstance(groups, list) or not groups or len(set(groups)) != len(groups) or any(g not in catalog["groups"] for g in groups):
        raise SourceError("Invalid plan groups")
    tiers = config.get("tiers", ["historical", "row"])
    if not isinstance(tiers, list) or not tiers or len(set(tiers)) != len(tiers) or any(t not in ("historical", "recent", "row") for t in tiers):
        raise SourceError("Invalid tiers")
    selected = config.get("station_ids", "all")
    if selected != "all" and not isinstance(selected, list):
        raise SourceError("station_ids must be 'all' or a list")
    selected = None if selected == "all" else {sid(x) for x in selected}
    if selected is not None and not selected:
        raise SourceError("Empty station selection")
    jobs = []
    for entry in catalog["archives"]:
        if entry["group"] not in groups or entry["tier"] not in tiers or selected is not None and entry["station_id"] not in selected:
            continue
        lo = max(entry["availability_start"], entry["archive_start"] or entry["availability_start"])
        hi = min(entry["availability_end"], entry["archive_end"] or entry["availability_end"])
        if parse_bound(lo) >= end or parse_bound(hi, end=True) <= start:
            continue
        job = dict(entry)
        job["job_id"] = digest(job)[:24]
        jobs.append(job)
    jobs.sort(key=lambda j: (j["group"], j["station_id"], j["tier"], j["filename"]))
    if not jobs:
        raise SourceError("No archives intersect the requested period")
    if selected is not None and selected - {j["station_id"] for j in jobs}:
        raise SourceError("At least one requested station has no matching archive")
    interval = finite(config.get("min_interval_seconds", 1.0))
    if interval < 0:
        raise SourceError("Negative request interval")
    plan = {"schema": "ige-dwd-plan-v1", "version": VERSION, "catalog_id": catalog["catalog_id"],
            "start_utc_inclusive": iso(start), "end_utc_exclusive": iso(end),
            "groups": groups, "tiers": tiers, "min_interval_seconds": interval,
            "selection_rule": "UTC where explicitly resolved; unresolved source-clock rows retained with basis and not falsely converted",
            "overlap_rule": "historical wins for the same group, station and resolved UTC stamp; disagreements counted",
            "jobs": jobs, "estimated_zip_bytes": sum(j["listing_bytes"] for j in jobs),
            "archive_scope": "Full provider ZIPs may span more years than the selection; export applies the requested bounds.",
            "sources": catalog["sources"],
            "stations": [s for s in catalog["stations"] if s["station_id"] in {j["station_id"] for j in jobs}]}
    plan["plan_id"] = digest(plan)
    return plan


def load_plan(path):
    plan = json.loads(Path(path).read_bytes())
    if plan.get("schema") != "ige-dwd-plan-v1" or plan.get("plan_id") != digest({k: v for k, v in plan.items() if k != "plan_id"}):
        raise SourceError("Plan hash/schema mismatch")
    if len({j["job_id"] for j in plan["jobs"]}) != len(plan["jobs"]):
        raise SourceError("Duplicate plan jobs")
    for job in plan["jobs"]:
        if job["job_id"] != digest({k: v for k, v in job.items() if k != "job_id"})[:24]:
            raise SourceError("Job identity mismatch")
        expected = BASE + job["group"] + "/" + ("" if job["tier"] == "row" else job["tier"] + "/") + job["filename"]
        if job["url"] != expected or parse_archive_name(job["filename"], job["group"], job["tier"]) is None:
            raise SourceError("Job archive URL mismatch")
        safe_url(job["url"])
    return plan


MINIMUM_FIELDS = {
    "air_temperature": {"TT_TU", "RF_TU"}, "dew_point": {"TT", "TD"},
    "moisture": {"ABSF_STD", "VP_STD", "TF_STD", "P_STD", "TT_STD", "RF_STD", "TD_STD"},
    "pressure": {"P", "P0"}, "wind": {"F", "D"}, "precipitation": {"R1", "RS_IND", "WRTR"},
    "cloudiness": {"V_N", "V_N_I"}, "sun": {"SD_SO"},
    "solar": {"ATMO_LBERG", "FD_LBERG", "FG_LBERG", "SD_LBERG", "ZENIT", "MESS_DATUM_WOZ"},
    "visibility": {"V_VV", "V_VV_I"},
}


def missing(value):
    if not value.strip():
        return True
    try:
        return float(value) == -999
    except ValueError:
        return False


def semicolon_rows(raw):
    reader = csv.reader(io.StringIO(raw.decode("cp1252")), delimiter=";")
    fields = [s.strip() for s in next(reader)]
    # Parameter metadata sometimes end every row and the header with a trailing ';'.
    while fields and fields[-1] == "":
        fields.pop()
    if len(fields) != len(set(fields)):
        raise SourceError("Duplicate metadata columns")
    result = []
    for row in reader:
        if not row or not any(s.strip() for s in row):
            continue
        if row[0].strip().startswith(("Legende:", "generiert:")):
            continue  # DWD text footer remains byte-for-byte in the original ZIP.
        while len(row) > len(fields) and not row[-1].strip():
            row.pop()
        if len(row) != len(fields):
            raise SourceError("Metadata column count mismatch")
        result.append(dict(zip(fields, (s.strip() for s in row))))
    return result


def archive_metadata(archive, job):
    infos = archive.infolist()
    names = [i.filename for i in infos]
    if len(names) != len(set(names)) or not names:
        raise SourceError("Empty ZIP or duplicate member names")
    if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
        raise SourceError("ZIP expanded size exceeds limit")
    for info in infos:
        if (PurePosixPath(info.filename).name != info.filename or "\\" in info.filename
                or info.file_size > MAX_MEMBER_BYTES or info.flag_bits & 1):
            raise SourceError("Unsupported or unsafe ZIP member")
    products = [n for n in names if n.startswith("produkt_") and n.endswith(".txt")]
    parameters = [n for n in names if n.startswith("Metadaten_Parameter_") and n.endswith(".txt")]
    geographies = [n for n in names if n.startswith("Metadaten_Geographie_") and n.endswith(".txt")]
    if len(products) != 1 or len(parameters) != 1 or len(geographies) != 1:
        raise SourceError("Expected one product, parameter history and geography history")
    if not products[0].endswith("_" + job["station_id"] + ".txt"):
        raise SourceError("Product member station mismatch")
    histories = semicolon_rows(archive.read(parameters[0]))
    geography = semicolon_rows(archive.read(geographies[0]))
    if not histories or not geography:
        raise SourceError("Empty parameter/geography metadata")
    for row in histories:
        if sid(row["Stations_ID"]) != job["station_id"]:
            raise SourceError("Parameter metadata station mismatch")
        for key in ("Von_Datum", "Bis_Datum"):
            if key == "Bis_Datum" and not row[key]:
                continue  # Open-ended current metadata interval.
            try:
                dt.datetime.strptime(row[key], "%Y%m%d")
            except ValueError as e:
                raise SourceError("Invalid parameter-history date") from e
    for row in geography:
        if sid(row["Stations_id"]) != job["station_id"]:
            raise SourceError("Geography metadata station mismatch")
        lat, lon = finite(row["Geogr.Breite"]), finite(row["Geogr.Laenge"])
        finite(row["Stationshoehe"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise SourceError("Invalid geography metadata")
        for key in ("von_datum", "bis_datum"):
            if key == "bis_datum" and not row[key]:
                continue
            try:
                dt.datetime.strptime(row[key], "%Y%m%d")
            except ValueError as e:
                raise SourceError("Invalid geography-history date") from e
    return {"product_member": products[0], "parameter_history": histories, "geography_history": geography,
            "members": [{"name": i.filename, "bytes": i.file_size, "crc32": i.CRC} for i in infos],
            "original_metadata_members": [parameters[0], geographies[0]]}


def clock_info(stamp, metadata, group, fields):
    date = stamp.strftime("%Y%m%d")
    hints = set()
    for row in metadata["parameter_history"]:
        if row["Von_Datum"] <= date <= (row["Bis_Datum"] or "99991231") and row["Parameter"] in fields:
            text = row.get("Zusatz-Info", "").upper()
            if "UTC" in text and "WOZ" in text and group == "solar" and "MESS_DATUM_WOZ" in fields:
                hints.add("UTC")  # The separate column is explicitly named WOZ.
            else:
                hints.update(b for b in ("UTC", "MEZ", "WOZ", "MOZ") if b in text)
    if hints == {"UTC"}:
        return iso(stamp.replace(tzinfo=UTC)), "UTC", "metadata_declared_utc"
    if hints == {"MEZ"}:
        return iso((stamp - HOUR).replace(tzinfo=UTC)), "MEZ", "converted_from_metadata_declared_UTC_plus_1"
    basis = next(iter(hints)) if len(hints) == 1 else "UNKNOWN" if not hints else "AMBIGUOUS"
    return "", basis, "unresolved_source_clock_retained"


def product_rows(archive, metadata, job):
    stream = io.TextIOWrapper(archive.open(metadata["product_member"]), encoding="cp1252", newline="")
    with stream:
        reader = csv.reader(stream, delimiter=";")
        try:
            fields = [s.strip() for s in next(reader)]
        except StopIteration as e:
            raise SourceError("Empty product file") from e
        expected = {"STATIONS_ID", "MESS_DATUM", "eor"} | MINIMUM_FIELDS[job["group"]]
        if len(set(fields)) != len(fields) or not expected.issubset(fields) or not any(f.startswith("QN_") for f in fields):
            raise SourceError("Missing/duplicate native product fields")
        previous = None
        day_clock = {}
        # A monotonic primary source axis permits streaming without a growing set of stamps.
        for row in reader:
            if not row or not any(s.strip() for s in row):
                continue
            if len(row) != len(fields):
                raise SourceError("Truncated/misaligned product row")
            values = dict(zip(fields, (s.strip() for s in row)))
            if sid(values["STATIONS_ID"]) != job["station_id"] or values["eor"] != "eor":
                raise SourceError("Product station or record terminator mismatch")
            stamp = source_stamp(values["MESS_DATUM"])
            if previous is not None and stamp <= previous:
                raise SourceError("Duplicate/nonmonotonic source timestamps")
            previous = stamp
            for key, value in values.items():
                if key in ("eor", "MESS_DATUM", "MESS_DATUM_WOZ", "V_N_I", "V_VV_I") or not value:
                    continue
                finite(value)
            if "MESS_DATUM_WOZ" in values and not missing(values["MESS_DATUM_WOZ"]):
                source_stamp(values["MESS_DATUM_WOZ"])
            day = stamp.date()
            if day not in day_clock:
                _, basis, status = clock_info(stamp, metadata, job["group"], fields)
                day_clock[day] = (basis, status)
            basis, status = day_clock[day]
            utc = (iso(stamp.replace(tzinfo=UTC)) if basis == "UTC" else
                   iso((stamp - HOUR).replace(tzinfo=UTC)) if basis == "MEZ" else "")
            yield fields, values | {"timestamp_source": values["MESS_DATUM"], "timestamp_utc": utc,
                                   "time_basis": basis, "utc_status": status}, stamp


def selected_row(row, stamp, start, end):
    if row["timestamp_utc"]:
        actual = dt.datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
        return start <= actual < end
    # Unresolved WOZ/MOZ/ambiguous records remain explicitly on their native clock.
    return start.replace(tzinfo=None) <= stamp < end.replace(tzinfo=None)


def coverage(rows, fields, start, end):
    expected = int((end - start) / HOUR)
    variables = [f for f in fields if f not in ("STATIONS_ID", "MESS_DATUM", "MESS_DATUM_WOZ", "eor") and not f.startswith("QN_")]
    counts = {f: {"present_rows": 0, "missing_rows": 0, "qc_on_present": collections.Counter()} for f in variables}
    present_hours = {f: set() for f in variables}
    utc_hours, bases, total, off_grid, unresolved = set(), collections.Counter(), 0, 0, 0
    qc_fields = [f for f in fields if f.startswith("QN_")]
    for row in rows:
        total += 1
        bases[row["time_basis"]] += 1
        full_hour = False
        if row["timestamp_utc"]:
            stamp = dt.datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            if not stamp.minute:
                utc_hours.add(row["timestamp_utc"])
                full_hour = True
            else:
                off_grid += 1
        else:
            unresolved += 1
        for field in variables:
            if missing(row[field]):
                counts[field]["missing_rows"] += 1
            else:
                counts[field]["present_rows"] += 1
                if full_hour:
                    present_hours[field].add(row["timestamp_utc"])
                for flag in qc_fields:
                    counts[field]["qc_on_present"][flag + "=" + row[flag]] += 1
    return {"selected_rows": total, "expected_hourly_utc_labels": expected,
            "distinct_full_hour_utc_labels": len(utc_hours),
            "missing_hourly_utc_labels": max(0, expected - len(utc_hours)),
            "off_full_hour_rows": off_grid, "unresolved_time_rows": unresolved,
            "time_basis_counts": dict(bases),
            "full_utc_hour_label_axis": len(utc_hours) == expected and not off_grid and not unresolved,
            "variables": {f: v | {"qc_on_present": dict(v["qc_on_present"]),
                "present_full_hour_utc_labels": len(present_hours[f]),
                "missing_full_hour_utc_labels": max(0, expected - len(present_hours[f]))} for f, v in counts.items()},
            "full_meteorological_year_or_epw_admission": False}


def run_root(output, plan):
    return Path(output) / plan["plan_id"][:20]


@contextlib.contextmanager
def run_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".download.lock"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as e:
        raise SourceError("Run locked; after a killed process confirm it has stopped before removing " + str(path)) from e
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def artifact_paths(job):
    j = job["job_id"]
    return ["raw/" + j + "/" + job["filename"], "parts/" + j + ".csv.gz", "metadata/" + j + ".json"]


def receipt_is_complete(root, job):
    try:
        receipt = json.loads((root / "receipts" / (job["job_id"] + ".json")).read_bytes())
        if receipt.get("status") != "complete" or receipt.get("job_sha256") != digest(job):
            return False
        artifacts = receipt["artifacts"]
        if len(artifacts) != 3 or {a["path"] for a in artifacts} != set(artifact_paths(job)):
            return False
        for artifact in artifacts:
            if digest((root / artifact["path"]).read_bytes()) != artifact["sha256"]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def save_job(root, plan, job, raw):
    if len(raw) != job["listing_bytes"]:
        raise SourceError("ZIP size differs from frozen directory listing; refresh catalogue and create a new plan/output")
    raw_path, csv_path, meta_path = artifact_paths(job)
    atomic_write(root / raw_path, raw)
    start, end = parse_bound(plan["start_utc_inclusive"]), parse_bound(plan["end_utc_exclusive"])
    selected = []
    fields = None
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        metadata = archive_metadata(archive, job)
        # Reading all product rows validates the complete downloaded product, not only the selected day.
        for native_fields, row, stamp in product_rows(archive, metadata, job):
            fields = native_fields
            if selected_row(row, stamp, start, end):
                selected.append(row)
        if fields is None:
            raise SourceError("No product records")
        # CRC also covers original HTML and any ancillary members retained in the ZIP.
        if archive.testzip() is not None:
            raise SourceError("ZIP CRC mismatch")
    atomic_write(root / csv_path, gzip.compress(csv_bytes(selected, TIME_FIELDS + fields), mtime=0))
    report = coverage(selected, fields, start, end)
    write_json(root / meta_path, metadata | {"source_url": job["url"], "zip_sha256": digest(raw),
               "native_fields": fields, "coverage": report,
               "time_selection_for_unresolved_rows": "nominal_source_clock_bounds; not proven UTC selection"})
    receipt = {"status": "complete", "retrieved_at_utc": now(), "job_sha256": digest(job),
               "source_url": job["url"], "zip_sha256": digest(raw), "coverage": report,
               "complete_means_transfer_and_structure_only": True,
               "artifacts": [{"path": p, "sha256": digest((root / p).read_bytes())} for p in artifact_paths(job)]}
    write_json(root / "receipts" / (job["job_id"] + ".json"), receipt)
    return receipt


def download(plan, output, client, *, max_jobs=None):
    if max_jobs is not None and max_jobs < 1:
        raise SourceError("max-jobs must be positive")
    root = run_root(output, plan)
    with run_lock(root):
        write_json(root / "plan.json", plan)
        attempts, failures = 0, []
        for index, job in enumerate(plan["jobs"], 1):
            if receipt_is_complete(root, job):
                continue
            if max_jobs is not None and attempts >= max_jobs:
                break
            attempts += 1
            print(f"[{index}/{len(plan['jobs'])}] {job['group']} {job['station_id']} {job['tier']}", flush=True)
            try:
                result = save_job(root, plan, job, client.get(job["url"]))
                print("  selected rows: " + str(result["coverage"]["selected_rows"]), flush=True)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as e:
                failure = {"job_id": job["job_id"], "error": type(e).__name__ + ": " + str(e)}
                failures.append(failure)
                with (root / "errors.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"at_utc": now(), **failure}, ensure_ascii=False) + "\n")
                print("  FAILED: " + failure["error"], file=sys.stderr, flush=True)
        completed = sum(receipt_is_complete(root, j) for j in plan["jobs"])
        summary = {"plan_id": plan["plan_id"], "planned_jobs": len(plan["jobs"]), "completed_jobs": completed,
                   "remaining_jobs": len(plan["jobs"]) - completed, "attempted_this_invocation": attempts,
                   "failures_this_invocation": failures, "all_transfers_complete": completed == len(plan["jobs"]),
                   "meteorological_completeness_or_epw_admission_assessed": False}
        write_json(root / "download_summary.json", summary)
        return summary


def export_station(plan, output, station, year, group, *, plain=False):
    station = sid(station)
    if group not in plan["groups"] or not 1800 <= year <= 2200:
        raise SourceError("Invalid export group/year")
    start = max(parse_bound(plan["start_utc_inclusive"]), dt.datetime(year, 1, 1, tzinfo=UTC))
    end = min(parse_bound(plan["end_utc_exclusive"]), dt.datetime(year + 1, 1, 1, tzinfo=UTC))
    if start >= end:
        raise SourceError("Year outside plan")
    jobs = [j for j in plan["jobs"] if j["station_id"] == station and j["group"] == group
            and parse_bound(j["archive_start"] or j["availability_start"]) < end
            and parse_bound(j["archive_end"] or j["availability_end"], end=True) > start]
    if not jobs:
        raise SourceError("Station/group/year has no planned archives")
    root = run_root(output, plan)
    with run_lock(root):
        if any(not receipt_is_complete(root, j) for j in jobs):
            raise SourceError("Export blocked: a required archive is missing or corrupt")
        merged, fields, conflicts, duplicate_rows = {}, None, 0, 0
        for job in sorted(jobs, key=lambda j: (j["tier"] != "historical", j["job_id"])):
            with gzip.open(root / artifact_paths(job)[1], "rt", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if fields is not None and reader.fieldnames != fields:
                    raise SourceError("Native schemas differ across selected archives")
                fields = reader.fieldnames
                for row in reader:
                    stamp = source_stamp(row["timestamp_source"])
                    if not selected_row(row, stamp, start, end):
                        continue
                    key = ("UTC", row["timestamp_utc"]) if row["timestamp_utc"] else (row["time_basis"], row["timestamp_source"])
                    if key in merged:
                        duplicate_rows += 1
                        old, old_job = merged[key]
                        if {k: v for k, v in old.items() if k != "source_job_id"} != row:
                            conflicts += 1
                            if old_job["tier"] == job["tier"]:
                                raise SourceError("Conflicting rows within the same DWD tier")
                        continue  # Historical is processed before recent.
                    merged[key] = (row | {"source_job_id": job["job_id"]}, job)
        rows = [v[0] for k, v in sorted(merged.items(), key=lambda item: (item[0][1], item[0][0]))]
        if fields is None:
            raise SourceError("No part schema")
        body = csv_bytes(rows, fields + ["source_job_id"])
        suffix = ".csv" if plain else ".csv.gz"
        path = root / "stations" / station / group / (str(year) + suffix)
        atomic_write(path, body if plain else gzip.compress(body, mtime=0))
        native_fields = [f for f in fields if f not in TIME_FIELDS]
        report = coverage(rows, native_fields, start, end) | {
            "station_id": station, "group": group, "year": year,
            "start_utc_inclusive": iso(start), "end_utc_exclusive": iso(end),
            "full_calendar_selection": start == dt.datetime(year, 1, 1, tzinfo=UTC) and end == dt.datetime(year + 1, 1, 1, tzinfo=UTC),
            "duplicate_rows_removed": duplicate_rows, "overlap_conflicts_historical_preferred": conflicts,
            "source_jobs": [j["job_id"] for j in jobs], "csv_sha256": digest(path.read_bytes()),
            "native_missing_marker": "-999 (including equivalent decimal representation), preserved in CSV",
            "native_units_and_parameter_history": ["metadata/" + j["job_id"] + ".json" for j in jobs]}
        write_json(path.with_name(str(year) + ".coverage.json"), report)
        return {"csv": str(path.resolve()), "coverage": report}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("catalog", help="Fetch station lists, archive indexes and source documentation")
    p.add_argument("--out", default="catalog_updated")
    p.add_argument("--groups", nargs="+", choices=list(GROUPS))
    p.add_argument("--interval", type=float, default=1.0)
    p = sub.add_parser("nearest", help="Search latest published coordinates; historical donor admission is separate")
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--groups", nargs="+", choices=list(GROUPS), default=["air_temperature"])
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--radius-km", type=float)
    p.add_argument("--elevation-m", type=float)
    p.add_argument("--max-height-difference-m", type=float)
    p.add_argument("--exclude-ids", nargs="*", default=[])
    p.add_argument("--csv")
    p = sub.add_parser("plan", help="Freeze selected provider ZIPs; does not download observations")
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    p.add_argument("--config", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("download", help="Download archives and write native data parts")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", default="downloaded")
    p.add_argument("--max-jobs", type=int)
    p = sub.add_parser("export", help="Merge verified parts for one station, group and year")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", default="downloaded")
    p.add_argument("--station-id", required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--group", choices=list(GROUPS), required=True)
    p.add_argument("--plain-csv", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            cat = build_catalog(args.out, Client(args.interval), groups=args.groups)
            print(json.dumps({"catalog_id": cat["catalog_id"], "station_ids": len(cat["stations"]), "archives": len(cat["archives"])}, ensure_ascii=False))
        elif args.command == "nearest":
            rows = nearest(load_catalog(args.catalog), args.lat, args.lon, args.date,
                           groups=args.groups, limit=args.limit, radius_km=args.radius_km,
                           elevation_m=args.elevation_m, height_difference_m=args.max_height_difference_m,
                           exclude_ids=args.exclude_ids)
            if args.csv:
                fields = SNAPSHOT_FIELDS + ["distance_km", "height_difference_m", "selection_date", "donor_admission"]
                atomic_write(args.csv, csv_bytes(rows, fields))
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif args.command == "plan":
            plan = build_plan(load_catalog(args.catalog), json.loads(Path(args.config).read_bytes()))
            write_json(args.out, plan)
            print(json.dumps({"plan_id": plan["plan_id"], "zip_archives": len(plan["jobs"]),
                              "listing_zip_bytes": plan["estimated_zip_bytes"], "download_started": False}))
        elif args.command == "download":
            plan = load_plan(args.plan)
            summary = download(plan, args.out, Client(plan["min_interval_seconds"]), max_jobs=args.max_jobs)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1 if summary["failures_this_invocation"] else 0
        elif args.command == "export":
            result = export_station(load_plan(args.plan), args.out, args.station_id, args.year, args.group, plain=args.plain_csv)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
