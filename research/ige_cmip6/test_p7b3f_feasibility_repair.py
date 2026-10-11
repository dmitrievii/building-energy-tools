"""P7B.3F: original daily invariance, minimal relaxation, exact M2 legacy identity."""
import math
import unittest
from datetime import date,datetime,timedelta
from unittest.mock import patch
from p7b3f_feasibility_repair import (
    minimum_relaxed_cap,prepare_daily,generate_repaired,radiometric_audit,
)
from p7b3e_multigcm_radiometric_closure import cap_profile
from p7b3c_conditional_solar import generate as legacy_generate


def fake_geometry(t=1.):
    dt=datetime(2013,6,1)
    return tuple((dt+timedelta(hours=h),t,.4*t) for h in range(24))


class P7B3FContracts(unittest.TestCase):
    def test_unrelaxed_caps_exact_legacy(self):
        g=fake_geometry()
        cs,f,original,total=minimum_relaxed_cap(g,10.)
        self.assertEqual(f,0.)
        self.assertEqual(cs,cap_profile(g,.65))
    def test_minimum_convex_fraction_analytic(self):
        g=fake_geometry()
        old=cap_profile(g,.65)
        E=.5*(sum(old)+24.)
        caps,f,original,total=minimum_relaxed_cap(g,E)
        self.assertAlmostEqual(f,.5,places=9)
        self.assertLess(abs(sum(caps)-E),2e-9)
        self.assertTrue(all(old_i<=v<=1 for old_i,v in zip(old,caps)))
        left=.49
        self.assertLess(sum(x+left*(t-x) for x,t in zip(old,[1.]*24)),E)
    def test_at_exact_toa_admitted(self):
        caps,f,_,_=minimum_relaxed_cap(fake_geometry(),24.)
        self.assertAlmostEqual(f,1.)
        self.assertEqual(caps,[1.]*24)
    def test_above_toa_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'EXCEEDS_CONSERVATIVE_TOA'):
            minimum_relaxed_cap(fake_geometry(),24.01)
    def test_nan_negative_and_wrong_hours_fail(self):
        for energy in (-.1,math.nan,math.inf):
            with self.assertRaises(ValueError):minimum_relaxed_cap(fake_geometry(),energy)
        with self.assertRaisesRegex(ValueError,'24'):
            minimum_relaxed_cap(fake_geometry()[:23],10.)
    def test_zero_energy_is_not_randomly_generated(self):
        g=fake_geometry()
        caps,frac,_,_=minimum_relaxed_cap(g,0.)
        self.assertEqual(frac,0.)
        self.assertTrue(all(c>=0 for c in caps))
    def test_prepared_model_keeps_rejected_days_explicit(self):
        days={date(2013,6,1):24.01}
        with patch('p7b3f_feasibility_repair.solar_vectors', return_value=fake_geometry()):
            prepared,counts,fractions,rejected,examples=prepare_daily(days,47.,15.)
        self.assertEqual(prepared,{})
        self.assertEqual(counts['original_daily_exceeds_toa'],1)
        self.assertEqual(len(rejected),1)
        self.assertIn('EXCEEDS_CONSERVATIVE_TOA',rejected[0]['reason'])
    def test_repaired_sampling_frozen_on_unrepaired(self):
        dt=datetime(2013,6,1)
        g=tuple((dt+timedelta(hours=h),(.2 if 7<=h<17 else 0.),(.17 if 7<=h<17 else 0.)) for h in range(24))
        # Low daily energy (old cap feasible); same source baseline.
        caps,frac,_,_=minimum_relaxed_cap(g,1.)
        self.assertEqual(frac,0.)
        from p7b3c_conditional_solar import project_energy
        base=project_energy([x[2] for x in g],1.,caps)
        day=date(2013,6,1)
        prepared={day:{'records':[(dt,base[h],x[1],x[2]) for h,x in enumerate(g) for dt in [x[0]]],
                       'caps':caps,'fraction':0.,'source_energy':1.}}
        lib={'JJA':[{'day':'2007-06-05','kt':.5,'ratios':[.3 if h%2 else .8 for h in range(24)]}]}
        for seed in [0,2,8]:
            a,old=legacy_generate({day:prepared[day]['records']},lib,.75,seed)
            b,new=generate_repaired(prepared,lib,seed)
            self.assertEqual(a,b)
            self.assertEqual(new['complete_days'],1)
    def test_repaired_day_energy_cap_and_components(self):
        dt=datetime(2013,6,1)
        g=tuple((dt+timedelta(hours=h),(1. if 7<=h<17 else 0.),(.4 if 7<=h<17 else 0.)) for h in range(24))
        caps,lam,_,_=minimum_relaxed_cap(g,8.)
        self.assertGreater(lam,0)
        from p7b3c_conditional_solar import project_energy
        base=project_energy([x[2] for x in g],8.,caps)
        day=date(2013,6,1)
        prep={day:{'records':[(x[0],base[h],x[1],x[2]) for h,x in enumerate(g)],
                 'caps':caps,'fraction':lam,'source_energy':8.}}
        lib={'JJA':[{'day':'2007-06-05','kt':.1,'ratios':[1. if h%2 else .5 for h in range(24)]}]}
        hourly,diag=generate_repaired(prep,lib,10)
        self.assertAlmostEqual(sum(hourly.values()),8.,places=10)
        self.assertLess(diag['max_daily_energy_residual'],1e-9)
        radi,rows=radiometric_audit(prep,hourly)
        self.assertLess(radi['max_radiometric_identity_residual_kwh_m2_h'],1e-10)

if __name__=='__main__':unittest.main()