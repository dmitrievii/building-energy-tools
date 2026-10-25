"""A1.2 original metadata replay and adversarial, synthetic source contracts.

All weather values/ZIP products generated in these tests are synthetic. No
2025 control temperature, raw wind container or network endpoint is opened.
"""
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sys
import unittest
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "research/ige_cmip6"))
from a12_metadata_zip import MetadataArchive
from a12_prepare_history import prepare, history_sources, dated_rows, wmdr_geometry, verify_metadata_ranges, PROTOCOL_SHA
from a12_exposure_audit import audit
from epw_climate_analyzer.station_admission import physical_identity, admitted_reference, admit_temperature
from epw_climate_analyzer.station_reconstruction import StationReference, decode_meteoswiss_hourly, model_reference_operator, reconstruct_temperature, T, RH, P
from test_p9_3b3_native_heights import xml, WSI

URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/stundenwerte_TU_02928_19510101_20251231_hist.zip"
META = "Metadaten_Geographie_02928.txt"
PRODUCT = "produkt_tu_stunde_synthetic_02928.txt"


def synthetic_zip():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED) as z:
        z.writestr(META, b"synthetic metadata only")
        z.writestr(PRODUCT, b"synthetic observation marker; never requested" * 10)
    return stream.getvalue()


class RangeServer:
    def __init__(self, raw, *, status=206, etags=None):
        self.raw, self.status = raw, status
        self.etags = etags or ['"synthetic-v1"'] * 30
        self.calls = []; self.body_reads = 0

    def __call__(self, request, **kwargs):
        header = request.get_header("Range"); self.calls.append(request)
        match = re.fullmatch(r"bytes=(-?\d+)(?:-(\d+))?", header)
        a = int(match[1]); a = len(self.raw) + a if a < 0 else a
        b = int(match[2]) if match[2] else len(self.raw) - 1
        server = self
        class Response:
            status = server.status
            headers = {"Content-Range": f"bytes {a}-{b}/{len(server.raw)}", "ETag": server.etags[len(server.calls)-1]}
            def geturl(self): return URL
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size):
                server.body_reads += 1
                return server.raw[a:b+1][:size]
        return Response()


class MetadataRangeTests(unittest.TestCase):
    def test_only_metadata_header_and_payload_ranges_read(self):
        server = RangeServer(synthetic_zip()); source = MetadataArchive(URL, server)
        self.assertEqual(source.read_metadata(META), b"synthetic metadata only")
        product = next(r for r in source.entries if r["name"] == PRODUCT)
        central = source.central_start
        for r in source.requests:
            a, b = r["range"]
            self.assertTrue(b < product["offset"] or a >= central)
        self.assertEqual(server.calls[1].get_header("If-match"), '"synthetic-v1"')
        self.assertFalse(source.proof()["observation_product_members_requested"])

    def test_product_filename_rejected_before_any_request(self):
        server = RangeServer(synthetic_zip())
        with self.assertRaisesRegex(ValueError, "ONLY_PARAMETER"):
            MetadataArchive(URL, server).read_metadata(PRODUCT)
        self.assertEqual(len(server.calls), 0)

    def test_ignored_range_200_rejected_before_body_read(self):
        server = RangeServer(synthetic_zip(), status=200)
        with self.assertRaisesRegex(ValueError, "RANGE_REQUIRED"):
            MetadataArchive(URL, server).directory()
        self.assertEqual(server.body_reads, 0)

    def test_missing_or_weak_etag_blocks_before_body(self):
        for etag in (None, 'W/"v1"'):
            server = RangeServer(synthetic_zip(), etags=[etag])
            with self.assertRaisesRegex(ValueError, "STRONG_ETAG"):
                MetadataArchive(URL, server).directory()
            self.assertEqual(server.body_reads, 0)

    def test_archive_version_change_rejected_before_second_body(self):
        server = RangeServer(synthetic_zip(), etags=['"v1"', '"v2"'])
        with self.assertRaisesRegex(ValueError, "ETAG_CHANGED"):
            MetadataArchive(URL, server).directory()
        self.assertEqual(server.body_reads, 1)

    def test_corrupt_metadata_crc_rejected(self):
        raw = bytearray(synthetic_zip()); raw[30+len(META)] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC_LENGTH"):
            MetadataArchive(URL, RangeServer(bytes(raw))).read_metadata(META)

    def test_duplicate_metadata_member_is_ambiguous(self):
        stream = io.BytesIO()
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(stream, "w") as z:
                z.writestr(META, b"a"); z.writestr(META, b"b")
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            MetadataArchive(URL, RangeServer(stream.getvalue())).directory()

    def test_request_budget_is_enforced(self):
        server = RangeServer(synthetic_zip()); source = MetadataArchive(URL, server)
        for _ in range(20): source._range(-22)
        with self.assertRaisesRegex(ValueError, "REQUEST_BUDGET"): source._range(-22)
        self.assertEqual(len(server.calls), 20)

    def test_wrong_host_station_product_or_period_blocked(self):
        for url in (URL.replace("opendata.dwd.de", "example.org"), URL.replace("02928", "00000"),
                URL.replace("air_temperature", "pressure"), URL.replace("20251231", "20241231")):
            with self.assertRaises(ValueError): MetadataArchive(url)


class DatedHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = prepare(); cls.bodies, cls.manifest = history_sources()

    def test_frozen_protocol_is_byte_unchanged_and_no_reselection(self):
        raw = (ROOT/"research/ige_cmip6/a1_1_protocol_20261025.json").read_bytes()
        self.assertEqual(sha256(raw).hexdigest(), PROTOCOL_SHA)
        p = json.loads(raw)
        for case in self.report["cases"]:
            group = next(g for g in p["targets"] if g["target_key"] == case["target_key"])
            self.assertEqual(case["frozen_donor_slots"], [d["key"] for d in group["donors"]])

    def test_actual_geometry_separated_from_two_metre_admission(self):
        for key, height in (("AT:6305", 2.1), ("CH:TIT", 56.), ("DE:01346", 14.4)):
            for row in self.report["station_windows"][key].values():
                self.assertEqual(row["geometry_status"], "DATED_TEMPERATURE_SENSOR_CONFIRMED")
                self.assertEqual(row["geometry"]["AGL_m"], height)
                self.assertFalse(row["strict_2m_compatible"])
                with self.assertRaises(ValueError): admitted_reference(row)

    def test_three_unmatched_austrian_identities_are_not_substituted(self):
        for key in ("AT:3315", "AT:5130", "AT:6430"):
            row = self.report["station_windows"][key]["winter"]
            self.assertIsNone(row["geometry"])
            self.assertIn("NO_UNAMBIGUOUS_OSCAR", row["source_block_reasons"][0])

    def test_DWD_UTC_SYNΟP_origin_does_not_certify_instantaneous_support(self):
        for key, seasons in self.report["station_windows"].items():
            if not key.startswith("DE:"): continue
            for row in seasons.values():
                self.assertEqual(row["geometry_status"], "DATED_TEMPERATURE_SENSOR_CONFIRMED")
                self.assertEqual(row["time_contract"]["operator"], "unknown")
                self.assertIn("DWD_HOURLY_TIME_OPERATOR_UNRESOLVED", row["source_block_reasons"])

    def test_CH_cases_source_ready_but_no_QC_prediction_or_validation_claim(self):
        ready = [r for r in self.report["cases"] if r["strict_T2m_metadata_ready"]]
        self.assertEqual({r["target_key"] for r in ready}, {"CH:BAS", "CH:ALT"})
        self.assertEqual(len(ready), 8)
        for row in ready:
            self.assertFalse(row["hourly_QC_and_coverage_verified"])
            self.assertFalse(row["predictions_created_or_sealed"])
            self.assertFalse(row["primary_validation_admitted"])
            if row["target_key"] == "CH:ALT":
                self.assertEqual(row["metadata_admitted_donors"], ["CH:GES", "CH:ENG"])
                self.assertEqual(row["blocked_donor_slots"], ["CH:TIT"])

    def test_swiss_first_reference_requires_previous_hour_geometry(self):
        row = self.report["station_windows"]["CH:BAS"]["winter"]
        self.assertEqual(row["actual_nominal_sample_support_first_UTC"], "2025-01-09T23:10:00+00:00")
        self.assertEqual(row["geometry"]["parser_geometry_check_bounds_UTC"][0], "2025-01-09T23:00:00+00:00")

    def test_null_group_is_not_shared_alias_and_repair_is_journaled(self):
        self.assertNotEqual(physical_identity("AT", "5000"), physical_identity("AT", "6430"))
        self.assertEqual(physical_identity("AT", "3202", group_id=56), "AT_GROUP:56")
        ledger = self.report["identity_adjustments"]
        self.assertEqual({r["station_key"] for r in ledger}, {"AT:5000", "AT:6430"})
        self.assertTrue(all(r["old"] == "AT_GROUP:None" for r in ledger))

    def test_original_HTTP_proofs_do_not_touch_product_member_ranges(self):
        for name, body in self.bodies.items():
            if name.endswith("range_proof.json"): self.assertEqual(verify_metadata_ranges(json.loads(body), self.bodies)[0], 14)
        self.assertEqual(self.manifest["range_requests"], 112)
        self.assertEqual(self.manifest["range_body_bytes"], 24554)

    def test_tampered_history_packet_rejected(self):
        raw = bytearray((ROOT/"research/ige_cmip6/a12_history_sources_20261025.zip").read_bytes()); raw[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "PACKET_HASH"): history_sources(bytes(raw))

    def test_forged_proof_request_into_product_is_rejected(self):
        proof = json.loads(self.bodies["DE_02928__range_proof.json"])
        product = next(m for m in proof["members"] if m["name"].startswith("produkt_"))
        r = proof["requests"][-1]; r["range"] = [product["offset"], product["offset"]+r["bytes"]-1]
        with self.assertRaisesRegex(ValueError, "TOUCHES_NON_METADATA"): verify_metadata_ranges(proof, self.bodies)

    def test_DWD_inclusive_date_end_and_no_current_snapshot_backfill(self):
        raw = b"Stations_id;von;bis\n1;20250110;20250116\n"
        first, last = pd.Timestamp("2025-01-10Z".replace("10Z", "10T00:00Z")), pd.Timestamp("2025-01-16T23:00Z")
        self.assertEqual(len(dated_rows(raw, "1", "von", "bis", first, last)), 1)
        self.assertEqual(dated_rows(raw, "1", "von", "bis", last+pd.Timedelta(hours=1), last+pd.Timedelta(hours=2)), [])

    def test_partial_epoch_overlaps_do_not_hide_behind_a_full_span_row(self):
        raw = b"Stations_id;von;bis\n1;20250101;20251231\n1;20250112;20250113\n"
        with self.assertRaisesRegex(ValueError, "CROSSES_REQUEST"):
            dated_rows(raw, "1", "von", "bis", pd.Timestamp("2025-01-10T00:00Z"), pd.Timestamp("2025-01-16T23:00Z"))

    def test_WMDR_uses_two_metre_channel_not_separate_five_cm(self):
        root = ET.fromstring(xml(code=224, height=37.8, agl=2))
        other = ET.fromstring(xml(code=224, height=35.85, agl=.05))
        facility = root.find('.//{http://def.wmo.int/wmdr/2017}ObservingFacility')
        facility.append(other.find('.//{http://www.opengis.net/om/2.0}OM_Observation'))
        row = wmdr_geometry(ET.tostring(root), WSI, "CH", pd.Timestamp("2025-01-10T00:00Z"), pd.Timestamp("2025-01-16T23:00Z"))
        self.assertEqual(row["AGL_m"], 2.); self.assertEqual(row["geospatial_z_as_reported_m"], 37.8)

    def test_WMDR_partly_overlapping_second_two_metre_sensor_blocks(self):
        root = ET.fromstring(xml(code=224, height=37.8, agl=2))
        other = ET.fromstring(xml(code=224, height=38., agl=2, start="2025-01-12T00:00Z", end="2025-01-14T00:00Z"))
        root.find('.//{http://def.wmo.int/wmdr/2017}ObservingFacility').append(other.find('.//{http://www.opengis.net/om/2.0}OM_Observation'))
        with self.assertRaisesRegex(ValueError, "PARTIAL_OVERLAP"):
            wmdr_geometry(ET.tostring(root), WSI, "CH", pd.Timestamp("2025-01-10T00:00Z"), pd.Timestamp("2025-01-16T23:00Z"))


def synthetic_batch(row, *, sid=None, date="10.01.2025", values=(1., 2.)):
    source = row["frozen_station"]
    station = StationReference(**{k: source[k] for k in StationReference.__dataclass_fields__})
    raw = "station_abbr;reference_timestamp;tre200h0;ure200h0;prestah0\n"
    raw += "".join(f"{sid or station.station_id};{date} {i:02}:00;{v};80;980\n" for i, v in enumerate(values))
    return decode_meteoswiss_hourly(raw.encode(), station)


class TemperatureBindingTests(unittest.TestCase):
    def setUp(self): self.row = deepcopy(prepare()["station_windows"]["CH:BAS"]["winter"])

    def test_binding_copies_T_only_and_preserves_raw_batch(self):
        batch = synthetic_batch(self.row); raw_data = batch.data.copy(deep=True)
        result = admit_temperature(batch, self.row)
        pd.testing.assert_frame_equal(batch.data, raw_data)
        self.assertFalse(batch.station.historical_geometry_verified)
        self.assertFalse(batch.fields[T]["sensor_height_history_verified"])
        self.assertTrue(result.station.historical_geometry_verified)
        self.assertEqual(result.values.attrs["sensor_AGL_m"], 2.)
        self.assertFalse(result.values.attrs["RH_or_pressure_height_certified"])
        self.assertIsInstance(result.values, pd.Series)
        result.values.iloc[0] = -55
        self.assertEqual(batch.data[T].iloc[0], 1.)
        self.assertEqual(batch.fields[RH]["RH_phase"], "SOURCE_PHASE_UNVERIFIED")
        self.assertFalse(batch.fields[P]["sensor_height_history_verified"])

    def test_outside_window_and_mismatched_operator_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "OUTSIDE_DATED"):
            admit_temperature(synthetic_batch(self.row, date="09.01.2025"), self.row)
        batch = synthetic_batch(self.row); batch.fields[T]["time_operator"] = "published_nominal_node"
        with self.assertRaisesRegex(ValueError, "DEFINITION_MISMATCH"): admit_temperature(batch, self.row)

    def test_wrong_station_and_falsely_claimed_two_metre_record_blocked(self):
        other = prepare()["station_windows"]["CH:ALT"]["winter"]
        with self.assertRaisesRegex(ValueError, "CROSS_STATION"): admit_temperature(synthetic_batch(other), self.row)
        for height in (2.1, 14.4, 56.):
            row = deepcopy(self.row); row["geometry"]["AGL_m"] = height
            with self.assertRaisesRegex(ValueError, "ACTUAL_DATED_2M"): admitted_reference(row)

    def test_admitted_two_donor_route_preserves_residual_math_without_TIT(self):
        rows = prepare()["station_windows"]
        target = admitted_reference(rows["CH:ALT"]["winter"])
        clock = pd.date_range("2025-01-09T23:00Z", periods=3, freq="h")
        nodes = pd.Series([0., 12., 24.], index=clock); nodes.attrs["unit"] = "°C"
        baseline = model_reference_operator(nodes, clock[1:], "mean_six_10min_nominal_nodes")
        donors, observations, backgrounds, masks = [], {}, {}, {}
        for key in ("CH:GES", "CH:ENG"):
            row = rows[key]["winter"]
            bound = admit_temperature(synthetic_batch(row, values=tuple(baseline+2)), row)
            donors.append(bound.station); observations[key] = bound.values
            backgrounds[key] = baseline.copy(); masks[key] = bound.quality_accepted
        result, ledger = reconstruct_temperature(target, baseline, donors, observations, backgrounds, masks)
        np.testing.assert_allclose(result, baseline+2, atol=1e-12)
        self.assertTrue(ledger["candidate_admitted"].all())
        self.assertNotIn("weight__CH:TIT", ledger)
        self.assertFalse(result.attrs["target_observations_used"])
        self.assertFalse(result.attrs["independent_accuracy_qualified"])


class ExposureAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.audit = audit()

    def test_both_CH_controls_have_confirmed_container_exposure_not_T_fit_claim(self):
        for key in ("CH:BAS", "CH:ALT"):
            row = self.audit["targets"][key]
            self.assertEqual(row["source_manifest_row"]["coverage"]["2025"]["usable_hours"], 8760)
            self.assertFalse(row["raw_byte_unseen_claim_allowed"])
            self.assertFalse(row["numeric_temperature_2025_extraction_demonstrated"])
            self.assertFalse(row["temperature_2025_prediction_errors_or_fitting_demonstrated"])

    def test_exposure_absence_is_not_global_independence_certificate(self):
        self.assertFalse(self.audit["strict_blindness_certified"])
        self.assertFalse(self.audit["independent_accuracy_qualified"])
        self.assertTrue(all(not r["absence_is_global_proof"] for r in self.audit["targets"].values()))
        self.assertFalse(self.audit["new_2025_station_measurements_opened"])
        self.assertFalse(self.audit["IV1_2022_values_opened"])

    def test_other_variable_prior_use_is_not_relabelled_T_leakage(self):
        self.assertTrue(self.audit["raw_bytes_exposed_does_not_by_itself_prove_training_or_score_leakage"])
        self.assertFalse(self.audit["targets"]["CH:BAS"]["numeric_2025_values_used_by_P8_2E_parser"])
        self.assertTrue(self.audit["targets"]["DE:01443"]["other_variable_prior_use"]["prior_pressure_availability_is_not_proof_of_2025_temperature_training"])
        self.assertFalse(self.audit["prior_P9_2C_2025"]["overlap_with_A1_control_station_identity"])


if __name__ == "__main__": unittest.main()
