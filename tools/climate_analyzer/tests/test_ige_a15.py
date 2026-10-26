"""A1.5 original snapshot, water-phase analysis and real-app UI acceptance."""
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

from epw_climate_analyzer import engine_station_product as service
from epw_climate_analyzer.engine_analysis import (prepare_engine_analysis_frame, monthly_engine_summary,
    T,TD,RH,P,Q,STATION_UI_CONTRACT)
from epw_climate_analyzer.engine.thermodynamics import saturation_nasa_phase_pa,saturation_water_pa,e_from_q
from epw_climate_analyzer.engine_psychrometrics import station_psychrometric_figure

APP=Path(__file__).resolve().parents[1]/"app.py"


class SavedProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("socket.socket.connect",side_effect=RuntimeError("A15_NETWORK_FORBIDDEN")):
            cls.products={k:service.load_station_year_product(k) for k in service.CATALOG}

    def test_both_original_EPWs_and_all_original_snapshot_members_are_unchanged(self):
        with zipfile.ZipFile(service.RESEARCH/service.BUNDLE_NAME) as z:
            for key,product in self.products.items():
                prefix=key.replace(":","_")+"_2025/"
                self.assertEqual(sha256(product.files["climate.epw"]).hexdigest(),service.CATALOG[key]["EPW_sha256"])
                for name in service.SNAPSHOT_FILES:
                    self.assertEqual(product.files["a14_snapshot/"+name],z.read(prefix+name))
                self.assertEqual(gzip.decompress(product.files["hourly.csv.gz"]),z.read(prefix+"hourly_states.csv"))

    def test_actual_calendar_sensor_location_and_qualified_axes_are_separate(self):
        for key,p in self.products.items():
            self.assertEqual(p.dataset.temporal.calendar_mode,"historical")
            self.assertEqual(p.dataset.temporal.source_years,(2025,))
            self.assertEqual(len(p.dataset.data),8760)
            self.assertEqual(str(p.dataset.start),"2025-01-01 00:00:00+01:00")
            self.assertEqual(str(p.dataset.end),"2025-12-31 23:00:00+01:00")
            self.assertEqual(p.dataset.location.station_id,key.split(":")[1])
            self.assertEqual(set(p.report["quality"]),{"execution_correctness","physical_admissibility","independent_accuracy","operational_and_application_scope"})
            self.assertNotEqual(p.dataset.location.elevation_m,p.report["source_geometry"]["elevation_m_provider_response_proxy"])
            self.assertTrue(p.report["UI_connected"])
            self.assertFalse(p.report["production_ready"])
            self.assertFalse(p.report["independent_station_accuracy_qualified"])
            self.assertFalse(p.report["local_pressure_accuracy_qualified"])
            self.assertFalse(p.report["instantaneous_T_accuracy_qualified"])

    def test_loading_runs_no_generator_provider_resaturation_or_EPWS_writer(self):
        with patch("epw_climate_analyzer.engine.historical.fetch_original",side_effect=AssertionError("NO_PROVIDER")), \
                patch("epw_climate_analyzer.engine.station_year.project_humidity",side_effect=AssertionError("NO_NEW_PROJECTION")), \
                patch("epw_climate_analyzer.engine.station_year.serialize_station_epw",side_effect=AssertionError("NO_REEXPORT")), \
                patch("epw_climate_analyzer.engine_application.run_historical",side_effect=AssertionError("NO_NEW_YEAR")):
            p=service.load_station_year_product("CH:ALT")
        self.assertEqual(p.report["weather_provider_requests_this_run"],0)
        self.assertFalse(p.report["EPW_regenerated"])
        self.assertFalse(p.report["new_target_observations_opened"])

    def test_unknown_station_and_corrupt_or_missing_packet_fail_without_fallback(self):
        for key in ("CH:NEW","AT:5000","CH:TIT"):
            with self.assertRaisesRegex(ValueError,"ONLY_SAVED"):service.load_station_year_product(key)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"corrupt.zip";p.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError,"BUNDLE_HASH"):service.load_station_year_product("CH:BAS",bundle_path=p)
            with self.assertRaises(FileNotFoundError):service.load_station_year_product("CH:BAS",bundle_path=Path(folder)/"missing")

    def test_snapshot_member_census_rejects_unregistered_body_even_if_hash_gate_is_stubbed(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,"w") as z:z.writestr("unexpected",b"body")
        raw=stream.getvalue()
        with patch.object(service,"STATION_BUNDLE_SHA",sha256(raw).hexdigest()):
            with self.assertRaisesRegex(ValueError,"MEMBER_CENSUS"):service._snapshot(raw,"CH:BAS")

    def test_ZIP_contains_complete_snapshot_provenance_and_separate_analysis(self):
        for p in self.products.values():
            with zipfile.ZipFile(io.BytesIO(p.archive)) as z:
                self.assertEqual(set(z.namelist()),set(p.files))
                for name,body in p.files.items():self.assertEqual(z.read(name),body)
            self.assertEqual(len(p.report["field_provenance"]),len(p.dataset.data.columns))
            self.assertEqual(len(p.report["source_references"]),3)
            self.assertFalse(p.report["raw_provider_bodies_in_UI_download"])
            for r in p.report["source_references"].values():
                self.assertIn(service.PARENT,r["url"])
                self.assertEqual(len(r["sha256"]),64)
            self.assertIn("UI_NOT_CONNECTED",p.report["source_snapshot_quality"]["operational_and_application_scope"])
            self.assertIn("RESEARCH_UI",p.report["quality"]["operational_and_application_scope"])


class StationAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.product=service.load_station_year_product("CH:BAS")

    def test_analysis_preserves_all_original_values_and_q_is_the_authority(self):
        original=self.product.dataset.data.copy(deep=True)
        a=prepare_engine_analysis_frame(self.product.dataset)
        pd.testing.assert_frame_equal(original,self.product.dataset.data)
        for key in original:np.testing.assert_array_equal(a[key],original[key])
        np.testing.assert_array_equal(a["analysis_specific_humidity_kg_kg"],original[Q])
        np.testing.assert_array_equal(a["specific_humidity_g_kg_moist_air"],1000*original[Q])
        np.testing.assert_allclose(a["humidity_ratio_g_kg"],1000*original[Q]/(1-original[Q]),rtol=1e-14)
        np.testing.assert_allclose(a["vapor_pressure_pa"],e_from_q(original[Q],original[P]),rtol=1e-14)

    def test_liquid_water_below_zero_does_not_become_ice_or_get_clipped(self):
        a=prepare_engine_analysis_frame(self.product.dataset)
        ice=100*a["vapor_pressure_pa"].to_numpy()/saturation_nasa_phase_pa(a[T])
        self.assertGreater(int(((a[T]<0)&(ice>100)).sum()),0)
        self.assertLessEqual(a[RH].max(),100)
        self.assertFalse(a.attrs["ige_ui_analysis"]["ice_supersaturation_clipped"])
        self.assertFalse(a.attrs["ige_ui_analysis"]["source_T_Td_RH_p_and_q_modified"])

    def test_missing_q_phase_admission_surface_p_or_modified_state_fails(self):
        for case in ("q","phase","admission","surface","T","RH","p","proxy"):
            f=self.product.dataset.data.copy(deep=True)
            if case=="q":f=f.drop(columns=Q)
            elif case=="phase":f.attrs["ige_RH_phase"]="unknown"
            elif case=="admission":f.attrs.pop("ige_station_ui_admission")
            elif case=="surface":f=f.drop(columns="surface_pressure_proxy_pa")
            else:
                key={"T":T,"RH":RH,"p":P,"proxy":"surface_pressure_proxy_pa"}[case]
                f.iloc[0,f.columns.get_loc(key)]+=1
            with self.subTest(case=case),self.assertRaises(ValueError):
                prepare_engine_analysis_frame(replace(self.product.dataset,data=f))

    def test_month_filters_keep_original_clock_and_conserved_sums(self):
        a=prepare_engine_analysis_frame(self.product.dataset)
        m=monthly_engine_summary(a)
        self.assertEqual(m.Hours.sum(),8760)
        self.assertAlmostEqual(m["GHI [kWh/m²]"].sum(),a.global_horizontal_radiation_wh_m2.sum()/1000,places=10)
        self.assertAlmostEqual(m["Total precipitation [mm]"].sum(),a.total_precipitation_depth_mm.sum(),places=10)
        self.assertEqual(len(a[a.index.month==2]),672)

    def test_shifted_year_or_DST_clock_is_not_relabelled_as_the_saved_year(self):
        for case in ("shift","DST","partial"):
            f=self.product.dataset.data.copy(deep=True)
            if case=="shift":f.index=f.index+pd.Timedelta(hours=1)
            elif case=="DST":f.index=f.index.tz_convert("Europe/Zurich")
            else:f=f.iloc[1:]
            with self.subTest(case=case),self.assertRaisesRegex(ValueError,"CALENDAR_CHANGED"):
                prepare_engine_analysis_frame(replace(self.product.dataset,data=f))


class WaterChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=prepare_engine_analysis_frame(service.load_station_year_product("CH:BAS").dataset)

    def test_chart_points_are_saved_T_and_w_and_do_not_change_with_guide_pressure(self):
        original=self.data.copy(deep=True)
        for p in (90000,100000):
            fig=station_psychrometric_figure(self.data,p)
            self.assertEqual(len(fig.data),6)
            np.testing.assert_array_equal(fig.data[-1].x,self.data[T])
            np.testing.assert_array_equal(fig.data[-1].y,1000*self.data[Q]/(1-self.data[Q]))
            self.assertEqual(fig.layout.meta["point_count"],8760)
            self.assertFalse(fig.layout.meta["points_recomputed_at_reference_pressure"])
            self.assertIsInstance(fig.data[-1].customdata[0][0],float)
        pd.testing.assert_frame_equal(original,self.data)

    def test_guides_use_water_saturation_and_reference_pressure_not_ice(self):
        f=station_psychrometric_figure(self.data,95000)
        t=np.asarray(f.data[4].x);w=np.asarray(f.data[4].y)/1000
        eps=287.05/461.5;e=w*95000/(eps+w)
        np.testing.assert_allclose(e,saturation_water_pa(t),rtol=2e-14)
        self.assertGreater(np.max(np.abs(e[t<0]-saturation_nasa_phase_pa(t[t<0]))),1)

    def test_filtered_chart_preserves_count_and_empty_or_invalid_reference_fails(self):
        january=self.data[self.data.index.month==1]
        self.assertEqual(len(station_psychrometric_figure(january,95000).data[-1].x),744)
        for frame,p in ((self.data.iloc[:0],95000),(self.data,float("nan")),(self.data,1000)):
            with self.assertRaises(ValueError):station_psychrometric_figure(frame,p)


class ActualStationRouteTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect","socket.socket.connect_ex"):
            guard=patch(target,side_effect=RuntimeError("A15_APPTEST_NO_NETWORK"));guard.start();self.addCleanup(guard.stop)

    def clean(self,app):
        self.assertEqual([x.message for x in app.exception],[])
        self.assertEqual([x.value for x in app.error],[])

    def app(self):
        from streamlit.testing.v1 import AppTest
        from epw_climate_analyzer.engine_ui import STATION_SOURCE
        app=AppTest.from_file(APP,default_timeout=60).run();self.clean(app)
        app.radio(key="climate_source_mode").set_value("Generate climate").run();self.clean(app)
        app.selectbox(key="ige_historical_source").set_value(STATION_SOURCE).run();self.clean(app)
        return app

    def load(self,app,label):
        app.selectbox(key="ige_station_year_choice").set_value(label)
        app.button(key="FormSubmitter:ige_station_year_request-Load station year").click().run();self.clean(app)
        return app.session_state["ige_engine_completed_product"]

    def test_real_app_both_stations_all_views_psychrometrics_downloads_and_reruns(self):
        from epw_climate_analyzer.engine_ui import PAGES
        app=self.app()
        with patch("epw_climate_analyzer.engine_ui.load_station_year_product",wraps=service.load_station_year_product) as run:
            for key in ("CH:BAS","CH:ALT"):
                if key=="CH:ALT":
                    from epw_climate_analyzer.engine_ui import STATION_SOURCE
                    app.sidebar.radio(key="climate_analyzer_navigation").set_value("Climate File Source").run();self.clean(app)
                    app.selectbox(key="ige_historical_source").set_value(STATION_SOURCE).run();self.clean(app)
                product=self.load(app,service.CATALOG[key]["label"])
                self.assertEqual(product.report["station_key"],key)
                self.assertEqual(len(app.download_button),4)
                self.assertTrue(all(b.proto.url for b in app.download_button))
                self.assertEqual(sha256(product.files["climate.epw"]).hexdigest(),service.CATALOG[key]["EPW_sha256"])
                self.assertTrue(any("actual station height" in x.value for x in app.warning))
                app.run();self.clean(app)
                self.assertEqual(run.call_count,1 if key=="CH:BAS" else 2)
                app.button(key="ige_explore").click().run();self.clean(app)
                self.assertEqual(app.session_state["active_canonical_climate"].location.station_id,key.split(":")[1])
                for page in PAGES:
                    if page in ("Climate File Source","Overview"):continue
                    app.sidebar.radio(key="climate_analyzer_navigation").set_value(page).run();self.clean(app)
                    if page!="Data Quality":self.assertEqual(len(app.get("plotly_chart")),1)
                app.sidebar.radio(key="climate_analyzer_navigation").set_value("Humidity and Psychrometrics").run();self.clean(app)
                app.radio(key="ige_station_humidity_view").set_value("Water-phase psychrometric chart").run();self.clean(app)
                self.assertEqual(len(app.get("plotly_chart")),1)
                app.multiselect(key="ige_filter_months").set_value([1]).run();self.clean(app)
                app.number_input(key="ige_station_guide_pressure").set_value(100000.).run();self.clean(app)
                self.assertEqual(product.files["climate.epw"],app.session_state["ige_engine_completed_product"].files["climate.epw"])
                self.assertEqual(run.call_count,1 if key=="CH:BAS" else 2)

    def test_station_choice_is_not_loaded_before_submit_and_failure_keeps_complete_result(self):
        app=self.app();previous=self.load(app,service.CATALOG["CH:BAS"]["label"])
        with patch("epw_climate_analyzer.engine_ui.load_station_year_product",side_effect=ValueError("saved packet SHA mismatch")) as run:
            app.selectbox(key="ige_station_year_choice").set_value(service.CATALOG["CH:ALT"]["label"]).run()
            self.clean(app);run.assert_not_called()
            app.button(key="FormSubmitter:ige_station_year_request-Load station year").click().run()
            self.assertEqual(len(app.exception),0)
            self.assertTrue(any("did not produce" in e.value for e in app.error))
            self.assertEqual(run.call_count,1)
            self.assertIs(app.session_state["ige_engine_completed_product"],previous)
            self.assertEqual(len(app.download_button),4)

    def test_ch_mode_returns_to_old_Graz_and_future_routes_without_carrying_station_phase(self):
        from epw_climate_analyzer.engine_application import HISTORICAL_EPW_SHA
        app=self.app();self.load(app,service.CATALOG["CH:BAS"]["label"])
        app.selectbox(key="ige_historical_source").set_value("Saved Graz 2023 pilot").run();self.clean(app)
        app.button(key="FormSubmitter:ige_historical_request-Generate historical year").click().run();self.clean(app)
        p=app.session_state["ige_engine_completed_product"]
        self.assertEqual(sha256(p.files["climate.epw"]).hexdigest(),HISTORICAL_EPW_SHA)
        self.assertNotIn("ige_station_ui_admission",p.dataset.data.attrs)
        app.radio(key="ige_generation_mode").set_value("Future climate").run();self.clean(app)
        app.button(key="FormSubmitter:ige_future_request-Generate future year").click().run();self.clean(app)
        p=app.session_state["ige_engine_completed_product"]
        self.assertEqual(p.dataset.temporal.calendar_mode,"climatology")
        self.assertNotIn("ige_station_ui_admission",p.dataset.data.attrs)
        self.assertEqual(sha256(p.files["climate.epw"]).hexdigest(),"fc00e09811498c368965785ee8873bc4ca1cd01761eaebb19c759faebd0e3c28")


if __name__=="__main__":unittest.main()
