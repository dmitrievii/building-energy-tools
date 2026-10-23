"""Independent scalar replay of TPA states, KKT and infeasibility duals.

Does not import the optimizer, vector thermodynamics or bound implementations.
Uses frozen scalar published saturation equations and independent validation.
The dual replay retains the explicit float64 guard; it is not an interval
arithmetic proof and does not qualify uncertain atmospheric inputs.
"""
from __future__ import annotations
from collections import Counter
import math

from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_c2_validation import validate_projection
from p9_3b3_state_validation import _es
from p9_3b3_tpa_contracts import DailyClimateConstraints, PressureTrajectory


EPS = 287.05/461.5
FORMULATION = 'MURPHY_KOOP_2005'


def cap(t, p):
    e = _es(t, 'WATER', FORMULATION)
    return EPS*e/(p-(1-EPS)*e)


def temperature_box(donor, target):
    dmin, dmax = min(donor), max(donor)
    t0 = ([target.Tmin_K]*24 if target.Tmin_K == target.Tmax_K else
          [target.Tmin_K+(target.Tmax_K-target.Tmin_K)*(v-dmin)/(dmax-dmin) for v in donor])
    fixed = set(range(24)) if target.Tmin_K == target.Tmax_K else {t0.index(min(t0)), t0.index(max(t0))}
    lo = [t if i in fixed else max(target.Tmin_K, t-2) for i, t in enumerate(t0)]
    hi = [t if i in fixed else min(target.Tmax_K, t+2) for i, t in enumerate(t0)]
    return t0, lo, hi


def replay_certificate(result, target, pressure, donor_T):
    t0, lo, hi = temperature_box(donor_T, target)
    u, v, p = target.q_weights, target.RH_weights, pressure.values_Pa
    if result['comparison_method'] == 'Q_ONLY_FIXED_T_P':
        capacity = math.fsum(w*cap(t, pi) for w, t, pi in zip(u, t0, p))
        if not target.q_mean_kgkg > capacity+1e-9:
            raise ValueError('TPA_AUDIT_Q_ONLY_CAPACITY_CERTIFICATE_FAILED')
        return {'kind': 'FIXED_T_Q_CAPACITY', 'separation_q_kgkg': target.q_mean_kgkg-capacity}
    c = result['certificate']
    caps = [cap(t, pi) for t, pi in zip(hi, p)]
    capacity = math.fsum(w*x for w, x in zip(u, caps))
    if abs(capacity-c['q_mean_capacity_upper']) > 1e-14:
        raise ValueError('TPA_AUDIT_DOMAIN_CAPACITY_MISMATCH')
    if c['reason'] == 'Q_INTERVAL_ABOVE_DOMAIN_CAPACITY':
        if target.q_mean_kgkg <= capacity+1e-9:
            raise ValueError('TPA_AUDIT_JOINT_CAPACITY_CERTIFICATE_FAILED')
        return {'kind': 'JOINT_BOX_Q_CAPACITY', 'separation_q_kgkg': target.q_mean_kgkg-capacity}
    esmin, esmax = [], []
    for low, high in zip(lo, hi):
        points = [low, high]
        if target.rh_phase == 'WATER_ICE':
            points += [x for x in (math.nextafter(273.15, -math.inf), 273.15) if low <= x <= high]
        values = [_es(t, target.rh_phase, FORMULATION) for t in points]
        esmin.append(min(values)); esmax.append(max(values))
    lam_hi = c['upper_dual']['multiplier']
    upper_terms = []
    for ui, vi, pi, es, ci in zip(u, v, p, esmin, caps):
        a = 100*pi/es
        if lam_hi == 0 or ui == 0:
            qi = ci if vi > 0 else 0.
        else:
            qi = min(ci, max(0., (math.sqrt(vi*a*EPS/(lam_hi*ui))-EPS)/(1-EPS)))
        upper_terms.append(vi*a*qi/(EPS+(1-EPS)*qi)-lam_hi*ui*qi)
    upper = (lam_hi*min(capacity, target.q_mean_kgkg+1e-9)+math.fsum(upper_terms)
             +c['upper_dual']['roundoff_guard_pp'])
    lam_lo = c['lower_dual']['multiplier']
    coefficients = [vi*100*pi/((EPS+(1-EPS)*ci)*es) for vi, pi, ci, es in zip(v, p, caps, esmax)]
    lower = max(0., lam_lo*max(0., target.q_mean_kgkg-1e-9)+math.fsum(
        min(0., (a-lam_lo*ui)*ci) for a, ui, ci in zip(coefficients, u, caps))-c['lower_dual']['roundoff_guard_pp'])
    if abs(upper-c['RH_mean_upper_pp']) > 5e-8 or abs(lower-c['RH_mean_lower_pp']) > 5e-8:
        raise ValueError('TPA_AUDIT_SCALAR_DUAL_REPLAY_MISMATCH')
    gap = (target.RH_mean_pct-upper if c['reason'] == 'RH_INTERVAL_ABOVE_DOMAIN_UPPER' else
           lower-target.RH_mean_pct if c['reason'] == 'RH_INTERVAL_BELOW_DOMAIN_LOWER' else -math.inf)
    if gap <= 1e-4:
        raise ValueError('TPA_AUDIT_DUAL_SEPARATION_NOT_ESTABLISHED')
    return {'kind': 'JOINT_T_BOX_FIXED_P_RH_DUAL', 'separation_RH_pp': gap,
            'RH_mean_lower_pp': lower, 'RH_mean_upper_pp': upper}


def audit_comparison(inputs, results):
    by_case = {r['case_id']: r for r in inputs}
    if len(by_case) != len(inputs):
        raise ValueError('TPA_AUDIT_DUPLICATED_REPLAY_INPUT')
    checks, states, q_kkt = [], 0, 0
    for result in results:
        if result['status'] == 'SOURCE_BLOCKED':
            continue
        record = by_case[result['case_id']]
        base = record['base_case']
        target = DailyClimateConstraints(**base['target'])
        pressure = PressureTrajectory(**record['pressure_trajectory'])
        if result['source_constraints_sha256'] != target.fingerprint or result['pressure_trajectory_sha256'] != pressure.fingerprint:
            raise ValueError('TPA_AUDIT_INPUT_IDENTITY_MISMATCH')
        source = dict(tasmin=target.Tmin_K, tasmax=target.Tmax_K, tas=target.tas_K,
                      huss=target.q_mean_kgkg, hurs=target.RH_mean_pct)
        if result['source_diagnostics'] != source:
            raise ValueError('TPA_AUDIT_SOURCE_DIAGNOSTICS_CHANGED')
        if result['status'] == 'CERTIFIED_INFEASIBLE':
            checks.append({'case_id': result['case_id'], 'method': result['comparison_method'],
                           **replay_certificate(result, target, pressure, base['donor_T'])})
        if 'T_K' not in result:
            continue
        qonly = result['comparison_method'] == 'Q_ONLY_FIXED_T_P'
        strict = result['comparison_method'] == 'STRICT_JOINT_T_Q_FIXED_P'
        valid = validate_projection(result['T_K'], result['p_Pa'], result['q_kgkg'], target.legacy_target(),
            pressure.values_Pa, base['donor_T'], target.q_weights, target.RH_weights, target.T_weights,
            hard_q=qonly or strict, hard_RH=strict)
        states += 1
        achieved = dict(tasmin=min(result['T_K']), tasmax=max(result['T_K']),
            tas=(min(result['T_K'])+max(result['T_K']))/2 if target.temperature_operator == 'DERIVED_TAS_MIDRANGE'
                else valid['T_time_mean_K'], huss=valid['q_mean_kgkg'], hurs=valid['RH_source_mean_pct'])
        if {j['variable'] for j in result['journal_all_diagnostics']} != set(achieved):
            raise ValueError('TPA_AUDIT_ALL_FIVE_JOURNAL_VARIABLES_REQUIRED')
        for journal in result['journal_all_diagnostics']:
            field = journal['variable']
            if (abs(journal['achieved']-achieved[field]) > 1e-10
                    or journal['requested'] != source[field]
                    or abs(journal['signed_delta']-(achieved[field]-result['source_diagnostics'][field])) > 1e-10
                    or journal['correction_budget_established'] is not False):
                raise ValueError('TPA_AUDIT_DAILY_LEDGER_MISMATCH')
        if qonly:
            caps = [cap(t, p) for t, p in zip(result['T_K'], result['p_Pa'])]
            lam = result['multiplier']
            for q, q0, ci, ui in zip(result['q_kgkg'], base['donor_q'], caps, target.q_weights):
                wanted = (min(ci, max(0., q0+lam*ui)) if lam is not None else
                          min(ci, max(0., q0)) if ui == 0 else 0. if target.q_mean_kgkg <= 0 else ci)
                if abs(q-wanted) > 1e-12:
                    raise ValueError('TPA_AUDIT_Q_PROJECTION_KKT_FAILED')
            objective = .5*math.fsum((q-q0)**2 for q, q0 in zip(result['q_kgkg'], base['donor_q']))
            if abs(objective-result['objective']) > 1e-16:
                raise ValueError('TPA_AUDIT_Q_OBJECTIVE_MISMATCH')
            q_kkt += 1
    strict_reuse = 0
    for case_id in by_case:
        cohort = {r['comparison_method']: r for r in results if r['case_id'] == case_id}
        strict = cohort['STRICT_JOINT_T_Q_FIXED_P']
        if strict['status'] == 'EXACT_DEFINED_OPERATORS':
            c2 = cohort['C2_BOTH_SOFT_STRICT_FIRST']
            if any(strict[k] != c2[k] for k in ('T_K', 'p_Pa', 'q_kgkg')):
                raise ValueError('TPA_AUDIT_C2_DID_NOT_REUSE_STRICT_STATE')
            strict_reuse += 1
    return {'status': 'PASS_INDEPENDENT_SCALAR_REPLAY', 'revalidated_states': states,
        'all_returned_states_revalidated': True,
        'q_only_KKT_and_objectives_replayed': q_kkt, 'strict_states_reused_by_C2': strict_reuse,
        'infeasibility_checks': checks, 'certificate_kinds': dict(Counter(r['kind'] for r in checks)),
        'bounds_numerics': 'FLOAT64_WITH_DECLARED_GUARDS_NOT_DIRECTED_ROUNDING_INTERVAL_ARITHMETIC',
        'pressure_input_changed': False, 'independent_accuracy': 'NOT_ASSESSED', 'operational_ready': False}
