from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import sys
import time
import uuid

UTC = dt.timezone.utc
HOUR = dt.timedelta(hours=1)
SCHEMAS = {"IGE_AT_DOWNLOAD_PLAN_v1": "AT", "ige-dwd-plan-v1": "DE", "IGE_CH_PLAN_v1": "CH"}


class InputError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def now():
    return dt.datetime.now(UTC).isoformat()


def stamp(value):
    value = str(value)
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise InputError("Ambiguous timestamp without time zone: " + value)
    return result.astimezone(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(message):
    print(message, flush=True)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_config_json(path):
    """Keep JSON strict and explain Windows path escapes before any run writes."""
    path = Path(path)
    hint = ('In JSON paths use /, for example "database": "../Database" or '
            '"database": "E:/User Folder/Climate/Database". '
            'A Windows backslash must be doubled as \\\\. '
            'Keep a comma between fields.')
    try:
        config = read_json(path)
    except json.JSONDecodeError as exc:
        raise InputError(
            f"Invalid JSON configuration: {path}; line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}. {hint}") from exc
    if not isinstance(config, dict):
        raise InputError("Configuration must be a JSON object: " + str(path))
    for key in ("database", "results"):
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise InputError(f"Configuration {path}: {key} must be a nonempty path string")
        if any(ord(char) < 32 for char in value):
            raise InputError(f"Configuration {path}: {key} contains a control character, "
                             f"possibly decoded from a Windows path escape. {hint}")
    return config


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def safe_join(root, relative):
    root = Path(root).resolve()
    relative = str(relative)
    win = PureWindowsPath(relative)
    p = Path(relative)
    if p.is_absolute() or win.is_absolute() or win.drive or ".." in p.parts or ".." in win.parts:
        raise InputError("Unsafe relative source path: " + relative)
    result = (root / p).resolve()
    if not result.is_relative_to(root):
        raise InputError("Source path escapes run directory: " + relative)
    return result


def fingerprint(path):
    s = Path(path).stat()
    return [s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_dev, s.st_ino]


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


class HashCache:
    """Cached digests are explicitly distinguished from a fresh full rehash."""

    def __init__(self, path, force=False):
        self.force = force
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("CREATE TABLE IF NOT EXISTS hashes (path TEXT PRIMARY KEY, stat TEXT, sha TEXT)")
        self.fresh = self.cached = self.bytes_read = 0

    def verify(self, path, expected):
        path = Path(path).resolve()
        before = fingerprint(path)
        key = json.dumps(before)
        old = self.db.execute("SELECT stat,sha FROM hashes WHERE path=?", (str(path),)).fetchone()
        if not self.force and old and old[0] == key and old[1] == expected:
            self.cached += 1
            return {"path": str(path), "sha256": expected, "fingerprint": before,
                    "verification": "CACHED_HASH_UNCHANGED_STAT"}
        result = hashlib.sha256()
        start = last = time.monotonic()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                result.update(chunk)
                self.bytes_read += len(chunk)
                if time.monotonic() - last >= 5:
                    log("  hashing " + path.name + " (" + str(round(time.monotonic() - start)) + " s)")
                    last = time.monotonic()
        if before != fingerprint(path):
            raise InputError("File changed during verification: " + str(path))
        actual = result.hexdigest()
        if actual != expected:
            raise InputError("SHA256 mismatch: " + str(path))
        self.fresh += 1
        self.db.execute("INSERT OR REPLACE INTO hashes VALUES(?,?,?)", (str(path), key, actual))
        self.db.commit()
        return {"path": str(path), "sha256": actual, "fingerprint": before,
                "verification": "FRESH_FULL_SHA256"}

    def close(self):
        self.db.close()


def number(value):
    if value is None or str(value).strip() in ("", "-999", "-999.0", "-9999", "-9999.0", "null", "None"):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    x = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, x))))


def peak_rss_bytes():
    try:
        if os.name != "nt":
            import resource
            v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(v if sys.platform == "darwin" else v * 1024)
        import ctypes
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        m = Memory(); m.cb = ctypes.sizeof(m)
        return int(m.PeakWorkingSetSize) if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(m), m.cb) else None
    except (ImportError, OSError, AttributeError):
        return None


def load_config(path):
    path = Path(path).resolve()
    cfg = read_config_json(path)
    allowed = {"schema", "database", "results", "countries", "windows", "variables", "targets", "max_targets_per_country",
               "candidate_count", "radius_km", "max_height_difference_m", "co_location_exclusion_km", "idw_max_donors",
               "idw_min_donors", "distance_floor_km", "temperature_lapse_K_per_m", "qc_modes", "rejected_native_qc",
               "benchmark_workers", "job_wall_budget_s", "worker_rss_budget_bytes", "role"}
    if set(cfg) - allowed or cfg.get("schema") != "IGE_E0_E10_CONFIG_v1":
        raise InputError("Unknown configuration key/schema")
    for key in ("database", "results"):
        cfg[key] = str((path.parent / cfg[key]).resolve())
    database, results = Path(cfg["database"]), Path(cfg["results"])
    if results.is_relative_to(database) or database.is_relative_to(results):
        raise InputError("Database and results must have disjoint directories")
    if not database.is_dir():
        raise InputError("Database directory not found: " + str(database))
    if cfg.get("role") != "D_DEVELOPMENT":
        raise InputError("This engineering pilot is development only; it cannot open a confirmatory holdout")
    if not cfg.get("countries") or not set(cfg["countries"]) <= {"AT", "DE", "CH"}:
        raise InputError("Invalid countries")
    if not cfg.get("variables") or not set(cfg["variables"]) <= {"T", "RH", "p"}:
        raise InputError("Pilot supports only native T, RH and station p")
    if not cfg.get("windows"):
        raise InputError("At least one explicit half-open UTC window is required")
    windows = sorted((stamp(w["start"]), stamp(w["end_exclusive"])) for w in cfg["windows"])
    for i, (lo, hi) in enumerate(windows):
        if lo >= hi or any(t.minute or t.second or t.microsecond for t in (lo, hi)):
            raise InputError("Windows must be nonempty full-hour UTC intervals")
        if i and windows[i-1][1] > lo:
            raise InputError("Overlapping pilot windows")
    if sum(int((b-a)/HOUR) for a,b in windows) > 10000:
        raise InputError("This is a small pilot: at most 10000 hourly positions per target")
    positive = ["max_targets_per_country", "candidate_count", "idw_max_donors", "idw_min_donors"]
    if any(type(cfg.get(k)) is not int or cfg[k] < 1 for k in positive):
        raise InputError("Invalid positive integer limits")
    if cfg["idw_min_donors"] > cfg["idw_max_donors"] or cfg["candidate_count"] < cfg["idw_max_donors"]:
        raise InputError("Inconsistent donor limits")
    for key in ("radius_km", "distance_floor_km", "job_wall_budget_s", "worker_rss_budget_bytes"):
        if number(cfg.get(key)) is None or cfg[key] <= 0:
            raise InputError("Invalid positive limit: " + key)
    for key in ("max_height_difference_m", "co_location_exclusion_km", "temperature_lapse_K_per_m"):
        if number(cfg.get(key)) is None or cfg[key] < 0:
            raise InputError("Invalid nonnegative parameter: " + key)
    if not cfg.get("qc_modes") or not set(cfg["qc_modes"]) <= {"primary", "sensitivity_all_published"}:
        raise InputError("Invalid QC modes")
    if not cfg.get("benchmark_workers") or any(type(n) is not int or not 1 <= n <= 8 for n in cfg["benchmark_workers"]):
        raise InputError("benchmark_workers must contain integers 1..8")
    for key in ("countries", "variables", "qc_modes", "benchmark_workers"):
        if len(cfg[key]) != len(set(cfg[key])):
            raise InputError("Duplicate configuration entries: " + key)
    if not isinstance(cfg.get("rejected_native_qc"), dict) or any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in cfg["rejected_native_qc"].values()):
        raise InputError("rejected_native_qc must contain lists of exact native strings")
    cfg["config_source_path"] = str(path)
    return cfg


def new_run(results):
    root = Path(results) / (dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ") + "_" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    return root
