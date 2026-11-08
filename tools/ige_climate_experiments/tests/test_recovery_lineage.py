import contextlib
import copy
import csv
import gzip
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ige_local.audit import audit
from ige_local.common import digest,source_audit_failed,write_json
from ige_local.recovery import resolve


def identify(p):
    p.pop("plan_id",None);p["plan_id"]=digest(p);return p


class LineageTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name);self.output=self.base/"Database/DE/downloaded"
        self.url="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/solar/"
        j={"station_id":"00001","group":"solar","tier":"row","filename":"stundenwerte_ST_00001_row.zip",
           "url":self.url+"stundenwerte_ST_00001_row.zip","listing_bytes":123,"listing_sha256":"0"*64,
           "listing_last_modified":"06-Nov-2026 08:35:11"}
        j["job_id"]=digest(j)[:24]
        self.original=identify({"schema":"ige-dwd-plan-v1","catalog_id":"frozen-original",
            "start_utc_inclusive":"2025-01-01T00:00:00Z","end_utc_exclusive":"2026-01-01T00:00:00Z",
            "stations":[{"station_id":"00001","latitude_deg":50,"longitude_deg":10,"elevation_m":100}],"jobs":[j]})
        self.child=copy.deepcopy(self.original);self.child.pop("plan_id")
        raw=b'<a href="stundenwerte_ST_00001_row.zip">stundenwerte_ST_00001_row.zip</a> 08-Nov-2026 08:35:11 124\n'
        stored=gzip.compress(raw,mtime=0);sha=digest(raw)
        self.index={"url":self.url,"sha256":sha,"stored_sha256":digest(stored),"path":"sources/"+sha+".html.gz"}
        new=self.child["jobs"][0];new.pop("job_id")
        new.update(listing_bytes=124,listing_sha256=sha,listing_last_modified="08-Nov-2026 08:35:11")
        new["job_id"]=digest(new)[:24]
        self.child["recovery"]={"schema":"ige-dwd-pending-recovery-v1","original_plan_id":self.original["plan_id"],
           "job_bindings":[{"original_job_id":j["job_id"],"replacement_job_id":new["job_id"]}],"directory_indexes":[self.index]}
        identify(self.child)
        self.parent_root=self.output/self.original["plan_id"][:20];self.child_root=self.output/self.child["plan_id"][:20]
        for p,root in ((self.original,self.parent_root),(self.child,self.child_root)):
            write_json(root/"plan.json",p)
        path=self.child_root/self.index["path"];path.parent.mkdir();path.write_bytes(stored)
        self.plans=[(self.original,self.parent_root),(self.child,self.child_root)]
        self.ledger=[{"country":"DE","plan_id":self.original["plan_id"],"job_id":j["job_id"],"status":"QUARANTINED","error":"corrupt old ZIP"},
                     {"country":"DE","plan_id":self.child["plan_id"],"job_id":new["job_id"],"status":"VERIFIED_COMPLETE","error":""}]

    def test_verified_child_resolves_but_preserves_original_error(self):
        resolution,extra,errors=resolve(self.plans,self.ledger)
        self.assertFalse(errors);self.assertEqual(extra["replaced_quarantined_jobs"],1)
        self.assertTrue(resolution[self.original["plan_id"]]["all_jobs_resolved"])
        self.assertEqual(self.ledger[0]["status"],"QUARANTINED")
        self.assertEqual(self.ledger[0]["effective_status"],"REPLACED_BY_VERIFIED_JOB")

    def test_failed_replacement_does_not_resolve_parent(self):
        self.ledger[1]["status"]="QUARANTINED"
        resolution,extra,errors=resolve(self.plans,self.ledger)
        self.assertEqual(extra["replaced_quarantined_jobs"],0)
        self.assertEqual(resolution[self.original["plan_id"]]["remaining_jobs"],1)

    def test_corrupt_index_cannot_clear_original_quarantine(self):
        (self.child_root/self.index["path"]).write_bytes(b"changed")
        resolution,extra,errors=resolve(self.plans,self.ledger)
        self.assertTrue(errors);self.assertEqual(extra["replaced_quarantined_jobs"],0)

    def test_wrong_station_cannot_clear_original_quarantine(self):
        self.child["jobs"][0]["station_id"]="00002"
        _,extra,errors=resolve(self.plans,self.ledger)
        self.assertTrue(errors);self.assertEqual(extra["replaced_quarantined_jobs"],0)

    def test_same_url_without_declared_lineage_is_not_replacement(self):
        self.child.pop("recovery")
        resolution,extra,errors=resolve(self.plans,self.ledger)
        self.assertFalse(resolution);self.assertEqual(extra["replaced_quarantined_jobs"],0)

    def test_a_third_verified_version_resolves_failed_child_and_parent(self):
        latest=copy.deepcopy(self.child);latest["revision_note"]="new retry";identify(latest)
        root=self.output/latest["plan_id"][:20]
        write_json(root/"plan.json",latest);path=root/self.index["path"];path.parent.mkdir()
        path.write_bytes((self.child_root/self.index["path"]).read_bytes())
        self.ledger[1]["status"]="QUARANTINED"
        self.ledger.append(self.ledger[1]|{"plan_id":latest["plan_id"],"status":"VERIFIED_COMPLETE"})
        resolution,extra,errors=resolve(self.plans+[(latest,root)],self.ledger)
        self.assertFalse(errors);self.assertEqual(extra["replaced_quarantined_jobs"],2)
        self.assertEqual(resolution[self.original["plan_id"]]["resolved_original_jobs"],1)

    def test_audit_separates_replaced_quarantine_and_active_errors(self):
        for plan,root in self.plans:
            job=plan["jobs"][0];jid=job["job_id"]
            values={"raw/"+jid+"/"+job["filename"]:b"SYNTHETIC NONWEATHER TEST BYTES",
                    "parts/"+jid+".csv.gz":gzip.compress(b"timestamp_utc,STATIONS_ID\n2025-01-01T00:00:00Z,00001\n",mtime=0),
                    "metadata/"+jid+".json":b"{}"}
            for name,body in values.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
            receipt={"status":"complete","job_sha256":digest(job),"artifacts":[{"path":k,"sha256":digest(v)} for k,v in values.items()]}
            write_json(root/"receipts"/(jid+".json"),receipt)
        p=self.parent_root/next(k for k in values if k.startswith("raw/")).replace(self.child["jobs"][0]["job_id"],self.original["jobs"][0]["job_id"])
        p.write_bytes(b"corrupted")
        cfg={"database":str(self.base/"Database"),"countries":["DE"],"results":str(self.base/"Results")}
        with contextlib.redirect_stdout(io.StringIO()):snapshot,summary=audit(cfg,self.base/"E0")
        stats=summary["countries"]["DE"]
        self.assertEqual(stats["quarantined_jobs"],1)
        self.assertEqual(stats["replaced_quarantined_jobs"],1)
        self.assertEqual(stats["unresolved_quarantined_jobs"],0)
        self.assertFalse(source_audit_failed(summary))
        self.assertEqual(len([j for run in snapshot["runs"] for j in run["jobs"]]),1)

    def test_unresolved_and_plan_errors_still_fail(self):
        self.assertTrue(source_audit_failed({"countries":{"DE":{"quarantined_jobs":2,"unresolved_quarantined_jobs":1}}}))
        self.assertTrue(source_audit_failed({"countries":{},"plan_errors":[{"error":"bad binding"}]}))
