from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from epw_climate_analyzer import aggregations, source_parity_monthly_canonical, source_parity_runtime
from epw_climate_analyzer import source_parity_contract_closure as contract
from epw_climate_analyzer.source_parity_contract_guard import install_contract_guards
from epw_climate_analyzer.source_parity_contract_guidance_hotfix import _decorate_monthly_table
from epw_climate_analyzer.source_parity_monthly_selection_state import (
    _normalize_catalogue_roles,
    _visible_catalogue,
)
from epw_climate_analyzer.source_parity_streamlit_surface import (
    pristine_delta_generator_date_input,
    pristine_streamlit_callable,
    restore_streamlit_surface,
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

    def test_runtime_reset_restores_leaked_streamlit_surface(self) -> None:
        restore_streamlit_surface()
        pristine_editor = pristine_streamlit_callable("data_editor")
        pristine_radio = pristine_streamlit_callable("radio")
        pristine_selectbox = pristine_streamlit_callable("selectbox")
        pristine_date_input = pristine_delta_generator_date_input()

        leaked = lambda *args, **kwargs: None
        st.data_editor = leaked
        st.radio = leaked
        st.selectbox = leaked
        DeltaGenerator.date_input = leaked

        source_parity_runtime._fresh_source_parity_ui()

        self.assertIs(st.data_editor, pristine_editor)
        self.assertIs(st.radio, pristine_radio)
        self.assertIs(st.selectbox, pristine_selectbox)
        self.assertIs(DeltaGenerator.date_input, pristine_date_input)

    def test_installed_marker_still_restores_leaked_streamlit_surface(self) -> None:
        restore_streamlit_surface()
        pristine_editor = pristine_streamlit_callable("data_editor")
        pristine_radio = pristine_streamlit_callable("radio")
        pristine_expander = pristine_streamlit_callable("expander")
        pristine_date_input = pristine_delta_generator_date_input()

        leaked = lambda *args, **kwargs: None
        st.data_editor = leaked
        st.radio = leaked
        st.expander = leaked
        DeltaGenerator.date_input = leaked

        namespace = {
            "VARIABLES": {},
            "load_epw_from_bytes": object(),
            "render_geosphere_source": object(),
            "render_canonical_climate_analysis": object(),
            "render_compare_climates": object(),
            "render_data_quality": object(),
            "_SOURCE_PARITY_RUNTIME_INSTALLED": True,
        }
        self.assertTrue(source_parity_runtime.install_into_app_globals(namespace))

        self.assertIs(st.data_editor, pristine_editor)
        self.assertIs(st.radio, pristine_radio)
        self.assertIs(st.expander, pristine_expander)
        self.assertIs(DeltaGenerator.date_input, pristine_date_input)

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

    def test_monthly_core_demotes_heuristic_recommended_statistics(self) -> None:
        decorated = pd.DataFrame(
            {
                "Provider": ["tl_mittel", "snow_days_ge_100", "mystery"],
                "Measured variable": [
                    "Air temperature — monthly mean",
                    "Days with total snow depth >= 100 cm",
                    "Mystery provider field",
                ],
                "Role": ["Core variable", "Core variable", "Other provider parameter"],
                "Selected": [True, True, True],
            }
        )
        normalized = _normalize_catalogue_roles(decorated)
        self.assertEqual(normalized.loc[0, "Role"], "Core variable")
        self.assertEqual(normalized.loc[1, "Role"], "Additional statistic")

        core = _visible_catalogue(SimpleNamespace(), normalized, "Core variables")
        self.assertEqual(core["Provider"].tolist(), ["tl_mittel"])

        expanded = _visible_catalogue(SimpleNamespace(), normalized, "Core + additional statistics")
        self.assertEqual(expanded["Provider"].tolist(), ["tl_mittel", "snow_days_ge_100"])
        self.assertNotIn("mystery", expanded["Provider"].tolist())


if __name__ == "__main__":
    unittest.main()
