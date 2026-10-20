import dataclasses
import json
import unittest
import numpy as np
from p9_3b3_source_semantics import DailyTarget,SourceSemantics
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_joint_solver import SolverPolicy,JointProblem,solve_day
from p9_3b3_source_reconciliation import reconcile_day
from p9_3b3_state_validation import validate_state
from p9_3b3_thermodynamics import q_saturation,relative_humidity


def fixture(seed=0,mean=False):
    rng=np.random.default_rng(seed)
    T=285.+7*np.sin(np.arange(24)*2*np.pi/24)+rng.uniform(-.05,.05,24)
    P=PressureReference(tuple(97000+50*np.cos(np.arange(24)*2*np.pi/24)),"SYNTHETIC","GRID")
    q=q_saturation(T,P.values_Pa)*(.55+.1*np.cos(np.arange(24)))
    sem=SourceSemantics("TIME_MEAN_TAS" if mean else "DERIVED_TAS_MIDRANGE","WATER",
                        time_support="SYNTHETIC_UTC_NODE_DAY",verified=True)
    target=DailyTarget("2014-01-02",float(T.min()),float(T.max()),
                      float(T.mean() if mean else (T.min()+T.max())/2),
                      float(q.mean()),float(np.mean(relative_humidity(T,P.values_Pa,q))),sem)
    return T,q,target,P


class JointSolver(unittest.TestCase):
    def test_twenty_mandatory_feasible_oracles(self):
        for seed in range(20):
            T,q,target,p=fixture(seed)
            r=solve_day(T,q,target,p)
            self.assertEqual(r["status"],"EXACT_DEFINED_OPERATORS",r)
            self.assertEqual(r["p_Pa"],list(p.values_Pa))
            self.assertLess(abs(r["validation"]["daily_residuals"]["RH_mean_pp"]),1e-4)

    def test_time_mean_constraint_is_applied(self):
        T,q,t,p=fixture(mean=True)
        # Deliberately skew donor shape, keep original true target moments.
        donor=T.copy();donor[2:8]+=.4
        r=solve_day(donor,q,t,p)
        self.assertEqual(r["status"],"EXACT_DEFINED_OPERATORS",r)
        self.assertLess(abs(np.mean(r["T_K"])-t.tas_K),1e-6)

    def test_joint_solver_moves_temperature_for_constructed_witness(self):
        T,q,t,p=fixture(1,mean=True)
        # Construct a target requiring a shape shift at the same extrema/mean.
        witness=T.copy();witness[2:5]+=.8;witness[15:18]-=.8
        qq=.999*q_saturation(witness,p.values_Pa)
        t=dataclasses.replace(t,q_mean_kgkg=float(qq.mean()),
                              RH_mean_pct=float(np.mean(relative_humidity(witness,p.values_Pa,qq))))
        r=solve_day(T,q,t,p)
        self.assertEqual(r["status"],"EXACT_DEFINED_OPERATORS",r)
        self.assertEqual(r["method"],"JOINT_T_Q_SLSQP_VALIDATED")

    def test_impossible_target_has_conditional_certificate(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,q_mean_kgkg=.09)
        r=solve_day(T,q,t,p)
        self.assertEqual(r["status"],"CERTIFIED_INFEASIBLE")
        self.assertEqual(r["certificate"]["scope"],"THIS_DONOR_AND_POLICY_ONLY")

    def test_unknown_phase_source_blocked(self):
        T,q,t,p=fixture()
        t=dataclasses.replace(t,semantics=dataclasses.replace(t.semantics,rh_phase="UNKNOWN",verified=False))
        self.assertEqual(solve_day(T,q,t,p)["status"],"SOURCE_BLOCKED")

    def test_local_iteration_limit_not_scientific_impossibility(self):
        T,q,t,p=fixture(mean=True)
        donor=T.copy();donor[2:8]+=.8
        r=solve_day(donor,q,t,p,policy=SolverPolicy(max_iterations=1))
        self.assertIn(r["status"],("EXACT_DEFINED_OPERATORS","UNRESOLVED"))

    def test_reconciliation_journal_original_immutable(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,q_mean_kgkg=.08,RH_mean_pct=80)
        original=json.dumps(t.to_dict(),sort_keys=True)
        r=reconcile_day(T,q,t,p)
        self.assertEqual(r["status"],"LOCAL_RECONCILIATION_CANDIDATE",r)
        self.assertEqual(json.dumps(t.to_dict(),sort_keys=True),original)
        self.assertEqual(r["p_Pa"],list(p.values_Pa))
        self.assertTrue(r["source_modified"])
        self.assertFalse(r["production_eligible"])
        self.assertFalse(r["global_optimality_certified"])
        self.assertLess(r["journal"][0]["delta"],0)

    def test_feasible_source_not_projected(self):
        T,q,t,p=fixture();r=reconcile_day(T,q,t,p)
        self.assertEqual(r["reconciliation"],"NOT_NEEDED")
        self.assertFalse(r["source_modified"])

    def test_observed_pressure_forbidden_in_generation(self):
        T,q,t,p=fixture();p=dataclasses.replace(p,mode="OBSERVED_SITE_VALIDATION_ONLY")
        with self.assertRaisesRegex(ValueError,"OBSERVATIONS"):
            solve_day(T,q,t,p)

    def test_validator_rejects_tampered_result(self):
        T,q,t,p=fixture()
        with self.assertRaisesRegex(ValueError,"SUPERSATURATED"):
            validate_state(T.tolist(),list(p.values_Pa),[.06]*24,t,[1/24]*24)

    def test_repeatability(self):
        T,q,t,p=fixture()
        self.assertEqual(solve_day(T,q,t,p),solve_day(T,q,t,p))

    def test_objective_and_constraint_jacobians(self):
        T,q,t,p=fixture(mean=True);pb=JointProblem(T,q,t,p);x=pb.x0.copy()
        value,grad=pb.shape(x)
        for i in (0,pb.k,pb.k+5):
            h=1e-5;a=x.copy();b=x.copy();a[i]+=h;b[i]-=h
            fd=(pb.shape(a)[0]-pb.shape(b)[0])/(2*h)
            self.assertAlmostEqual(grad[i],fd,delta=1e-5)
        r,j=pb.humidity(x)
        for i in (0,pb.k,pb.k+5):
            h=1e-5;a=x.copy();b=x.copy();a[i]+=h;b[i]-=h
            fd=(pb.humidity(a)[0]-pb.humidity(b)[0])/(2*h)
            self.assertAlmostEqual(j[i],fd,delta=1e-5)


if __name__=="__main__":unittest.main()
