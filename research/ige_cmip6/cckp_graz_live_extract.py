#!/usr/bin/env python3
"""Independent extraction of World Bank CCKP public CMIP6 NetCDF anomalies.

This is an empirical data probe, not a weather generator. Future anomalies
refer to the CCKP 1995-2014 baseline. No observed 1991-2020 baseline is
silently combined with them.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import netCDF4
import numpy as np

BASE = "https://wbg-cckp.s3.amazonaws.com/"
ROOT = "data/cmip6-x0.25/"
GRAZ_LAT = 46.983
GRAZ_LON = 15.450
VARIABLES = ("tas", "pr")
SCENARIOS = ("ssp245", "ssp585")
WINDOWS = ("2040-2059", "2080-2099")
BASE_PERIOD = "1995-2014"
MAX_BYTES = 180 * 1024 * 1024
OUT = Path("outputs")
OUT.mkdir(exist_ok=True)
DOWNLOADS = Path("cckp_tmp")
DOWNLOADS.mkdir(exist_ok=True)
HEADERS = {"User-Agent": "IGE-Research-CCKP-CMIP6-Graz-Probe/0.2.2"}


def request(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=75)


def list_prefix(prefix: str):
    url = BASE + "?list-type=2&max-keys=1000&prefix=" + urllib.parse.quote(prefix, safe="")
    with request(url) as response:
        blob = response.read(5_000_000)
        if response.status != 200:
            raise RuntimeError(f"S3 list failed HTTP={response.status}: {prefix}")
    doc = ET.fromstring(blob)
    keys = []
    for el in doc.iter():
        if el.tag.rsplit("}", 1)[-1] != "Contents":
            continue
        d = {c.tag.rsplit("}", 1)[-1]: c.text for c in el}
        if d.get("Key", "").endswith(".nc"):
            keys.append({"key": d["Key"], "bytes": int(d.get("Size", 0))})
    truncated = next((x.text for x in doc.iter() if x.tag.rsplit("}",1)[-1]=="IsTruncated"),"false")
    if truncated.lower() == "true":
        raise RuntimeError(f"Catalog pagination required, refused incomplete list: {prefix}")
    return keys


def find_exact(keys, fragment: str, end: str):
    options = [x for x in keys
               if x["key"].split("/")[-1].startswith(fragment)
               and x["key"].split("/")[-1].endswith(end)]
    if len(options) != 1:
        names = [x["key"].split("/")[-1] for x in keys if "-monthly-" in x["key"]]
        raise RuntimeError(f"Expected exactly one match {fragment}*{end}; found {len(options)}. Candidates: {names[:18]}")
    return options[0]


def download(item: dict):
    size = item["bytes"]
    if not (0 < size <= MAX_BYTES):
        raise RuntimeError(f"Unexpected object size {size} for {item['key']}")
    url = BASE + urllib.parse.quote(item["key"], safe="/")
    dest = DOWNLOADS / Path(item["key"]).name
    if dest.exists():
        dest.unlink()
    attempts = []
    for attempt in range(3):
        sha = hashlib.sha256()
        n = 0
        try:
            with request(url) as response, open(dest, "wb") as out:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status} for {item['key']}")
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    out.write(block)
                    sha.update(block)
                    n += len(block)
                    if n > MAX_BYTES:
                        raise RuntimeError("File exceeds safety cap")
            if n != size:
                raise RuntimeError(f"Truncated download: {n} vs S3 listing {size}")
            return dest, sha.hexdigest(), url
        except Exception as exc:
            attempts.append(str(exc))
            if dest.exists():
                dest.unlink()
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Download failed after 3 attempts: {item['key']}: {attempts}")


def locate(ds):
    latvar = lonvar = None
    for name, v in ds.variables.items():
        std = str(getattr(v, "standard_name", "")).lower()
        if v.ndim == 1 and (name.lower() in {"lat","latitude"} or std == "latitude"):
            latvar = v
        if v.ndim == 1 and (name.lower() in {"lon","longitude"} or std == "longitude"):
            lonvar = v
    if latvar is None or lonvar is None:
        raise RuntimeError("No recognizable one-dimensional geographic coordinates: " + str(list(ds.variables)))
    lats = np.asarray(latvar[:], dtype=float)
    lons = np.asarray(lonvar[:], dtype=float)
    query_lon = GRAZ_LON % 360 if np.nanmax(lons) > 180 else GRAZ_LON
    lat_i = int(np.nanargmin(abs(lats - GRAZ_LAT)))
    lon_i = int(np.nanargmin(abs(lons - query_lon)))
    return latvar.dimensions[0], lonvar.dimensions[0], lat_i, lon_i, float(lats[lat_i]), float(lons[lon_i])


def extract(path: Path, expected_variable: str):
    with netCDF4.Dataset(path) as ds:
        latdim, londim, lati, loni, slat, slon = locate(ds)
        options = [(n, v) for n, v in ds.variables.items()
                   if n not in ds.dimensions
                   and latdim in v.dimensions
                   and londim in v.dimensions
                   and v.ndim >= 3]
        ranked = [(n,v) for n,v in options if expected_variable.lower() in n.lower()]
        if len(ranked) == 1:
            name, var = ranked[0]
        elif len(options) == 1:
            name, var = options[0]
        else:
            raise RuntimeError("Ambiguous data variables: " + str([(n,v.dimensions) for n,v in options]))
        index = []
        untouched = []
        for dim in var.dimensions:
            if dim == latdim:
                index.append(lati)
            elif dim == londim:
                index.append(loni)
            elif len(ds.dimensions[dim]) == 12:
                index.append(slice(None))
                untouched.append(dim)
            elif len(ds.dimensions[dim]) == 1:
                index.append(0)
            else:
                raise RuntimeError(f"Unexpected dimension {dim}={len(ds.dimensions[dim])}; no silent slicing")
        values = np.asarray(np.ma.filled(var[tuple(index)], np.nan), dtype=float).reshape(-1)
        if len(values) != 12 or len(untouched) != 1 or not np.all(np.isfinite(values)):
            raise RuntimeError(f"Expected 12 valid monthly values, got {values.shape}, remaining={untouched}")
        attr = {k: str(getattr(ds, k))[:500] for k in ds.ncattrs() if k.startswith("wb_") or k in ("title", "institution", "source", "history")}
        vattr = {k: str(getattr(var, k))[:500] for k in var.ncattrs() if k in ("units","long_name","standard_name","description","comment")}
        return {
            "field": name,
            "dimensions": list(var.dimensions),
            "month_dimension": untouched[0],
            "units": str(getattr(var, "units", "UNSPECIFIED")),
            "coordinates": {"requested_lat": GRAZ_LAT, "requested_lon": GRAZ_LON,
                            "sample_lat":slat, "sample_lon":slon,
                            "lat_index":lati,"lon_index":loni,
                            "sampling_method":"nearest_native_grid_node"},
            "values": [float(v) for v in values],
            "global_attributes": attr,
            "variable_attributes": vattr,
        }


def main():
    report = {
        "status": "started",
        "source": "World Bank CCKP public S3; datasets unmodified",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "coordinate": {"lat":GRAZ_LAT,"lon":GRAZ_LON,"label":"Graz Meteonorm EPW reference coordinate"},
        "baseline_declared": BASE_PERIOD,
        "requested_windows": list(WINDOWS),
        "warning": "2040-2059 and 2080-2099 are 20-year climatologies, not point values for 2050 or 2100. Anomalies must not be directly added to 1991-2020 observations.",
        "records": [],
        "errors": [],
    }
    catalog = {}
    rows = []
    try:
        for variable in VARIABLES:
            for scenario in SCENARIOS:
                prefix = f"{ROOT}{variable}/ensemble-all-{scenario}/"
                catalog[prefix] = list_prefix(prefix)
                print("CATALOG",prefix,len(catalog[prefix]),flush=True)
        (OUT/"cckp_catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")

        # Ensemble anomaly products have CCKP's own fixed historical reference;
        # do not confuse them with observed GeoSphere station normal 1991-2020.
        for variable in VARIABLES:
            for scenario in SCENARIOS:
                prefix = f"{ROOT}{variable}/ensemble-all-{scenario}/"
                for window in WINDOWS:
                    end = f"_climatology_median_{window}.nc"
                    source = find_exact(catalog[prefix], f"anomaly-{variable}-monthly-mean_", end)
                    print("SELECT",variable,scenario,window,source["key"],source["bytes"],flush=True)
                    path, sha, url = download(source)
                    try:
                        extraction = extract(path, variable)
                    finally:
                        path.unlink(missing_ok=True)
                    record = {
                        "variable": variable, "scenario": scenario, "window": window,
                        "key":source["key"],"source_url":url,"bytes":source["bytes"],
                        "sha256":sha, **extraction
                    }
                    report["records"].append(record)
                    print("EXTRACT",variable,scenario,window, "unit=",extraction["units"],
                          "range=",min(extraction["values"]),max(extraction["values"]),
                          "grid=",extraction["coordinates"]["sample_lat"],extraction["coordinates"]["sample_lon"],
                          flush=True)
                    for m,v in enumerate(extraction["values"], 1):
                        rows.append({
                            "site":"Graz","lat":GRAZ_LAT,"lon":GRAZ_LON,
                            "scenario":scenario,"window":window,"variable":variable,
                            "month":m,"anomaly_raw":v,"native_units":extraction["units"],
                            "sample_lat":extraction["coordinates"]["sample_lat"],
                            "sample_lon":extraction["coordinates"]["sample_lon"],
                            "baseline":BASE_PERIOD,"source_key":source["key"],
                            "sha256":sha,
                        })
        report["status"]="PASS"
    except Exception as exc:
        report["status"]="FAIL"
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print("FAIL",repr(exc), flush=True)
        raise
    finally:
        (OUT/"cckp_graz_anomaly_provenance.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
        if rows:
            with (OUT/"cckp_graz_monthly_anomalies.csv").open("w",newline="",encoding="utf-8") as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        (OUT/"README.md").write_text(
            "# IGE real CMIP6 CCKP experiment\n\n"
            f"Status: {report['status']}\n\n"
            "Requested location: 46.983N, 15.450E (Meteonorm Graz reference).\n\n"
            "Scenarios: SSP2-4.5 and SSP5-8.5; variables: tas and pr.\n\n"
            "Native anomaly units are preserved. No arbitrary conversion to Celsius or mm.\n\n"
            "2040-2059 and 2080-2099 are ensemble climatological periods, not 2050/2100 instantaneous forecasts.\n\n"
            "Dataset anomaly reference is CCKP 1995-2014; do not add to 1991-2020 GeoSphere normals directly.\n\n"
            "Source URLs, sha256, raw variable names, units and attributes are in the provenance JSON.\n\n"
            "This research workflow does not change the production Climate Analyzer or publish the NetCDF inputs.\n",
            encoding="utf-8")
    if report["status"]!="PASS":
        raise RuntimeError("Research extraction incomplete; inspect provenance artifact")


if __name__ == "__main__":
    main()
