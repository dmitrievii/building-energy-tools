import collections
import contextlib
import copy
import csv
import gzip
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import (ROOT, cells_ch_setup, cells_de_setup, config, files_unchanged_state,
                     make_at, publish_at, rewrite_csv)
from ige_local.common import (InputError, canonical, digest, distance, load_config, read_json,
                              safe_join, stamp, write_json)
from ige_local.audit import audit, discover, validate_plan
from ige_local.readers import (cells, insert_observation, prepare, qc_allowed, qc_stratum,
                               target_selection, timestamps)
import ige_local.pilot as pc


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="IGE User Folder Климат ")
        self.base = Path(self.tmp.name)
        self.config_path = config(self.base)
        self.cfg = load_config(self.config_path)

    def tearDown(self):
        pc.STATE = None
        self.tmp.cleanup()

    def make(self, **kwargs):
        return make_at(self.base/"Database", **kwargs)

    def audited(self, sub="audit"):
        with contextlib.redirect_stdout(io.StringIO()):
            return audit(self.cfg, self.base/sub)

    def prepared(self, snapshot, sub="prepare"):
        out = self.base/sub; out.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            path, info = prepare(snapshot, self.cfg, out)
        with gzip.open(path,"rt",encoding="utf-8") as f: data=json.load(f)
        return data, info, path

    def compute(self, snapshot, target="AT:100", variable="T", mode="primary", sub="prepare"):
        data, info, path = self.prepared(snapshot, sub)
        pc.initialize(str(path), info["dataset_sha256"])
        report=pc.calculate_job({"job_id": "test", "target": target, "variable": variable, "qc_mode": mode,
                                 "output": str(self.base/(sub+"_job"))})
        return report, data, info


class ConfigurationTests(WorkspaceTest):
    def modify(self, key, value):
        c=read_json(self.config_path); c[key]=value; write_json(self.config_path,c)

    def test_paths_relative_to_config_not_working_directory(self):
        self.assertEqual(self.cfg["database"],str(self.base/"Database"))
        self.assertEqual(self.cfg["results"],str(self.base/"ClimateExperiments"/"results"))

    def test_no_writes_below_database(self):
        self.modify("results","../Database/results")
        with self.assertRaises(InputError): load_config(self.config_path)

    def test_no_results_directory_containing_database(self):
        self.modify("results","..")
        with self.assertRaises(InputError): load_config(self.config_path)

    def test_unknown_config_typo_fails(self):
        self.modify("raduis_km",100)
        with self.assertRaises(InputError): load_config(self.config_path)

    def test_confirmatory_use_not_permitted(self):
        self.modify("role","C_CONFIRMATION")
        with self.assertRaises(InputError): load_config(self.config_path)

    def test_duplicate_profiles_fail_before_computation(self):
        self.modify("benchmark_workers",[1,1])
        with self.assertRaises(InputError): load_config(self.config_path)

    def test_unresolved_time_fails(self):
        with self.assertRaises(InputError): stamp("2025-01-01T00:00")

    def test_non_hour_window_fails(self):
        self.modify("windows",[{"start":"2025-01-01T00:30Z","end_exclusive":"2025-01-02T00:00Z"}])
        with self.assertRaises(InputError): load_config(self.config_path)

    def test_overlapping_windows_fail(self):
        w=read_json(self.config_path)["windows"]; self.modify("windows",w+w)
        with self.assertRaises(InputError): load_config(self.config_path)

    def test_leap_year_axis(self):
        self.cfg["windows"]=[{"start":"2024-01-01T00:00Z","end_exclusive":"2025-01-01T00:00Z"}]
        self.assertEqual(len(timestamps(self.cfg)),8784)

    def test_unsafe_cross_platform_paths(self):
        for path in ["../outside","/etc/passwd",r"C:\outside",r"..\outside",r"\\server\share\file"]:
            with self.subTest(path=path), self.assertRaises(InputError): safe_join(self.base,path)


class AuditTests(WorkspaceTest):
    def test_native_at_run_discovered_inside_repeated_at_folder(self):
        self.make(); s,r=self.audited()
        self.assertEqual(r["countries"]["AT"]["verified_jobs"],1)
        self.assertEqual(s["runs"][0]["planned_jobs"],1)

    def test_pending_is_not_corruption(self):
        self.make(days=2,complete_days=1); _,r=self.audited()
        self.assertEqual(r["countries"]["AT"],{"planned_jobs":2,"verified_jobs":1,"pending_jobs":1,"quarantined_jobs":0})

    def test_inputs_hashes_and_modification_times_unchanged(self):
        self.make(); before=files_unchanged_state(self.base/"Database"); self.audited()
        self.assertEqual(before,files_unchanged_state(self.base/"Database"))

    def test_hash_cache_reuses_only_unchanged_files(self):
        self.make(); _,first=self.audited(); _,second=self.audited("audit2")
        self.assertGreater(first["freshly_hashed_files"],0)
        self.assertEqual(second["freshly_hashed_files"],0)
        self.assertEqual(first["freshly_hashed_files"],second["cached_unchanged_files"])

    def test_force_rehash_reads_everything_again(self):
        self.make(); _,first=self.audited()
        with contextlib.redirect_stdout(io.StringIO()): _,second=audit(self.cfg,self.base/"audit2",rehash=True)
        self.assertEqual(first["freshly_hashed_files"],second["freshly_hashed_files"])
        self.assertEqual(second["cached_unchanged_files"],0)

    def test_changed_native_bytes_quarantine_whole_job(self):
        run,p=self.make(); r=read_json(next((run/"receipts").glob("*.json")))
        a=r["artifacts"][0]; (run/a["path"]).write_bytes(b"corrupt")
        s,report=self.audited(); self.assertEqual(report["countries"]["AT"]["quarantined_jobs"],1)
        self.assertEqual(s["runs"][0]["jobs"],[])

    def test_missing_csv_quarantines_job(self):
        run,p=self.make(); next((run/"csv").rglob("*.gz")).unlink()
        _,r=self.audited(); self.assertEqual(r["countries"]["AT"]["quarantined_jobs"],1)

    def test_receipt_job_binding_required(self):
        run,p=self.make(); rp=next((run/"receipts").glob("*.json")); r=read_json(rp)
        r["request_sha256"]="0"*64; write_json(rp,r)
        _,r=self.audited(); self.assertEqual(r["countries"]["AT"]["quarantined_jobs"],1)

    def test_extra_receipt_artifact_rejected(self):
        run,p=self.make(); rp=next((run/"receipts").glob("*.json")); r=read_json(rp)
        r["artifacts"].append(r["artifacts"][0]); write_json(rp,r)
        _,r=self.audited(); self.assertEqual(r["countries"]["AT"]["quarantined_jobs"],1)

    def test_plan_hash_tampering_rejected(self):
        run,p=self.make(); p["end"]="2025-02-01T00:00Z"; write_json(run/"plan.json",p)
        s,r=self.audited(); self.assertTrue(r["plan_errors"]); self.assertFalse(s["runs"])

    def test_metadata_body_hash_checked(self):
        run,p=self.make(); p["metadata_sha256"]="0"*64
        p["plan_id"]=digest({k:v for k,v in p.items() if k!="plan_id"})
        write_json(run/"plan.json",p)
        _,r=self.audited(); self.assertTrue(r["plan_errors"])

    def test_country_mismatch_rejected(self):
        _,p=self.make()
        with self.assertRaises(InputError): validate_plan(p,"DE")

    def test_late_download_not_added_to_existing_snapshot(self):
        run,p=self.make(days=2,complete_days=1); old,_=self.audited(); old_id=old["snapshot_id"]
        publish_at(run,p,p["jobs"][1]); new,_=self.audited("audit2")
        self.assertEqual(len(old["runs"][0]["jobs"]),1)
        self.assertEqual(len(new["runs"][0]["jobs"]),2)
        self.assertEqual(old["snapshot_id"],old_id)

    def test_planning_copy_not_double_counted(self):
        _,p=self.make(); write_json(self.base/"Database"/"AT"/"plan.json",p)
        s,r=self.audited(); self.assertEqual(len(s["runs"]),1)
        self.assertTrue(any(x["reason"]=="PLAN_WITHOUT_DOWNLOAD_RUN" for x in r["discovery_notes"]))

    def test_missing_countries_do_not_block_at(self):
        self.make(); self.cfg["countries"]=["AT","DE","CH"]; _,r=self.audited()
        self.assertEqual(r["countries"]["AT"]["verified_jobs"],1)
        self.assertEqual(r["countries"]["DE"]["planned_jobs"],0)
        self.assertEqual(len([n for n in r["discovery_notes"] if n["reason"]=="COUNTRY_DIRECTORY_MISSING"]),2)


class ReaderAndPolicyTests(WorkspaceTest):
    def test_partial_day_allowed_without_annual_gate(self):
        self.make(hours=6); s,_=self.audited(); d,info,_=self.prepared(s)
        self.assertEqual(len(d["selection"]["timestamps"]),6)
        self.assertGreater(info["retained_cells"],0)

    def test_target_family_and_combined_rows_excluded(self):
        def meta(m):
            m["stations"][0]["group_id"]=30; m["stations"][1]["group_id"]=30
            m["stations"][3]["type"]="COMBINED"
        self.make(metadata_transform=meta); s,_=self.audited(); d,_,_=self.prepared(s)
        ds=d["selection"]["donors"]["AT:100"]
        self.assertEqual([x["key"] for x in ds],["AT:102"])

    def test_manual_and_automatic_values_both_in_primary(self):
        for flag in ["10","11","12","20","21","22"]:
            self.assertTrue(qc_allowed("AT",flag,"primary",self.cfg))

    def test_unchecked_qc_is_sensitivity_not_incorrect(self):
        self.assertFalse(qc_allowed("AT","0","primary",self.cfg))
        self.assertTrue(qc_allowed("AT","0","sensitivity_all_published",self.cfg))
        self.assertEqual(qc_stratum("AT","0"),"unchecked")

    def test_unknown_qc_not_guessed_manual_or_bad(self):
        self.assertEqual(qc_stratum("CH","not_supplied"),"not_supplied")
        self.assertTrue(qc_allowed("DE","QN_9=3","primary",self.cfg))
        self.assertTrue(qc_allowed("AT","99","sensitivity_all_published",self.cfg))

    def test_only_explicit_native_rejects_excluded(self):
        self.cfg["rejected_native_qc"]["DE"]=["QN_9=3"]
        self.assertFalse(qc_allowed("DE","QN_9=3","primary",self.cfg))
        self.assertTrue(qc_allowed("DE","QN_9=4","primary",self.cfg))

    def test_de_station_pressure_not_sea_level(self):
        run,r,row,meta=cells_de_setup(); c=collections.Counter()
        parsed=list(cells("DE",run,r,row,stamp("2025-01-01T00:00Z"),meta,c))
        self.assertEqual(parsed[0][0],"p"); self.assertEqual(parsed[0][1]["value"],950.0)
        self.assertEqual(parsed[0][1]["qc"],"QN_8=3")

    def test_de_unknown_operator_not_silently_accepted(self):
        run,r,row,_=cells_de_setup(); c=collections.Counter()
        self.assertFalse(list(cells("DE",run,r,row,stamp("2025-01-01T00:00Z"),{},c)))
        self.assertEqual(c["unknown_or_ambiguous_operator_cells"],1)

    def test_wrong_pressure_unit_not_guessed(self):
        run,r,row,meta=cells_de_setup(); meta["parameter_history"][0]["Einheit"]="Pa"; c=collections.Counter()
        self.assertFalse(list(cells("DE",run,r,row,stamp("2025-01-01T00:00Z"),meta,c)))
        self.assertEqual(c["unit_mismatch_cells"],1)

    def test_dwd_blank_unit_uses_explicit_verified_product_contract(self):
        run,r,row,meta=cells_de_setup(); meta["parameter_history"][0]["Einheit"]=""; c=collections.Counter()
        parsed=list(cells("DE",run,r,row,stamp("2025-01-01T00:00Z"),meta,c))
        self.assertEqual(parsed[0][1]["value"],950.)
        self.assertEqual(parsed[0][1]["unit_provenance"],"DWD_hourly_pressure_v24.03_column_P0_hPa")

    def test_dwd_station_field_must_have_matching_native_reference(self):
        run,r,row,meta=cells_de_setup(); meta["parameter_history"][0]["Parameterbeschreibung"]="auf NN reduzierter Luftdruck"
        c=collections.Counter()
        self.assertFalse(list(cells("DE",run,r,row,stamp("2025-01-01T00:00Z"),meta,c)))
        self.assertEqual(c["station_pressure_reference_mismatch_cells"],1)

    def test_ch_no_fabricated_per_value_qc(self):
        run,r,row=cells_ch_setup(); c=collections.Counter()
        parsed=list(cells("CH",run,r,row,stamp("2025-01-01T00:00Z"),{},c))
        self.assertEqual({x[1]["qc"] for x in parsed},{"not_supplied"})

    def test_ch_legacy_support_preserved(self):
        run,r,row=cells_ch_setup(); row["hour_interval_regime"]="pre2018_synop_rule_for_aggregates"
        parsed=list(cells("CH",run,r,row,stamp("2017-01-01T00:00Z"),{},collections.Counter()))
        self.assertTrue(parsed); self.assertIn("pre2018",parsed[0][1]["operator"])

    def test_ch_wrong_support_regime_fails_closed(self):
        run,r,row=cells_ch_setup(); c=collections.Counter()
        self.assertFalse(list(cells("CH",run,r,row,stamp("2017-01-01T00:00Z"),{},c)))
        self.assertGreater(c["unknown_or_ambiguous_operator_cells"],0)

    def test_duplicate_timestamps_reject_whole_part(self):
        run,p=self.make(); rewrite_csv(run,p["jobs"][0],100,lambda rows: rows.insert(1,rows[0].copy()))
        s,_=self.audited(); d,info,_=self.prepared(s)
        self.assertTrue(info["read_failures"])
        self.assertFalse(any(r[0]=="AT:100" for r in d["observations"]))

    def test_source_mutation_after_audit_not_read(self):
        run,p=self.make(); s,_=self.audited()
        rewrite_csv(run,p["jobs"][0],100,lambda rows: rows[0].update(tl="999"))
        d,info,_=self.prepared(s); self.assertTrue(info["read_failures"])
        self.assertFalse(any(r[0]=="AT:100" for r in d["observations"]))

    def test_configuration_cannot_change_under_sealed_snapshot(self):
        self.make(); s,_=self.audited(); self.cfg["radius_km"]=200
        with self.assertRaises(InputError): self.prepared(s)

    def test_snapshot_tampering_detected(self):
        self.make(); s,_=self.audited(); s["runs"][0]["planned_jobs"]=0
        with self.assertRaises(InputError): self.prepared(s)

    def test_pressure_missing_does_not_remove_temperature(self):
        def edit(rows):
            for rr in rows.values():
                for row in rr: row["p"]=None
        self.make(transform=edit); s,_=self.audited(); report,_,_=self.compute(s)
        self.assertEqual(report["metrics"][0]["n"],6)

    def test_equal_priority_conflicts_are_excluded(self):
        data={}; conflicts={}; counts=collections.Counter(); slot=("x","t","T")
        a={"value":1.,"qc":"12","operator":"a","priority":0}; b=a|{"value":2.}
        insert_observation(data,conflicts,slot,a,counts); insert_observation(data,conflicts,slot,b,counts)
        self.assertNotIn(slot,data); self.assertIn(slot,conflicts)
        insert_observation(data,conflicts,slot,a,counts); self.assertNotIn(slot,data)

    def test_historical_over_recent_priority_not_a_fit(self):
        data={}; conflicts={}; counts=collections.Counter(); slot=("x","t","T")
        a={"value":1.,"qc":"12","operator":"a","priority":1}
        insert_observation(data,conflicts,slot,a,counts)
        insert_observation(data,conflicts,slot,a|{"priority":0,"value":2},counts)
        self.assertEqual(data[slot]["value"],2)

    def test_null_control_value_can_still_have_a_prediction(self):
        def edit(rows): rows["100"][0]["tl"]=None
        self.make(transform=edit); s,_=self.audited(); report,_,_=self.compute(s)
        m=report["metrics"][0]
        self.assertEqual(m["N_obs"],5); self.assertEqual(m["N_pred_among_obs"],5); self.assertEqual(m["N_pred_all"],6)
        self.assertEqual(m["coverage_method"],1)

    def test_one_donor_has_nn_but_not_multi_donor_idw(self):
        self.make(nsites=2); s,_=self.audited(); report,_,_=self.compute(s)
        self.assertEqual(report["metrics"][0]["n"],6)
        self.assertEqual(report["metrics"][1]["n"],0)
        self.assertEqual(report["metrics"][1]["N_obs"],6)

    def test_donor_families_not_double_counted(self):
        def meta(m): m["stations"][1]["group_id"]=90; m["stations"][2]["group_id"]=90
        self.make(nsites=3,metadata_transform=meta); s,_=self.audited(); report,_,_=self.compute(s)
        self.assertEqual(report["metrics"][1]["n"],0)

    def test_physical_diagnostic_does_not_silently_clip_raw_rh(self):
        def edit(rows):
            for rr in rows.values():
                for row in rr: row["rf"]=105
        self.make(transform=edit); s,_=self.audited(); report,_,_=self.compute(s,variable="RH")
        with (self.base/"prepare_job"/"predictions.csv").open(encoding="utf-8-sig") as f: rows=list(csv.DictReader(f))
        self.assertEqual(float(rows[0]["prediction"]),105)
        self.assertTrue(rows[0]["diagnostic_physics_flag"])

    def test_target_values_do_not_enter_spatial_prediction(self):
        run,p=self.make(); s,_=self.audited(); a,_,_=self.compute(s,sub="first")
        rewrite_csv(run,p["jobs"][0],100,lambda rows: [r.update(tl="-9998") for r in rows])
        s,_=self.audited("audit2"); b,_,_=self.compute(s,sub="second")
        def preds(sub):
            with (self.base/(sub+"_job")/"predictions.csv").open(encoding="utf-8-sig") as f:
                return [(r["timestamp_utc"],r["method"],r["prediction"],r["donors_json"]) for r in csv.DictReader(f)]
        self.assertEqual(preds("first"),preds("second"))
        self.assertNotEqual(a["metrics"][0]["MAE"],b["metrics"][0]["MAE"])


class NumericalAndReportingTests(unittest.TestCase):
    def test_independent_analytic_oracles(self): self.assertTrue(all(pc.numerical_oracles().values()))

    def test_distance_earth_quarter_circumference(self):
        self.assertAlmostEqual(distance({"lat":0,"lon":0},{"lat":0,"lon":90}),6371.0088*math.pi/2,places=7)

    def test_zero_denominator_undefined(self): self.assertIsNone(pc.ratio(0,0))

    def test_zero_scored_error_metrics_undefined(self):
        self.assertIsNone(pc.error_metrics([])["MAE"])

    def test_known_error_numbers(self):
        m=pc.error_metrics([-1.,3.]); self.assertEqual(m["MAE"],2); self.assertEqual(m["bias"],1)
        self.assertAlmostEqual(m["RMSE"],math.sqrt(5))

    def test_invalid_weight_inputs_rejected(self):
        for values,distances in [([],[]),([1],[1,2]),([float("nan")],[1]),([1],[-1])]:
            with self.subTest(values=values),self.assertRaises(InputError): pc.weighted_prediction(values,distances,.25)

    def test_constant_field_at_coincident_points(self):
        p,_=pc.weighted_prediction([7,7],[0,0],.25); self.assertEqual(p,7)

    def test_execution_failure_keeps_expected_denominator(self):
        j={"job_id":"x","target":"AT:100","variable":"T","qc_mode":"primary","expected_N_calendar":24,"expected_N_obs":20}
        r=pc.job_failure(j,"simulated worker failure")
        self.assertEqual(r["metrics"][0]["N_obs"],20)
        self.assertEqual(r["metrics"][0]["N_calendar"],24)
        self.assertEqual(r["metrics"][0]["coverage_method"],0)


class NativeFixtureTests(unittest.TestCase):
    fixtures = ROOT/"tests"/"fixtures"

    def first(self, name):
        with (self.fixtures/name).open(encoding="utf-8-sig",newline="") as f:
            return next(csv.DictReader(f))

    def test_fixture_fingerprints(self):
        p=read_json(self.fixtures/"provenance.json")
        for filename,sha in p["fixture_sha256"].items():
            with self.subTest(filename=filename): self.assertEqual(digest((self.fixtures/filename).read_bytes()),sha)

    def test_actual_at_values_and_automatic_flag_preserved(self):
        row=self.first("at_16413_20250101.csv")
        run={"parameter_definitions":read_json(self.fixtures/"at_parameter_definitions.json")}
        parsed=dict(cells("AT",run,{"job":{}},row,stamp(row["timestamp_utc"]),{},collections.Counter()))
        self.assertEqual(parsed["T"]["value"],-4.4)
        self.assertEqual(parsed["T"]["qc"],"10")
        self.assertEqual(parsed["T"]["qc_stratum"],"automatic_state_unknown")
        self.assertEqual(parsed["p"]["value"],987.1)

    def test_actual_dwd_temperature_and_native_qn(self):
        row=self.first("de_01048_20250601.csv")
        meta=read_json(self.fixtures/"de_air_temperature_metadata.json")
        parsed=dict(cells("DE",{}, {"job":{"group":"air_temperature"}},row,stamp(row["timestamp_utc"]),meta,collections.Counter()))
        self.assertEqual(parsed["T"]["value"],18.8)
        self.assertEqual(parsed["RH"]["value"],80.0)
        self.assertEqual(parsed["T"]["qc"],"QN_9=3")

    def test_actual_dwd_station_and_sea_pressure_not_swapped(self):
        row=self.first("de_pressure_01048_20250601.csv")
        meta=read_json(self.fixtures/"de_pressure_metadata.json")
        parsed=dict(cells("DE",{}, {"job":{"group":"pressure"}},row,stamp(row["timestamp_utc"]),meta,collections.Counter()))
        self.assertEqual(parsed["p"]["value"],989.2)
        self.assertNotEqual(parsed["p"]["value"],float(row["P"]))
        self.assertEqual(parsed["p"]["native_parameter"],"P0")

    def test_actual_meteoswiss_values_with_no_invented_qc(self):
        run,record,_=cells_ch_setup(); row=self.first("ch_BER_20250601.csv")
        parsed=dict(cells("CH",run,record,row,stamp(row["timestamp_utc"]),{},collections.Counter()))
        self.assertEqual(parsed["T"]["value"],16.9)
        self.assertEqual(parsed["RH"]["value"],93.1)
        self.assertEqual(parsed["p"]["value"],955.9)
        self.assertEqual(parsed["p"]["qc"],"not_supplied")

    def test_each_native_fixture_retains_24_rows(self):
        for path in self.fixtures.glob("*.csv"):
            with path.open(encoding="utf-8-sig",newline="") as f:
                self.assertEqual(len(list(csv.DictReader(f))),24)


class CommandLineIntegrationTests(WorkspaceTest):
    def invoke(self, workers=(1,2), countries=("AT","DE","CH")):
        c=read_json(self.config_path); c["benchmark_workers"]=list(workers); c["countries"]=list(countries)
        write_json(self.config_path,c)
        result=subprocess.run([sys.executable,str(ROOT/"ige_experiments.py"),"run","--config",str(self.config_path)],
                              cwd=self.base,capture_output=True,text=True,encoding="utf-8",timeout=60)
        reports=sorted((self.base/"ClimateExperiments"/"results").glob("*/summary.json"))
        return result,read_json(reports[-1]) if reports else None

    def test_serial_and_spawn_parallel_predictions_identical(self):
        self.make(); before=files_unchanged_state(self.base/"Database")
        result,report=self.invoke()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(report["E10"]["serial_parallel_prediction_hashes_match"])
        self.assertEqual([p["failed_jobs"] for p in report["E10"]["profile_sizes"]],[0,0])
        self.assertEqual(before,files_unchanged_state(self.base/"Database"))
        self.assertFalse(report["full_E10_legacy_replay_complete"])
        self.assertEqual(report["E10"]["quality_axes"]["independent_accuracy"],"NOT_ASSESSED; DEVELOPMENT_DESCRIPTIVE_ERRORS_ONLY")

    def test_empty_database_never_reports_successful_pilot(self):
        result,report=self.invoke(workers=(1,))
        self.assertEqual(result.returncode,2)
        self.assertEqual(report["E10"]["scored_method_case_pairs_first_profile"],0)

    def test_limited_budget_is_explicit_unresolved(self):
        self.make(); c=read_json(self.config_path); c["worker_rss_budget_bytes"]=1; write_json(self.config_path,c)
        result,report=self.invoke(workers=(1,))
        self.assertEqual(result.returncode,2)
        self.assertGreater(report["E10"]["profile_sizes"][0]["budget_exceeded_jobs"],0)

    def test_new_attempt_reuses_hash_cache_and_creates_new_report(self):
        self.make(); first,r1=self.invoke(workers=(1,)); second,r2=self.invoke(workers=(1,))
        self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        self.assertEqual(second.returncode,0,second.stdout+second.stderr)
        self.assertNotEqual(r1["run_directory"],r2["run_directory"])
        self.assertEqual(r2["E0"]["freshly_hashed_files"],0)
        self.assertIsNone(r2["E10"]["serial_parallel_prediction_hashes_match"])


if __name__ == "__main__":
    unittest.main()
