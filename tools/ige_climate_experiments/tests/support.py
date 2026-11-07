"""Clearly synthetic native-layout fixtures; never presented as weather evidence."""
import copy
import csv
import datetime as dt
import gzip
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ige_local.common import HOUR, canonical, digest, iso, read_json, stamp, write_json


def csv_blob(rows, fields):
    f = io.StringIO(newline="")
    w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
    w.writeheader(); w.writerows(rows)
    return gzip.compress(f.getvalue().encode("utf-8"), mtime=0)


def publish_at(run, p, job, transform=None):
    hours = [iso(stamp(job["start"]) + HOUR*i) for i in range(job["expected_hours"])]
    records = {}
    for i, sid in enumerate(job["station_ids"]):
        records[sid] = [{"timestamp_utc": t, "station_id": sid, "tl": 5+i*2+h*.1, "tl_flag": 12,
            "rf": 60+i, "rf_flag": 22, "p": 960-i*3, "p_flag": 12} for h,t in enumerate(hours)]
    if transform:
        transform(records)
    raw = canonical({"fixture": "SYNTHETIC_NATIVE_LAYOUT_NOT_OBSERVATIONS", "rows": records})
    source_sha = digest(raw)
    raw_path = f"raw/{job['job_id']}/{source_sha}.json.gz"
    body = gzip.compress(raw, mtime=0)
    (run / raw_path).parent.mkdir(parents=True, exist_ok=True)
    (run / raw_path).write_bytes(body)
    artifacts = [{"path": raw_path, "file_sha256": digest(body)}]
    summaries = {}
    for sid, rows in records.items():
        relative = f"csv/{sid}/{job['start'][:4]}/{job['job_id']}.csv.gz"
        body = csv_blob(rows, ["timestamp_utc", "station_id", *job["parameters"]])
        (run/relative).parent.mkdir(parents=True, exist_ok=True); (run/relative).write_bytes(body)
        artifacts.append({"path": relative, "file_sha256": digest(body)})
        summaries[sid] = {name: {"unit": {"tl": "°C", "rf": "%", "p": "hPa"}[name],
            "requested_hours": len(rows), "non_null_hours": sum(r[name] is not None for r in rows),
            "qc_counts_on_non_null": {"12": len(rows)}} for name in ("tl", "rf", "p")}
    r = {"status": "complete", "request_sha256": digest(job), "original_response_sha256": source_sha,
         "artifacts": artifacts, "stations": summaries}
    write_json(run/"receipts"/(job["job_id"]+".json"), r)


def make_at(base, nsites=4, hours=6, days=1, complete_days=1, transform=None, metadata_transform=None, start="2025-01-01T00:00:00Z"):
    base = Path(base)
    metadata = {"frequency": "PT1H", "type": "station", "mode": "historical", "stations": [], "parameters": []}
    for i in range(nsites):
        metadata["stations"].append({"id": 100+i, "name": "Synthetic " + str(i), "type": "INDIVIDUAL", "group_id": None,
            "lat": 47.0, "lon": 15.0+i*.1, "altitude": 400+i*50, "valid_from": "2000-01-01T00:00:00Z", "valid_to": "2100-01-01T00:00:00Z"})
    for native, unit in (("tl", "°C"), ("rf", "%"), ("p", "hPa")):
        metadata["parameters"].append({"name": native, "unit": unit, "description": "synthetic declared hourly measurement"})
        metadata["parameters"].append({"name": native+"_flag", "unit": "code"})
    if metadata_transform:
        metadata_transform(metadata)
    raw_meta = canonical(metadata)
    params = [x["name"] for x in metadata["parameters"]]
    jobs = []
    for day in range(days):
        lo = stamp(start) + dt.timedelta(days=day)
        j = {"start": iso(lo), "end": iso(lo+HOUR*(hours-1)), "station_ids": [str(100+i) for i in range(nsites)],
             "parameters": params, "expected_hours": hours, "requested_values": hours*nsites*len(params)}
        j["job_id"] = digest(j)[:24]; jobs.append(j)
    p = {"schema": "IGE_AT_DOWNLOAD_PLAN_v1", "start": jobs[0]["start"], "end": jobs[-1]["end"],
         "metadata_original_utf8": raw_meta.decode("utf-8"), "metadata_sha256": digest(raw_meta), "jobs": jobs}
    p["plan_id"] = digest(p)
    run = base / "AT" / "AT" / "downloaded" / p["plan_id"][:20]
    run.mkdir(parents=True, exist_ok=True); write_json(run/"plan.json", p)
    for j in jobs[:complete_days]:
        publish_at(run, p, j, transform)
    return run, p


def config(base, countries=None, workers=None, start="2025-01-01T00:00:00Z", hours=6):
    base = Path(base)
    code = base / "ClimateExperiments"
    database = base / "Database"
    code.mkdir(parents=True, exist_ok=True); database.mkdir(exist_ok=True)
    c = read_json(ROOT/"config_E0_E10.json")
    c.update({"countries": countries or ["AT"], "variables": ["T", "RH", "p"],
              "benchmark_workers": workers or [1], "max_targets_per_country": 2,
              "windows": [{"start": start, "end_exclusive": iso(stamp(start)+hours*HOUR)}]})
    path = code/"config.json"; write_json(path, c)
    return path


def files_unchanged_state(base):
    return {str(p.relative_to(base)): (digest(p.read_bytes()),p.stat().st_mtime_ns,p.stat().st_ctime_ns)
            for p in Path(base).rglob("*") if p.is_file()}


def rewrite_csv(run, job, station, edit):
    rp = run/"receipts"/(job["job_id"]+".json")
    receipt = read_json(rp)
    a = next(a for a in receipt["artifacts"] if a["path"].startswith("csv/"+str(station)+"/"))
    with gzip.open(run/a["path"], "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f); fields = reader.fieldnames; rows = list(reader)
    edit(rows)
    blob = csv_blob(rows, fields); (run/a["path"]).write_bytes(blob)
    a["file_sha256"] = digest(blob); write_json(rp, receipt)


def cells_de_setup():
    run = {"parameter_definitions": {}}
    record = {"job": {"group": "pressure"}}
    row = {"P0": "950.0", "P": "1013.25", "QN_8": "3"}
    meta = {"parameter_history": [{"Parameter": "P0", "Von_Datum": "20000101", "Bis_Datum": "",
        "Einheit": "hPa", "Parameterbeschreibung": "Luftdruck in Stationshoehe", "Zusatz-Info": "UTC"}]}
    return run, record, row, meta


def cells_ch_setup():
    run = {"parameter_definitions": {"smn": {"tre200h0": {"parameter_unit": "°C"},
            "ure200h0": {"parameter_unit": "%"}, "prestah0": {"parameter_unit": "hPa"}}}}
    record = {"job": {"network": "smn"}}
    row = {"tre200h0": "5", "ure200h0": "70", "prestah0": "950", "hour_interval_regime": "since2018_hour_rule_for_aggregates"}
    return run, record, row
