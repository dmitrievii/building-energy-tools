"""U1 source-phase, calendar, transactional output and actual Streamlit routes.

AppTest executes the real app entry point and its runtime installers. These
checks qualify UI/software behaviour, not local climate or station accuracy.
"""
from __future__ import annotations

from dataclasses import replace
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import pandas as pd

from epw_climate_analyzer import engine_application as application
from epw_climate_analyzer.engine_analysis import (
    UI_CONTRACT, prepare_engine_analysis_frame, monthly_engine_summary, T, TD, RH, P, Q,
)
from epw_climate_analyzer.engine.thermodynamics import EPSILON, e_from_q, saturation_nasa_phase_pa

APP = Path(__file__).resolve().parents[1] / "app.py"
FUTURE_EPW_SHA = "fc00e09811498c368965785ee8873bc4ca1cd01761eaebb19c759faebd0e3c28"


class ActualProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("socket.socket.connect", side_effect=RuntimeError("U1_WEATHER_NETWORK_FORBIDDEN")), \
                patch("socket.socket.connect_ex", side_effect=RuntimeError("U1_WEATHER_NETWORK_FORBIDDEN")):
            cls.historical = application.run_historical_product(application.pilot_historical_request())
            cls.future = application.run_future_pilot_product()

    def test_original_epw_bytes_are_not_changed_by_UI_integration(self):
        for product, expected in ((self.historical, application.HISTORICAL_EPW_SHA), (self.future, FUTURE_EPW_SHA)):
            self.assertEqual(sha256(product.files["climate.epw"]).hexdigest(), expected)
            self.assertEqual(len(product.dataset.data), 8760)

    def test_real_year_and_representative_calendar_do_not_become_typical_year(self):
        self.assertEqual(self.historical.dataset.temporal.calendar_mode, "historical")
        self.assertEqual(self.future.dataset.temporal.calendar_mode, "climatology")
        for product in (self.historical, self.future):
            self.assertEqual(str(product.dataset.start), "2023-01-01 00:00:00+01:00")
            self.assertEqual(str(product.dataset.end), "2023-12-31 23:00:00+01:00")
            self.assertEqual(product.report["state_sample_offset_minutes"], 60)
        self.assertEqual(self.future.report["future_request"]["future_window"], [2040, 2059])

    def test_analysis_preserves_all_original_states_and_source_metadata(self):
        for product in (self.historical, self.future):
            original = product.dataset.data.copy(deep=True)
            analysed = prepare_engine_analysis_frame(product.dataset)
            pd.testing.assert_frame_equal(product.dataset.data, original)
            for column in original:
                np.testing.assert_array_equal(analysed[column], original[column])
            self.assertFalse(analysed.attrs["ige_UI_humidity_phase_adapter_required"])
            self.assertTrue(product.dataset.data.attrs["ige_UI_humidity_phase_adapter_required"])

    def test_future_q_and_dry_air_mixing_ratio_are_preserved(self):
        data = prepare_engine_analysis_frame(self.future.dataset)
        np.testing.assert_array_equal(data[Q], self.future.dataset.data[Q])
        np.testing.assert_allclose(data["humidity_ratio_g_kg"], 1000*data[Q]/(1-data[Q]), rtol=1e-14)
        np.testing.assert_allclose(data["vapor_pressure_pa"], e_from_q(data[Q], data[P]), rtol=1e-14)

    def test_ice_supersaturation_does_not_clip_water_states(self):
        data = prepare_engine_analysis_frame(self.future.dataset)
        rh_ice = 100*data["vapor_pressure_pa"].to_numpy()/saturation_nasa_phase_pa(data[T])
        self.assertGreater(int(((data[T] < 0) & (rh_ice > 100)).sum()), 0)
        self.assertLessEqual(float(data[RH].max()), 100)
        self.assertFalse(data.attrs["ige_ui_analysis"]["ice_supersaturation_clipped"])

    def test_historical_rounding_uses_source_RH_and_keeps_Td(self):
        data = prepare_engine_analysis_frame(self.historical.dataset)
        expected = data[RH]/100 * 610.94*np.exp(17.625*data[T]/(243.04+data[T]))
        np.testing.assert_allclose(data["vapor_pressure_pa"], expected, rtol=1e-14)
        np.testing.assert_array_equal(data[TD], self.historical.dataset.data[TD])
        self.assertTrue(data.attrs["ige_ui_analysis"]["historical_q_is_display_estimate_not_source_observation"])

    def test_below_zero_phase_is_not_silently_switched_to_ice(self):
        frame = self.historical.dataset.data.copy()
        frame.iloc[0, frame.columns.get_loc(T)] = -10.
        frame.iloc[0, frame.columns.get_loc(RH)] = 90.
        data = prepare_engine_analysis_frame(replace(self.historical.dataset, data=frame))
        e_water = .9*610.94*np.exp(17.625*-10/(243.04-10))
        e_ice = .9*float(saturation_nasa_phase_pa(-10.))
        self.assertAlmostEqual(data["vapor_pressure_pa"].iloc[0], e_water, places=10)
        self.assertGreater(abs(e_water-e_ice), 10.)

    def test_zero_vapour_is_not_given_a_display_humidity_floor(self):
        frame = self.historical.dataset.data.copy()
        frame.iloc[0, frame.columns.get_loc(RH)] = 0.
        data = prepare_engine_analysis_frame(replace(self.historical.dataset, data=frame))
        self.assertEqual(data["humidity_ratio_g_kg"].iloc[0], 0.)

    def test_unknown_phase_missing_q_or_changed_future_state_fail_closed(self):
        for change in ("phase", "q", "RH", "pressure"):
            frame = self.future.dataset.data.copy(deep=True)
            if change == "phase": frame.attrs["ige_RH_phase"] = "unknown"
            elif change == "q": frame = frame.drop(columns=[Q])
            elif change == "RH": frame.iloc[0, frame.columns.get_loc(RH)] -= 1.
            else: frame.iloc[0, frame.columns.get_loc(P)] += 100.
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare_engine_analysis_frame(replace(self.future.dataset, data=frame))

    def test_missing_or_negative_pressure_has_no_default_fallback(self):
        for value in (np.nan, -1.):
            frame = self.historical.dataset.data.copy(deep=True)
            frame.iloc[0, frame.columns.get_loc(P)] = value
            with self.assertRaisesRegex(ValueError, "NO_FALLBACK"):
                prepare_engine_analysis_frame(replace(self.historical.dataset, data=frame))

    def test_monthly_flux_and_precipitation_are_summed_not_averaged(self):
        for product in (self.historical, self.future):
            data = prepare_engine_analysis_frame(product.dataset)
            monthly = monthly_engine_summary(data)
            self.assertEqual(int(monthly["Hours"].sum()), 8760)
            self.assertAlmostEqual(monthly["GHI [kWh/m²]"].sum(), data["global_horizontal_radiation_wh_m2"].sum()/1000, places=10)
            self.assertAlmostEqual(monthly["Total precipitation [mm]"].sum(), data["total_precipitation_depth_mm"].sum(), places=10)

    def test_quality_axes_and_unqualified_claims_remain_separate(self):
        for product in (self.historical, self.future):
            report = product.report
            self.assertEqual(set(report["quality"]), {"execution_correctness", "physical_admissibility", "independent_accuracy", "operational_and_application_scope"})
            self.assertTrue(report["UI_connected"])
            self.assertFalse(report["production_ready"])
            self.assertFalse(report["IV1_station_observations_opened"])
            self.assertFalse(report["NASA_hurs_signal_enforced"])
            self.assertFalse(report["EnergyPlus_building_simulation_run"])
            self.assertEqual(report["weather_provider_requests_this_run"], 0)

    def test_requested_location_and_grid_proxy_are_not_conflated(self):
        for product in (self.historical, self.future):
            d = product.report["source_geometry"]
            self.assertEqual(d["requested_point"], [47.0707, 15.4395])
            self.assertEqual(d["background_cell"], [47., 15.5])
            self.assertAlmostEqual(d["requested_to_background_distance_km"], 9.100825, places=5)
            self.assertEqual(d["elevation_m_provider_response_proxy"], 467.)
            self.assertFalse(d["local_height_correction_applied"])

    def test_download_zip_contains_exact_epw_analysis_and_original_sources(self):
        for product in (self.historical, self.future):
            with zipfile.ZipFile(io.BytesIO(product.archive)) as archive:
                self.assertEqual(set(archive.namelist()), set(product.files))
                for name, body in product.files.items(): self.assertEqual(archive.read(name), body)
            analysis = pd.read_csv(io.BytesIO(gzip.decompress(product.files["analysis_state.csv.gz"])))
            self.assertEqual(len(analysis), 8760)
            self.assertTrue("interval_start_local_standard" in analysis)
        self.assertEqual(len(self.future.report["retained_source_packets_sha256"]), 4)
        self.assertIn("sources.zip", self.historical.files)

    def test_saved_source_cannot_replace_a_different_requested_point(self):
        other = replace(application.pilot_historical_request(), latitude=48.)
        with patch.object(application, "run_historical") as run:
            with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"):
                application.run_historical_product(other)
            run.assert_not_called()

    def test_live_request_is_passed_to_engine_and_failure_produces_no_product(self):
        request = replace(application.pilot_historical_request(), latitude=48., year=2024, label="AT test")
        directories = []
        def fail(received, output, **kwargs):
            self.assertEqual(received, request)
            self.assertIsNone(kwargs["source_bundle"])
            self.assertIsNone(kwargs["source_bundle_sha256"])
            directories.append(output.parent)
            raise TimeoutError("simulated provider unavailable")
        with patch.object(application, "run_historical", side_effect=fail):
            with self.assertRaises(TimeoutError): application.run_historical_product(request, use_saved_pilot=False)
        self.assertTrue(all(not p.exists() for p in directories))

    def test_output_manifest_hash_gate_rejects_modified_or_incomplete_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.assertRaisesRegex(ValueError, "INCOMPLETE"):
                application._complete_product(None, output, {})
            for name, body in self.historical.files.items():
                if name in json.loads(self.historical.files["manifest.json"])["files"] or name == "manifest.json":
                    (output/name).write_bytes(body)
            with (output/"climate.epw").open("ab") as stream: stream.write(b"mutated")
            with self.assertRaisesRegex(ValueError, "OUTPUT_HASH_MISMATCH"):
                application._complete_product(None, output, {})


class StreamlitRouteTests(unittest.TestCase):
    """Preserved offline research examples through the real app router."""
    def setUp(self):
        from epw_climate_analyzer.engine_ui import render_engine_research_examples
        replay = patch("epw_climate_analyzer.engine_ui.render_engine_source", render_engine_research_examples)
        replay.start(); self.addCleanup(replay.stop)
        self.stack = []
        for target in ("socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(target, side_effect=RuntimeError("U1_APPTEST_NETWORK_FORBIDDEN"))
            guard.start(); self.addCleanup(guard.stop)

    def app(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(APP, default_timeout=45).run()
        self.clean(app)
        app.radio(key="climate_source_mode").set_value("Generate climate").run()
        self.clean(app)
        return app

    def clean(self, app):
        self.assertEqual([e.message for e in app.exception], [])
        self.assertEqual([e.value for e in app.error], [])

    def test_full_app_two_actual_years_plots_downloads_and_reruns(self):
        from epw_climate_analyzer.engine_ui import PRODUCT_KEY
        app = self.app()
        with patch("epw_climate_analyzer.engine_ui.run_historical_product", wraps=application.run_historical_product) as run_h:
            app.button(key="FormSubmitter:ige_historical_request-Generate historical year").click().run()
            self.clean(app); self.assertEqual(run_h.call_count, 1)
            historical = app.session_state[PRODUCT_KEY]
            self.assertEqual(historical.report["calendar_mode"], "historical")
            self.assertEqual(sha256(historical.files["climate.epw"]).hexdigest(), application.HISTORICAL_EPW_SHA)
            self.assertEqual(len(app.download_button), 4)
            for button in app.download_button: self.assertTrue(button.proto.url)
            app.run(); self.clean(app); self.assertEqual(run_h.call_count, 1)
            app.button(key="ige_explore").click().run(); self.clean(app)
            self.assertEqual(app.session_state["active_canonical_climate"].temporal.calendar_mode, "historical")
            # Exercise all admitted views through the real installed app router.
            for page in ("Temperature", "Humidity and Psychrometrics", "Solar and Radiation", "Wind and Ventilation",
                    "Sky and Daylight", "Precipitation and Snow", "Time Series and Overlay", "Data Quality"):
                app.sidebar.radio(key="climate_analyzer_navigation").set_value(page).run(); self.clean(app)
                if page != "Data Quality": self.assertEqual(len(app.get("plotly_chart")), 1)
            self.assertEqual(run_h.call_count, 1)
        app.sidebar.radio(key="climate_analyzer_navigation").set_value("Climate File Source").run(); self.clean(app)
        app.radio(key="ige_generation_mode").set_value("Future climate").run()
        with patch("epw_climate_analyzer.engine_ui.run_future_pilot_product", wraps=application.run_future_pilot_product) as run_f:
            app.button(key="FormSubmitter:ige_future_request-Generate future year").click().run(); self.clean(app)
            future = app.session_state[PRODUCT_KEY]
            self.assertEqual(future.report["calendar_mode"], "climatology")
            self.assertEqual(sha256(future.files["climate.epw"]).hexdigest(), FUTURE_EPW_SHA)
            self.assertEqual(len(app.download_button), 4)
            app.button(key="ige_explore").click().run(); self.clean(app)
            self.assertEqual(app.session_state["active_canonical_climate"].temporal.calendar_mode, "climatology")
            app.sidebar.radio(key="climate_analyzer_navigation").set_value("Humidity and Psychrometrics").run(); self.clean(app)
            self.assertEqual(len(app.get("plotly_chart")), 1)
            self.assertEqual(run_f.call_count, 1)
            self.assertTrue(any("not a forecast" in e.value for e in app.info))

    def test_request_form_is_not_sent_before_submit_and_failure_keeps_last_complete_year(self):
        from epw_climate_analyzer.engine_ui import PRODUCT_KEY
        app = self.app()
        app.button(key="FormSubmitter:ige_historical_request-Generate historical year").click().run(); self.clean(app)
        previous = app.session_state[PRODUCT_KEY]
        with patch("epw_climate_analyzer.engine_ui.run_historical_product", side_effect=TimeoutError("provider timeout")) as run:
            app.selectbox(key="ige_historical_source").set_value("Coordinates — request provider data").run()
            app.number_input(key="ige_latitude").set_value(48.2082)
            app.number_input(key="ige_year").set_value(2024)
            app.run(); self.clean(app); run.assert_not_called()
            app.button(key="FormSubmitter:ige_historical_request-Generate historical year").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("did not produce" in e.value for e in app.error))
            self.assertEqual(run.call_count, 1)
            request = run.call_args.args[0]
            self.assertEqual(request.latitude, 48.2082); self.assertEqual(request.year, 2024)
            self.assertFalse(run.call_args.kwargs["use_saved_pilot"])
            self.assertIs(app.session_state[PRODUCT_KEY], previous)
            self.assertTrue(any(e.value == "Previous completed result" for e in app.subheader))


if __name__ == "__main__":
    unittest.main()
