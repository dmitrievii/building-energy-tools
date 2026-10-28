"""B-M1 mathematical identities, source admission and actual-source regression.

These are implementation/physical contract checks, not station validation.
"""
from __future__ import annotations
import csv
from dataclasses import replace
import importlib.util
import io
import json
from pathlib import Path
import unittest
import numpy as np

from epw_climate_analyzer.engine import FutureRequest, HistoricalRequest
from epw_climate_analyzer.engine.future import (
    PATTERN_SOURCE_SHA, reference_climatology, temperature_morph, morph_future, verify_signals,
    T, TD, RH, P, Q, GHI, LW, WS, PR,
)
from epw_climate_analyzer.engine.historical import read_source_bundle, assemble_historical
from epw_climate_analyzer.engine.epw import serialize_epw, validate_weather
from epw_climate_analyzer.engine.model_sources import admit_nex, monthly_nex_signals, SEMANTICS_VERSION, sha
from epw_climate_analyzer.engine.thermodynamics import (
    saturation_water_pa, saturation_nasa_phase_pa, q_from_e, e_from_q,
    pressure_at_2m, baseline_vapour_state, state_from_vapour, q_saturation_at_2m,
    project_monthly_q, dew_point_water_c, RD, RV, G,
)

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / "research/ige_cmip6"
BASE_SHA = "acf8e7d82be69de5fa19f76c599143559d477aa01cdb7c56414fc23c93796635"


def request():
    return FutureRequest(BASE_SHA, "CanESM5", "r1i1p1f1", "ssp245", (2002, 2014), (2040, 2059), SEMANTICS_VERSION, 2023)


class ThermodynamicTests(unittest.TestCase):
    def test_Murphy_Koop_matches_unchanged_P9_3B3_reference(self):
        spec = importlib.util.spec_from_file_location("ige_independent_research_thermo", RESEARCH / "p9_3b3_thermodynamics.py")
        reference = importlib.util.module_from_spec(spec); spec.loader.exec_module(reference)
        t = np.linspace(-60, 50, 200)
        np.testing.assert_allclose(saturation_water_pa(t), reference.saturation(t+273.15, "WATER"), rtol=1e-13)
        np.testing.assert_allclose(saturation_nasa_phase_pa(t), reference.saturation(t+273.15, "WATER_ICE"), rtol=1e-13)

    def test_vapour_specific_humidity_inverse_uses_moist_air_fraction(self):
        e = np.array([0., 500., 2000.]); p = np.array([80000., 95000., 100000.])
        q = q_from_e(e, p)
        np.testing.assert_allclose(e_from_q(q, p), e, atol=1e-12)
        self.assertGreater(q[-1]/(1-q[-1]), q[-1])

    def test_hydrostatic_two_metre_adapter_matches_ideal_gas_solution(self):
        temperature, q, ps = 15., .008, 100000.
        expected = ps*np.exp(-G*2 / ((RD*(1-q)+RV*q)*(temperature+273.15)))
        self.assertAlmostEqual(float(pressure_at_2m(temperature, q, ps)), expected, places=10)
        self.assertLess(expected, ps)

    def test_implicit_adapter_keeps_the_original_vapour_pressure(self):
        t, td, ps = np.array([-10., 0., 25.]), np.array([-12., -3., 15.]), np.array([95000., 100000., 98000.])
        q, p, rh = baseline_vapour_state(t, td, ps)
        np.testing.assert_allclose(e_from_q(q, p), saturation_water_pa(td), rtol=1e-13)
        np.testing.assert_allclose(p, pressure_at_2m(t, q, ps), atol=1e-9)
        self.assertTrue(np.all((rh >= 0) & (rh <= 100)))

    def test_coupled_saturation_bound_is_feasible_in_floating_point(self):
        t = np.linspace(-40, 45, 1000); ps = np.linspace(80000, 102000, 1000)
        q = q_saturation_at_2m(t, ps); p = pressure_at_2m(t, q, ps)
        e = e_from_q(q, p)
        self.assertTrue(np.all(e <= saturation_water_pa(t)))
        np.testing.assert_allclose(e, saturation_water_pa(t), rtol=1e-13)

    def test_NASA_ice_RH_is_diagnostic_and_may_exceed_water_RH(self):
        t = np.array([-10., 0., 20.]); e = .99*saturation_water_pa(t)
        water = 100*e/saturation_water_pa(t); nasa = 100*e/saturation_nasa_phase_pa(t)
        self.assertGreater(nasa[0], 100)
        np.testing.assert_allclose(nasa[1:], water[1:], atol=1e-12)

    def test_projection_has_the_analytic_unique_two_hour_solution(self):
        out, lam = project_monthly_q(np.array([.01, .01]), np.array([.007, .02]))
        np.testing.assert_allclose(out, [.007, .013], atol=1e-15)
        self.assertAlmostEqual(lam, .003, places=14)
        self.assertAlmostEqual(float(out.sum()), .02, places=14)

    def test_projection_KKT_for_many_hours_and_exact_time_mean(self):
        target = np.array([.001, .002, .004, .009, .006])
        upper = np.array([.003, .004, .008, .006, .005])
        out, lam = project_monthly_q(target, upper)
        np.testing.assert_allclose(out, np.clip(target+lam, 0, upper), atol=1e-15)
        self.assertAlmostEqual(float(out.sum()), float(target.sum()), places=14)
        free = (out > 0) & (out < upper)
        np.testing.assert_allclose(out[free]-target[free], lam, atol=1e-15)

    def test_projection_infeasibility_does_not_silently_clip_q_target(self):
        with self.assertRaisesRegex(ValueError, "INFEASIBLE"):
            project_monthly_q(np.array([.02, .02]), np.array([.01, .01]))

    def test_zero_q_is_not_replaced_by_an_arbitrary_RH_floor(self):
        out, _ = project_monthly_q(np.zeros(3), np.full(3, .01))
        np.testing.assert_array_equal(out, 0)
        with self.assertRaisesRegex(ValueError, "FINITE_FORMULA_DOMAIN"):
            dew_point_water_c(np.array([0.]))

    def test_invalid_states_and_supersaturated_base_fail_closed(self):
        for fn in (lambda: q_from_e(100000, 95000), lambda: e_from_q(1, 95000),
                lambda: saturation_water_pa(60), lambda: baseline_vapour_state(10, 11, 95000)):
            with self.assertRaises(ValueError): fn()

    def test_dewpoint_inversion_including_below_zero_water_phase(self):
        td = np.linspace(-60, 45, 100)
        np.testing.assert_allclose(dew_point_water_c(saturation_water_pa(td)), td, atol=1e-10)


class TemperatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.months = HistoricalRequest(47, 15, 2023, 60).local_starts.month.to_numpy()[::24]
        c = np.arange(365)*.01
        shape = np.array([-1.]*21+[4.]*3)
        cls.t = (c[:, None]+shape).reshape(-1)
        cls.reference = {m: {"midrange_c": 10.+m, "dtr_K": 6.} for m in range(1,13)}
        cls.signals = {m: {"midrange_delta_K": 2., "dtr_ratio": 1.1,
            "historical_midrange_sorted_c": [-10., 10., 20.], "future_midrange_sorted_c": [-9., 12., 23.]}
            for m in range(1,13)}

    def test_NASA_midrange_and_DTR_targets_not_hourly_T_mean(self):
        output, monthly = temperature_morph(self.t, self.months, self.reference, self.signals)
        for r in monthly:
            self.assertAlmostEqual(r["actual_midrange_c"], self.reference[r["month"]]["midrange_c"]+2, places=12)
            self.assertAlmostEqual(r["actual_DTR_K"], 6.6, places=12)
            self.assertGreater(abs(r["hourly_time_mean_T_c_DIAGNOSTIC_NOT_NEX_tas"]-r["actual_midrange_c"]), 1.)

    def test_pattern_temperature_offset_does_not_double_count_warming(self):
        a, _ = temperature_morph(self.t, self.months, self.reference, self.signals)
        b, _ = temperature_morph(self.t+10, self.months, self.reference, self.signals)
        np.testing.assert_allclose(a, b, atol=1e-12)

    def test_flat_month_or_incomplete_year_requires_separate_method(self):
        for values in (np.ones(8760), self.t[:-1]):
            with self.assertRaises(ValueError): temperature_morph(values, self.months, self.reference, self.signals)


class ActualSourceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.future = request()
        pattern_request = HistoricalRequest(47.0707, 15.4395, 2023, 60, label="Graz")
        raw, receipts = read_source_bundle(RESEARCH / "i1_a0_graz2023_original_sources_20261025.zip", PATTERN_SOURCE_SHA, pattern_request)
        cls.pattern = assemble_historical(pattern_request, raw, receipts)
        h, f, cls.nex = admit_nex(RESEARCH / "e2e_original_replay_inputs_20261025.zip", cls.future)
        cls.h, cls.f, cls.signals = h, f, monthly_nex_signals(h, f)
        cls.ref, cls.ref_evidence = reference_climatology(RESEARCH / "bm1_reference_sources_2002_2014_20261025.zip",
            cls.pattern, sha((RESEARCH / "bm1_protocol_20261025.json").read_bytes()))
        cls.result = morph_future(cls.pattern, cls.future, cls.ref, cls.signals, cls.ref_evidence, cls.nex)
        cls.payload, cls.epw = serialize_epw(cls.result)

    def test_NEX_both_full_windows_and_selected_historical_period(self):
        self.assertEqual(len(self.h), 13*365); self.assertEqual(len(self.f), 20*365)
        for key in ("historical", "ssp245"):
            self.assertEqual(self.nex[key]["archive_days_checked"], 7300)
            self.assertLess(self.nex[key]["max_tas_midrange_residual_K"], 5e-5)
        self.assertFalse(self.nex["daily_bounds_verified"])

    def test_unregistered_identity_or_epoch_is_not_silently_replaced(self):
        for future in (replace(self.future, model="OtherGCM"), replace(self.future, historical_window=(1995,2014))):
            with self.assertRaisesRegex(ValueError, "UNREGISTERED"):
                admit_nex(RESEARCH / "e2e_original_replay_inputs_20261025.zip", future)

    def test_reference_keeps_all_original_hours_and_explicitly_removes_only_leap_estimator_days(self):
        self.assertEqual(len(self.ref_evidence["reference_years"]), 13)
        self.assertEqual(self.ref_evidence["noleap_estimator_total_hours"], 13*8760)
        self.assertEqual(self.ref_evidence["full_original_hours"], 13*8760+3*24)

    def test_actual_future_thermodynamic_and_hydrostatic_state(self):
        f = self.result.data
        e = e_from_q(f[Q], f[P])
        np.testing.assert_allclose(100*e/saturation_water_pa(f[T]), f[RH], atol=1e-10)
        np.testing.assert_allclose(saturation_water_pa(f[TD]), e, rtol=1e-12)
        np.testing.assert_allclose(f[P], pressure_at_2m(f[T], f[Q], f["surface_pressure_proxy_pa"]), atol=1e-8)
        self.assertLessEqual(float(f[RH].max()), 100.)
        self.assertFalse(self.result.diagnostics["pressure_accuracy_independently_qualified"])

    def test_serialized_EPW_monthly_signal_readback(self):
        result = verify_signals(self.result, self.payload)
        self.assertEqual(result["records"], 8760)
        self.assertFalse(result["independent_accuracy_qualified"])
        self.assertLess(max(abs(r["q_mean_error_kgkg"]) for r in result["monthly_readback"]), 1e-9)

    def test_NASA_total_precipitation_is_not_claimed_as_liquid_rain(self):
        f, b = self.result.data, self.pattern.data
        self.assertGreater(float((f[PR]-f["liquid_precipitation_depth_mm"]).sum()), 0)
        wet = b[PR].to_numpy() > 0
        np.testing.assert_allclose((f["liquid_precipitation_depth_mm"]/f[PR]).to_numpy()[wet],
            (b["liquid_precipitation_depth_mm"]/b[PR]).to_numpy()[wet], atol=1e-13)
        np.testing.assert_array_equal(f[PR].to_numpy() > 0, wet)

    def test_component_radiation_direction_and_cloud_structure_are_inherited(self):
        f, b = self.result.data, self.pattern.data
        np.testing.assert_allclose(f[GHI], f["direct_horizontal_radiation_wh_m2"]+f["diffuse_horizontal_radiation_wh_m2"], atol=1e-10)
        for name in ("wind_direction_deg", "total_sky_cover_tenths"):
            np.testing.assert_array_equal(f[name], b[name])
        self.assertFalse(self.result.diagnostics["independent_DNI_DHI_future_signals_available"])

    def test_hurs_is_diagnostic_and_not_falsely_claimed_as_a_joint_constraint(self):
        self.assertFalse(self.result.diagnostics["hurs_signal_enforced"])
        self.assertFalse(self.result.diagnostics["hourly_NASA_daily_constraints_enforced"])
        self.assertIn("relative_humidity_NASA_phase_pct", self.result.data)

    def test_future_metadata_uses_pattern_calendar_not_a_forecast_for_2023(self):
        c = self.result.to_canonical()
        self.assertEqual(c.temporal.calendar_mode, "climatology")
        self.assertEqual(set(c.data.index.year), {2023})
        self.assertTrue(c.data.attrs["ige_UI_humidity_phase_adapter_required"])
        rows = list(csv.reader(io.StringIO(self.payload.decode())))
        self.assertIn("2040-2059", rows[7][3]); self.assertIn("PATTERN 2023", rows[7][3])

    def test_original_historical_EPW_and_data_have_not_changed(self):
        _, report = serialize_epw(self.pattern)
        self.assertEqual(report["sha256"], BASE_SHA)
        self.assertNotIn(Q, self.pattern.data)
        self.assertEqual(len(self.result.adjustments), 8760)

    def test_modified_export_temperature_signal_is_detected(self):
        rows = list(csv.reader(io.StringIO(self.payload.decode())))
        # Construct a physically consistent warmer day with the same q, so
        # it must fail the climate target rather than the physical-state gate.
        t = self.result.data[T].iloc[:24].to_numpy()+1.
        q = self.result.data[Q].iloc[:24].to_numpy()
        ps = self.result.data["surface_pressure_proxy_pa"].iloc[:24].to_numpy()
        p = pressure_at_2m(t, q, ps); e = e_from_q(q, p)
        rh = 100*(e/saturation_water_pa(t)); td = dew_point_water_c(e)
        for i, row in enumerate(rows[8:32]):
            for column, values in ((6,t),(7,td),(8,rh),(9,p)):
                row[column] = format(float(values[i]), ".10g")
        stream=io.StringIO(); csv.writer(stream,lineterminator="\n").writerows(rows)
        with self.assertRaisesRegex(ValueError, "SIGNAL_LOST"):
            verify_signals(self.result, stream.getvalue().encode())

    def test_serialized_pressure_error_is_detected_even_if_monthly_q_error_is_small(self):
        rows = list(csv.reader(io.StringIO(self.payload.decode())))
        rows[8][9] = str(float(rows[8][9])+1.)
        stream=io.StringIO(); csv.writer(stream,lineterminator="\n").writerows(rows)
        with self.assertRaisesRegex(ValueError, "PRESSURE_OR_VAPOUR_CLOSURE_LOST"):
            verify_signals(self.result, stream.getvalue().encode())

    def test_known_CI_libm_last_digit_differences_encode_to_identical_EPW(self):
        # Actual four-cell difference in CI #40206686961 under 10-significant
        # encoding. Keep its negative receipt; do not relax the file hash gate.
        pairs = [(3375, RH, (41.07314971, 41.07314972)),
            (7721, TD, (-3.43322742e-6, -3.433227533e-6)),
            (7935, TD, (-.001663189884, -.001663189885)),
            (7946, TD, (.7087665086, .7087665087))]
        outputs = []
        for variant in (0, 1):
            frame = self.result.data.copy()
            for i, name, values in pairs:
                frame.iloc[i, frame.columns.get_loc(name)] = values[variant]
            payload, report = serialize_epw(replace(self.result, data=frame))
            self.assertEqual(report["numeric_serialization"]["future_T_Td_RH_only"], "7 fixed decimal places")
            verify_signals(replace(self.result, data=frame), payload)
            outputs.append(payload)
        self.assertEqual(outputs[0], outputs[1])

    def test_missing_state_consistency_cannot_pass_only_range_checks(self):
        changed = self.result.data.copy(); changed[RH] *= .9
        with self.assertRaisesRegex(ValueError, "CLOSURE_FAILED"):
            validate_weather(replace(self.result, data=changed))


if __name__ == "__main__": unittest.main()
