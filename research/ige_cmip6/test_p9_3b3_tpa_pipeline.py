"""TPA experiment census, replay inputs and failure-denominator tests."""
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_tpa_compare import METHODS, compare
from p9_3b3_tpa_pressure import pressure_at_thermo
from p9_3b3_tpa_run import (ROOT, build_cases, load_protocol, summarize, run, json_write,
                           audit_daily_rows)
from test_p9_3b3_tpa_contracts import example_models, example_pressure, example_target


def example_rows(protocol):
    dates = protocol['NASA_seasonal_dates']+protocol['NASA_old_blocked_dates']
    return [dict(date=d, tasmin='267', tasmax='273', tas='270', huss='.002', hurs='60',
                 model='CanESM5', member='r1i1p1f1', scenario='historical') for d in dates]


class ExperimentIntegrity(unittest.TestCase):
    def test_preregistered_21_cases_and_fixed_season_rule(self):
        p = load_protocol()
        cases = build_cases(example_models(), example_rows(p), p)
        self.assertEqual(Counter(c.family for c in cases), p['case_families'])
        self.assertEqual(len(cases), 21)
        self.assertEqual(sum(c.synthetic_control for c in cases), 12)
        for c in cases:
            self.assertEqual(c.slot, {'AT': 'D2', 'DE': 'D1', 'CH': 'D1'}[c.country])
            if c.family.startswith('NASA'):
                self.assertEqual(c.source_day, '2021-08-01' if c.target.date[5:7] == '08' else '2021-02-01')
                self.assertEqual(c.target.source_kind, 'NASA_REGISTERED_REGRESSION')

    def test_control_target_and_prior_built_once_not_by_pressure_variant(self):
        p, models = load_protocol(), example_models()
        cases = build_cases(models, example_rows(p), p)
        for a in [c for c in cases if c.family == 'CONTROL_RH60']:
            b = next(c for c in cases if c.country == a.country and c.source_day == a.source_day
                     and c.family == 'CONTROL_Q90CAP_RH20')
            self.assertEqual(a.donor_T, b.donor_T)
            self.assertEqual(a.donor_q, b.donor_q)
            self.assertEqual(a.target.RH_mean_pct, 60.)
            self.assertEqual(b.target.RH_mean_pct, 20.)
            self.assertNotEqual(a.target.fingerprint, b.target.fingerprint)

    def test_replay_at_same_day_and_explicit_revealed_sensitivity(self):
        models = example_models()
        base = build_cases(models, example_rows(load_protocol()), load_protocol())
        for c in (base[0], base[-1]):
            p = pressure_at_thermo(models, c.country, c.source_day, 'P2_NATIVE', c.slot, target_date=c.target.date)
            self.assertEqual(p.alignment, 'DONOR_DATE_SENSITIVITY' if c.target.date != c.source_day else 'TARGET_DAY_EXTERNAL_FIXED')
            self.assertEqual(p.source_date, c.source_day)
            self.assertEqual(p.target_date, c.target.date)

    def test_output_creation_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'result.json'
            json_write(path, {'original': True})
            with self.assertRaises(FileExistsError):
                json_write(path, {'original': False})
            self.assertEqual(json.loads(path.read_text()), {'original': True})
            with self.assertRaises(FileExistsError):
                run(folder, 'unused.zip', 'unused.zip')

    def test_wrong_daily_rows_do_not_acquire_NASA_operator_status(self):
        with self.assertRaisesRegex(ValueError, '730_CORE_DATES'):
            audit_daily_rows(example_rows(load_protocol()), load_protocol())

    def test_189_result_census_retains_blocked_pressure_cells(self):
        p = load_protocol()
        pressure, target = example_pressure(), example_target()
        validated = compare(target, pressure)
        # Compare is replaced only to keep this ledger/census test independent
        # of solver cost; physics and original archive seals have separate tests.
        def comparison(t, pr, T, q):
            from p9_3b3_compare_vertical_frame import fingerprint
            return [{**r, 'source_constraints_sha256': t.fingerprint,
                     'common_prior_sha256': fingerprint({'T': T, 'q': q})} for r in validated]
        actual_adapter = pressure_at_thermo
        def admission(models, country, day, variant, slot, **kwargs):
            if variant == 'P1_LAPSE_0065' and kwargs:
                raise SourceBlocked('FORCED_ADMISSION_BLOCK_FOR_DENOMINATOR_TEST')
            return actual_adapter(models, country, day, variant, slot, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('nv2.zip', 'nasa.zip'):
                (root/name).write_bytes(b'fixture-size-only')
            with patch('p9_3b3_tpa_run.load_sealed_nv2', return_value=example_models()), \
                 patch('p9_3b3_tpa_run.read_registered', return_value=(example_rows(p), {})), \
                 patch('p9_3b3_tpa_run.audit_daily_rows', return_value={'fixture': True}), \
                 patch('p9_3b3_tpa_run.audit_comparison', return_value={'status': 'NOT_THE_SUBJECT_OF_THIS_TEST'}), \
                 patch('p9_3b3_tpa_run.compare', side_effect=comparison), \
                 patch('p9_3b3_tpa_run.pressure_at_thermo', side_effect=admission), \
                 patch('builtins.print'):
                report = run(root/'output', root/'nv2.zip', root/'nasa.zip')
            self.assertEqual(report['comparison_results'], 189)
            self.assertEqual(report['status_counts']['SOURCE_BLOCKED'], 63)
            self.assertEqual(len(report['case_census']), 63)
            rows = json.loads((root/'output'/'comparison_results.json').read_text())
            self.assertEqual(len({r['case_id'] for r in rows}), 63)
            self.assertTrue(all(len(r['journal_all_diagnostics']) == 5 for r in rows))
            for r in (r for r in rows if r['status'] == 'SOURCE_BLOCKED'):
                self.assertIsNone(r['pressure'])
                self.assertEqual(r['schema_version'], 'IGE_TPA1_THERMO_CLOSURE_v1')
                self.assertTrue(all(set(('requested', 'achieved', 'signed_delta', 'unit', 'constraint_role',
                    'operator', 'weights_sha256', 'phase', 'correction_acceptance')) <= set(j)
                    for j in r['journal_all_diagnostics']))
            self.assertEqual({r['comparison_method'] for r in rows}, set(METHODS))
            self.assertFalse(report['new_station_observations_opened'])
            self.assertFalse(report['production_epw_ready'])

    def test_nonuniform_q_and_RH_operators_are_kept_separate(self):
        p = example_pressure()
        u = np.linspace(1., 2., 24); u /= u.sum()
        v = u[::-1]
        t = example_target(p, q_weights=tuple(u), RH_weights=tuple(v), q_mean_kgkg=float(u@p.prior_q_kgkg))
        rows = compare(t, p)
        qrow = rows[1]
        self.assertAlmostEqual(qrow['achieved_diagnostics']['huss'], t.q_mean_kgkg, places=12)
        self.assertNotEqual(next(j for j in qrow['journal_all_diagnostics'] if j['variable'] == 'huss')['weights_sha256'],
                            next(j for j in qrow['journal_all_diagnostics'] if j['variable'] == 'hurs')['weights_sha256'])


if __name__ == '__main__':
    unittest.main()
