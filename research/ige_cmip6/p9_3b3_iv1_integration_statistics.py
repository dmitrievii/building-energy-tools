"""Registered paired hourly metrics and circular moving-day bootstrap."""
from __future__ import annotations

import datetime as dt
from collections import Counter
import numpy as np

from p9_3b3_iv1_methods import METHODS
from p9_3b3_thermodynamics import MK, epsilon_for, q_from_e, saturation


def metrics(errors):
    e = np.asarray(errors, float)
    if not len(e):
        return {'MAE': None, 'RMSE': None, 'bias': None}
    if not np.isfinite(e).all():
        raise ValueError('IV1_NONFINITE_SCORE_ERROR')
    return {'MAE': float(np.mean(abs(e))), 'RMSE': float(np.sqrt(np.mean(e*e))), 'bias': float(np.mean(e))}


def bootstrap_bounds(daily_sum, daily_count, settings):
    """Pooled paired-hour MAE differences; no equal-day reweighting or redraw.

    Identical day draws across cells retain shared weather-block dependence.
    The Bonferroni quantile is the preregistered one-sided primary bound.
    """
    sums, counts = np.asarray(daily_sum, float), np.asarray(daily_count, int)
    if sums.shape != (14,) or counts.shape != (14,) or np.any(counts < 0) or not np.isfinite(sums).all():
        raise ValueError('IV1_BOOTSTRAP_REQUIRES_14_REGISTERED_DAYS')
    results = []
    for block in [settings['block_days'], *settings['sensitivity_block_days']]:
        rng = np.random.Generator(np.random.PCG64(settings['seed']))
        starts = rng.integers(0, 14, size=(settings['repetitions'], (14+block-1)//block))
        indices = ((starts[..., None]+np.arange(block)) % 14).reshape(settings['repetitions'], -1)[:, :14]
        denominator = counts[indices].sum(axis=1)
        if np.any(denominator == 0):
            results.append({'block_days': block, 'status': 'INCONCLUSIVE_ZERO_SUPPORT_REPLICATE',
                            'zero_support_replicates': int(np.sum(denominator == 0)), 'upper_delta_MAE': None})
            continue
        draws = sums[indices].sum(axis=1)/denominator
        results.append({'block_days': block, 'status': 'COMPUTED', 'zero_support_replicates': 0,
            'upper_delta_MAE': float(np.quantile(draws, settings['one_sided_upper_quantile'])),
            'one_sided_quantile': settings['one_sided_upper_quantile']})
    return results


def state_predictions(cases):
    result = {country: {m: {} for m in METHODS} for country in ('AT', 'DE', 'CH')}
    for case in cases:
        for row in case['results']:
            if 'T_K' not in row:
                continue
            method = row['IV1_method']
            RH = row['validation']['diagnostics']['RH_water_pct']
            for hour, (T, R, q, p) in enumerate(zip(row['T_K'], RH, row['q_kgkg'], row['p_Pa'])):
                stamp = case['date']+f'T{hour:02d}:00'
                result[case['country']][method][stamp] = {'T_K': T, 'RH_pp': R, 'q_kgkg': q, 'p_thermo_Pa': p}
    return result


def score_arrays(cases, barometer, observations, protocol):
    predicted = state_predictions(cases)
    individual, common, comparisons, pressure_cells, proxies, dispositions = [], [], [], [], [], []
    candidate, baseline = protocol['primary_comparison']
    settings = protocol['statistics']
    for country in protocol['countries']:
        obs = observations.get(country, {}).get('values', {})
        for season, (start, end) in enumerate(protocol['windows_UTC']):
            dates = [(dt.date.fromisoformat(start)+dt.timedelta(days=d)).isoformat() for d in range(14)]
            hours = [day+f'T{h:02d}:00' for day in dates for h in range(24)]
            for method in METHODS:
                rows = [r for c in cases if c['country'] == country and c['date'] in dates
                        for r in c['results'] if r['IV1_method'] == method]
                dispositions.append({'country': country, 'season_index': season, 'method': method,
                    'expected_days': 14, 'case_records': len(rows),
                    'status_counts': dict(Counter(r['status'] for r in rows)),
                    'physical_state_hours': sum('T_K' in r for r in rows)*24,
                    'expected_hours': 336})
            for variable in ('T_K', 'RH_pp'):
                truth = obs.get(variable, {})
                all_mask = [t for t in hours if t in truth and all(t in predicted[country][m] for m in METHODS)]
                for method in METHODS:
                    series = predicted[country][method]
                    mask = [t for t in hours if t in truth and t in series]
                    individual.append({'country': country, 'season_index': season, 'variable': variable,
                        'method': method, 'expected_hours': 336, 'matched_hours': len(mask), 'coverage': len(mask)/336,
                        **metrics([series[t][variable]-truth[t] for t in mask])})
                    common.append({'country': country, 'season_index': season, 'variable': variable,
                        'method': method, 'mask': 'ALL_FIVE_METHODS_AND_EXACT_QC_OBSERVATIONS',
                        'expected_hours': 336, 'matched_hours': len(all_mask), 'coverage': len(all_mask)/336,
                        **metrics([series[t][variable]-truth[t] for t in all_mask])})
                a, b = predicted[country][candidate], predicted[country][baseline]
                mask = [t for t in hours if t in truth and t in a and t in b]
                differences = {t: abs(a[t][variable]-truth[t])-abs(b[t][variable]-truth[t]) for t in mask}
                sums = [sum(differences[t] for t in mask if t.startswith(day)) for day in dates]
                counts = [sum(t.startswith(day) for t in mask) for day in dates]
                bounds = bootstrap_bounds(sums, counts, settings) if mask else []
                full = len(mask) >= settings['min_paired_hours']
                margin = settings['research_noninferiority_MAE_margins'][variable]
                upper = bounds[0]['upper_delta_MAE'] if bounds else None
                comparisons.append({'country': country, 'season_index': season, 'variable': variable,
                    'candidate': candidate, 'baseline': baseline, 'mask': 'PREREGISTERED_PRIMARY_PAIR_AND_QC',
                    'expected_hours': 336, 'matched_hours': len(mask), 'coverage': len(mask)/336,
                    'candidate_metrics': metrics([a[t][variable]-truth[t] for t in mask]),
                    'baseline_metrics': metrics([b[t][variable]-truth[t] for t in mask]),
                    'delta_MAE': sum(differences.values())/len(mask) if mask else None,
                    'paired_days': [{'date': day, 'matched_hours': count,
                        'delta_MAE': value/count if count else None} for day, value, count in zip(dates, sums, counts)],
                    'bootstrap': bounds, 'research_margin': margin,
                    'margin_is_calibrated_physical_error_budget': False,
                    'status': 'INCONCLUSIVE_COVERAGE' if not full else 'INCONCLUSIVE_BOOTSTRAP_SUPPORT' if upper is None
                              else 'PASS_RESEARCH_NONINFERIORITY' if upper <= margin else 'FAIL_RESEARCH_NONINFERIORITY'})
            pressure_truth = obs.get('p_barometer_Pa', {})
            pmask = [t for t in hours if t in pressure_truth and t in barometer.get(country, {})]
            stats = metrics([(barometer[country][t]-pressure_truth[t])/100 for t in pmask])
            pressure_cells.append({'country': country, 'season_index': season, 'expected_hours': 336,
                'matched_hours': len(pmask), 'unit': 'hPa', **stats,
                'status': 'INCONCLUSIVE_COVERAGE' if len(pmask) < settings['min_paired_hours'] else
                          'PASS_RESEARCH_GATE' if stats['MAE'] <= protocol['pressure']['pressure_research_MAE_gate_hPa_per_cell']
                          else 'FAIL_RESEARCH_GATE'})
            for method in METHODS:
                eq, qq = [], []
                for stamp in hours:
                    if not all(stamp in obs.get(k, {}) for k in ('T_K', 'RH_pp', 'p_barometer_Pa')):
                        continue
                    state = predicted[country][method].get(stamp)
                    pbar_model = barometer.get(country, {}).get(stamp)
                    if state is None or pbar_model is None:
                        continue
                    e = obs['RH_pp'][stamp]/100*float(saturation(obs['T_K'][stamp], 'WATER', MK))
                    pproxy = obs['p_barometer_Pa'][stamp]*state['p_thermo_Pa']/pbar_model
                    if not e < pproxy:
                        continue
                    q = float(q_from_e(e, pproxy, epsilon_for(MK)))
                    e_model = state['q_kgkg']*state['p_thermo_Pa']/(epsilon_for(MK)+(1-epsilon_for(MK))*state['q_kgkg'])
                    eq.append(e_model-e); qq.append((state['q_kgkg']-q)*1000)
                proxies.append({'country': country, 'season_index': season, 'method': method,
                    'matched_hours': len(eq), 'e_error_Pa': metrics(eq), 'q_error_gkg': metrics(qq),
                    'scope': 'DERIVED_SYNCHRONOUS_T_RH_PROXY_Q_USES_MODEL_VERTICAL_PRESSURE_RATIO',
                    'independent_specific_humidity_measurement': False,
                    'DE_thermo_barometer_horizontal_separation_approx_m': 266 if country == 'DE' else None})
    primary_pass = len(comparisons) == 12 and all(r['status'] == 'PASS_RESEARCH_NONINFERIORITY' for r in comparisons)
    pressure_pass = len(pressure_cells) == 6 and all(r['status'] == 'PASS_RESEARCH_GATE' for r in pressure_cells)
    return {'schema': 'IGE_IV1_PAIRED_STATION_SCORES_v1', 'individual_cells': individual,
        'all_five_common_cells': common, 'primary_comparisons': comparisons,
        'pressure_cells': pressure_cells, 'derived_humidity_proxy_cells': proxies,
        'method_dispositions': dispositions,
        'primary_noninferiority_pass': primary_pass, 'pressure_research_gate_pass': pressure_pass,
        'IV1_research_criteria_pass': primary_pass and pressure_pass,
        'criterion_scope': 'REGISTERED_ERA5_REFERENCE_RECONSTRUCTION_NOT_NATIVE_NEX_OR_INFORMATION_INDEPENDENT_ERA5',
        'B4_qualified': False, 'P2_superiority_established': False, 'production_epw_ready': False}
