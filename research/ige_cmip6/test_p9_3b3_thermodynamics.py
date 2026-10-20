import math
import unittest
import numpy as np

from p9_3b3_thermodynamics import (MK,BUCK,RD,RV,saturation,q_from_e,e_from_q,
    q_saturation,qsat_derivative,relative_humidity,dew_point,state_diagnostics)


class Thermodynamics(unittest.TestCase):
    def test_published_triple_point(self):
        # Murphy & Koop boundary condition 611.657 Pa, 273.16 K.
        for phase in ("WATER","ICE"):
            self.assertAlmostEqual(float(saturation(273.16,phase)),611.657,delta=.002)

    def test_ice_reference_200K(self):
        self.assertAlmostEqual(float(saturation(200.,"ICE")),.162691446,delta=1e-8)

    def test_ice_published_lower_domain(self):
        self.assertGreater(float(saturation(115.,"ICE")),0)
        with self.assertRaises(ValueError):saturation(115.,"WATER")

    def test_analytical_specific_humidity_mass_fraction(self):
        # Construct masses independently from ideal gas partial densities.
        T,p,e=288.,98000.,1400.
        mv=e/(RV*T);md=(p-e)/(RD*T)
        q=mv/(mv+md)
        self.assertAlmostEqual(float(q_from_e(e,p)),q,places=14)
        self.assertNotAlmostEqual(q,mv/md,places=6)

    def test_inverse_roundtrip_grid(self):
        for p in (60000,85000,101325):
            q=np.linspace(0,.035,50)
            np.testing.assert_allclose(q_from_e(e_from_q(q,p),p),q,rtol=1e-13,atol=1e-15)

    def test_ice_supersaturation_can_be_water_unsaturated(self):
        T=253.15;p=90000.
        e=float(saturation(T,"ICE"))*1.05
        q=float(q_from_e(e,p))
        self.assertGreater(float(relative_humidity(T,p,q,"WATER_ICE")),100)
        self.assertLess(float(relative_humidity(T,p,q,"WATER")),100)

    def test_water_ice_declared_switch(self):
        for t in (240.,270.,273.15,290.):
            phase="ICE" if t<273.15 else "WATER"
            self.assertEqual(saturation(t,"WATER_ICE"),saturation(t,phase))

    def test_dewpoint_inverse(self):
        for t in (200.,253.15,273.16,300.):
            self.assertAlmostEqual(dew_point(float(saturation(t))),t,places=9)

    def test_zero_vapour_no_fabricated_floor(self):
        self.assertIsNone(dew_point(0))
        self.assertEqual(float(q_from_e(0,100000)),0)
        self.assertEqual(state_diagnostics([280.],[100000.],[0.])["dew_point_K"],[None])

    def test_analytic_derivatives_against_independent_difference(self):
        for phase in ("WATER","ICE","WATER_ICE"):
            for T in (220.,255.,270.):
                h=1e-3
                fd=(saturation(T+h,phase)-saturation(T-h,phase))/(2*h)
                self.assertAlmostEqual(float(saturation(T,phase,derivative=True))/fd,1,delta=2e-8)
        for T in (250.,280.,310.):
            h=1e-3
            fd=(q_saturation(T+h,100000)-q_saturation(T-h,100000))/(2*h)
            self.assertAlmostEqual(float(qsat_derivative(T,100000))/fd,1,delta=2e-8)

    def test_domains_fail_closed(self):
        for args in ((100.,"WATER"),(280.,"ICE"),(333.,"WATER"),(270.,"UNKNOWN")):
            with self.assertRaises(ValueError):saturation(*args)
        for e,p in ((-1,100000),(100000,100000),(2,0)):
            with self.assertRaises(ValueError):q_from_e(e,p)
        with self.assertRaises(ValueError):e_from_q(float("nan"),100000)

    def test_legacy_is_explicit_separate_formulation(self):
        self.assertAlmostEqual(float(saturation(273.15,formulation=BUCK)),611.21)
        with self.assertRaises(ValueError):saturation(250.,"ICE",BUCK)

    def test_averages_do_not_commute(self):
        t=np.array([270.,300.]);p=np.array([98000.,99000.]);q=np.array([.002,.009])
        mean_r=float(np.mean(relative_humidity(t,p,q)))
        proxy=float(relative_humidity(np.mean(t),np.mean(p),np.mean(q)))
        self.assertGreater(abs(mean_r-proxy),1)


if __name__=="__main__":unittest.main()
