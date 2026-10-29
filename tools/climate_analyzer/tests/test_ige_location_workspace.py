"""Public request semantics and map/widget synchronization, without providers."""
from __future__ import annotations

from hashlib import sha256
from dataclasses import replace
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from epw_climate_analyzer import location_picker as picker
from epw_climate_analyzer import engine_application as application
from epw_climate_analyzer.engine_ui import PRODUCT_KEY, REQUEST_KEY

APP = Path(__file__).resolve().parents[1] / "app.py"


class PointStateTests(unittest.TestCase):
    def state(self):
        state = {}
        picker.initialize_point(state)
        return state

    def click(self, state, latitude, longitude):
        key = f"ige_selected_point_map_{state[picker.EPOCH]}"
        state[key] = {"last_clicked": {"lat": latitude, "lng": longitude}}
        return picker.accept_map_click(state, key)

    def test_click_then_manual_edit_updates_one_point_and_clears_old_height(self):
        state = self.state()
        state[picker.HEIGHT] = 380.
        state[picker.HEIGHT_REFERENCE] = "Survey; local datum"
        self.assertTrue(self.click(state, 48.2082, 16.3738))
        self.assertEqual((state[picker.LATITUDE], state[picker.LONGITUDE]), (48.2082, 16.3738))
        self.assertIsNone(state[picker.HEIGHT])
        self.assertEqual(state[picker.HEIGHT_REFERENCE], "")
        state[picker.LATITUDE] = 47.3769
        state[picker.LONGITUDE] = 8.5417
        self.assertTrue(picker.coordinates_edited(state))
        self.assertEqual(state[picker.SELECTED], (47.3769, 8.5417))

    def test_same_point_does_not_clear_height_or_repeat_rerender(self):
        state = self.state()
        state[picker.HEIGHT] = 100.
        self.assertFalse(self.click(state, 47.5, 14.2))
        self.assertEqual(state[picker.HEIGHT], 100.)
        self.assertEqual(state[picker.EPOCH], 0)

    def test_stale_component_event_cannot_overwrite_a_later_manual_edit(self):
        state = self.state()
        old_key = "ige_selected_point_map_0"
        state[old_key] = {"last_clicked": {"lat": 48., "lng": 16.}}
        state[picker.LATITUDE] = 46.
        picker.coordinates_edited(state)
        self.assertFalse(picker.accept_map_click(state, old_key))
        self.assertEqual(state[picker.LATITUDE], 46.)

    def test_invalid_events_do_not_change_location(self):
        for click in (None, {}, {"lat": True, "lng": 1.}, {"lat": float("nan"), "lng": 0.},
                      {"lat": 91., "lng": 0.}, {"lat": 1., "lng": float("inf")}):
            with self.subTest(click=click):
                state = self.state()
                state["ige_selected_point_map_0"] = {"last_clicked": click}
                self.assertFalse(picker.accept_map_click(state, "ige_selected_point_map_0"))
                self.assertEqual(state[picker.SELECTED], (47.5, 14.2))

    def test_world_wrap_maps_to_the_same_canonical_longitude(self):
        state = self.state()
        self.assertTrue(self.click(state, 0., 181.))
        self.assertEqual(state[picker.LONGITUDE], -179.)

    def test_leaflet_marker_and_component_callback_use_current_point(self):
        state = self.state()
        state[picker.LATITUDE], state[picker.LONGITUDE] = 46., 7.
        picker.coordinates_edited(state)
        with patch("streamlit_folium.st_folium", return_value={}) as component:
            picker.render_location_map(state)
        fmap = component.call_args.args[0]
        markers = [child for child in fmap._children.values() if child.__class__.__name__ == "Marker"]
        self.assertEqual([marker.location for marker in markers], [[46., 7.]])
        self.assertEqual(component.call_args.kwargs["height"], 560)
        self.assertEqual(component.call_args.kwargs["returned_objects"], ["last_clicked"])
        key = component.call_args.kwargs["key"]
        state[key] = {"last_clicked": {"lat": 49., "lng": 10.}}
        component.call_args.kwargs["on_change"]()
        self.assertEqual(state[picker.SELECTED], (49., 10.))


class PublicWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = application.run_historical_product(application.pilot_historical_request())

    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("PUBLIC_MAP_TEST_NO_NETWORK"))
            guard.start(); self.addCleanup(guard.stop)
        # AppTest cannot drive Leaflet JS. The real component payload and callback
        # are tested above; here the actual app and native Streamlit widgets run.
        self.map = patch("epw_climate_analyzer.location_picker.render_location_map")
        self.map_mock = self.map.start(); self.addCleanup(self.map.stop)

    def app(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(APP, default_timeout=45).run()
        app.radio(key="climate_source_mode").set_value("Generate climate").run()
        self.clean(app)
        return app

    def clean(self, app):
        self.assertEqual([e.message for e in app.exception], [])
        self.assertEqual([e.value for e in app.error], [])

    def test_supplied_height_is_recorded_without_changing_weather_or_epw_height(self):
        with zipfile.ZipFile(io.BytesIO(self.original.files["sources.zip"])) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            receipts = {item["id"]: item for item in manifest["sources"]}
            payloads = {key: archive.read(key + ".json") for key in receipts}
        request = replace(application.pilot_historical_request(), site_elevation_m=378.8,
                          site_elevation_reference="Historical barometer metadata; datum unverified")
        with patch("epw_climate_analyzer.engine.historical.fetch_original",
                   side_effect=lambda key, spec: (payloads[key], receipts[key])) as fetch:
            product = application.run_historical_product(request, use_saved_pilot=False)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(product.files["climate.epw"], self.original.files["climate.epw"])
        self.assertEqual(product.report["diagnostics"]["site_height_m_requested"], 378.8)
        self.assertFalse(product.report["diagnostics"]["site_height_used_for_weather_correction"])
        output_manifest = json.loads(product.files["manifest.json"])
        self.assertEqual(output_manifest["request"]["site_elevation_reference"], request.site_elevation_reference)

    def test_public_route_has_point_editor_and_no_saved_city_or_future_pilot_selector(self):
        with patch("epw_climate_analyzer.engine_ui.run_historical_product") as run, \
                patch("epw_climate_analyzer.engine_ui.run_future_pilot_product") as future, \
                patch("epw_climate_analyzer.engine_ui.load_station_year_product") as station:
            app = self.app()
            self.assertNotIn("ige_historical_source", [x.key for x in app.selectbox])
            self.assertNotIn("ige_generation_mode", [x.key for x in app.radio])
            self.assertNotIn("ige_station_year_choice", [x.key for x in app.selectbox])
            self.assertEqual(app.number_input(key=picker.LATITUDE).value, 47.5)
            self.assertIsNone(app.number_input(key=picker.HEIGHT).value)
            self.assertTrue(any("not station interpolation" in item.value for item in app.info))
            self.assertTrue(any("not a guarantee" in item.value for item in app.caption))
            run.assert_not_called(); future.assert_not_called(); station.assert_not_called()
            self.map_mock.assert_called()

    def test_edits_move_point_but_do_not_fetch_and_height_needs_reference(self):
        with patch("epw_climate_analyzer.engine_ui.run_historical_product") as run:
            app = self.app()
            app.number_input(key=picker.LATITUDE).set_value(48.2082).run()
            app.number_input(key=picker.LONGITUDE).set_value(16.3738).run()
            self.assertEqual(app.session_state[picker.SELECTED], (48.2082, 16.3738))
            app.number_input(key=picker.HEIGHT).set_value(180.).run()
            self.assertTrue(app.button(key="ige_build_background").disabled)
            app.text_input(key=picker.HEIGHT_REFERENCE).set_value("Survey; datum unverified").run()
            self.assertFalse(app.button(key="ige_build_background").disabled)
            app.number_input(key=picker.LATITUDE).set_value(48.3).run()
            self.assertIsNone(app.number_input(key=picker.HEIGHT).value)
            self.assertEqual(app.text_input(key=picker.HEIGHT_REFERENCE).value, "")
            run.assert_not_called()
            self.clean(app)

    def test_build_passes_requested_point_year_and_height_with_no_saved_fallback(self):
        with patch("epw_climate_analyzer.engine_ui.run_historical_product", side_effect=TimeoutError("provider timeout")) as run:
            app = self.app()
            app.number_input(key=picker.LATITUDE).set_value(46.887).run()
            app.number_input(key=picker.LONGITUDE).set_value(8.622).run()
            app.number_input(key=picker.HEIGHT).set_value(438.).run()
            app.text_input(key=picker.HEIGHT_REFERENCE).set_value("Survey; LN02").run()
            app.number_input(key="ige_year").set_value(2024).run()
            app.button(key="ige_build_background").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("provider timeout" in e.value for e in app.error))
            self.assertEqual(run.call_count, 1)
            request = run.call_args.args[0]
            self.assertEqual((request.latitude, request.longitude, request.year), (46.887, 8.622, 2024))
            self.assertEqual(request.site_elevation_m, 438.)
            self.assertEqual(request.site_elevation_reference, "Survey; LN02")
            self.assertFalse(run.call_args.kwargs["use_saved_pilot"])
            self.assertEqual(len(app.download_button), 0)

    def test_failure_from_previous_point_is_not_assigned_to_an_edited_point(self):
        with patch("epw_climate_analyzer.engine_ui.run_historical_product", side_effect=TimeoutError("provider timeout")) as run:
            app = self.app()
            app.button(key="ige_build_background").click().run()
            self.assertTrue(any(x.value.startswith("This request") for x in app.error))
            app.number_input(key=picker.LATITUDE).set_value(49.).run()
            self.assertTrue(any(x.value.startswith("Previous request") for x in app.error))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(len(app.exception), 0)

    def test_edit_and_failed_build_keep_last_product_visibly_separate(self):
        app = self.app()
        with patch("epw_climate_analyzer.engine_ui.run_historical_product", return_value=self.original) as run:
            app.button(key="ige_build_background").click().run(); self.clean(app)
            self.assertEqual(run.call_count, 1)
            old_request = app.session_state[REQUEST_KEY]
            old_product = app.session_state[PRODUCT_KEY]
            self.assertEqual(len(app.download_button), 4)
            self.assertTrue(all(item.proto.url for item in app.download_button))
            app.number_input(key=picker.LATITUDE).set_value(49.).run(); self.clean(app)
            self.assertTrue(any(x.value == "Previous completed result" for x in app.subheader))
            self.assertEqual(run.call_count, 1)
        with patch("epw_climate_analyzer.engine_ui.run_historical_product", side_effect=ValueError("IGE_MISSING_NONFINITE_OR_NONNUMERIC_SOURCE_temperature_2m")):
            app.button(key="ige_build_background").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("temperature_2m" in e.value for e in app.error))
        self.assertIs(app.session_state[PRODUCT_KEY], old_product)
        self.assertEqual(app.session_state[REQUEST_KEY], old_request)
        self.assertEqual(sha256(old_product.files["climate.epw"]).hexdigest(), application.HISTORICAL_EPW_SHA)


if __name__ == "__main__":
    unittest.main()
