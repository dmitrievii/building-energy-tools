#!/usr/bin/env python3
"""P9.3B2D preregistered source-only DWD true station-P census.

Counts only; NEVER logs pressure measurements, model predictions or errors.
Fixed candidate order and windows are documented before source readback.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

ROOT = ("https://opendata.dwd.de/climate_environment/CDC/"
        "observations_germany/climate/hourly/pressure/historical/")
META = "P0_Stundenwerte_Beschreibung_Stationen.txt"
WINDOWS = {"JAN_2023": ("2023011000", "2023011623"),
           "JUL_2023": ("2023071000", "2023071623")}
STRATA = (
    ("LOWLAND", ("01420", "03015")),
    ("SOUTHWEST", ("01443", "05440")),
    ("ALPINE_APPROACH", ("02559", "01550")),
)
MIN_VALID_PER_WINDOW = 144
MAX_BYTES = 10_000_000


def load(url, cap=MAX_BYTES):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme, parsed.hostname) != ("https", "opendata.dwd.de"):
        raise ValueError("P93B2D_SOURCE_HOST_NOT_WHITELISTED")
    if not parsed.path.startswith(urllib.parse.urlsplit(ROOT).path):
        raise ValueError("P93B2D_SOURCE_PATH_NOT_WHITELISTED")
    req = urllib.request.Request(url, headers={"User-Agent":
        "IGE-P93B2D-fixed-source-census-before-pressure-validation/1.0"})
    with urllib.request.urlopen(req, timeout=100) as res:
        buf = res.read(cap + 1)
    if len(buf) > cap:
        raise ValueError("P93B2D_SOURCE_TOO_LARGE")
    return buf, hashlib.sha256(buf).hexdigest()


def metadata(original_bytes):
    stations = {}
    for line in original_bytes.decode("latin1").splitlines():
        m = re.match(r"^\s*(\d{5})\s+(\d{8})\s+(\d{8})\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+", line)
        if not m:
            continue
        sid, begin, end, z, lat, lon = m.groups()
        if sid in {s for _, group in STRATA for s in group}:
            if sid in stations:
                raise ValueError("P93B2D_DUPLICATE_SOURCE_STATION")
            stations[sid] = {"id": sid, "start": begin, "end": end,
                "height_m": float(z), "lat": float(lat), "lon": float(lon),
                "original_source_line": line.strip()}
    return stations


def archive_name(listing, sid):
    text = listing.decode("utf8", errors="replace")
    pairs = set(re.findall(
        rf"stundenwerte_P0_{re.escape(sid)}_(\d{{8}})_(\d{{8}})_hist\.zip",
        text, re.I))
    matches = [p for p in pairs if p[0] <= "20230110" and p[1] >= "20230716"]
    if len(matches) != 1:
        raise ValueError("P93B2D_NO_UNAMBIGUOUS_2023_HISTORICAL_ZIP")
    a, b = matches[0]
    return f"stundenwerte_P0_{sid}_{a}_{b}_hist.zip"


def field_counts(original_zip, sid):
    seen = {n: set() for n in WINDOWS}
    out = {n: {"native_rows": 0, "valid_QC10": 0, "valid_QC3": 0,
               "valid_other_QC": 0, "missing_P": 0, "P0_numeric_nonzero": 0,
               "native_QN8_histogram": Counter()} for n in WINDOWS}
    with zipfile.ZipFile(io.BytesIO(original_zip)) as z:
        if z.testzip() is not None:
            raise ValueError("P93B2D_ORIGINAL_DWD_ZIP_BAD_CRC")
        members = [n for n in z.namelist()
                   if Path(n).name.startswith("produkt_p0_stunde_")
                   and n.endswith(".txt")]
        if len(members) != 1:
            raise ValueError("P93B2D_DWD_CSV_NOT_UNIQUE")
        with io.TextIOWrapper(z.open(members[0]), encoding="latin1") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            if not {"STATIONS_ID", "MESS_DATUM", "QN_8", "P", "P0"}.issubset(
                    set((x or "").strip() for x in (reader.fieldnames or []))):
                raise ValueError("P93B2D_NO_NATIVE_P_AND_P0_COLUMNS")
            for row in reader:
                stamp = (row.get("MESS_DATUM") or "").strip()
                name = next((n for n, (a, b) in WINDOWS.items()
                             if a <= stamp <= b), None)
                if name is None:
                    continue
                if int(row["STATIONS_ID"]) != int(sid):
                    raise ValueError("P93B2D_CROSS_STATION_DATA")
                if stamp in seen[name]:
                    raise ValueError("P93B2D_DUPLICATE_ORIGINAL_STATION_HOUR")
                if dt.datetime.strptime(stamp, "%Y%m%d%H").strftime("%Y%m%d%H") != stamp:
                    raise ValueError("P93B2D_UTC_STAMP_PARSE_FAILED")
                seen[name].add(stamp)
                item = out[name]
                item["native_rows"] += 1
                q = (row.get("QN_8") or "").strip()
                item["native_QN8_histogram"][q] += 1
                try:
                    v = float((row.get("P") or "").strip())
                except ValueError:
                    v = float("nan")
                try:
                    v0 = float((row.get("P0") or "").strip())
                except ValueError:
                    v0 = float("nan")
                if math.isfinite(v0) and 450 < v0 < 1100:
                    item["P0_numeric_nonzero"] += 1  # never a P substitute
                if not (math.isfinite(v) and 450 < v < 1100):
                    item["missing_P"] += 1
                elif q == "10":
                    item["valid_QC10"] += 1
                elif q == "3":
                    item["valid_QC3"] += 1
                else:
                    item["valid_other_QC"] += 1
    for item in out.values():
        item["native_QN8_histogram"] = dict(item["native_QN8_histogram"])
        item["valid_combined_QC10_QC3"] = item["valid_QC10"] + item["valid_QC3"]
    return out


def choose(source):
    selected = {}
    for stratum, candidates in STRATA:
        selected[stratum] = next((sid for sid in candidates
            if source.get(sid, {}).get("status") == "SOURCE_FIELD_P_READ"
            and all(source[sid]["windows"][w]["valid_combined_QC10_QC3"]
                    >= MIN_VALID_PER_WINDOW for w in WINDOWS)), None)
    return selected


def synthetic_contracts():
    assert choose({"01420": {"status": "SOURCE_FIELD_P_READ",
              "windows": {w: {"valid_combined_QC10_QC3": 143}
                          for w in WINDOWS}},
                   "03015": {"status": "SOURCE_FIELD_P_READ",
              "windows": {w: {"valid_combined_QC10_QC3": 144}
                          for w in WINDOWS}}})["LOWLAND"] == "03015"
    assert choose({}) == dict.fromkeys(s for s, _ in STRATA)
    assert len({id_ for _, arr in STRATA for id_ in arr}) == 6
    assert all(len(str(k)) == 8 for bounds in WINDOWS.values() for k in bounds)
    assert all(int(b[-2:]) == 23 for _, b in WINDOWS.values())
    print("P93B2D_SOURCE_ONLY_UNIT_CONTRACTS_PASS")


def run(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    result = {"phase": "P93B2D_GERMAN_ORIGINAL_STATION_P_ONLY_AVAILABILITY_CENSUS",
              "pre_registered_protocol":
                "docs/IGE_P9_3B2D_DWD_SOURCE_CENSUS_PREREG_20261020_RU.md",
              "sample_selection_before_any_error_scoring": True,
              "pressure_P_true_station_level_not_P0": True,
              "original_pressure_measurements_emitted": False,
              "model_pressure_called": False,
              "production_pressure_qualified": False,
              "windows": WINDOWS, "min_valid_unique_hours_per_window":
                 MIN_VALID_PER_WINDOW, "strata": STRATA, "sources": {}}
    source = result["sources"]
    try:
        meta_raw, meta_sha = load(ROOT + META, 900_000)
        index_raw, index_sha = load(ROOT, 2_500_000)
        result["DWD_metadata_SHA256"] = meta_sha
        result["DWD_listing_SHA256"] = index_sha
        stations = metadata(meta_raw)
        for _, candidates in STRATA:
            for sid in candidates:
                info = {"station": stations.get(sid), "status": "NOT_EVALUATED"}
                source[sid] = info
                try:
                    if sid not in stations:
                        raise ValueError("P93B2D_ORIGINAL_METADATA_STATION_NOT_FOUND")
                    if not (stations[sid]["start"] <= "20230110"
                            and stations[sid]["end"] >= "20230716"):
                        raise ValueError("P93B2D_STATION_NOT_ACTIVE_IN_BOTH_WINDOWS")
                    filename = archive_name(index_raw, sid)
                    raw, sha = load(ROOT + filename)
                    info.update({"archive_name": filename, "archive_SHA256": sha,
                                 "windows": field_counts(raw, sid),
                                 "status": "SOURCE_FIELD_P_READ"})
                except Exception as exc:
                    info.update({"status": "SOURCE_BLOCKED",
                                 "reason": f"{type(exc).__name__}: {exc}"[:240]})
                print("P93B2D_DWD_TRUE_P_CENSUS", sid,
                    json.dumps({"status": info["status"],
                                "windows": info.get("windows")}), flush=True)
        result["selected_by_source_only_rule"] = choose(source)
        result["eligible_strata"] = sum(v is not None for v in
                                      result["selected_by_source_only_rule"].values())
        result["status"] = ("SOURCE_CENSUS_COMPLETED_ALL_STRATA" if
                            result["eligible_strata"] == len(STRATA)
                            else "SOURCE_CENSUS_COMPLETED_PARTIAL_OR_BLOCKED")
    except Exception as exc:
        result["status"] = "SOURCE_CENSUS_UNAVAILABLE"
        result["source_failure_reason"] = f"{type(exc).__name__}: {exc}"[:350]
    (directory / "p9_3b2d_dwd_true_P_source_census.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print("P93B2D_CENSUS_FINAL",
          json.dumps({"status": result["status"],
                      "selected": result.get("selected_by_source_only_rule"),
                      "source_only": True, "pressure_errors_seen": False}), flush=True)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="outputs/p93b2d-source")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    synthetic_contracts()
    if not args.self_test:
        run(args.out)
