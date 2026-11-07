"""E0: snapshot completed native downloader jobs. Never writes in Database."""
from __future__ import annotations

import collections
import csv
import gzip
import os
from pathlib import Path
import re
import time

from .common import (SCHEMAS, HOUR, HashCache, InputError, digest, fingerprint, iso,
                     log, now, number, read_json, safe_join, stamp, write_csv, write_json)


def discover(database, countries):
    found, notes = [], []
    for country in countries:
        base = Path(database) / country
        if not base.is_dir():
            notes.append({"country": country, "reason": "COUNTRY_DIRECTORY_MISSING", "path": str(base)})
            continue
        for directory, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in {"raw", "parts", "csv", "stations", "catalog", "__pycache__"}
                             and not (Path(directory) / d).is_symlink())
            if "plan.json" not in files:
                continue
            path = Path(directory) / "plan.json"
            try:
                p = read_json(path)
                if p.get("schema") not in SCHEMAS:
                    continue
                # A top-level planning copy is not a second downloaded run.
                if not (path.parent / "receipts").is_dir() and path.parent.name != str(p.get("plan_id", ""))[:20]:
                    notes.append({"country": country, "reason": "PLAN_WITHOUT_DOWNLOAD_RUN", "path": str(path)})
                    continue
                found.append((country, path))
            except (OSError, ValueError) as exc:
                notes.append({"country": country, "reason": "UNREADABLE_PLAN", "path": str(path), "error": str(exc)})
    return sorted(found, key=lambda x: (x[0], str(x[1]))), notes


def plan_bounds(country, p):
    return (stamp(p["start"]), stamp(p["end"]) + HOUR) if country == "AT" else (
        stamp(p["start_utc_inclusive"]), stamp(p["end_utc_exclusive"]))


def validate_plan(p, country):
    if SCHEMAS.get(p.get("schema")) != country:
        raise InputError("Plan country/schema disagrees with Database subdirectory")
    if p.get("plan_id") != digest({k: v for k, v in p.items() if k != "plan_id"}):
        raise InputError("Plan hash mismatch")
    ids = [j["job_id"] for j in p["jobs"]]
    if len(ids) != len(set(ids)) or any(not re.fullmatch("[0-9a-f]{24}", x) for x in ids):
        raise InputError("Invalid or duplicate job identities")
    for j in p["jobs"]:
        if j["job_id"] != digest({k: v for k, v in j.items() if k != "job_id"})[:24]:
            raise InputError("Job hash mismatch")
    if country == "AT" and digest(p["metadata_original_utf8"].encode("utf-8")) != p["metadata_sha256"]:
        raise InputError("AT metadata body hash mismatch")
    if plan_bounds(country, p)[0] >= plan_bounds(country, p)[1]:
        raise InputError("Reversed or empty plan period")


def stations_for(country, p):
    import json
    source = json.loads(p["metadata_original_utf8"])["stations"] if country == "AT" else p["stations"]
    result = []
    for s in source:
        sid = str(s["id"] if country == "AT" else s["station_id"])
        network = "" if country != "CH" else s["network"]
        key = country + ":" + (network + ":" if network else "") + sid
        group = s.get("group_id")
        family = "AT:group:" + str(group) if country == "AT" and group is not None else (
            "CH:wigos:" + s["wigos_id"] if country == "CH" and s.get("wigos_id") else country + ":site:" + sid)
        result.append({"key": key, "country": country, "station_id": sid, "network": network,
                       "name": s.get("name", ""), "family": family,
                       "lat": number(s.get("lat") if country == "AT" else s.get("latitude_deg")),
                       "lon": number(s.get("lon") if country == "AT" else s.get("longitude_deg")),
                       "height_m": number(s.get("altitude") if country == "AT" else s.get("elevation_m")),
                       "station_type": s.get("type", "INDIVIDUAL"),
                       "geometry_role": "published_station_geometry_proxy_not_verified_sensor_history",
                       "valid_from": s.get("valid_from"), "valid_to": s.get("valid_to"),
                       "published_barometer_height_m": s.get("barometer_elevation_m"),
                       "native_metadata": s})
    return result


def expected_paths(country, job, receipt):
    j = job["job_id"]
    if country == "AT":
        sha = receipt["original_response_sha256"]
        if not re.fullmatch("[0-9a-f]{64}", sha):
            raise InputError("Invalid source digest")
        return {f"raw/{j}/{sha}.json.gz"} | {f"csv/{sid}/{job['start'][:4]}/{j}.csv.gz" for sid in job["station_ids"]}
    return {f"raw/{j}/{job['filename']}" + (".gz" if country == "CH" else ""),
            f"parts/{j}.csv.gz", f"metadata/{j}.json"}


def coverage_rows(country, run_id, job, receipt):
    base = {"country": country, "plan_id": run_id, "job_id": job["job_id"],
            "coverage_source": "native_downloader_receipt_not_recomputed_hourly_union"}
    if country == "AT":
        for sid, params in receipt.get("stations", {}).items():
            for name, c in params.items():
                yield base | {"station_id": sid, "group": "", "period": job["start"] + "/" + job["end"],
                              "parameter": name, "expected_labels": c.get("requested_hours"),
                              "non_null": c.get("non_null_hours"), "qc_or_regime": str(c.get("qc_counts_on_non_null", {}))}
    elif country == "DE":
        c = receipt.get("coverage", {})
        for name, v in c.get("variables", {}).items():
            yield base | {"station_id": job["station_id"], "group": job["group"], "period": "plan_window",
                          "parameter": name, "expected_labels": c.get("expected_hourly_utc_labels"),
                          "non_null": v.get("present_rows"), "qc_or_regime": str(v.get("qc_on_present", {}))}
    else:
        for year, c in receipt.get("coverage_by_year", {}).items():
            for name, v in c.get("parameters", {}).items():
                yield base | {"station_id": job["station_id"], "group": job["network"], "period": year,
                              "parameter": name, "expected_labels": c.get("expected_hourly_labels"),
                              "non_null": v.get("non_null_rows"), "qc_or_regime": str(c.get("hour_interval_regimes", {}))}


def audit(cfg, output, rehash=False):
    start = time.monotonic()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    paths, notes = discover(cfg["database"], cfg["countries"])
    cache = HashCache(Path(cfg["results"]) / "state" / "source_hashes.sqlite", force=rehash)
    jobs_ledger, coverage, snapshots, errors = [], [], [], []
    totals = {c: collections.Counter() for c in cfg["countries"]}
    try:
        for country, path in paths:
            p = read_json(path)
            try:
                validate_plan(p, country)
            except (InputError, ValueError, KeyError, TypeError) as exc:
                errors.append({"path": str(path), "country": country, "error": str(exc)})
                continue
            lo, hi = plan_bounds(country, p)
            item = {"country": country, "root": str(path.parent.resolve()), "plan_path": str(path.resolve()),
                    "plan_file_sha256": digest(path.read_bytes()), "plan_id": p["plan_id"],
                    "start": iso(lo), "end_exclusive": iso(hi), "stations": stations_for(country, p),
                    "jobs": [], "planned_jobs": len(p["jobs"]), "download_lock_observed": (path.parent / ".download.lock").exists()}
            if country == "AT":
                import json
                m = json.loads(p["metadata_original_utf8"])
                item["parameter_definitions"] = {x["name"]: x for x in m["parameters"]}
                item["native_code_lists"] = m.get("code_lists", {})
            else:
                item["parameter_definitions"] = p.get("parameter_definitions", {})
            log(f"E0 {country}: {len(p['jobs'])} planned jobs in {path.parent}")
            last = time.monotonic()
            for index, job in enumerate(p["jobs"], 1):
                total = totals[country]
                total["planned_jobs"] += 1
                receipt_path = path.parent / "receipts" / (job["job_id"] + ".json")
                row = {"country": country, "plan_id": p["plan_id"], "job_id": job["job_id"], "status": "PENDING", "error": ""}
                try:
                    if not receipt_path.is_file():
                        total["pending_jobs"] += 1
                    else:
                        receipt_bytes = receipt_path.read_bytes()
                        import json
                        r = json.loads(receipt_bytes)
                        if r.get("status") != "complete" or r.get("request_sha256" if country == "AT" else "job_sha256") != digest(job):
                            raise InputError("Receipt status/job binding mismatch")
                        expected = expected_paths(country, job, r)
                        assets = r["artifacts"]
                        if len(assets) != len(expected) or {a["path"] for a in assets} != expected:
                            raise InputError("Missing, duplicate or unexpected receipt artifacts")
                        verified = []
                        for a in assets:
                            sha = a.get("file_sha256") if country == "AT" else a.get("sha256")
                            if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha):
                                raise InputError("Invalid artifact SHA256")
                            asset = cache.verify(safe_join(path.parent, a["path"]), sha)
                            asset["relative"] = a["path"]
                            if a["path"].startswith(("parts/", "csv/")):
                                with gzip.open(asset["path"], "rt", encoding="utf-8-sig", newline="") as f:
                                    header = next(csv.reader(f), [])
                                if "timestamp_utc" not in header or len(header) != len(set(header)):
                                    raise InputError("Invalid native CSV header")
                                asset["columns"] = header
                            verified.append(asset)
                        if receipt_bytes != receipt_path.read_bytes():
                            raise InputError("Receipt changed during audit")
                        item["jobs"].append({"job": job, "artifacts": verified,
                                             "receipt_path": str(receipt_path.resolve()), "receipt_sha256": digest(receipt_bytes)})
                        row["status"] = "VERIFIED_COMPLETE"
                        total["verified_jobs"] += 1
                        coverage.extend(coverage_rows(country, p["plan_id"], job, r))
                except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
                    row["status"] = "QUARANTINED"
                    row["error"] = str(exc)
                    total["quarantined_jobs"] += 1
                jobs_ledger.append(row)
                if index == len(p["jobs"]) or index % 20 == 0 or time.monotonic() - last >= 5:
                    log(f"  {index}/{len(p['jobs'])}: verified={total['verified_jobs']}, pending={total['pending_jobs']}, quarantined={total['quarantined_jobs']}")
                    last = time.monotonic()
            if item["plan_file_sha256"] != digest(path.read_bytes()):
                errors.append({"path": str(path), "error": "Plan changed during audit; run snapshot rejected"})
            else:
                snapshots.append(item)
    finally:
        cache.close()
    snapshot = {"schema": "IGE_E0_SNAPSHOT_v1", "created_at_utc": now(), "database": cfg["database"],
                "snapshot_semantics": "Only complete jobs visible during this audit; later downloads excluded",
                "coverage_semantics": "Receipt summaries verified by artifact hashes; exact per-hour values scanned only for pilot subset",
                "geometry_semantics": "Published metadata retained; sensor geometry not promoted to historical verification",
                "config_sha256": digest(cfg), "runs": snapshots}
    snapshot["snapshot_id"] = digest(snapshot)
    write_json(output / "snapshot.json", snapshot)
    summary = {"schema": "IGE_E0_REPORT_v1", "snapshot_id": snapshot["snapshot_id"], "created_at_utc": now(),
               "countries": {c: {k: v[k] for k in ("planned_jobs", "verified_jobs", "pending_jobs", "quarantined_jobs")} for c, v in totals.items()},
               "discovery_notes": notes, "plan_errors": errors, "freshly_hashed_files": cache.fresh,
               "cached_unchanged_files": cache.cached, "fresh_bytes_read": cache.bytes_read,
               "wall_seconds": time.monotonic() - start,
               "qc_filter_applied": False, "full_year_gate_applied": False,
               "original_data_modified": False, "network_requests": 0,
               "source_checksum_reverification": "Artifact hashes; provider/raw-uncompressed checksum status is inherited, not recomputed",
               "warnings": ["Receipt coverage is not a union across overlapping plans", "Unknown sensor histories/operators remain explicit", "PENDING is expected while a downloader is active"]}
    write_json(output / "summary.json", summary)
    write_csv(output / "jobs.csv", jobs_ledger, ["country", "plan_id", "job_id", "status", "error"])
    write_csv(output / "receipt_coverage.csv", coverage, ["country", "plan_id", "job_id", "station_id", "group", "period", "parameter", "expected_labels", "non_null", "qc_or_regime", "coverage_source"])
    lines = ["# E0 — локальный аудит", "", "Снимок: `" + snapshot["snapshot_id"] + "`.", "",
             "| Страна | Запланировано | Проверено | Ожидается | Карантин |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {c} | {s['planned_jobs']} | {s['verified_jobs']} | {s['pending_jobs']} | {s['quarantined_jobs']} |" for c, s in summary["countries"].items()]
    lines += ["", "`jobs.csv` содержит причины карантина. `receipt_coverage.csv` сохраняет сводки загрузчика;",
              "они не называются заново пересчитанной почасовой полнотой. Точные маски выбранных окон",
              "создаёт E1.0. Полные годы и ручной QC не являются условиями допуска.", "",
              "Кэшированные хеши отмечены отдельно; `--rehash` повторно читает все исходные байты.", "",
              "Ошибки планов: " + str(len(errors)) + ". Научная точность методов этим аудитом не проверяется."]
    (output / "REPORT_RU.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return snapshot, summary
