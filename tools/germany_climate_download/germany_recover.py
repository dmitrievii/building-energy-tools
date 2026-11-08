#!/usr/bin/env python3
"""Recover unfinished DWD jobs into explicitly versioned supplementary plans.

The original plan, receipts and observations are read only. Requires the supplied
germany_climate.py (Python standard library only).
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
from pathlib import Path
import sys

import germany_climate as g

VERSION = "1.0.0"
RECOVERY_SCHEMA = "ige-dwd-pending-recovery-v1"
MUTABLE = {"job_id", "listing_bytes", "listing_sha256", "listing_last_modified"}


def _same_job(original, replacement):
    return ({k: v for k, v in original.items() if k not in MUTABLE}
            == {k: v for k, v in replacement.items() if k not in MUTABLE})


def validate_recovery(original, plan, root):
    """Check the one-to-one lineage; a different station/file cannot close a job."""
    meta = plan.get("recovery", {})
    if meta.get("schema") != RECOVERY_SCHEMA or meta.get("original_plan_id") != original["plan_id"]:
        raise g.SourceError("Recovery lineage does not match the original plan")
    for key in ("start_utc_inclusive", "end_utc_exclusive", "catalog_id"):
        if plan[key] != original[key]:
            raise g.SourceError("Recovery selection/catalogue changed: " + key)
    originals = {j["job_id"]: j for j in original["jobs"]}
    jobs = {j["job_id"]: j for j in plan["jobs"]}
    links = meta["job_bindings"]
    if (len(links) != len(jobs) or len({x["original_job_id"] for x in links}) != len(links)
            or {x["replacement_job_id"] for x in links} != set(jobs)):
        raise g.SourceError("Recovery job bindings are incomplete or duplicated")
    wanted = {j["station_id"] for j in jobs.values()}
    if plan["stations"] != [s for s in original["stations"] if s["station_id"] in wanted]:
        raise g.SourceError("Recovery station metadata differs from original catalogue")
    indexes = {}
    for source in meta["directory_indexes"]:
        name = source["path"]
        if name != "sources/" + source["sha256"] + ".html.gz":
            raise g.SourceError("Unsafe recovery index path")
        body = (Path(root)/name).read_bytes()
        if g.digest(body) != source["stored_sha256"] or g.digest(gzip.decompress(body)) != source["sha256"]:
            raise g.SourceError("Recovery directory index hash mismatch")
        if source["url"] in indexes:
            raise g.SourceError("Duplicate recovery directory URL")
        indexes[source["url"]] = source
    for link in links:
        old, new = originals[link["original_job_id"]], jobs[link["replacement_job_id"]]
        if not _same_job(old, new):
            raise g.SourceError("Recovery changed station, product, URL or original selection")
        url = new["url"].rsplit("/", 1)[0]+"/"
        source = indexes[url]
        _, sizes = g.listing(gzip.decompress((Path(root)/source["path"]).read_bytes()))
        record = sizes.get(new["filename"])
        if (not record or new["listing_sha256"] != source["sha256"]
                or any(new[k] != record[k] for k in ("listing_bytes", "listing_last_modified"))):
            raise g.SourceError("Recovery ZIP is not bound to its saved directory listing")
    return links


def inspect(original, output):
    output = Path(output).resolve()
    parent = g.run_root(output, original)
    if not (parent/"plan.json").is_file():
        raise g.SourceError("Original downloaded run not found: " + str(parent))
    if g.load_plan(parent/"plan.json")["plan_id"] != original["plan_id"]:
        raise g.SourceError("Original output plan mismatch")
    if (parent/".download.lock").exists():
        raise g.SourceError("Original downloader is locked; finish it before recovery")
    resolved = {}
    original_complete = 0
    for i, job in enumerate(original["jobs"], 1):
        if g.receipt_is_complete(parent, job):
            resolved[job["job_id"]] = {"plan_id": original["plan_id"], "job_id": job["job_id"]}
            original_complete += 1
        if i % 250 == 0:
            print("Verifying original receipts: %s/%s" % (i, len(original["jobs"])), flush=True)
    warnings = []
    recovery_plans = []
    # Discover only child runs with an explicit binding to this original plan.
    for path in sorted(output.glob("*/plan.json")):
        if path.parent.is_symlink():
            continue
        try:
            candidate = json.loads(path.read_bytes())
        except (OSError, ValueError):
            continue
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("recovery"), dict)
                or candidate["recovery"].get("original_plan_id") != original["plan_id"]):
            continue
        try:
            plan = g.load_plan(path)
            if path.parent != g.run_root(output, plan):
                raise g.SourceError("Recovery directory identity mismatch")
            if (path.parent/".download.lock").exists():
                raise g.SourceError("Recovery downloader is locked")
            links = validate_recovery(original, plan, path.parent)
            jobs = {j["job_id"]: j for j in plan["jobs"]}
            recovery_plans.append(plan["plan_id"])
            for link in links:
                old_id, new_id = link["original_job_id"], link["replacement_job_id"]
                if old_id not in resolved and g.receipt_is_complete(path.parent, jobs[new_id]):
                    resolved[old_id] = {"plan_id": plan["plan_id"], "job_id": new_id}
        except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
            warnings.append({"path": str(path), "error": type(exc).__name__+": "+str(exc)})
    pending = [j for j in original["jobs"] if j["job_id"] not in resolved]
    summary = {"original_plan_id": original["plan_id"], "planned_original_jobs": len(original["jobs"]),
               "completed_in_original_run": original_complete,
               "completed_via_recovery": len(resolved)-original_complete,
               "resolved_original_jobs": len(resolved), "remaining_jobs": len(pending),
               "all_jobs_resolved": not pending,
               "exact_original_frozen_run_complete": original_complete == len(original["jobs"]),
               "resolution_scope": "Original verified files plus explicitly versioned replacement ZIPs; original snapshot is never rewritten",
               "recovery_plan_ids": recovery_plans, "warnings": warnings,
               "meteorological_completeness_or_epw_admission_assessed": False}
    return pending, summary, resolved


def prepare(original, pending, output, client):
    """Refresh archive indexes only; retain original station/product definitions."""
    indexes = {}
    for url in sorted({j["url"].rsplit("/", 1)[0]+"/" for j in pending}):
        print("Freezing current DWD directory: "+url, flush=True)
        raw = client.get(url)
        _, sizes = g.listing(raw)
        sha = g.digest(raw)
        stored = gzip.compress(raw, mtime=0)
        source = {"url": url, "sha256": sha, "stored_sha256": g.digest(stored),
                  "path": "sources/"+sha+".html.gz", "compression": "gzip", "bytes": len(raw),
                  "retrieved_at_utc": g.now(), "role": "recovery_directory_listing"}
        indexes[url] = (source, stored, sizes)
    jobs, links = [], []
    for old in pending:
        source, _, sizes = indexes[old["url"].rsplit("/", 1)[0]+"/"]
        current = sizes.get(old["filename"])
        if not current:
            raise g.SourceError("Original archive filename is no longer listed; explicit source review required: "+old["filename"])
        job = {k: v for k, v in old.items() if k != "job_id"}
        job.update(current, listing_sha256=source["sha256"])
        job["job_id"] = g.digest(job)[:24]
        jobs.append(job)
        links.append({"original_job_id": old["job_id"], "replacement_job_id": job["job_id"],
                      "old_listing_bytes": old["listing_bytes"], "new_listing_bytes": job["listing_bytes"]})
    plan = copy.deepcopy({k: v for k, v in original.items() if k != "plan_id"})
    plan["jobs"] = jobs
    plan["estimated_zip_bytes"] = sum(j["listing_bytes"] for j in jobs)
    wanted = {j["station_id"] for j in jobs}
    plan["stations"] = [s for s in original["stations"] if s["station_id"] in wanted]
    source_records = [x[0] for x in indexes.values()]
    plan["sources"] += source_records
    plan["recovery"] = {"schema": RECOVERY_SCHEMA, "version": VERSION,
                        "created_at_utc": g.now(), "original_plan_id": original["plan_id"],
                        "station_metadata_origin": "Unchanged original catalogue; fresh ZIPs retain their own dated native metadata",
                        "archive_revision_policy": "Explicit new frozen listing for unfinished jobs; never weaken size/CRC/schema/hash checks",
                        "job_bindings": links, "directory_indexes": source_records}
    plan["plan_id"] = g.digest(plan)
    root = g.run_root(output, plan)
    if root.exists():
        raise g.SourceError("Recovery run already exists; no overwrite performed")
    root.mkdir(parents=True)
    for source, body, _ in indexes.values():
        g.atomic_write(root/source["path"], body)
    g.write_json(root/"plan.json", plan)
    validate_recovery(original, plan, root)
    print("New supplementary plan: "+str(root/"plan.json"), flush=True)
    return plan


def recover(original, output, client, *, status_only=False, max_jobs=None):
    if max_jobs is not None and max_jobs < 1:
        raise g.SourceError("max-jobs must be positive")
    output = Path(output).resolve()
    control = output/"recovery_control"/original["plan_id"][:20]
    with g.run_lock(control):
        pending, before, resolved = inspect(original, output)
        transfer = None
        if pending and not status_only:
            plan = prepare(original, pending, output, client)
            transfer = g.download(plan, output, client, max_jobs=max_jobs)
            _, after, resolved = inspect(original, output)
        else:
            after = before
            # No additional source request or rehash is needed for a completed run.
        after.update(checked_at_utc=g.now(), recovery_tool_version=VERSION,
                     attempted_this_invocation=transfer["attempted_this_invocation"] if transfer else 0,
                     failures_this_invocation=transfer["failures_this_invocation"] if transfer else [])
        g.write_json(control/"recovery_summary.json", after)
        g.write_json(control/"resolved_jobs.json", resolved)
        return after


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument("--plan", required=True, help="Original plan.json, not a supplementary plan")
    p.add_argument("--out", default="downloaded")
    p.add_argument("--status-only", action="store_true", help="Verify original and supplementary receipts without network requests")
    p.add_argument("--max-jobs", type=int)
    a = p.parse_args(argv)
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="backslashreplace")
        original = g.load_plan(a.plan)
        if "recovery" in original:
            raise g.SourceError("Pass the original plan, not a recovery plan")
        result = recover(original, a.out, g.Client(original["min_interval_seconds"]), status_only=a.status_only, max_jobs=a.max_jobs)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["all_jobs_resolved"] else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(type(exc).__name__+": "+str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
