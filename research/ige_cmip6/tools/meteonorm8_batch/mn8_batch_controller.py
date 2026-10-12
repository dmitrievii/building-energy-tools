#!/usr/bin/env python3
"""Meteonorm 8.2 research batch preparation, EPW QC and Windows UI inspection.

Uses documented Meteonorm 8 batch import/export; does not modify or
reverse-engineer Meteonorm, invoke its licensing system, or call undocumented APIs.
Python >=3.9; standard library for all commands except optional 'inspect-ui'.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path

FORMAT_NUMBER = 22             # ENERGY PLUS (.epw), Meteonorm 8.2 handbook Table 2.4.3
SCENARIOS = ("contemporary", "rcp45_2050", "rcp85_2050", "rcp85_2100")
SEEDS = (1, 2, 3)
# Heights and situations here are pilot values, not a verified matching of an
# individual Meteonorm built-in station. Review them before scientific runs.
DEFAULT_SITES = [
    {"id": "graz", "name": "IGE_Graz", "latitude": 46.9830, "longitude": 15.4500,
     "altitude": 342, "situation": "open"},
    {"id": "vienna_hohe_warte", "name": "IGE_Wien_Hohe_Warte",
     "latitude": 48.2480, "longitude": 16.3570, "altitude": 198, "situation": "open"},
    {"id": "innsbruck", "name": "IGE_Innsbruck", "latitude": 47.2600,
     "longitude": 11.3940, "altitude": 575, "situation": "open"},
    {"id": "sonnblick", "name": "IGE_Sonnblick", "latitude": 47.054167,
     "longitude": 12.957778, "altitude": 3106, "situation": "summit"},
    {"id": "tripoli_greece", "name": "IGE_Tripoli_Greece", "latitude": 37.5270,
     "longitude": 22.4120, "altitude": 643, "situation": "open"},
]
REQUIRED_META = {"name", "latitude", "longitude", "altitude", "situation"}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def dump_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def valid_config(config):
    if not config.get("sites"):
        raise ValueError("At least one site required")
    if len(config["sites"]) > 100:
        raise ValueError("Meteonorm 8 batch mode supports at most 100 sites")
    ids = []
    for x in config["sites"]:
        if not REQUIRED_META.issubset(x):
            raise ValueError("Missing site keys: " + str(REQUIRED_META - set(x)))
        ident = x.get("id", "")
        if not re.fullmatch("[a-z][a-z0-9_]*", ident):
            raise ValueError("Site id must be lower-case ASCII snake_case: " + repr(ident))
        if not re.fullmatch("[A-Za-z0-9_-]+", str(x["name"])):
            raise ValueError("Meteonorm batch name must be ASCII and contain no spaces")
        if not -90 <= float(x["latitude"]) <= 90:
            raise ValueError("Invalid latitude: " + str(x))
        if not -180 <= float(x["longitude"]) <= 180:
            raise ValueError("Invalid longitude: " + str(x))
        if not -450 <= float(x["altitude"]) <= 9000:
            raise ValueError("Implausible altitude: " + str(x))
        ids.append(ident)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate site IDs")
    scenarios = config["scenarios"]
    seeds = config["seeds"]
    if not scenarios or not seeds or not set(scenarios).issubset(SCENARIOS):
        raise ValueError("Invalid scenario list")
    if any(not isinstance(s, int) or s not in range(1, 11) for s in seeds):
        raise ValueError("Meteonorm 8 first random seed must be one of its 10 GUI selections (1..10)")


def batch_file(path, sites, sep, *, include_situation=False):
    """Make Meteonorm 8 batch file, using the official 4-column minimal example.

    The 8.2 manual shows TAB-separated rows without optional columns.
    Semicolon is a fallback. Comma + 'situation' from the former
    pilot is unverified and intentionally no longer the default.
    """
    cols = ["name", "longitude", "latitude", "altitude"]
    if include_situation:
        cols.append("situation")
    with Path(path).open("w", encoding="ascii", newline="") as f:
        w = csv.writer(f, delimiter=sep, lineterminator="\r\n")
        w.writerow(["Formattyp = 22"])
        w.writerow(["Save = hour"])
        w.writerow(cols)
        for x in sites:
            row = [x["name"], format(float(x["longitude"]), ".6f"),
                   format(float(x["latitude"]), ".6f"), x["altitude"]]
            if include_situation:
                row.append(x["situation"])
            w.writerow(row)


def create_project(folder, *, rewrite=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    config_file = folder / "project_config.json"
    if config_file.exists() and not rewrite:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    else:
        if config_file.exists():
            raise FileExistsError("Refusing to overwrite edited project_config.json")
        config = {
            "title": "IGE P8 Meteonorm 8.2 independent method benchmark",
            "meteonorm_product": "Meteonorm 8.x desktop (user licensed)",
            "epw_format_number": FORMAT_NUMBER,
            "sites": DEFAULT_SITES, "scenarios": list(SCENARIOS), "seeds": list(SEEDS),
            "settings": {
                "source": "Meteonorm database, not imported user data",
                "horizon": "record exact GUI setting",
                "solar_model": "document whether Perez/BRL etc.",
                "time_system": "Legal/local standard (verify in GUI)",
                "uvi_ghi": "not part of EPW benchmark",
                "urban_heat_island": "disabled unless expressly part of experiment",
            },
            "warning": "Never treat RCP as identical to SSP or this typical year as an observed year."
        }
        dump_json(config_file, config)
    valid_config(config)

    batches = folder / "batch_input"
    batches.mkdir(exist_ok=True)
    # Primary on-PC pilot: test one location, 4 columns, literal TABs,
    # plain ASCII, and CRLF, mirroring the Meteonorm 8.2 handbook example.
    batch_file(batches / "pilot_one_graz_tabs.txt", config["sites"][:1], "\t")
    batch_file(batches / "locations_5_tabs.txt", config["sites"], "\t")
    # Fallback if this Meteonorm installation accepts semicolon CSV.
    batch_file(batches / "locations_5_semicolon.csv", config["sites"], ";")
    # Update compatibility names too: an existing project may contain the
    # previously generated comma+optional-situation CSV.
    batch_file(batches / "locations_format22.csv", config["sites"], ";")
    batch_file(batches / "locations_format22.tsv", config["sites"], "\t")
    run_rows = []
    for scenario in config["scenarios"]:
        for seed in config["seeds"]:
            key = "{}_seed{:02d}".format(scenario, seed)
            (folder / "exports" / key).mkdir(parents=True, exist_ok=True)
            run_rows.append({
                "run_id": key, "period": "Contemporary" if scenario == "contemporary" else "Future",
                "scenario": scenario, "first_random_seed": seed,
                "expected_epw_count": len(config["sites"]),
                "expected_raw_export_dir": str(Path("exports") / key),
                "reviewed_gui_settings": "NO",
            })
    with (folder / "run_plan.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(run_rows[0]))
        w.writeheader()
        w.writerows(run_rows)
    print("Project: ", folder)
    print("Batch location inputs: ", batches)
    print("Runs: {}, expected individual EPWs: {}".format(
        len(run_rows), len(run_rows) * len(config["sites"])))
    print("FIRST: import pilot_one_graz_tabs.txt with Locations > Import locations for batch mode.")
    print("Only after success, import locations_5_tabs.txt; fallback locations_5_semicolon.csv.")
    print("Then for each run in run_plan.csv select GUI period/RCP/year/seed and Save All.")
    print("Finally: python mn8_batch_controller.py verify --project PROJECT_DIRECTORY")


def verify_epw(path):
    """Structure, dates, robust meteorological ranges; no fake missing-value imputation."""
    p = Path(path)
    with p.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        lines = list(csv.reader(f))
    if len(lines) != 8768 or not lines[0] or lines[0][0].strip().upper() != "LOCATION":
        raise ValueError("Expected 8 EPW header lines + 8760 hourly records")
    if len(lines[0]) < 10:
        raise ValueError("EPW LOCATION has fewer than 10 fields")
    try:
        lat, lon, elevation = (float(lines[0][i]) for i in (6, 7, 9))
    except (ValueError, IndexError) as e:
        raise ValueError("Bad EPW LOCATION latitude/longitude/elevation") from e
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and -450 <= elevation <= 9000):
        raise ValueError("Invalid EPW site coordinates")
    seen = set()
    counts = collections.Counter()
    for i, row in enumerate(lines[8:], start=1):
        if len(row) != 35:
            raise ValueError("EPW line {} has {} fields, expected 35".format(i, len(row)))
        try:
            mo, day, hr, mi = (int(row[j]) for j in (1, 2, 3, 4))
            datetime.date(2001, mo, day)
            if not 1 <= hr <= 24 or not 0 <= mi <= 60:
                raise ValueError("EPW invalid time")
            t = float(row[6]); dp = float(row[7]); rh = float(row[8])
            pressure = float(row[9]); ghi, dni, dhi = (float(row[j]) for j in (13, 14, 15))
            wd, ws = float(row[20]), float(row[21])
        except (ValueError, IndexError) as e:
            raise ValueError("EPW line {} invalid date or weather".format(i)) from e
        key = (mo, day, hr)
        if key in seen:
            raise ValueError("Repeated EPW hour: " + str(key))
        seen.add(key)
        if not (-100 <= t <= 80 and -100 <= dp <= 80 and dp <= t + 1.0):
            counts["suspect_temperature_or_dewpoint"] += 1
        if not (0 <= rh <= 100):
            counts["suspect_RH"] += 1
        if not (45000 <= pressure <= 112000):
            counts["suspect_pressure"] += 1
        if any(v < 0 or v > 1600 for v in (ghi, dni, dhi)):
            counts["suspect_solar"] += 1
        if not (0 <= wd <= 360 and 0 <= ws <= 100):
            counts["suspect_wind"] += 1
    if len(seen) != 8760:
        raise ValueError("Incomplete hourly EPW coverage")
    return {
        "epw_sha256": sha256(p), "hour_count": 8760, "field_count": 35,
        "latitude": lat, "longitude": lon, "elevation_m": elevation,
        "qc_flags": dict(counts), "has_qc_flags": bool(counts),
    }


def match_site(epw_info, sites, tolerance_deg):
    hits = [s for s in sites if
            abs(float(s["latitude"]) - epw_info["latitude"]) <= tolerance_deg and
            abs(float(s["longitude"]) - epw_info["longitude"]) <= tolerance_deg]
    if len(hits) != 1:
        raise ValueError("EPW must match exactly one configured site; got " +
                         str([x["id"] for x in hits]))
    # Elevation is explicitly audited and not forcibly overwritten.
    return hits[0]


def verify_project(folder, tolerance_deg=0.025):
    folder = Path(folder)
    config = json.loads((folder / "project_config.json").read_text(encoding="utf-8"))
    valid_config(config)
    all_rows = []
    error_rows = []
    for scenario in config["scenarios"]:
        for seed in config["seeds"]:
            run_id = "{}_seed{:02d}".format(scenario, seed)
            raw_dir = folder / "exports" / run_id
            paths = sorted(raw_dir.rglob("*.epw")) if raw_dir.exists() else []
            visited = set()
            if len(paths) != len(config["sites"]):
                error_rows.append({"run_id": run_id, "issue": "wrong_epw_count",
                                   "observed": len(paths), "required": len(config["sites"])})
            for p in paths:
                try:
                    result = verify_epw(p)
                    site = match_site(result, config["sites"], tolerance_deg)
                    if site["id"] in visited:
                        raise ValueError("Duplicate site in one run: " + site["id"])
                    visited.add(site["id"])
                    record = {"run_id": run_id, "scenario": scenario, "seed": seed,
                              "site_id": site["id"], "source_path": str(p.relative_to(folder)),
                              **result}
                    if abs(result["elevation_m"] - float(site["altitude"])) > 100:
                        record["elevation_warning"] = "EPW site elevation differs >100m"
                    if result["has_qc_flags"]:
                        error_rows.append({"run_id": run_id, "site_id": site["id"],
                                           "issue": "weather_qc_flags", "flags": result["qc_flags"]})
                    all_rows.append(record)
                except (OSError, ValueError) as e:
                    error_rows.append({"run_id": run_id, "file": str(p), "issue": str(e)})
            if visited != {s["id"] for s in config["sites"]}:
                error_rows.append({"run_id": run_id, "issue": "missing_sites",
                                   "site_ids": sorted({s["id"] for s in config["sites"]} - visited)})
    hashes = collections.defaultdict(list)
    for row in all_rows:
        hashes[row["epw_sha256"]].append(row)
    duplicates = [[{"site": v["site_id"], "run_id": v["run_id"]} for v in group]
                  for group in hashes.values() if len(group) > 1]
    complete = not error_rows and len(all_rows) == len(config["sites"]) * len(config["seeds"]) * len(config["scenarios"])
    report = {"stage": "IGE_P8_MN8_BATCH_QC", "complete": complete,
              "n_expected": len(config["sites"]) * len(config["seeds"]) * len(config["scenarios"]),
              "n_passed_structural": len(all_rows), "failures": error_rows,
              "cross_run_byte_identical_duplicates": duplicates,
              "license": "User-provided Meteonorm; do not commit raw EPWs to public GitHub",
              "meteorological_benchmark_validated": False, "records": all_rows}
    dump_json(folder / "verification_report.json", report)
    print("EPW matched: {}/{} | failures: {} | duplicate groups: {}".format(
        len(all_rows), report["n_expected"], len(error_rows), len(duplicates)))
    print("Saved:", folder / "verification_report.json")
    if error_rows:
        print("First failures:\n" + json.dumps(error_rows[:8], indent=2))
    return 0 if complete else 2


def inspect_ui(output, max_depth=5):
    try:
        from pywinauto import Desktop
    except ImportError as e:
        raise RuntimeError("Windows only: pip install pywinauto comtypes pywin32") from e
    windows = [w for w in Desktop(backend="uia").windows()
               if "meteonorm" in w.window_text().lower()]
    if not windows:
        raise RuntimeError("Start licensed Meteonorm 8 first; no window with Meteonorm title found")
    def inspect(node, depth=0):
        desc = {"depth": depth, "control_type": "", "automation_id": "",
                "class_name": "", "name": "", "rectangle": ""}
        try:
            info = node.element_info
            desc["control_type"] = str(info.control_type)
            desc["automation_id"] = str(info.automation_id)
            desc["class_name"] = str(info.class_name)
            # Don't capture Edit field values, license information, or credentials.
            desc["name"] = (str(info.name)[:150] if info.control_type != "Edit" else "[edit]")
            desc["rectangle"] = str(node.rectangle())
        except Exception as e:
            desc["error"] = type(e).__name__
        children = []
        if depth < max_depth:
            try:
                children = [inspect(child, depth + 1) for child in node.children()[:250]]
            except Exception:
                pass
        if children:
            desc["children"] = children
        return desc
    dump_json(output, {"diagnostic_only": True, "application": "Meteonorm 8",
                       "windows": [inspect(w) for w in windows[:3]]})
    print("Wrote sanitized UIA tree to", output)
    print("No button was pressed and no licence settings were read.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="action", required=True)
    init = subs.add_parser("init", help="Prepare 5-site x 4 climate-setting x 3-seed batch plan")
    init.add_argument("--project", required=True)
    verify = subs.add_parser("verify", help="Validate exported EPWs by run and geo-match")
    verify.add_argument("--project", required=True)
    verify.add_argument("--tolerance-deg", type=float, default=0.025)
    chk = subs.add_parser("check-epw", help="Inspect one EPW, including its SHA-256")
    chk.add_argument("epw")
    insp = subs.add_parser("inspect-ui", help="Read sanitized Meteonorm 8 UI Automation control tree")
    insp.add_argument("--out", default="meteonorm_uia_controls.json")
    insp.add_argument("--max-depth", type=int, default=5)
    a = p.parse_args()
    if a.action == "init":
        create_project(a.project)
    elif a.action == "verify":
        return verify_project(a.project, a.tolerance_deg)
    elif a.action == "check-epw":
        print(json.dumps(verify_epw(a.epw), ensure_ascii=False, indent=2))
    else:
        inspect_ui(a.out, a.max_depth)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print("ERROR:", str(exc), file=sys.stderr)
        sys.exit(2)
