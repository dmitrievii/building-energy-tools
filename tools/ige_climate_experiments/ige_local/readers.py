"""Read only verified native CSV parts; keep support operators and QC explicit."""
from __future__ import annotations

import collections
import csv
import gzip
import json
from pathlib import Path
import time

from .common import (HOUR, InputError, digest, distance, file_hash, fingerprint, iso,
                     log, number, stamp, write_csv, write_json)

VARIABLES = {
    "AT": {"tl": "T", "rf": "RH", "p": "p"},
    "DE": {"air_temperature": {"TT_TU": "T", "RF_TU": "RH"}, "pressure": {"P0": "p"}},
    "CH": {"tre200h0": "T", "ure200h0": "RH", "prestah0": "p"},
}
UNITS = {"T": "degC", "RH": "%", "p": "hPa"}


def normalize_unit(value):
    value = str(value).strip().lower().replace(" ", "")
    if value in {"°c", "gradc", "gradcelsius", "degc", "celsius"}:
        return "degC"
    if value in {"%", "prozent", "percent"}:
        return "%"
    return "hPa" if value == "hpa" else "UNKNOWN:" + value


def native_qc(value):
    n = number(value)
    if n is not None and n.is_integer():
        return str(int(n))
    return str(value).strip() if value is not None and str(value).strip() else "undefined"


def qc_stratum(country, value):
    if country != "AT":
        return value
    return {"10": "automatic_state_unknown", "11": "automatic_changed", "12": "automatic_original",
            "20": "manual_state_unknown", "21": "manual_changed", "22": "manual_original",
            "0": "unchecked"}.get(value, "undefined_or_unknown:" + value)


def qc_allowed(country, code, mode, cfg):
    if code in cfg.get("rejected_native_qc", {}).get(country, []):
        return False
    return country != "AT" or mode == "sensitivity_all_published" or code in {"10", "11", "12", "20", "21", "22"}


def timestamps(cfg):
    result = []
    for w in sorted(cfg["windows"], key=lambda x: stamp(x["start"])):
        t, end = stamp(w["start"]), stamp(w["end_exclusive"])
        while t < end:
            result.append(iso(t)); t += HOUR
    return result


def overlap(start, end, cfg):
    return any(start < stamp(w["end_exclusive"]) and end > stamp(w["start"]) for w in cfg["windows"])


def relevant_parts(run, cfg):
    country = run["country"]
    for record in run["jobs"]:
        j = record["job"]
        if country == "AT":
            if not overlap(stamp(j["start"]), stamp(j["end"]) + HOUR, cfg):
                continue
            for a in record["artifacts"]:
                if a["relative"].startswith("csv/"):
                    sid = Path(a["relative"]).parts[1]
                    yield "AT:" + sid, record, a
        elif country == "DE":
            if j["group"] not in VARIABLES["DE"] or not overlap(stamp(run["start"]), stamp(run["end_exclusive"]), cfg):
                continue
            yield "DE:" + j["station_id"], record, next(a for a in record["artifacts"] if a["relative"].startswith("parts/"))
        elif j["network"] == "smn" and overlap(stamp(run["start"]), stamp(run["end_exclusive"]), cfg) and overlap(stamp(j["nominal_start"]), stamp(j["nominal_end_exclusive"]), cfg):
            yield "CH:smn:" + j["station_id"], record, next(a for a in record["artifacts"] if a["relative"].startswith("parts/"))


def valid_geometry(s):
    return s["station_type"] != "COMBINED" and s["lat"] is not None and s["lon"] is not None and -90 <= s["lat"] <= 90 and -180 <= s["lon"] <= 180


def target_selection(stations, available, cfg):
    targets = []
    notes = []
    for country in cfg["countries"]:
        pool = sorted((s for k, s in stations.items() if k in available and s["country"] == country and valid_geometry(s)),
                      key=lambda x: (x["height_m"] is None, x["height_m"] or 0, x["key"]))
        wanted = cfg.get("targets", {}).get(country, "auto")
        if wanted == "auto":
            n = min(cfg["max_targets_per_country"], len(pool))
            # Metadata-only elevation quantiles; observations/errors are not inspected.
            indices = sorted({round(i * (len(pool)-1)/(n-1)) if n > 1 else 0 for i in range(n)})
            chosen = [pool[i] for i in indices]
        elif isinstance(wanted, list):
            chosen = [s for s in pool if s["key"] in wanted or s["station_id"] in wanted]
            missing = [x for x in wanted if not any(x in (s["key"], s["station_id"]) for s in chosen)]
            if missing:
                notes.append({"country": country, "reason": "REQUESTED_TARGET_UNAVAILABLE_IN_SNAPSHOT", "targets": missing})
        else:
            raise InputError("targets must contain 'auto' or explicit station IDs")
        targets.extend(s["key"] for s in chosen)
        if not chosen:
            notes.append({"country": country, "reason": "NO_READY_BASIC_VARIABLE_PARTS_FOR_REQUESTED_WINDOWS"})
    return sorted(set(targets)), notes


def candidate_selection(target, stations, available, cfg):
    candidates = []
    for key in sorted(available):
        s = stations.get(key)
        if not s or not valid_geometry(s) or s["country"] != target["country"] or s["family"] == target["family"] or key == target["key"]:
            continue
        d = distance(target, s)
        if d <= cfg["co_location_exclusion_km"] or d > cfg["radius_km"]:
            continue
        if s["height_m"] is None or target["height_m"] is None or abs(s["height_m"]-target["height_m"]) > cfg["max_height_difference_m"]:
            continue
        candidates.append({"key": key, "distance_km": d, "delta_height_target_minus_donor_m": target["height_m"]-s["height_m"]})
    return sorted(candidates, key=lambda x: (x["distance_km"], x["key"]))[:cfg["candidate_count"]]


def checked_metadata(record):
    assets = [a for a in record["artifacts"] if a["relative"].startswith("metadata/")]
    if not assets:
        return {}
    a = assets[0]
    body = Path(a["path"]).read_bytes()
    if digest(body) != a["sha256"] or fingerprint(a["path"]) != a["fingerprint"]:
        raise InputError("Metadata changed since E0: " + a["path"])
    return json.loads(body)


def de_definition(meta, field, day):
    rows = [r for r in meta.get("parameter_history", []) if r.get("Parameter") == field and
            r["Von_Datum"] <= day <= (r.get("Bis_Datum") or "99991231")]
    signatures = {tuple(r.get(k, "") for k in ("Einheit", "Parameterbeschreibung", "Zusatz-Info", "Datenquelle (Strukturversion=SV)")) for r in rows}
    if len(signatures) != 1:
        return None
    return next(iter(signatures))


def cells(country, run, record, row, t, meta, counters):
    j = record["job"]
    fields = VARIABLES["DE"][j["group"]] if country == "DE" else VARIABLES[country]
    for native, variable in fields.items():
        if native not in row:
            continue
        value = number(row[native])
        if value is None:
            if str(row[native]).strip() not in ("", "-999", "-999.0", "-9999", "-9999.0"):
                counters["unusable_numeric_cells"] += 1
        if country == "AT":
            definition = run["parameter_definitions"].get(native, {})
            unit = normalize_unit(definition.get("unit"))
            operator = "AT:" + native + ":" + digest({k: definition.get(k) for k in ("unit", "description", "long_name")})[:16]
            qc = native_qc(row.get(native + "_flag"))
        elif country == "DE":
            definition = de_definition(meta, native, t.strftime("%Y%m%d"))
            if definition is None:
                counters["unknown_or_ambiguous_operator_cells"] += 1
                continue
            unit = normalize_unit(definition[0])
            # DWD v24.03 explicitly defines P0 as station pressure in hPa. Some
            # native per-station histories leave Einheit blank. Never use P (MSL).
            unit_provenance = "native_parameter_history"
            if native == "P0":
                description = definition[1].lower()
                if not any(term in description for term in ("stationshoehe", "stationshöhe", "station height", "station level")):
                    counters["station_pressure_reference_mismatch_cells"] += 1
                    continue
                if not definition[0].strip():
                    unit = "hPa"
                    unit_provenance = "DWD_hourly_pressure_v24.03_column_P0_hPa"
                    counters["unit_from_official_product_contract_cells"] += 1
            operator = "DE:" + j["group"] + ":" + native + ":" + digest(definition)[:16]
            qn = sorted(k for k in row if k.startswith("QN_"))
            qc = ";".join(k + "=" + native_qc(row[k]) for k in qn) if qn else "not_supplied"
        else:
            definition = run["parameter_definitions"].get(j["network"], {}).get(native, {})
            unit = normalize_unit(definition.get("parameter_unit"))
            expected_regime = "pre2018_synop_rule_for_aggregates" if t.year < 2018 else "since2018_hour_rule_for_aggregates"
            regime = row.get("hour_interval_regime", "")
            # Preserve the downloader's actual labels, including its exact legacy name.
            if regime != expected_regime:
                counters["unknown_or_ambiguous_operator_cells"] += 1
                continue
            operator = "CH:" + native + ":" + regime
            qc = "not_supplied"
        if unit != UNITS[variable]:
            counters["unit_mismatch_cells"] += 1
            continue
        if variable == "p" and value is not None and value <= 0:
            counters["nonpositive_station_pressure_cells"] += 1
            continue
        yield variable, {"value": value, "qc": qc, "qc_stratum": qc_stratum(country, qc), "operator": operator,
                         "native_parameter": native, "unit_provenance": unit_provenance if country == "DE" else "native_parameter_definition"}


def insert_observation(data, conflicts, slot, obs, counters):
    old = data.get(slot)
    if old is None:
        if slot not in conflicts or obs["priority"] < conflicts[slot]:
            data[slot] = obs
            conflicts.pop(slot, None)
        return
    if obs["priority"] < old["priority"]:
        if old["value"] != obs["value"]:
            counters["overlap_disagreements_resolved_by_declared_priority"] += 1
        data[slot] = obs
    elif obs["priority"] == old["priority"]:
        if (obs["value"], obs["qc"], obs["operator"]) != (old["value"], old["qc"], old["operator"]):
            counters["equal_priority_conflicts"] += 1
            conflicts[slot] = obs["priority"]
            del data[slot]
        else:
            counters["identical_duplicate_cells"] += 1


def prepare(snapshot, cfg, output):
    started = time.monotonic()
    if snapshot.get("snapshot_id") != digest({k: v for k, v in snapshot.items() if k != "snapshot_id"}):
        raise InputError("E0 snapshot hash mismatch")
    if snapshot["config_sha256"] != digest(cfg):
        raise InputError("Configuration differs from the E0 snapshot; create a new audit")
    stations, variants = {}, set()
    parts = []
    for run in snapshot["runs"]:
        for s in run["stations"]:
            old = stations.get(s["key"])
            if old and any(old[k] != s[k] for k in ("lat", "lon", "height_m", "family", "station_type")):
                variants.add(s["key"])
            stations[s["key"]] = s
        parts.extend((run, key, r, a) for key, r, a in relevant_parts(run, cfg))
    available = {key for _, key, _, _ in parts} - variants
    targets, notes = target_selection(stations, available, cfg)
    notes.extend({"station": k, "reason": "CONFLICTING_GEOMETRY_ACROSS_SOURCE_SNAPSHOTS"} for k in sorted(variants))
    donors = {k: candidate_selection(stations[k], stations, available, cfg) for k in targets}
    needed = set(targets) | {d["key"] for ds in donors.values() for d in ds}
    times = timestamps(cfg)
    time_set = set(times)
    # This is sealed before any observation is read or any error is calculated.
    selection = {"schema": "IGE_E10_D_SELECTION_v1", "role": cfg["role"], "snapshot_id": snapshot["snapshot_id"],
                 "config_sha256": digest(cfg), "targets": targets, "donors": donors, "timestamps": times,
                 "selection_rule": "ready source parts plus metadata-only elevation quantiles; no error/quality optimization",
                 "same_country_donors_only": True, "geometry_role": "published station geometry proxy",
                 "notes": notes}
    selection["selection_id"] = digest(selection)
    write_json(Path(output) / "selection.sealed.json", selection)
    data, conflicts = {}, {}
    counters = collections.Counter()
    sources, failures = [], []
    seen_parts = set()
    for index, (run, key, record, asset) in enumerate(parts, 1):
        if key not in needed or (asset["path"], asset["sha256"]) in seen_parts:
            continue
        seen_parts.add((asset["path"], asset["sha256"]))
        log("E1.0 input: " + key + " / " + Path(asset["path"]).name)
        try:
            if fingerprint(asset["path"]) != asset["fingerprint"] or file_hash(asset["path"]) != asset["sha256"]:
                raise InputError("CSV changed since E0")
            meta = checked_metadata(record)
            pending = []
            last = None
            country = run["country"]
            j = record["job"]
            with gzip.open(asset["path"], "rt", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames != asset["columns"]:
                    raise InputError("CSV header changed since E0")
                for row in reader:
                    counters["native_rows_scanned"] += 1
                    if None in row or any(v is None for v in row.values()):
                        raise InputError("Malformed native CSV row")
                    native_time = row.get("timestamp_utc", "")
                    if not native_time:
                        counters["unresolved_time_rows"] += 1
                        continue
                    t = stamp(native_time)
                    if last is not None and t <= last:
                        raise InputError("Duplicate/unsorted timestamps inside a native part")
                    last = t
                    if t.minute or t.second or t.microsecond:
                        counters["off_hour_rows_not_resampled"] += 1
                        continue
                    if country == "AT":
                        if row.get("station_id") != stations[key]["station_id"]:
                            raise InputError("Native AT station identity mismatch")
                        if not stamp(j["start"]) <= t <= stamp(j["end"]):
                            raise InputError("AT row outside its requested part")
                    elif country == "DE":
                        if str(row.get("STATIONS_ID", "")).zfill(5) != stations[key]["station_id"]:
                            raise InputError("Native DE station identity mismatch")
                    elif row.get("station_abbr", "").strip().upper() != stations[key]["station_id"]:
                        raise InputError("Native CH station identity mismatch")
                    if not stamp(run["start"]) <= t < stamp(run["end_exclusive"]):
                        raise InputError("Native part contains rows outside plan selection")
                    time_key = iso(t)
                    if time_key not in time_set:
                        continue
                    for variable, obs in cells(country, run, record, row, t, meta, counters):
                        if variable not in cfg["variables"]:
                            continue
                        priority = {"historical": 0, "recent": 1, "row": 2, "now": 2}.get(j.get("tier", j.get("type")), 0)
                        obs.update({"priority": priority, "source": run["plan_id"] + "/" + j["job_id"] + "/" + asset["sha256"]})
                        pending.append(((key, time_key, variable), obs))
            if fingerprint(asset["path"]) != asset["fingerprint"]:
                raise InputError("CSV changed during parsing")
            for slot, obs in pending:
                insert_observation(data, conflicts, slot, obs, counters)
            sources.append({"path": asset["path"], "sha256": asset["sha256"], "station": key,
                            "exposure": "AUTOMATED_READ_NATIVE_CONTAINER_FOR_D_PILOT", "selected_window_cells": len(pending)})
        except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
            failures.append({"path": asset["path"], "station": key, "reason": str(exc)})
    dataset = {"schema": "IGE_E10_DATASET_v1", "selection": selection, "config": cfg,
               "stations": {k: stations[k] for k in sorted(needed)},
               "observations": [[*slot, data[slot]] for slot in sorted(data)],
               "conflicts": [list(s) for s in sorted(conflicts)], "sources": sources,
               "read_failures": failures, "read_counters": dict(counters)}
    raw = json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    path = Path(output) / "dataset.sealed.json.gz"
    path.write_bytes(gzip.compress(raw, mtime=0))
    info = {"dataset_sha256": file_hash(path), "uncompressed_sha256": digest(raw), "source_csv_files": len(sources),
            "retained_cells": len(data), "conflict_cells_excluded": len(conflicts), "read_failures": failures,
            "read_counters": dict(counters), "prepare_wall_s": time.monotonic()-started,
            "new_confirmatory_holdout_opened": False, "notes": notes}
    write_json(Path(output) / "preparation.json", info)
    availability = []
    for key in sorted(needed):
        country = stations[key]["country"]
        for variable in cfg["variables"]:
            cells_here = [data[(key,t,variable)] for t in times if (key,t,variable) in data and data[(key,t,variable)]["value"] is not None]
            for mode in cfg["qc_modes"]:
                availability.append({"station": key, "role": "target" if key in targets else "donor",
                    "variable": variable, "qc_mode": mode, "N_calendar": len(times), "N_numeric_published": len(cells_here),
                    "N_eligible": sum(qc_allowed(country, x["qc"], mode, cfg) for x in cells_here),
                    "qc_histogram": json.dumps(dict(collections.Counter(x["qc_stratum"] for x in cells_here)), ensure_ascii=False)})
    write_csv(Path(output) / "availability.csv", availability, ["station", "role", "variable", "qc_mode", "N_calendar", "N_numeric_published", "N_eligible", "qc_histogram"])
    return path, info
