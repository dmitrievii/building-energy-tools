import dataclasses
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from p9_3b3_at_de_ch_validation import (score_frozen,empty_observations,read_sealed,
                                       SourceCache,coherent_target,protocol_guard,timestamps)
from p9_3b3_generator import generate,ThermoDonor
from p9_3b3_run import run
from test_p9_3b3_joint_solver import fixture


class ValidationContracts(unittest.TestCase):
    def test_sealed_data_tampering_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.json";p.write_text('{}')
            sha=hashlib.sha256(p.read_bytes()).hexdigest();p.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,"DIGEST_CHANGED"):read_sealed(p,sha)

    def test_all_missing_cells_stay_in_denominator(self):
        with tempfile.TemporaryDirectory() as d:
            pred=Path(d)/"pred.json";pred.write_text('{"members":[]}')
            obs=Path(d)/"obs.json";obs.write_text(json.dumps({c:empty_observations(c,"unavailable") for c in ("AT","DE","CH")}))
            m={"frozen_before_scoring":True,"countries":["AT","DE","CH"],"algorithm_commit":"a"*40,
               "predictions_path":str(pred),"predictions_sha256":hashlib.sha256(pred.read_bytes()).hexdigest(),
               "observations_path":str(obs),"observations_sha256":hashlib.sha256(obs.read_bytes()).hexdigest()}
            r=score_frozen(m)
            # 6 country-periods, (3 methods*5 seeds + rich*1), 5 variables.
            self.assertEqual(len(r["cells"]),6*16*5)
            self.assertTrue(all(x["status"]=="SOURCE_OR_GENERATION_COVERAGE_BLOCKED" for x in r["cells"]))
            self.assertFalse(r["pressure_model_qualified"])
            self.assertEqual(r["expected_site_hours"],2016)
            self.assertTrue(all(x["pressure_accuracy_gate"]=="INCONCLUSIVE_COVERAGE"
                                for x in r["cells"] if x["variable"]=="p_hPa"))

    def test_unfrozen_and_worldwide_scoring_rejected(self):
        for m in ({},{"frozen_before_scoring":True,"countries":["AT","DE","CH","US"]}):
            with self.assertRaises(ValueError):score_frozen(m)

    def test_generator_year_leakage(self):
        T,q,t,p=fixture();donor=ThermoDonor(t.date,tuple(T),tuple(q),p)
        with self.assertRaisesRegex(ValueError,"LEAKAGE"):generate([t],[donor])

    def test_no_donors_means_unresolved_not_physical_certificate(self):
        T,q,t,p=fixture();donor=ThermoDonor("2019-07-10",tuple(T),tuple(q),p)
        r,s=generate([t],[donor])
        self.assertEqual(r[0]["status"],"UNRESOLVED")
        self.assertEqual(s["total"],1)

    def test_generation_seed_order_reproducible(self):
        T,q,t,p=fixture()
        ds=[ThermoDonor(date,tuple(T),tuple(q),p) for date in ("2019-01-10","2020-01-11")]
        a,_=generate([t],ds);b,_=generate([t],list(reversed(ds)))
        self.assertEqual(a[0]["donor_date"],b[0]["donor_date"])
        self.assertEqual(a[0]["T_K"],b[0]["T_K"])

    def test_cli_full_state_readback_and_no_overwrite(self):
        T,q,t,p=fixture()
        m={"targets":[t.to_dict()],"donors":[dataclasses.asdict(ThermoDonor("2019-01-10",tuple(T),tuple(q),p))]}
        with tempfile.TemporaryDirectory() as d:
            manifest=Path(d)/"input.json";manifest.write_text(json.dumps(m))
            out=Path(d)/"out";report=run("strict",manifest,out)
            self.assertEqual(report["days"][0]["status"],"EXACT_DEFINED_OPERATORS")
            self.assertFalse(report["production_epw_ready"])
            with self.assertRaisesRegex(ValueError,"NO_OVERWRITE"):run("strict",manifest,out)

    def test_source_cache_allowlist(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):SourceCache(d).fetch("https://example.com/station.csv")

    def test_frozen_protocol_exposure_check(self):
        self.assertEqual(len(protocol_guard()),64)

    def test_bootstrap_uses_identical_hours_of_both_models(self):
        from p9_3b3_thermodynamics import saturation,q_from_e
        stamps=timestamps("2021-02-01","2021-02-14")
        observations={c:empty_observations(c) for c in ("AT","DE","CH")}
        o=observations["AT"];o["time_support"]="INSTANT"
        for key,v in (("T2m",10.),("RH2m",65.),("p_hPa",970.)):
            o["cells"]["winter"][key]={ts:v for ts in stamps}
        e=float(saturation(283.15))*.65
        row={"T2m":10.05,"RH2m":65.,"p_hPa":970.,"e_hPa":e/100,"q_gkg":float(q_from_e(e,97000))*1000}
        a={ts:dict(row) for ts in stamps};a[stamps[0]]["T2m"]=50.
        b={ts:{**row,"T2m":10.2} for ts in stamps[1:]}
        preds={"members":[{"country":"AT","period":"winter","method":m,"seed":7313,"hourly":x}
                          for m,x in (("B3_STRICT",a),("P93A_DAILY_CONTROL",b))]}
        with tempfile.TemporaryDirectory() as d:
            pp=Path(d)/"p.json";op=Path(d)/"o.json"
            pp.write_text(json.dumps(preds));op.write_text(json.dumps(observations))
            manifest={"frozen_before_scoring":True,"countries":["AT","DE","CH"],"algorithm_commit":"a"*40,
                "predictions_path":str(pp),"predictions_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),
                "observations_path":str(op),"observations_sha256":hashlib.sha256(op.read_bytes()).hexdigest()}
            report=score_frozen(manifest)
            json.dumps(report,allow_nan=False)
            pressure=next(x for x in report["cells"] if x["country"]=="AT" and
                x["period"]=="winter" and x["method"]=="B3_STRICT" and x["variable"]=="p_hPa")
            self.assertEqual(pressure["pressure_accuracy_gate"],"PASS_THIS_CELL_ONLY")
            c=next(x for x in report["comparisons"] if x["country"]=="AT" and x["variable"]=="T2m")
            self.assertAlmostEqual(c["delta_MAE"],-.15,places=9)


if __name__=="__main__":unittest.main()
