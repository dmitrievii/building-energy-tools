"""Scalar objective replay and compact audit of a complete CD2 result folder."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import lzma
import math
from pathlib import Path

from p9_3b3_cd1_run import write_new
from p9_3b3_cd2_run import guard, load_registered_inputs, case_inputs, ROOT
from p9_3b3_cd2_solvers import VARIANTS
from p9_3b3_c2_validation import validate_projection
from p9_3b3_state_validation import _es


def scalar_objective(T, p, q, source):
    """Independent scalar gas law, weighted diagnostics and quadratic prior."""
    base = source['base_case']; target = base['target']; n = len(T)
    donorT, donorq = base['donor_T'], base['donor_q']
    tmin, tmax = target['Tmin_K'], target['Tmax_K']
    if tmax == tmin:
        T0 = [tmin]*n
    else:
        low, width = min(donorT), max(donorT)-min(donorT)
        T0 = [tmin+(tmax-tmin)*(t-low)/width for t in donorT]
    eps = 287.05/461.5
    phase = 'WATER_ICE'
    RH = [100*qq*pp/(eps+(1-eps)*qq)/_es(t,phase,'MURPHY_KOOP_2005') for t,pp,qq in zip(T,p,q)]
    def mean(values, name):
        weights = target[name]
        total = math.fsum(weights)
        return math.fsum(w*x for w,x in zip(weights, values))/total
    dq = 1000*(mean(q,'q_weights')-target['q_mean_kgkg'])
    dr = mean(RH,'RH_weights')-target['RH_mean_pct']
    data = .5*(dq*dq+(dr/5)**2)
    qscale = max(.001,math.sqrt(math.fsum(z*z for z in donorq)/n))
    a = [(t-t0)/2 for t,t0 in zip(T,T0)]
    b = [(z-z0)/qscale for z,z0 in zip(q,donorq)]
    shape = math.fsum(z*z for z in a+b)/n
    if n > 1:
        shape += math.fsum((v[i+1]-v[i])**2 for v in (a,b) for i in range(n-1))/((n-1)*(24/n)**2)
    return {'total':data+.01*shape,'data_metric':data,'shape_unweighted':shape,'shape_weighted':.01*shape}


def _range(values):
    if not values:return None
    s=sorted(values)
    return {'min':s[0],'median':s[len(s)//2] if len(s)%2 else (s[len(s)//2-1]+s[len(s)//2])/2,'max':s[-1]}


def audit(folder):
    folder=Path(folder)
    protocol=guard();inputs,baseline,ci=load_registered_inputs(protocol)
    sources={r['case_id']:r for r in inputs}
    summary=json.loads((folder/'CD2_summary.json').read_text())
    if (summary['case_count'],summary['method_results'],summary['optimizer_trials']) != (63,252,396):
        raise AssertionError('CD2_INCOMPLETE_SUMMARY')
    for name,sha in summary['code_sha256'].items():
        if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()!=sha:
            raise AssertionError('CD2_AUDIT_EXECUTED_CODE_DIFFERS')
    full=[json.loads(p.read_text()) for p in sorted(folder.glob('*_CD2_case.json'))]
    if len(full)!=63 or {r['case_id'] for r in full}!=set(sources):
        raise AssertionError('CD2_AUDIT_CASE_CENSUS')
    rows=[];errors=[];valid_trials=Counter();validated_states=Counter();trial_counts=Counter();same_control=0;max_objective_error=0.
    for case in full:
        source=sources[case['case_id']]
        args,kwargs,target,pressure=case_inputs(source,baseline)
        if len(case['variants'])!=4 or [v['variant']['id'] for v in case['variants']]!=[v['id'] for v in VARIANTS]:
            raise AssertionError('CD2_AUDIT_VARIANT_CENSUS')
        starts=None
        for result in case['variants']:
            name=result['variant']['id'];raw=result['frozen_result']
            trial_counts[name]+=len(result['trials'])
            initial=[t['initial_x_sha256'] for t in result['trials']]
            if starts is not None and starts!=initial:raise AssertionError('CD2_AUDIT_STARTS_DIFFER')
            starts=initial
            if name=='FROZEN_C2':
                if not result['same_runtime_control_exactly_equal']:raise AssertionError('CD2_CONTROL_CHANGED')
                same_control+=1
            for trial in result['trials']:
                if trial['algorithm_error']:errors.append([case['case_id'],name,trial['trial_index'],trial['algorithm_error']])
                if trial['physical_admissibility']=='VALIDATED':valid_trials[name]+=1
            if 'T_K' not in raw:continue
            validated=validate_projection(raw['T_K'],raw['p_Pa'],raw['q_kgkg'],args[2],pressure.values_Pa,args[0],
                target.q_weights,target.RH_weights,target.T_weights)
            validated_states[name]+=1
            independent=scalar_objective(raw['T_K'],raw['p_Pa'],raw['q_kgkg'],source)
            mismatch=abs(independent['total']-raw['objective']['total'])/max(1.,abs(independent['total']))
            max_objective_error=max(max_objective_error,mismatch)
            if mismatch>protocol['comparison']['F_numerical_tie_relative']:
                raise AssertionError('CD2_INDEPENDENT_SCALAR_OBJECTIVE_MISMATCH')
            selected=result['selected_trial_index']
            if selected is None:continue
            t=result['trials'][selected];history=t['iteration_journal'];tail=history[-10:]
            ref=case['variants'][0]['frozen_result']
            F,F0=independent['total'],ref['objective']['total']
            tie=1e-10*max(1.,abs(F0))
            f1=next(k for k in t['first_order'] if k['active_tolerance']==1e-6)
            rows.append({'case_id':case['case_id'],'family':case['family'],'variant':name,
                'selected_trial':selected,'solver_success':t['solver_success'],'solver_status':t['solver_status'],
                'iterations':t['iterations'],'objective':raw['objective'],'independent_scalar_F':independent['total'],
                'delta_F_vs_control':raw['objective']['total']-F0,
                'comparison':'NUMERICAL_TIE' if abs(raw['objective']['total']-F0)<=tie else 'LOWER_F' if raw['objective']['total']<F0 else 'HIGHER_F',
                'stationarity_Linf_by_tolerance':{str(k['active_tolerance']):k['stationarity_Linf'] for k in t['first_order']},
                'primal_violation_scaled':f1['primal_violation_scaled'],'complementarity_Linf':f1['complementarity_Linf'],
                'phase_crossings_in_trace':sum(h.get('phase_crossings',0) for h in history),
                'final_phase_distance_K':t['final']['min_distance_to_freezing_K'],
                'last_ten_objective_range':max(h['objective_total'] for h in tail)-min(h['objective_total'] for h in tail),
                'max_T_difference_from_control_K':max(abs(x-y) for x,y in zip(raw['T_K'],ref['T_K'])),
                'max_q_difference_from_control_gkg':1000*max(abs(x-y) for x,y in zip(raw['q_kgkg'],ref['q_kgkg'])),
                'source_q_adjustment_gkg':1000*validated['daily_residuals']['q_mean_kgkg'],
                'source_RH_adjustment_pp':validated['daily_residuals']['RH_mean_pp']})
    aggregates={}
    for variant in VARIANTS:
        name=variant['id'];selected=[r for r in rows if r['variant']==name]
        if trial_counts[name]!=99 or valid_trials[name]!=summary['variants'][name]['physically_valid_trials']:
            raise AssertionError('CD2_AUDIT_TRIAL_CENSUS')
        trials=[t for c in full for v in c['variants'] if v['variant']['id']==name for t in v['trials']]
        FD={}
        for step in (1e-5,5e-6):
            checks=[d for t in trials for d in t.get('finite_differences',[]) if d['dimensionless_step']==step]
            FD[str(step)]={
                'checked_trial_count':len(checks),
                'objective_max_relative_error':max((c['objective_max_relative_error'] for c in checks if c['objective_max_relative_error'] is not None),default=None),
                'constraint_Jacobian_max_relative_error':max((c['constraint_Jacobian_max_relative_error'] for c in checks if c['constraint_Jacobian_max_relative_error'] is not None),default=None),
                'unavailable_columns':sum(len(c['unavailable_columns']) for c in checks)}
        aggregates[name]={
            'selected_count':len(selected),'independently_validated_states':validated_states[name],
            'physically_valid_trials':valid_trials[name],
            'solver_status_counts':dict(Counter(t['solver_status'] for t in trials)),
            'finite_differences':FD,
            'first_order_LS_fit_failures':sum(not k['least_squares_success'] for t in trials for k in t.get('first_order',[])),
            'callback_trace_semantics':'PER_FUNCTION_EVALUATION_PROBES_NOT_ACCEPTED_ITERATIONS' if variant['algorithm']=='COBYQA' else 'PER_SLSQP_MAJOR_ITERATION',
            'stationarity_Linf_tau_1e_6':_range([r['stationarity_Linf_by_tolerance']['1e-06'] for r in selected]),
            'objective_delta_vs_control':_range([r['delta_F_vs_control'] for r in selected]),
            'selected_comparison_counts':dict(Counter(r['comparison'] for r in selected)),
            'max_T_difference_from_control_K':max((r['max_T_difference_from_control_K'] for r in selected),default=None),
            'max_q_difference_from_control_gkg':max((r['max_q_difference_from_control_gkg'] for r in selected),default=None),
            'max_primal_violation_scaled':max((r['primal_violation_scaled'] for r in selected),default=None),
            'max_complementarity_Linf':max((r['complementarity_Linf'] for r in selected),default=None)}
    return {'phase':'P9.3B3_CD2_SCALAR_AUDIT','summary':{k:v for k,v in summary.items() if k!='cases'},
        'same_runtime_control_exactly_equal':same_control,'audited_trial_counts':dict(trial_counts),
        'additional_unobserved_control_optimizer_calls':trial_counts['FROZEN_C2'],
        'total_optimizer_invocations_including_unobserved_control':sum(trial_counts.values())+trial_counts['FROZEN_C2'],
        'max_relative_scalar_objective_error':max_objective_error,
        'aggregates':aggregates,'algorithm_errors':errors,'selected_trials':rows,
        'independent_accuracy':'NOT_QUALIFIED','local_optimum_certified':False,'global_optimum_certified':False,
        'operational_ready':False},full,summary


def save(folder, output_json, output_archive=None):
    result,full,summary=audit(folder)
    if output_archive:
        archive=Path(output_archive).resolve()
        with archive.open('xb') as stream:
            with lzma.LZMAFile(stream,'w',preset=6) as compressed:
                value=json.dumps({'CD2_summary':summary,'case_journals':full},ensure_ascii=False,separators=(',',':'),allow_nan=False)
                compressed.write(value.encode())
        result['replay_archive']={'path':str(archive.relative_to(ROOT)), 'bytes':archive.stat().st_size,
            'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'format':'UTF8_JSON_XZ_LZMA2'}
    write_new(output_json,result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--archive')
    a=p.parse_args();r=save(a.input,a.out,a.archive)
    print(json.dumps({k:v for k,v in r.items() if k not in ('selected_trials','summary')}))
