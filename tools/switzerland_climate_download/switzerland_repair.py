#!/usr/bin/env python3
"""Rebuild one derived CH job from its checksum-pinned saved original, offline."""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
import zlib

import switzerland_climate as c

VERSION = "1.0.0"


def repair(plan, output, job_id):
    jobs = [j for j in plan["jobs"] if j["job_id"] == job_id]
    if len(jobs) != 1:
        raise c.SourceError("Job ID must identify exactly one original plan job")
    job = jobs[0]
    root = c.run_root(output, plan).resolve()
    if not (root/"plan.json").is_file() or c.load_plan(root/"plan.json")["plan_id"] != plan["plan_id"]:
        raise c.SourceError("Matching original downloaded run not found")
    raw_path, part_path, meta_path = c.artifact_paths(job)
    receipt_path = "receipts/"+job_id+".json"
    with c.run_lock(root):
        raw = c.saved_original(root, job)
        if raw is None:
            raise c.SourceError("Saved original does not match frozen provider SHA256; no repair performed")
        original = root/raw_path
        original_state = (c.digest(original.read_bytes()), original.stat().st_mtime_ns)
        with tempfile.TemporaryDirectory(prefix=".repair-stage-", dir=root) as folder:
            stage = Path(folder)
            receipt = c.save_job(stage, plan, job, raw, reprocessed_original=True)
            expected = gzip.decompress((stage/part_path).read_bytes())
            reader = csv.reader(io.StringIO(expected.decode("utf-8-sig"), newline=""))
            columns = next(reader)
            rows = 0
            for row in reader:
                if len(row) != len(columns):
                    raise c.SourceError("Regenerated CSV row width mismatch")
                rows += 1
            if rows != receipt["source_information"]["selected_rows"] or not c.receipt_is_complete(stage, job):
                raise c.SourceError("Staged derivative verification failed")
            try:
                previous = gzip.decompress((root/part_path).read_bytes())
            except (OSError, EOFError, ValueError, zlib.error):
                previous = None
            result = {"plan_id":plan["plan_id"], "job_id":job_id, "station_id":job["station_id"],
                      "selected_rows":rows, "columns":len(columns), "provider_sha256":c.digest(raw),
                      "network_requests":0, "original_preserved":True,
                      "derived_plain_sha256":c.digest(expected), "repair_tool_version":VERSION}
            if previous == expected and c.receipt_is_complete(root, job):
                return result | {"repaired":False, "already_consistent":True}
            repair_id = c.now().replace(":", "").replace("+", "_")+"_"+uuid.uuid4().hex[:8]
            history = root/"repair_history"/job_id/repair_id
            history.mkdir(parents=True)
            before = []
            for relative in (part_path, meta_path, receipt_path):
                p = root/relative
                if p.is_file():
                    saved = history/"before"/relative
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, saved)
                    before.append({"path":relative,"sha256":c.digest(p.read_bytes())})
            manifest = result | {"status":"PREPARED", "repair_id":repair_id,
                                "before":before, "source_url":job["url"],
                                "reason":"Rebuild derivatives from the unchanged frozen-provider original"}
            if previous is not None:
                manifest["previous_plain_sha256"] = c.digest(previous)
                if len(previous) == len(expected):
                    manifest["different_plain_bytes"] = sum(a != b for a,b in zip(previous,expected))
            c.write_json(history/"repair.json", manifest)
            # Write the complete receipt last. An interrupted update cannot pass old hashes.
            for relative in (part_path, meta_path):
                c.atomic_write(root/relative, (stage/relative).read_bytes())
            for artifact in receipt["artifacts"]:
                if artifact["path"] == raw_path:
                    artifact["sha256"] = original_state[0]
            receipt["repair"] = {"repair_id":repair_id,"backup":str(history.relative_to(root)),
                                 "original_preserved":True,"repair_tool_version":VERSION}
            c.write_json(root/receipt_path, receipt)
            if not c.receipt_is_complete(root, job):
                raise c.SourceError("Repaired receipt verification failed; backup is in "+str(history))
            if (c.digest(original.read_bytes()), original.stat().st_mtime_ns) != original_state:
                raise c.SourceError("Saved original changed during repair")
            manifest["status"] = "COMPLETE"
            manifest["after"] = receipt["artifacts"]
            c.write_json(history/"repair.json", manifest)
            return result | {"repaired":True,"already_consistent":False,"backup_directory":str(history),
                             "different_plain_bytes":manifest.get("different_plain_bytes")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--out", default="downloaded")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = repair(c.load_plan(args.plan), args.out, args.job_id)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(type(exc).__name__+": "+str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
