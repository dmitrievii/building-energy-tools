from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from epw_climate_analyzer import aggregations, source_parity_monthly_canonical, source_parity_runtime
from epw_climate_analyzer import source_parity_contract_closure as contract
from epw_climate_analyzer.source_parity_contract_guard import install_contract_guards
from epw_climate_analyzer.source_parity_contract_guidance_hotfix import _decorate_monthly_table
from epw_climate_analyzer.source_parity_resource_persistence import (
    RESOURCE_KEY,
    RESOURCE_PERSIST_KEY,
    RESOURCE_WIDGET_KEY,
    install_resource_persistence,
    resolved_resource,
)


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

    def test_streamlit_surface_is_restored_before_a_new_runtime_stack(self) -> None:
        source_parity_runtime._restore_streamlit_surface()
        original_data_editor = st.data_editor
        original_radio = st.radio
        original_selectbox = st.selectbox
        original_rerun = st.rerun

        st.data_editor = lambda *args, **kwargs: None
        st.radio = lambda *args, **kwargs: None
        st.selectbox = lambda *args, **kwargs: None
        st.rerun = lambda *args, **kwargs: None

        source_parity_runtime._restore_streamlit_surface()

        self.assertIs(st.data_editor, original_data_editor)
        self.assertIs(st.radio, original_radio)
        self.assertIs(st.selectbox, original_selectbox)
        self.assertIs(st.rerun, original_rerun)

    def test_visible_resource_widget_wins_route_resolution(self) -> None:
        self.assertEqual(
            resolved_resource(
                ["klima-v2-10min", "klima-v2-1h", "klima-v2-1m"],
                widget_resource="klima-v2-1m",
                persisted_resource="klima-v2-10min",
                route_resource="klima-v2-10min",
            ),
            "klima-v2-1m",
        )

    def test_station_rerun_preserves_visible_monthly_resource(self) -> None:
        snapshots: list[dict[str, object]] = []

        class FakeStreamlit:
            def __init__(self) -> None:
                self.session_state = {
                    RESOURCE_WIDGET_KEY: "klima-v2-1m",
                    RESOURCE_KEY: "klima-v2-10min",
                }

            def rerun(self, *args, **kwargs):
                snapshots.append(dict(self.session_state))
                return None

        fake_st = FakeStreamlit()

        def legacy_selector(_legacy, _original) -> None:
            # Reproduce the legacy layer resetting its routing key immediately
            # before the station-confirmation rerun.
            fake_st.session_state[RESOURCE_KEY] = "klima-v2-10min"
            fake_st.rerun()

        parity = SimpleNamespace(
            st=fake_st,
            available_resource_specs=lambda: [
                SimpleNamespace(resource_id="klima-v2-10min"),
                SimpleNamespace(resource_id="klima-v2-1m"),
            ],
            _render_geosphere_resource_selector=legacy_selector,
        )
        install_resource_persistence(parity)
        parity._render_geosphere_resource_selector(None, None)

        self.assertTrue(snapshots)
        self.assertEqual(snapshots[-1][RESOURCE_KEY], "klima-v2-1m")
        self.assertEqual(snapshots[-1][RESOURCE_PERSIST_KEY], "klima-v2-1m")
        self.assertEqual(fake_st.session_state[RESOURCE_KEY], "klima-v2-1m")
        self.assertEqual(fake_st.session_state[RESOURCE_PERSIST_KEY], "klima-v2-1m")

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
