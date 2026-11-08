import gzip
import json
from pathlib import Path
import tempfile
import unittest

import test_switzerland_climate as native
import switzerland_repair as r
c = native.c


class RepairTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def save(self):
        return native.Contracts.save(self)

    def test_repair_regenerates_corrupt_part_and_preserves_original(self):
        plan,root,receipt = self.save()
        c.write_json(root/"plan.json",plan)
        job=plan["jobs"][0];raw,part,_=c.artifact_paths(job)
        good=gzip.decompress((root/part).read_bytes());bad=good.replace(b",",b"(",1)
        (root/part).write_bytes(gzip.compress(bad,mtime=0))
        # Reproduce the user case: corrupted structure already has a matching receipt hash.
        for artifact in receipt["artifacts"]:
            if artifact["path"]==part:artifact["sha256"]=c.digest((root/part).read_bytes())
        c.write_json(root/"receipts"/(job["job_id"]+".json"),receipt)
        self.assertTrue(c.receipt_is_complete(root,job))
        before=(root/raw).read_bytes();mtime=(root/raw).stat().st_mtime_ns
        result=r.repair(plan,self.out,job["job_id"])
        self.assertTrue(result["repaired"])
        self.assertEqual(gzip.decompress((root/part).read_bytes()),good)
        self.assertEqual((root/raw).read_bytes(),before)
        self.assertEqual((root/raw).stat().st_mtime_ns,mtime)
        self.assertTrue(c.receipt_is_complete(root,job))
        self.assertEqual(gzip.decompress((Path(result["backup_directory"])/"before"/part).read_bytes()),bad)

    def test_repeat_is_idempotent_and_offline(self):
        plan,root,_=self.save();c.write_json(root/"plan.json",plan)
        job=plan["jobs"][0];state={str(p):p.read_bytes() for p in root.rglob("*") if p.is_file()}
        result=r.repair(plan,self.out,job["job_id"])
        self.assertTrue(result["already_consistent"])
        self.assertFalse(result["repaired"])
        self.assertEqual(result["network_requests"],0)
        self.assertEqual({str(p):p.read_bytes() for p in root.rglob("*") if p.is_file()},state)

    def test_unpinned_original_is_rejected_without_rewriting(self):
        plan,root,_=self.save();c.write_json(root/"plan.json",plan)
        job=plan["jobs"][0];raw,part,_=c.artifact_paths(job)
        (root/raw).write_bytes(gzip.compress(b"changed",mtime=0));before=(root/part).read_bytes()
        with self.assertRaisesRegex(c.SourceError,"does not match"):
            r.repair(plan,self.out,job["job_id"])
        self.assertEqual((root/part).read_bytes(),before)

    def test_wrong_job_and_output_cannot_start_full_download(self):
        plan,root,_=self.save();c.write_json(root/"plan.json",plan)
        with self.assertRaises(c.SourceError):r.repair(plan,self.out,"0"*24)
        with self.assertRaises(c.SourceError):r.repair(plan,self.out/"wrong",plan["jobs"][0]["job_id"])


