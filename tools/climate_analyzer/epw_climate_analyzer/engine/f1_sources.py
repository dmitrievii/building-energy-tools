"""F1: location-specific original NEX v2 point subsets and strict offline replay.

No old Graz signal is substituted. NCSS stationAltitude=0 is a transport
placeholder, never interpreted as terrain height or future surface pressure.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import calendar
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import math
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

from .contracts import finite_number
from .historical import json_bytes
from .model_sources import bounded_zip, monthly_nex_signals

SCHEMA = "IGE_F1_NEX_ORIGINAL_POINT_SOURCES_v1"
SEMANTICS = "F1_CANESM5_V2_VERIFIED_MIDRANGE_MONTHLY_TRANSFER_v1"
ROOT = "https://ds.nccs.nasa.gov/thredds"
SPECS = {"tas": ("K", 180., 350.), "tasmin": ("K", 170., 350.), "tasmax": ("K", 180., 355.),
    "huss": ("1", 0., 1.), "hurs": ("%", 0., 105.), "pr": ("kg m-2 s-1", 0., .05),
    "rsds": ("W m-2", 0., 1000.), "rlds": ("W m-2", 0., 1000.), "sfcWind": ("m s-1", 0., 120.)}
MAX_PACKET = 120*1024**2
SCENARIOS = ("ssp126", "ssp245", "ssp370", "ssp585")
SCENARIO_LABELS = {"ssp126": "SSP1-2.6 · low emissions", "ssp245": "SSP2-4.5 · intermediate emissions",
                   "ssp370": "SSP3-7.0 · high emissions", "ssp585": "SSP5-8.5 · very high emissions"}


@dataclass(frozen=True)
class SignalRequest:
    latitude: float
    longitude: float
    reference_window: tuple[int, int] = (2002, 2014)
    future_window: tuple[int, int] = (2040, 2059)
    model: str = "CanESM5"
    member: str = "r1i1p1f1"
    scenario: str = "ssp245"

    def __post_init__(self):
        if not -60 <= finite_number(self.latitude, "LATITUDE") <= 89.875:
            raise ValueError("F1_NEX_LATITUDE_OUTSIDE_SOURCE_GRID")
        if not -180 <= finite_number(self.longitude, "LONGITUDE") <= 180:
            raise ValueError("F1_NEX_LONGITUDE_OUTSIDE_SOURCE_GRID")
        if (self.model, self.member) != ("CanESM5", "r1i1p1f1") or self.scenario not in SCENARIOS:
            raise ValueError("F1_MODEL_MEMBER_SCENARIO_NOT_ADMITTED")
        for window in (self.reference_window, self.future_window):
            if (len(window) != 2 or any(type(y) is not int for y in window)
                    or not 10 <= window[1]-window[0]+1 <= 30):
                raise ValueError("F1_REFERENCE_AND_FUTURE_REQUIRE_10_TO_30_COMPLETE_YEARS")
        if not 1950 <= self.reference_window[0] <= self.reference_window[1] <= 2025:
            raise ValueError("F1_REFERENCE_WINDOW_OUTSIDE_ADMITTED_PERIOD")
        if not max(2015, self.reference_window[1]+1) <= self.future_window[0] <= self.future_window[1] <= 2100:
            raise ValueError("F1_FUTURE_MUST_FOLLOW_REFERENCE_AND_BE_WITHIN_2100")

    def to_dict(self):
        return json.loads(json.dumps(asdict(self)))

    @property
    def jobs(self):
        years = range(self.reference_window[0], self.reference_window[1]+1)
        future = range(self.future_window[0], self.future_window[1]+1)
        return [("historical" if y <= 2014 else self.scenario, y, var)
                for y in (*years, *future) for var in SPECS]


def _text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def catalog_url(request, scenario, variable):
    return f"{ROOT}/catalog/AMES/NEX/GDDP-CMIP6/{request.model}/{scenario}/{request.member}/{variable}/catalog.xml"


def catalog_path(raw, request, scenario, year, variable):
    name = f"{variable}_day_{request.model}_{scenario}_{request.member}_gn_{year}_v2.0.nc"
    expected = f"AMES/NEX/GDDP-CMIP6/{request.model}/{scenario}/{request.member}/{variable}/{name}"
    nodes = [node for node in ET.fromstring(raw).iter() if node.tag.endswith("dataset") and node.attrib.get("name") == name]
    if len(nodes) != 1 or nodes[0].attrib.get("urlPath") != expected:
        raise ValueError(f"F1_NASA_V2_SOURCE_NOT_FOUND_{scenario}_{year}_{variable}")
    return expected


def subset_url(request, path, year, variable):
    return f"{ROOT}/ncss/grid/{path}?"+urlencode({"var": variable, "latitude": f"{request.latitude:.6f}",
        "longitude": f"{request.longitude:.6f}", "time_start": f"{year}-01-01T00:00:00Z",
        "time_end": f"{year}-12-31T23:59:59Z", "accept": "netcdf3", "addLatLon": "true"})


def download(url):
    errors = []
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "IGE-F1-source-admission"}), timeout=45) as response:
                body = response.read(2*1024**2+1)
                if response.status != 200 or not body or len(body) > 2*1024**2:
                    raise ValueError("F1_SOURCE_RESPONSE_SIZE_OR_STATUS")
                return body
        except Exception as exc:
            errors.append(type(exc).__name__+": "+str(exc))
            if attempt < 2: time.sleep(1+attempt)
    raise RuntimeError("F1_SOURCE_UNAVAILABLE "+url+" "+str(errors))


def _noleap_serial(year, month=1, day=1):
    return 365*year+sum((31,28,31,30,31,30,31,31,30,31,30,31)[:month-1])+day-1


def decode_point(raw, variable, year, request):
    from scipy.io import netcdf_file
    if not raw.startswith((b"CDF\x01", b"CDF\x02")): raise ValueError("F1_NASA_POINT_NOT_NETCDF3")
    with netcdf_file(io.BytesIO(raw), mmap=False) as dataset:
        if _text(dataset._attributes.get("featureType", "")) != "timeSeries":
            raise ValueError("F1_NCSS_POINT_REPRESENTATION_CHANGED")
        required = {variable, "time", "latitude", "longitude", "stationIndex"}
        if not required <= set(dataset.variables): raise ValueError("F1_NCSS_POINT_VARIABLES_MISSING")
        f, t = dataset.variables[variable], dataset.variables["time"]
        if f.dimensions != ("obs",) or t.dimensions != ("obs",) or f.shape != (365,) or t.shape != (365,):
            raise ValueError("F1_NASA_POINT_DIMENSIONS_OR_DAILY_CENSUS")
        units = _text(f._attributes.get("units", ""))
        accepted = {SPECS[variable][0]}
        if variable == "huss": accepted |= {"kg kg-1", "kg/kg"}
        if units not in accepted: raise ValueError("F1_NASA_UNIT_CHANGED_"+variable)
        cal = _text(t._attributes.get("calendar", ""))
        if cal not in ("noleap", "365_day"): raise ValueError("F1_CANESM5_CALENDAR_CHANGED")
        match = re.fullmatch(r"[Dd]ays? since (\d{4})-(\d{2})-(\d{2})(?:T00:00:00Z| 00:00:00)?", _text(t._attributes.get("units", "")))
        if not match: raise ValueError("F1_CF_TIME_UNITS_NOT_ADMITTED")
        origin = tuple(map(int, match.groups()))
        axis = np.asarray(t[:], float).copy()
        expected = np.arange(365)+_noleap_serial(year)-_noleap_serial(*origin)+.5
        if not np.allclose(axis, expected, rtol=0, atol=1e-8):
            raise ValueError("F1_MISSING_DUPLICATE_REORDERED_OR_WRONG_CF_DAY")
        latitude = np.asarray(dataset.variables["latitude"][:], float).reshape(-1)
        longitude = np.asarray(dataset.variables["longitude"][:], float).reshape(-1)
        if latitude.shape != (1,) or longitude.shape != (1,) or np.any(dataset.variables["stationIndex"][:] != 0):
            raise ValueError("F1_SOURCE_NOT_SINGLE_POINT")
        lat, lon = float(latitude[0]), float(longitude[0]); lon = (lon+180)%360-180
        if (not np.isfinite([lat, lon]).all() or abs(lat-request.latitude) > .125001
                or abs((lon-request.longitude+180)%360-180) > .125001
                or abs((lat-.125)/.25-round((lat-.125)/.25)) > 1e-6
                or abs((lon-.125)/.25-round((lon-.125)/.25)) > 1e-6):
            raise ValueError("F1_SOURCE_NOT_NEAREST_NEX_GRID_CENTER")
        values = np.asarray(f[:], float).copy()
        for key in ("_FillValue", "missing_value"):
            if key in f._attributes: values[values == f._attributes[key]] = np.nan
        values = values*float(f._attributes.get("scale_factor", 1.))+float(f._attributes.get("add_offset", 0.))
    if (not np.isfinite(values).all() or np.any(values < SPECS[variable][1]) or np.any(values > SPECS[variable][2])
            or (variable == "huss" and np.any(values >= 1))):
        raise ValueError("F1_NASA_NONFINITE_OR_PHYSICAL_DOMAIN_"+variable)
    months = np.repeat(np.arange(1,13), (31,28,31,30,31,30,31,31,30,31,30,31))
    return values, months, {"grid": [lat, lon], "calendar": "noleap", "unit": units,
        "state_labels": "12:00 UTC nominal daily labels", "native_time_bounds_in_subset": False,
        "NCSS_stationAltitude_zero_is_not_orography": True}


def acquire_nex(request, *, checkpoint=None, progress=lambda message: None, fetch=download):
    """At most four workers; failed acquisitions keep optional local checkpoints."""
    from ..geosphere_station_year import _zip
    pairs = sorted({(scenario, var) for scenario, year, var in request.jobs})
    files, catalogs, receipts = {}, {}, []
    for scenario, var in pairs:
        progress(f"NASA source catalogue: {scenario} / {var}")
        url = catalog_url(request, scenario, var)
        body = fetch(url); name = f"catalog_{scenario}_{var}.xml"
        files[name] = body; catalogs[scenario, var] = body
        receipts.append({"file": name, "url": url, "sha256": sha256(body).hexdigest(), "bytes": len(body), "kind": "catalog"})
    def worker(job):
        scenario, year, var = job
        path = catalog_path(catalogs[scenario, var], request, scenario, year, var)
        url = subset_url(request, path, year, var)
        name = f"{scenario}_{year}_{var}.nc"
        if checkpoint is not None and (checkpoint/name).exists(): body = (checkpoint/name).read_bytes()
        else:
            body = fetch(url)
        _, _, metadata = decode_point(body, var, year, request)
        if checkpoint is not None: (checkpoint/name).write_bytes(body)
        return name, body, {"file": name, "url": url, "scenario": scenario, "year": year, "variable": var,
            "sha256": sha256(body).hexdigest(), "bytes": len(body), "kind": "subset", **metadata}
    if checkpoint is not None: checkpoint.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, job) for job in request.jobs]
        try:
            for i, future in enumerate(as_completed(futures), 1):
                name, body, receipt = future.result(); files[name] = body; receipts.append(receipt)
                if sum(len(b) for b in files.values()) > MAX_PACKET: raise ValueError("F1_NEX_PACKET_BUDGET")
                progress(f"NASA point source {i}/{len(futures)}: {name}")
        except Exception:
            for future in futures: future.cancel()
            raise
    files["manifest.json"] = json_bytes({"schema": SCHEMA, "request": request.to_dict(),
        "receipts": sorted(receipts, key=lambda row: row["file"]), "captured_at_utc": datetime.now(timezone.utc).isoformat()})
    return _zip(files)


def admit_nex_packet(packet, expected_sha256, request):
    if not expected_sha256 or sha256(packet).hexdigest() != expected_sha256 or len(packet) > MAX_PACKET:
        raise ValueError("F1_NEX_PACKET_HASH_OR_SIZE")
    files = bounded_zip(packet, byte_limit=MAX_PACKET, member_limit=640)
    manifest = json.loads(files["manifest.json"])
    if manifest.get("schema") != SCHEMA or manifest.get("request") != request.to_dict():
        raise ValueError("F1_NEX_PACKET_LOCATION_OR_REQUEST_MISMATCH")
    receipts = manifest["receipts"]
    by_name = {row["file"]: row for row in receipts}
    if len(by_name) != len(receipts) or set(files) != set(by_name) | {"manifest.json"}:
        raise ValueError("F1_NEX_RESPONSE_CENSUS")
    for name, row in by_name.items():
        if row["bytes"] != len(files[name]) or row["sha256"] != sha256(files[name]).hexdigest():
            raise ValueError("F1_NEX_ORIGINAL_RESPONSE_CHANGED")
    frames, metadata, grids = {}, [], set()
    for scenario, year, var in request.jobs:
        catalog = f"catalog_{scenario}_{var}.xml"
        if by_name[catalog]["url"] != catalog_url(request, scenario, var): raise ValueError("F1_NEX_CATALOG_IDENTITY")
        path = catalog_path(files[catalog], request, scenario, year, var)
        name = f"{scenario}_{year}_{var}.nc"; row = by_name[name]
        if (row.get("scenario"), row.get("year"), row.get("variable"), row["url"]) != (scenario, year, var, subset_url(request, path, year, var)):
            raise ValueError("F1_NEX_SUBSET_IDENTITY")
        values, months, proof = decode_point(files[name], var, year, request)
        grids.add(tuple(proof["grid"])); metadata.append(proof)
        frame = frames.setdefault((scenario, year), pd.DataFrame({"year": year, "month": months, "day_index": np.arange(365)}))
        frame[var] = values
    if len(grids) != 1: raise ValueError("F1_MIXED_NEX_GRID_CELLS")
    expected_names = {f"{s}_{y}_{v}.nc" for s,y,v in request.jobs} | {f"catalog_{s}_{v}.xml" for s,y,v in request.jobs}
    if set(by_name) != expected_names: raise ValueError("F1_UNEXPECTED_NEX_RESPONSE")
    for frame in frames.values():
        if np.any(frame.tasmin > frame.tasmax) or np.max(np.abs(frame.tas-(frame.tasmin+frame.tasmax)/2)) > 5e-5:
            raise ValueError("F1_TAS_OPERATOR_NOT_VERIFIED_MIDRANGE")
        frame["c"] = frame.tas-273.15; frame["dtr"] = frame.tasmax-frame.tasmin
    reference = pd.concat([f for (s,y),f in frames.items() if request.reference_window[0] <= y <= request.reference_window[1]])
    future = pd.concat([f for (s,y),f in frames.items() if request.future_window[0] <= y <= request.future_window[1]])
    evidence = {"source_packet_sha256": expected_sha256, "request": request.to_dict(), "grid": list(next(iter(grids))),
        "reference_daily_rows": len(reference), "future_daily_rows": len(future), "original_responses": len(receipts),
        "temperature_operator": "VERIFIED_TAS_EQUALS_DAILY_MIN_MAX_MIDRANGE_NOT_HOURLY_MEAN",
        "q_operator": "DAILY_SPECIFIC_HUMIDITY_TIME_MEAN_KG_PER_KG_MOIST_AIR",
        "hurs_phase": "NOT_CONFIRMED_BY_POINT_SUBSET; SOURCE_PERCENT_CHANGE_DIAGNOSTIC_ONLY",
        "reference_model_branch": "historical through 2014; selected SSP from 2015 if needed",
        "daily_time_bounds_verified": False, "hourly_NASA_daily_equalities_claimed": False,
        "monthly_operator": "UTC daily seasonal signals transferred to fixed-local-standard monthly pattern"}
    return monthly_nex_signals(reference, future), evidence
