import itertools
import unittest
import numpy as np
from p9_3b3_daily_feasibility import (fixed_profile_feasibility,lower_rh_bound,
    upper_rh_profile,bounded_mean_profile,weights_for)
from p9_3b3_thermodynamics import q_saturation,relative_humidity


def vertex_min(T,P,Q,w):
    # Independent exact vertex enumeration: all but at most one q at bounds.
    c=q_saturation(T,P);best=1e99
    for free in range(len(c)):
        others=[i for i in range(len(c)) if i!=free]
        for bits in itertools.product((0,1),repeat=len(others)):
            q=np.zeros(len(c))
            for i,b in zip(others,bits):q[i]=b*c[i]
            q[free]=(Q-w@q)/w[free]
            if -1e-13<=q[free]<=c[free]+1e-13:
                q=np.clip(q,0,c)
                best=min(best,float(w@relative_humidity(T,P,q)))
    return best


class Feasibility(unittest.TestCase):
    def test_constructed_known_feasible_profiles(self):
        for seed in range(20):
            rng=np.random.default_rng(seed)
            T=rng.uniform(275,300,8);P=rng.uniform(90000,101000,8)
            q=q_saturation(T,P)*rng.uniform(.2,.9,8)
            r=float(np.mean(relative_humidity(T,P,q)))
            d=fixed_profile_feasibility(T,P,float(np.mean(q)),r,lower_time_limit=1)
            self.assertEqual(d["status"],"FEASIBLE",d)
            self.assertAlmostEqual(float(np.mean(d["witness_q"])),float(np.mean(q)),places=10)

    def test_capacity_certificate(self):
        T=np.array([280.,290.]);P=np.array([1e5,1e5])
        Q=float(np.mean(q_saturation(T,P)))+.001
        self.assertEqual(fixed_profile_feasibility(T,P,Q,90)["reason"],"Q_ABOVE_FIXED_PROFILE_CAPACITY")

    def test_global_upper_certificate(self):
        d=fixed_profile_feasibility([290.]*4,[100000.]*4,.005,100.)
        self.assertEqual(d["reason"],"RH_ABOVE_FIXED_PROFILE_GLOBAL_MAX")

    def test_kkt_maximum_beats_random_q_feasible_witnesses(self):
        T=np.array([278.,280.,290.,300.]);P=np.full(4,97000.)
        Q=.006;high=upper_rh_profile(T,P,Q)
        upper=float(np.mean(relative_humidity(T,P,high)))
        for seed in range(30):
            q=bounded_mean_profile(np.random.default_rng(seed).uniform(0,.02,4),q_saturation(T,P),Q)
            self.assertLessEqual(float(np.mean(relative_humidity(T,P,q))),upper+1e-8)

    def test_milp_bound_brackets_exact_vertex_min(self):
        T=np.array([278.,286.,294.,302.]);P=np.array([95000.,98000.,99000.,1e5])
        w=np.array([.1,.2,.3,.4]);Q=.006
        exact=vertex_min(T,P,Q,w)
        d=lower_rh_bound(T,P,Q,weights=w,time_limit=2)
        self.assertLessEqual(d["lower_pp"],exact+1e-6)
        self.assertGreaterEqual(d["witness_pp"],exact-1e-6)
        self.assertLess(d["gap_pp"],1e-3)

    def test_timeout_is_unresolved_not_false_infeasibility(self):
        d=lower_rh_bound([278.,300.],[1e5,1e5],.005,time_limit=0)
        self.assertEqual(d["status"],"RH_LOWER_BOUND_UNRESOLVED")

    def test_zero_and_full_capacity_unique_profiles(self):
        for Q in (0.,float(np.mean(q_saturation([280.,290.],[1e5,1e5])))):
            d=lower_rh_bound([280.,290.],[1e5,1e5],Q)
            self.assertEqual(d["gap_pp"],0)

    def test_weighted_projection_zero_prior(self):
        w=np.array([.1,.2,.7]);c=np.array([.005,.01,.02]);Q=.006
        q=bounded_mean_profile(np.zeros(3),c,Q,w)
        self.assertAlmostEqual(float(w@q),Q,places=12)
        self.assertTrue(np.all(q<=c))

    def test_invalid_weights(self):
        for w in ([0,1],[-1,2],[.2,.2],[float("nan"),1]):
            with self.assertRaises(ValueError):weights_for(2,w)


if __name__=="__main__":unittest.main()
