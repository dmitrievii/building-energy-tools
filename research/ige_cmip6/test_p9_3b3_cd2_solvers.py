"""CD2 independent mathematical oracles and same-problem contracts."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.optimize import minimize_scalar

import p9_3b3_c2_projection as frozen
import p9_3b3_cd2_solvers as cd2
from p9_3b3_cd2_run import guard, load_registered_inputs, case_inputs, run, compare_to_control
from p9_3b3_cd1_run import write_new
from p9_3b3_thermodynamics import saturation
from test_p9_3b3_c2_projection import fixture, scalar_q, scalar_rh
from audit_p9_3b3_CD2 import scalar_objective
import audit_p9_3b3_CD2 as scalar_audit


class EquivalentCoordinates(unittest.TestCase):
    def setUp(self):
        self.c = cd2.Coordinates([280., 0.], [2., 8.], [[278., 282.], [0., 16.]])

    def test_invertible_map_and_bounds(self):
        np.testing.assert_array_equal(self.c.scaled_bounds, [[-1., 1.], [0., 2.]])
        for x in ([278., 0.], [282., 16.], [279.3, 3.2]):
            np.testing.assert_allclose(self.c.x(self.c.y(x)), x, rtol=0, atol=1e-14)

    def test_nonpositive_or_nonfinite_scale_is_rejected(self):
        for D in ([0., 1.], [-1., 1.], [np.inf, 1.], [1.]):
            with self.assertRaises(ValueError):
                cd2.Coordinates([0., 0.], D, [[-1., 1.], [-1., 1.]])

    def test_objective_value_and_gradient_chain_rule(self):
        def f(x):
            return x[0]**2+3*x[0]*x[1]+2*x[1]**2, np.array([2*x[0]+3*x[1], 3*x[0]+4*x[1]])
        y=np.array([.2, .7]); x=np.array([280.4, 5.6])
        F,g=self.c.objective(f)(y)
        self.assertEqual(F, f(x)[0])
        np.testing.assert_allclose(g, [2*(2*x[0]+3*x[1]), 8*(3*x[0]+4*x[1])])
        h=1e-5
        numeric=[(self.c.objective(f)(y+np.eye(2)[j]*h)[0]-self.c.objective(f)(y-np.eye(2)[j]*h)[0])/(2*h) for j in range(2)]
        np.testing.assert_allclose(g,numeric,rtol=1e-7)

    def test_constraint_value_and_Jacobian_positive_scaling(self):
        constraints=[{'type':'ineq','fun':lambda x:np.array([x[0]*x[1]-10]),
                      'jac':lambda x:np.array([[x[1],x[0]]])}]
        mapped=self.c.constraints(constraints,[4.])[0]
        y=np.array([.1,.5]); x=self.c.x(y)
        self.assertEqual(mapped['fun'](y)[0],(x[0]*x[1]-10)/4)
        np.testing.assert_allclose(mapped['jac'](y),[[x[1]/2,2*x[0]]])
        for scale in (0.,-1.,np.inf):
            with self.assertRaises(ValueError):self.c.constraints(constraints,[scale])

    def test_no_clipping_of_transformed_points(self):
        np.testing.assert_array_equal(self.c.x([2.,3.]),[284.,24.])

    def test_freezing_branch_and_adjacent_floats_are_preserved(self):
        c=cd2.Coordinates([272.9],[2.],[[271.,275.]])
        for t in [np.nextafter(273.15,-np.inf),273.15,np.nextafter(273.15,np.inf)]:
            x=c.x(c.y([t]))[0]
            self.assertEqual(x,t)
            self.assertEqual(saturation(x,'WATER_ICE'),saturation(t,'WATER_ICE'))


class AnalyticOptimizerOracles(unittest.TestCase):
    def test_quadratic_with_equality_and_active_bound(self):
        # Projection of (-1,2) onto x+y=1, 0<=x,y<=0.7 is (0.3,0.7).
        def f(x):return .5*float((x-[-1.,2.])@(x-[-1.,2.])),x-[-1.,2.]
        bounds=np.array([[0.,.7],[0.,.7]])
        c=cd2.Coordinates([.5,0.],[2.,.8],bounds)
        cons=[{'type':'eq','fun':lambda x:x.sum()-1,'jac':lambda x:np.ones(2)}]
        for alg in ('SLSQP','COBYQA'):
            r,counts=cd2.solve_equivalent(f,np.array([.4,.6]),bounds,cons,c,[2.],alg)
            np.testing.assert_allclose(r.x,[.3,.7],atol=2e-6)
            self.assertAlmostEqual(f(r.x)[0],1.69,delta=1e-6)
            if alg=='COBYQA':self.assertEqual(counts['constraint_Jacobian_calls'],0)

    def test_scalar_thermodynamic_minimum_in_original_units(self):
        T,q,t,p=fixture();t=replace(t,RH_mean_pct=90.)
        qscale=max(.001,abs(q[0]))
        def f(z):
            a=(z-t.q_mean_kgkg)*1000
            b=(scalar_rh(T[0],p.values_Pa[0],z)-90)/5
            return .5*(a*a+b*b)+.01*((z-q[0])/qscale)**2
        oracle=minimize_scalar(f,bounds=(0,scalar_q(T[0],p.values_Pa[0],100)),
            method='bounded',options={'xatol':1e-14})
        for v in cd2.VARIANTS:
            r=cd2.solve_variant(T,q,t,p,v['id'],donor_date='2019-02-01')
            raw=r['frozen_result']
            self.assertAlmostEqual(raw['q_kgkg'][0],oracle.x,delta=2e-8)
            self.assertAlmostEqual(raw['objective']['total'],oracle.fun,delta=1e-6)
            self.assertFalse(r['local_optimum_certified'])
            self.assertTrue(all(x['physical_admissibility']=='VALIDATED' for x in r['trials']))

    def test_independent_optimizer_receives_scalar_objective_without_derivatives(self):
        def f(x):return float(x@x),2*x
        c=cd2.Coordinates([0.],[2.],[[-1.,1.]])
        from scipy.optimize import OptimizeResult
        def fake(fun,x0,**kw):
            self.assertEqual(kw['method'],'COBYQA')
            self.assertNotIn('jac',kw)
            self.assertIsInstance(fun(x0),float)
            self.assertEqual(kw['options'],cd2.COBYQA_OPTIONS)
            return OptimizeResult(x=np.array([.1]),success=True,nit=1,nfev=1,status=0,message='fixture')
        with patch.object(cd2,'minimize',side_effect=fake):
            r,_=cd2.solve_equivalent(f,np.array([.2]),c.bounds,[],c,[],'COBYQA')
        self.assertAlmostEqual(r.x[0],.2)


class IndependentScalarAuditOracles(unittest.TestCase):
    def test_relative_archive_export_preserves_result_and_refuses_overwrite(self):
        import json,lzma
        with tempfile.TemporaryDirectory(dir=scalar_audit.ROOT) as folder:
            directory=Path(folder)
            archive=(directory/'replay.json.xz').relative_to(scalar_audit.ROOT)
            output=directory/'audit.json'
            with patch.object(scalar_audit,'audit',return_value=({'checked':True},[{'case':'fixture'}],{'complete':True})):
                r=scalar_audit.save(directory,output,archive)
                self.assertEqual(r['replay_archive']['path'],str(archive))
                self.assertEqual(json.loads(lzma.decompress(archive.read_bytes()))['case_journals'],[{'case':'fixture'}])
                with self.assertRaises(FileExistsError):scalar_audit.save(directory,directory/'other.json',archive)

    def source(self,T,q,RH=None,qmean=None):
        n=len(T)
        return {'base_case':{'donor_T':list(T),'donor_q':list(q),'target':{
            'Tmin_K':min(T),'Tmax_K':max(T),'q_mean_kgkg':sum(q)/n if qmean is None else qmean,
            'RH_mean_pct':sum(scalar_rh(t,97000,z,'WATER_ICE') for t,z in zip(T,q))/n if RH is None else RH,
            'q_weights':[1/n]*n,'RH_weights':[1/n]*n}}}

    def test_zero_forward_residual_and_prior_has_zero_objective(self):
        T=[270.,273.15,280.];q=[.001,.002,.003]
        r=scalar_objective(T,[97000.]*3,q,self.source(T,q))
        self.assertAlmostEqual(r['total'],0.,delta=1e-24)

    def test_known_unit_data_residuals_in_original_gkg_and_pp(self):
        T=[280.];q=[.002]
        RH=scalar_rh(280.,97000.,.002,'WATER_ICE')
        r=scalar_objective(T,[97000.],q,self.source(T,q,RH=RH-5,qmean=.003))
        self.assertAlmostEqual(r['data_metric'],1.,places=12)
        self.assertEqual(r['shape_unweighted'],0.)
        self.assertAlmostEqual(r['total'],1.,places=12)

    def test_hand_computed_nonzero_shape_and_temporal_roughness(self):
        donor=[280.,281.,282.,283.];q0=[.002]*4
        T=[280.,282.,281.,283.];q=[.002,.0022,.0018,.002]
        source=self.source(donor,q0,RH=sum(scalar_rh(t,97000,z,'WATER_ICE') for t,z in zip(T,q))/4)
        r=scalar_objective(T,[97000.]*4,q,source)
        expected=(.5+.02)/4+(1.5+.06)/(3*6**2)
        self.assertAlmostEqual(r['shape_unweighted'],expected,places=12)
        self.assertAlmostEqual(r['total'],.01*expected,places=12)


class FrozenIntegration(unittest.TestCase):
    def test_registered_protocol_protects_139_files(self):
        p=guard();inputs,baseline,ci=load_registered_inputs(p)
        self.assertEqual(len(p['protected_control_sha256']),139)
        self.assertEqual((len(inputs),len(baseline),len(ci)),(63,189,63))

    def test_exact_forward_witness_never_calls_any_optimizer(self):
        T,q,t,p=fixture()
        for v in cd2.VARIANTS:
            with patch.object(frozen,'minimize') as original,patch.object(cd2,'minimize') as new:
                r=cd2.solve_variant(T,q,t,p,v['id'],donor_date='2019-02-01')
                original.assert_not_called();new.assert_not_called()
            self.assertEqual(r['frozen_result']['status'],'EXACT_SOURCE_PRESERVED')
            self.assertEqual(r['trials'],[])

    def test_all_variants_receive_identical_starts_and_unchanged_pressure(self):
        T,q,t,p=fixture(4);t=replace(t,RH_mean_pct=5.)
        starts=[];original=frozen.minimize
        for v in cd2.VARIANTS:
            r=cd2.solve_variant(T,q,t,p,v['id'],donor_date='2019-02-01')
            self.assertIs(frozen.minimize,original)
            self.assertTrue(r['inputs_unchanged'])
            starts.append([s['initial_x_sha256'] for s in r['trials']])
            if 'p_Pa' in r['frozen_result']:self.assertEqual(r['frozen_result']['p_Pa'],list(p.values_Pa))
            if v['id']=='FROZEN_C2':self.assertTrue(r['same_runtime_control_exactly_equal'])
        self.assertTrue(starts[0])
        self.assertTrue(all(s==starts[0] for s in starts))

    def test_algorithm_exception_is_retained_and_not_an_initial_state_fallback(self):
        T,q,t,p=fixture();t=replace(t,RH_mean_pct=90.)
        with patch.object(cd2,'minimize',side_effect=RuntimeError('synthetic solver failure')):
            r=cd2.solve_variant(T,q,t,p,'COBYQA_SCALED_XC',donor_date='2019-02-01')
        self.assertEqual(r['frozen_result']['status'],'UNRESOLVED')
        self.assertNotIn('T_K',r['frozen_result'])
        self.assertEqual(len(r['trials']),3)
        for s in r['trials']:
            self.assertIn('synthetic solver failure',s['algorithm_error'])
            self.assertEqual(s['physical_admissibility'],'REJECTED')
            self.assertIsNone(s['final_x'])
            self.assertIsNone(r['selected_trial_index'])

    def test_unregistered_variant_is_rejected(self):
        T,q,t,p=fixture()
        with self.assertRaises(ValueError):cd2.solve_variant(T,q,t,p,'OTHER',donor_date='2019-02-01')

    def test_output_directory_and_files_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'original.json';write_new(p,{'original':True})
            with self.assertRaises(FileExistsError):write_new(p,{'original':False})
            with self.assertRaises(FileExistsError):run(folder)

    def test_objective_comparison_is_not_accuracy_qualification(self):
        raw={'T_K':[280.],'q_kgkg':[.002],'objective':{'total':2.}}
        control={'frozen_result':raw}
        r=compare_to_control(control,control)
        self.assertEqual(r['classification'],'NUMERICAL_TIE')
        self.assertEqual(r['scientific_accuracy_interpretation'],'NONE')
        missing=compare_to_control({'frozen_result':{'status':'UNRESOLVED'}},control)
        self.assertEqual(missing['classification'],'NO_COMMON_VALIDATED_STATE')


if __name__=='__main__':unittest.main()
