"""Actual Streamlit source router and state changes, with offline product fixtures."""
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from epw_climate_analyzer import location_picker as picker
from epw_climate_analyzer import point_interpolation as service
from epw_climate_analyzer.point_interpolation_ui import PRODUCT_KEY
from test_ige_s1_point_interpolation import epw_inputs

APP = Path(__file__).resolve().parents[1]/"app.py"


class S1UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request, epws = epw_inputs()
        cls.complete = service.run_point_product(cls.request, mode="EPW", epws=epws, actual_year_confirmed=True)
        cls.blocked = service.run_point_product(cls.request, mode="EPW", epws=epws[:3], actual_year_confirmed=True)
        from epw_climate_analyzer.engine_application import run_historical_product, pilot_historical_request
        background = run_historical_product(pilot_historical_request())
        cls.composite = service.run_point_product(cls.request, mode="EPW", epws=epws, actual_year_confirmed=True,
                                                include_background=True, background_product=background)

    def setUp(self):
        for name in ("socket.socket.connect", "socket.socket.connect_ex"):
            p = patch(name, side_effect=AssertionError("S1_UI_OFFLINE")); p.start(); self.addCleanup(p.stop)
        lookup = patch("epw_climate_analyzer.site_elevation.lookup_elevation", side_effect=ValueError("OFFLINE"))
        lookup.start(); self.addCleanup(lookup.stop)
        p = patch("epw_climate_analyzer.location_picker.render_location_map")
        self.map = p.start(); self.addCleanup(p.stop)
        p = patch("epw_climate_analyzer.climate_maps.station_location_markers", return_value=[
            {"latitude": 47.1, "longitude": 15.4, "station_id": "TEST", "selected": False,
             "label": "Test metadata station", "detail": "Year completeness unchecked"}])
        self.locations = p.start(); self.addCleanup(p.stop)

    def clean(self, app):
        self.assertEqual([e.message for e in app.exception], [])
        self.assertEqual([e.value for e in app.error], [])

    def app(self):
        app = AppTest.from_file(APP, default_timeout=60).run()
        app.radio(key="climate_source_mode").set_value("Generate climate").run()
        app.radio(key="ige_historical_method").set_value("Station / EPW interpolation").run()
        self.clean(app)
        return app

    def ready(self, app):
        app.number_input(key=picker.LATITUDE).set_value(self.request.latitude).run()
        app.number_input(key=picker.LONGITUDE).set_value(self.request.longitude).run()
        app.number_input(key=picker.HEIGHT).set_value(400.).run()
        app.session_state[picker.HEIGHT_REFERENCE] = self.request.elevation_reference
        app.text_input(key="ige_s1_label").set_value(self.request.label).run()
        self.clean(app)
        return app

    def test_default_station_locations_and_enabled_build_without_method_checkboxes(self):
        with patch("epw_climate_analyzer.point_interpolation_ui.run_point_product") as run:
            app = self.app()
            self.assertTrue(app.button(key="ige_s1_build").disabled)
            self.ready(app)
            self.assertFalse(app.button(key="ige_s1_build").disabled)
            self.assertEqual(len(self.map.call_args.kwargs["sources"]), 1)
            self.assertEqual(self.map.call_args.kwargs["sources"][0]["station_id"], "TEST")
            self.assertTrue({"ige_s1_phase", "ige_s1_height_proxy", "ige_s1_background"}.isdisjoint({x.key for x in app.checkbox}))
            self.assertEqual(self.map.call_args.kwargs["purpose"], "interpolation")
            self.assertTrue(any("used in temperature" in e.value for e in app.info))
            app.run(); run.assert_not_called()
            self.locations.assert_called_once()

    def test_point_move_clears_height_and_requires_a_new_reference(self):
        with patch("epw_climate_analyzer.point_interpolation_ui.run_point_product") as run:
            app = self.ready(self.app())
            app.number_input(key=picker.LATITUDE).set_value(48.).run()
            self.assertIsNone(app.number_input(key=picker.HEIGHT).value)
            self.assertTrue(app.button(key="ige_s1_build").disabled)
            self.assertEqual(app.session_state[picker.HEIGHT_REFERENCE], "")
            run.assert_not_called()

    def test_core_only_downloads_do_not_offer_epw(self):
        with patch("epw_climate_analyzer.point_interpolation_ui.run_point_product", return_value=self.complete) as run:
            app = self.ready(self.app())
            app.checkbox(key="ige_s1_core_only").check().run()
            app.button(key="ige_s1_build").click().run(); self.clean(app)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], self.request)
            self.assertFalse(run.call_args.kwargs["include_background"])
            self.assertEqual(len(app.download_button), 3)
            monthly = app.dataframe[0].value
            self.assertEqual(len(monthly), 12)
            self.assertEqual(set(monthly.index.year), {self.request.year})
            self.assertEqual(list(monthly.index.month), list(range(1, 13)))
            self.assertNotIn("ige_s1_download_epw", [d.key for d in app.download_button])
            app.run(); run.assert_called_once()

    def test_failed_donor_admission_displays_report_without_epw_or_fake_success(self):
        with patch("epw_climate_analyzer.point_interpolation_ui.run_point_product", return_value=self.blocked):
            app = self.ready(self.app()); app.button(key="ige_s1_build").click().run(); self.clean(app)
            self.assertTrue(any("cannot be reconstructed" in e.value for e in app.warning))
            self.assertEqual(len(app.download_button), 3)
            self.assertEqual(len(app.success), 0)

    def test_only_complete_explicit_composite_exposes_epw_download(self):
        with patch("epw_climate_analyzer.point_interpolation_ui.run_point_product", return_value=self.composite) as run:
            app = self.ready(self.app())
            run.assert_not_called()
            app.button(key="ige_s1_build").click().run(); self.clean(app)
            self.assertTrue(run.call_args.kwargs["include_background"])
            self.assertEqual(len(app.download_button), 4)
            self.assertTrue(all(d.proto.url for d in app.download_button))
            self.assertTrue(any("gridded background" in e.value for e in app.caption))

    def test_station_map_failure_can_retry_and_does_not_disable_a_valid_weather_request(self):
        self.locations.side_effect = [TimeoutError("metadata timeout"), self.locations.return_value]
        app = self.ready(self.app())
        self.assertFalse(app.button(key="ige_s1_build").disabled)
        self.assertEqual(self.locations.call_count, 1)
        app.button(key="ige_s1_retry_stations").click().run()
        self.assertEqual(self.locations.call_count, 2)
        self.assertEqual(len(self.map.call_args.kwargs["sources"]), 1)
        self.assertNotIn("ige_s1_retry_stations", [b.key for b in app.button])

    def test_changed_elevation_cannot_show_old_donors_as_current_admitted_sources(self):
        with patch("epw_climate_analyzer.point_interpolation_ui.run_point_product", return_value=self.complete) as run:
            app = self.ready(self.app())
            app.button(key="ige_s1_build").click().run(); self.clean(app)
            self.assertEqual(sum(bool(m["selected"]) for m in self.map.call_args.kwargs["sources"]), 4)
            app.number_input(key=picker.HEIGHT).set_value(500.).run(); self.clean(app)
            self.assertFalse(any(m["selected"] for m in self.map.call_args.kwargs["sources"]))
            self.assertTrue(any("previous completed point" in w.value for w in app.warning))
            run.assert_called_once()

    def test_edits_and_failed_request_keep_previous_product_with_correct_label(self):
        app = self.ready(self.app())
        with patch("epw_climate_analyzer.point_interpolation_ui.run_point_product", return_value=self.complete):
            app.button(key="ige_s1_build").click().run(); self.clean(app)
        previous = app.session_state[PRODUCT_KEY]
        with patch("epw_climate_analyzer.point_interpolation_ui.run_point_product", side_effect=TimeoutError("source timeout")) as run:
            app.number_input(key="ige_s1_year").set_value(2024).run()
            run.assert_not_called()
            self.assertTrue(any("previous completed point" in e.value for e in app.warning))
            app.button(key="ige_s1_build").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIs(app.session_state[PRODUCT_KEY], previous)
            self.assertEqual(len(app.download_button), 3)
            self.assertTrue(any("source timeout" in e.value for e in app.error))

    def test_upload_mode_needs_four_files_and_actual_year_confirmation(self):
        with patch("epw_climate_analyzer.point_interpolation_ui.run_point_product") as run:
            app = self.ready(self.app())
            app.selectbox(key="ige_s1_source").set_value("Upload synchronous actual-year EPWs").run()
            self.clean(app)
            self.assertTrue(app.button(key="ige_s1_build").disabled)
            app.checkbox(key="ige_s1_actual_year").check().run()
            self.assertTrue(app.button(key="ige_s1_build").disabled)
            run.assert_not_called()


if __name__ == "__main__": unittest.main()
