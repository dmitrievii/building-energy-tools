import dataclasses
import datetime as dt
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from p9_3b3_joint_bounds import joint_domain_bounds
from p9_3b3_generator import ThermoDonor,generate
from p9_3b3_pressure_diagnostics import pressure_from_msl,with_legacy_pressure,score_pressure_diagnostics
from p9_3b3_source_time_support import parse_ascii_array,evaluate_support,fetch_time_support
from p9_3b3_thermodynamics import relative_humidity,q_saturation
from test_p9_3b3_joint_solver import fixture
from p9_3b3_at_de_ch_validation import _assert_pressure_alignment,_generate_days,empty_observations
from p9_3b3_joint_solver import SolverPolicy
from p9_3b3_repair_acceptance import compare


class JointOuterBounds(unittest.TestCase):
    def test_120_constructed_states_never_falsely_certified(self):
        rng=np.random.default_rng(20261021)
        for phase in ('WATER','WATER_ICE'):
            for _ in range(60):
                n=8;lo=rng.uniform(255,285,n);hi=lo+rng.uniform(0,12,n)
                T=rng.uniform(lo,hi);P=rng.uniform(80000,104000,n)
                q=q_saturation(T,P)*rng.uniform(0,1,n);w=rng.uniform(.1,1,n);w/=w.sum()
                Q=float(w@q);R=float(w@relative_humidity(T,P,q,phase))
                b=joint_domain_bounds(lo,hi,P,Q,R,phase,weights=w)
                self.assertNotEqual(b['status'],'CERTIFIED_INFEASIBLE',b)
                self.assertLessEqual(b['RH_mean_lower_pp'],R+1e-7)
                self.assertGreaterEqual(b['RH_mean_upper_pp'],R-1e-7)

    def test_cold_low_q_high_RH_is_universally_impossible(self):
        b=joint_domain_bounds([270]*24,[280]*24,[97000]*24,.0015,80,'WATER_ICE')
        self.assertEqual(b['reason'],'RH_ABOVE_JOINT_DOMAIN_GLOBAL_UPPER')

    def test_warm_high_q_low_RH_is_universally_impossible(self):
        b=joint_domain_bounds([278]*24,[283]*24,[97000]*24,.0075,50)
        self.assertEqual(b['reason'],'RH_BELOW_JOINT_DOMAIN_GLOBAL_LOWER')

    def test_zero_mass_has_zero_RH(self):
        b=joint_domain_bounds([265]*4,[280]*4,[97000]*4,0,0)
        self.assertNotEqual(b['status'],'CERTIFIED_INFEASIBLE')
        self.assertEqual(joint_domain_bounds([265]*4,[280]*4,[97000]*4,0,80)['status'],'CERTIFIED_INFEASIBLE')

    def test_all_donors_bound_not_only_eight(self):
        T,q,t,p=fixture();t=dataclasses.replace(t,q_mean_kgkg=.00001,RH_mean_pct=80)
        donors=[ThermoDonor('2019-01-'+str(i).zfill(2),tuple(T),tuple(q),p) for i in range(1,13)]
        r,_=generate([t],donors)
        self.assertEqual(r[0]['status'],'CERTIFIED_INFEASIBLE')
        self.assertEqual(len(r[0]['trials']),12)
        self.assertTrue(all(x['certificate']['domain']=='FULL_SOURCE_TMIN_TMAX_RELAXING_DONOR_PRIOR' for x in r[0]['trials']))


class PressureRepair(unittest.TestCase):
    def test_standard_dry_atmosphere_at_1000m(self):
        p=float(pressure_from_msl(101325.,281.65,0,1000))
        # ISA tabulation uses Rd=287.05287; this project fixes Rd=287.05.
        self.assertAlmostEqual(p,89874.56,delta=.2)
        self.assertEqual(float(pressure_from_msl(101325.,280,.005,0)),101325.)
        self.assertGreater(float(pressure_from_msl(101325.,281.65,.01,1000)),p)

    def test_msl_wrong_units_and_invalid_height_rejected(self):
        for p,z in ((1013.,100),(101325.,5000)):
            with self.assertRaises(ValueError):pressure_from_msl(p,280.,.005,z)

    def test_external_target_pressure_independent_of_donor_and_immutable(self):
        T,q,t,p=fixture();external=dataclasses.replace(p,values_Pa=tuple(x+100 for x in p.values_Pa),reference_date=t.date)
        d=ThermoDonor('2019-01-10',tuple(T),tuple(q),p)
        r,_=generate([t],[d],pressure_by_date={t.date:external})
        self.assertEqual(r[0]['status'],'EXACT_DEFINED_OPERATORS')
        self.assertEqual(r[0]['p_Pa'],list(external.values_Pa))
        self.assertNotEqual(r[0]['p_Pa'],list(d.pressure.values_Pa))
        self.assertEqual(r[0]['pressure_time_alignment'],'EXTERNAL_TARGET_DAY_FIXED')
        with self.assertRaisesRegex(ValueError,'TIME_REFERENCE'):
            generate([t],[d],pressure_by_date={t.date:p})
        with self.assertRaisesRegex(ValueError,'DATES'):
            generate([t],[d],pressure_by_date={})

    def test_target_observed_pressure_prohibited(self):
        T,q,t,p=fixture();d=ThermoDonor('2019-01-10',tuple(T),tuple(q),p)
        observed=dataclasses.replace(p,mode='OBSERVED_SITE_VALIDATION_ONLY',reference_date=t.date)
        with self.assertRaisesRegex(ValueError,'OBSERVATIONS'):
            generate([t],[d],pressure_by_date={t.date:observed})

    def test_legacy_pressure_override_does_not_mutate_original(self):
        from p9_2a_joint_weather_regimes import Day,FIELDS
        v={k:0. for k in FIELDS};v.update(temperature_2m=10.,dew_point_2m=5.,relative_humidity_2m=70.,surface_pressure=970.)
        d=Day(dt.date(2019,1,1),tuple(dict(v) for _ in range(24)),'a'*64)
        _,_,t,p=fixture();p=dataclasses.replace(p,reference_date=t.date)
        changed=with_legacy_pressure(d,p)
        self.assertEqual(d.vectors[0]['surface_pressure'],970.)
        self.assertNotEqual(changed.original_sha256,d.original_sha256)
        for a,b in zip(d.vectors,changed.vectors):
            self.assertEqual({k:v for k,v in a.items() if k!='surface_pressure'},
                             {k:v for k,v in b.items() if k!='surface_pressure'})

    def test_hourly_pressure_contract_detects_wrong_day_or_donor(self):
        _,_,t,p=fixture();p=dataclasses.replace(p,reference_date=t.date)
        h={t.date+'T00:00':{'p_hPa':p.values_Pa[0]/100}}
        _assert_pressure_alignment(h,{t.date:p})
        h[t.date+'T00:00']['p_hPa']+=1
        with self.assertRaisesRegex(AssertionError,'IDENTICAL_TARGET_DAY'):
            _assert_pressure_alignment(h,{t.date:p})

    def test_daily_control_conditioning_is_explicit(self):
        T,q,t,p=fixture();p=dataclasses.replace(p,reference_date=t.date)
        d=ThermoDonor('2019-01-10',tuple(T),tuple(q),p)
        rows,summary=_generate_days([t],[d],7313,None,SolverPolicy(),pressure_by_date={t.date:p})
        self.assertEqual(summary['counts'],{'EXACT_DEFINED_OPERATORS':1})
        self.assertEqual(summary['selection_conditioning'],'INDEPENDENT_DAYS_NO_PREVIOUS_DAY_SELECTION')

    def test_missing_pressure_diagnostics_keep_18_cells(self):
        obs={c:empty_observations(c) for c in ('AT','DE','CH')}
        r=score_pressure_diagnostics([],obs)
        self.assertEqual(len(r['cells']),18)
        self.assertTrue(all(c['status']=='COVERAGE_BLOCKED' for c in r['cells']))

    def test_pressure_diagnostic_hour_mean_and_common_hours(self):
        obs={c:empty_observations(c) for c in ('AT','DE','CH')}
        obs['CH']['time_support']='PRECEDING_HOUR_MEAN_END_STAMP'
        obs['CH']['cells']['winter']['p_hPa']={'2021-02-01T01:00':850}
        keys=('DATE_ALIGNED_ERA5_GRID','MSL_SITE_FIXED_LAPSE_PROVISIONAL','MSL_SITE_ISOTHERMAL_SENSITIVITY')
        p={'country':'CH','period':'winter','hourly':{'2021-02-01T00:00':dict.fromkeys(keys,848.),
                                                    '2021-02-01T01:00':dict.fromkeys(keys,852.)}}
        r=score_pressure_diagnostics([p],obs)
        cells=[c for c in r['cells'] if c['country']=='CH' and c['period']=='winter']
        self.assertTrue(all(c['matched_hours']==1 and c['MAE_hPa']==0 for c in cells))


class NativeTimeRepair(unittest.TestCase):
    def meta(self,bounds=True):
        return {'variable':'tas','year':2013,'status':'SOURCE_METADATA_READ','url':'https://example.test/tas.nc.das',
            'blocks':{'time':{'calendar':'365_day','units':'days since 1850-01-01 0:0:0.0',**({'bounds':'time_bnds'} if bounds else {})}}}

    def axis(self):return (2013-1850)*365+np.arange(365)+.5

    def test_dangling_bounds_attribute_cannot_qualify_intervals(self):
        b=evaluate_support(self.meta(),self.axis(),'Dataset { Float64 time[time = 365]; }')
        self.assertFalse(b['interval_semantics_verified'])
        self.assertEqual(b['bounds_status'],'DANGLING_ATTRIBUTE_VARIABLE_ABSENT_IN_DDS')

    def test_real_bounds_checked_separately_from_coordinate_labels(self):
        a=self.axis();dds='Dataset { Float64 time_bnds[time=365][bnds=2]; }'
        b=evaluate_support(self.meta(),a,dds,np.c_[a-.5,a+.5])
        self.assertTrue(b['interval_semantics_verified'])
        with self.assertRaisesRegex(ValueError,'BOUNDS'):
            evaluate_support(self.meta(),a,dds,np.c_[a-.5,a+1.5])
        with self.assertRaisesRegex(ValueError,'NOON'):
            evaluate_support(self.meta(),a-.5,dds)

    def test_ascii_indexed_and_flat_arrays(self):
        body='Dataset {}\n---------------------------------------------\ntime[3]\n1, 2, 3\n'
        self.assertEqual(parse_ascii_array(body,'time',(3,)).tolist(),[1,2,3])
        body='Dataset {}\n---------------------------------------------\ntime_bnds[2][2]\n[0], 1, 2\n[1], 2, 3\n'
        self.assertEqual(parse_ascii_array(body,'time_bnds',(2,2)).tolist(),[[1,2],[2,3]])

    def test_time_fetch_bounds_absent_is_recorded_not_inferred(self):
        a=self.axis()
        def fetch(url):
            if url.endswith('.dds'):return b'Dataset { Float64 time[time=365]; }'
            return ('Dataset {}\n---------------------------------------------\ntime[365]\n'+', '.join(map(str,a))+'\n').encode()
        b=fetch_time_support(self.meta(),fetch)
        self.assertEqual(b['n_time_coordinates'],365)
        self.assertFalse(b['interval_semantics_verified'])
        self.assertEqual(len(b['source_responses']),2)


class IntegrationRepair(unittest.TestCase):
    def test_real_runner_seals_and_scores_same_pressure_for_both_algorithms(self):
        from p9_2a_joint_weather_regimes import Day,FIELDS
        from p9_3b3_at_de_ch_validation import run
        T,_,_,_=fixture()
        def era(cache,lat,lon,start,end):
            vs=[]
            for t in T:
                v=dict.fromkeys(FIELDS,0.)
                v.update(temperature_2m=float(t-273.15),dew_point_2m=float(t-278.15),
                         relative_humidity_2m=70.,surface_pressure=970.)
                vs.append(v)
            return [Day(dt.date.fromisoformat(start),tuple(vs),'a'*64)],{
                'selected_cell_latitude':lat,'selected_cell_longitude':lon,
                'canonical_hourly_weather_and_selected_cell_sha256':'b'*64}
        def preflight(cache,out):
            obs={c:empty_observations(c) for c in ('AT','DE','CH')}
            path=cache.root/'test_observations_PRIVATE.json';path.write_text(json.dumps(obs))
            return path,{'protocol_sha256':'c'*64,'cells':{c:{'site':{'lat':47.,'lon':15.,'height_m':366.}} for c in obs}}
        def msl(*args):
            return {'2021-02-01T'+f'{h:02d}:00':1013. for h in range(24)},{'sha256':'d'*64}
        with tempfile.TemporaryDirectory() as d,patch('p9_3b3_at_de_ch_validation.PERIODS',(('winter','2021-02-01','2021-02-01'),)),\
             patch('p9_3b3_at_de_ch_validation._era5',side_effect=era),\
             patch('p9_3b3_at_de_ch_validation.preflight',side_effect=preflight),\
             patch('p9_3b3_pressure_diagnostics.source_msl',side_effect=msl):
            root=Path(d);r=run(root/'private',root/'public')
            p=json.loads((root/'private/predictions_PRIVATE_DO_NOT_PUBLISH.json').read_text())
            primary=[m for m in p['members'] if m['country']=='AT' and m['seed']==7313 and m['method'] in ('B3_STRICT','P93A_DAILY_CONTROL')]
            self.assertEqual(len(primary),2)
            self.assertTrue(all(len(m['hourly'])==24 for m in primary))
            self.assertTrue(all(v['p_hPa']==970. for m in primary for v in m['hourly'].values()))
            self.assertTrue(r['previously_revealed_2021_windows'])
            self.assertFalse(r['operational_ready'])
            self.assertEqual(r['daily_selection_conditioning'],'INDEPENDENT_DAYS_BOTH_METHODS')
            self.assertEqual(len(r['pressure_diagnostics']['cells']),18)


if __name__=='__main__':unittest.main()
