"""TPA1 preregistered 63-case comparison, no new station observations.

Runs synthetic controls and revealed NASA sensitivity cases separately. All
inputs and all 189 outcomes are retained, including blocked/unresolved cells.
Existing scientific controls, source bytes and the protocol are immutable.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

import numpy as np

from p9_3b3_compare_vertical_frame import SourceBlocked, fingerprint
from p9_3b3_regression_audit import read_registered
from p9_3b3_source_semantics import parse_das
from p9_3b3_source_time_support import parse_ascii_array, evaluate_support
from p9_3b3_thermodynamics import saturation, q_from_e, q_saturation
from p9_3b3_tpa_contracts import DailyClimateConstraints
from p9_3b3_tpa_compare import METHODS, compare
from p9_3b3_tpa_pressure import load_sealed_nv2, pressure_at_thermo
from p9_3b3_tpa_audit import audit_comparison


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = Path(__file__).with_name('p9_3b3_tpa_protocol.json')
PROTOCOL_SHA = 'aedb4b8f5d635dbd16a03eb3ba1bd4ee3b517cfae20b27b5fc194ceb4dfe4a2a'
SEMANTICS_SHA = '4c6c4cec6d9ba8bf81a0041669080c97cb3145b85f2d1290e089cadba0a85e14'


def load_protocol(path=DEFAULT_PROTOCOL):
    p = json.loads(Path(path).read_text())
    if fingerprint(p) != PROTOCOL_SHA:
        raise ValueError('TPA_PREREGISTERED_PROTOCOL_CHANGED')
    return p


def protected_controls(protocol, root=ROOT):
    checks = []
    for relative, expected in protocol['protected_control_sha256'].items():
        actual = hashlib.sha256((root/relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('TPA_PROTECTED_CONTROL_CHANGED_'+relative)
        checks.append({'path': relative, 'sha256': actual, 'status': 'UNCHANGED'})
    if len(checks) != 109:
        raise ValueError('TPA_EXPECTED_109_FROZEN_CONTROLS')
    return checks


def audit_semantics(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SEMANTICS_SHA:
        raise ValueError('TPA_PREREGISTERED_SEMANTICS_SNAPSHOT_CHANGED')
    s = json.loads(raw)
    responses = {}
    for response in s['raw_source_responses']:
        key = response['year'], response['variable'], response['kind']
        if key in responses or hashlib.sha256(response['body'].encode()).hexdigest() != response['sha256']:
            raise ValueError('TPA_RAW_SOURCE_RESPONSE_CHANGED_OR_DUPLICATED')
        responses[key] = response
    expected = {(y, v, k) for y in (2013, 2014) for v in ('tas', 'tasmin', 'tasmax', 'huss', 'hurs')
                for k in ('das', 'dds', 'time_ascii')}
    if set(responses) != expected:
        raise ValueError('TPA_30_NATIVE_SOURCE_RESPONSES_REQUIRED')
    headers = []
    for year in (2013, 2014):
        for variable in ('tas', 'tasmin', 'tasmax', 'huss', 'hurs'):
            metadata = {'variable': variable, 'year': year, **parse_das(responses[year, variable, 'das']['body'])}
            stored = s['headers'][str(year)][variable]
            if metadata != stored['metadata']:
                raise ValueError('TPA_PARSED_METADATA_DIFFERS_FROM_NATIVE_RESPONSE')
            g = metadata['blocks']['NC_GLOBAL']
            if any(g.get(k) != v for k, v in {'cmip6_source_id': 'CanESM5', 'variant_label': 'r1i1p1f1',
                                             'scenario': 'historical', 'version': '2.0'}.items()):
                raise ValueError('TPA_NATIVE_SOURCE_IDENTITY_MISMATCH')
            time_axis = parse_ascii_array(responses[year, variable, 'time_ascii']['body'], 'time', (365,))
            support = evaluate_support(metadata, time_axis, responses[year, variable, 'dds']['body'])
            if support != stored['time_support'] or support['interval_semantics_verified']:
                raise ValueError('TPA_NATIVE_BOUNDS_UNRESOLVED_MUST_REMAIN_EXPLICIT')
            attrs = metadata['blocks'][variable]
            if variable == 'tas' and ('derived from downscaled tasmax & tasmin' not in attrs.get('comment', '')
                                     or 'time: maximum' not in attrs.get('cell_methods', '')):
                raise ValueError('TPA_TAS_CONFLICT_EVIDENCE_CHANGED')
            if variable in ('huss', 'hurs') and 'time: mean' not in attrs.get('cell_methods', ''):
                raise ValueError('TPA_NATIVE_HUMIDITY_MEAN_OPERATOR_CHANGED')
            if variable == 'hurs' and not all(t in attrs.get('comment', '').lower() for t in ('water', 'ice')):
                raise ValueError('TPA_RH_WATER_ICE_EVIDENCE_REQUIRED')
            headers.append({'variable': variable, 'year': year, 'native_attributes': attrs, 'time_support': support})
    if s['fully_verified'] or s['daily_bounds_verified']:
        raise ValueError('TPA_CONFLICT_AND_MISSING_BOUNDS_NOT_FULLY_VERIFIED')
    return {'snapshot_sha256': SEMANTICS_SHA, 'raw_response_count': len(responses), 'headers': headers,
            'temperature_operator': s['temperature_operator'], 'metadata_conflict': s['metadata_conflict'],
            'rh_phase': s['rh_phase'], 'daily_bounds_verified': False, 'fully_verified': False}


def audit_daily_rows(rows, protocol):
    chosen = [r for r in rows if r['date'][:4] in ('2013', '2014')]
    if len(chosen) != 730 or len({r['date'] for r in chosen}) != 730:
        raise ValueError('TPA_REGISTERED_730_CORE_DATES_REQUIRED')
    residual = max(abs(float(r['tas'])-(float(r['tasmin'])+float(r['tasmax']))/2) for r in chosen)
    if residual > 5e-5 or any(r['model'] != 'CanESM5' or r['member'] != 'r1i1p1f1'
                            or r['scenario'] != 'historical' for r in chosen):
        raise ValueError('TPA_ARCHIVED_SOURCE_OPERATOR_OR_IDENTITY_DRIFT')
    return {'source_csv_sha256': protocol['source_csv_sha256'], 'days': len(chosen),
            'max_abs_tas_minus_midrange_K': residual, 'hourly_T_mean_is_not_tas_constraint': True,
            'source_values_changed': False, 'scope': 'SPECIFIC_REGISTERED_CANESM5_MEMBER_GRID_V2'}


@dataclass(frozen=True)
class BaseCase:
    case_id: str
    family: str
    country: str
    source_day: str
    slot: str
    target: DailyClimateConstraints
    donor_T: tuple
    donor_q: tuple
    synthetic_control: bool


def build_cases(models, rows, protocol):
    """Build targets/priors once at P2, before considering other p variants."""
    cases = []
    for country in protocol['countries']:
        slot = protocol['thermo_donor_slots'][country]
        for day in protocol['source_days']:
            pressure = pressure_at_thermo(models, country, day, 'P2_NATIVE', slot)
            t = np.asarray(pressure.prior_T_K)
            control_q = q_from_e(.6*saturation(t, 'WATER_ICE'), np.asarray(pressure.values_Pa), 287.05/461.5)
            for family in ('CONTROL_RH60', 'CONTROL_Q90CAP_RH20'):
                Q = float(np.mean(control_q)) if family == 'CONTROL_RH60' else .9*float(np.mean(q_saturation(t, pressure.values_Pa)))
                R = 60. if family == 'CONTROL_RH60' else 20.
                identity = json.dumps({'family': family, 'country': country, 'source_day': day,
                    'target_construction_pressure': 'P2_NATIVE', 'synthetic': True,
                    'not_NASA_observations': True}, sort_keys=True)
                digest = fingerprint({'identity': identity, 'T': list(pressure.prior_T_K),
                                      'q_prior': control_q.tolist(), 'Q': Q, 'R': R})
                target = DailyClimateConstraints(day, float(t.min()), float(t.max()), float((t.min()+t.max())/2),
                    Q, R, 'SYNTHETIC_OPERATOR_CONTROL', digest, SEMANTICS_SHA, identity)
                cases.append(BaseCase(family+'|'+country+'|'+day, family, country, day, slot, target,
                                      pressure.prior_T_K, tuple(control_q), True))
    registered = {r['date']: r for r in rows}
    dates = protocol['NASA_seasonal_dates']+protocol['NASA_old_blocked_dates']
    for day in dates:
        source_day = '2021-02-01' if int(day[5:7]) in (11, 12, 1, 2, 3) else '2021-08-01'
        pressure = pressure_at_thermo(models, 'AT', source_day, 'P2_NATIVE', 'D2')
        r = registered[day]
        identity = json.dumps({'model': 'CanESM5', 'scenario': 'historical', 'member': 'r1i1p1f1',
            'version': '2.0', 'grid_latitude': 46.875, 'grid_longitude': 15.375,
            'application': 'GRAZ_THERMO_LEVEL_WITHOUT_QUALIFIED_SPATIAL_DOWNSCALING',
            'pressure': '2021_NV2_D2_DONOR_DATE_SENSITIVITY',
            'not_native_target_day_pressure': True}, sort_keys=True)
        target = DailyClimateConstraints(day, float(r['tasmin']), float(r['tasmax']), float(r['tas']),
            float(r['huss']), float(r['hurs']), 'NASA_REGISTERED_REGRESSION',
            protocol['source_csv_sha256'], SEMANTICS_SHA, identity)
        family = 'NASA_2013_2014_REVEALED_SENSITIVITY'
        cases.append(BaseCase(family+'|AT|'+day, family, 'AT', source_day, 'D2', target,
                              pressure.prior_T_K, pressure.prior_q_kgkg, False))
    if len(cases) != protocol['expected_base_cases'] or Counter(c.family for c in cases) != protocol['case_families']:
        raise AssertionError('TPA_PREREGISTERED_BASE_CASE_CENSUS')
    return cases


def summarize(rows):
    groups = []
    for family in sorted({r['family'] for r in rows}):
        for method in METHODS:
            cohort = [r for r in rows if r['family'] == family and r['comparison_method'] == method]
            states = [r for r in cohort if r['quality']['physical_admissibility'] == 'CONDITIONAL_DISCRETE_GAS_STATE_VALIDATED']
            deltas = lambda key, scale=1: [scale*(r['achieved_diagnostics'][key]-r['source_diagnostics'][key]) for r in states]
            groups.append({'family': family, 'method': method, 'planned': len(cohort),
                'status_counts': dict(Counter(r['status'] for r in cohort)), 'validated_states': len(states),
                'unchanged_daily_diagnostics': sum(not r['source_diagnostics_changed'] for r in states),
                'max_abs_delta_q_gkg': max(map(abs, deltas('huss', 1000)), default=None),
                'max_abs_delta_RH_pp': max(map(abs, deltas('hurs')), default=None),
                'max_RH_water_pct': max((r['validation']['RH_water_max_pct'] for r in states), default=None),
                'no_independent_accuracy_inference': True})
    timing = {}
    for method in METHODS:
        seconds = [r['wall_seconds'] for r in rows if r['comparison_method'] == method]
        timing[method] = {'n': len(seconds), 'total_wall_seconds': sum(seconds),
                          'p50_wall_seconds': float(np.percentile(seconds, 50)),
                          'p95_wall_seconds': float(np.percentile(seconds, 95))}
    return {'groups': groups, 'method_costs': timing,
            'comparison_results': len(rows), 'status_counts': dict(Counter(r['status'] for r in rows))}


def json_write(path, value):
    def convert(v):
        if isinstance(v, np.ndarray):
            return v.tolist()
        if isinstance(v, np.generic):
            return v.item()
        raise TypeError(type(v).__name__)
    # All outputs are new files; no previous results are overwritten.
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False, default=convert)
        stream.write('\n')


def blocked_result(case, method, reason, common_prior):
    """A failed admission has a complete source ledger, never fabricated p."""
    t = case.target
    source = dict(tasmin=t.Tmin_K, tasmax=t.Tmax_K, tas=t.tas_K, huss=t.q_mean_kgkg, hurs=t.RH_mean_pct)
    journal = []
    for variable, requested in source.items():
        hard = variable.startswith('tas') or variable == 'huss' and method in METHODS[:2] or variable == 'hurs' and method == METHODS[0]
        w = t.q_weights if variable == 'huss' else t.RH_weights if variable == 'hurs' else t.T_weights
        journal.append({'variable': variable, 'requested': requested, 'achieved': None, 'signed_delta': None,
            'unit': 'kg/kg' if variable == 'huss' else 'percentage_point' if variable == 'hurs' else 'K',
            'constraint_role': 'HARD' if hard else 'DIAGNOSTIC_NOT_ENFORCED' if method == METHODS[1] else 'SOFT_RESEARCH_METRIC',
            'operator': 'MIN' if variable == 'tasmin' else 'MAX' if variable == 'tasmax'
                        else t.temperature_operator if variable == 'tas' else 'DECLARED_WEIGHTED_TIME_MEAN',
            'weights_sha256': fingerprint(w), 'phase': t.rh_phase if variable == 'hurs' else None,
            'reason': reason, 'source_diagnostic_changed': False, 'correction_budget_established': False,
            'correction_acceptance': 'NO_VALIDATED_STATE', 'pressure_trajectory_sha256': None})
    return {'schema_version': 'IGE_TPA1_THERMO_CLOSURE_v1', 'status': 'SOURCE_BLOCKED', 'reason': reason,
        'comparison_method': method, 'source_constraints_sha256': t.fingerprint,
        'common_prior_sha256': common_prior, 'source_diagnostics': source, 'achieved_diagnostics': {},
        'source_input_mutated': False, 'source_diagnostics_changed': False, 'source_fidelity': 'NO_STATE',
        'pressure_trajectory_sha256': None, 'pressure': None, 'validation': None,
        'quality': {'physical_admissibility': 'NO_VALIDATED_STATE', 'independent_accuracy': 'NOT_QUALIFIED',
                    'code_correctness': 'SEE_SEPARATE_TEST_EVIDENCE', 'operational_readiness': 'NOT_QUALIFIED'},
        'journal_all_diagnostics': journal, 'wall_seconds': 0., 'B4_qualified': False, 'production_epw_ready': False}


def run(out, nv2_zip, nasa_zip, protocol_path=DEFAULT_PROTOCOL):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    protocol = load_protocol(protocol_path)
    controls = protected_controls(protocol)
    semantics = audit_semantics(ROOT/protocol['source_semantics_file'])
    models = load_sealed_nv2(Path(nv2_zip))
    rows, source = read_registered(Path(nasa_zip))
    daily_audit = audit_daily_rows(rows, protocol)
    cases = build_cases(models, rows, protocol)
    json_write(out/'frozen_input_audit.json', {'protected_controls': controls, 'semantics': semantics,
        'daily_operator_audit': daily_audit, 'NASA_archive_source_QA': source,
        'observations_opened': False, 'native_fields_downloaded': False})
    inputs, results, case_census = [], [], []
    for case in cases:
        common_prior = fingerprint({'T': case.donor_T, 'q': case.donor_q})
        for variant in protocol['pressure_variants']:
            case_id = case.case_id+'|'+variant
            try:
                pressure = pressure_at_thermo(models, case.country, case.source_day, variant, case.slot,
                                              target_date=case.target.date)
            except SourceBlocked as exc:
                # Admission failures stay in the registered denominator.
                compared = [blocked_result(case, m, str(exc), common_prior) for m in METHODS]
            else:
                inputs.append({'case_id': case_id, 'base_case': asdict(case), 'pressure_trajectory': asdict(pressure),
                               'common_prior_sha256': common_prior})
                compared = compare(case.target, pressure, case.donor_T, case.donor_q)
                if {r['source_constraints_sha256'] for r in compared} != {case.target.fingerprint} or {
                        r['common_prior_sha256'] for r in compared} != {common_prior}:
                    raise AssertionError('TPA_METHODS_DO_NOT_SHARE_INPUTS')
            for result in compared:
                results.append({**result, 'case_id': case_id, 'base_case_id': case.case_id, 'family': case.family,
                    'country': case.country, 'pressure_variant': variant, 'target_date': case.target.date,
                    'source_day': case.source_day, 'synthetic_control': case.synthetic_control})
            case_census.append({'case_id': case_id, 'source_constraints_sha256': case.target.fingerprint,
                                'common_prior_sha256': common_prior, 'methods_returned': len(compared)})
            print(json.dumps({'case_id': case_id, 'statuses': [r['status'] for r in compared]}), flush=True)
    if len(case_census) != protocol['expected_pressure_cases'] or len(results) != protocol['expected_method_results']:
        raise AssertionError('TPA_PREREGISTERED_63_CASE_189_RESULT_CENSUS')
    for case in cases:
        cohort = [r for r in results if r['base_case_id'] == case.case_id]
        if len(cohort) != 9 or len({r['source_constraints_sha256'] for r in cohort}) != 1 or len({r['common_prior_sha256'] for r in cohort}) != 1:
            raise AssertionError('TPA_PRESSURE_VARIANTS_DO_NOT_SHARE_TARGET_AND_PRIOR')
    json_write(out/'comparison_inputs.json', inputs)
    json_write(out/'comparison_results.json', results)
    numeric_audit = audit_comparison(inputs, results)
    json_write(out/'independent_numeric_audit.json', numeric_audit)
    code = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('p9_3b3_tpa_*.py'))}
    report = {'phase': protocol['phase'], 'preregistered_protocol_sha256': PROTOCOL_SHA,
        'semantics_snapshot_sha256': SEMANTICS_SHA, 'protected_controls_unchanged': len(controls),
        'code_sha256': code, 'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'case_census': case_census, **summarize(results), 'independent_numeric_audit': numeric_audit,
        'output_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.json'))},
        'input_sizes_bytes': {'NV2_ZIP': Path(nv2_zip).stat().st_size, 'NASA_ZIP': Path(nasa_zip).stat().st_size},
        'wall_seconds': time.perf_counter()-start, 'CPU_seconds': time.process_time()-cpu,
        'peak_RSS_KiB_Linux': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'source_date_pressure_sensitivity_only': True,
        'hydrostatic_reintegration_after_T_q_change': False, 'new_station_observations_opened': False,
        'independent_accuracy': 'NOT_ASSESSED_REVEALED_AND_SYNTHETIC_ONLY',
        'native_future_CanESM5_pressure_recovered': False, 'B4_qualified': False,
        'production_epw_ready': False, 'operational_ready': False, 'merge_main': False,
        'C2_correction_budget': 'NOT_ESTABLISHED', 'source_semantics_fully_verified': False}
    json_write(out/'comparison_summary.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--sealed-nv2-zip', required=True)
    parser.add_argument('--original-canesm5-registered-zip', required=True)
    parser.add_argument('--protocol', default=str(DEFAULT_PROTOCOL))
    args = parser.parse_args()
    report = run(args.out, args.sealed_nv2_zip, args.original_canesm5_registered_zip, args.protocol)
    print(json.dumps({k: report[k] for k in ('comparison_results', 'status_counts', 'wall_seconds', 'CPU_seconds')}, indent=2))
