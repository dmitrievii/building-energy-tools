"""I1/A0 clocks, source semantics and immutable replay. Synthetic fixtures only.

Scientific accuracy is evaluated separately; these tests never read IV1 data.
"""
from __future__ import annotations

from dataclasses import replace
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import pandas as pd

from epw_climate_analyzer.engine.contracts import (
    HistoricalRequest, FutureRequest, specific_humidity_to_mixing_ratio_g_kg,
)
from epw_climate_analyzer.engine.epw import serialize_epw, validate_epw_bytes, write_exclusive
from epw_climate_analyzer.engine.historical import (
    MAPPING, SCHEMA, assemble_historical, digest, json_bytes, make_source_bundle,
    read_source_bundle, run_historical, source_plan,
)


def fixture(request: HistoricalRequest) -> tuple[dict, list]:
    plan = source_plan(request)
    par = plan["open_meteo"]["parameters"]
    met_times = pd.date_range(par["start_date"], pd.Timestamp(par["end_date"]) + pd.Timedelta(days=1),
        freq="h", inclusive="left", tz="UTC")
    values = {k: [0.] * len(met_times) for k in MAPPING}
    values.update({"temperature_2m": [0.] * len(met_times), "dew_point_2m": [0.] * len(met_times),
        "relative_humidity_2m": [100.] * len(met_times), "surface_pressure": [950.] * len(met_times),
        "cloud_cover": [43.] * len(met_times), "wind_direction_10m": [120.] * len(met_times)})
    met = {"latitude": request.latitude, "longitude": request.longitude, "elevation": 400.,
        "timezone": "GMT", "utc_offset_seconds": 0,
        "hourly_units": {k: v[1] for k, v in MAPPING.items()},
        "hourly": {"time": met_times.strftime("%Y-%m-%dT%H:%M").tolist(), **values}}
    pp = plan["nasa_power"]["parameters"]
    power_times = pd.date_range(pd.to_datetime(pp["start"]), pd.to_datetime(pp["end"]) + pd.Timedelta(days=1),
        freq="h", inclusive="left", tz="UTC")
    power = {"header": {"time_standard": "UTC", "start": pp["start"], "end": pp["end"],
            "sources": ["SYN1DEG"], "fill_value": -999},
        "geometry": {"type": "Point", "coordinates": [request.longitude, request.latitude, 400.]},
        "parameters": {"ALLSKY_SFC_LW_DWN": {"units": "W m-2"}}, "messages": [],
        "properties": {"parameter": {"ALLSKY_SFC_LW_DWN": {t.strftime("%Y%m%d%H"): 300. for t in power_times}}}}
    raw = {"open_meteo": json_bytes(met), "nasa_power": json_bytes(power)}
    receipts = [{"id": k, "url": plan[k]["url"], "provider": plan[k]["provider"], "dataset": plan[k]["dataset"],
        "sha256": digest(v), "bytes": len(v), "http_attempts": 1} for k, v in raw.items()]
    return raw, receipts


def change(raw: dict, receipts: list, key: str, transform) -> tuple[dict, list]:
    obj = json.loads(raw[key])
    transform(obj)
    updated = {**raw, key: json_bytes(obj)}
    rec = [{**r, "sha256": digest(updated[key]), "bytes": len(updated[key])} if r["id"] == key else r for r in receipts]
    return updated, rec


class RequestTests(unittest.TestCase):
    def test_positive_offset_requires_previous_UTC_interval_start_but_next_endpoint(self):
        r = HistoricalRequest(47, 15, 2023, 60)
        self.assertEqual(len(r.utc_starts), 8760)
        self.assertEqual(r.utc_starts[0].isoformat(), "2022-12-31T23:00:00+00:00")
        self.assertEqual(r.utc_ends[0].isoformat(), "2023-01-01T00:00:00+00:00")
        self.assertEqual(r.utc_ends[-1].isoformat(), "2023-12-31T23:00:00+00:00")

    def test_negative_offset_needs_next_year_endpoint(self):
        r = HistoricalRequest(47, 15, 2023, -300)
        self.assertEqual(r.utc_starts[0].isoformat(), "2023-01-01T05:00:00+00:00")
        self.assertEqual(r.utc_ends[-1].isoformat(), "2024-01-01T05:00:00+00:00")
        self.assertEqual(source_plan(r)["open_meteo"]["parameters"]["end_date"], "2024-01-01")

    def test_leap_year_not_dropped_and_no_DST_gaps(self):
        r = HistoricalRequest(47, 15, 2024, 60)
        self.assertEqual(len(r.utc_starts), 8784)
        self.assertEqual(sum((r.local_starts.month == 2) & (r.local_starts.day == 29)), 24)
        self.assertTrue(((r.utc_starts[1:] - r.utc_starts[:-1]) == pd.Timedelta(hours=1)).all())
        self.assertEqual(len(set(r.local_starts.strftime("%Y-%m-%dT%H"))), 8784)

    def test_fractional_offsets_do_not_silently_round(self):
        with self.assertRaisesRegex(ValueError, "REBINNING_NOT_IMPLEMENTED"):
            HistoricalRequest(47, 15, 2023, 330)

    def test_invalid_coordinates_years_mode_and_unreferenced_height(self):
        for kwargs in ({"latitude": float("nan")}, {"longitude": 181}, {"year": True},
                {"mode": "local_reconstruction"}, {"utc_offset_minutes": True},
                {"site_elevation_m": 350}, {"label": "unsafe,header"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                HistoricalRequest(**{**dict(latitude=47., longitude=15., year=2023, utc_offset_minutes=60), **kwargs})

    def test_source_availability_is_not_silent_fallback(self):
        with self.assertRaisesRegex(ValueError, "2002_THROUGH_2025"):
            source_plan(HistoricalRequest(47, 15, 1990, 60))

    def test_future_identity_window_and_definition_are_explicit(self):
        good = dict(historical_base_sha256="a" * 64, model="CanESM5", member="r1i1p1f1", scenario="ssp245",
            historical_window=(1995, 2014), future_window=(2040, 2059), semantics_version="NASA-midrange-v1",
            representative_pattern_year=2023)
        self.assertEqual(FutureRequest(**good).method, "monthly_morph")
        for k, v in (("historical_base_sha256", ""), ("semantics_version", ""), ("future_window", (2059, 2040))):
            with self.subTest(k=k), self.assertRaises(ValueError):
                FutureRequest(**{**good, k: v})

    def test_specific_humidity_is_not_dry_air_mixing_ratio(self):
        q = np.array([0, .008, .02])
        w = specific_humidity_to_mixing_ratio_g_kg(q)
        np.testing.assert_allclose(w, [0, 8.064516129032258, 20.408163265306122], rtol=1e-14)
        np.testing.assert_allclose(w / (1000 + w), q, atol=1e-15)
        for bad in ([-.001], [1], [float("nan")]):
            with self.assertRaises(ValueError):
                specific_humidity_to_mixing_ratio_g_kg(bad)


class SourceAndExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = HistoricalRequest(47.0707, 15.4395, 2023, 60, label="Graz")
        cls.raw, cls.receipts = fixture(cls.request)

    def result(self):
        return assemble_historical(self.request, self.raw, self.receipts)

    def test_one_hour_support_differences_detected_by_impulses(self):
        # Interval [03,04) UTC: Open-Meteo preceding-hour rain at 04;
        # POWER longwave labelled 03. Source values at the other hour differ.
        raw, rec = change(self.raw, self.receipts, "open_meteo", lambda x: x["hourly"]["rain"].__setitem__(4, 2.))
        raw, rec = change(raw, rec, "open_meteo", lambda x: x["hourly"]["precipitation"].__setitem__(4, 2.))
        raw, rec = change(raw, rec, "nasa_power", lambda x: x["properties"]["parameter"]["ALLSKY_SFC_LW_DWN"].__setitem__("2023010103", 456.))
        result = assemble_historical(self.request, raw, rec)
        stamp = pd.Timestamp("2023-01-01T03:00Z")
        self.assertEqual(result.data.loc[stamp, "liquid_precipitation_depth_mm"], 2.)
        self.assertEqual(result.data.loc[stamp, "horizontal_infrared_radiation_intensity_wh_m2"], 456.)
        self.assertEqual(result.data.loc[stamp + pd.Timedelta(hours=1), "liquid_precipitation_depth_mm"], 0.)

    def test_pressure_is_absolute_Pa_and_model_surface_not_MSL_or_2m(self):
        result = self.result()
        self.assertEqual(result.data["atmospheric_station_pressure_pa"].iloc[0], 95000.)
        self.assertIn("not moved to 2m", result.fields["atmospheric_station_pressure_pa"].definition)
        self.assertFalse(result.diagnostics["pressure_reduced_to_sea_level"])

    def test_no_implicit_height_correction_or_specific_humidity(self):
        request = replace(self.request, site_elevation_m=350, site_elevation_reference="test benchmark; orthometric")
        raw, rec = fixture(request)
        result = assemble_historical(request, raw, rec)
        self.assertEqual(result.location.elevation_m, 400.)
        self.assertFalse(result.diagnostics["site_height_used_for_weather_correction"])
        self.assertNotIn("specific_humidity_kg_kg", result.data)

    def test_corrupt_original_bytes_rejected_before_parse(self):
        with self.assertRaisesRegex(ValueError, "HASH_OR_REQUEST"):
            assemble_historical(self.request, {**self.raw, "open_meteo": self.raw["open_meteo"] + b" "}, self.receipts)

    def test_changed_pressure_unit_fails_closed(self):
        raw, rec = change(self.raw, self.receipts, "open_meteo", lambda x: x["hourly_units"].__setitem__("surface_pressure", "Pa"))
        with self.assertRaisesRegex(ValueError, "UNIT_CHANGED"):
            assemble_historical(self.request, raw, rec)

    def test_missing_or_reordered_time_not_filled(self):
        for transform in (lambda x: x["hourly"]["time"].pop(), lambda x: x["hourly"]["time"].reverse()):
            raw, rec = change(self.raw, self.receipts, "open_meteo", transform)
            with self.assertRaisesRegex(ValueError, "SHIFTED_TIME"):
                assemble_historical(self.request, raw, rec)

    def test_missing_bool_or_nonfinite_source_values_not_coerced(self):
        for value in (None, True, "0"):
            raw, rec = change(self.raw, self.receipts, "open_meteo", lambda x: x["hourly"]["temperature_2m"].__setitem__(0, value))
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "NONNUMERIC_SOURCE"):
                assemble_historical(self.request, raw, rec)

    def test_nonfinite_json_number_not_treated_as_missing_weather(self):
        obj = json.loads(self.raw["open_meteo"])
        obj["hourly"]["temperature_2m"][0] = float("nan")
        value = json.dumps(obj).encode()
        raw = {**self.raw, "open_meteo": value}
        rec = [{**r, "sha256": digest(value), "bytes": len(value)} if r["id"] == "open_meteo" else r for r in self.receipts]
        with self.assertRaisesRegex(ValueError, "NONNUMERIC_SOURCE"):
            assemble_historical(self.request, raw, rec)

    def test_POWER_fill_value_and_shifted_time_standard_rejected(self):
        raw, rec = change(self.raw, self.receipts, "nasa_power", lambda x: x["properties"]["parameter"]["ALLSKY_SFC_LW_DWN"].__setitem__("2022123123", -999.))
        with self.assertRaisesRegex(ValueError, "PROVIDER_FILL"):
            assemble_historical(self.request, raw, rec)
        raw, rec = change(self.raw, self.receipts, "nasa_power", lambda x: x["header"].__setitem__("time_standard", "LST"))
        with self.assertRaisesRegex(ValueError, "TIME_STANDARD"):
            assemble_historical(self.request, raw, rec)

    def test_POWER_source_chain_and_coordinates_cannot_change_silently(self):
        for transform, reason in (
            (lambda x: x["header"].__setitem__("sources", ["GEOS_UNKNOWN"]), "SOURCE_CHAIN_CHANGED"),
            (lambda x: x["geometry"].__setitem__("coordinates", [0, 0, 0]), "WRONG_GEOGRAPHIC_POINT")):
            raw, rec = change(self.raw, self.receipts, "nasa_power", transform)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                assemble_historical(self.request, raw, rec)

    def test_RH_quantization_boxes_not_arbitrary_error_tolerance(self):
        raw, rec = change(self.raw, self.receipts, "open_meteo", lambda x: x["hourly"]["relative_humidity_2m"].__setitem__(0, 98.))
        with self.assertRaisesRegex(ValueError, "QUANTIZATION_INTERVALS_INCOMPATIBLE"):
            assemble_historical(self.request, raw, rec)

    def test_direct_humidity_adapter_keeps_real_year_and_phase_warning(self):
        c = self.result().to_canonical()
        self.assertEqual(c.temporal.calendar_mode, "historical")
        self.assertEqual(set(c.data.index.year), {2023})
        self.assertEqual(c.start.isoformat(), "2023-01-01T00:00:00+01:00")
        self.assertEqual(c.data.attrs["ige_state_sample_offset_minutes_from_row_start"], 60)
        self.assertIn("LIQUID_WATER", c.data.attrs["ige_RH_phase"])
        self.assertNotIn("humidity_ratio_g_kg", c.data)

    def test_result_rejects_shifted_clock_and_unknown_field(self):
        result = self.result()
        for frame in (result.data.iloc[:-1], result.data.assign(unknown=1)):
            with self.assertRaises(ValueError):
                replace(result, data=frame)

    def test_export_rechecks_clock_after_frame_mutation(self):
        result = self.result()
        result.data.index = result.data.index + pd.Timedelta(hours=1)
        with self.assertRaisesRegex(ValueError, "SHIFTED_OR_REORDERED_HOUR"):
            serialize_epw(result)

    def test_full_year_generic_export_readback_preserves_missing_and_period(self):
        result = self.result()
        payload, receipt = serialize_epw(result)
        rows = list(csv.reader(io.StringIO(payload.decode())))
        self.assertEqual(receipt["records"], 8760)
        self.assertEqual(rows[8][:5], ["2023", "1", "1", "1", "60"])
        self.assertEqual(rows[-1][:5], ["2023", "12", "31", "24", "60"])
        self.assertEqual(rows[8][22:24], ["4", "99"])
        self.assertEqual(rows[8][33:35], ["0", "1"])

    def test_leap_and_negative_offset_export_are_not_fixed_Graz_2013_CET(self):
        request = HistoricalRequest(48., 11., 2024, -300, label="Other location")
        raw, rec = fixture(request)
        result = assemble_historical(request, raw, rec)
        payload, receipt = serialize_epw(result)
        rows = list(csv.reader(io.StringIO(payload.decode())))
        self.assertEqual(receipt["records"], 8784)
        self.assertEqual(rows[0][6:9], ["48.0", "11.0", "-5.0"])
        self.assertEqual(rows[4][1], "Yes")
        self.assertEqual(sum(r[1:3] == ["2", "29"] for r in rows[8:]), 24)

    def test_export_rejects_wrong_pressure_unit_even_with_plausible_numbers(self):
        result = self.result()
        bad_fields = {**result.fields, "atmospheric_station_pressure_pa": replace(result.fields["atmospheric_station_pressure_pa"], unit="hPa")}
        with self.assertRaisesRegex(ValueError, "UNIT_OR_OPERATOR_MISMATCH"):
            serialize_epw(replace(result, fields=bad_fields))

    def test_readback_detects_changed_data_and_clock(self):
        result = self.result()
        payload, _ = serialize_epw(result)
        rows = list(csv.reader(io.StringIO(payload.decode())))
        for column, value in ((3, "2"), (9, "101325"), (34, "0")):
            altered = [r.copy() for r in rows]
            altered[8][column] = value
            stream = io.StringIO(); csv.writer(stream, lineterminator="\n").writerows(altered)
            with self.subTest(column=column), self.assertRaises(ValueError):
                validate_epw_bytes(stream.getvalue().encode(), result)

    def test_readback_detects_wrong_coordinates_or_elevation(self):
        result = self.result()
        payload, _ = serialize_epw(result)
        rows = list(csv.reader(io.StringIO(payload.decode())))
        for column, value in ((6, "0"), (7, "0"), (8, "2"), (9, "0")):
            altered = [r.copy() for r in rows]; altered[0][column] = value
            stream = io.StringIO(); csv.writer(stream, lineterminator="\n").writerows(altered)
            with self.subTest(column=column), self.assertRaisesRegex(ValueError, "LOCATION_OR_STANDARD_OFFSET"):
                validate_epw_bytes(stream.getvalue().encode(), result)

    def test_negative_total_precipitation_is_not_hidden_by_zero_liquid_rain(self):
        raw, rec = change(self.raw, self.receipts, "open_meteo", lambda x: x["hourly"]["precipitation"].__setitem__(0, -.01))
        with self.assertRaisesRegex(ValueError, "NEGATIVE_TOTAL_PRECIPITATION"):
            assemble_historical(self.request, raw, rec)

    def test_bundle_hash_and_request_are_checked_and_no_network_replay(self):
        bundle = make_source_bundle(self.request, self.raw, self.receipts)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "source.zip"; path.write_bytes(bundle)
            with self.assertRaisesRegex(ValueError, "SHA_MISMATCH"):
                read_source_bundle(path, "0" * 64, self.request)
            with self.assertRaisesRegex(ValueError, "REQUEST_OR_SCHEMA"):
                read_source_bundle(path, digest(bundle), replace(self.request, year=2024))
            out = Path(d) / "result"
            with patch("epw_climate_analyzer.engine.historical.fetch_original", side_effect=AssertionError("network forbidden")):
                run_historical(self.request, out, source_bundle=path, source_bundle_sha256=digest(bundle))
            receipt = json.loads((out / "manifest.json").read_text())
            self.assertEqual(receipt["weather_provider_requests_this_run"], 0)
            self.assertFalse(receipt["production_ready"])
            old = (out / "climate.epw").read_bytes()
            with self.assertRaises(FileExistsError):
                run_historical(self.request, out, source_bundle=path, source_bundle_sha256=digest(bundle))
            self.assertEqual((out / "climate.epw").read_bytes(), old)

    def test_bundle_unexpected_or_duplicate_members_rejected(self):
        for name in ("../evil.json", "open_meteo.json"):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as z:
                z.writestr("manifest.json", b"{}"); z.writestr("open_meteo.json", b"{}"); z.writestr("nasa_power.json", b"{}")
                z.writestr(name, b"{}");
            raw = stream.getvalue()
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "bundle.zip"; p.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, "UNSAFE_DUPLICATE"):
                    read_source_bundle(p, digest(raw), self.request)

    def test_exclusive_writes_preserve_previous_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.json"
            write_exclusive(path, b"first")
            with self.assertRaises(FileExistsError):
                write_exclusive(path, b"second")
            self.assertEqual(path.read_bytes(), b"first")


if __name__ == "__main__":
    unittest.main()
