"""Recovery must preserve original bytes and keep source revisions explicit."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_germany_climate import ROOT, RAW, edit_first_value, edit_product, fixture_plan

import germany_climate as g
import germany_recover as r


class CurrentProvider:
    def __init__(self, plan, overrides=None, broken_size=False, missing_filename=False):
        self.calls = []
        self.values = {}
        indexes = {}
        for j in plan["jobs"]:
            raw = (overrides or {}).get(j["group"], RAW[j["group"]])
            self.values[j["url"]] = raw
            url = j["url"].rsplit("/", 1)[0]+"/"
            name = j["filename"] if not missing_filename else "not_the_original.zip"
            indexes.setdefault(url, []).append('<a href="%s">%s</a> 08-Nov-2026 08:35:11 %s' % (name, name, len(raw)+int(broken_size)))
        self.values.update({url: "\n".join(lines).encode() for url, lines in indexes.items()})

    def get(self, url):
        self.calls.append(url)
        value = self.values[url]
        if isinstance(value, Exception):
            raise value
        return value


def state(folder):
    return {str(p.relative_to(folder)): (g.digest(p.read_bytes()), p.stat().st_mtime_ns)
            for p in folder.rglob("*") if p.is_file()}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)/"downloaded"
        self.plan = fixture_plan(["pressure", "solar"])
        self.root = g.run_root(self.output, self.plan)
        self.root.mkdir(parents=True)
        g.write_json(self.root/"plan.json", self.plan)
        self.pressure = next(j for j in self.plan["jobs"] if j["group"] == "pressure")
        g.save_job(self.root, self.plan, self.pressure, RAW["pressure"])

    def test_only_pending_is_fetched_and_parent_unchanged(self):
        before = state(self.root)
        changed = edit_first_value(RAW["solar"], "FG_LBERG", "123.456")
        client = CurrentProvider(self.plan, {"solar": changed})
        result = r.recover(self.plan, self.output, client)
        self.assertEqual((result["completed_in_original_run"], result["completed_via_recovery"]), (1, 1))
        self.assertTrue(result["all_jobs_resolved"])
        self.assertFalse(result["exact_original_frozen_run_complete"])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(state(self.root), before)
        path = self.output/result["recovery_plan_ids"][0][:20]/"plan.json"
        new = g.load_plan(path)
        self.assertEqual(len(new["jobs"]), 1)
        self.assertEqual(new["jobs"][0]["listing_bytes"], len(changed))
        self.assertNotEqual(new["plan_id"], self.plan["plan_id"])
        self.assertEqual(new["recovery"]["original_plan_id"], self.plan["plan_id"])

    def test_completed_recovery_resume_has_no_network_requests(self):
        r.recover(self.plan, self.output, CurrentProvider(self.plan))
        client = CurrentProvider(self.plan)
        result = r.recover(self.plan, self.output, client)
        self.assertEqual(client.calls, [])
        self.assertEqual(result["attempted_this_invocation"], 0)
        self.assertEqual(result["resolved_original_jobs"], 2)

    def test_partial_recovery_next_run_fetches_only_remaining(self):
        self.plan = fixture_plan(["dew_point", "pressure", "solar"])
        self.root = g.run_root(self.output, self.plan)
        self.root.mkdir(parents=True)
        g.write_json(self.root/"plan.json", self.plan)
        pressure = next(j for j in self.plan["jobs"] if j["group"] == "pressure")
        g.save_job(self.root, self.plan, pressure, RAW["pressure"])
        one = r.recover(self.plan, self.output, CurrentProvider(self.plan), max_jobs=1)
        self.assertEqual(one["remaining_jobs"], 1)
        client = CurrentProvider(self.plan)
        two = r.recover(self.plan, self.output, client)
        self.assertTrue(two["all_jobs_resolved"])
        self.assertEqual(two["resolved_original_jobs"], 3)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(two["recovery_plan_ids"]), 2)

    def test_network_failure_can_be_retried_without_losing_other_results(self):
        client = CurrentProvider(self.plan)
        solar = next(j for j in self.plan["jobs"] if j["group"] == "solar")
        client.values[solar["url"]] = ConnectionError("synthetic network error")
        a = r.recover(self.plan, self.output, client)
        self.assertEqual(len(a["failures_this_invocation"]), 1)
        self.assertEqual(a["remaining_jobs"], 1)
        b = r.recover(self.plan, self.output, CurrentProvider(self.plan))
        self.assertTrue(b["all_jobs_resolved"])

    def test_changed_index_after_planning_still_fails_strict_size_check(self):
        result = r.recover(self.plan, self.output, CurrentProvider(self.plan, broken_size=True))
        self.assertFalse(result["all_jobs_resolved"])
        self.assertIn("ZIP size differs", result["failures_this_invocation"][0]["error"])

    def test_malformed_product_is_not_silently_skipped(self):
        broken = edit_product(RAW["solar"], lambda lines: lines[:1]+[lines[1].rsplit(";", 1)[0]]+lines[2:])
        result = r.recover(self.plan, self.output, CurrentProvider(self.plan, {"solar": broken}))
        self.assertEqual(result["remaining_jobs"], 1)
        self.assertIn("Truncated/misaligned", result["failures_this_invocation"][0]["error"])

    def test_missing_current_filename_is_not_guessed(self):
        before = state(self.root)
        with self.assertRaisesRegex(g.SourceError, "no longer listed"):
            r.recover(self.plan, self.output, CurrentProvider(self.plan, missing_filename=True))
        self.assertEqual(state(self.root), before)

    def test_tampered_supplementary_zip_is_not_counted(self):
        result = r.recover(self.plan, self.output, CurrentProvider(self.plan))
        root = self.output/result["recovery_plan_ids"][0][:20]
        p = g.load_plan(root/"plan.json")
        (root/g.artifact_paths(p["jobs"][0])[0]).write_bytes(b"corrupt")
        pending, report, _ = r.inspect(self.plan, self.output)
        self.assertEqual(len(pending), 1)
        self.assertEqual(report["completed_via_recovery"], 0)

    def test_tampered_source_index_is_not_counted(self):
        result = r.recover(self.plan, self.output, CurrentProvider(self.plan))
        root = self.output/result["recovery_plan_ids"][0][:20]
        p = g.load_plan(root/"plan.json")
        (root/p["recovery"]["directory_indexes"][0]["path"]).write_bytes(b"corrupt")
        _, report, _ = r.inspect(self.plan, self.output)
        self.assertEqual(report["remaining_jobs"], 1)
        self.assertEqual(len(report["warnings"]), 1)

    def test_wrong_original_job_binding_is_rejected(self):
        result = r.recover(self.plan, self.output, CurrentProvider(self.plan))
        root = self.output/result["recovery_plan_ids"][0][:20]
        p = g.load_plan(root/"plan.json")
        p["recovery"]["job_bindings"][0]["original_job_id"] = self.pressure["job_id"]
        p["plan_id"] = g.digest({k: v for k, v in p.items() if k != "plan_id"})
        new_root = g.run_root(self.output, p)
        root.rename(new_root)
        g.write_json(new_root/"plan.json", p)
        _, report, _ = r.inspect(self.plan, self.output)
        self.assertEqual(report["remaining_jobs"], 1)
        self.assertEqual(report["completed_via_recovery"], 0)

    def test_missing_original_run_does_not_start_full_download(self):
        client = CurrentProvider(self.plan)
        with self.assertRaisesRegex(g.SourceError, "run not found"):
            r.recover(self.plan, self.output/"wrong", client)
        self.assertFalse(client.calls)

    def test_original_lock_blocks_recovery(self):
        (self.root/".download.lock").write_text("test")
        client = CurrentProvider(self.plan)
        with self.assertRaisesRegex(g.SourceError, "locked"):
            r.recover(self.plan, self.output, client)
        self.assertFalse(client.calls)

    def test_status_only_never_fetches(self):
        client = CurrentProvider(self.plan)
        report = r.recover(self.plan, self.output, client, status_only=True)
        self.assertEqual(report["remaining_jobs"], 1)
        self.assertFalse(client.calls)

    def test_invalid_job_limit_does_not_fetch_or_create_new_plan(self):
        client = CurrentProvider(self.plan)
        with self.assertRaisesRegex(g.SourceError, "must be positive"):
            r.recover(self.plan, self.output, client, max_jobs=0)
        self.assertFalse(client.calls)
        self.assertEqual(len(list(self.output.glob("*/plan.json"))), 1)

    def test_unrelated_invalid_plan_shape_does_not_block_recovery(self):
        folder = self.output/"unrelated"
        folder.mkdir()
        (folder/"plan.json").write_text("[]")
        client = CurrentProvider(self.plan)
        report = r.recover(self.plan, self.output, client, status_only=True)
        self.assertEqual(report["remaining_jobs"], 1)
        self.assertFalse(client.calls)

    def test_cli_status_with_spaces_and_cyrillic_path(self):
        folder = Path(self.tmp.name)/"Планы с пробелами"
        folder.mkdir()
        path = folder/"plan.json"
        g.write_json(path, self.plan)
        result = subprocess.run([sys.executable, str(ROOT/"germany_recover.py"), "--plan", str(path),
                                 "--out", str(self.output), "--status-only"], capture_output=True,
                                encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["remaining_jobs"], 1)


if __name__ == "__main__":
    unittest.main()
