"""The independent audit must reject state, ledger, KKT and certificate edits."""
from copy import deepcopy
from dataclasses import asdict
import unittest

from p9_3b3_tpa_audit import audit_comparison
from p9_3b3_tpa_compare import compare
from test_p9_3b3_tpa_contracts import example_pressure, example_target


def example_replay(conflict=False):
    pressure = example_pressure(T=[280.]*24) if conflict else example_pressure()
    target = example_target(pressure, RH_mean_pct=20. if conflict else 60.)
    inputs = [{'case_id': 'FIXTURE', 'base_case': {'target': asdict(target),
        'donor_T': pressure.prior_T_K, 'donor_q': pressure.prior_q_kgkg},
        'pressure_trajectory': asdict(pressure)}]
    results = [{**r, 'case_id': 'FIXTURE'} for r in compare(target, pressure)]
    return inputs, results


class IndependentNumericAudit(unittest.TestCase):
    def test_scalar_state_KKT_and_strict_reuse_replay(self):
        inputs, results = example_replay()
        r = audit_comparison(inputs, results)
        self.assertEqual(r['revalidated_states'], 3)
        self.assertEqual(r['q_only_KKT_and_objectives_replayed'], 1)
        self.assertEqual(r['strict_states_reused_by_C2'], 1)
        self.assertEqual(r['infeasibility_checks'], [])

    def test_pressure_or_source_diagnostic_tamper_is_rejected(self):
        inputs, results = example_replay()
        for field in ('p_Pa', 'source_diagnostics'):
            changed = deepcopy(results)
            if field == 'p_Pa':
                changed[0][field][0] += .1
            else:
                changed[0][field]['hurs'] += .1
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_comparison(inputs, changed)

    def test_journal_and_KKT_multiplier_tamper_is_rejected(self):
        inputs, results = example_replay()
        changed = deepcopy(results)
        changed[1]['journal_all_diagnostics'][0]['requested'] += .001
        with self.assertRaisesRegex(ValueError, 'LEDGER_MISMATCH'):
            audit_comparison(inputs, changed)
        changed = deepcopy(results)
        changed[1]['multiplier'] += .01
        with self.assertRaisesRegex(ValueError, 'KKT_FAILED'):
            audit_comparison(inputs, changed)

    def test_dual_certificate_replays_and_edited_bound_is_rejected(self):
        inputs, results = example_replay(True)
        r = audit_comparison(inputs, results)
        self.assertEqual(r['certificate_kinds'], {'JOINT_T_BOX_FIXED_P_RH_DUAL': 1})
        self.assertGreater(r['infeasibility_checks'][0]['separation_RH_pp'], 1.)
        changed = deepcopy(results)
        changed[0]['certificate']['RH_mean_lower_pp'] -= 1.
        with self.assertRaisesRegex(ValueError, 'DUAL_REPLAY_MISMATCH'):
            audit_comparison(inputs, changed)


if __name__ == '__main__':
    unittest.main()
