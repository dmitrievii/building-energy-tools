from __future__ import annotations

import inspect
import unittest
from contextlib import nullcontext
from types import SimpleNamespace

import pandas as pd

from epw_climate_analyzer import source_parity_monthly_canonical as monthly_ui
from epw_climate_analyzer import source_parity_monthly_selection_state as selection_state_module
from epw_climate_analyzer import source_parity_monthly_surface_guard as surface_guard
from epw_climate_analyzer.source_parity_monthly_selection_state import (
    _FLAG_STATE_KEY,
    _LAST_VIEW_KEY,
    _MONTHLY_EDITOR_KEY_PREFIX,
    _PARAMETER_SET_EPOCH_KEY,
    _SELECTION_STATE_KEY,
    _cleared_provider_state,
    _loader_table_from_provider_state,
    _provider_state,
    install_monthly_selection_state,
    reset_monthly_parameter_set_state,
)


class _EditorStreamlit:
    def __init__(self, resource_id: str):
        self.session_state = {
            "geosphere_resource_id": resource_id,
            "geosphere_selected_station_id": "105",
        }
        self.calls: list[tuple[pd.DataFrame, dict[str, object]]] = []
        self.next_edited: pd.DataFrame | None = None

    def data_editor(self, data, *args, **kwargs):
        self.calls.append((data.copy(), dict(kwargs)))
        if self.next_edited is not None:
            edited = self.next_edited.copy()
            self.next_edited = None
            return edited
        return data.copy()


class MonthlyMatureLoaderContractTests(unittest.TestCase):
    def test_provider_identity_is_stable_within_view_but_parameter_set_change_clears_selection(self) -> None:
        full = pd.DataFrame(
            {
                "Provider": ["rf_mittel", "p", "tl_mittel", "absf_max"],
                "Selected": [True, True, True, True],
                "Quality flag": [False, False, False, False],
                "Role": ["Core variable", "Core variable", "Core variable", "Other provider parameter"],
            }
        )
        st = SimpleNamespace(session_state={})
        selection = _provider_state(st, _SELECTION_STATE_KEY, full, "Selected", default=False)
        flags = _provider_state(st, _FLAG_STATE_KEY, full, "Quality flag", default=False)
        self.assertEqual(selection, {name: False for name in full["Provider"]})

        # Within one unchanged Parameter set, provider ID owns row identity.
        for provider in ("tl_mittel", "rf_mittel", "p"):
            selection[provider] = True
        rebuilt = _loader_table_from_provider_state(full, selection, flags)
        self.assertEqual(
            rebuilt["Provider"].tolist(),
            ["rf_mittel", "p", "tl_mittel", "absf_max"],
        )
        self.assertEqual(
            rebuilt.loc[rebuilt["Selected"], "Provider"].tolist(),
            ["rf_mittel", "p", "tl_mittel"],
        )

        # Crossing a Parameter-set boundary is deliberately simpler: no hidden
        # selection or quality-flag state is carried into the next catalogue view.
        cleared = _cleared_provider_state(full)
        self.assertEqual(cleared, {name: False for name in full["Provider"]})
        reset = _loader_table_from_provider_state(full, cleared, cleared)
        self.assertFalse(reset["Selected"].any())
        self.assertFalse(reset["Quality flag"].any())

    def test_parameter_set_callback_clears_server_and_widget_snapshots_and_advances_epoch(self) -> None:
        editor_key = f"{_MONTHLY_EDITOR_KEY_PREFIX}v3__all__fixture"
        st = SimpleNamespace(
            session_state={
                _SELECTION_STATE_KEY: {"tl_mittel": True},
                _FLAG_STATE_KEY: {"tl_mittel": True},
                _LAST_VIEW_KEY: "All provider parameters",
                _PARAMETER_SET_EPOCH_KEY: 4,
                editor_key: {"edited_rows": {0: {"Selected": True}}},
                "_geosphere_variable_form_load_requested_v1": ("klima-v2-1m", "105"),
                "unrelated": "keep",
            }
        )

        epoch = reset_monthly_parameter_set_state(st)

        self.assertEqual(epoch, 5)
        self.assertEqual(st.session_state[_PARAMETER_SET_EPOCH_KEY], 5)
        self.assertEqual(st.session_state[_SELECTION_STATE_KEY], {})
        self.assertEqual(st.session_state[_FLAG_STATE_KEY], {})
        self.assertNotIn(_LAST_VIEW_KEY, st.session_state)
        self.assertNotIn(editor_key, st.session_state)
        self.assertNotIn("_geosphere_variable_form_load_requested_v1", st.session_state)
        self.assertEqual(st.session_state["unrelated"], "keep")

    def test_monthly_parameter_set_transition_resets_server_side_provider_state(self) -> None:
        source = pd.DataFrame(
            {
                "Provider": ["rf_mittel", "p", "tl_mittel", "absf_max"],
                "Selected": [False, False, False, False],
                "Quality flag": [False, False, False, False],
                "Role": ["Core variable", "Core variable", "Core variable", "Other provider parameter"],
            }
        )
        fake_st = _EditorStreamlit("klima-v2-1m")
        fake_st.session_state[selection_state_module._PARAMETER_SET_KEY] = "All provider parameters"
        selected_all = source.copy()
        selected_all.loc[selected_all["Provider"].isin(["rf_mittel", "p", "tl_mittel"]), "Selected"] = True
        fake_st.next_edited = selected_all
        captured: dict[str, pd.DataFrame] = {}

        def base_selector(_legacy, _original):
            captured["result"] = fake_st.data_editor(source, key="geosphere_variable_editor")

        parity = SimpleNamespace(st=fake_st, _render_geosphere_resource_selector=base_selector)
        original_decorate = selection_state_module._decorate_monthly_table
        selection_state_module._decorate_monthly_table = lambda _parity, data: data.copy()
        try:
            install_monthly_selection_state(parity)
            parity._render_geosphere_resource_selector(SimpleNamespace(), lambda: None)
            self.assertTrue(fake_st.session_state[_SELECTION_STATE_KEY]["rf_mittel"])
            self.assertTrue(fake_st.session_state[_SELECTION_STATE_KEY]["p"])
            self.assertTrue(fake_st.session_state[_SELECTION_STATE_KEY]["tl_mittel"])

            fake_st.session_state[selection_state_module._PARAMETER_SET_KEY] = "Core variables"
            parity._render_geosphere_resource_selector(SimpleNamespace(), lambda: None)
        finally:
            selection_state_module._decorate_monthly_table = original_decorate

        self.assertTrue(all(value is False for value in fake_st.session_state[_SELECTION_STATE_KEY].values()))
        self.assertTrue(all(value is False for value in fake_st.session_state[_FLAG_STATE_KEY].values()))
        self.assertIn("result", captured)
        self.assertFalse(captured["result"]["Selected"].any())
        self.assertFalse(captured["result"]["Quality flag"].any())

    def test_hourly_and_ten_minute_bypass_monthly_selection_logic(self) -> None:
        source = pd.DataFrame(
            {
                "Selected": [False, True],
                "Measured variable": ["Temperature", "Humidity"],
                "Provider": ["tl", "rf"],
            }
        )
        for resource_id in ("klima-v2-10min", "klima-v2-1h"):
            with self.subTest(resource_id=resource_id):
                fake_st = _EditorStreamlit(resource_id)
                captured: dict[str, object] = {}

                def base_selector(_legacy, _original):
                    captured["result"] = fake_st.data_editor(
                        source,
                        key="geosphere_variable_editor_v2::scope",
                    )

                parity = SimpleNamespace(
                    st=fake_st,
                    _render_geosphere_resource_selector=base_selector,
                )
                install_monthly_selection_state(parity)
                parity._render_geosphere_resource_selector(SimpleNamespace(), lambda: None)

                self.assertEqual(len(fake_st.calls), 1)
                rendered, kwargs = fake_st.calls[0]
                pd.testing.assert_frame_equal(rendered, source)
                self.assertEqual(kwargs["key"], "geosphere_variable_editor_v2::scope")
                pd.testing.assert_frame_equal(captured["result"], source)
                self.assertNotIn(_SELECTION_STATE_KEY, fake_st.session_state)

    def test_monthly_surface_guard_never_owns_editor_or_load_button_transport(self) -> None:
        source = inspect.getsource(surface_guard.install_monthly_surface_guard)
        self.assertNotIn("st.form", source)
        self.assertNotIn("form_submit_button", source)
        self.assertNotIn("st.button =", source)
        self.assertNotIn("st.data_editor =", source)
        self.assertNotIn("_FORM_REQUEST", source)

    def test_surface_guard_leaves_mature_load_button_callable_untouched(self) -> None:
        calls: list[str] = []

        def button(label, *args, **kwargs):
            calls.append(str(label))
            return str(label) == "Load measured GeoSphere interval"

        st = SimpleNamespace(
            session_state={surface_guard._RESOURCE_KEY: surface_guard.MONTHLY_RESOURCE_ID},
            caption=lambda *args, **kwargs: None,
            info=lambda *args, **kwargs: None,
            radio=lambda label, options, *args, **kwargs: list(options)[0],
            expander=lambda *args, **kwargs: nullcontext(),
            button=button,
        )
        captured: dict[str, object] = {}

        def previous(_legacy, _original):
            captured["button_object"] = st.button
            captured["load"] = st.button("Load measured GeoSphere interval", type="primary")

        parity = SimpleNamespace(st=st, _render_geosphere_resource_selector=previous)
        old_flag = getattr(monthly_ui, "_MONTHLY_SURFACE_ANALYSIS_GUARD_INSTALLED", None)
        monthly_ui._MONTHLY_SURFACE_ANALYSIS_GUARD_INSTALLED = True
        try:
            surface_guard.install_monthly_surface_guard(parity)
            parity._render_geosphere_resource_selector(SimpleNamespace(), lambda: None)
        finally:
            if old_flag is None:
                delattr(monthly_ui, "_MONTHLY_SURFACE_ANALYSIS_GUARD_INSTALLED")
            else:
                monthly_ui._MONTHLY_SURFACE_ANALYSIS_GUARD_INSTALLED = old_flag

        self.assertIs(captured["button_object"], button)
        self.assertTrue(captured["load"])
        self.assertEqual(calls, ["Load measured GeoSphere interval"])


if __name__ == "__main__":
    unittest.main()
