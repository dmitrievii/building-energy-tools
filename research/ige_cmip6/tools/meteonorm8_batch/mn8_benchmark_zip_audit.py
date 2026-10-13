#!/usr/bin/env python3
"""Private offline scientific inventory and physical QC for Meteonorm EPW ZIP.

No network calls; reads only the nominated ZIP, writes aggregate JSON without
embedding hourly weather values. Does not upload licensed Meteonorm data.
Python 3.9+ standard library. Numerical validity is NOT forecast validation.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
import statistics
import sys
import zipfile
from pathlib import Path

SITES = {
    "graz": (46.9830, 15.4500, 332),
    "vienna_hohe_warte": (48.2480, 16.3570, 200),
    "innsbruck": (47.2600, 11.3940, 582),
    "sonnblick": (47.054167, 12.957778, 3051),
    "tripoli_greece": (37.5270, 22.4120, 643),
}
SCENARIOS = ("contemporary", "rcp45_2050", "rcp85_2050", "rcp85_2100")
MAX_EPW_UNCOMPRESSED = 30 * 1024 * 1024
MAX_FILES = 200
MISSING = {"temperature": 99.9, "dewpoint": 99.9, "rh": 999.0,
           "pressure": 999999., "radiation": 9999.}

def match_site(lat, lon, tolerance=0.15):
    scores = {name: math.hypot(lat - x, (lon - y)*math.cos(math.radians(lat)))
              for name,(x,y,_) in SITES.items()}
    site = min(scores, key=scores.get)
    return site if scores[site] <= tolerance else None

def scenario_from_name(name):
    s = name.lower().replace(" ", "_")
    if "contemporary" in s or "current" in s or "baseline" in s or "historic" in s:
        return "contemporary"
    rcp = re.search(r"rcp[_\-. ]?(?:4(?:[._]?5)|8(?:[._]?5))", s)
    year = re.search(r"(?<!\d)(2050|2100)(?!\d)", s)
    if rcp and year:
        target = "45" if re.search(r"4(?:[._]?5)", rcp.group()) else "85"
        return "rcp" + target + "_" + year.group()
    return None

def seed_from_name(name):
    match = re.search(r"seed[_\-. ]?0?([1-9]|10)(?!\d)",name.lower())
    return int(match.group(1)) if match else None

def numeric(row, n):
    try:
        value = float(row[n])
        return value if math.isfinite(value) else None
    except (ValueError, IndexError):
        return None

def vapor_pressure(t):
    return 6.112 * math.exp(17.62 * t / (243.12 + t))

def audit_epw(data: bytes, fname: str, *, site_tolerance=0.15):
    raw_sha = hashlib.sha256(data).hexdigest()
    errors = []
    warnings = []
    try:
        table = csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"), newline=""))
        header = [next(table) for _ in range(8)]
    except (StopIteration, csv.Error):
        return {"name": fname, "sha256": raw_sha,
                "errors": ["Missing 8 EPW header lines"], "status": "FAIL"}
    loc = header[0]
    if not loc or loc[0].strip().upper() != "LOCATION" or len(loc) < 10:
        return {"name": fname, "sha256": raw_sha,
                "errors": ["Invalid LOCATION header"], "status": "FAIL"}
    try:
        lat, lon, tz, elev = [float(loc[i]) for i in (6,7,8,9)]
    except ValueError:
        return {"name": fname, "sha256": raw_sha,
                "errors": ["Non-numeric coordinates/time-zone/elevation"], "status": "FAIL"}
    site = match_site(lat, lon, site_tolerance)
    if site is None:
        warnings.append("Coordinates do not match target sites (tolerance " +
                        str(site_tolerance) + " deg)")
    elif abs(elev-SITES[site][2]) > 50:
        warnings.append("Elevation differs by >50 m from Meteonorm screenshot")
    stats = collections.Counter()
    temperatures = []
    dewpoints = []
    rhs = []
    monthly = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0, 0, 0, 0])
    slots = set()
    rows = 0
    minmax = {n: [float("inf"), -float("inf")] for n in
              ("temperature_C", "rh_pct", "ghi_Whm2", "dni_Whm2", "dhi_Whm2")}
    try:
        for row in table:
            rows += 1
            if len(row) != 35:
                stats["invalid_field_count"] += 1
                continue
            try:
                month, day, hour, minute = [int(row[k]) for k in (1,2,3,4)]
                dt.date(2001,month,day)
                if not (1 <= hour <= 24 and 0 <= minute <= 60):
                    raise ValueError("Invalid hour/minute")
                slot=(month,day,hour)
                if slot in slots:
                    stats["duplicate_hour"] += 1
                slots.add(slot)
            except ValueError:
                stats["invalid_timestamps"] += 1
                continue
            t, td, rh, pressure = [numeric(row,k) for k in (6,7,8,9)]
            ghi,dni,dhi=[numeric(row,k) for k in (13,14,15)]
            if t is None or td is None or rh is None or pressure is None:
                stats["nonnumeric_core_weather"] += 1
                continue
            if t >= 99.0 or td >= 99.0 or rh > 100 or pressure >= 999999:
                stats["missing_core_weather"] += 1
                continue
            temperatures.append(t); dewpoints.append(td); rhs.append(rh)
            for key,v in zip(minmax,(t,rh,ghi,dni,dhi)):
                if v is not None:
                    minmax[key][0] = min(minmax[key][0],v)
                    minmax[key][1] = max(minmax[key][1],v)
            if not (-90 <= t <= 70 and -100 <= td <= 70):
                stats["out_of_range_temperature"] += 1
            if td > t + 0.2:
                stats["dewpoint_above_drybulb"] += 1
            if not (0 <= rh <= 100):
                stats["out_of_range_rh"] += 1
            if not (30000 <= pressure <= 110000):
                stats["out_of_range_pressure"] += 1
            if -80 <= t <= 60 and -100 <= td <= t+0.2:
                expected_rh = 100.0*vapor_pressure(td)/vapor_pressure(t)
                if abs(expected_rh-rh)>2:
                    stats["thermodynamic_rh_mismatch_gt2pp"] += 1
            if any(v is None for v in (ghi,dni,dhi)):
                stats["nonnumeric_solar"] += 1
            elif any(v >= MISSING["radiation"] for v in (ghi,dni,dhi)):
                stats["missing_solar"] += 1
            else:
                if any(v < 0 for v in (ghi,dni,dhi)):
                    stats["negative_solar"] += 1
                if any(v > 1400 for v in (ghi,dni,dhi)):
                    stats["solar_irradiance_above_1400"] += 1
                if ghi+1e-9 < dhi-5:
                    stats["dhi_exceeds_ghi"] += 1
                monthly[month][0]+=ghi
                monthly[month][1]+=dni
                monthly[month][2]+=dhi
                monthly[month][3]+=1
            monthly[month][4] += t
            monthly[month][5] += 1
            if t>=30:
                monthly[month][6] += 1
    except csv.Error as exc:
        errors.append("CSV parse error: "+str(exc))
    if rows!=8760:
        errors.append(f"Expected 8760 weather rows; got {rows}")
    if len(slots)!=8760:
        errors.append(f"Unique month/day/hour slots {len(slots)} != 8760")
    if stats["invalid_field_count"] or stats["invalid_timestamps"] or stats["duplicate_hour"]:
        errors.append("EPW structural errors present")
    for tag in ("missing_core_weather", "nonnumeric_core_weather", "missing_solar",
                "nonnumeric_solar","out_of_range_rh","out_of_range_pressure",
                "out_of_range_temperature","negative_solar","solar_irradiance_above_1400"):
        if stats[tag]:
            warnings.append(tag+"="+str(stats[tag]))
    for tag in ("thermodynamic_rh_mismatch_gt2pp","dewpoint_above_drybulb","dhi_exceeds_ghi"):
        if stats[tag]:
            warnings.append(tag+"="+str(stats[tag]))
    per_month = []
    for m in range(1,13):
        g,d,n,valid,t_sum,t_n,hot = monthly[m]
        per_month.append({"month":m,
                          "ghi_kWh_m2":round(g/1000,3),
                          "dni_kWh_m2":round(d/1000,3),
                          "dhi_kWh_m2":round(n/1000,3),
                          "valid_solar_hours":valid,
                          "tmean_C":round(t_sum/t_n,3) if t_n else None,
                          "hours_ge_30C":hot})
    return {
        "name":fname,"sha256":raw_sha,"status":"FAIL" if errors else ("WARN" if warnings else "PASS"),
        "errors":errors,"warnings":warnings,"site":site,
        "latitude":lat,"longitude":lon,"timezone":tz,"elevation_m":elev,
        "scenario_from_filename":scenario_from_name(fname),
        "seed_from_filename":seed_from_name(fname),
        "location_header_name":loc[1],"hour_rows":rows,"unique_hours":len(slots),
        "counts":dict(stats),"temperature_mean_C":round(statistics.mean(temperatures),4) if temperatures else None,
        "temperature_min_C":min(temperatures) if temperatures else None,
        "temperature_max_C":max(temperatures) if temperatures else None,
        "rh_mean_pct":round(statistics.mean(rhs),4) if rhs else None,
        "annual_ghi_kWh_m2":round(sum(v[0] for v in monthly.values())/1000,3),
        "annual_dni_kWh_m2":round(sum(v[1] for v in monthly.values())/1000,3),
        "annual_dhi_kWh_m2":round(sum(v[2] for v in monthly.values())/1000,3),
        "hours_ge_30C":sum(v[6] for v in monthly.values()),
        "monthly":per_month,
        "minmax":{k:[None if math.isinf(x) else x for x in v] for k,v in minmax.items()},
    }

def audit_zip(path, *, site_tolerance=0.15):
    archive=Path(path)
    if not archive.exists():
        raise FileNotFoundError(str(archive))
    records=[]
    inventory=[]
    errors=[]
    with zipfile.ZipFile(archive) as z:
        entries = [x for x in z.infolist() if not x.is_dir()]
        if len(entries)>MAX_FILES:
            raise ValueError("Unexpectedly many archive entries: "+str(len(entries)))
        epws=[x for x in entries if x.filename.lower().endswith(".epw")]
        if not epws:
            raise ValueError("No .epw files in ZIP")
        for x in entries:
            inventory.append({"name":x.filename,"size_bytes":x.file_size})
        for e in epws:
            if e.file_size > MAX_EPW_UNCOMPRESSED:
                records.append({"name":e.filename,"status":"FAIL",
                                "errors":["Uncompressed EPW exceeds 30 MiB"]})
                continue
            try:
                raw=z.read(e)
                records.append(audit_epw(raw,e.filename,site_tolerance=site_tolerance))
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                records.append({"name":e.filename,"status":"FAIL","errors":[str(exc)]})
    coverage=collections.Counter()
    unassigned=[]
    for rec in records:
        key=(rec.get("site"),rec.get("scenario_from_filename"),rec.get("seed_from_filename"))
        if all(x is not None for x in key):
            coverage[key]+=1
        else:
            unassigned.append(rec["name"])
    duplicates=[{"site":site,"scenario":sc,"seed":seed,"count":count}
                for (site,sc,seed),count in coverage.items() if count>1]
    if duplicates:
        errors.append("Duplicate site/scenario/seed combinations")
    missing_seed1=[{"site":site,"scenario":sc} for site in SITES for sc in SCENARIOS
                   if (site,sc,1) not in coverage]
    counts=collections.Counter(r["status"] for r in records)
    report={
        "stage":"IGE_P8_EPWS_ZIP_PRIVATE_QA_V01",
        "generated_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "archive_filename":archive.name,
        "epw_count":len(records),
        "other_file_count":len(entries)-len(epws),
        "site_target_count":len(SITES),
        "scenario_target_count":len(SCENARIOS),
        "seed1_expected_epw_count":20,
        "full_3_seed_expected_epw_count":60,
        "status_counts":dict(counts),
        "duplicates":duplicates,
        "missing_seed1":missing_seed1,
        "unassigned_filename_scenarios_or_seeds":unassigned,
        "archive_errors":errors,
        "records":records,
        "non_epw_names":[x["name"] for x in inventory if not x["name"].lower().endswith(".epw")],
        "interpretation":"Structural/physical QA only; NOT scientific validation of IGE or Meteonorm.",
        "no_weather_hourly_values_exported":True,
        "no_network_calls":True
    }
    return report

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path",help="Full path to private Meteonorm EPW archive")
    parser.add_argument("--out",default="ige_p8_epw_zip_audit.json")
    parser.add_argument("--tolerance-deg",type=float,default=0.15)
    a=parser.parse_args(argv)
    try:
        report=audit_zip(a.zip_path,site_tolerance=a.tolerance_deg)
        out=Path(a.out)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        print("EPWs:",report["epw_count"],
              "PASS/WARN/FAIL:",report["status_counts"],
              "missing seed1 combinations:",len(report["missing_seed1"]))
        print("Report:",out.resolve())
        return 2 if report["status_counts"].get("FAIL") or report["archive_errors"] else 0
    except (OSError,ValueError,zipfile.BadZipFile) as exc:
        print("EPW ZIP AUDIT ERROR:",str(exc),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
