"""Actual Streamlit widgets and source-router integration for H1."""
from dataclasses import replace
from hashlib import sha256
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from epw_climate_analyzer import geosphere as geo
from epw_climate_analyzer import geosphere_station_year as source
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.station_epw_admission import assess_station_year
from epw_climate_analyzer.station_year_ui import PRODUCT_KEY
from test_ige_h1_station_year import complete_inputs, metadata_fixture, replay_fixture

SCRIPT = '''
import streamlit as st
from epw_climate_analyzer.geosphere import GeoSphereStation
from epw_climate_analyzer.station_year_ui import render_station_year
station = GeoSphereStation("12345", "Synthetic fixture", 47.5, 14.2, 400.,
    valid_from="2000-01-01T00:00:00+00:00", valid_to="2100-12-31T00:00:00+00:00")
render_station_year(st, station, {"start_time": "1880-04-01T00:00:00+00:00"})
'''


class StationYearUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        request, packet = replay_fixture()
        cls.refused = source.run_station_year(request, source_packet=packet,
                                             expected_sha256=sha256(packet).hexdigest())

    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("H1_UI_NO_NETWORK"))
            guard.start(); self.addCleanup(guard.stop)

    def app(self):
        app = AppTest.from_string(SCRIPT, default_timeout=45).run()
        app.number_input(key="ige_h1_year_12345").set_value(2023).run()
        self.clean(app)
        return app

    def clean(self, app):
        self.assertEqual([e.message for e in app.exception], [])
        self.assertEqual([e.value for e in app.error], [])

    def test_editing_year_and_rerendering_do_not_acquire_measurements(self):
        with patch("epw_climate_analyzer.station_year_ui.run_station_year") as run:
            app = self.app()
            app.number_input(key="ige_h1_year_12345").set_value(2024).run()
            app.run(); self.clean(app)
            run.assert_not_called()
            self.assertEqual(len(app.download_button), 0)

    def test_refused_year_still_has_coverage_sources_and_full_gap_downloads(self):
        with patch("epw_climate_analyzer.station_year_ui.run_station_year", return_value=self.refused) as run:
            app = self.app()
            app.button(key="ige_h1_load_year").click().run(); self.clean(app)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], self.refused.request)
            self.assertTrue(any("cannot be formed" in e.value for e in app.warning))
            self.assertEqual(len(app.download_button), 3)
            self.assertTrue(all(item.proto.url for item in app.download_button))
            self.assertNotIn("ige_h1_download_epw", [item.key for item in app.download_button])
            app.run(); self.clean(app)
            self.assertEqual(run.call_count, 1)

    def test_failed_new_request_keeps_old_report_and_marks_its_station_year(self):
        app = self.app()
        with patch("epw_climate_analyzer.station_year_ui.run_station_year", return_value=self.refused):
            app.button(key="ige_h1_load_year").click().run(); self.clean(app)
        previous = app.session_state[PRODUCT_KEY]
        with patch("epw_climate_analyzer.station_year_ui.run_station_year", side_effect=TimeoutError("metadata timeout")) as run:
            app.number_input(key="ige_h1_year_12345").set_value(2024).run()
            self.assertTrue(any("previous station/year" in e.value for e in app.warning))
            run.assert_not_called()
            app.button(key="ige_h1_load_year").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("metadata timeout" in e.value for e in app.error))
            self.assertIs(app.session_state[PRODUCT_KEY], previous)
            self.assertEqual(len(app.download_button), 3)

    def test_only_an_admitted_product_exposes_epw_download(self):
        r, l, f, fields = complete_inputs()
        a = assess_station_year(r, l, f, fields, source_id="SYNTHETIC_TEST")
        report = {**a.report, "additional_source_fields": []}
        files = {"climate.epw": a.epw, "admission.json": json_bytes(report), "missing_hours.csv.gz": b"fixture"}
        product = source.StationYearProduct(r, report, files, source._zip(files))
        with patch("epw_climate_analyzer.station_year_ui.run_station_year", return_value=product):
            app = self.app()
            app.button(key="ige_h1_load_year").click().run(); self.clean(app)
            self.assertIn("ige_h1_download_epw", [item.key for item in app.download_button])
            self.assertEqual(len(app.download_button), 4)

    def test_real_app_hourly_source_contains_the_same_annual_tool(self):
        from pathlib import Path
        import streamlit as st
        st.cache_data.clear()
        metadata = metadata_fixture()
        with patch("epw_climate_analyzer.geosphere.fetch_metadata", return_value=metadata), \
             patch("streamlit_folium.st_folium", return_value={}), \
             patch("epw_climate_analyzer.station_year_ui.run_station_year", return_value=self.refused) as run:
            app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=60).run()
            app.radio(key="climate_source_mode").set_value("GeoSphere Austria").run()
            app.selectbox(key="_geosphere_resource_selector_widget_v1").set_value("klima-v2-1h").run()
            self.clean(app)
            self.assertEqual(app.session_state["geosphere_resource_id"], "klima-v2-1h")
            app.number_input(key="ige_h1_year_12345").set_value(2023).run()
            run.assert_not_called()
            app.button(key="ige_h1_load_year").click().run(); self.clean(app)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(len(app.download_button), 3)
