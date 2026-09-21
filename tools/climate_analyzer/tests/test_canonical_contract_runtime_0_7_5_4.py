from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from epw_climate_analyzer import aggregations, source_parity_monthly_canonical, source_parity_runtime
from epw_climate_analyzer import source_parity_contract_closure as contract
from epw_climate_analyzer.source_parity_contract_guard import install_contract_guards
from epw_climate_analyzer.source_parity_contract_guidance_hotfix import _decorate_monthly_table


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

    def test_final_monthly_guidance_decorates_raw_selector_table_before_sorting(self) -> None:
        raw = pd.DataFrame(
            {
                "Selected": [False, False, False],
                "Quality flag": [False, False, False],
                "Provider": ["tl_mittel", "frost_days", "mystery"],
                "Measured variable": [
                    "Air temperature monthly mean",
                    "Frost days monthly count",
                    "Mystery provider field",
                ],
                "Unit": ["°C", "d", "1"],
                "Canonical field": ["dry_bulb_temperature_c", "", ""],
            }
        )
        # _metadata_descriptor intentionally tolerates a parity object without a
        # live metadata bundle; this reproduces the raw-table stage that caused
        # the branch-local Streamlit KeyError('Category').
        decorated = _decorate_monthly_table(SimpleNamespace(), raw)

        for column in ("Category", "Statistic", "Notes", "Role", "Original GeoSphere name"):
            self.assertIn(column, decorated.columns)
        self.assertNotIn("_recommended", decorated.columns)
        self.assertEqual(decorated["Selected"].tolist(), [False, False, False])
        roles = set(decorated["Role"].astype(str))
        self.assertIn("Core variable", roles)
        self.assertIn("Additional statistic", roles)
        self.assertIn("Other provider parameter", roles)


if __name__ == "__main__":
    unittest.main()
