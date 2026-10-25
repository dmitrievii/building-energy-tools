"""Admit the frozen CanESM5 pilot source; never infer support for all GCMs.

Original P6 derived daily CSVs, their provider URLs and QA are retained. Raw
upstream NetCDF payloads are not contained in this portable selection.
"""
from __future__ import annotations
import calendar
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile
import numpy as np
import pandas as pd

from .contracts import FutureRequest

NEX_PACKET_SHA = "49dab390ec5d5250f79198df16e69cc3ba37a9985b66f739fde5a729db3c192d"
REFERENCE_PACKET_SHA = "68f19f8e02fb00d178009ab6dbe2f4dc441f879bc870b71a98d797b05ecd1403"
SEMANTICS_VERSION = "IGE_BM1_CANESM5_V2_MIDRANGE_MONTHLY_v1"
VARIABLE_UNITS = {"tas": "K", "tasmax": "K", "tasmin": "K", "hurs": "%", "huss": "1",
    "pr": "kg m-2 s-1", "rsds": "W m-2", "rlds": "W m-2", "sfcWind": "m s-1"}
ARCHIVES = {
    "historical-1995-2014": ("5490003b68cbdf0fa5394a45f8491232d2e39e25ac230f83d4e3aa8632f7496d",
        "77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef", 1995, 2014, "historical"),
    "ssp245-2040-2059": ("cb9fcfa5144fc1a8d86ee057f79a3b2883ef7de2704c4881aa82dafb269819a1",
        "5cdc6bad425127a8d7a232a2cfd1c649306821f1e0ea8376b90839a8472d97b3", 2040, 2059, "ssp245"),
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def bounded_zip(raw: bytes, *, byte_limit=32*1024**2, member_limit=40) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > member_limit or sum(i.file_size for i in infos) > byte_limit:
            raise ValueError("BM1_ARCHIVE_BUDGET")
        names = set()
        for i in infos:
            p = PurePosixPath(i.filename)
            if (p.is_absolute() or ".." in p.parts or "\\" in i.filename or p.as_posix() != i.filename
                    or i.is_dir() or i.filename in names or (i.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("BM1_ARCHIVE_UNSAFE_OR_DUPLICATE_MEMBER")
            names.add(i.filename)
        return {i.filename: archive.read(i) for i in infos}


def read_pinned(path: Path, expected_sha: str) -> bytes:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 16*1024**2:
        raise ValueError("BM1_SOURCE_PACKET_MISSING_OR_TOO_LARGE")
    raw = path.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError("BM1_SOURCE_PACKET_SHA_CHANGED")
    return raw


def admit_nex(path: Path, request: FutureRequest) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if (request.model, request.member, request.scenario, request.historical_window, request.future_window,
            request.semantics_version, request.method) != ("CanESM5", "r1i1p1f1", "ssp245", (2002, 2014),
            (2040, 2059), SEMANTICS_VERSION, "monthly_morph"):
        raise ValueError("BM1_UNREGISTERED_MODEL_MEMBER_WINDOWS_OR_SEMANTICS")
    packet = bounded_zip(read_pinned(path, NEX_PACKET_SHA))
    result, evidence = {}, {}
    for window, (archive_sha, csv_sha, first, last, scenario) in ARCHIVES.items():
        name = "model_window_sources/IGE_FREEZE_NEX_CanESM5-" + window + ".zip"
        body = packet[name]
        if sha(body) != archive_sha:
            raise ValueError("BM1_NEX_NESTED_ARCHIVE_CHANGED")
        files = bounded_zip(body)
        qa, provenance = json.loads(files["quality_report.json"]), json.loads(files["source_provenance.json"])
        for proof in (qa, provenance):
            if any(proof.get(k) != v for k, v in {"status": "PASS", "model": "CanESM5", "member": "r1i1p1f1", "window": window}.items()):
                raise ValueError("BM1_NEX_IDENTITY_CHANGED")
            for file, digest in proof["csv_sha256"].items():
                if sha(files[file]) != digest:
                    raise ValueError("BM1_NEX_DERIVED_CSV_CHANGED")
        if qa["calendar"] not in ("noleap", "365_day") or qa["days"] != 7300 or qa["grid"] != [46.875, 15.375]:
            raise ValueError("BM1_NEX_GRID_CALENDAR_OR_CENSUS_CHANGED")
        original = provenance["subset_provenance"]
        if len(original) != 180:
            raise ValueError("BM1_NEX_RAW_SUBSET_CENSUS_CHANGED")
        for row in original:
            if (row["units"] != VARIABLE_UNITS[row["variable"]] or row["lat"] != 46.875 or row["lon"] != 15.375
                    or row["model"] != "CanESM5" or row["member"] != "r1i1p1f1" or row["scenario"] != scenario):
                raise ValueError("BM1_NEX_SOURCE_UNITS_OR_CHAIN_CHANGED")
        if sha(files["joint_daily_raw.csv"]) != csv_sha:
            raise ValueError("BM1_NEX_REGISTERED_CSV_HASH_CHANGED")
        rows = list(csv.DictReader(io.StringIO(files["joint_daily_raw.csv"].decode())))
        expected = [date(y, m, d).isoformat() for y in range(first, last+1) for m in range(1, 13)
            for d in range(1, (28 if m == 2 else calendar.monthrange(y, m)[1])+1)]
        if [r["date"] for r in rows] != expected or any(r["model"] != request.model or r["member"] != request.member or r["scenario"] != scenario for r in rows):
            raise ValueError("BM1_NEX_MISSING_DUPLICATE_REORDERED_OR_WRONG_DAY")
        frame = pd.DataFrame([{k: float(r[k]) for k in (*VARIABLE_UNITS, "year", "month", "day")} for r in rows])
        if not np.isfinite(frame.to_numpy()).all():
            raise ValueError("BM1_NEX_NONFINITE_DAILY_DATA")
        residual = np.abs(frame.tas - (frame.tasmin + frame.tasmax)/2)
        if residual.max() > 5e-5 or (frame.tasmin > frame.tasmax).any():
            raise ValueError("BM1_NEX_TAS_NOT_VERIFIED_MIDRANGE")
        if ((frame.hurs < 0) | (frame.hurs > 105) | (frame.huss < 0) | (frame.huss >= 1)).any() or (frame[["pr", "rsds", "rlds", "sfcWind"]] < 0).any().any():
            raise ValueError("BM1_NEX_DAILY_PHYSICAL_DOMAIN")
        frame["c"] = frame.tas - 273.15
        frame["dtr"] = frame.tasmax - frame.tasmin
        result[scenario] = frame
        evidence[scenario] = {"archive_window": window, "archive_sha256": archive_sha, "daily_csv_sha256": csv_sha,
            "archive_days_checked": len(frame), "max_tas_midrange_residual_K": float(residual.max()), "grid": qa["grid"]}
    historical = result["historical"]
    historical = historical[(historical.year >= 2002) & (historical.year <= 2014)].copy()
    assert len(historical) == 13*365
    evidence.update({"selected_historical_window": [2002, 2014], "selected_historical_days": len(historical),
        "daily_temperature_operator": "MIDRANGE_NOT_24H_TIME_MEAN",
        "huss_operator": "DAILY_TIME_MEAN_SPECIFIC_HUMIDITY", "hurs_operator": "DAILY_TIME_MEAN_WATER_ICE_RH",
        "raw_NetCDF_payloads_in_packet": False, "daily_bounds_verified": False,
        "time_support_policy": "24_UNIFORM_UTC_STATE_NODES_APPROXIMATION; MONTHLY_SEASONAL_TRANSFER_TO_FIXED_STANDARD_INTERVALS",
        "fully_verified_NASA_time_bounds": False})
    return historical, result["ssp245"], evidence


def monthly_nex_signals(historical: pd.DataFrame, future: pd.DataFrame) -> dict:
    signals = {}
    for m in range(1, 13):
        h, f = historical[historical.month == m], future[future.month == m]
        if not len(h) or not len(f):
            raise ValueError("BM1_EMPTY_MODEL_MONTH")
        row = {"midrange_delta_K": float(f.c.mean()-h.c.mean()),
            "historical_midrange_sorted_c": sorted(h.c.tolist()), "future_midrange_sorted_c": sorted(f.c.tolist()),
            "NASA_hurs_delta_pp_DIAGNOSTIC_NOT_ENFORCED": float(f.hurs.mean()-h.hurs.mean())}
        for key in ("dtr", "huss", "pr", "rsds", "rlds", "sfcWind"):
            denominator = float(h[key].mean())
            if denominator <= 0:
                raise ValueError("BM1_ZERO_REFERENCE_MODEL_MEAN_REQUIRES_SEPARATE_METHOD_" + key)
            row[key + "_ratio"] = float(f[key].mean()) / denominator
        signals[m] = row
    return signals
