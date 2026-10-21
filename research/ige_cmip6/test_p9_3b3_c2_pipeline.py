"""C2 complete denominators, sealed scoring and source-blind common donors."""
import copy
import dataclasses
import datetime as dt
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from p9_3b3_at_de_ch_validation import empty_observations,sha_file
from p9_3b3_c2_projection import MODES
from p9_3b3_c2_run import (choose_common_donor,control_integrity,load_protocol,
    project_modes,run,summarize)
from p9_3b3_c2_stations import expected_members,matched_errors,score_sealed,station_diagnostic,structure
from p9_3b3_generator import ThermoDonor
from test_p9_3b3_c2_projection import fixture


class C2ProtocolAndDonors(unittest.TestCase):
    def test_all_40_scientific_controls_are_unchanged(self):
        self.assertEqual(len(control_integrity(load_protocol())),40)

    def test_protocol_rejects_fitted_weights_and_new_country_or_holdout_claim(self):
        p=load_protocol()
        variants=[]
        for key,value in (("countries",["AT","DE","CH","FR"]),
                          ("station_role","NEW_HOLDOUT"),("pressure_is_optimization_variable",True)):
            q=copy.deepcopy(p);q[key]=value;variants.append(q)
        q=copy.deepcopy(p);q["metric"]["q_scale_gkg"]=.7;variants.append(q)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"protocol.json"
            for bad in variants:
                path.write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError,"PROTOCOL_DRIFT"):load_protocol(path)

    def test_failed_strict_day_uses_lexicographic_eligible_donor_without_correction_ranking(self):
        T,q,t,p=fixture(4)
        donors=[ThermoDonor(d,T,q,p,wet) for d,wet in (("2020-02-01",True),("2019-02-03",True),
            ("2019-02-01",False),("2019-08-01",True))]
        selected=choose_common_donor(t,donors,True,{"status":"UNRESOLVED"})
        self.assertEqual(selected.date,"2019-02-03")
        exact=choose_common_donor(t,donors,True,{"status":"EXACT_DEFINED_OPERATORS","donor_date":"2020-02-01"})
        self.assertEqual(exact.date,"2020-02-01")
        self.assertIsNone(choose_common_donor(t,[],True,{"status":"UNRESOLVED"}))

    def test_all_modes_preserve_same_strict_state_and_target_pressure(self):
        T,q,t,p=fixture(4)
        d=ThermoDonor("2019-02-01",T,q,p,False)
        strict={"status":"EXACT_DEFINED_OPERATORS","T_K":list(T),"q_kgkg":list(q),"p_Pa":list(p.values_Pa)}
        rows=project_modes(t,d,strict,load_protocol(),"TARGET_DAY_EXTERNAL_FIXED")
        self.assertEqual([r["mode"] for r in rows],list(MODES))
        self.assertTrue(all(r["status"]=="EXACT_SOURCE_PRESERVED" for r in rows))
        self.assertEqual(len({r["pressure_reference"]["fingerprint"] for r in rows}),1)

    def test_missing_donor_is_retained_in_every_mode_and_summary(self):
        _,_,t,_=fixture()
        rows=project_modes(t,None,{"status":"UNRESOLVED"},load_protocol(),"TARGET_DAY_EXTERNAL_FIXED")
        self.assertEqual(len(rows),3)
        summary=summarize(rows)
        self.assertEqual(summary["counts"],{"SOURCE_BLOCKED_NO_ELIGIBLE_DONOR":3})
        self.assertEqual(summary["huss"]["count"],0)

    def test_report_directory_cannot_overwrite_old_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"report"
            r=run(out)
            self.assertFalse(r["source_values_modified"])
            self.assertFalse(r["new_independent_holdout_opened"])
            with self.assertRaises(FileExistsError):run(out)


class C2SealedScoring(unittest.TestCase):
    def sealed(self,temp,members=None):
        root=Path(temp)
        obs={c:empty_observations(c) for c in ("AT","DE","CH")}
        for source in obs.values():source["time_support"]="HOURLY_NODE"
        obs["AT"]["cells"]["winter"]["T2m"]={"2021-02-01T00:00":0.,"2021-02-01T01:00":0.}
        o=root/"obs.json";o.write_text(json.dumps(obs))
        p=root/"pred.json";p.write_text(json.dumps({"members":members or []}))
        return {"frozen_before_scoring":True,"countries":["AT","DE","CH"],
            "cohort_role":"REVEALED_2021_RECONSTRUCTION_DIAGNOSTIC_NOT_NEW_HOLDOUT",
            "algorithm_commit":"a"*40,"predictions_path":str(p),"predictions_sha256":sha_file(p),
            "observations_path":str(o),"observations_sha256":sha_file(o)}

    def row(self,T):return {"T2m":T,"RH2m":50.,"p_hPa":970.,"e_hPa":5.,"q_gkg":3.}

    def test_missing_sources_and_generations_remain_in_all_630_cells(self):
        self.assertEqual(len(expected_members()),126)
        with tempfile.TemporaryDirectory() as tmp:r=score_sealed(self.sealed(tmp))
        self.assertEqual(len(r["cells"]),630)
        self.assertEqual(r["cell_status_counts"],{"SOURCE_OR_GENERATION_COVERAGE_BLOCKED":630})
        self.assertFalse(r["pressure_model_qualified"])

    def test_paired_accuracy_uses_identical_hours_and_reports_new_coverage(self):
        members=[{"country":"AT","period":"winter","seed":7313,"method":"B3_STRICT",
                  "hourly":{"2021-02-01T01:00":self.row(3.)}},
                 {"country":"AT","period":"winter","seed":7313,"method":"BOTH_SOFT",
                  "hourly":{"2021-02-01T00:00":self.row(100.),"2021-02-01T01:00":self.row(1.)}}]
        with tempfile.TemporaryDirectory() as tmp:r=score_sealed(self.sealed(tmp,members))
        paired=next(c for c in r["paired_comparisons"] if c["country"]=="AT" and c["period"]=="winter"
            and c["seed"]==7313 and c["variable"]=="T2m" and c["mode"]=="BOTH_SOFT")
        self.assertEqual(paired["common_hours"],1)
        self.assertEqual(paired["candidate_only_hours"],1)
        self.assertEqual(paired["delta_MAE"],-2.)

    def test_changed_sealed_bytes_and_duplicate_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=self.sealed(tmp)
            Path(manifest["predictions_path"]).write_text('{}')
            with self.assertRaisesRegex(ValueError,"DIGEST"):score_sealed(manifest)
            m={"country":"AT","period":"winter","seed":7313,"method":"B3_STRICT","hourly":{}}
            with self.assertRaisesRegex(ValueError,"DUPLICATE"):score_sealed(self.sealed(tmp,[m,m]))

    def test_unsealed_and_out_of_scope_predictions_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=self.sealed(tmp);manifest["frozen_before_scoring"]=False
            with self.assertRaisesRegex(ValueError,"UNFROZEN"):score_sealed(manifest)
            m={"country":"AT","period":"winter","seed":7313,"method":"B3_STRICT",
                "hourly":{"2021-03-01T00:00":self.row(0)}}
            with self.assertRaisesRegex(ValueError,"OUTSIDE"):score_sealed(self.sealed(tmp,[m]))

    def test_preceding_hour_proxy_keeps_first_hour_missing_and_never_fits_lag(self):
        truth={"2021-02-01T00:00":0.,"2021-02-01T01:00":5.}
        hourly={"2021-02-01T00:00":self.row(2),"2021-02-01T01:00":self.row(10)}
        errors=matched_errors(hourly,truth,"T2m","PRECEDING_HOUR_MEAN_END_STAMP",list(truth))
        self.assertEqual(errors,{"2021-02-01T01:00":1.})

    def test_structure_spells_do_not_bridge_generation_gaps(self):
        h={s:self.row(1) for s in ("2021-02-01T00:00","2021-02-01T01:00","2021-02-01T03:00")}
        for row in h.values():row["RH2m"]=95.
        r=structure(h)
        self.assertEqual(r["RH_ge90_spell_lengths_hours"],[2,1])

    def test_station_pipeline_seals_before_scoring_with_all_126_expected_members(self):
        from p9_3b3_c2_stations import _rich_nodes
        def era(cache,lat,lon,start,end):
            day=dt.date.fromisoformat(start);last=dt.date.fromisoformat(end);days=[]
            while day<=last:
                vectors=[{"temperature_2m":10+5*math.sin(i*math.pi/12),
                    "dew_point_2m":5+5*math.sin(i*math.pi/12),"surface_pressure":970.,"precipitation":0.} for i in range(24)]
                days.append(SimpleNamespace(date=day,vectors=vectors,original_sha256="a"*64));day+=dt.timedelta(days=1)
            return days,{"selected_cell_latitude":lat,"selected_cell_longitude":lon}
        def strict(targets,donors,seed,wet,policy,pressure_by_date):
            rows=[]
            for t in targets:
                eligible=sorted((d for d in donors if d.date[5:7]==t.date[5:7]),key=lambda d:d.date)
                d=eligible[0]
                rows.append({"date":t.date,"status":"EXACT_DEFINED_OPERATORS","donor_date":d.date,
                    "T_K":list(d.T_K),"q_kgkg":list(d.q_kgkg),"p_Pa":list(pressure_by_date[t.date].values_Pa),
                    "diagnostics":{"RH_source_pct":[50.]*24,"e_Pa":[500.]*24}})
            return rows,{"total":len(rows),"counts":{"EXACT_DEFINED_OPERATORS":len(rows)}}
        def pre(cache,path):
            obs={c:empty_observations(c) for c in ("AT","DE","CH")}
            private=cache.root/"obs.json";private.write_text(json.dumps(obs))
            summary={"cells":{c:{"site":o["site"]} for c,o in obs.items()}}
            Path(path).write_text(json.dumps(summary))
            return private,summary
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"out";out.mkdir()
            with patch("p9_3b3_c2_stations.preflight",side_effect=pre), \
                 patch("p9_3b3_c2_stations._era5",side_effect=era), \
                 patch("p9_3b3_c2_stations._generate_days",side_effect=strict), \
                 patch("builtins.print"):
                r=station_diagnostic(load_protocol(),out,Path(tmp)/"private")
            self.assertEqual(r["actual_generated_members"],126)
            self.assertEqual(r["expected_cells"],630)
            self.assertEqual(r["cell_status_counts"],{"SOURCE_OR_GENERATION_COVERAGE_BLOCKED":630})
            ledger=json.loads((out/"c2_station_correction_ledger.json").read_text())
            self.assertEqual(len(ledger),30)
            self.assertTrue(all(m["summary"]["counts"]=={"EXACT_SOURCE_PRESERVED":14} for x in ledger for m in x["modes"]))


if __name__=="__main__":unittest.main()
