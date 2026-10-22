"""Independent pressure/height oracles and adversarial vertical references."""
import dataclasses
import math
import unittest

import numpy as np

from p9_3b3_compare_vertical_frame import G0,SourceBlocked,VerticalCoordinate
from p9_3b3_reference_column import GASES,hybrid_column,target_geopotential,transfer_pressure


TIME='2021-02-01T00:00'


def column(T=280.,q=.005,ps=100000.,ground=0.,first=109,gas='B3_GAS_CONSISTENT',lat=47.):
    n=138-first
    t=np.full(n,T) if np.ndim(T)==0 else np.asarray(T)
    qq=np.full(n,q) if np.ndim(q)==0 else np.asarray(q)
    return hybrid_column(math.log(ps),ground*G0,t,qq,np.zeros(138),np.linspace(0,1,138),
        first_level=first,timestamp_UTC=TIME,latitude=lat,longitude=15.5,
        source='INDEPENDENT_SYNTHETIC_COLUMN',source_sha256='a'*64,gas=gas)


def target(h,role='BAROMETER',kind='GEOPOTENTIAL_HEIGHT_M',datum='MSL_GEOID',verified=True):
    return VerticalCoordinate(h,kind,datum,role,'SYNTHETIC_SOURCE_ORACLE',verified)


class ColumnOracles(unittest.TestCase):
    def test_isothermal_pressure_at_41_forward_heights_for_both_gases(self):
        for gas,(rd,coef) in GASES.items():
            c=column(gas=gas)
            for h in np.linspace(0,1500,41):
                expected=100000*math.exp(-G0*h/(rd*280*(1+coef*.005)))
                self.assertAlmostEqual(math.exp(c.log_pressure(h*G0)),expected,delta=2e-9)

    def test_source_surface_anchor_is_exact(self):
        c=column(ground=467.1535)
        self.assertAlmostEqual(math.exp(c.log_pressure(c.domain[0])),100000.,places=8)
        self.assertEqual(c.half_pressure_Pa[-1],math.exp(math.log(100000.)))

    def test_full_pressure_is_arithmetic_but_phi_has_ecmwf_alpha(self):
        c=column(first=1,gas='ECMWF_PUBLISHED_APPROXIMATION')
        rd,coef=GASES[c.gas];tv=280*(1+coef*.005);phi=0.
        expected=[]
        for i in range(136,-1,-1):
            upper=c.half_pressure_Pa[i];lower=c.half_pressure_Pa[i+1]
            dlog=math.log(lower/(.1 if i==0 else upper))
            alpha=math.log(2) if i==0 else 1-upper/(lower-upper)*dlog
            expected.append(phi+rd*tv*alpha);phi+=rd*tv*dlog
        np.testing.assert_allclose(c.full_geopotential_ECMWF_alpha_m2s2,list(reversed(expected)),atol=1e-8,rtol=0)
        np.testing.assert_allclose(c.full_pressure_Pa,(np.array(c.half_pressure_Pa[:-1])+c.half_pressure_Pa[1:])/2)
        # A full-level mean geopotential must not be silently inverted as if
        # its paired arithmetic pressure were an exact isothermal point.
        j=60
        self.assertGreater(abs(math.exp(c.log_pressure(c.full_geopotential_ECMWF_alpha_m2s2[j]))-c.full_pressure_Pa[j]),.01)

    def test_layer_boundary_pressures_and_monotonicity(self):
        T=np.linspace(250,292,29);q=np.linspace(.0005,.008,29);c=column(T,q)
        for p,phi in zip(c.integration_half_pressure_Pa,c.half_geopotential_m2s2):
            self.assertAlmostEqual(math.exp(c.log_pressure(phi)),p,delta=2e-9)
        phis=np.linspace(*c.domain,301)
        self.assertTrue(np.all(np.diff([c.log_pressure(x) for x in phis])<0))

    def test_piecewise_inversion_column_agrees_with_independent_layer_sum(self):
        T=280+8*np.sin(np.arange(29));q=np.linspace(.001,.009,29);c=column(T,q)
        phi=(c.domain[0]+c.domain[1])/2
        # Direct scalar integration from the SURFACE, independently of the
        # kernel's containing-layer formula and its upper-anchor blend.
        integral=0.;rd,coef=GASES[c.gas]
        for j in range(28,-1,-1):
            low=c.half_geopotential_m2s2[j+1];high=min(phi,c.half_geopotential_m2s2[j])
            if high>low:integral+=(high-low)/(rd*T[j]*(1+coef*q[j]))
        self.assertAlmostEqual(c.log_pressure(phi),math.log(100000)-integral,places=13)

    def test_supplied_inputs_remain_immutable(self):
        t=np.ones(29)*280;q=np.ones(29)*.005;a=np.zeros(138);b=np.linspace(0,1,138)
        original=[x.copy() for x in (t,q,a,b)]
        hybrid_column(math.log(100000),0,t,q,a,b,first_level=109,timestamp_UTC=TIME,latitude=47,longitude=15.5,source='ORACLE',source_sha256='a'*64)
        for before,after in zip(original,(t,q,a,b)):np.testing.assert_array_equal(before,after)

    def test_invalid_surface_units_missing_levels_and_q_are_rejected(self):
        for kwargs in ({'ps':1000},{'q':-.01},{'q':math.nan},{'T':80},{'T':[280]*28}):
            with self.assertRaises(ValueError):column(**kwargs)

    def test_invalid_hybrid_coefficients_are_rejected(self):
        for bad in ('reversed','bottom','pv_length'):
            a=np.zeros(138);b=np.linspace(0,1,138)
            if bad=='reversed':b=b[::-1]
            elif bad=='bottom':b[-1]=.99
            else:a=a[:-1]
            with self.assertRaises(ValueError):
                hybrid_column(math.log(100000),0,[280]*29,[.005]*29,a,b,first_level=109,timestamp_UTC=TIME,latitude=47,longitude=15.5,source='ORACLE',source_sha256='a'*64)


class SpatialAndReferenceContracts(unittest.TestCase):
    def test_two_column_isothermal_has_independent_blended_integral(self):
        a,b=column(T=270,q=.003,lat=47),column(T=290,q=.009,ps=96000,lat=47.25)
        h=700.;r=transfer_pressure([a,b],[10,10],target(h),timestamp_UTC=TIME)
        rd,coef=GASES[a.gas];top=min(a.domain[1],b.domain[1]);phi=h*G0
        anchor=(math.log(100000)+math.log(96000))/2-top/rd*(1/(270*(1+coef*.003))+1/(290*(1+coef*.009)))/2
        expected=math.exp(anchor+(top-phi)/(rd*280*(1+coef*.006)))
        self.assertAlmostEqual(r['pressure_Pa'],expected,delta=2e-9)
        self.assertEqual(r['target_layer_T_K'],280.)
        self.assertAlmostEqual(r['target_layer_q_kgkg'],.006,places=15)
        self.assertEqual(r['water_saturation_admissibility'],'NOT_CHECKED_BY_VERTICAL_TRANSFER')
        self.assertEqual(sum(c['weight'] for c in r['active_columns']),1.)
        self.assertFalse(r['pressure_model_qualified'])

    def test_four_column_permutation_keeps_pressure_and_weights(self):
        cs=[column(T=275+i,lat=47+i*.25) for i in range(4)]
        r=transfer_pressure(cs,[2,4,8,16],target(500),timestamp_UTC=TIME)
        s=transfer_pressure(cs[::-1],[16,8,4,2],target(500),timestamp_UTC=TIME)
        self.assertAlmostEqual(r['pressure_Pa'],s['pressure_Pa'],delta=1e-9)

    def test_zero_distance_uses_that_column_only(self):
        a,b=column(lat=47),column(T=290,lat=47.25)
        r=transfer_pressure([a,b],[0,3],target(500),timestamp_UTC=TIME)
        self.assertEqual(len(r['active_columns']),1)
        self.assertAlmostEqual(r['pressure_Pa'],math.exp(a.log_pressure(500*G0)),delta=1e-9)

    def test_below_surface_is_blocked_not_interpolated_through_ground(self):
        high=column(ground=1999)
        with self.assertRaises(SourceBlocked):high.log_pressure(1596*G0)
        with self.assertRaisesRegex(SourceBlocked,'AIR_DOMAIN'):
            transfer_pressure([high],[10],target(1596),timestamp_UTC=TIME)

    def test_source_geometry_can_select_lower_neighbor_without_station_pressure(self):
        high,low=column(ground=1999,lat=46.75),column(ground=1450,lat=47)
        r=transfer_pressure([high,low],[2,15],target(1596),timestamp_UTC=TIME)
        self.assertEqual(r['rejected_columns'],1);self.assertEqual(r['eligible_columns'],1)
        self.assertAlmostEqual(r['pressure_Pa'],math.exp(low.log_pressure(1596*G0)),delta=1e-9)

    def test_ground_is_available_only_as_explicit_sensitivity(self):
        c=column()
        with self.assertRaises(SourceBlocked):transfer_pressure([c],[1],target(366,'STATION_GROUND'),timestamp_UTC=TIME)
        r=transfer_pressure([c],[1],target(366,'STATION_GROUND'),timestamp_UTC=TIME,allow_ground_diagnostic=True)
        self.assertEqual(r['target_role'],'GROUND_SENSITIVITY_NOT_SENSOR')
        self.assertFalse(r['sensor_height_history_qualified'])

    def test_geometric_height_requires_explicit_approximation_and_verified_datum(self):
        with self.assertRaises(SourceBlocked):target_geopotential(target(366,kind='GEOMETRIC_M'))
        value,scope=target_geopotential(target(366,kind='GEOMETRIC_M'),allow_constant_g_geometric=True)
        self.assertEqual(value,366*G0);self.assertIn('APPROXIMATION',scope)
        for t in (target(366,verified=False),target(366,datum='WGS84_ELLIPSOID')):
            with self.assertRaises(SourceBlocked):target_geopotential(t,allow_constant_g_geometric=True)

    def test_time_gas_distance_and_duplicate_columns_cannot_be_mixed(self):
        a,b=column(lat=47),column(lat=47.25)
        for cs,dist,stamp in (([a,b],[1,-1],TIME),([a,a],[1,2],TIME),
                ([a,dataclasses.replace(b,timestamp_UTC='2019-02-01T00:00')],[1,2],TIME),
                ([a,column(gas='ECMWF_PUBLISHED_APPROXIMATION',lat=47.25)],[1,2],TIME)):
            with self.assertRaises(ValueError):transfer_pressure(cs,dist,target(500),timestamp_UTC=stamp)


if __name__=='__main__':unittest.main()
