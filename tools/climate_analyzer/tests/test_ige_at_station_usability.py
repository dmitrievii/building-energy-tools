"""Source availability diagnostics and byte-preserving catalogue reuse."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

from epw_climate_analyzer import geosphere as geo
from epw_climate_analyzer import geosphere_station_year as source
from epw_climate_analyzer.engine.station_epw_admission import assess_station_year
from epw_climate_analyzer.point_interpolation import donor_from_station_year
from epw_climate_analyzer.station_coverage import station_core_coverage
from test_ige_h1_station_year import complete_inputs, replay_fixture


class CoreCoverageTests(unittest.TestCase):
    def report(self, data):
        r, location, frame, fields = data
        return assess_station_year(r, location, frame, fields, source_id="SYNTHETIC_TEST").report

    def test_station_can_supply_s1_core_while_full_station_epw_is_blocked(self):
        r, location, frame, fields = complete_inputs()
        frame = frame.drop(columns=["direct_normal_radiation_wh_m2"])
        row = station_core_coverage(self.report((r, location, frame, fields)))
        self.assertTrue(row["core_sources_admitted"])
        self.assertFalse(row["station_only_EPW_admitted"])
        self.assertEqual(row["blocker_types"], [])
        self.assertEqual((row["T_admitted_hours"], row["RH_admitted_hours"], row["p_admitted_hours"]), (8760,)*3)

    def test_complete_station_epw_is_reported_separately(self):
        row = station_core_coverage(self.report(complete_inputs()))
        self.assertTrue(row["core_sources_admitted"])
        self.assertTrue(row["station_only_EPW_admitted"])

    def test_missing_values_qc_and_definitions_remain_distinct(self):
        r, location, frame, fields = complete_inputs()
        t, rh, p = "dry_bulb_temperature_c", "relative_humidity_pct", "atmospheric_station_pressure_pa"
        frame.loc[frame.index[:2], rh] = np.nan
        frame["quality__T"] = 10
        frame.loc[frame.index[4], "quality__T"] = 0
        fields[t] = replace(fields[t], origin="measured", quality_column="quality__T",
                            accepted_quality_codes=(10,), quality_policy_id="SYNTHETIC_QC10")
        fields[p] = replace(fields[p], quantity_definition="sea_level_pressure")
        report = self.report((r, location, frame, fields))
        before = deepcopy(report)
        row = station_core_coverage(report)
        self.assertEqual(row["blocker_types"], ["REJECTED_QC_T", "MISSING_OBSERVATIONS_RH", "DEFINITION_NOT_ADMITTED_p"])
        self.assertEqual((row["T_admitted_hours"], row["RH_admitted_hours"], row["p_admitted_hours"]), (8759,8758,0))
        self.assertEqual(report, before)

    def test_entirely_absent_measurements_and_transport_failures_are_not_partial_gaps(self):
        data = complete_inputs();data[2]["atmospheric_station_pressure_pa"] = np.nan
        report = self.report(data);report["global_blockers"].append("SOURCE_REQUEST_FAILED: synthetic timeout")
        row = station_core_coverage(report)
        self.assertEqual(row["blocker_types"], ["NO_MEASUREMENTS_p", "SOURCE_ACQUISITION_FAILED"])
        self.assertFalse(row["core_sources_admitted"])


class OriginalMetadataReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request, cls.packet = replay_fixture()
        cls.digest = sha256(cls.packet).hexdigest()
        _, cls.captured = source.read_sources(cls.packet, cls.digest)
        cls.metadata_body = cls.captured[0][2]

    def setUp(self):
        guard = patch("socket.socket.connect", side_effect=AssertionError("SOURCE_TEST_OFFLINE"))
        guard.start();self.addCleanup(guard.stop)

    def acquire(self, metadata_body):
        def retained_measurements(**kwargs):
            for url, query, body in self.captured[1:]:
                kwargs["response_capture"](url, query, body)
        with patch.object(geo, "fetch_metadata", side_effect=AssertionError("CATALOGUE_ALREADY_ACQUIRED")), \
                patch.object(geo, "fetch_station_provider_frame", side_effect=retained_measurements):
            return source.run_station_year(self.request, original_metadata_body=metadata_body)

    def test_reused_original_bytes_replay_with_same_values_qc_and_admission(self):
        live = self.acquire(self.metadata_body)
        original = source.run_station_year(self.request, source_packet=self.packet, expected_sha256=self.digest)
        replay = source.run_station_year(self.request, source_packet=live.files["sources.zip"],
                                         expected_sha256=sha256(live.files["sources.zip"]).hexdigest())
        self.assertEqual(live.report["metadata_provider_responses_this_run"], 0)
        self.assertEqual(live.report["weather_provider_responses_this_run"], 1)
        self.assertTrue(live.report["original_metadata_reused_for_live_request"])
        _, bodies = source.read_sources(live.files["sources.zip"], sha256(live.files["sources.zip"]).hexdigest())
        self.assertEqual(bodies[0][2], self.metadata_body)
        for result in (live, replay):
            self.assertEqual(result.report["fields"], original.report["fields"])
            self.assertEqual(result.report["global_blockers"], original.report["global_blockers"])
            self.assertEqual(result.files["hourly_states.csv.gz"], original.files["hourly_states.csv.gz"])
            self.assertEqual(donor_from_station_year(result).blockers, donor_from_station_year(original).blockers)

    def test_reuse_never_bypasses_changed_pressure_definition(self):
        metadata = json.loads(self.metadata_body)
        next(p for p in metadata["parameters"] if p["name"] == "p")["description"] = "Reduzierter Luftdruck"
        result = self.acquire(json.dumps(metadata).encode())
        row = station_core_coverage(result.report)
        self.assertEqual(row["p_admitted_hours"], 0)
        self.assertIn("DEFINITION_NOT_ADMITTED_p", row["blocker_types"])
        self.assertIn("H1_CORE_NOT_ADMITTED_atmospheric_station_pressure_pa", donor_from_station_year(result).blockers)

    def test_replay_rejects_metadata_override_and_live_requires_original_bytes(self):
        with self.assertRaisesRegex(ValueError, "LIVE_ONLY"):
            source.run_station_year(self.request, source_packet=self.packet, expected_sha256=self.digest,
                                    original_metadata_body=self.metadata_body)
        for body in (b"", "{}", b"[]"):
            with self.subTest(body=body), patch.object(geo, "fetch_metadata") as fetch:
                with self.assertRaisesRegex(ValueError, "METADATA"):
                    source.run_station_year(self.request, original_metadata_body=body)
                fetch.assert_not_called()


class OriginalStationDevelopmentReplayTests(unittest.TestCase):
    def test_real_2021_station_point_replays_and_2025_missing_qc_stays_blocked(self):
        research = Path(__file__).resolve().parents[3] / "research/ige_cmip6"
        with patch.object(sys, "path", [str(research), *sys.path]), \
                patch("socket.socket.connect", side_effect=AssertionError("AT_PILOT_REPLAY_OFFLINE")), \
                patch("socket.socket.connect_ex", side_effect=AssertionError("AT_PILOT_REPLAY_OFFLINE")):
            from at_station_usability_replay import replay_at_station_pilot
            summary = replay_at_station_pilot()
        self.assertEqual(summary["hours"], 8760)
        self.assertEqual(summary["selected_donors"], ["16412", "16413", "16511", "16411"])
        self.assertTrue(summary["real_station_core_sources"])
        self.assertEqual(summary["negative_2025"]["eligible_stations"], 0)
        self.assertFalse(summary["new_independent_accuracy_validation"])
        self.assertFalse(summary["future_climate_or_multiyear_reference_qualified"])

    def test_real_point_is_a_future_base_but_grid_reference_is_not_its_local_climate(self):
        from epw_climate_analyzer.engine.point_interpolation import PointRequest
        from epw_climate_analyzer.point_interpolation import run_point_product
        from epw_climate_analyzer.future_selected import base_from_point, background_reference
        research = Path(__file__).resolve().parents[3] / "research/ige_cmip6"
        c = json.loads((research / "at_station_usability_20261102.json").read_bytes())
        with patch("socket.socket.connect", side_effect=AssertionError("AT_POINT_BASE_OFFLINE")):
            point = run_point_product(PointRequest(**c["request"]),
                input_packet=(research/c["inputs"]["file"]).read_bytes(), expected_sha256=c["inputs"]["sha256"],
                include_background=True, background_packet=(research/c["background"]["file"]).read_bytes(),
                background_sha256=c["background"]["sha256"])
            base = base_from_point(point)
            self.assertEqual(base.sha256, c["output_EPW_sha256"])
            self.assertEqual(base.location.elevation_m, 375.)
            with self.assertRaisesRegex(ValueError, "CANNOT_REPLACE_STATION_OR_POINT_CLIMATOLOGY"):
                background_reference(base, (2002,2014))


if __name__ == "__main__":
    unittest.main()
