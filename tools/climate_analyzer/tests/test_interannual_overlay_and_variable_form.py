from __future__ import annotations

import inspect
from types import SimpleNamespace
import unittest

import pandas as pd

from epw_climate_analyzer import source_parity_monthly_surface_guard as surface_guard
from epw_climate_analyzer import source_parity_ux_followup as ux
from epw_climate_analyzer import source_parity_variable_form as variable_form
from epw_climate_analyzer import temporal_filtering


class _FakeForm:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeStreamlit:
    def __init__(self, edited: pd.DataFrame, *, submit: bool = True):
        self.session_state = {
            "geosphere_resource_id": "klima-v2-1h",
            "geosphere_selected_station_id": "105",
        }
        self._edited = edited
        self._submit = submit
        self.real_button_calls: list[str] = []
        self.warning_calls: list[str] = []
        self.caption_calls: list[str] = []
        self.form_calls: list[str] = []
        self.rerun_calls = 0

    def data_editor(self, data, *args, **kwargs):
        return self._edited.copy()

    def button(self, label, *args, **kwargs):
        self.real_button_calls.append(str(label))
        return False

    def warning(self, body, *args, **kwargs):
        self.warning_calls.append(str(body))

    def caption(self, body, *args, **kwargs):
        self.caption_calls.append(str(body))

    def form(self, key, clear_on_submit=False):
        self.form_calls.append(str(key))
        return _FakeForm()

    def form_submit_button(self, label, *args, **kwargs):
        return bool(self._submit)

    def rerun(self):
        self.rerun_calls += 1
        raise AssertionError("same-run form contract must not call st.rerun()")


class InterannualOverlayAndVariableFormTests(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        index = pd.DatetimeIndex(
            [
                "2022-01-01 00:00",
                "2022-01-15 00:00",
                "2023-01-01 00:00",
                "2023-01-15 00:00",
                "2023-02-01 00:00",
            ]
        )
        frame = pd.DataFrame({"value": [1.0, 3.0, 10.0, 14.0, 20.0]}, index=index)
        ux._enable_time_basis_contract()
        return temporal_filtering.with_time_basis(frame, ux.INTERANNUAL_OVERLAY)

    def test_interannual_monthly_summary_never_averages_across_years(self) -> None:
        slots, summaries = ux.interannual_year_summaries(self._frame(), "value", "Monthly")
        self.assertEqual(slots, [1, 2])
        self.assertEqual(sorted(summaries), [2022, 2023])

        self.assertAlmostEqual(float(summaries[2022].loc[1, "mean"]), 2.0)
        self.assertAlmostEqual(float(summaries[2022].loc[1, "min"]), 1.0)
        self.assertAlmostEqual(float(summaries[2022].loc[1, "max"]), 3.0)
        self.assertTrue(pd.isna(summaries[2022].loc[2, "mean"]))

        self.assertAlmostEqual(float(summaries[2023].loc[1, "mean"]), 12.0)
        self.assertAlmostEqual(float(summaries[2023].loc[1, "min"]), 10.0)
        self.assertAlmostEqual(float(summaries[2023].loc[1, "max"]), 14.0)
        self.assertAlmostEqual(float(summaries[2023].loc[2, "mean"]), 20.0)

        self.assertNotEqual(float(summaries[2022].loc[1, "mean"]), 7.0)
        self.assertNotEqual(float(summaries[2023].loc[1, "mean"]), 7.0)

    def test_interannual_profile_keeps_one_legend_group_per_real_year_and_gap(self) -> None:
        frame = self._frame()
        fig = ux._interannual_profile_chart(
            frame,
            "value",
            "Monthly",
            "Test",
            "°C",
            extensive=False,
            highlight_year=2023,
        )
        central = {trace.name: trace for trace in fig.data if trace.showlegend}
        self.assertEqual(set(central), {"2022", "2023"})
        self.assertEqual(list(central["2022"].y)[0], 2.0)
        self.assertTrue(pd.isna(list(central["2022"].y)[1]))
        self.assertEqual(list(central["2023"].y), [12.0, 20.0])
        self.assertFalse(bool(central["2022"].connectgaps))
        self.assertFalse(bool(central["2023"].connectgaps))
        self.assertGreater(float(central["2023"].line.width), float(central["2022"].line.width))

    def test_authoritative_submitted_request_restores_routing_without_mutating_widget_state(self) -> None:
        submitted = ("klima-v2-1m", "105")
        fake_st = SimpleNamespace(
            session_state={
                variable_form._FORM_REQUEST_KEY: submitted,
                "geosphere_resource_id": "klima-v2-1h",
                "_geosphere_resource_selector_widget_v1": "klima-v2-1h",
                "geosphere_selected_station_id": "999",
            }
        )

        self.assertTrue(variable_form.consume_geosphere_variable_form_load_request(fake_st))
        self.assertEqual(fake_st.session_state["geosphere_resource_id"], submitted[0])
        # The selectbox has already been instantiated when the mature load gate
        # runs. Streamlit forbids writing its widget-owned session-state key at
        # that point, so the handoff must leave it untouched.
        self.assertEqual(fake_st.session_state["_geosphere_resource_selector_widget_v1"], "klima-v2-1h")
        self.assertEqual(fake_st.session_state["geosphere_selected_station_id"], submitted[1])
        self.assertNotIn(variable_form._FORM_REQUEST_KEY, fake_st.session_state)
        self.assertFalse(variable_form.consume_geosphere_variable_form_load_request(fake_st))

    def test_v2_variable_form_submit_forwards_to_mature_load_same_run(self) -> None:
        edited = pd.DataFrame(
            {
                "Selected": [True, False],
                "Measured variable": ["Temperature", "Humidity"],
                "Provider": ["tl", "rf"],
            }
        )
        fake_st = _FakeStreamlit(edited, submit=True)
        captured: dict[str, object] = {}

        def base_selector(_legacy, _original):
            result = fake_st.data_editor(edited, key="geosphere_variable_editor")
            captured["selected"] = int(result["Selected"].sum())
            captured["load"] = fake_st.button(
                "Load measured GeoSphere interval",
                type="primary",
                key="load_geosphere_interval",
            )
            return result

        parity = SimpleNamespace(st=fake_st, _render_geosphere_resource_selector=base_selector)
        variable_form.install_geosphere_variable_form(parity)
        parity._render_geosphere_resource_selector(SimpleNamespace(), lambda: None)

        self.assertEqual(captured["selected"], 1)
        self.assertTrue(captured["load"])
        self.assertEqual(fake_st.rerun_calls, 0)
        self.assertNotIn(variable_form._FORM_REQUEST_KEY, fake_st.session_state)
        self.assertEqual(fake_st.real_button_calls, [])
        self.assertEqual(len(fake_st.form_calls), 1)
        self.assertTrue(any("staged locally" in text for text in fake_st.caption_calls))

    def test_monthly_variable_label_alias_enters_v2_transactional_form(self) -> None:
        edited = pd.DataFrame(
            {
                "Selected": [True, False],
                "Variable": ["Temperature — monthly mean", "Humidity — monthly mean"],
                "Provider": ["tl_mittel", "rf_mittel"],
            }
        )
        fake_st = _FakeStreamlit(edited, submit=True)
        fake_st.session_state["geosphere_resource_id"] = "klima-v2-1m"
        captured: dict[str, object] = {}

        def base_selector(_legacy, _original):
            source = edited.copy()
            source["Selected"] = False
            result = fake_st.data_editor(
                source,
                key="geosphere_variable_editor__monthly__v2__core__fixture",
            )
            captured["columns"] = tuple(result.columns)
            captured["load"] = fake_st.button(
                "Load measured GeoSphere interval",
                type="primary",
                key="load_geosphere_interval",
            )

        parity = SimpleNamespace(st=fake_st, _render_geosphere_resource_selector=base_selector)
        surface_guard._install_monthly_form_table_alias(parity)
        variable_form.install_geosphere_variable_form(parity)
        parity._render_geosphere_resource_selector(SimpleNamespace(), lambda: None)

        self.assertTrue(captured["load"])
        self.assertNotIn("Measured variable", captured["columns"])
        self.assertNotIn(variable_form._FORM_REQUEST_KEY, fake_st.session_state)
        self.assertEqual(fake_st.rerun_calls, 0)
        self.assertEqual(fake_st.real_button_calls, [])
        self.assertEqual(len(fake_st.form_calls), 1)

    def test_empty_v2_form_submit_warns_once_and_never_commits_request(self) -> None:
        edited = pd.DataFrame(
            {
                "Selected": [False, False],
                "Measured variable": ["Temperature", "Humidity"],
                "Provider": ["tl", "rf"],
            }
        )
        fake_st = _FakeStreamlit(edited, submit=True)
        captured: dict[str, object] = {}

        def base_selector(_legacy, _original):
            result = fake_st.data_editor(edited, key="geosphere_variable_editor")
            if int(result["Selected"].sum()) == 0:
                fake_st.warning("Select at least one measured GeoSphere variable to load.")
                captured["load"] = False
                return
            captured["load"] = fake_st.button(
                "Load measured GeoSphere interval",
                type="primary",
                key="load_geosphere_interval",
            )

        parity = SimpleNamespace(st=fake_st, _render_geosphere_resource_selector=base_selector)
        variable_form.install_geosphere_variable_form(parity)
        parity._render_geosphere_resource_selector(SimpleNamespace(), lambda: None)

        self.assertFalse(captured["load"])
        self.assertEqual(fake_st.warning_calls, ["Select at least one measured GeoSphere variable to load."])
        self.assertEqual(fake_st.rerun_calls, 0)
        self.assertNotIn(variable_form._FORM_REQUEST_KEY, fake_st.session_state)
        self.assertEqual(fake_st.real_button_calls, [])

    def test_monthly_surface_guard_wires_authoritative_v2_form_module(self) -> None:
        source = inspect.getsource(surface_guard.install_monthly_surface_guard)
        self.assertIn(
            "from .source_parity_variable_form import install_geosphere_variable_form",
            source,
        )
        self.assertNotIn(
            "from .source_parity_ux_followup import install_geosphere_variable_form",
            source,
        )


if __name__ == "__main__":
    unittest.main()
