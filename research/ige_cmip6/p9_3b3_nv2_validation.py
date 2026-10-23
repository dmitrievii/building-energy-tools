"""NV2 pressure scores with fixed cells and explicit pairwise support."""
from __future__ import annotations

import itertools
import zipfile

import numpy as np

from p9_3b3_native_validation import predicted_pressure, sealed_read, target_hours


def error_metrics(errors):
    e = np.asarray(errors, float)
    if not len(e):
        return {}
    return {'MAE_hPa': float(np.mean(abs(e))), 'bias_hPa': float(np.mean(e)),
            'RMSE_hPa': float(np.sqrt(np.mean(e*e))), 'max_abs_error_hPa': float(np.max(abs(e)))}


def score_nv2(predictions, observed, protocol):
    cells, pairs = [], []
    for country in protocol['countries']:
        methods = protocol['methods_by_country'][country]
        for day in protocol['development_days']:
            times = [t for t in target_hours(protocol) if t.startswith(day)]
            for method in methods:
                errors = []
                for t in times:
                    p = predicted_pressure(predictions, country, method, t)
                    truth = observed.get(country, {}).get(t)
                    if p is not None and truth is not None:
                        errors.append((p-truth)/100)
                row = {'country': country, 'day': day, 'method': method, 'expected_hours': 24,
                       'matched_hours': len(errors), 'coverage': len(errors)/24,
                       'independently_qualified': False, **error_metrics(errors)}
                row['accuracy_gate'] = ('INCONCLUSIVE_COVERAGE' if row['coverage'] < protocol['minimum_cell_coverage']
                                        else 'PASS_THIS_REVEALED_CELL' if row['MAE_hPa'] <= protocol['pressure_MAE_gate_hPa']
                                        else 'FAIL_THIS_REVEALED_CELL')
                cells.append(row)
            # Include empty comparisons: no selection by convenient coverage.
            for a, b in itertools.combinations(methods, 2):
                paired, matched_times = [], []
                for t in times:
                    pa = predicted_pressure(predictions, country, a, t)
                    pb = predicted_pressure(predictions, country, b, t)
                    truth = observed.get(country, {}).get(t)
                    if pa is not None and pb is not None and truth is not None:
                        paired.append(((pa-truth)/100, (pb-truth)/100))
                        matched_times.append(t)
                slot_a, slot_b = a.rsplit('_', 1)[-1], b.rsplit('_', 1)[-1]
                same_donor = slot_a == slot_b and slot_a in ('D1', 'D2')
                pair = {'country': country, 'day': day, 'method': a, 'baseline': b,
                        'comparison_scope': ('SAME_DONOR_SAME_SURFACE_ANCHOR' if same_donor
                                             else 'BETWEEN_DONOR_OR_BLEND_SENSITIVITY'),
                        'paired_hours': len(paired), 'expected_hours': 24,
                        'matched_timestamps_UTC': matched_times, 'independently_qualified': False}
                if paired:
                    ea, eb = np.asarray(paired).T
                    pair.update(method_metrics=error_metrics(ea), baseline_metrics=error_metrics(eb),
                                delta_MAE_hPa=float(np.mean(abs(ea))-np.mean(abs(eb))),
                                delta_RMSE_hPa=float(np.sqrt(np.mean(ea*ea))-np.sqrt(np.mean(eb*eb))))
                pairs.append(pair)
    return {'cells': cells, 'paired_comparisons': pairs,
            'expected_score_cells': protocol['expected_pressure_score_cells'],
            'independent_accuracy': 'NOT_QUALIFIED_REVEALED_TWO_DAY_PILOT',
            'all_AT_DE_CH_qualified': False, 'B4_qualified': False, 'production_epw_ready': False}


def verify_seals(out, seals):
    for name, digest in seals.items():
        sealed_read(out/name, digest)


def score_after_seal(out, seals, cache, protocol, source_protocol, eligible_countries):
    # Resolve here to make the ordering independently testable with an I/O spy.
    from p9_3b3_native_validation import observation_pressure, score_pressure
    verify_seals(out, seals)
    pred = sealed_read(out/'sealed_pressure_predictions.json', seals['sealed_pressure_predictions.json'])['hourly']
    observed, provenance = {}, {}
    for country in protocol['countries']:
        if country not in eligible_countries:
            observed[country] = {}
            provenance[country] = {'status': 'OBSERVATIONS_NOT_OPENED_DATED_REFERENCE_BLOCKED'}
            continue
        try:
            observed[country], provenance[country] = observation_pressure(cache, country, source_protocol)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            observed[country] = {}
            provenance[country] = {'status': 'SOURCE_BLOCKED', 'reason': type(exc).__name__+':'+str(exc)}
    verify_seals(out, seals)
    result = score_nv2(pred, observed, protocol)
    g0 = {t: {co: value['G0'] for co, value in row.items()} for t, row in pred.items()}
    return ({**result, 'observation_provenance': provenance, 'sealed_inputs_sha256': seals},
            {**score_pressure(g0, observed, source_protocol), 'observation_provenance': provenance,
             'sealed_inputs_sha256': seals})
