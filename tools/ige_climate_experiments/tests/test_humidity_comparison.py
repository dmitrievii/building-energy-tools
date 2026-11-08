"""Independent conversions, grouped exclusions, fixed cases and workflow controls."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from support_auto import ROOT,config,synthetic_cube
from ige_auto.cases import Cases
from ige_auto.data import buck_water
from ige_auto.fit import fit_cases,predict
from ige_local.common import InputError,digest,read_json,write_json
from ige_hum.physics import EPSILON,q_from_e,e_from_q,restore,dewpoint_water
from ige_hum.cases import HumidityCases
from ige_hum.config import load,check_cohort
from ige_hum.metrics import score,errors
from ige_hum.auxiliary import MODEL,training_folds,train_bundle,forecasts
from ige_hum.optimize import optimize_chain
from ige_hum.study import create_spec,train,evaluate,seal


class HumidityPhysics(unittest.TestCase):
    def test_macro_score_balances_countries_and_stations(self):
        from types import SimpleNamespace
        case=SimpleNamespace(country=np.array(["AT","AT","AT","DE"]),
            station=np.array(["AT1","AT1","AT2","DE1"]),month=np.ones(4,dtype=int))
        result=errors(np.zeros(4),np.array([0.,0.,2.,5.]),case,np.ones(4,dtype=bool))
        self.assertEqual(result["MAE"],1.75)
        self.assertEqual(result["macro_MAE"],3.)

    def test_specific_humidity_is_water_mass_over_total_mass(self):
        e=np.array([0.,2.,10.,25.]);p=np.array([700.,850.,1000.,1013.25])
        water_over_dry=EPSILON*e/(p-e)
        np.testing.assert_allclose(q_from_e(e,p),water_over_dry/(1+water_over_dry),rtol=1e-14)
        self.assertNotEqual(float(q_from_e(10.,1000.)),float(EPSILON*10/(1000-10)))

    def test_q_e_roundtrip_and_pressure_units(self):
        e=np.array([.1,2.,10.,30.]);p=np.array([700.,850.,1000.,1013.25])
        q=q_from_e(e,p)
        np.testing.assert_allclose(e_from_q(q,p),e,rtol=1e-14)
        np.testing.assert_allclose(q_from_e(e*100,p*100),q,rtol=1e-14)

    def test_recovered_RH_uses_predicted_temperature(self):
        e=10.;q=q_from_e(e,1000.)
        cold=restore("q",np.array([q]),np.array([10.]),np.array([1000.]))
        warm=restore("q",np.array([q]),np.array([25.]),np.array([1000.]))
        self.assertGreater(cold["RH"][0],warm["RH"][0])
        self.assertAlmostEqual(cold["e_hPa"][0],warm["e_hPa"][0])

    def test_RH_and_supersaturation_are_not_clipped(self):
        out=restore("RH",np.array([-4.,110.]),np.array([20.,20.]),np.array([1000.,1000.]))
        np.testing.assert_array_equal(out["RH"],[-4.,110.])
        np.testing.assert_array_equal(out["supersaturated"],[False,True])
        np.testing.assert_array_equal(out["negative_RH"],[True,False])

    def test_math_failures_are_explicit(self):
        self.assertTrue(np.isnan(e_from_q(.01,-1.)))
        out=restore("log_e",np.array([1000.]),np.array([20.]),np.array([1000.]),False)
        self.assertFalse(np.isfinite(out["RH"][0]))

    def test_dewpoint_inverts_same_water_curve_and_bounds(self):
        t=np.array([-50.,-5.,0.,15.,35.])
        np.testing.assert_allclose(dewpoint_water(buck_water(t)),t,atol=1e-10)
        self.assertTrue(np.isnan(dewpoint_water(0.)))
        self.assertTrue(np.isnan(dewpoint_water(buck_water(60.))))


class HumidityWorkspace(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="IGE Humidity Климат ");self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name).resolve();self.c=config(self.base)
        self.c["variables"]=["T","RH","p","log_e_water"]
        self.c["models"]=[self.c["models"][0]]
        self.c["optimizer"].update(max_evaluations=180,max_iterations=40,wall_seconds_per_model=30,starts=1)
        p=Path(self.c["config_source_path"]);raw=read_json(p)
        raw["variables"]=self.c["variables"];raw["models"]=self.c["models"];raw["optimizer"]=self.c["optimizer"]
        write_json(p,raw)
        self.cube=synthetic_cube(self.base,self.c,missing=False)
        keys=("data_signature","stations","family_roles","inner_folds","times","time_roles")
        self.anchor={"schema":"IGE_AUTO_SPLIT_v1",**{k:self.cube.meta[k] for k in keys}}
        self.anchor["split_id"]=digest(self.anchor)
        self.anchor_path=self.base/"frozen_run/cube/split.sealed.json";write_json(self.anchor_path,self.anchor)
        self.h={"schema":"IGE_HUMIDITY_COMPARISON_v1","base_config":str(p),"cohort_anchor":str(self.anchor_path),
                "results":str(self.base/"humidity_results"),"coordinates":["RH","log_e","q"],
                "primary_metric":"equal_country_station_macro_MAE_RH","workers":1,
                "auxiliary_optimizer":self.c["optimizer"].copy()}
        self.hpath=self.base/"humidity_config.json";write_json(self.hpath,self.h)
        self.d=np.flatnonzero(self.cube.roles=="D");self.v=np.flatnonzero(self.cube.roles=="V")
        self.dt=np.flatnonzero(self.cube.time_roles=="D");self.vt=np.flatnonzero(self.cube.time_roles=="V")

    def native(self):return HumidityCases(self.cube,self.c,[(self.v,self.vt)],self.d,"V_test")

    def aux(self,native):return {"T":native.values[:,0].copy(),"p":native.values[:,2].copy()}


class HumidityCasesTests(HumidityWorkspace):
    def test_same_cases_and_donors_for_all_coordinates(self):
        n=self.native();views=[n.view(x) for x in ("RH","log_e","q")]
        for b in views[1:]:
            np.testing.assert_array_equal(b.mask,views[0].mask)
            np.testing.assert_array_equal(b.obs,views[0].obs)
            self.assertEqual(b.row_id,views[0].row_id)

    def test_joint_family_exclusion_all_hours(self):
        n=self.native();b=n.view("q")
        for i,s in enumerate(b.s):
            for j,d in enumerate(b.d):
                if b.mask[i,j]:self.assertNotEqual(self.cube.stations[s]["family"],self.cube.stations[d]["family"])

    def test_missing_pressure_reduces_joint_but_not_direct_RH_support(self):
        n=self.native();n.quality[:,:,2]=False;n.joint_donors[:]=False
        self.assertEqual(n.view("RH").fit_mask.sum(),0)
        self.assertGreater(n.view("RH",False).fit_mask.sum(),0)

    def test_one_donor_per_physical_family(self):
        self.cube.stations[self.d[1]]["family"]=self.cube.stations[self.d[0]]["family"]
        n=self.native();b=n.view("q")
        cols=[j for j,d in enumerate(b.d) if self.cube.stations[d]["family"]==self.cube.stations[self.d[0]]["family"]]
        self.assertTrue(np.all(b.mask[:,cols].sum(axis=1)<=1))

    def test_validation_truth_cannot_change_prediction(self):
        n=self.native();b=n.view("q");fit={"coefficients":[-.0005]}
        before=predict(b,MODEL,[2.,0.],fit)[0]
        n.values[:,0]+=5;n.values[:,2]+=50;n.q[:]=.02
        after=predict(n.view("q"),MODEL,[2.,0.],fit)[0]
        np.testing.assert_array_equal(before,after)

    def test_manual_and_automatic_strata_do_not_change_weights(self):
        n=self.native();b=n.view("RH");before=b.weights("idw",[2.,0.])
        n.target_qc[:,1]=0
        np.testing.assert_array_equal(n.view("RH").weights("idw",[2.,0.]),before)

    def test_common_mask_is_fixed_before_any_candidate_predictions(self):
        n=self.native();aux=self.aux(n);mask=n.common_mask(aux)
        bad=restore("RH",np.full(len(mask),np.nan),aux["T"],aux["p"])
        result=score(n,bad,mask)
        self.assertEqual(result["RH"]["N_reference"],int(mask.sum()))
        self.assertEqual(result["RH"]["N_scored"],0)
        self.assertIsNone(result["RH"]["macro_MAE"])
        np.testing.assert_array_equal(mask,n.common_mask(aux))

    def test_anchor_refuses_changed_role_or_source_selection(self):
        bad=copy.deepcopy(self.anchor);bad["family_roles"]=dict(bad["family_roles"])
        bad["family_roles"][next(iter(bad["family_roles"]))]="C"
        with self.assertRaises(InputError):check_cohort(self.cube,bad)
        bad=copy.deepcopy(self.anchor);bad["data_signature"]="other"
        with self.assertRaises(InputError):check_cohort(self.cube,bad)

    def test_nested_auxiliary_folds_exclude_held_family(self):
        outer=self.d[self.cube.folds[self.d]!=0]
        parts,mapping=training_folds(self.cube,self.c,outer)
        for i,part in enumerate(parts):
            held={self.cube.stations[s]["family"] for s in outer if mapping[self.cube.stations[s]["family"]]==i}
            self.assertFalse(held&{self.cube.stations[s]["family"] for s in part})
            self.assertTrue(all(self.cube.roles[s]=="D" for s in part))

    def test_joint_family_dedup_keeps_an_available_alternative_site(self):
        self.cube.stations[self.d[1]]["family"]=self.cube.stations[self.d[0]]["family"]
        n=self.native();cols=[j for j,d in enumerate(n.base.d) if d in self.d[:2]]
        n.joint_donors[:,cols[0]]=False;n.joint_donors[:,cols[1]]=True
        n.geometry[:,cols[1]]=True
        b=n.view("q")
        self.assertFalse(b.mask[:,cols[0]].any())
        self.assertTrue(b.mask[:,cols[1]].all())

    def test_q_chain_uses_predicted_pressure(self):
        q=np.array([.008])
        low=restore("q",q,np.array([20.]),np.array([800.]))
        high=restore("q",q,np.array([20.]),np.array([1000.]))
        self.assertGreater(high["RH"][0],low["RH"][0])

    def test_q_outside_physical_domain_is_preserved_and_flagged(self):
        q=np.array([-.01,1.1])
        out=restore("q",q,np.array([20.,20.]),np.array([1000.,1000.]))
        np.testing.assert_array_equal(out["q_kgkg"],q)
        self.assertTrue(out["q_outside_0_1"].all())

    def test_dependency_free_config_preflight(self):
        result=subprocess.run([sys.executable,"-S",str(ROOT/"ige_humidity.py"),"check-config","--config",str(self.hpath)],
                              capture_output=True,encoding="utf-8",env={**os.environ,"PYTHONUTF8":"1"},timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(json.loads(result.stdout)["configuration_valid"])
        self.assertFalse(Path(self.h["results"]).exists())

    def test_prior_C_exposure_is_not_relabelled_as_new(self):
        write_json(self.anchor_path.parent.parent/"C_OPENED.json",{"exposed":True})
        with self.assertRaisesRegex(InputError,"already exposed"):load(self.hpath)


class HumidityWorkflow(HumidityWorkspace):
    def test_full_DV_run_resume_and_explicit_C_on_synthetic_only(self):
        root=self.base/"run";root.mkdir()
        create_spec(self.cube,self.h,self.c,self.anchor,root)
        with contextlib.redirect_stdout(io.StringIO()):
            result=train(root)
        self.assertEqual(result["exit_code"],0,result)
        self.assertEqual(result["models_eligible"],3)
        self.assertFalse(result["holdout_opened"])
        self.assertFalse((root/"C_OPENED.json").exists())
        self.assertFalse((self.anchor_path.parent.parent/"C_OPENED.json").exists())
        with patch("ige_hum.study.train_bundle",side_effect=AssertionError("No retraining on resume")):
            with contextlib.redirect_stdout(io.StringIO()):again=train(root)
        self.assertEqual(again["primary_chain_selected_on_V"],result["primary_chain_selected_on_V"])
        with patch("ige_hum.study.fit_cases",side_effect=AssertionError("No fit on C")):
            evaluated=evaluate(root)
        self.assertEqual(evaluated["exit_code"],0)
        with self.assertRaisesRegex(InputError,"already exposed"):evaluate(root)
        self.assertTrue(evaluate(root,repeat=True)["repeated_exposure"])

    def test_unresolved_source_error_stops_before_model_training(self):
        self.cube.meta["source_errors"]=[{"error":"malformed source"}]
        with self.assertRaisesRegex(InputError,"unresolved errors"):
            create_spec(self.cube,self.h,self.c,self.anchor,self.base/"blocked")

    def test_modified_prediction_refuses_resume(self):
        root=self.base/"run";root.mkdir()
        create_spec(self.cube,self.h,self.c,self.anchor,root)
        with contextlib.redirect_stdout(io.StringIO()):train(root)
        path=next((root/"models").rglob("V_own_predictions.csv"))
        with path.open("a",encoding="utf-8") as f:f.write("changed\n")
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(InputError,"own-coverage predictions changed"):train(root)
        self.assertFalse((root/"C_OPENED.json").exists())
