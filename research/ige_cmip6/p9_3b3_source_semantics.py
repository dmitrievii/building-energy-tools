"""Versioned operators and source sidecars. Never rewrites historical CSVs."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
from pathlib import Path
import urllib.request

REGISTERED_CSV_SHA = "77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef"
OPERATORS = ("DERIVED_TAS_MIDRANGE", "TIME_MEAN_TAS")


@dataclass(frozen=True)
class SourceSemantics:
    temperature_operator: str
    rh_phase: str
    calendar: str = "noleap"
    time_support: str = "NATIVE_AVERAGING_BOUNDS_NOT_VERIFIED_UTC_DAY_ASSUMED"
    verified: bool = False
    source: str = "NEX_GDDP_CMIP6_V2_CANESM5"

    def __post_init__(self):
        if self.temperature_operator not in OPERATORS:
            raise ValueError("P93B3_UNKNOWN_TEMPERATURE_OPERATOR")
        if self.rh_phase not in ("WATER", "ICE", "WATER_ICE", "UNKNOWN"):
            raise ValueError("P93B3_UNKNOWN_RH_PHASE")
        if self.calendar not in ("noleap", "365_day", "standard", "gregorian", "proleptic_gregorian"):
            raise ValueError("P93B3_UNSUPPORTED_CALENDAR")
        if self.verified and (self.rh_phase == "UNKNOWN" or "ASSUMED" in self.time_support):
            raise ValueError("P93B3_CANNOT_VERIFY_UNKNOWN_SOURCE_SEMANTICS")


@dataclass(frozen=True)
class DailyTarget:
    date: str
    Tmin_K: float
    Tmax_K: float
    tas_K: float
    q_mean_kgkg: float
    RH_mean_pct: float
    semantics: SourceSemantics

    def __post_init__(self):
        day = dt.date.fromisoformat(self.date)
        vals = (self.Tmin_K, self.Tmax_K, self.tas_K, self.q_mean_kgkg, self.RH_mean_pct)
        if not all(math.isfinite(v) for v in vals):
            raise ValueError("P93B3_NONFINITE_DAILY_TARGET")
        if not 173 < self.Tmin_K <= self.tas_K <= self.Tmax_K < 332:
            raise ValueError("P93B3_DAILY_TEMPERATURE_DOMAIN")
        if not 0 <= self.q_mean_kgkg < .1 or not 0 <= self.RH_mean_pct <= 105:
            raise ValueError("P93B3_DAILY_HUMIDITY_DOMAIN")
        if self.semantics.calendar in ("noleap", "365_day") and (day.month, day.day) == (2, 29):
            raise ValueError("P93B3_LEAP_DATE_IN_NOLEAP_SOURCE")
        if self.semantics.temperature_operator == "DERIVED_TAS_MIDRANGE" and abs(
                self.tas_K - (self.Tmin_K + self.Tmax_K) / 2) > 5e-5:
            raise ValueError("P93B3_DERIVED_TAS_MIDRANGE_INCONSISTENT")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, row):
        d = dict(row)
        d["semantics"] = SourceSemantics(**d["semantics"])
        return cls(**d)


def parse_das(text):
    """Retain native string metadata and absence of bounds, without inference."""
    blocks = {}
    for match in re.finditer(r"(?m)^\s*(\w+)\s*\{([^{}]*)\}", text):
        blocks[match[1]] = dict(re.findall(r'String\s+(\w+)\s+"([^"\n]*)"\s*;', match[2]))
    if "NC_GLOBAL" not in blocks or "time" not in blocks:
        raise ValueError("P93B3_NOT_A_SOURCE_DAS_HEADER")
    return {"blocks": blocks, "time_bounds_declared": "bounds" in blocks["time"],
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


def fetch_metadata(variable, year=2013, attempts=2):
    if variable not in ("tas", "tasmin", "tasmax", "hurs", "huss") or year not in (2013, 2014):
        raise ValueError("P93B3_METADATA_REQUEST_OUTSIDE_REGISTERED_SOURCE")
    url = ("https://ds.nccs.nasa.gov/thredds/dodsC/AMES/NEX/GDDP-CMIP6/CanESM5/"
           f"historical/r1i1p1f1/{variable}/{variable}_day_CanESM5_historical_r1i1p1f1_gn_{year}_v2.0.nc.das")
    errors = []
    for _ in range(min(2, attempts)):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                raw = response.read(200001)
            if len(raw) > 200000:
                raise ValueError("P93B3_METADATA_TOO_LARGE")
            parsed = parse_das(raw.decode())
            g = parsed["blocks"]["NC_GLOBAL"]
            expected = {"cmip6_source_id": "CanESM5", "variant_label": "r1i1p1f1",
                        "scenario": "historical", "version": "2.0"}
            if any(g.get(k) != v for k, v in expected.items()):
                raise ValueError("P93B3_METADATA_SOURCE_IDENTITY_MISMATCH")
            return {"status": "SOURCE_METADATA_READ", "variable": variable, "year":year, "url": url, **parsed}
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    return {"status": "SOURCE_METADATA_BLOCKED", "variable": variable, "year":year, "url": url, "errors": errors}


def audit_csv(path, expected_sha=REGISTERED_CSV_SHA):
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != expected_sha:
        raise ValueError("P93B3_REGISTERED_SOURCE_CSV_SHA_MISMATCH")
    rows = [r for r in csv.DictReader(io.StringIO(raw.decode())) if r["date"][:4] in ("2013", "2014")]
    if len(rows) != 730 or len({r["date"] for r in rows}) != 730:
        raise ValueError("P93B3_REGRESSION_SOURCE_730_DAYS_REQUIRED")
    return {"csv_sha256": sha, "n_regression_days": len(rows),
            "max_abs_tas_minus_midrange_K": max(abs(float(r["tas"]) - (
                float(r["tasmin"]) + float(r["tasmax"]))/2) for r in rows),
            "temporal_mean_not_observed_from_derived_tas": True,
            "original_values_modified": False}
