#!/usr/bin/env python3
"""MeteoSwiss OGD hourly station downloader. Python 3.10+, standard library only.

Preserves incomplete records and native units. Does not fabricate QC, values or historical site coordinates.
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
import io
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0.0"
BASE = "https://data.geo.admin.ch/"
API = BASE + "api/stac/v1/collections/"
NETWORKS = {"smn": "ch.meteoschweiz.ogd-smn", "smn-precip": "ch.meteoschweiz.ogd-smn-precip"}
DOCS = ["a-data-groundbased/a1-automatic-weather-stations", "a-data-groundbased/a2-automatic-precipitation-stations", "general/download", "general/faq", "general/terms-of-use"]
DOC_BASE = "https://opendatadocs.meteoswiss.ch/"
UTC = dt.timezone.utc
HOUR = dt.timedelta(hours=1)
DEFAULT_CATALOG = Path(__file__).resolve().parent / "catalog" / "catalog.json.gz"
MAX_HTTP_BYTES = 128 * 1024 * 1024
TIME_FIELDS = ["timestamp_utc", "hour_interval_regime"]
STATION_FIELDS = ["network", "station_id", "name", "canton", "wigos_id", "latitude_deg", "longitude_deg", "elevation_m", "barometer_elevation_m", "data_since", "owner", "coordinate_role", "hourly_parameters", "station_url"]

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

def distance_km(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, h))))

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


def station_id(value):
    text = str(value).upper()
    if not re.fullmatch(r"[A-Z0-9]{3,6}", text):
        raise SourceError("Expected a MeteoSwiss station abbreviation (e.g. BER)")
    return text


def safe_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.fragment or p.username or p.password:
        raise SourceError("Expected official HTTPS URL")
    if any(s in (".", "..") for s in urllib.parse.unquote(p.path).split("/")):
        raise SourceError("Unsafe source path")
    if p.netloc == "opendatadocs.meteoswiss.ch" and p.path.strip("/") in DOCS and not p.query:
        return url
    if p.netloc == "data.geo.admin.ch":
        for collection in NETWORKS.values():
            if p.path == "/api/stac/v1/collections/" + collection or p.path == "/api/stac/v1/collections/" + collection + "/items":
                return url
            if p.path.startswith("/" + collection + "/") and not p.query:
                return url
    raise SourceError("URL is outside supported MeteoSwiss OGD collections")


class Client:
    def __init__(self, interval=1.0, retries=4, timeout=90):
        self.interval = finite(interval)
        if self.interval < 0 or retries < 1:
            raise SourceError("Invalid request policy")
        self.retries, self.timeout, self.last = retries, timeout, 0.0
        self.response_headers = {}

    def get(self, url, *, cached=None):
        safe_url(url)
        for attempt in range(self.retries):
            delay = self.interval - (time.monotonic() - self.last)
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()
            headers = {"User-Agent": "IGE-MeteoSwiss-Climate/" + VERSION}
            if cached and cached[1]:
                headers["If-None-Match"] = cached[1]
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    safe_url(response.url)
                    self.response_headers = {k.lower(): v for k, v in response.headers.items()}
                    raw = response.read(MAX_HTTP_BYTES + 1)
                    if len(raw) > MAX_HTTP_BYTES:
                        raise SourceError("Response exceeds size limit")
                    return raw
            except urllib.error.HTTPError as e:
                if e.code == 304 and cached:
                    self.response_headers = {"etag": cached[1]}
                    return cached[0]
                if e.code not in (408, 429, 500, 502, 503, 504) or attempt + 1 == self.retries:
                    raise
                retry = e.headers.get("Retry-After", "")
                try:
                    pause = float(retry)
                except ValueError:
                    try:
                        pause = (parsedate_to_datetime(retry) - dt.datetime.now(UTC)).total_seconds()
                    except (TypeError, ValueError, OverflowError):
                        pause = min(30, 2 ** (attempt + 1)) + random.random()
                if pause > 60:
                    raise SourceError("Server requests a longer pause; resume later") from e
                time.sleep(max(0, pause))
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt + 1 == self.retries:
                    raise
                time.sleep(min(30, 2 ** (attempt + 1)) + random.random())


def decode_csv(raw):
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "cp1252"
    return raw.decode(encoding), encoding


def read_table(raw):
    text, _ = decode_csv(raw)
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=";")
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise SourceError("Missing/duplicate CSV headers")
    result = []
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise SourceError("Metadata CSV column count mismatch")
        result.append(row)
    return result


def source_time(text):
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", text):
        raise SourceError("Unsupported native timestamp: " + text)
    try:
        return dt.datetime(int(text[6:10]), int(text[3:5]), int(text[:2]), int(text[11:13]), int(text[14:16]), tzinfo=UTC)
    except ValueError as e:
        raise SourceError("Invalid native timestamp") from e


def inventory_date(text):
    return iso(source_time(text)) if text else None


def interval_regime(stamp):
    return "pre2018_synop_rule_for_aggregates" if stamp.year < 2018 else "since2018_hour_rule_for_aggregates"


def checksum_sha256(value):
    # STAC file extension uses a multihash: 0x12 = sha2-256, 0x20 = 32 bytes.
    if value is None:
        return None
    if not re.fullmatch(r"1220[0-9a-fA-F]{64}", value):
        raise SourceError("Unsupported STAC checksum; expected sha2-256 multihash")
    return value[4:].lower()


def parse_asset(name, network, station, item, metadata, snapshot_year):
    prefix = "ogd-" + network + "_" + station.lower() + "_h_"
    match = re.fullmatch(re.escape(prefix) + r"(historical_(\d{4})-(\d{4})|recent|now)\.csv", name)
    if not match:
        return None
    kind, y1, y2 = match.groups()
    kind = "historical" if y1 else kind
    if y1 and (int(y2) < int(y1) or int(y2) - int(y1) != 9):
        raise SourceError("Unexpected historical decade interval")
    expected = BASE + NETWORKS[network] + "/" + station.lower() + "/" + name
    if metadata.get("href") != expected or metadata.get("type", "").split(";")[0] != "text/csv":
        raise SourceError("Asset identity/URL/media type mismatch")
    lo = int(y1) if y1 else snapshot_year
    hi = int(y2) + 1 if y2 else snapshot_year + 1
    nominal_start = f"{lo:04d}-01-01T00:00Z"
    nominal_end = f"{hi:04d}-01-01T00:00Z"
    if kind == "now":
        updated = dt.datetime.fromisoformat(metadata.get("updated", f"{snapshot_year}-01-01T00:00:00Z").replace("Z", "+00:00"))
        day = updated.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        nominal_start, nominal_end = iso(day - dt.timedelta(days=2)), iso(day + dt.timedelta(days=1))
    return {"network": network, "station_id": station, "item_id": item,
            "filename": name, "type": kind, "url": expected,
            "nominal_start": nominal_start, "nominal_end_exclusive": nominal_end,
            "provider_sha256": checksum_sha256(metadata.get("file:checksum")),
            "provider_bytes": metadata.get("file:size"), "asset_updated": metadata.get("updated"),
            "bounds_role": "filename_decade_or_snapshot_year_not_observed_coverage"}


def load_catalog(path):
    raw = Path(path).read_bytes()
    obj = json.loads(gzip.decompress(raw) if str(path).endswith(".gz") else raw)
    if obj.get("schema") != "IGE_CH_CATALOG_v1" or obj.get("catalog_id") != digest({k: v for k, v in obj.items() if k != "catalog_id"}):
        raise SourceError("Catalogue identity/schema mismatch")
    return obj


def build_catalog(output, client, *, networks=None):
    networks = list(NETWORKS) if networks is None else networks
    if not networks or len(set(networks)) != len(networks) or any(n not in NETWORKS for n in networks):
        raise SourceError("Invalid networks")
    output = Path(output)
    previous = load_catalog(output / "catalog.json.gz") if (output / "catalog.json.gz").exists() else None
    cached_sources = {s["url"]: s for s in previous["sources"]} if previous else {}
    sources, stations, parameters, inventory, assets, warnings = [], [], {}, [], [], []
    retrieved = now()
    snapshot_year = dt.datetime.fromisoformat(retrieved).year

    def capture(url, role):
        cached = None
        prior = cached_sources.get(url)
        if prior and prior.get("etag"):
            stored = (output / prior["path"]).read_bytes()
            if digest(stored) != prior["stored_sha256"]:
                raise SourceError("Cached source is corrupt")
            cached = (gzip.decompress(stored), prior["etag"])
        raw = client.get(url, cached=cached)
        sha = digest(raw)
        suffix = ".json" if "/api/stac/" in url else ".html" if url.startswith(DOC_BASE) else ".csv"
        path = "sources/" + sha + suffix + ".gz"
        stored = gzip.compress(raw, mtime=0)
        atomic_write(output / path, stored)
        sources.append({"url": url, "role": role, "path": path, "sha256": sha,
                        "stored_sha256": digest(stored), "bytes": len(raw), "retrieved_at_utc": now(),
                        "etag": getattr(client, "response_headers", {}).get("etag")})
        return raw

    for network in networks:
        print("Catalogue: " + network, flush=True)
        base = BASE + NETWORKS[network] + "/ogd-" + network + "_meta_"
        native_stations = read_table(capture(base + "stations.csv", "station_metadata"))
        native_parameters = read_table(capture(base + "parameters.csv", "parameter_metadata"))
        native_inventory = read_table(capture(base + "datainventory.csv", "data_inventory"))
        parameters[network] = [p for p in native_parameters if p["parameter_granularity"] == "H"]
        codes = {p["parameter_shortname"] for p in parameters[network]}
        if not codes or len(codes) != len(parameters[network]):
            raise SourceError("Empty/duplicate hourly parameter definitions")
        for row in native_inventory:
            if row["parameter_shortname"] not in codes:
                continue
            lo, hi = inventory_date(row["data_since"]), inventory_date(row["data_till"])
            if not lo or hi is not None and lo > hi:
                raise SourceError("Invalid inventory interval")
            inventory.append({"network": network, "station_id": station_id(row["station_abbr"]),
                              "parameter": row["parameter_shortname"], "start_utc": lo, "end_utc_inclusive": hi,
                              "measurement_category": row["meas_cat_nr"], "owner": row["owner"]})
        collection = API + NETWORKS[network]
        capture(collection, "collection_metadata")
        url, pages, item_lookup = collection + "/items?limit=100", set(), {}
        while url:
            if url in pages or len(pages) >= 100:
                raise SourceError("STAC pagination cycle/limit")
            pages.add(url)
            obj = json.loads(capture(url, "stac_items_page"))
            if obj.get("type") != "FeatureCollection" or not isinstance(obj.get("features"), list):
                raise SourceError("Expected STAC FeatureCollection")
            for item in obj["features"]:
                identity = station_id(item["id"])
                if identity in item_lookup or item.get("collection") != NETWORKS[network]:
                    raise SourceError("Duplicate/wrong-collection STAC item")
                item_lookup[identity] = item
            links = [l for l in obj.get("links", []) if l.get("rel") == "next"]
            if len(links) > 1 or links and links[0].get("method", "GET") != "GET":
                raise SourceError("Unsupported STAC pagination")
            url = links[0]["href"] if links else None
            if url and urllib.parse.urlsplit(url).path != "/api/stac/v1/collections/" + NETWORKS[network] + "/items":
                raise SourceError("STAC pagination escapes collection")
        lookup = {}
        for native in native_stations:
            identity = station_id(native["station_abbr"])
            if identity in lookup:
                raise SourceError("Duplicate station abbreviation")
            lookup[identity] = native
        for identity in sorted(set(lookup) | set(item_lookup)):
            native, item = lookup.get(identity), item_lookup.get(identity)
            if native:
                lat, lon = finite(native["station_coordinates_wgs84_lat"]), finite(native["station_coordinates_wgs84_lon"])
                height = finite(native["station_height_masl"]) if native["station_height_masl"] else None
                barometer = finite(native["station_height_barometer_masl"]) if native["station_height_barometer_masl"] else None
                name, canton = native["station_name"], native["station_canton"]
                since = dt.datetime.strptime(native["station_data_since"], "%d.%m.%Y").date().isoformat() if native["station_data_since"] else None
            else:
                if item.get("geometry", {}).get("type") != "Point":
                    raise SourceError("Unlisted STAC item has no explicit point coordinates")
                lon, lat = map(finite, item["geometry"]["coordinates"][:2])
                height, barometer, canton, since = None, None, "", None
                name = item.get("properties", {}).get("title", identity)
                warnings.append({"network": network, "station_id": identity, "code": "STAC_ITEM_WITHOUT_STATION_TABLE_METADATA"})
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise SourceError("Station coordinates out of range")
            if not item:
                warnings.append({"network": network, "station_id": identity, "code": "STATION_WITHOUT_STAC_ITEM"})
            relevant = [r for r in inventory if r["network"] == network and r["station_id"] == identity]
            stations.append({"network": network, "station_id": identity, "name": name, "canton": canton,
                             "wigos_id": native["station_wigos_id"] if native else "", "latitude_deg": lat, "longitude_deg": lon,
                             "elevation_m": height, "barometer_elevation_m": barometer, "data_since": since,
                             "owner": native["station_dataowner"] if native else "",
                             "coordinate_role": "published_position_not_dated_site_history" if native else "stac_point_station_table_metadata_missing",
                             "hourly_parameters": ";".join(sorted({r["parameter"] for r in relevant})),
                             "station_url": native["station_url_en"] if native else ""})
            if item:
                for name, asset in item.get("assets", {}).items():
                    parsed = parse_asset(name, network, identity, item["id"], asset, snapshot_year)
                    if parsed:
                        assets.append(parsed)
    for slug in DOCS:
        capture(DOC_BASE + slug, "provider_documentation")
    if not assets or len({a["url"] for a in assets}) != len(assets):
        raise SourceError("Empty or duplicate hourly assets")
    payload = {"schema": "IGE_CH_CATALOG_v1", "created_at_utc": retrieved, "networks": networks,
               "provider": "MeteoSwiss", "sources": sources, "stations": stations, "parameters": parameters,
               "inventory": inventory, "assets": assets, "warnings": warnings,
               "qc_policy": "Preserve native fields; missing per-value QC is not labelled automatic/manual or incorrect",
               "historical_positions_available": False}
    payload["catalog_id"] = digest(payload)
    atomic_write(output / "catalog.json.gz", gzip.compress(canonical(payload), mtime=0))
    atomic_write(output / "stations.csv", csv_bytes(stations, STATION_FIELDS))
    atomic_write(output / "inventory.csv.gz", gzip.compress(csv_bytes(inventory, list(inventory[0])), mtime=0))
    atomic_write(output / "assets.csv.gz", gzip.compress(csv_bytes(assets, list(assets[0])), mtime=0))
    write_json(output / "parameters.json", parameters)
    write_json(output / "catalog_warnings.json", warnings)
    atomic_write(output / "stations.geojson", canonical({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["longitude_deg"], s["latitude_deg"]]}, "properties": s} for s in stations]}))
    outputs = ("catalog.json.gz", "stations.csv", "stations.geojson", "inventory.csv.gz", "assets.csv.gz", "parameters.json", "catalog_warnings.json")
    write_json(output / "catalog_manifest.json", {"catalog_id": payload["catalog_id"], "created_at_utc": retrieved,
               "station_records": len(stations), "station_table_records": sum(1 for s in stations if s["coordinate_role"] == "published_position_not_dated_site_history"),
               "stations_by_network": dict(collections.Counter(s["network"] for s in stations)),
               "hourly_assets": len(assets), "hourly_inventory_records": len(inventory), "warnings": warnings,
               "files": {name: digest((output / name).read_bytes()) for name in outputs},
               "sources": sources, "license": "CC BY 4.0; Source: MeteoSwiss"})
    return payload


def nearest(catalog, lat, lon, date, *, networks=None, parameters=None, limit=10,
            radius_km=None, elevation_m=None, height_difference_m=None, exclude_ids=(), exclude_wigos=()):
    lat, lon = finite(lat), finite(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or limit < 1:
        raise SourceError("Invalid geographic search")
    when = parse_bound(date)
    networks = catalog["networks"] if networks is None else networks
    parameters = ["tre200h0"] if parameters is None else parameters
    if not networks or any(n not in catalog["networks"] for n in networks) or not parameters:
        raise SourceError("Invalid networks/parameters")
    available_codes = {p["parameter_shortname"] for n in networks for p in catalog["parameters"][n]}
    if set(parameters) - available_codes:
        raise SourceError("Unknown hourly parameter")
    if radius_km is not None and finite(radius_km) < 0:
        raise SourceError("Invalid radius")
    if height_difference_m is not None and (elevation_m is None or finite(height_difference_m) < 0):
        raise SourceError("Height filter requires target elevation and nonnegative difference")
    excluded = {station_id(s) for s in exclude_ids}
    eligible = collections.defaultdict(set)
    for row in catalog["inventory"]:
        if row["start_utc"] <= iso(when) and (row["end_utc_inclusive"] is None or iso(when) <= row["end_utc_inclusive"]):
            eligible[(row["network"], row["station_id"])].add(row["parameter"])
    result = []
    for s in catalog["stations"]:
        if s["network"] not in networks or s["station_id"] in excluded or s["wigos_id"] and s["wigos_id"] in exclude_wigos:
            continue
        if not set(parameters).issubset(eligible[(s["network"], s["station_id"])]):
            continue
        distance = distance_km(lat, lon, s["latitude_deg"], s["longitude_deg"])
        dh = None if elevation_m is None or s["elevation_m"] is None else s["elevation_m"] - finite(elevation_m)
        if radius_km is not None and distance > radius_km or height_difference_m is not None and (dh is None or abs(dh) > height_difference_m):
            continue
        result.append(s | {"distance_km": round(distance, 6), "station_minus_target_elevation_m": dh,
                           "selection_time_utc": iso(when), "donor_admission": "not_assessed"})
    return sorted(result, key=lambda s: (s["distance_km"], s["network"], s["station_id"]))[:limit]


def build_plan(catalog, config):
    allowed = {"start", "end", "networks", "station_ids", "parameters", "types", "min_interval_seconds"}
    if set(config) - allowed:
        raise SourceError("Unknown config keys")
    start, end = parse_bound(config["start"]), parse_bound(config["end"], end=True)
    if start >= end:
        raise SourceError("Start must precede end")
    networks = config.get("networks", catalog["networks"])
    if not isinstance(networks, list) or not networks or len(networks) != len(set(networks)) or any(n not in catalog["networks"] for n in networks):
        raise SourceError("Invalid networks")
    types = config.get("types", ["historical"])
    if not isinstance(types, list) or not types or len(types) != len(set(types)) or any(t not in ("historical", "recent", "now") for t in types):
        raise SourceError("Invalid asset types")
    selected = config.get("station_ids", "all")
    if selected != "all" and (not isinstance(selected, list) or not selected):
        raise SourceError("station_ids must be all or a nonempty list")
    selected = None if selected == "all" else {station_id(s) for s in selected}
    params = config.get("parameters", "all")
    definitions = {n: {p["parameter_shortname"]: p for p in catalog["parameters"][n]} for n in networks}
    all_codes = {p for ps in definitions.values() for p in ps}
    if params != "all" and (not isinstance(params, list) or not params or len(set(params)) != len(params) or set(params) - all_codes):
        raise SourceError("Invalid hourly parameter selection")
    jobs = []
    for asset in catalog["assets"]:
        n = asset["network"]
        if n not in networks or asset["type"] not in types or selected is not None and asset["station_id"] not in selected:
            continue
        if parse_bound(asset["nominal_start"]) >= end or parse_bound(asset["nominal_end_exclusive"]) <= start:
            continue
        required = sorted(definitions[n]) if params == "all" else sorted(set(params) & set(definitions[n]))
        if not required:
            continue
        job = dict(asset) | {"parameters": required}
        job["job_id"] = digest(job)[:24]
        jobs.append(job)
    jobs.sort(key=lambda j: (j["network"], j["station_id"], j["nominal_start"], j["type"]))
    if not jobs or selected is not None and selected - {j["station_id"] for j in jobs}:
        raise SourceError("Requested station/period has no matching hourly assets")
    interval = finite(config.get("min_interval_seconds", 1.0))
    if interval < 0:
        raise SourceError("Negative request interval")
    keys = {(j["network"], j["station_id"]) for j in jobs}
    sizes = [j["provider_bytes"] for j in jobs]
    plan = {"schema": "IGE_CH_PLAN_v1", "version": VERSION, "catalog_id": catalog["catalog_id"],
            "start_utc_inclusive": iso(start), "end_utc_exclusive": iso(end), "networks": networks, "types": types,
            "min_interval_seconds": interval, "jobs": jobs, "parameter_definitions": definitions,
            "stations": [s for s in catalog["stations"] if (s["network"], s["station_id"]) in keys],
            "source_metadata": catalog["sources"], "catalog_warnings": catalog["warnings"],
            "total_provider_bytes": sum(sizes) if all(isinstance(s, int) for s in sizes) else None,
            "size_note": "STAC sizes may be absent; bytes are not inferred from another station",
            "full_calendar_year_required": False, "quality_filter_applied": False,
            "time_rule": "UTC reference labels preserved; pre-2018 legacy SYNOP hour tagged, no silent rebinning"}
    plan["plan_id"] = digest(plan)
    return plan


def load_plan(path):
    plan = json.loads(Path(path).read_bytes())
    if plan.get("schema") != "IGE_CH_PLAN_v1" or plan.get("plan_id") != digest({k: v for k, v in plan.items() if k != "plan_id"}):
        raise SourceError("Plan identity/schema mismatch")
    if len(plan["jobs"]) != len({j["job_id"] for j in plan["jobs"]}):
        raise SourceError("Duplicate jobs")
    for job in plan["jobs"]:
        if job["job_id"] != digest({k: v for k, v in job.items() if k != "job_id"})[:24]:
            raise SourceError("Job identity mismatch")
        parsed = parse_asset(job["filename"], job["network"], job["station_id"], job["item_id"],
                             {"href": job["url"], "type": "text/csv"}, int(job["nominal_start"][:4]))
        if parsed is None or parsed["type"] != job["type"]:
            raise SourceError("Unsupported asset identity")
        safe_url(job["url"])
    return plan


def parse_observations(raw, plan, job):
    text, encoding = decode_csv(raw)
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=";")
    fields = reader.fieldnames
    definitions = plan["parameter_definitions"][job["network"]]
    if (not fields or len(fields) != len(set(fields)) or not {"station_abbr", "reference_timestamp"}.issubset(fields)
            or set(fields) - {"station_abbr", "reference_timestamp"} - set(definitions)):
        raise SourceError("Unknown/duplicate native hourly CSV columns; refresh metadata")
    if not set(fields) & set(definitions):
        raise SourceError("CSV has no known hourly measurement fields")
    start, end = parse_bound(plan["start_utc_inclusive"]), parse_bound(plan["end_utc_exclusive"])
    previous, result, total = None, [], 0
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise SourceError("Truncated/misaligned measurement CSV row")
        if station_id(row["station_abbr"]) != job["station_id"]:
            raise SourceError("Measurement station identity mismatch")
        stamp = source_time(row["reference_timestamp"])
        if previous is not None and stamp <= previous:
            raise SourceError("Duplicate/nonmonotonic measurement timestamps")
        previous, total = stamp, total + 1
        for name in fields:
            if name not in ("station_abbr", "reference_timestamp") and row[name].strip():
                finite(row[name])
        if start <= stamp < end:
            result.append({"timestamp_utc": iso(stamp), "hour_interval_regime": interval_regime(stamp), **row})
    if not total:
        raise SourceError("Empty measurement CSV")
    return fields, result, {"encoding": encoding, "source_rows": total,
                           "selected_rows": len(result), "qc_status": "per_value_flags_not_supplied_in_this_csv",
                           "missing_selected_columns": sorted(set(job["parameters"]) - set(fields))}


def coverage(rows, parameters, start, end):
    expected = int((end - start) / HOUR)
    variables = {p: {"non_null_rows": 0, "null_rows": 0, "non_null_full_hour_labels": 0,
                     "max_missing_full_hour_run": 0, "_last": start - HOUR} for p in parameters}
    axis, off_grid, regimes, previous = 0, 0, collections.Counter(), None
    for row in rows:
        stamp = dt.datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
        if not start <= stamp < end:
            continue
        if previous is not None and stamp <= previous:
            raise SourceError("Coverage rows must have unique ordered UTC labels")
        previous = stamp
        regimes[row["hour_interval_regime"]] += 1
        full = stamp.minute == 0
        axis += full
        off_grid += not full
        for p, entry in variables.items():
            if row.get(p, "").strip() == "":
                entry["null_rows"] += 1
            else:
                entry["non_null_rows"] += 1
                if full:
                    entry["non_null_full_hour_labels"] += 1
                    gap = int((stamp - entry["_last"]) / HOUR) - 1
                    entry["max_missing_full_hour_run"] = max(entry["max_missing_full_hour_run"], gap)
                    entry["_last"] = stamp
    for entry in variables.values():
        entry["max_missing_full_hour_run"] = max(entry["max_missing_full_hour_run"], int((end - entry.pop("_last")) / HOUR) - 1)
        entry["missing_full_hour_labels"] = expected - entry["non_null_full_hour_labels"]
        entry["coverage_percent_before_qc"] = round(100 * entry["non_null_full_hour_labels"] / expected, 6) if expected else None
    return {"start_utc_inclusive": iso(start), "end_utc_exclusive": iso(end),
            "expected_hourly_labels": expected, "present_full_hour_labels": axis,
            "absent_full_hour_labels": expected - axis, "off_grid_rows": off_grid,
            "full_label_axis": axis == expected and off_grid == 0, "hour_interval_regimes": dict(regimes),
            "parameters": variables, "qc_status": "per_value_flags_not_supplied_in_this_csv",
            "qc_filter_applied": False, "gap_filling_applied": False, "epw_admission_assessed": False}


def annual_coverages(rows, parameters, start, end):
    by_year = collections.defaultdict(list)
    for row in rows:
        by_year[int(row["timestamp_utc"][:4])].append(row)
    result = {}
    for year in range(start.year, (end - dt.timedelta(microseconds=1)).year + 1):
        lo = max(start, dt.datetime(year, 1, 1, tzinfo=UTC))
        hi = min(end, dt.datetime(year + 1, 1, 1, tzinfo=UTC))
        result[str(year)] = coverage(by_year[year], parameters, lo, hi)
    return result


def artifact_paths(job):
    j = job["job_id"]
    return ["raw/" + j + "/" + job["filename"] + ".gz", "parts/" + j + ".csv.gz", "metadata/" + j + ".json"]


def receipt_is_complete(root, job):
    try:
        receipt = json.loads((root / "receipts" / (job["job_id"] + ".json")).read_bytes())
        if receipt.get("status") != "complete" or receipt.get("job_sha256") != digest(job):
            return False
        artifacts = receipt["artifacts"]
        if len(artifacts) != 3 or {a["path"] for a in artifacts} != set(artifact_paths(job)):
            return False
        for a in artifacts:
            if digest((root / a["path"]).read_bytes()) != a["sha256"]:
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def save_job(root, plan, job, raw, *, response_headers=None):
    raw_path, part_path, meta_path = artifact_paths(job)
    # Preserve the response even if it does not match the planned provider version.
    raw_sha = digest(raw)
    if job.get("provider_sha256") and raw_sha != job["provider_sha256"]:
        atomic_write(root / "rejected" / job["job_id"] / (raw_sha + ".csv.gz"), gzip.compress(raw, mtime=0))
        raise SourceError("Provider checksum differs from frozen STAC; refresh catalogue and create a new plan/output")
    if job.get("provider_bytes") is not None and len(raw) != job["provider_bytes"]:
        raise SourceError("Provider size mismatch")
    atomic_write(root / raw_path, gzip.compress(raw, mtime=0))
    fields, rows, info = parse_observations(raw, plan, job)
    atomic_write(root / part_path, gzip.compress(csv_bytes(rows, TIME_FIELDS + fields), mtime=0))
    start = max(parse_bound(plan["start_utc_inclusive"]), parse_bound(job["nominal_start"]))
    end = min(parse_bound(plan["end_utc_exclusive"]), parse_bound(job["nominal_end_exclusive"]))
    reports = annual_coverages(rows, job["parameters"], start, end)
    station = next(s for s in plan["stations"] if s["network"] == job["network"] and s["station_id"] == job["station_id"])
    meta = {"source_url": job["url"], "raw_response_sha256": raw_sha, "provider_sha256": job.get("provider_sha256"),
            "raw_response_bytes": len(raw), "response_etag": (response_headers or {}).get("etag"),
            "native_fields": fields, "station_metadata": station,
            "parameter_definitions": plan["parameter_definitions"][job["network"]],
            "coverage_by_year": reports, "source_information": info,
            "hourly_rule": "UTC reference labels retained. Pre-2018 aggregation windows differ; parameter operator must also be consulted."}
    write_json(root / meta_path, meta)
    receipt = {"status": "complete", "retrieved_at_utc": now(), "job_sha256": digest(job),
               "raw_response_sha256": raw_sha, "provider_checksum_verified": bool(job.get("provider_sha256")),
               "source_information": info, "coverage_by_year": reports,
               "artifacts": [{"path": p, "sha256": digest((root / p).read_bytes())} for p in artifact_paths(job)],
               "complete_means_transfer_and_structure_only": True}
    write_json(root / "receipts" / (job["job_id"] + ".json"), receipt)
    return receipt


def download(plan, output, client, *, max_jobs=None):
    if max_jobs is not None and max_jobs < 1:
        raise SourceError("max-jobs must be positive")
    root = run_root(output, plan)
    with run_lock(root):
        write_json(root / "plan.json", plan)
        attempted, failures = 0, []
        for index, job in enumerate(plan["jobs"], 1):
            if receipt_is_complete(root, job):
                continue
            if max_jobs is not None and attempted >= max_jobs:
                break
            attempted += 1
            print(f"[{index}/{len(plan['jobs'])}] {job['network']} {job['station_id']} {job['filename']}", flush=True)
            try:
                raw = client.get(job["url"])
                receipt = save_job(root, plan, job, raw, response_headers=getattr(client, "response_headers", {}))
                print("  selected rows: " + str(receipt["source_information"]["selected_rows"]), flush=True)
            except (OSError, ValueError, TypeError, KeyError) as e:
                error = {"job_id": job["job_id"], "error": type(e).__name__ + ": " + str(e)}
                failures.append(error)
                with (root / "errors.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"at_utc": now(), **error}, ensure_ascii=False) + "\n")
                print("  FAILED: " + error["error"], file=sys.stderr, flush=True)
        completed = sum(receipt_is_complete(root, job) for job in plan["jobs"])
        result = {"plan_id": plan["plan_id"], "planned_jobs": len(plan["jobs"]), "completed_jobs": completed,
                  "remaining_jobs": len(plan["jobs"]) - completed, "attempted_this_invocation": attempted,
                  "failures_this_invocation": failures, "all_transfers_complete": completed == len(plan["jobs"]),
                  "meteorological_completeness_or_epw_admission_assessed": False}
        write_json(root / "download_summary.json", result)
        return result


def collect_year(plan, root, network, station, year, *, verified=False):
    station = station_id(station)
    if network not in plan["networks"] or not 1800 <= year <= 2200:
        raise SourceError("Invalid network/year")
    start = max(parse_bound(plan["start_utc_inclusive"]), dt.datetime(year, 1, 1, tzinfo=UTC))
    end = min(parse_bound(plan["end_utc_exclusive"]), dt.datetime(year + 1, 1, 1, tzinfo=UTC))
    if start >= end:
        raise SourceError("Year outside plan")
    jobs = [j for j in plan["jobs"] if j["network"] == network and j["station_id"] == station
            and parse_bound(j["nominal_start"]) < end and parse_bound(j["nominal_end_exclusive"]) > start]
    if not jobs or not verified and any(not receipt_is_complete(root, j) for j in jobs):
        raise SourceError("Export/audit blocked: required hourly assets missing or corrupt")
    priority = {"historical": 0, "recent": 1, "now": 2}
    merged, fields, conflicts, duplicates = {}, ["station_abbr", "reference_timestamp"], 0, 0
    for job in sorted(jobs, key=lambda j: (priority[j["type"]], j["job_id"])):
        with gzip.open(root / artifact_paths(job)[1], "rt", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for field in reader.fieldnames:
                if field not in TIME_FIELDS and field not in fields:
                    fields.append(field)
            for row in reader:
                stamp = dt.datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
                if not start <= stamp < end:
                    continue
                key = row["timestamp_utc"]
                if key in merged:
                    duplicates += 1
                    previous, old_job = merged[key]
                    comparable = set(row) | set(previous) - {"source_job_id"}
                    if any(row.get(k, "") != previous.get(k, "") for k in comparable if k != "source_job_id"):
                        conflicts += 1
                        if old_job["type"] == job["type"]:
                            raise SourceError("Conflicting rows within the same asset type")
                    continue
                merged[key] = (row | {"source_job_id": job["job_id"]}, job)
    rows = [v[0] for k, v in sorted(merged.items())]
    params = sorted({p for j in jobs for p in j["parameters"]})
    report = coverage(rows, params, start, end) | {"network": network, "station_id": station, "year": year,
        "selected_rows": len(rows), "calendar_year_hours": int((dt.datetime(year+1,1,1,tzinfo=UTC)-dt.datetime(year,1,1,tzinfo=UTC))/HOUR),
        "full_calendar_selection": start == dt.datetime(year,1,1,tzinfo=UTC) and end == dt.datetime(year+1,1,1,tzinfo=UTC),
        "duplicate_rows_removed": duplicates, "conflicts_preferred_historical_then_recent": conflicts,
        "source_jobs": [j["job_id"] for j in jobs]}
    return rows, fields, report


def export_station(plan, output, station, year, *, network="smn", plain=False):
    root = run_root(output, plan)
    with run_lock(root):
        rows, fields, report = collect_year(plan, root, network, station, year)
        body = csv_bytes(({k: r.get(k, "") for k in TIME_FIELDS + fields + ["source_job_id"]} for r in rows), TIME_FIELDS + fields + ["source_job_id"])
        path = root / "stations" / network / station_id(station) / (str(year) + (".csv" if plain else ".csv.gz"))
        atomic_write(path, body if plain else gzip.compress(body, mtime=0))
        report["file_sha256"] = digest(path.read_bytes())
        write_json(path.with_name(str(year) + ".coverage.json"), report)
        return {"path": str(path.resolve()), **report}


def audit(plan, output, report_path):
    root = run_root(output, plan)
    with run_lock(root):
        bad = [j["job_id"] for j in plan["jobs"] if not receipt_is_complete(root, j)]
        if bad:
            raise SourceError("Audit blocked: %d missing/corrupt assets; run download to resume" % len(bad))
        keys = sorted({(j["network"], j["station_id"], year)
                       for j in plan["jobs"]
                       for year in range(max(int(j["nominal_start"][:4]), int(plan["start_utc_inclusive"][:4])),
                                         min(int(j["nominal_end_exclusive"][:4]), int(plan["end_utc_exclusive"][:4])) + 1)
                       if dt.datetime(year,1,1,tzinfo=UTC) < parse_bound(plan["end_utc_exclusive"])
                       and dt.datetime(year+1,1,1,tzinfo=UTC) > parse_bound(plan["start_utc_inclusive"])
                       and dt.datetime(year,1,1,tzinfo=UTC) < parse_bound(j["nominal_end_exclusive"])
                       and dt.datetime(year+1,1,1,tzinfo=UTC) > parse_bound(j["nominal_start"])})
        result = []
        for network, station, year in keys:
            rows, fields, report = collect_year(plan, root, network, station, year, verified=True)
            for parameter, values in report["parameters"].items():
                result.append({"network": network, "station_id": station, "year": year, "parameter": parameter,
                               "unit": plan["parameter_definitions"][network][parameter]["parameter_unit"],
                               "calendar_year_hours": report["calendar_year_hours"], "selected_expected_hours": report["expected_hourly_labels"],
                               "rows": report["selected_rows"], **values, "qc_status": report["qc_status"],
                               "epw_admission_assessed": False})
        if not result:
            raise SourceError("No auditable station-years")
        report_path = Path(report_path)
        atomic_write(report_path, csv_bytes(result, list(result[0])))
        summary = {"plan_id": plan["plan_id"], "verified_assets": len(plan["jobs"]), "station_years": len(keys),
                   "parameter_rows": len(result), "report": str(report_path.resolve()),
                   "partial_station_years_retained": True, "network_requests": 0, "quality_filter_applied": False}
        write_json(report_path.with_suffix(".summary.json"), summary)
        return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("catalog", help="Refresh station/inventory/STAC snapshots")
    c.add_argument("--out", default="catalog_updated")
    c.add_argument("--networks", nargs="+", choices=list(NETWORKS))
    c = sub.add_parser("nearest", help="Find hourly-data candidates, not admitted donors")
    c.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    c.add_argument("--lat", required=True, type=float)
    c.add_argument("--lon", required=True, type=float)
    c.add_argument("--date", required=True)
    c.add_argument("--parameters", nargs="+", default=["tre200h0"])
    c.add_argument("--networks", nargs="+", choices=list(NETWORKS))
    c.add_argument("--limit", type=int, default=10)
    c.add_argument("--radius-km", type=float)
    c.add_argument("--elevation-m", type=float)
    c.add_argument("--max-height-difference-m", type=float)
    c.add_argument("--exclude-ids", nargs="*", default=[])
    c.add_argument("--exclude-wigos", nargs="*", default=[])
    c.add_argument("--csv")
    c = sub.add_parser("plan", help="Freeze hourly asset selection without downloading observations")
    c.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    c.add_argument("--config", required=True)
    c.add_argument("--out", required=True)
    c = sub.add_parser("download", help="Download/resume with checksum verification")
    c.add_argument("--plan", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--max-jobs", type=int)
    c = sub.add_parser("export", help="Export one station/year with coverage")
    c.add_argument("--plan", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--network", choices=list(NETWORKS), default="smn")
    c.add_argument("--station-id", required=True)
    c.add_argument("--year", type=int, required=True)
    c.add_argument("--plain-csv", action="store_true")
    c = sub.add_parser("audit", help="Offline coverage and gap report; retains partial years")
    c.add_argument("--plan", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--report", default="coverage.csv")
    args = p.parse_args(argv)
    try:
        if args.command == "catalog":
            cat = build_catalog(args.out, Client(), networks=args.networks)
            result = {"catalog_id": cat["catalog_id"], "station_records": len(cat["stations"]), "hourly_assets": len(cat["assets"]), "warnings": cat["warnings"]}
        elif args.command == "nearest":
            result = nearest(load_catalog(args.catalog), args.lat, args.lon, args.date,
                networks=args.networks, parameters=args.parameters, limit=args.limit, radius_km=args.radius_km,
                elevation_m=args.elevation_m, height_difference_m=args.max_height_difference_m,
                exclude_ids=args.exclude_ids, exclude_wigos=args.exclude_wigos)
            if args.csv:
                fields = STATION_FIELDS + ["distance_km", "station_minus_target_elevation_m", "selection_time_utc", "donor_admission"]
                atomic_write(args.csv, csv_bytes(result, fields))
        elif args.command == "plan":
            plan = build_plan(load_catalog(args.catalog), json.loads(Path(args.config).read_bytes()))
            write_json(args.out, plan)
            result = {"plan_id": plan["plan_id"], "station_records": len(plan["stations"]), "requests": len(plan["jobs"]), "provider_bytes": plan["total_provider_bytes"], "download_started": False}
        elif args.command == "download":
            plan = load_plan(args.plan)
            result = download(plan, args.out, Client(interval=plan["min_interval_seconds"]), max_jobs=args.max_jobs)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["failures_this_invocation"] else 0
        elif args.command == "export":
            result = export_station(load_plan(args.plan), args.out, args.station_id, args.year, network=args.network, plain=args.plain_csv)
        else:
            result = audit(load_plan(args.plan), args.out, args.report)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as e:
        print(type(e).__name__ + ": " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
