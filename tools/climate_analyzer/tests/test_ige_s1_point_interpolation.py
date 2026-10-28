"""S1 numerical parity, source gates, active corrections and output lineage."""
from __future__ import annotations

import ast
import calendar
import collections
from dataclasses import replace
import datetime as dt
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import pandas as pd

from epw_climate_analyzer.climate_model import ClimateLocation
from epw_climate_analyzer.engine.point_interpolation import (T, P, E, RH, TD,
    PointRequest, PointDonor, calibration, idw_weights, distance_km,
    hypsometric_pressure_hpa, saturation_buck_hpa, dewpoint_buck_c,
    reconcile_vapour, interpolate_point)
from epw_climate_analyzer import point_interpolation as service

ROOT = Path(__file__).resolve().parents[3]


def inputs(year=2023, offset=0, latitude=47.0707, longitude=15.4395):
    request = PointRequest(latitude, longitude, 400., "Synthetic common ASL datum", year, offset,
        "S1 SYNTHETIC TEST", assume_buck_water=True, allow_nominal_height_proxy=True)
    mon = request.local_starts.month.to_numpy()
    n = len(mon); time = np.arange(n)
    base_t = 10+7*np.sin(2*np.pi*time/n)+2*np.sin(2*np.pi*time/24)
    base_e = .5*saturation_buck_hpa(base_t)
    config = calibration()["training"]
    donors = []
    for i, z in enumerate((300., 420., 500., 580.)):
        t = base_t+np.asarray(config["temperature_slope_K_m"])[mon-1]*(z-request.elevation_m)
        e = base_e*np.exp(np.asarray(config["log_vapour_slope_m_inv"])[mon-1]*(z-request.elevation_m))
        p = np.full(n, 96000.+i*600)
        frame = pd.DataFrame({T: t, P: p, E: e, RH: 100*e/saturation_buck_hpa(t)}, index=request.utc_starts)
        donors.append(PointDonor(f"D{i}", ClimateLocation(latitude+.03*(i+1), longitude+.02*i, z),
            frame, year, z, z, "SYNTHETIC common datum", False, sha256(f"SYNTHETIC_D{i}".encode()).hexdigest(), "SYNTHETIC_TEST"))
    return request, donors


def frozen_functions():
    """Execute only original pure functions, without old network/training imports."""
    folder = ROOT/"research/ige_cmip6/s1_frozen_p82f"
    namespace = {"np": np, "math": math, "calendar": calendar, "dt": dt, "collections": collections,
        "YEAR": 2019, "N_DONORS": 4, "MONTHS": tuple(range(1, 13)), "RD": 287.05, "G": 9.80665,
        "METHODS": ("constant", "nearest_shape", "half_multidonor_shape", "full_multidonor_shape"),
        "MAX_PRESSURE_FRACTION": .98, "EPS": 1e-6}
    wanted = {"esat_water_hpa", "dew_point_from_vapour", "capacity", "reconcile_monthly", "annual_hours",
              "weights", "hypsometric_pressure", "donor_month_datum", "annual_predict"}
    for name in ("p8_2a_humidity.py", "p8_2b_hourly.py", "p8_2c_hourly.py", "p8_2e_crossyear.py"):
        tree = ast.parse((folder/name).read_text())
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        exec(compile(tree, str(folder/name), "exec"), namespace)
    return namespace


def epw_inputs():
    """Small complete synthetic weather definitions; all source rows are real-year shaped."""
    from test_ige_h1_station_year import complete_inputs
    from epw_climate_analyzer.engine.station_epw_admission import assess_station_year
    request, location, frame, fields = complete_inputs()
    out = assess_station_year(request, location, frame, fields, source_id="SYNTHETIC_TEST")
    rows = list(__import__("csv").reader(io.StringIO(out.epw.decode())))
    data = []
    for i in range(4):
        copy = [list(row) for row in rows]
        copy[0][1] = f"SYNTHETIC TEST DONOR {i}"
        copy[0][6:8] = [47.0707+.03*(i+1), 15.4395+.01*i]
        copy[0][9] = 300.+i*60
        text = io.StringIO(newline=""); __import__("csv").writer(text, lineterminator="\n").writerows(copy)
        data.append((f"synthetic_{i}.epw", text.getvalue().encode()))
    r = PointRequest(47.0707, 15.4395, 400., "Synthetic datum", 2023, 60, "SYNTHETIC POINT",
                     assume_buck_water=True, allow_nominal_height_proxy=True)
    return r, data


class S1PhysicsTests(unittest.TestCase):
    def test_frozen_calibration_and_source_solver_identity(self):
        c = calibration()
        self.assertTrue(c["not_retrained"])
        path = ROOT/"research/ige_cmip6/s1_frozen_p82f/accepted_2019_ci_artifact.zip"
        raw = path.read_bytes()
        self.assertEqual(sha256(raw).hexdigest(), c["artifact"]["sha256"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(json.loads(archive.read("selection_provenance.json"))["austria_training"], c["training"])
        original = (path.parent/"p8_2e_crossyear.py").read_bytes()
        from hashlib import sha1
        self.assertEqual(sha1(b"blob "+str(len(original)).encode()+b"\0"+original).hexdigest(), c["original_solver_blob_sha"])

    def test_complete_annual_solver_matches_immutable_p82f_equations(self):
        request, donors = inputs()
        new = interpolate_point(request, donors)
        self.assertEqual(new.report["status"], "POINT_YEAR_COMPLETE_RESEARCH")
        old = frozen_functions()
        hours = old["annual_hours"](request.year)
        month = np.array([stamp.month for stamp in hours])
        weather, monthly, selected = {}, {}, []
        for donor in donors:
            sid = donor.station_id
            weather[sid] = {stamp: {"T": row[T], "P": row[P]/100, "e": row[E], "RH": row[RH]} for stamp, (_, row) in zip(hours, donor.data.iterrows())}
            monthly[sid] = {f"2023-{m:02d}": {"e": float(donor.data[E].to_numpy()[month == m].mean())} for m in range(1, 13)}
            selected.append((distance_km(request.latitude, request.longitude, donor.location.latitude, donor.location.longitude),
                {"station_id": sid, "hoehe_m": donor.temperature_elevation_m}))
        selected.sort(key=lambda x: (x[0], x[1]["station_id"]))
        cfg = calibration()["training"]
        prediction, _ = old["annual_predict"]({"station_id": "target", "hoehe_m": request.elevation_m},
            selected, hours, weather, monthly, cfg["log_vapour_slope_m_inv"], cfg["temperature_slope_K_m"], year=request.year)
        for col, key, factor, atol in ((T, "T", 1, 1e-11), (P, "P", 100, 1e-8), (E, "e", 1, 1e-10),
                                       (RH, "RH", 1, 1e-8), (TD, "Td", 1, 1e-9)):
            np.testing.assert_allclose(new.hourly[col], factor*prediction["full_multidonor_shape"][key], rtol=0, atol=atol)

    def test_height_changes_weather_and_pressure_signs_are_physical(self):
        request, donors = inputs()
        a = interpolate_point(request, donors)
        b = interpolate_point(replace(request, elevation_m=500.), donors)
        mon = request.local_starts.month
        expected = np.asarray(calibration()["training"]["temperature_slope_K_m"])[mon-1]*100
        np.testing.assert_allclose(b.hourly[T]-a.hourly[T], expected, rtol=0, atol=1e-12)
        self.assertTrue((b.hourly[P] < a.hourly[P]).all())
        self.assertGreater(a.report["max_abs_temperature_height_correction_K"], 0)
        self.assertGreater(a.report["max_abs_pressure_height_correction_pa"], 0)
        self.assertEqual(len(a.donor_months), 48)
        self.assertLess(a.report["max_q_to_e_closure_pa"], 1e-9)
        self.assertTrue((a.adjustments["T_after_height_c"] == a.hourly[T]).all())

    def test_missing_nearer_donor_is_rejected_before_four_donor_selection(self):
        request, donors = inputs()
        bad = replace(donors[0], station_id="bad", source_sha256="bad", location=ClimateLocation(request.latitude, request.longitude, 300), data=donors[0].data.copy())
        bad.data.iloc[0, bad.data.columns.get_loc(T)] = np.nan
        result = interpolate_point(request, [bad, *donors])
        self.assertEqual(result.report["status"], "POINT_YEAR_COMPLETE_RESEARCH")
        self.assertNotIn("bad", result.report["selected_donors"])
        self.assertFalse(result.report["donor_admission"][0]["eligible"])

    def test_no_complete_year_from_three_donors_and_no_background_request(self):
        request, donors = inputs()
        result = interpolate_point(request, donors[:3])
        self.assertEqual(result.report["status"], "POINT_YEAR_BLOCKED")
        self.assertEqual(len(result.hourly.columns), 0)

    def test_repeated_source_or_target_identity_cannot_inflate_donor_count(self):
        request, donors = inputs()
        duplicate = replace(donors[0], station_id="other")
        self.assertIn("DUPLICATED_DONOR_ID_OR_SOURCE_BYTES", interpolate_point(request, [*donors, duplicate]).report["global_blockers"])
        excluded = interpolate_point(replace(request, excluded_station_id="D0"), donors)
        self.assertEqual(excluded.report["status"], "POINT_YEAR_BLOCKED")
        self.assertIn("TARGET_STATION_EXCLUDED", excluded.report["donor_admission"][0]["reasons"])

    def test_explicit_phase_height_clock_and_geographic_admission(self):
        request, donors = inputs()
        for r, error in ((replace(request, assume_buck_water=False), "BUCK_WATER_ASSUMPTION_NOT_ACCEPTED"),
            (replace(request, latitude=40.), "OUTSIDE_OPERATIONAL_RADIUS"),
            (replace(request, elevation_m=3000.), "OUTSIDE_OPERATIONAL_HEIGHT_DIFFERENCE")):
            result = interpolate_point(r, donors)
            self.assertEqual(result.report["status"], "POINT_YEAR_BLOCKED")
            self.assertIn(error, result.report["donor_admission"][0]["reasons"])
        proxy = [replace(d, height_is_proxy=True) for d in donors]
        result = interpolate_point(replace(request, allow_nominal_height_proxy=False), proxy)
        self.assertEqual(result.report["status"], "POINT_YEAR_BLOCKED")
        shifted = replace(donors[0], data=donors[0].data.set_axis(donors[0].data.index+pd.Timedelta(hours=1)))
        self.assertEqual(interpolate_point(request, [shifted, *donors[1:]]).report["status"], "POINT_YEAR_BLOCKED")

    def test_leap_day_and_fixed_standard_clock_retained(self):
        request, donors = inputs(2024, 60)
        result = interpolate_point(request, donors)
        self.assertEqual(result.report["hours"], 8784)
        self.assertEqual(result.hourly.index[0], pd.Timestamp("2023-12-31T23:00:00Z"))
        self.assertEqual(int(((request.local_starts.month == 2) & (request.local_starts.day == 29)).sum()), 24)

    def test_saturation_redistributes_with_exact_monthly_goal_and_ledger(self):
        t = np.array([-5., 15., 15., 15.]); p = np.full(4, 950.)
        e, scale, cap = reconcile_vapour(5., np.array([8., 1., 1., 1.]), t, p)
        self.assertAlmostEqual(e.mean(), 5., places=8)
        self.assertLess(e[0], scale*8)
        self.assertTrue(np.all(e <= cap))
        with self.assertRaisesRegex(ValueError, "INFEASIBLE_MONTHLY"):
            reconcile_vapour(50., np.ones(4), t, p)
        with self.assertRaisesRegex(ValueError, "SHAPE"):
            reconcile_vapour(5., np.array([1, 0, 1, 1]), t, p)

    def test_infeasible_point_goal_is_blocked_without_weakening_source_constraints(self):
        request, donors = inputs()
        wet = [replace(d, monthly_vapour_hpa=(70.,)*12, monthly_origin="SYNTHETIC_IMPOSSIBLE_CONSTRAINT") for d in donors]
        result = interpolate_point(request, wet)
        self.assertEqual(result.report["status"], "POINT_YEAR_BLOCKED")
        self.assertIn("INFEASIBLE_MONTHLY_MEAN_UNDER_HOURLY_SATURATION", result.report["global_blockers"])

    def test_water_curve_inverse_and_dry_pressure_are_frozen_not_new_fit(self):
        old = frozen_functions()
        for t in (-30., -5., 10., 30.):
            e = float(saturation_buck_hpa(t))
            self.assertAlmostEqual(e, old["esat_water_hpa"](t), places=12)
            self.assertAlmostEqual(float(dewpoint_buck_c(e)), t, places=11)
        for dz in (-500., 0., 500.):
            self.assertAlmostEqual(float(hypsometric_pressure_hpa(980., 10., dz)), old["hypsometric_pressure"](980., 10., dz), places=12)
        np.testing.assert_equal(idw_weights([0, .1, 2]), old["weights"]([0, .1, 2]))


class S1SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request, cls.epws = epw_inputs()

    def setUp(self):
        guard = patch("socket.socket.connect", side_effect=AssertionError("S1_SOURCE_TEST_OFFLINE"))
        guard.start(); self.addCleanup(guard.stop)

    def test_original_h1_missing_weather_is_not_promoted_by_vapour_derivation(self):
        from epw_climate_analyzer.geosphere_station_year import run_station_year
        from epw_climate_analyzer.engine.station_epw_admission import StationYearRequest
        c = json.loads((ROOT/"research/ige_cmip6/h1_graz16412_2023_source_contract_20261028.json").read_bytes())
        raw = (ROOT/"research/ige_cmip6"/c["source_packet"]).read_bytes()
        h1 = run_station_year(StationYearRequest(**c["request"]), source_packet=raw, expected_sha256=c["source_packet_sha256"])
        donor = service.donor_from_station_year(h1)
        self.assertTrue(any("H1_CORE_NOT_ADMITTED" in reason for reason in donor.blockers))
        self.assertEqual(int(donor.data[T].notna().sum()), 4303)
        self.assertEqual(int(donor.data[E].notna().sum()), 4303)
        self.assertEqual(sha256(raw).hexdigest(), c["source_packet_sha256"])
        r = replace(self.request, label="Station identity regression")
        packet = service._source_inputs(r, "GEOSPHERE", [{"file": "station.sources.zip", "station_id": "WRONG"}],
                                        {"station.sources.zip": raw})
        with self.assertRaisesRegex(ValueError, "STATION_IDENTITY_MISMATCH"):
            service.run_point_product(r, input_packet=packet, expected_sha256=sha256(packet).hexdigest())

    def test_retained_original_source_examples_and_donor_epw_lineage(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ige_s1_replay_audit", ROOT/"research/ige_cmip6/s1_replay_audit.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        r = module.replay_s1_examples()
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["positive_hours"], 8760)
        self.assertEqual(r["negative_station_eligible"], 1)
        self.assertFalse(r["new_independent_accuracy_validation"])

    def test_actual_epw_clock_and_confirmation_required_no_tmy_relabelling(self):
        raw = self.epws[0][1]
        for r, data, confirm, error in ((self.request, raw, False, "CONFIRMATION"),
            (replace(self.request, year=2024), raw, True, "COMPLETE_ACTUAL_YEAR"),
            (replace(self.request, utc_offset_minutes=0), raw, True, "OFFSET_MISMATCH"),
            (self.request, raw.replace(b"SYNTHETIC TEST DONOR", b"TMY TEST DONOR"), True, "TMY")):
            with self.assertRaisesRegex(ValueError, error):
                service.donor_from_epw(data, r, actual_year_confirmed=confirm)

    def test_epw_source_interpolation_has_replay_and_no_fabricated_other_fields(self):
        product = service.run_point_product(self.request, mode="EPW", epws=self.epws, actual_year_confirmed=True)
        self.assertEqual(product.report["status"], "POINT_YEAR_COMPLETE_RESEARCH")
        self.assertNotIn("climate.epw", product.files)
        self.assertEqual(len(product.report["EPW_blockers"]), 8)
        packet = product.files["inputs.zip"]
        replay = service.run_point_product(self.request, input_packet=packet, expected_sha256=sha256(packet).hexdigest())
        self.assertEqual(product.files["hourly.csv.gz"], replay.files["hourly.csv.gz"])
        self.assertEqual(product.files["adjustments.csv.gz"], replay.files["adjustments.csv.gz"])
        self.assertEqual(product.files["donor_months.csv"], replay.files["donor_months.csv"])
        self.assertEqual(product.report["selected_base_sha256"], replay.report["selected_base_sha256"])
        self.assertFalse(product.report["quality"]["production_ready"])

    def test_hash_and_request_tampering_fail_before_source_replay(self):
        product = service.run_point_product(self.request, mode="EPW", epws=self.epws, actual_year_confirmed=True)
        packet = product.files["inputs.zip"]
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            service.run_point_product(self.request, input_packet=packet, expected_sha256="0"*64)
        with self.assertRaisesRegex(ValueError, "REQUEST_MISMATCH"):
            service.run_point_product(replace(self.request, elevation_m=500.), input_packet=packet, expected_sha256=sha256(packet).hexdigest())

    def test_background_is_explicit_and_cannot_hide_failed_core(self):
        with patch("epw_climate_analyzer.engine_application.run_historical_product") as background:
            product = service.run_point_product(self.request, mode="EPW", epws=self.epws[:3],
                actual_year_confirmed=True, include_background=True)
            self.assertEqual(product.report["background_status"], "NOT_ACQUIRED_CORE_BLOCKED")
            self.assertNotIn("climate.epw", product.files)
            background.assert_not_called()

    def test_complete_composite_preserves_background_fields_and_changes_actual_height(self):
        import csv
        from epw_climate_analyzer.engine_application import run_historical_product, pilot_historical_request
        background = run_historical_product(pilot_historical_request())
        product = service.run_point_product(self.request, mode="EPW", epws=self.epws, actual_year_confirmed=True,
            include_background=True, background_product=background)
        self.assertEqual(product.report["EPW_status"], "ADMITTED_MIXED_SOURCE_RESEARCH", product.report["EPW_blockers"])
        epw = list(csv.reader(io.StringIO(product.files["climate.epw"].decode())))
        original = list(csv.reader(io.StringIO(background.files["climate.epw"].decode())))
        self.assertEqual(float(epw[0][9]), 400.)
        self.assertEqual(float(epw[0][6]), self.request.latitude)
        self.assertIn("height corrections", epw[5][1])
        for name, (col, _, _) in service.EPW_FIELDS.items():
            if name not in (T, P, RH, TD):
                self.assertEqual([row[col] for row in epw[8:]], [row[col] for row in original[8:]], name)
        self.assertEqual(product.files["background.epw"], background.files["climate.epw"])
        self.assertFalse(product.report["EPW_screen"]["EnergyPlus_simulation_executed"])
        packet = background.files["sources.zip"]
        replay = service.replay_background(self.request, packet, sha256(packet).hexdigest())
        self.assertEqual(replay.files["climate.epw"], background.files["climate.epw"])
        with self.assertRaisesRegex(ValueError, "WEATHER_REQUEST_MISMATCH"):
            service.replay_background(replace(self.request, latitude=48.), packet, sha256(packet).hexdigest())

    def test_background_failure_keeps_valid_core_and_refuses_epw(self):
        with patch("epw_climate_analyzer.engine_application.run_historical_product", side_effect=TimeoutError("source timeout")):
            product = service.run_point_product(self.request, mode="EPW", epws=self.epws, actual_year_confirmed=True, include_background=True)
        self.assertEqual(product.report["status"], "POINT_YEAR_COMPLETE_RESEARCH")
        self.assertEqual(product.report["background_status"], "BLOCKED")
        self.assertNotIn("climate.epw", product.files)
        self.assertIn("source timeout", product.report["EPW_blockers"][0])


if __name__ == "__main__": unittest.main()
