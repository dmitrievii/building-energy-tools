"""P7B.3B M0/M1 TAG-inspired physical source and reproducibility contracts."""
import unittest
from datetime import datetime,timedelta
from p7b3b_tag_benchmark import (
    exact_bounded_daily_scale, generate, seasonal_deltas, tag_coeff, tag_day
)

class P7B3BMethodTests(unittest.TestCase):
    def test_handbook_coefficients(self):
        phi,sigma=tag_coeff(.4)
        self.assertAlmostEqual(phi,.499712,places=6)
        self.assertAlmostEqual(sigma,.322,places=8)
    def test_clamped_clearness(self):
        self.assertEqual(tag_coeff(-1),tag_coeff(0))
        self.assertEqual(tag_coeff(9),tag_coeff(1))
    def test_bounded_conservation(self):
        result=exact_bounded_daily_scale([1,2,1],1.5,[.5,.9,.8])
        self.assertAlmostEqual(sum(result),1.5)
        self.assertTrue(all(0<=v<=c for v,c in zip(result,[.5,.9,.8])))
    def test_no_spurious_energy_at_zero(self):
        self.assertEqual(exact_bounded_daily_scale([1,1],[0][0],[1,1]),[0.,0.])
    def test_unreachable_day_is_error(self):
        with self.assertRaisesRegex(ValueError,"cannot be physically assigned"):
            exact_bounded_daily_scale([1,1],2.5,[1,1])
    def test_tag_daily_conservation_night_zero(self):
        clear=[0.]*6+[.1,.2,.4,.7,.9,1,1,.9,.7,.4,.2,.1]+[0.]*6
        ghi=[.4*v for v in clear]
        result=tag_day("2013-06-01",ghi,clear,0)
        self.assertAlmostEqual(sum(result),sum(ghi),places=9)
        self.assertEqual(result[:6],[0.]*6)
        self.assertEqual(result[-6:],[0.]*6)
        self.assertTrue(all(0<=v<=c for v,c in zip(result,clear)))
    def test_reproducible_seed(self):
        toa=[0.]*6+[.1,.2,.4,.7,.9,1,1,.9,.7,.4,.2,.1]+[0.]*6
        ghi=[.4*c for c in toa]
        self.assertEqual(tag_day("2013-06-01",ghi,toa,17),
                         tag_day("2013-06-01",ghi,toa,17))
        self.assertNotEqual(tag_day("2013-06-01",ghi,toa,17),
                            tag_day("2013-06-01",ghi,toa,18))
    def test_nontrivial_hourly_variability(self):
        toa=[0.]*6+[.1,.2,.4,.7,.9,1,1,.9,.7,.4,.2,.1]+[0.]*6
        ghi=[.4*c for c in toa]
        # A particular seeded Gaussian realization may clip every perturbation;
        # require variability over a reproducible ensemble, not in one chosen draw.
        self.assertTrue(any(
            max(abs(x-y) for x,y in zip(tag_day("2013-06-01",ghi,toa,seed),ghi))>.001
            for seed in range(20)))
    def test_strict_24_hour_requirement(self):
        with self.assertRaisesRegex(ValueError,"24 source hours"):
            tag_day("2013-01-01",[.1],[1],0)
    def test_no_fake_consecutive_delta_after_gap(self):
        t=datetime(2013,6,1,8)
        sample={t:.1,t+timedelta(hours=2):.5}
        self.assertEqual(seasonal_deltas(sample,(6,)),[])
    def test_generate_all_365_days_source_daily(self):
        base=datetime(2013,1,1)
        rows=[]
        for i in range(8760):
            h=i%24
            toa=1. if 8<=h<=16 else 0.
            rows.append((base+timedelta(hours=i),.45*toa,toa))
        generated,maxerr=generate(rows,4)
        self.assertEqual(len(generated),8760)
        self.assertLess(maxerr,1e-9)
        self.assertAlmostEqual(sum(v for _,v in generated),.45*9*365,places=6)

if __name__=="__main__":
    unittest.main()
