"""F1 gates, mathematical invariants, original-source replay and public routing.

Synthetic controls establish implementation properties, not station accuracy.
"""
from dataclasses import replace
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from epw_climate_analyzer.climate_model import ClimateLocation
from epw_climate_analyzer.engine.contracts import ClimateResult, HistoricalRequest, FieldDefinition, QualityStatus
from epw_climate_analyzer.engine.epw import EPW_FIELDS, serialize_epw
from epw_climate_analyzer.engine.future import T, TD, RH, P, Q, GHI, LW, WS, PR
from epw_climate_analyzer.engine.f1_base import (admit_base, climatology, epw_reference,
    water_es, water_dew, SURFACE, COLLOCATED, MK, BUCK)
from epw_climate_analyzer.engine.f1 import morph_selected, check_state, saturation_capacity
from epw_climate_analyzer.engine.f1_sources import SignalRequest, decode_point, admit_nex_packet
from epw_climate_analyzer.engine.thermodynamics import e_from_q
from epw_climate_analyzer.engine_application import run_historical_product, pilot_historical_request
from epw_climate_analyzer.future_selected import base_from_engine, background_reference, run_selected_future
from epw_climate_analyzer.engine_analysis import prepare_engine_analysis_frame, monthly_engine_summary

ROOT = Path(__file__).resolve().parents[3]


def synthetic_base(year=2023, curve=BUCK, pressure_contract=COLLOCATED, humidity=65., kind="ACTUAL_YEAR"):
    r = HistoricalRequest(47.0707, 15.4395, year, 60, "F1 SYNTHETIC CONTROL")
    h = np.arange(len(r.utc_starts)); t = 9+9*np.sin(2*np.pi*h/len(h))+3*np.sin(2*np.pi*h/24)
    sun = np.maximum(0, np.sin(2*np.pi*(h%24-6)/24))
    values = {T: t, TD: water_dew(humidity/100*water_es(t, curve), curve), RH: np.full(len(h), humidity),
        P: np.full(len(h), 98000.), GHI: 350*sun, LW: np.full(len(h), 300.),
        "direct_normal_radiation_wh_m2": 300*sun, "diffuse_horizontal_radiation_wh_m2": 200*sun,
        "wind_direction_deg": h%360, WS: np.full(len(h), 2.), "total_sky_cover_tenths": np.full(len(h), 4.),
        "liquid_precipitation_depth_mm": np.where(h%120 == 0, 1., 0.)}
    f = pd.DataFrame(values, index=r.utc_starts)
    defs = {k: FieldDefinition(u, o, "synthetic", "Synthetic collocated", "Synthetic water control") for k,(_,u,o) in EPW_FIELDS.items()}
    result = ClimateResult(r, f, ClimateLocation(r.latitude, r.longitude, 400.), defs, ({"id":"synthetic"},), (), (),
        QualityStatus("SYNTHETIC", "SYNTHETIC", "UNQUALIFIED", "TEST_ONLY"), {})
    epw,_ = serialize_epw(result)
    return admit_base(epw, calendar_kind=kind, pressure_contract=pressure_contract, water_curve=curve)


def signals(delta=2., humidity_ratio=1.03):
    return {m: {"midrange_delta_K": delta, "dtr_ratio": 1.05, "huss_ratio": humidity_ratio,
        "historical_midrange_sorted_c": [-3., 0., 3.], "future_midrange_sorted_c": [-3.+delta, delta, 3.+delta],
        "rsds_ratio": 1.02, "rlds_ratio": 1.01, "sfcWind_ratio": .97, "pr_ratio": 1.1,
        "NASA_hurs_delta_pp_DIAGNOSTIC_NOT_ENFORCED": 37.} for m in range(1,13)}


def calculate(base, sig=None, reference=None, **kwargs):
    r = SignalRequest(*base.identity["signal_site"])
    return morph_selected(base, reference or climatology([base]), sig or signals(), r,
        reference_evidence={"reference_window": [2002,2014], "kind":"SYNTHETIC_CONTROL"},
        nex_evidence={"source_packet_sha256": "0"*64, "grid":[47.125,15.375], "kind":"SYNTHETIC_CONTROL"},
        allow_liquid_precipitation_proxy=True, **kwargs)


class F1MathTests(unittest.TestCase):
    def test_monthly_targets_and_common_state_for_both_curves_and_leap_calendars(self):
        for year, curve in ((2023,BUCK),(2024,MK)):
            with self.subTest(year=year, curve=curve):
                b = synthetic_base(year, curve)
                before = b.data.copy(deep=True); result, epw, ledger, screen = calculate(b)
                self.assertEqual(len(result.data), 8784 if year == 2024 else 8760)
                self.assertEqual(len(ledger), len(result.data))
                self.assertEqual(screen["F1_monthly_EPW_readback"], "PASS")
                self.assertEqual(screen["hard_failure_count"], 0)
                check_state(result.data, curve)
                self.assertLessEqual(float(result.data[RH].max()), 100.)
                pd.testing.assert_frame_equal(b.data, before)
                for col in ("wind_direction_deg", "total_sky_cover_tenths"):
                    np.testing.assert_array_equal(result.data[col], b.data[col])
                for row in result.diagnostics["temperature_months"]:
                    self.assertAlmostEqual(row["target_midrange_c"], row["actual_midrange_c"], places=10)
                    self.assertAlmostEqual(row["target_DTR_K"], row["actual_DTR_K"], places=10)
                self.assertIn(b"REPRESENTATIVE FUTURE", epw[:1700])
                self.assertFalse(result.diagnostics["NASA_hurs_signal_enforced"])

    def test_collocated_pressure_is_not_adapted_twice(self):
        b = synthetic_base()
        result, _, ledger, _ = calculate(b)
        np.testing.assert_array_equal(result.data[P], b.data[P])
        np.testing.assert_array_equal(ledger.source_pressure_Pa, ledger.future_state_pressure_Pa)

    def test_surface_pressure_has_one_explicit_adapter_and_same_source_proxy(self):
        from epw_climate_analyzer.engine.thermodynamics import pressure_at_2m
        b = synthetic_base(pressure_contract=SURFACE)
        result,_,ledger,_ = calculate(b)
        expected = pressure_at_2m(result.data[T], result.data[Q], b.data[P])
        np.testing.assert_array_equal(result.data[P], expected)
        self.assertTrue((ledger.future_state_pressure_Pa < ledger.source_pressure_Pa).all())

    def test_radiation_components_share_factor_and_total_is_not_invented(self):
        b = synthetic_base(); out,_,_,_ = calculate(b)
        for m in range(1,13):
            ix = b.request.local_starts.month == m
            factor = signals()[m]["rsds_ratio"]
            for k in (GHI,"direct_normal_radiation_wh_m2","diffuse_horizontal_radiation_wh_m2"):
                np.testing.assert_allclose(out.data.loc[ix,k], b.data.loc[ix,k]*factor, rtol=1e-14)
        self.assertNotIn(PR, out.data)
        self.assertFalse(out.diagnostics["total_precipitation_available"])

    def test_infeasible_q_target_fails_without_lowering_target(self):
        b = synthetic_base()
        with self.assertRaisesRegex(ValueError, "Q_INFEASIBLE"):
            calculate(b, signals(humidity_ratio=100.))

    def test_saturation_bound_feasible_at_float_precision_for_both_pressure_contracts(self):
        from epw_climate_analyzer.engine.f1 import pressure
        t = np.linspace(-40.,40.,8760); p = np.full(len(t), 98000.)
        for curve in (MK,BUCK):
            es = water_es(t, curve)
            for c in (SURFACE,COLLOCATED):
                upper = saturation_capacity(t,p,c,es)
                self.assertTrue(np.all(e_from_q(upper,pressure(t,upper,p,c)) <= es))

    def test_zero_pattern_event_amount_is_blocked_instead_of_creating_events(self):
        b = synthetic_base(); f = b.data.copy(); f["liquid_precipitation_depth_mm"] = 0.
        with self.assertRaisesRegex(ValueError, "ZERO_PATTERN_AMOUNT"):
            calculate(replace(b,data=f), reference=climatology([b]))

    def test_reference_rebase_removes_pattern_climate_anomaly(self):
        b = synthetic_base(); ref = climatology([b]); original = ref[1]["midrange_c"]
        for m in ref: ref[m]["midrange_c"] -= 3.
        out,_,_,_ = calculate(b, reference=ref)
        row = out.diagnostics["temperature_months"][0]
        self.assertAlmostEqual(row["actual_midrange_c"], original-3+2, places=10)
        self.assertAlmostEqual(row["pattern_to_reference_rebase_K"], -3., places=10)


class F1AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.b = synthetic_base()

    def modified(self, action):
        rows = list(csv.reader(io.StringIO(self.b.epw.decode()))); action(rows)
        out = io.StringIO(newline=""); csv.writer(out,lineterminator="\n").writerows(rows)
        return out.getvalue().encode()

    def admit(self, raw, kind="ACTUAL_YEAR"):
        return admit_base(raw,calendar_kind=kind,pressure_contract=COLLOCATED,water_curve=BUCK)

    def test_missing_and_duplicated_hours_never_become_a_full_year(self):
        for action in (lambda rows: rows.pop(),lambda rows: rows.__setitem__(9,rows[8])):
            with self.assertRaises(ValueError): self.admit(self.modified(action))

    def test_missing_required_source_value_is_not_zero_filled(self):
        for col, missing in ((6,"99.9"),(9,"999999"),(13,"9999"),(33,"999")):
            with self.subTest(col=col), self.assertRaisesRegex(ValueError,"MISSING_OR_OUT_OF_RANGE"):
                self.admit(self.modified(lambda rows: rows[8].__setitem__(col,missing)))

    def test_extra_total_precipitation_requires_the_same_clock_and_core_values(self):
        for changed in ("clock", "core"):
            f = self.b.data.copy(); f[PR] = f["liquid_precipitation_depth_mm"]
            if changed == "clock": f.index = f.index+pd.Timedelta(hours=1)
            else: f.iloc[0,f.columns.get_loc(T)] += 1.
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError,"SIDECAR"):
                admit_base(self.b.epw,calendar_kind="ACTUAL_YEAR",pressure_contract=COLLOCATED,water_curve=BUCK,extras=f)

    def test_tmy_allowed_as_declared_representative_but_not_real_year(self):
        data = self.modified(lambda rows: rows[0].__setitem__(1,"Meteonorm TMY control"))
        with self.assertRaisesRegex(ValueError,"TMY_IS_NOT_AN_ACTUAL"): self.admit(data)
        base = self.admit(data,"REPRESENTATIVE_YEAR")
        self.assertEqual(base.request.year,2001)
        self.assertEqual(base.source_years,(2023,))

    def test_future_cannot_become_historical_base(self):
        _,epw,_,_ = calculate(self.b)
        with self.assertRaisesRegex(ValueError,"FUTURE_OUTPUT"): self.admit(epw,"REPRESENTATIVE_YEAR")

    def test_unknown_reference_period_not_inferred_from_actual_pattern(self):
        ref = self.admit(self.b.epw,"REPRESENTATIVE_YEAR")
        with self.assertRaisesRegex(ValueError,"SOURCE_EVIDENCE"): epw_reference(self.b,ref,(2002,2014),"")
        with self.assertRaisesRegex(ValueError,"MUST_REPRESENT"): epw_reference(self.b,self.b,(2002,2014),"Synthetic")

    def test_reference_geometry_height_clock_and_pressure_must_match(self):
        ref = self.admit(self.b.epw,"REPRESENTATIVE_YEAR")
        bad = [replace(ref,location=replace(ref.location,elevation_m=401.)),
            replace(ref,location=replace(ref.location,latitude=48.)),
            replace(ref,request=replace(ref.request,utc_offset_minutes=0)),replace(ref,pressure_contract=SURFACE)]
        for r in bad:
            with self.assertRaisesRegex(ValueError,"MISMATCH"): epw_reference(self.b,r,(2002,2014),"Synthetic period")

    def test_station_point_cannot_silently_use_background_climate_reference(self):
        with self.assertRaisesRegex(ValueError,"CANNOT_REPLACE_STATION_OR_POINT"):
            background_reference(self.b,(2002,2014))

    def test_liquid_precipitation_proxy_requires_explicit_admission(self):
        r = SignalRequest(*self.b.identity["signal_site"])
        with self.assertRaisesRegex(ValueError,"LIQUID_RAIN_PROXY_REQUIRED"):
            morph_selected(self.b,climatology([self.b]),signals(),r,reference_evidence={"reference_window":[2002,2014]},nex_evidence={})

    def test_model_point_windows_are_explicit_and_bounded(self):
        for change in ({"model":"Other"},{"scenario":"ssp126"},{"latitude":-70},
            {"reference_window":(2023,2023)},{"future_window":(2000,2019)}, {"future_window":(2090,2110)}):
            with self.subTest(change=change),self.assertRaises(ValueError): SignalRequest(47.,15.,**change) if "latitude" not in change else SignalRequest(longitude=15.,**change)
        r = SignalRequest(47.,15.,(2005,2024),(2040,2059),scenario="ssp585")
        self.assertIn(("ssp585",2024,"tas"),r.jobs)
        self.assertIn(("historical",2014,"tas"),r.jobs)


class F1OriginalSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT/"research/ige_cmip6/f1_selected_base_replay_contract_20261029.json").read_bytes())
        cls.packet = (ROOT/"research/ige_cmip6"/cls.contract["NASA_packet"]).read_bytes()
        cls.request = SignalRequest(**{**cls.contract["signal_request"], "reference_window":tuple(cls.contract["signal_request"]["reference_window"]),
            "future_window":tuple(cls.contract["signal_request"]["future_window"])})

    def setUp(self):
        guard=patch("socket.socket.connect",side_effect=AssertionError("F1_OFFLINE_SOURCE_REPLAY"));guard.start();self.addCleanup(guard.stop)

    def test_every_original_netcdf_and_model_month_replayed_offline(self):
        s,e = admit_nex_packet(self.packet,self.contract["NASA_packet_sha256"],self.request)
        self.assertEqual(e["grid"],[47.125,15.375])
        self.assertEqual(e["reference_daily_rows"],13*365)
        self.assertEqual(e["future_daily_rows"],20*365)
        self.assertEqual(e["original_responses"],315)
        self.assertFalse(e["daily_time_bounds_verified"])
        self.assertEqual(len(s),12)
        self.assertNotEqual(e["grid"],[46.875,15.375])

    def test_wrong_packet_hash_and_reused_other_site_are_blocked(self):
        with self.assertRaisesRegex(ValueError,"HASH_OR_SIZE"): admit_nex_packet(self.packet,"0"*64,self.request)
        with self.assertRaisesRegex(ValueError,"LOCATION_OR_REQUEST_MISMATCH"):
            admit_nex_packet(self.packet,self.contract["NASA_packet_sha256"],replace(self.request,latitude=48.))

    def test_original_unit_calendar_and_time_order_are_not_just_row_counts(self):
        from epw_climate_analyzer.engine.model_sources import bounded_zip
        from scipy.io import netcdf_file
        raw = bounded_zip(self.packet,member_limit=640)["historical_2002_tas.nc"]
        for field in ("units","calendar","duplicate_day"):
            # scipy append mode rewrites this in-memory NetCDF; retain an
            # open buffer explicitly, since netcdf_file closes its file.
            class Buffer(io.BytesIO):
                def close(self):
                    if not self.closed: self.saved = self.getvalue()
                    super().close()
            buf=Buffer(raw)
            with netcdf_file(buf,"a",mmap=False) as nc:
                if field=="units": nc.variables["tas"].units="degC"
                elif field=="calendar": nc.variables["time"].calendar="gregorian"
                else: nc.variables["time"][1]=nc.variables["time"][0]
            expected = {"units":"UNIT_CHANGED", "calendar":"CALENDAR_CHANGED", "duplicate_day":"WRONG_CF_DAY"}[field]
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,expected): decode_point(buf.saved,"tas",2002,self.request)

    def test_actual_full_future_year_and_phase_aware_analysis(self):
        from f1_replay_audit import replay_f1_example
        p, audit = replay_f1_example()
        self.assertEqual(audit["status"],"PASS")
        self.assertEqual(len(p.dataset.data),8760)
        self.assertFalse(p.report["production_ready"])
        self.assertEqual(p.report["quality"]["independent_accuracy"], "NOT_INDEPENDENTLY_VALIDATED")
        frame=prepare_engine_analysis_frame(p.dataset)
        self.assertEqual(frame.attrs["ige_ui_analysis"]["pressure_scope"],SURFACE)
        self.assertTrue(monthly_engine_summary(frame)["Total precipitation [mm]"].notna().all())

    def test_downloaded_future_archive_contains_all_inputs_for_offline_replay(self):
        from f1_replay_audit import replay_f1_example, compare_output
        from epw_climate_analyzer.future_selected import replay_selected_future
        product,_ = replay_f1_example()
        again = replay_selected_future(product.archive,sha256(product.archive).hexdigest())
        self.assertEqual(compare_output(again.files["climate.epw"],product.files["climate.epw"])["comparison"],
            "PASS_EXISTING_EPW_READBACK_PRECISION_1E_7_OR_1E_9_RELATIVE")
        with self.assertRaisesRegex(ValueError,"SHA256_REQUIRED"): replay_selected_future(product.archive,"0"*64)

    def test_selected_point_with_compatible_reference_has_future_route_without_background_substitution(self):
        b = synthetic_base()
        ref = admit_base(b.epw,calendar_kind="REPRESENTATIVE_YEAR",pressure_contract=COLLOCATED,water_curve=BUCK)
        product = run_selected_future(b,self.request,reference_mode="SEPARATE_REFERENCE_EPW",reference_base=ref,
            period_evidence="SYNTHETIC CONTROL ONLY; not a measured multi-year climatology",
            nex_packet=self.packet,nex_packet_sha256=self.contract["NASA_packet_sha256"],allow_liquid_precipitation_proxy=True)
        self.assertEqual(product.report["diagnostics"]["water_curve"],BUCK)
        self.assertEqual(product.report["diagnostics"]["pressure_contract"],COLLOCATED)
        self.assertEqual(product.report["source_geometry"]["selected_base"]["elevation_m"],400.)
        self.assertFalse(product.report["diagnostics"]["total_precipitation_available"])
        frame = prepare_engine_analysis_frame(product.dataset)
        self.assertTrue(monthly_engine_summary(frame)["Total precipitation [mm]"].isna().all())
        np.testing.assert_array_equal(frame[P],b.data[P])


if __name__ == "__main__": unittest.main()
