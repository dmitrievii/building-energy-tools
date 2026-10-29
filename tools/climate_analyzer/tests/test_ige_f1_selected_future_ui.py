"""Execute the real public Streamlit router; all weather requests forbidden."""
from pathlib import Path
from dataclasses import replace
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from epw_climate_analyzer.climate_sources import ClimateFilePayload
from epw_climate_analyzer.engine_application import run_historical_product,pilot_historical_request
from epw_climate_analyzer.future_selected_ui import PRODUCT_KEY
from test_ige_f1_selected_future import synthetic_base

APP = Path(__file__).resolve().parents[1]/"app.py"


class F1UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from f1_replay_audit import replay_f1_example
        cls.historical = run_historical_product(pilot_historical_request())
        cls.future,_ = replay_f1_example()
        cls.epw = synthetic_base().epw

    def setUp(self):
        for name in ("socket.socket.connect","socket.socket.connect_ex"):
            p=patch(name,side_effect=AssertionError("F1_UI_NO_WEATHER_NETWORK"));p.start();self.addCleanup(p.stop)
        p=patch("epw_climate_analyzer.location_picker.render_location_map");p.start();self.addCleanup(p.stop)

    def clean(self, app): self.assertEqual([e.message for e in app.exception],[])

    def app(self, historical=False, active=False):
        app=AppTest.from_file(APP,default_timeout=60).run()
        if historical: app.session_state["ige_engine_completed_product"]=self.historical
        if active: app.session_state["active_climate_file"]=ClimateFilePayload("synthetic.epw",self.epw,"SYNTHETIC TEST")
        if active:
            app.run()
            app.sidebar.radio(key="climate_analyzer_navigation").set_value("Climate File Source").run()
        app.radio(key="climate_source_mode").set_value("Generate climate").run()
        app.radio(key="ige_climate_task").set_value("Future climate from selected base").run()
        self.clean(app);return app

    def test_empty_workspace_cannot_generate_arbitrary_future(self):
        with patch("epw_climate_analyzer.future_selected_ui.run_selected_future") as run:
            app=self.app()
            self.assertTrue(app.button(key="ige_f1_build").disabled)
            self.assertEqual(len(app.selectbox(key="ige_f1_base_choice").options),2)
            app.run();run.assert_not_called()

    def test_completed_background_supplies_identity_without_fixed_city_choices(self):
        with patch("epw_climate_analyzer.future_selected_ui.run_selected_future") as run:
            app=self.app(historical=True)
            self.assertFalse(app.button(key="ige_f1_build").disabled)
            self.assertEqual(app.selectbox(key="ige_f1_reference_mode").value,"Same-chain multi-year background reference")
            self.assertEqual(app.selectbox(key="ige_f1_base_choice").value,self.historical.report["engine_EPW_sha256"])
            app.number_input(key="ige_f1_future_first").set_value(2050).run()
            app.number_input(key="ige_f1_future_last").set_value(2069).run()
            run.assert_not_called()

    def test_active_epw_requires_source_and_period_admission(self):
        with patch("epw_climate_analyzer.future_selected_ui.run_selected_future") as run:
            app=self.app(active=True)
            self.assertTrue(app.button(key="ige_f1_build").disabled)
            app.checkbox(key="ige_f1_source_assumptions").check().run()
            app.selectbox(key="ige_f1_reference_mode").set_value("Selected representative base").run()
            self.assertTrue(app.button(key="ige_f1_build").disabled)
            app.text_input(key="ige_f1_period_evidence").set_value("Synthetic 2002–2014 control").run()
            app.checkbox(key="ige_f1_liquid_proxy").check().run()
            self.clean(app);self.assertFalse(app.button(key="ige_f1_build").disabled)
            run.assert_not_called()

    def test_actual_year_needs_separate_reference_without_auto_relabelling(self):
        with patch("epw_climate_analyzer.future_selected_ui.run_selected_future") as run:
            app=self.app(active=True)
            app.checkbox(key="ige_f1_source_assumptions").check().run()
            app.selectbox(key="ige_f1_calendar").set_value("Actual observed year").run()
            app.text_input(key="ige_f1_period_evidence").set_value("Evidence cannot turn 2023 into 2002–2014 climate").run()
            app.checkbox(key="ige_f1_liquid_proxy").check().run()
            self.assertTrue(app.button(key="ige_f1_build").disabled)
            self.assertNotIn("Same-chain multi-year background reference",app.selectbox(key="ige_f1_reference_mode").options)
            run.assert_not_called()

    def test_build_has_downloads_and_edits_or_failure_preserve_previous_product(self):
        app=self.app(historical=True)
        with patch("epw_climate_analyzer.future_selected_ui.run_selected_future",return_value=self.future) as run:
            app.button(key="ige_f1_build").click().run();self.clean(app)
            run.assert_called_once();self.assertEqual(run.call_args.args[0].sha256,self.historical.report["engine_EPW_sha256"])
        previous=app.session_state[PRODUCT_KEY]
        self.assertEqual(len(app.download_button),5)
        self.assertTrue(all(d.proto.url for d in app.download_button))
        with patch("epw_climate_analyzer.future_selected_ui.run_selected_future",side_effect=TimeoutError("NASA unavailable")) as run:
            app.selectbox(key="ige_f1_ssp").set_value("ssp585").run();run.assert_not_called()
            self.assertTrue(any("previous completed base" in w.value for w in app.warning))
            app.button(key="ige_f1_build").click().run();self.clean(app)
            self.assertIs(app.session_state[PRODUCT_KEY],previous)
            self.assertTrue(any("NASA unavailable" in e.value for e in app.error))

    def test_future_explore_uses_common_analysis_and_keeps_original_base_available(self):
        app=self.app(historical=True)
        with patch("epw_climate_analyzer.future_selected_ui.run_selected_future",return_value=self.future):
            app.button(key="ige_f1_build").click().run();self.clean(app)
            app.button(key="ige_f1_explore").click().run();self.clean(app)
        self.assertEqual(app.session_state["ige_engine_completed_product"].report["product_kind"],"F1_SELECTED_BASE_FUTURE")
        self.assertIn(self.historical.report["engine_EPW_sha256"],app.session_state["ige_f1_base_candidates"])

    def test_source_packet_mode_needs_upload_and_matching_rebuild_reuses_original_packet(self):
        with patch("epw_climate_analyzer.future_selected_ui.run_selected_future",return_value=self.future) as run:
            app=self.app(historical=True)
            app.selectbox(key="ige_f1_nasa_source_mode").set_value("Use a saved original NASA source packet").run()
            self.assertTrue(app.button(key="ige_f1_build").disabled);run.assert_not_called()
            app.selectbox(key="ige_f1_nasa_source_mode").set_value("Acquire original data / reuse matching completed request").run()
            app.button(key="ige_f1_build").click().run();self.clean(app)
            self.assertIsNone(run.call_args.kwargs["nex_packet"])
            app.button(key="ige_f1_build").click().run();self.clean(app)
            self.assertEqual(run.call_args.kwargs["nex_packet"],self.future.files["source_packets/NASA_NEX_original.sources.zip"])

    def test_a_stored_base_rejected_by_f1_does_not_prevent_another_base_selection(self):
        invalid=replace(self.historical,files={**self.historical.files,"climate.epw":b"incomplete"})
        app=AppTest.from_file(APP,default_timeout=60).run()
        app.session_state["ige_engine_completed_product"]=invalid
        app.radio(key="climate_source_mode").set_value("Generate climate").run()
        app.radio(key="ige_climate_task").set_value("Future climate from selected base").run();self.clean(app)
        self.assertTrue(any("not admitted for F1" in w.value for w in app.warning))
        self.assertTrue(app.button(key="ige_f1_build").disabled)


if __name__ == "__main__": unittest.main()
