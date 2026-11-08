"""Numerical failure handling and preservation of the failed parent run."""
import contextlib
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from scipy.optimize import minimize as scipy_minimize
from test_humidity_comparison import HumidityWorkspace
from ige_auto.fit import optimize as native_optimize
from ige_hum.auxiliary import train_bundle
from ige_hum.config import sealed
from ige_hum.recovery import fork_run
from ige_hum.solver import recover_search,POLICY
from ige_hum.study import create_spec,seal
from ige_local.common import InputError,file_hash,write_json,read_json


class SolverRecovery(unittest.TestCase):
    def failed(self):
        return {"status":"UNRESOLVED_OPTIMIZATION","bounds":[[0.,5.],[-2.,2.]],
                "trace":[{"evaluation":1,"eta":[1.,0.],"objective":5.,"failure":None}],
                "runs":[{"success":False,"message":"INJECTED_NUMERICAL_FAILURE"}]}

    @staticmethod
    def objective(x):return (x[0]-3.)**2+(x[1]+1.)**2

    def test_failed_search_recovers_on_same_bounded_objective(self):
        result=recover_search(self.failed(),self.objective)
        self.assertEqual(result["status"],"CONVERGED")
        np.testing.assert_allclose(result["eta"],[3.,-1.],atol=1e-3)
        self.assertEqual(result["runs"][0]["message"],"INJECTED_NUMERICAL_FAILURE")
        self.assertTrue(result["recovery_used"])
        json.dumps(result,allow_nan=False)

    def test_derivative_free_stage_is_used_after_gradient_failure(self):
        def fail_gradient(fun,x0,method,**kwargs):
            if method=="L-BFGS-B":
                return SimpleNamespace(success=False,fun=fun(x0),x=np.array(x0),message="INJECTED_LINE_SEARCH",nit=0)
            return scipy_minimize(fun,x0,method=method,**kwargs)
        with patch("ige_hum.solver.minimize",side_effect=fail_gradient):result=recover_search(self.failed(),self.objective)
        self.assertEqual(result["status"],"CONVERGED")
        self.assertEqual(result["recovery_attempts"][-1]["method"],"Powell")
        np.testing.assert_allclose(result["eta"],[3.,-1.],atol=1e-3)

    def test_a_good_search_does_not_run_another_optimizer(self):
        initial={"status":"CONVERGED","eta":[3.,-1.]}
        with patch("ige_hum.solver.minimize",side_effect=AssertionError("Should reuse convergence")):
            self.assertIs(recover_search(initial,self.objective),initial)

    def test_exhausted_budget_is_never_relabelled_converged(self):
        with patch.dict(POLICY,{"max_evaluations_per_method":1}):result=recover_search(self.failed(),self.objective)
        self.assertEqual(result["status"],"UNRESOLVED_OPTIMIZATION")
        self.assertTrue(all(not r["success"] for r in result["recovery_attempts"]))

    def test_all_invalid_objectives_remain_failed(self):
        result=recover_search(self.failed(),lambda _:float("nan"))
        self.assertEqual(result["status"],"UNRESOLVED_OPTIMIZATION")
        self.assertTrue(any(t.get("failure") for t in result["trace"]))


class VersionedContinuation(HumidityWorkspace):
    def parent(self):
        root=self.base/"failed_run";root.mkdir()
        spec=create_spec(self.cube,self.h,self.c,self.anchor,root)
        with contextlib.redirect_stdout(io.StringIO()):bundle=train_bundle(self.cube,self.c,self.d,self.dt,self.h["auxiliary_optimizer"])
        cp=seal(root/"checkpoints/aux_full_D.json",{"spec_id":spec["spec_id"],"value":bundle},"checkpoint_id")
        cp=sealed(root/"checkpoints/aux_full_D.json","checkpoint_id")
        return root,spec,cp

    def test_fork_reuses_verified_D_bundles_and_preserves_parent(self):
        source,spec,cp=self.parent()
        before={str(p):file_hash(p) for p in source.rglob('*') if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()):child=fork_run(source)
        fresh=sealed(child/"run_spec.sealed.json","spec_id")
        inherited=sealed(child/"checkpoints/aux_full_D.json","checkpoint_id")
        self.assertNotEqual(fresh["spec_id"],spec["spec_id"])
        self.assertEqual(fresh["cube_id"],spec["cube_id"])
        self.assertEqual(inherited["value"],cp["value"])
        self.assertEqual(inherited["spec_id"],fresh["spec_id"])
        self.assertEqual(inherited["inherited_from"]["checkpoint_id"],cp["checkpoint_id"])
        self.assertEqual(before,{str(p):file_hash(p) for p in source.rglob('*') if p.is_file()})
        self.assertFalse((child/"C_OPENED.json").exists())

    def test_fork_refuses_previous_humidity_selection(self):
        source,_,_=self.parent();write_json(source/"models/RH/height/result.sealed.json",{})
        with self.assertRaisesRegex(InputError,"before humidity selection"):fork_run(source)

    def test_fork_refuses_C_exposure(self):
        source,_,_=self.parent();write_json(source/"C_OPENED.json",{})
        with self.assertRaisesRegex(InputError,"C already exposed"):fork_run(source)

    def test_corrupt_checkpoint_is_not_resealed_as_valid(self):
        source,spec,cp=self.parent()
        cp["value"]["T"]["fit"]["coefficients"]=[100.]
        write_json(source/"checkpoints/aux_full_D.json",cp)
        with self.assertRaisesRegex(InputError,"Sealed document mismatch"):fork_run(source)

    def test_holdout_year_cannot_enter_inherited_training(self):
        source,spec,cp=self.parent();cp.pop("checkpoint_id")
        cp["value"]["p"]["training_years"].append(2025)
        seal(source/"checkpoints/aux_full_D.json",cp,"checkpoint_id")
        with self.assertRaisesRegex(InputError,"D-only support"):fork_run(source)

    def test_unknown_old_implementation_is_refused(self):
        source,spec,cp=self.parent();spec.pop("spec_id");spec["implementation"]={"other":"code"}
        seal(source/"run_spec.sealed.json",spec,"spec_id")
        with self.assertRaisesRegex(InputError,"published 0.2.0"):fork_run(source)

    def test_failed_pressure_trace_is_saved_before_raising(self):
        bad={"status":"UNRESOLVED_OPTIMIZATION","trace":[],"runs":[{"success":False,"message":"INJECTED_FAILURE"}]}
        def optimize(folds,model,c):
            return copy.deepcopy(bad) if folds[0][0].variable=="p" else native_optimize(folds,model,c)
        diagnostics=self.base/"diagnostics"
        with contextlib.redirect_stdout(io.StringIO()),patch("ige_hum.auxiliary.optimize",side_effect=optimize),patch("ige_hum.auxiliary.recover_native",return_value=bad):
            with self.assertRaisesRegex(InputError,"Auxiliary p"):train_bundle(self.cube,self.c,self.d,self.dt,self.h["auxiliary_optimizer"],diagnostics)
        self.assertEqual(read_json(diagnostics/"p_optimization.json")["runs"][0]["message"],"INJECTED_FAILURE")
