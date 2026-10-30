"""Public workspace regressions: geometry, immutable sources and chart semantics."""
from __future__ import annotations

import csv
from hashlib import sha256
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from epw_climate_analyzer import location_picker as picker
from epw_climate_analyzer.climate_maps import donor_markers, epw_markers, grid_markers
from epw_climate_analyzer.engine.f1_base import admit_base, MK, SURFACE, PROVIDER_ROUNDING, water_es
from epw_climate_analyzer.engine.f1_sources import SignalRequest, SCENARIOS, catalog_url
from epw_climate_analyzer.engine.thermodynamics import e_from_q
from epw_climate_analyzer.engine_display import prepare_engine_display_frame
from epw_climate_analyzer.engine_application import run_historical_product, pilot_historical_request
from epw_climate_analyzer.humidity_display import current_water_curve
from test_ige_f1_selected_future import synthetic_base

APP = Path(__file__).resolve().parents[1]/"app.py"


class TerrainTests(unittest.TestCase):
    def test_one_lookup_per_point_manual_override_survives_and_new_point_refreshes(self):
        state = {}; picker.initialize_point(state)
        def response(lat, lon): return {"elevation_m": 370.+lat, "source": "TEST DEM", "latitude": lat, "longitude": lon}
        with patch("epw_climate_analyzer.site_elevation.lookup_elevation", side_effect=response) as lookup:
            picker.resolve_point_elevation(state); self.assertEqual(state[picker.HEIGHT], 417.5)
            state[picker.HEIGHT] = 380.; picker.elevation_edited(state)
            picker.resolve_point_elevation(state); self.assertEqual(state[picker.HEIGHT], 380.)
            self.assertEqual(lookup.call_count, 1)
            state[picker.LATITUDE] = 48.; picker.coordinates_edited(state)
            picker.resolve_point_elevation(state); self.assertEqual(state[picker.HEIGHT], 418.)
            self.assertEqual(lookup.call_count, 2)

    def test_failed_lookup_is_not_zero_filled_or_repeated_on_every_rerun(self):
        state = {}; picker.initialize_point(state)
        with patch("epw_climate_analyzer.site_elevation.lookup_elevation", side_effect=TimeoutError("OFFLINE")) as lookup:
            picker.resolve_point_elevation(state); picker.resolve_point_elevation(state)
            self.assertEqual(lookup.call_count, 1); self.assertIsNone(state[picker.HEIGHT])
            picker.reset_elevation(state); picker.resolve_point_elevation(state)
            self.assertEqual(lookup.call_count, 2)

    def test_map_sources_keep_real_coordinates_and_selection_status(self):
        rows = [{"latitude": 47., "longitude": 15., "station_id": "AT:1", "selected": True,
                 "temperature_elevation_m": 380., "distance_km": 2.}]
        marker = donor_markers(rows)[0]
        self.assertEqual((marker["latitude"], marker["longitude"]), (47., 15.))
        self.assertTrue(marker["selected"])
        preview = epw_markers([("control.epw", synthetic_base().epw)])
        self.assertEqual(len(preview), 1); self.assertFalse(preview[0]["selected"])
        self.assertEqual(grid_markers({}), [])


class RoundingTests(unittest.TestCase):
    def body(self, delta=.1):
        base = synthetic_base(curve=MK, pressure_contract=SURFACE)
        rows = list(csv.reader(io.StringIO(base.epw.decode())))
        rows[8][6], rows[8][7], rows[8][8] = "10.0", str(10.+delta), "100"
        stream = io.StringIO(newline=""); csv.writer(stream, lineterminator="\n").writerows(rows)
        return stream.getvalue().encode()

    def admit(self, body, **kwargs):
        return admit_base(body, calendar_kind="ACTUAL_YEAR", pressure_contract=SURFACE,
                          water_curve=MK, vapour_authority="DEW_POINT", **kwargs)

    def test_strict_unknown_source_still_blocks_but_bounded_known_rounding_is_logged(self):
        body = self.body(); original = sha256(body).hexdigest()
        with self.assertRaisesRegex(ValueError, "VAPOUR_ABOVE_SATURATION"):
            self.admit(body)
        base = self.admit(body, source_kind="IGE_B0_BACKGROUND", rounding_policy=PROVIDER_ROUNDING)
        q, p = base.vapour_state(); e = e_from_q(q, p)
        self.assertAlmostEqual(e[0], float(water_es(np.array([10.]), MK)[0]), places=8)
        self.assertEqual(base.data.iloc[0].dew_point_temperature_c, 10.1)
        self.assertEqual(base.sha256, original)
        log = base.identity["source_rounding_admission"]
        self.assertEqual(log["hours"], 1)
        self.assertLess(log["adjustments"][0]["delta_vapour_Pa"], 0)
        self.assertFalse(log["original_EPW_modified"])

    def test_policy_cannot_repair_unknown_source_large_or_non_quantised_excess(self):
        with self.assertRaises(ValueError): self.admit(self.body(), rounding_policy=PROVIDER_ROUNDING)
        with self.assertRaises(ValueError): self.admit(self.body(.2), source_kind="IGE_B0_BACKGROUND", rounding_policy=PROVIDER_ROUNDING)
        with self.assertRaises(ValueError): self.admit(self.body(.05), source_kind="IGE_B0_BACKGROUND", rounding_policy=PROVIDER_ROUNDING)


class DisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.historical = run_historical_product(pilot_historical_request())

    def test_display_preserves_all_source_values_and_clock(self):
        original = self.historical.dataset.data.copy(deep=True)
        display = prepare_engine_display_frame(self.historical.dataset, include_solar=True)
        pd.testing.assert_index_equal(display.index, original.index)
        for column in original:
            np.testing.assert_array_equal(display[column], original[column])
        self.assertEqual(display.attrs["ige_display_water_curve"], "PROVIDER_MAGNUS_WATER")
        self.assertTrue(display.wet_bulb_temperature_c.isna().all())
        self.assertTrue(display.snow_depth_cm.isna().all())
        self.assertEqual(sha256(self.historical.files["climate.epw"]).hexdigest(),
                         "acf8e7d82be69de5fa19f76c599143559d477aa01cdb7c56414fc23c93796635")

    def test_existing_psychrometric_representations_use_water_and_restore_default(self):
        from epw_climate_analyzer.charts import psychrometric_chart
        from epw_climate_analyzer.psychrometric_distribution import psychrometric_density_field
        frame = prepare_engine_display_frame(self.historical.dataset)
        for mode in ("Points", "Distribution grid", "Climate contour"):
            fig = psychrometric_chart(frame, data_mode=mode, show_comfort_zone=False,
                                      t_range=(-20., 40.), metric_layers=["Relative humidity"])
            self.assertGreater(len(fig.data), 0)
            self.assertIsNone(current_water_curve())
        water = frame.iloc[:4].copy()
        water["dry_bulb_temperature_c"] = -10.
        e = float(water_es(np.array([-10.]), MK)[0])
        water["humidity_ratio_g_kg"] = 1000*(287.05/461.5)*e/(101325-e)
        water.attrs["ige_display_water_curve"] = MK
        field = psychrometric_density_field(water, pressure_pa=101325.)
        self.assertGreater(field.total_hours, 0)
        self.assertIsNone(current_water_curve())

    def test_actual_app_opens_established_panels_and_exposes_four_pathways(self):
        from streamlit.testing.v1 import AppTest
        with patch("epw_climate_analyzer.site_elevation.lookup_elevation", side_effect=ValueError("OFFLINE")), \
                patch("epw_climate_analyzer.location_picker.render_location_map"), \
                patch("epw_climate_analyzer.engine_ui.run_historical_product", return_value=self.historical):
            app = AppTest.from_file(APP, default_timeout=60).run()
            app.radio(key="climate_source_mode").set_value("Generate climate").run()
            self.assertNotIn(picker.HEIGHT_REFERENCE, [x.key for x in app.text_input])
            app.button(key="ige_build_background").click().run()
            app.button(key="ige_explore").click().run()
            self.assertEqual([e.message for e in app.exception], [])
            self.assertTrue(any("EPW Climate Analyzer" in h.value for h in app.header))
            app.sidebar.radio(key="climate_analyzer_navigation").set_value("Temperature").run()
            self.assertTrue(any(s.label == "Analysis type" for s in app.selectbox))
            app.sidebar.radio(key="climate_analyzer_navigation").set_value("Humidity and Psychrometrics").run()
            app.selectbox(key="humidity_analysis_type").set_value("Psychrometric chart").run()
            self.assertTrue(any(r.label == "Representation" for r in app.radio))
            self.assertEqual([e.message for e in app.exception], [])

    def test_four_scenarios_generate_distinct_source_requests_without_fallback(self):
        urls = []
        for scenario in SCENARIOS:
            req = SignalRequest(47., 15., scenario=scenario)
            self.assertIn((scenario, 2040, "tas"), req.jobs)
            urls.append(catalog_url(req, scenario, "tas"))
        self.assertEqual(len(set(urls)), 4)
        with self.assertRaises(ValueError): SignalRequest(47., 15., scenario="ssp119")


if __name__ == "__main__": unittest.main()
