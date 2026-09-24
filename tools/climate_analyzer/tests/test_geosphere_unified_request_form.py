from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest

import pandas as pd

from epw_climate_analyzer import source_parity_ux_followup as ux
from epw_climate_analyzer.geosphere_request_form import (
    COMMITTED_REQUEST_KEY,
    STAGED_REQUEST_KEY,
    GeoSphereRequestForm,
    GeoSphereRequestState,
    install_geosphere_request_form,
)
from epw_climate_analyzer.source_parity_variable_form_compat import (
    install_geosphere_variable_form_compat,
)


class GeoSphereUnifiedRequestStateTests(unittest.TestCase):
    def _form(self, resource_id: str, station_id: str = "105") -> tuple[SimpleNamespace, GeoSphereRequestForm]:
        st = SimpleNamespace(
            session_state={
                "geosphere_resource_id": resource_id,
                "geosphere_selected_station_id": station_id,
            }
        )
        return st, GeoSphereRequestForm(st)

    def test_same_request_schema_is_used_for_all_three_resources(self) -> None:
        for resource_id in ("klima-v2-10min", "klima-v2-1h", "klima-v2-1m"):
            with self.subTest(resource_id=resource_id):
                st, form = self._form(resource_id)
                form.capture_date("geosphere_start_date", date(2020, 1, 1))
                form.capture_date("geosphere_end_date", date(2020, 12, 31))
                state = form.capture_editor(
                    pd.DataFrame(
                        {
                            "Selected": [True, False],
                            "Quality flag": [True, True],
                            "Provider": ["tl", "rf"],
                            "Canonical field": ["dry_bulb_temperature_c", "relative_humidity_pct"],
                        }
                    )
                )
                self.assertEqual(state.resource_id, resource_id)
                self.assertEqual(state.station_id, "105")
                self.assertEqual(state.provider_parameters, ("tl",))
                self.assertEqual(state.quality_flags, ("tl_flag",))
                self.assertEqual(state.canonical_fields, ("dry_bulb_temperature_c",))
                self.assertTrue(state.is_loadable)
                self.assertIn(STAGED_REQUEST_KEY, st.session_state)

    def test_scope_change_does_not_reuse_previous_provider_selection(self) -> None:
        st, form = self._form("klima-v2-1h")
        form.capture_editor(pd.DataFrame({"Selected": [True], "Provider": ["tl"]}))
        self.assertEqual(form.staged().provider_parameters, ("tl",))

        st.session_state["geosphere_resource_id"] = "klima-v2-1m"
        self.assertEqual(form.staged().resource_id, "klima-v2-1m")
        self.assertEqual(form.staged().provider_parameters, ())

        st.session_state["geosphere_selected_station_id"] = "16412"
        self.assertEqual(form.staged().station_id, "16412")
        self.assertEqual(form.staged().provider_parameters, ())

    def test_committed_request_is_an_explicit_snapshot(self) -> None:
        st, form = self._form("klima-v2-1m")
        form.capture_date("geosphere_start_date", "2020-01-01")
        form.capture_date("geosphere_end_date", "2025-12-31")
        form.capture_editor(
            pd.DataFrame(
                {
                    "Selected": [True, True, True],
                    "Provider": ["rf_mittel", "p", "tl_mittel"],
                    "Canonical field": ["", "", ""],
                }
            )
        )
        committed = form.commit()
        restored = GeoSphereRequestState.from_mapping(st.session_state[COMMITTED_REQUEST_KEY])
        self.assertEqual(restored, committed)
        self.assertEqual(
            committed.provider_parameters,
            ("rf_mittel", "p", "tl_mittel"),
        )
        self.assertTrue(committed.is_loadable)

    def test_roundtrip_is_serializable_mapping_not_streamlit_widget_object(self) -> None:
        state = GeoSphereRequestState(
            resource_id="klima-v2-1h",
            station_id="105",
            start_date=date(1990, 1, 1),
            end_date=date(2025, 12, 31),
            provider_parameters=("tl", "rf"),
            quality_flags=("tl_flag",),
            canonical_fields=("dry_bulb_temperature_c", "relative_humidity_pct"),
            catalogue_view="",
        )
        payload = state.to_mapping()
        self.assertEqual(payload["start_date"], "1990-01-01")
        self.assertEqual(payload["provider_parameters"], ["tl", "rf"])
        self.assertEqual(GeoSphereRequestState.from_mapping(payload), state)


class GeoSphereSubmitBoundaryTests(unittest.TestCase):
    def test_visible_form_submit_commits_without_requiring_or_replacing_st_button(self) -> None:
        calls: list[str] = []
        st = SimpleNamespace(
            session_state={
                "geosphere_resource_id": "klima-v2-1m",
                "geosphere_selected_station_id": "105",
                "geosphere_start_date": date(2020, 1, 1),
                "geosphere_end_date": date(2025, 12, 31),
            },
            data_editor=lambda data, *args, **kwargs: data,
            form_submit_button=lambda label, *args, **kwargs: calls.append(str(label)) or True,
        )
        editor_frame = pd.DataFrame(
            {
                "Selected": [True, False],
                "Provider": ["tl_mittel", "rf_mittel"],
                "Canonical field": ["dry_bulb_temperature_c", "relative_humidity_pct"],
            }
        )

        def previous(_legacy, _original):
            st.data_editor(editor_frame, key="geosphere_variable_editor::monthly")
            return st.form_submit_button("Load measured GeoSphere interval", type="primary")

        parity = SimpleNamespace(st=st, _render_geosphere_resource_selector=previous)
        install_geosphere_request_form(parity)

        self.assertTrue(parity._render_geosphere_resource_selector(None, None))
        self.assertEqual(calls, ["Load measured GeoSphere interval"])
        self.assertFalse(hasattr(st, "button"))
        committed = GeoSphereRequestState.from_mapping(st.session_state[COMMITTED_REQUEST_KEY])
        self.assertIsNotNone(committed)
        assert committed is not None
        self.assertEqual(committed.resource_id, "klima-v2-1m")
        self.assertEqual(committed.station_id, "105")
        self.assertEqual(committed.provider_parameters, ("tl_mittel",))
        self.assertTrue(committed.is_loadable)

    def test_request_boundary_source_does_not_patch_plain_streamlit_button(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "epw_climate_analyzer"
            / "geosphere_request_form.py"
        ).read_text(encoding="utf-8")
        self.assertIn("st.form_submit_button = form_submit_button", source)
        self.assertIn("st.form_submit_button = real_form_submit_button", source)
        self.assertNotIn("st.button = button", source)
        self.assertNotIn("real_button = st.button", source)


class GeoSphereTransactionalFormValidationTests(unittest.TestCase):
    def test_empty_submit_emits_one_persistent_warning_without_load_request(self) -> None:
        warnings: list[str] = []

        @contextmanager
        def form(*_args, **_kwargs):
            yield None

        st = SimpleNamespace(
            session_state={
                "geosphere_resource_id": "klima-v2-1m",
                "geosphere_selected_station_id": "105",
            },
            data_editor=lambda data, *args, **kwargs: data,
            button=lambda *_args, **_kwargs: False,
            warning=lambda body, *args, **kwargs: warnings.append(str(body)),
            form=form,
            caption=lambda *_args, **_kwargs: None,
            form_submit_button=lambda *_args, **_kwargs: True,
        )
        empty_frame = pd.DataFrame(
            {
                "Selected": [False],
                "Provider": ["tl_mittel"],
                "Variable": ["Air temperature — monthly mean"],
            }
        )
        message = "Select at least one measured GeoSphere variable to load."

        def previous(_legacy, _original):
            st.data_editor(empty_frame, key="geosphere_variable_editor::monthly")
            # The mature selector still emits its legacy zero-selection warning;
            # the transactional wrapper must suppress this duplicate and publish
            # exactly one post-form validation message instead.
            st.warning(message)
            return "blocked"

        parity = SimpleNamespace(st=st, _render_geosphere_resource_selector=previous)
        install_geosphere_variable_form_compat(parity)

        self.assertEqual(parity._render_geosphere_resource_selector(None, None), "blocked")
        self.assertEqual(warnings, [message])
        self.assertNotIn(ux._FORM_REQUEST_KEY, st.session_state)


class GeoSphereRuntimeBoundaryContractTests(unittest.TestCase):
    def test_transactional_form_and_request_boundary_precede_freeze_without_fragmenting_station_browser(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "epw_climate_analyzer"
            / "source_parity_runtime.py"
        ).read_text(encoding="utf-8")
        patch_pos = source.index("patch_variable_form_installer()")
        form_pos = source.index("install_geosphere_variable_form_compat(parity)")
        request_pos = source.index("install_geosphere_request_form(parity)")
        freeze_pos = source.index("_freeze_session_geosphere_selector(proxy, parity)")
        self.assertLess(patch_pos, form_pos)
        self.assertLess(form_pos, request_pos)
        self.assertLess(request_pos, freeze_pos)
        self.assertNotIn("fragment_factory", source)
        self.assertNotIn("fragment(execute_geosphere_selector)", source)
        # Request-state classes are pure value objects; reloading this module
        # would produce incompatible dataclass identities during one process.
        reset_block = source[source.index("module_names = (") : source.index("package = __package__")]
        self.assertNotIn('"geosphere_request_form"', reset_block)


if __name__ == "__main__":
    unittest.main()
