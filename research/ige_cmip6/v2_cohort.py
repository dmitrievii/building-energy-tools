"""V2 metadata-only cohort discovery. No station measurements or models.

The bounded discovery frame is specified before new metadata requests.
Possible prior-use evidence is excluded conservatively, never promoted to
proof of actual raw-byte exposure or global absence of prior use.
"""
from __future__ import annotations
import ast
from dataclasses import asdict
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

import numpy as np
import pandas as pd

from a1_prepare import metadata_sources
from v1_prepare import metadata as v1_metadata
from epw_climate_analyzer.station_admission import physical_identity
from epw_climate_analyzer.station_reconstruction import StationReference, _csv

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "research/ige_cmip6"
BASE = "8320428593cbb27418581e56fc43176d46fe6337"
DESIGN = "v1a_next_validation_design_20261027.json"
DESIGN_SHA = "60efc5bdc4e1c3f324e8a2043ce76375fd6cdc4348b044585b53e78a378d6422"
FRAME_PER_COUNTRY = 18
COUNTRIES = ("AT", "DE", "CH")
METADATA_ATTEMPTS_MAX = 240
FIRST = pd.Timestamp("2019-01-10T00:00Z")
LAST = pd.Timestamp("2019-10-16T23:00Z")


def json_bytes(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def design():
    raw = (R / DESIGN).read_bytes()
    if sha256(raw).hexdigest() != DESIGN_SHA:
        raise ValueError("V2_PARENT_DESIGN_CHANGED")
    return json.loads(raw)


def catalogs():
    old, receipts, _ = metadata_sources(); newer, _ = v1_metadata()
    first = pd.Timestamp("2019-01-01", tz="UTC"); last = pd.Timestamp("2019-12-31T23:00Z")
    at_rows = json.loads(old["AT_hourly_v2_metadata.json"])["stations"]
    pool = []
    for row in at_rows:
        if row["type"] == "INDIVIDUAL" and pd.Timestamp(row["valid_from"]) <= first <= last <= pd.Timestamp(row["valid_to"]):
            pool.append(StationReference("AT", str(row["id"]), row["name"], row["lat"], row["lon"], row["altitude"],
                sha256(old["AT_hourly_v2_metadata.json"]).hexdigest(), physical_identity("AT", str(row["id"]), group_id=row["group_id"])))
    for line in newer["DE_10min_stations.txt"].decode("cp1252").splitlines():
        match = re.match(r"^\s*(\d{5})\s+(\d{8})\s+(\d{8})\s+(-?[\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+?)\s{2,}", line)
        if not match:
            continue
        sid, a, b, h, lat, lon, name = match.groups()
        if a <= "20190101" and b >= "20191231":
            pool.append(StationReference("DE", sid, name.strip(), float(lat), float(lon), float(h),
                sha256(newer["DE_10min_stations.txt"]).hexdigest(), physical_identity("DE", sid)))
    inventory, _ = _csv(old["CH_inventory.csv"]); available = set()
    for row in inventory:
        if row["parameter_shortname"] != "tre200h0":
            continue
        a = pd.to_datetime(row["data_since"], format="%d.%m.%Y %H:%M", utc=True)
        b = pd.to_datetime(row["data_till"], format="%d.%m.%Y %H:%M", utc=True) if row["data_till"].strip() else pd.Timestamp("2100-01-01", tz="UTC")
        if a <= first <= last <= b:
            available.add(row["station_abbr"])
    rows, _ = _csv(old["CH_stations.csv"])
    for row in rows:
        sid = row["station_abbr"]
        if sid in available:
            pool.append(StationReference("CH", sid, row["station_name"], float(row["station_coordinates_wgs84_lat"]),
                float(row["station_coordinates_wgs84_lon"]), float(row["station_height_masl"]),
                sha256(old["CH_stations.csv"]).hexdigest(), physical_identity("CH", sid, wsi=row["station_wigos_id"])))
    if len({s.key for s in pool}) != len(pool):
        raise ValueError("V2_CATALOG_DUPLICATE")
    sources = {"AT_hourly_v2_metadata.json": sha256(old["AT_hourly_v2_metadata.json"]).hexdigest(),
        "DE_10min_stations.txt": sha256(newer["DE_10min_stations.txt"]).hexdigest(),
        "CH_inventory.csv": sha256(old["CH_inventory.csv"]).hexdigest(), "CH_stations.csv": sha256(old["CH_stations.csv"]).hexdigest()}
    return sorted(pool, key=lambda s: s.key), at_rows, sources


def frozen_text():
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE, "--", "research/ige_cmip6", "docs", ".github/workflows"], cwd=ROOT, text=True).splitlines()
    # Source/program/protocol text only. No compressed observation body or
    # hourly CSV is opened to construct an exposure registry.
    paths = [p for p in paths if Path(p).suffix in (".py", ".md", ".yml", ".yaml", ".json")
             and not Path(p).name.startswith("test_")]
    data = subprocess.check_output(["git", "archive", "--format=tar", BASE, "--", *paths], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return {p: archive.extractfile(p).read() for p in paths}


def retained_exposure(pool, at_rows):
    texts = frozen_text(); by_key = {s.key: s for s in pool}
    all_at = {str(r["id"]): r for r in at_rows}
    ch_ids = {s.station_id for s in pool if s.country == "CH"}
    de_ids = {s.station_id for s in pool if s.country == "DE"}
    evidence = {s.key: [] for s in pool}
    def add(key, path, kind, detail):
        if key in evidence and len(evidence[key]) < 16:
            row = {"path": path, "kind": kind, "detail": detail}
            if row not in evidence[key]: evidence[key].append(row)
    def at_alias(sid, path, kind):
        sid = str(int(sid)); row = all_at.get(sid)
        if row is None: return
        group = int(sid) if row["type"] == "COMBINED" else row.get("group_id")
        for target in pool:
            if target.country != "AT": continue
            candidate = all_at[target.station_id]
            if target.station_id == sid or group is not None and candidate.get("group_id") == group:
                add(target.key, path, kind, "GeoSphere physical/group alias of " + sid)
    for path, raw in texts.items():
        text = raw.decode("utf-8", errors="replace")
        # Explicit station keys in retained protocols/reports, including
        # unobserved reserved targets, are excluded. A mention alone is not
        # labelled a confirmed measurement download.
        for country, sid in re.findall(r"\b(AT|DE|CH):([A-Z0-9]+)\b", text):
            if country == "AT" and sid.isdigit(): at_alias(sid, path, "EXPLICIT_PRIOR_OR_RESERVED_IDENTITY")
            else: add(country + ":" + sid, path, "EXPLICIT_PRIOR_OR_RESERVED_IDENTITY", "retained station key")
        if Path(path).suffix != ".py":
            continue
        try: tree = ast.parse(text)
        except SyntaxError: continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for sid in set(re.findall(r"(?<![A-Za-z0-9_])([A-Z]{3})(?![A-Za-z0-9_])", node.value)) & ch_ids:
                    add("CH:" + sid, path, "CONSERVATIVE_PRIOR_CODE_IDENTITY", "exact Swiss identifier in a Python string; not proof of execution")
                for sid in set(re.findall(r"(?<!\d)(\d{5})(?!\d)", node.value)) & de_ids:
                    if "dwd" in path.lower() or "dwd" in text.lower():
                        add("DE:" + sid, path, "CONSERVATIVE_PRIOR_CODE_IDENTITY", "DWD identifier literal; not proof of execution")
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            names = [n.id for n in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(n, ast.Name)]
            if not any(re.fullmatch(r"(?:.*_)?(?:IDS|SITES|STATIONS|TARGETS|POOL|ANCHORS)(?:_.*)?", n) for n in names):
                continue
            try: value = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError): continue
            def visit(item, country=None):
                if isinstance(item, dict):
                    for k, v in item.items(): visit(v, k if k in COUNTRIES else country)
                elif isinstance(item, (list, tuple, set)):
                    for v in item: visit(v, country)
                elif isinstance(item, (int, str)) and not isinstance(item, bool):
                    if str(item).isdigit():
                        if country == "AT" or country is None and "geosphere" in text.lower(): at_alias(item, path, "CONSERVATIVE_PRIOR_STATION_SET")
                        if country == "DE" or country is None and "dwd" in text.lower():
                            add("DE:" + str(int(item)).zfill(5), path, "CONSERVATIVE_PRIOR_STATION_SET", "station-set literal; not proof of execution")
            visit(value)
    old = json.loads(texts["research/ige_cmip6/v1_exposure_audit_20261026.json"])
    for sid in old["old_CH_2010_2019_hourly_candidate_union"]:
        add("CH:" + sid, "research/ige_cmip6/v1_exposure_audit_20261026.json", "PRIOR_2010_2019_CONTAINER_REQUEST_SCOPE", "whole h container, including unused years/variables; conservatively excluded")
    # The retained wind aggregate contains metadata, target identities and
    # provenance. Never read a new observation payload to inspect exposure.
    artifact_path = "research/ige_cmip6/a12_prior_wind_provenance_39023515729.zip"
    data = (ROOT / artifact_path).read_bytes()
    if sha256(data).hexdigest() != "33e1f8fc85fbf0de9c2baa820fc58adfd1e7ee02dd4661b67ad50397da83e8c7":
        raise ValueError("V2_PRIOR_WIND_PROVENANCE_HASH")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist()) != 1 or archive.infolist()[0].file_size > 2_000_000:
            raise ValueError("V2_PRIOR_WIND_AGGREGATE_ONLY")
        past = json.loads(archive.read(archive.namelist()[0]))
    for sid in past["new_targets"]:
        add("CH:" + sid, artifact_path, "PRIOR_WIND_TARGET_IDENTITY", "previous target excluded regardless of different field/decade")
    return {"schema": "IGE_V2_BOUNDED_METADATA_ONLY_EXPOSURE_v1", "parent_commit": BASE,
        "retained_text_file_sha256": {p: sha256(raw).hexdigest() for p, raw in texts.items()},
        "retained_text_files": len(texts), "evidence_by_catalog_station": evidence,
        "prior_2020_2029_CH_wind_container_census": len(past["full_catalog_original_provenance"]),
        "wind_decade_not_silently_relabelled_2010_2019": True,
        "prior_coarse_monthly_climatology_exposure": "broad AT/CH studies; not certified station-blind; all explicit prior/reserved identities additionally excluded",
        "scope_limits": ["retained source, protocol/report text and one checked aggregate provenance", "expired or unpublished artifacts and unindexed sessions not globally certifiable", "code-set literals conservatively excluded without claiming execution", "ERA5 assimilation and provider spatial QC dependence remain"],
        "global_raw_byte_blindness_certified": False, "new_measurements_opened": False}


def tie_key(station_key):
    return sha256(("IGE_V2_2019|" + station_key + "|20261027").encode()).hexdigest()


def discovery():
    design(); pool, at, sources = catalogs(); exposure = retained_exposure(pool, at)
    frame, counts = [], {}
    for country in COUNTRIES:
        candidates = [s for s in pool if s.country == country and not exposure["evidence_by_catalog_station"][s.key]]
        candidates.sort(key=lambda s: (tie_key(s.key), s.key))
        # Bounded metadata discovery is a new pre-weather clarification of the
        # parent design, not a change to any registered weather experiment.
        chosen = []; seen = set()
        for station in candidates:
            if station.identity_group in seen: continue
            seen.add(station.identity_group); chosen.append(station)
            if len(chosen) == FRAME_PER_COUNTRY: break
        counts[country] = {"2019_catalog": sum(s.country == country for s in pool), "exposure_admitted_for_metadata": len(candidates), "frozen_metadata_frame": len(chosen)}
        frame.extend(asdict(s) for s in chosen)
    return {"schema": "IGE_V2_PREWEATHER_METADATA_DISCOVERY_FRAME_v1", "parent_commit": BASE,
        "parent_design_sha256": DESIGN_SHA, "source_catalog_sha256": sources,
        "counts": counts, "frame_per_country_cap": FRAME_PER_COUNTRY,
        "frame_order": "ascending SHA256 IGE_V2_2019|station_key|20261027 then key, after conservative exposure exclusions",
        "relative_height_strata_applied_after_dated_metadata_admission": True,
        "frame_physical_identity_aliases_deduplicated": True,
        "metadata_HTTP_attempts_total_cap": METADATA_ATTEMPTS_MAX,
        "targets_selected": False, "new_weather_requests_authorized": 0,
        "metadata_candidates": frame}, exposure


if __name__ == "__main__":
    frame, exposure = discovery()
    print(json.dumps({"counts": frame["counts"], "candidates": [(r["country"] + ":" + r["station_id"], r["name"]) for r in frame["metadata_candidates"]], "text_files": exposure["retained_text_files"]}, ensure_ascii=False, indent=2))
