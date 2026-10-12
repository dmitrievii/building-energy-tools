"""IGE P7C.1C: reference-aware monthly q projection contracts (public synthetic only)."""
import unittest, math
import numpy as np
from p7c1_epw_morphing import q_from_rh,rh_from_q
from p7c1c_hourly_humidity_coherence import (
    EPSILON,project_monthly,rh_v_and_derivative,minimize_humidity,objective_gradient,
    saturation_vapor_pressure_pa,evaluate_epw,arrays_for_moisture
)

class P7C1CContracts(unittest.TestCase):
    def months(self):return np.repeat(np.arange(1,13),[744,672,744,720,744,720,744,744,720,744,720,744])
    def state(self):
        m=self.months();t=np.full(8760,15.);p=np.full(8760,101325.);lo=np.full(8760,2.);hi=np.full(8760,16.);
        v=np.full(8760,8.);ref=np.full(8760,55.);return m,t,p,lo,hi,v,ref
    def test_calendar_support(self):self.assertEqual(len(self.months()),8760)
    def test_exact_parent_epsilon(self):self.assertAlmostEqual(EPSILON,.62198,12)
    def test_saturation_round_trip(self):
        for temp in (-15.,-1.,10.,25.,40.):
            es=saturation_vapor_pressure_pa(temp)
            q=q_from_rh(temp,100.,101325.)
            self.assertAlmostEqual(q*101325/(EPSILON+(1-EPSILON)*q),es,6)
    def test_rh_inversion_and_derivative(self):
        ts=np.array([0.,15.,30.]);pp=np.full(3,101325.);qs=np.array([.002,.005,.014]);vg=qs*1000
        rh,d=rh_v_and_derivative(vg,ts,pp)
        for i in range(3):
            self.assertAlmostEqual(rh[i],rh_from_q(ts[i],qs[i],pp[i]),8)
            eps=1e-5;up=rh_v_and_derivative(vg+np.eye(3)[i]*eps,ts,pp)[0][i]
            dn=rh_v_and_derivative(vg-np.eye(3)[i]*eps,ts,pp)[0][i]
            self.assertAlmostEqual((up-dn)/(2*eps),d[i],5)
    def test_monthly_orthogonal_projection_exact(self):
        m,t,p,lo,hi,v,ref=self.state();v[100]=25.;v[200]=-2.
        totals={mm:8.*int(np.sum(m==mm)) for mm in range(1,13)}
        w=project_monthly(v,lo,hi,m,totals)
        self.assertTrue(np.all(w>=lo-1e-10) and np.all(w<=hi+1e-10))
        for mm in totals:self.assertAlmostEqual(float(np.sum(w[m==mm])),totals[mm],6)
        self.assertLessEqual(float(np.max(w)),16.)
    def test_infeasible_month_rejected(self):
        m,t,p,lo,hi,v,ref=self.state();totals={k:8*int(np.sum(m==k)) for k in range(1,13)}
        totals[2]=int(np.sum(m==2))*20
        with self.assertRaises(ValueError):project_monthly(v,lo,hi,m,totals)
    def test_missing_month_rejected(self):
        m,t,p,lo,hi,v,ref=self.state();m[:]=1
        with self.assertRaises(ValueError):project_monthly(v,lo,hi,m,{k:0 for k in range(1,13)})
    def test_nonfinite_rejected(self):
        m,t,p,lo,hi,v,ref=self.state();v[100]=float('nan')
        with self.assertRaises(ValueError):minimize_humidity(v,lo,hi,m,t,p,ref,np.full(8760,8.))
    def test_bad_length_rejected(self):
        m,t,p,lo,hi,v,ref=self.state()
        with self.assertRaises(ValueError):minimize_humidity(v[:-1],lo,hi,m,t,p,ref,v)
    def test_smooth_constant_fixed(self):
        m,t,p,lo,hi,v,ref=self.state()
        r,s=minimize_humidity(v,lo,hi,m,t,p,ref,v,iterations=15)
        self.assertLess(max(abs(r-v)),1e-8)
        self.assertAlmostEqual(s['objective_after'],0.,8)
    def test_new_spike_reduced_without_monthly_loss(self):
        m,t,p,lo,hi,v,ref=self.state();
        # 1-hour disturbance in a constant reference; prior already month-correct.
        prior=v.copy();prior[44]=11.;prior[45]=5.
        prior=project_monthly(prior,lo,hi,m,{k:8*int(np.sum(m==k)) for k in range(1,13)})
        r,s=minimize_humidity(v,lo,hi,m,t,p,ref,prior,iterations=65)
        self.assertLessEqual(abs(r[45]-r[44]),abs(prior[45]-prior[44])+1e-9)
        self.assertAlmostEqual(sum(r),sum(v),5)
    def test_parent_month_incompatibility_blocks(self):
        m,t,p,lo,hi,v,ref=self.state();hi[:]=4.
        with self.assertRaises(ValueError):minimize_humidity(v,lo,hi,m,t,p,ref,np.full(8760,4.))
    def test_gradient_finite_difference_at_spike(self):
        m,t,p,lo,hi,v,ref=self.state();v[100]=10.;v[101]=7.
        es=np.array([saturation_vapor_pressure_pa(tt) for tt in t]);threshold=np.full(8759,19.5)
        f,g,_=objective_gradient(v,np.full(8760,8.),t,p,es,np.diff(ref),threshold,v)
        eps=1e-5;j=101
        vv=v.copy();vv[j]+=eps; fp=objective_gradient(vv,np.full(8760,8.),t,p,es,np.diff(ref),threshold,v)[0]
        vv[j]-=2*eps;fm=objective_gradient(vv,np.full(8760,8.),t,p,es,np.diff(ref),threshold,v)[0]
        self.assertAlmostEqual(g[j],(fp-fm)/(2*eps),places=3)
    def test_physical_rh_at_saturation(self):
        m,t,p,lo,hi,v,ref=self.state(); cap=1000*q_from_rh(15.,100.,101325.)
        rh,_=rh_v_and_derivative(np.array([cap]),np.array([15.]),np.array([101325.]))
        self.assertAlmostEqual(rh[0],100.,9)

if __name__=='__main__':unittest.main()