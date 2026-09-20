from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer import aggregations, source_parity_monthly_canonical, source_parity_runtime
from epw_climate_analyzer import source_parity_contract_closure as contract
from epw_climate_analyzer.source_parity_contract_guard import install_contract_guards


class CanonicalContractRuntimeTests(unittest.TestCase):
    def test_full_runtime_reset_drops_persistent_monthly_and_aggregation_wrappers(self) -> None:
        stale_monthly = lambda *args, **kwargs: None
        stale_aggregation = lambda *args, **kwargs: None
        source_parity_monthly_canonical._render_monthly_generic = stale_monthly
        aggregations.aggregate_summary = stale_aggregation

        source_parity_runtime._fresh_source_parity_ui()

        self.assertIsNot(source_parity_monthly_canonical._render_monthly_generic, stale_monthly)
        self.assertIsNot(aggregations.aggregate_summary, stale_aggregation)
        self.assertEqual(source_parity_monthly_canonical._render_monthly_generic.__name__, "_render_monthly_generic")
        self.assertEqual(aggregations.aggregate_summary.__name__, "aggregate_summary")

    def test_unknown_provider_statistic_is_native_monthly_only(self) -> None:
        install_contract_guards()
        column = "monthly__unknown__other__foo"
        frame = pd.DataFrame(
            {column: [1.0, 2.0]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-02-01"]),
        )
        monthly = contract.monthly_period_values(frame, column, "Monthly")
        self.assertEqual(monthly.tolist(), [1.0, 2.0])
        with self.assertRaises(ValueError):
            contract.monthly_period_values(frame, column, "Seasonal")
        with self.assertRaises(ValueError):
            contract.monthly_period_values(frame, column, "Annual")


if __name__ == "__main__":
    unittest.main()
