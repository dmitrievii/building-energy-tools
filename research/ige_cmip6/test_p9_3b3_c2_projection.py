"""C2 independent scalar optima, forward witnesses and adversarial contracts."""
import dataclasses
import json
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import minimize_scalar

from p9_3b3_c2_projection import (MODES, CorrectionBudget, ProjectionMetric,
    ProjectionPolicy, ProjectionProblem, project_day)
from p9_3b3_c2_validation import validate_projection
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_source_semantics import DailyTarget, SourceSemantics
from p9_3b3_state_validation import _es


EPS = 287.05/461.5


def scalar_rh(T, P, q, phase="WATER"):
    return 100*q*P/(EPS+(1-EPS)*q)/_es(T, phase, "MURPHY_KOOP_2005")


def scalar_q(T, P, RH):
    e = RH/100*_es(T, "WATER", "MURPHY_KOOP_2005")
    return EPS*e/(P-(1-EPS)*e)


def fixture(n=1, *, q_weights=None, RH_weights=None, T_weights=None, mean=False, phase="WATER"):
    T = np.array([280.]) if n == 1 else 283+6*np.sin(2*np.pi*np.arange(n)/n)
    P = PressureReference(tuple(97000+np.zeros(n)), "INDEPENDENT_SCALAR_ORACLE", "GRID",
                          reference_date="2021-02-01")
    q = np.array([scalar_q(t,p,50+5*math.cos(i)) for i,(t,p) in enumerate(zip(T,P.values_Pa))])
    u = np.ones(n)/n if q_weights is None else np.array(q_weights)
    v = np.ones(n)/n if RH_weights is None else np.array(RH_weights)
    w = np.ones(n)/n if T_weights is None else np.array(T_weights)
    sem = SourceSemantics("TIME_MEAN_TAS" if mean else "DERIVED_TAS_MIDRANGE",phase,
        time_support="INDEPENDENT_SYNTHETIC_DISCRETE_NODES",verified=True)
    R = float(v@np.array([scalar_rh(t,p,z,phase) for t,p,z in zip(T,P.values_Pa,q)]))
    target = DailyTarget("2021-02-01",float(T.min()),float(T.max()),
        float(w@T if mean else (T.min()+T.max())/2),float(u@q),R,sem)
    return T,q,target,P


def project(T,q,target,P,**kwargs):
    return project_day(T,q,target,P,donor_date="2019-02-01",**kwargs)


class ScalarProjectionOracles(unittest.TestCase):
    def test_all_modes_preserve_an_exact_forward_state(self):
        for n in (1,4,24):
            T,q,t,p=fixture(n)
            for mode in MODES:
                r=project(T,q,t,p,mode=mode)
                self.assertEqual(r["status"],"EXACT_SOURCE_PRESERVED")
                np.testing.assert_array_equal(r["T_K"],T)
                np.testing.assert_allclose(r["q_kgkg"],q,rtol=0,atol=1e-18)
                self.assertEqual(r["p_Pa"],list(p.values_Pa))
                self.assertEqual(len(r["journal"]),2)
                self.assertFalse(r["source_modified"])

    def test_hard_q_one_node_has_a_unique_analytic_solution(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        r=project(T,q,t,p,mode="HARD_Q_SOFT_RH")
        self.assertEqual(r["status"],"LOCAL_PHYSICAL_PROJECTION_RESEARCH_ONLY")
        self.assertAlmostEqual(r["q_kgkg"][0],t.q_mean_kgkg,places=11)
        self.assertAlmostEqual(r["journal"][1]["achieved_value"],55.,places=7)
        self.assertEqual(r["strict_stage_status"],"CERTIFIED_INFEASIBLE")
        self.assertFalse(r["journal"][0]["correction_applied"])
        self.assertTrue(r["journal"][1]["correction_applied"])

    def test_hard_RH_one_node_has_a_unique_analytic_inverse(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        r=project(T,q,t,p,mode="HARD_RH_SOFT_Q")
        self.assertAlmostEqual(r["q_kgkg"][0],scalar_q(T[0],p.values_Pa[0],90),places=10)
        self.assertLess(abs(r["validation"]["daily_residuals"]["RH_mean_pp"]),1e-4)

    def test_both_soft_matches_independent_bounded_scalar_minimum(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        for correlation in (-.4,0.,.6):
            metric=ProjectionMetric(correlation=correlation)
            policy=ProjectionPolicy(lambda_shape=0)
            def independent_objective(z):
                a=(z-t.q_mean_kgkg)*1000/metric.q_scale_gkg
                b=(scalar_rh(T[0],p.values_Pa[0],z)-90)/metric.RH_scale_pp
                return .5*(a*a-2*correlation*a*b+b*b)/(1-correlation**2)
            oracle=minimize_scalar(independent_objective,bounds=(0,scalar_q(T[0],p.values_Pa[0],100)),
                method="bounded",options={"xatol":1e-14})
            r=project(T,q,t,p,metric=metric,policy=policy)
            self.assertAlmostEqual(r["q_kgkg"][0],oracle.x,delta=2e-9)
            self.assertAlmostEqual(r["objective"]["data_metric"],oracle.fun,delta=1e-8)
            self.assertFalse(r["global_optimality_certified"])

    def test_redundant_fixed_T_mean_does_not_disable_scalar_optimization(self):
        T,q,t,p=fixture(mean=True);t=dataclasses.replace(t,RH_mean_pct=90.)
        r=project(T,q,t,p,mode="HARD_RH_SOFT_Q")
        self.assertAlmostEqual(r["q_kgkg"][0],scalar_q(T[0],p.values_Pa[0],90),places=10)
        self.assertTrue(r["selected_solver_reported_success"])

    def test_prior_and_correlated_data_analytic_gradient(self):
        T,q,t,p=fixture(12)
        problem=ProjectionProblem(T,q,t,p)
        x=problem.base.pack(T+.1*np.cos(np.arange(12)),q*.9)
        metric=ProjectionMetric(correlation=.37)
        _,gradient=problem.objective(x,metric)
        numeric=[]
        for j in range(len(x)):
            a,b=x.copy(),x.copy();a[j]+=1e-5;b[j]-=1e-5
            numeric.append((problem.objective(a,metric)[0]-problem.objective(b,metric)[0])/2e-5)
        np.testing.assert_allclose(gradient,numeric,rtol=3e-6,atol=2e-7)

    def test_resolution_normalized_prior_for_constant_perturbation(self):
        for n in (1,4,24,48):
            T,q,t,p=fixture(n);problem=ProjectionProblem(T,q,t,p)
            x=problem.base.pack(T,q+problem.qscale*.2)
            value,_=problem.shape(x)
            self.assertAlmostEqual(value,.04,places=12)

    def test_saturation_cap_is_enforced_when_source_q_is_impossible(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,q_mean_kgkg=.05,RH_mean_pct=100.)
        hard=project(T,q,t,p,mode="HARD_Q_SOFT_RH")
        self.assertEqual(hard["status"],"CERTIFIED_HARD_CONSTRAINTS_INFEASIBLE")
        soft=project(T,q,t,p)
        self.assertLessEqual(soft["validation"]["RH_water_max_pct"],100.000001)
        self.assertLess(soft["journal"][0]["delta"],0)


class OperatorsAndPhysicalValidation(unittest.TestCase):
    def test_distinct_zero_support_q_RH_and_T_operators(self):
        u,v,w=[.5,.5,0,0],[0,0,.2,.8],[.1,.2,.3,.4]
        T,q,t,p=fixture(4,q_weights=u,RH_weights=v,T_weights=w,mean=True)
        r=project(T,q,t,p,q_weights=u,RH_weights=v,T_weights=w)
        self.assertEqual(r["status"],"EXACT_SOURCE_PRESERVED")
        self.assertEqual(r["q_weights"],u)
        self.assertNotEqual(r["journal"][0]["operator_weights_sha256"],r["journal"][1]["operator_weights_sha256"])

    def test_midrange_does_not_impose_a_T_time_mean(self):
        T=np.array([280.,280.,280.,290.]);q=np.array([.002]*4)
        _,_,t,p=fixture(4)
        R=math.fsum(scalar_rh(a,b,c) for a,b,c in zip(T,p.values_Pa,q))/4
        t=dataclasses.replace(t,Tmin_K=280.,Tmax_K=290.,tas_K=285.,q_mean_kgkg=.002,RH_mean_pct=R)
        r=project(T,q,t,p)
        self.assertEqual(r["status"],"EXACT_SOURCE_PRESERVED")
        self.assertEqual(r["validation"]["T_time_mean_K"],282.5)

    def test_incompatible_hard_temperature_mean_is_a_scoped_LP_certificate(self):
        T,q,t,p=fixture(4,mean=True)
        t=dataclasses.replace(t,tas_K=t.Tmax_K-.1)
        r=project(T,q,t,p)
        self.assertEqual(r["status"],"CERTIFIED_T_DOMAIN_INFEASIBLE")
        self.assertEqual(r["scope"],"THIS_DONOR_T_PRIOR_ONLY")
        self.assertEqual(len(r["journal"]),2)
        self.assertTrue(all(j["delta"] is None and not j["correction_applied"] for j in r["journal"]))

    def test_unknown_source_phase_blocks_instead_of_guessing(self):
        T,q,t,p=fixture()
        t=dataclasses.replace(t,semantics=dataclasses.replace(t.semantics,rh_phase="UNKNOWN",verified=False))
        self.assertEqual(project(T,q,t,p)["status"],"SOURCE_BLOCKED")

    def test_ice_relative_humidity_may_exceed_100_under_water_cap(self):
        T=np.array([268.]);P=PressureReference((97000.,),"ORACLE","GRID",reference_date="2021-02-01")
        q=np.array([scalar_q(268.,97000.,99.)]);R=scalar_rh(268.,97000.,q[0],"WATER_ICE")
        self.assertGreater(R,100);self.assertLessEqual(R,105)
        sem=SourceSemantics("DERIVED_TAS_MIDRANGE","WATER_ICE")
        t=DailyTarget("2021-02-01",268.,268.,268.,float(q[0]),R,sem)
        r=project(T,q,t,P)
        self.assertEqual(r["status"],"EXACT_SOURCE_PRESERVED")
        self.assertAlmostEqual(r["validation"]["RH_water_max_pct"],99.)

    def test_hard_water_RH_above_100_is_conditionally_impossible(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=103.)
        self.assertEqual(project(T,q,t,p,mode="HARD_RH_SOFT_Q")["status"],"CERTIFIED_HARD_CONSTRAINTS_INFEASIBLE")

    def test_validator_rejects_modified_pressure_and_supersaturation(self):
        T,q,t,p=fixture()
        for P,Q,message in (([97001.],q,"PRESSURE"),(p.values_Pa,[.09],"SUPERSATURATION")):
            with self.assertRaisesRegex(ValueError,message):
                validate_projection(T,P,Q,t,p.values_Pa,T,[1],[1],[1])

    def test_validator_does_not_trust_solver_extrema_or_declared_operators(self):
        T,q,t,p=fixture(4)
        a=T.copy();a[np.argmin(T)]+=.1
        with self.assertRaisesRegex(ValueError,"GEOMETRY"):
            validate_projection(a,p.values_Pa,q,t,p.values_Pa,T,[.25]*4,[.25]*4,[.25]*4)
        with self.assertRaisesRegex(ValueError,"WEIGHTS"):
            validate_projection(T,p.values_Pa,q,t,p.values_Pa,T,[.2]*4,[.25]*4,[.25]*4)


class EvidenceAndFailureContracts(unittest.TestCase):
    def test_source_arrays_and_pressure_are_immutable(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        before=(T.copy(),q.copy(),json.dumps(t.to_dict(),sort_keys=True),p.fingerprint)
        r=project(T,q,t,p)
        np.testing.assert_array_equal(T,before[0]);np.testing.assert_array_equal(q,before[1])
        self.assertEqual(json.dumps(t.to_dict(),sort_keys=True),before[2]);self.assertEqual(p.fingerprint,before[3])
        self.assertFalse(r["source_inputs_mutated"])
        self.assertTrue(r["source_modified"])
        for j in r["journal"]:
            self.assertAlmostEqual(j["achieved_value"]-j["source_value"],j["delta"],places=12)

    def test_zero_research_budget_rejects_but_retains_physical_candidate_and_ledger(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        budget=CorrectionBudget(0,0,"RESEARCH_GUARD_NOT_SCIENTIFIC_ACCEPTANCE","EXPLICIT_TEST_GUARD")
        r=project(T,q,t,p,budget=budget)
        self.assertEqual(r["status"],"REJECTED_CORRECTION_BUDGET")
        self.assertIn("q_kgkg",r);self.assertEqual(len(r["journal"]),2)
        self.assertEqual(r["validation"]["physical_admissibility"],"PASS_UNDER_DECLARED_DISCRETE_POLICY")
        self.assertFalse(r["production_eligible"])

    def test_no_calibrated_budget_or_covariance_is_invented(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        r=project(T,q,t,p)
        self.assertEqual(r["correction_acceptance"],"PROVISIONAL_CORRECTION_BUDGET_NOT_ESTABLISHED")
        self.assertIn("SENSITIVITY",r["metric"]["interpretation"])
        self.assertEqual(r["independent_accuracy"],"NOT_TESTED")
        for key in ("operational_ready","pressure_model_qualified","reconciliation_science_qualified"):
            self.assertFalse(r[key])

    def test_external_budget_metadata_never_qualifies_model_automatically(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        b=CorrectionBudget(100,100,"EXTERNALLY_JUSTIFIED_SAME_PRODUCT_BUDGET","SYNTHETIC_TEST_EVIDENCE_ONLY")
        r=project(T,q,t,p,budget=b)
        self.assertEqual(r["correction_acceptance"],"WITHIN_DECLARED_EXTERNAL_BUDGET")
        self.assertFalse(r["reconciliation_science_qualified"])

    def test_same_day_pressure_is_required_unless_registered_donor_sensitivity(self):
        T,q,t,p=fixture();p=dataclasses.replace(p,reference_date="2019-02-01")
        with self.assertRaisesRegex(ValueError,"DATE_MISMATCH"):project(T,q,t,p)
        r=project(T,q,t,p,pressure_alignment="REGISTERED_DONOR_PRESSURE_SENSITIVITY")
        self.assertEqual(r["status"],"EXACT_SOURCE_PRESERVED")
        with self.assertRaisesRegex(ValueError,"OBSERVED"):
            project(T,q,t,dataclasses.replace(p,mode="OBSERVED_SITE_VALIDATION_ONLY"))

    def test_strict_witness_is_revalidated_from_raw_arrays(self):
        T,q,t,p=fixture(4)
        witness={"status":"EXACT_DEFINED_OPERATORS","T_K":T.tolist(),"p_Pa":list(p.values_Pa),"q_kgkg":q.tolist()}
        good=project(T,q,t,p,strict_witness=witness)
        self.assertEqual(good["status"],"EXACT_SOURCE_PRESERVED")
        witness["T_K"][int(np.argmin(T))]+=.1
        with self.assertRaisesRegex(ValueError,"GEOMETRY"):project(T,q,t,p,strict_witness=witness)

    def test_forged_strict_witness_pressure_is_not_replaced_silently(self):
        T,q,t,p=fixture()
        witness={"status":"EXACT_DEFINED_OPERATORS","T_K":T.tolist(),"p_Pa":[96000.],"q_kgkg":q.tolist()}
        with self.assertRaisesRegex(ValueError,"PRESSURE_MISMATCH"):project(T,q,t,p,strict_witness=witness)

    def test_solver_failure_flag_does_not_hide_a_valid_feasible_candidate(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        def stopped(fun,x,**kw):return SimpleNamespace(x=np.asarray(x),success=False,nit=1,message="FORCED_TEST_STOP")
        with patch("p9_3b3_c2_projection.minimize",side_effect=stopped):r=project(T,q,t,p)
        self.assertEqual(r["status"],"LOCAL_PHYSICAL_PROJECTION_RESEARCH_ONLY")
        self.assertFalse(r["selected_solver_reported_success"])
        self.assertIn("OPTIMALITY_UNRESOLVED",r["local_optimality_status"])

    def test_solver_success_flag_cannot_admit_nonfinite_candidate(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        def forged(fun,x,**kw):return SimpleNamespace(x=np.full(len(x),np.nan),success=True,nit=1,message="FORGED_SUCCESS")
        with patch("p9_3b3_c2_projection.minimize",side_effect=forged):r=project(T,q,t,p)
        self.assertEqual(r["status"],"UNRESOLVED")
        self.assertNotIn("q_kgkg",r)

    def test_strict_local_failure_is_not_reported_as_infeasibility(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,RH_mean_pct=90.)
        def stopped(fun,x,**kw):return SimpleNamespace(x=np.asarray(x),success=False,nit=1,message="TEST_STOP")
        with patch("p9_3b3_c2_projection.identified_bounds",return_value={"status":"BOUND_INCONCLUSIVE"}), \
             patch("p9_3b3_c2_projection.minimize",side_effect=stopped):r=project(T,q,t,p)
        self.assertEqual(r["strict_stage_status"],"STRICT_SEARCH_UNRESOLVED_COMPATIBILITY_NOT_DISPROVED")
        self.assertFalse(r["global_optimality_certified"])

    def test_invalid_metric_and_budget_inputs_are_rejected(self):
        for kwargs in ({"q_scale_gkg":0},{"RH_scale_pp":math.nan},{"correlation":1.},
                       {"q_scale_gkg":1e-300},{"RH_scale_pp":1e300},{"evidence":""}):
            with self.assertRaises(ValueError):ProjectionMetric(**kwargs)
        for kwargs in ({"q_limit_gkg":1},{"interpretation":"RESEARCH_GUARD_NOT_SCIENTIFIC_ACCEPTANCE"},
                       {"evidence":""}):
            with self.assertRaises(ValueError):CorrectionBudget(**kwargs)


if __name__=="__main__":unittest.main()
