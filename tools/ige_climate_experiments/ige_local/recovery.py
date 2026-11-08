"""Resolve explicit DWD replacement lineage after normal artifact verification."""
import gzip
import re

from .common import InputError, digest, read_json, safe_join

MUTABLE = {"job_id", "listing_bytes", "listing_sha256", "listing_last_modified"}


def replacement_links(original, plan, root):
    meta = plan["recovery"]
    if meta.get("schema") != "ige-dwd-pending-recovery-v1" or meta["original_plan_id"] != original["plan_id"]:
        raise InputError("Unsupported DWD recovery lineage")
    for key in ("start_utc_inclusive", "end_utc_exclusive", "catalog_id"):
        if plan[key] != original[key]:
            raise InputError("DWD recovery selection changed")
    old = {j["job_id"]:j for j in original["jobs"]}
    new = {j["job_id"]:j for j in plan["jobs"]}
    links = meta["job_bindings"]
    if (len(links) != len(new) or len({x["original_job_id"] for x in links}) != len(links)
            or {x["replacement_job_id"] for x in links} != set(new)):
        raise InputError("DWD recovery bindings incomplete or duplicated")
    wanted = {j["station_id"] for j in new.values()}
    if plan["stations"] != [s for s in original["stations"] if s["station_id"] in wanted]:
        raise InputError("DWD recovery station metadata changed")
    indexes = {}
    for source in meta["directory_indexes"]:
        if source["path"] != "sources/"+source["sha256"]+".html.gz":
            raise InputError("Invalid DWD recovery index path")
        body = safe_join(root,source["path"]).read_bytes()
        if digest(body) != source["stored_sha256"]:
            raise InputError("DWD recovery stored index hash mismatch")
        path = safe_join(root,source["path"])
        with gzip.open(path,"rb") as f:
            raw = f.read(8*1024*1024+1)
        if len(raw)>8*1024*1024 or digest(raw)!=source["sha256"] or source["url"] in indexes:
            raise InputError("DWD recovery index identity mismatch")
        records = {}
        for line in raw.decode("utf-8").splitlines():
            match = re.search(r'href="([^\"]+)".*?</a>\s+([\w:-]+\s+[\d:]+)\s+(\d+)\s*$',line)
            if match:
                records[match[1]] = (match[2],int(match[3]))
        indexes[source["url"]] = (source["sha256"],records)
    for link in links:
        a,b = old[link["original_job_id"]],new[link["replacement_job_id"]]
        if {k:v for k,v in a.items() if k not in MUTABLE}!={k:v for k,v in b.items() if k not in MUTABLE}:
            raise InputError("DWD recovery changed original job semantics")
        sha,records = indexes[b["url"].rsplit("/",1)[0]+"/"]
        if sha!=b["listing_sha256"] or records.get(b["filename"])!=(b["listing_last_modified"],b["listing_bytes"]):
            raise InputError("DWD replacement is not bound to its frozen index")
    return links


def resolve(plans, ledger):
    """Preserve native statuses; add separately verified replacement resolution."""
    by_id = {p["plan_id"]:(p,root) for p,root in plans if p.get("schema")=="ige-dwd-plan-v1"}
    anchors,parents,errors = {},set(),[]
    for pid,(plan,root) in by_id.items():
        if "recovery" not in plan:
            continue
        try:
            parent_id = plan["recovery"]["original_plan_id"]
            original,_ = by_id[parent_id]
            if "recovery" in original:
                raise InputError("Nested DWD recovery parent is unsupported")
            for link in replacement_links(original,plan,root):
                anchors[(pid,link["replacement_job_id"])] = (parent_id,link["original_job_id"])
            parents.add(parent_id)
        except (OSError,ValueError,KeyError,TypeError,EOFError) as exc:
            errors.append({"country":"DE","path":str(root/"plan.json"),"error":"Recovery lineage: "+str(exc)})
    verified = {}
    for row in ledger:
        key = (row["plan_id"],row["job_id"])
        anchor = anchors.get(key,key)
        if row["status"]=="VERIFIED_COMPLETE":
            verified.setdefault(anchor,key)
    extra = {"replaced_pending_jobs":0,"replaced_quarantined_jobs":0}
    for row in ledger:
        row["effective_status"] = row["status"]
        key = (row["plan_id"],row["job_id"])
        replacement = verified.get(anchors.get(key,key))
        if row["country"]=="DE" and row["status"] in ("PENDING","QUARANTINED") and replacement and replacement!=key:
            row["effective_status"] = "REPLACED_BY_VERIFIED_JOB"
            row["resolved_by_plan_id"],row["resolved_by_job_id"] = replacement
            extra["replaced_pending_jobs" if row["status"]=="PENDING" else "replaced_quarantined_jobs"] += 1
    resolution = {}
    for pid in sorted(parents):
        original,_ = by_id[pid]
        complete = sum((pid,j["job_id"]) in verified for j in original["jobs"])
        resolution[pid] = {"planned_original_jobs":len(original["jobs"]),"resolved_original_jobs":complete,
                           "remaining_jobs":len(original["jobs"])-complete,"all_jobs_resolved":complete==len(original["jobs"])}
    return resolution,extra,errors
