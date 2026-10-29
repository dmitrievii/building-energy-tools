"""Annual admission: calendars, source meaning, QC, complete refusals and export."""
from dataclasses import replace
from hashlib import sha256
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import pandas as pd

from epw_climate_analyzer.climate_model import ClimateLocation
from epw_climate_analyzer.engine.epw import EPW_FIELDS
from epw_climate_analyzer.engine.station_epw_admission import (StationYearRequest,
    StationField, assess_station_year, QC_POLICY)
from epw_climate_analyzer import geosphere as geo
from epw_climate_analyzer import geosphere_station_year as source


def complete_inputs(year=2023, offset=60):
    request = StationYearRequest("12345", year, offset, "Synthetic fixture")
    location = ClimateLocation(47.5, 14.2, 400., "Synthetic fixture", "", "Austria", "12345")
    values = dict(dry_bulb_temperature_c=10., dew_point_temperature_c=5., relative_humidity_pct=71.0757,
                  atmospheric_station_pressure_pa=96000., horizontal_infrared_radiation_intensity_wh_m2=300.,
                  global_horizontal_radiation_wh_m2=0., direct_normal_radiation_wh_m2=0.,
                  diffuse_horizontal_radiation_wh_m2=0., wind_direction_deg=180., wind_speed_m_s=2.,
                  total_sky_cover_tenths=5., liquid_precipitation_depth_mm=0.)
    frame = pd.DataFrame(values, index=request.utc_ends)
    fields = {name: StationField(unit, name, operator, "Synthetic test geometry", "Synthetic test fixture",
                origin="synthetic_test", quantity_definition=("absolute_station_pressure" if "pressure" in name
                else "liquid_precipitation" if name == "liquid_precipitation_depth_mm" else "synthetic"))
              for name, (_, unit, operator) in EPW_FIELDS.items()}
    return request, location, frame, fields


def metadata_fixture():
    parameters = []
    for provider, binding in source.BINDINGS.items():
        parameters.extend([{"name": provider, "unit": binding[1], "description": binding[5]},
                           {"name": provider + "_flag", "unit": "code", "code_list_ref": "q21"}])
    parameters.append({"name": "pred", "unit": "hPa", "description": "Reduzierter Luftdruck"})
    return {"frequency": "PT1H", "start_time": "1880-04-01T00:00:00+00:00",
        "parameters": parameters,
        "stations": [{"id": 12345, "name": "Synthetic fixture", "lat": 47.5, "lon": 14.2,
                      "altitude": 400., "type": "INDIVIDUAL", "valid_from": "2000-01-01T00:00:00+00:00",
                      "valid_to": "2100-12-31T00:00:00+00:00"}],
        "code_lists": {"q21": [{"key": None, "value": "undefiniert"}, {"key": 0, "value": "ungeprüfte Daten"}]
                               + [{"key": k, "value": v} for k, v in source.QC_LABELS.items()]}}


def replay_fixture(year=2023, wrong_id=False, description_change=False):
    request = StationYearRequest("12345", year, 60, "Synthetic fixture")
    metadata = metadata_fixture()
    if description_change:
        next(p for p in metadata["parameters"] if p["name"] == "p")["description"] = "Reduzierter Luftdruck"
    params = source._parameters(metadata)
    query = geo.build_data_query("12345", request.utc_ends[0], request.utc_ends[-1], params, resource_id=source.RESOURCE)
    times = request.utc_ends.strftime("%Y-%m-%dT%H:%M:%S%z").tolist()
    data = {}
    for p in params:
        v = 10 if p.endswith("_flag") else 10 if p == "tl" else 70 if p == "rf" else 960 if p == "p" else 2 if p == "ff" else 180 if p == "dd" else 0
        data[p] = {"data": [v] * len(times)}
    payload = {"timestamps": times, "features": [{"type": "Feature",
        "properties": {"station": "99999" if wrong_id else "12345", "parameters": data}}]}
    captured = [(geo.resource_spec(source.RESOURCE).metadata_endpoint, {}, json.dumps(metadata).encode()),
                (geo.resource_spec(source.RESOURCE).endpoint, query, json.dumps(payload).encode())]
    packet = source._source_packet(request, captured)
    return request, packet


class AnnualAdmissionTests(unittest.TestCase):
    def assess(self, data=None):
        r, l, f, fields = data or complete_inputs()
        return assess_station_year(r, l, f, fields, source_id="SYNTHETIC_TEST")

    def test_complete_year_and_leap_year_have_actual_calendar_and_readback(self):
        for year, n in ((2023, 8760), (2024, 8784), (1880, 8784)):
            with self.subTest(year=year):
                a = self.assess(complete_inputs(year))
                self.assertEqual(a.report["status"], "EPW_ADMITTED_RESEARCH")
                self.assertEqual(a.report["expected_hours"], n)
                rows = a.epw.decode().splitlines()
                self.assertEqual(len(rows), n + 8)
                self.assertIn("STATION YEAR RESEARCH", rows[0])
                self.assertNotIn("IGE_ERA5_DERIVED", rows[0])
                self.assertEqual(rows[0].split(",")[5], "999999")
                self.assertEqual(rows[8].split(",")[:5], [str(year), "1", "1", "1", "60"])
                self.assertEqual(rows[-1].split(",")[:5], [str(year), "12", "31", "24", "60"])
                self.assertFalse(a.report["production_ready"])
                self.assertFalse(a.report["weather_screen"]["EnergyPlus_simulation_executed"])

    def test_every_missing_field_and_gap_is_reported_without_export_or_fill(self):
        r, l, f, fields = complete_inputs()
        f.loc[f.index[4], "dry_bulb_temperature_c"] = np.nan
        f = f.drop(columns=["direct_normal_radiation_wh_m2", "diffuse_horizontal_radiation_wh_m2"])
        a = self.assess((r, l, f, fields))
        self.assertIsNone(a.epw)
        counts = {x["field"]: x["missing_value_hours"] for x in a.report["fields"]}
        self.assertEqual(counts["dry_bulb_temperature_c"], 1)
        self.assertEqual(counts["direct_normal_radiation_wh_m2"], 8760)
        self.assertEqual(counts["diffuse_horizontal_radiation_wh_m2"], 8760)
        self.assertEqual(a.report["engine_missing_values_filled"], 0)
        self.assertTrue(np.isnan(a.hourly["dry_bulb_temperature_c"].iloc[4]))
        gap = a.gaps[(a.gaps.field == "dry_bulb_temperature_c") & (a.gaps.reason == "MISSING_VALUE")].iloc[0]
        self.assertEqual(gap.first_interval_start_utc, r.utc_starts[4].isoformat())

    def test_reviewed_provider_codes_are_distinct_from_old_qc10_validation(self):
        r, l, f, fields = complete_inputs()
        name = "dry_bulb_temperature_c"
        f["quality_flag__tl"] = 10
        f.loc[f.index[:8], "quality_flag__tl"] = [0, np.nan, 11, 12, 20, 21, 22, 3.5]
        fields[name] = replace(fields[name], origin="measured", quality_column="quality_flag__tl",
            accepted_quality_codes=(10, 11, 12, 20, 21, 22), quality_policy_id=source.QC_PROFILE)
        a = self.assess((r, l, f, fields))
        row = next(x for x in a.report["fields"] if x["field"] == name)
        self.assertEqual(row["rejected_qc_hours"], 2)
        self.assertEqual(row["missing_qc_hours"], 1)
        self.assertEqual(row["usable_for_epw_hours"], 8757)
        self.assertEqual(row["quality_histogram"]["3.5"], 1)
        self.assertEqual(a.report["qc_policy"]["id"], QC_POLICY)
        self.assertFalse(a.report["qc_policy"]["previous_V2_QC10_validation_policy_changed"])

    def test_other_provider_uses_its_own_declared_qc_codes(self):
        r, l, f, fields = complete_inputs()
        name = "dry_bulb_temperature_c"
        f["quality_flag__TT_TU"] = 3
        f.loc[f.index[0], "quality_flag__TT_TU"] = 10
        fields[name] = replace(fields[name], origin="measured", quality_column="quality_flag__TT_TU",
            accepted_quality_codes=(3,), quality_policy_id="SYNTHETIC_DWD_QN3_PROFILE")
        a = self.assess((r, l, f, fields))
        row = next(x for x in a.report["fields"] if x["field"] == name)
        self.assertEqual(row["usable_for_epw_hours"], 8759)
        self.assertEqual(row["rejected_qc_hours"], 1)

    def test_reduced_pressure_mean_states_and_unknown_liquid_phase_are_blocked(self):
        r, l, f, fields = complete_inputs()
        fields["atmospheric_station_pressure_pa"] = replace(fields["atmospheric_station_pressure_pa"], quantity_definition="sea_level_pressure")
        fields["wind_speed_m_s"] = replace(fields["wind_speed_m_s"], operator="mean_over_preceding_hour")
        fields["liquid_precipitation_depth_mm"] = replace(fields["liquid_precipitation_depth_mm"], quantity_definition="total_precipitation")
        a = self.assess((r, l, f, fields))
        self.assertIsNone(a.epw)
        reasons = set(a.gaps.reason)
        self.assertTrue({"ABSOLUTE_STATION_PRESSURE_REQUIRED", "TIME_OPERATOR_NOT_ADMITTED", "LIQUID_PHASE_NOT_ESTABLISHED"} <= reasons)

    def test_out_of_bounds_and_inconsistent_solar_components_do_not_get_repaired(self):
        r, l, f, fields = complete_inputs()
        f.loc[f.index[1], "relative_humidity_pct"] = 101.
        a = self.assess((r, l, f, fields))
        self.assertIsNone(a.epw)
        self.assertEqual(a.hourly.relative_humidity_pct.iloc[1], 101.)
        f.loc[f.index[1], "relative_humidity_pct"] = 70.
        f.loc[f.index[5], "diffuse_horizontal_radiation_wh_m2"] = 10.
        a = self.assess((r, l, f, fields))
        self.assertIsNone(a.epw)
        self.assertTrue(any("DHI_EXCEEDS_GHI" in x for x in a.report["global_blockers"]))

    def test_duplicate_hour_is_ambiguous_and_outside_grid_is_not_ignored(self):
        r, l, f, fields = complete_inputs()
        f = pd.concat([f, f.iloc[[4]], f.iloc[[0]].set_axis([r.utc_ends[-1] + pd.Timedelta(hours=1)])])
        a = self.assess((r, l, f, fields))
        self.assertEqual(a.report["duplicate_source_rows"], 2)
        self.assertEqual(a.report["unexpected_source_rows"], 1)
        self.assertEqual(a.report["fields"][0]["missing_value_hours"], 1)
        self.assertIsNone(a.epw)

    def test_source_type_and_location_metadata_are_not_assumed(self):
        r, l, f, fields = complete_inputs()
        a = assess_station_year(r, replace(l, elevation_m=None), f, fields,
            source_id="SYNTHETIC_TEST", source_metadata={"station_type": "COMBINED"})
        self.assertIn("EPW_LOCATION_ELEVATION_UNAVAILABLE", a.report["global_blockers"])
        self.assertIn("COMBINED_SERIES_NOT_ADMITTED_AS_ONE_FIXED_SITE", a.report["global_blockers"])
        self.assertIsNone(a.epw)

    def test_utc_boundaries_are_derived_from_fixed_standard_clock(self):
        self.assertEqual(StationYearRequest("CH:BAS", 2023).station_id, "CH:BAS")
        for offset in (-300, 0, 60, 540):
            r = StationYearRequest("12345", 2023, offset)
            self.assertEqual(r.utc_ends[0], r.local_starts[0].tz_convert("UTC") + pd.Timedelta(hours=1))
            self.assertEqual(len(r.utc_starts), 8760)
        with self.assertRaisesRegex(ValueError, "WHOLE_HOUR"):
            StationYearRequest("12345", 2023, 330)


class GeoSphereReplayTests(unittest.TestCase):
    def test_original_Graz_2023_packet_replays_exact_disclosed_coverage_without_network(self):
        root = Path(__file__).resolve().parents[3] / "research/ige_cmip6"
        contract = json.loads((root / "h1_graz16412_2023_source_contract_20261028.json").read_bytes())
        packet = (root / contract["source_packet"]).read_bytes()
        self.assertEqual(sha256(packet).hexdigest(), contract["source_packet_sha256"])
        with patch("socket.socket.connect", side_effect=AssertionError("H1_ORIGINAL_REPLAY_OFFLINE")):
            p = source.run_station_year(StationYearRequest(**contract["request"]), source_packet=packet,
                                       expected_sha256=contract["source_packet_sha256"])
        self.assertEqual(p.report["status"], contract["expected_status"])
        self.assertEqual(p.report["source_rows"], contract["expected_source_rows"])
        counts = {r["field"]: r["numeric_hours"] for r in p.report["fields"]}
        for field, count in contract["expected_numeric_hours"].items():
            self.assertEqual(counts[field], count, field)
        self.assertFalse(p.report["new_independent_validation"])
        self.assertNotIn("climate.epw", p.files)

    def test_changed_unit_is_retained_as_native_data_and_never_converted_as_old_unit(self):
        metadata = metadata_fixture()
        next(p for p in metadata["parameters"] if p["name"] == "p")["unit"] = "Pa"
        frame = pd.DataFrame({"p": [96000.], "p_flag": [10]}, index=pd.date_range("2023-01-01", periods=1, tz="UTC"))
        canonical, fields = source._canonical(frame, metadata)
        self.assertNotIn("atmospheric_station_pressure_pa", canonical)
        self.assertIn("PROVIDER_UNIT_CHANGED", fields["atmospheric_station_pressure_pa"].definition_error)
        self.assertEqual(frame.p.iloc[0], 96000.)

    def test_incomplete_current_or_future_year_does_not_request_measurements(self):
        metadata = metadata_fixture()
        def fetch_metadata(**kwargs):
            kwargs["response_capture"](geo.resource_spec(source.RESOURCE).metadata_endpoint, {}, json.dumps(metadata).encode())
            return metadata
        with patch.object(geo, "fetch_metadata", side_effect=fetch_metadata), \
                patch.object(geo, "fetch_station_provider_frame") as fetch:
            product = source.run_station_year(StationYearRequest("12345", 2098, 60, "Synthetic fixture"))
        fetch.assert_not_called()
        self.assertFalse(product.report["transport_complete"])
        self.assertTrue(any("YEAR_IS_NOT_COMPLETE" in e for e in product.report["global_blockers"]))
        self.assertNotIn("climate.epw", product.files)

    def test_capture_retains_exact_original_bytes_while_preserving_the_old_decoder(self):
        body = b'  {"ok": true, "numbers": [1.00, 2.50]}\n'
        class Response:
            status_code = 200
            headers = {}
            closed = False
            def raise_for_status(self): pass
            def iter_content(self, chunk_size): return iter([body[:7], body[7:]])
            def close(self): self.closed = True
        response, captures = Response(), []
        url = geo.resource_spec(source.RESOURCE).metadata_endpoint
        with patch.object(geo.requests, "get", return_value=response):
            decoded = geo._bounded_get_json(url, response_capture=lambda u, q, b: captures.append((u, q, b)))
        self.assertEqual(decoded, {"ok": True, "numbers": [1., 2.5]})
        self.assertEqual(captures, [(url, {}, body)])
        self.assertTrue(response.closed)

    def test_live_key_value_codebook_shape_is_parsed_without_losing_codes(self):
        metadata = metadata_fixture()
        codebook = geo.quality_flag_codebook(metadata, "tl")
        self.assertEqual(codebook[10], "automatisch geprüft")
        self.assertEqual(codebook[22], "manuell geprüft (original)")
        self.assertEqual(codebook[0], "ungeprüfte Daten")
        self.assertNotIn(None, codebook)

    def test_hourly_replay_retains_all_data_and_explains_no_epw(self):
        request, packet = replay_fixture()
        with patch("socket.socket.connect", side_effect=AssertionError("NO_NETWORK")):
            p = source.run_station_year(request, source_packet=packet, expected_sha256=sha256(packet).hexdigest())
        self.assertNotIn("climate.epw", p.files)
        self.assertEqual(p.report["source_rows"], 8760)
        self.assertTrue(p.report["offline_replay"])
        self.assertEqual(p.report["weather_provider_responses_this_run"], 0)
        rows = {r["field"]: r for r in p.report["fields"]}
        self.assertEqual(rows["dry_bulb_temperature_c"]["usable_for_epw_hours"], 8760)
        self.assertEqual(rows["wind_speed_m_s"]["reviewed_in_bounds_hours"], 8760)
        self.assertIn("TIME_OPERATOR_NOT_ADMITTED", rows["wind_speed_m_s"]["definition_errors"])
        self.assertEqual(rows["direct_normal_radiation_wh_m2"]["numeric_hours"], 0)
        self.assertEqual(rows["liquid_precipitation_depth_mm"]["numeric_hours"], 0)
        self.assertIn("total_precipitation_depth_mm", [x["field"] for x in p.report["additional_source_fields"]])
        self.assertEqual(p.files["sources.zip"], packet)
        with zipfile.ZipFile(io.BytesIO(p.archive)) as archive:
            self.assertNotIn("climate.epw", archive.namelist())

    def test_p_cannot_be_replaced_by_pred_or_a_changed_pressure_description(self):
        request, packet = replay_fixture(description_change=True)
        p = source.run_station_year(request, source_packet=packet, expected_sha256=sha256(packet).hexdigest())
        pressure = next(r for r in p.report["fields"] if r["field"] == "atmospheric_station_pressure_pa")
        self.assertIn("PROVIDER_DEFINITION_CHANGED", pressure["definition_errors"])
        self.assertEqual(pressure["usable_for_epw_hours"], 0)
        self.assertNotIn("pred", source._parameters(metadata_fixture()))

    def test_replay_refuses_other_year_other_station_and_tampering(self):
        request, packet = replay_fixture()
        digest = sha256(packet).hexdigest()
        with self.assertRaisesRegex(ValueError, "HASH"):
            source.run_station_year(request, source_packet=packet + b"x", expected_sha256=digest)
        with self.assertRaisesRegex(ValueError, "REQUEST_MISMATCH"):
            source.run_station_year(replace(request, year=2024), source_packet=packet, expected_sha256=digest)
        wrong_request, wrong_packet = replay_fixture(wrong_id=True)
        with self.assertRaisesRegex(ValueError, "WRONG_STATION"):
            source.run_station_year(wrong_request, source_packet=wrong_packet, expected_sha256=sha256(wrong_packet).hexdigest())


if __name__ == "__main__": unittest.main()
