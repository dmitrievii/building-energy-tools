"""Adversarial source separation and deterministic metadata cohort tests."""
from dataclasses import replace
import io
import json
import socket
import unittest
from unittest.mock import patch
import zipfile

import pandas as pd

from v2_cohort import R, COUNTRIES, discovery, json_bytes, tie_key
from v2_metadata import (MetadataCollector, metadata_url, validate_body, normalized_name,
    lookup_candidates, choose_targets, donor_candidates, MAX_TOTAL)
from v2_verify_metadata import records_equal
from v1_time_admission import operator
from epw_climate_analyzer.station_reconstruction import StationReference

URL = "https://oscar.wmo.int/surface/rest/api/wmd/download/0-20000-0-00001"


class Response(io.BytesIO):
    status = 200
    def __init__(self, body, url=URL):
        super().__init__(body); self.url = url; self.headers = {"Content-Type": "application/xml"}
    def geturl(self): return self.url


def collector(opener):
    with patch("v2_metadata.old_metadata", return_value=({}, {"source_receipts": []})):
        return MetadataCollector(opener=opener)


def ref(country, sid, lat=47., lon=14., height=300., identity=None):
    return StationReference(country, sid, sid, lat, lon, height, "0" * 64, identity or country + ":" + sid)


class MetadataEndpointTests(unittest.TestCase):
    def test_metadata_routes_are_explicit(self):
        self.assertTrue(metadata_url(URL))
        self.assertTrue(metadata_url("https://oscar.wmo.int/surface/rest/api/stations/approvedStations/names?q=WIEN&page=1&pageSize=100"))
        self.assertTrue(metadata_url("https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/meta_data/Meta_Daten_zehn_min_tu_00071.zip"))

    def test_temperature_QC_and_model_routes_are_forbidden(self):
        urls = ["https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h?parameters=tl_flag&station_ids=123",
            "https://archive-api.open-meteo.com/v1/archive?hourly=temperature_2m",
            "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/biv/ogd-smn_biv_h_historical_2010-2019.csv",
            "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/historical/10minutenwerte_TU_00071_20100101_20201231_hist.zip"]
        for url in urls:
            with self.subTest(url=url): self.assertFalse(metadata_url(url))

    def test_query_redirect_userinfo_and_other_host_cannot_smuggle_source(self):
        for url in [URL + "?parameters=tl", URL.replace("https:", "http:"), URL.replace("oscar.wmo.int", "oscar.wmo.int.example.org"), URL.replace("oscar.wmo.int", "user@oscar.wmo.int"), URL + "#fragment"]:
            with self.subTest(url=url): self.assertFalse(metadata_url(url))

    def test_forbidden_route_is_rejected_before_network(self):
        c = collector(lambda *args, **kw: self.fail("network called"))
        with self.assertRaisesRegex(ValueError, "FORBIDDEN"):
            c.get("https://archive-api.open-meteo.com/v1/archive")
        self.assertEqual(c.attempts, 0)

    def test_attempt_budget_stops_before_network(self):
        c = collector(lambda *args, **kw: self.fail("network called")); c.attempts = 240
        with self.assertRaisesRegex(ValueError, "BUDGET"): c.get(URL)
        self.assertEqual(c.attempts, 240)

    def test_byte_budget_stops_before_network(self):
        c = collector(lambda *args, **kw: self.fail("network called")); c.bytes = MAX_TOTAL
        with self.assertRaisesRegex(ValueError, "BUDGET"): c.get(URL)

    def test_same_URL_is_not_queried_twice(self):
        calls = []
        c = collector(lambda request, **kw: (calls.append(request.full_url) or Response(b"<WIGOSMetadataRecord/>")))
        self.assertEqual(c.get(URL), c.get(URL)); self.assertEqual(c.attempts, 1); self.assertEqual(len(calls), 1)

    def test_schema_failure_retains_body_and_does_not_retry(self):
        calls = []
        c = collector(lambda request, **kw: (calls.append(request.full_url) or Response(b"<weather/>")))
        for _ in range(2):
            with self.assertRaises(ValueError): c.get(URL)
        self.assertEqual(len(calls), 1)
        row = c.receipts[URL]
        self.assertEqual(row["status"], "SOURCE_BLOCKED")
        self.assertEqual(c.bodies[row["member"]], b"<weather/>")

    def test_truncated_HTTP_body_is_not_called_an_original(self):
        def opener(request, **kw):
            response = Response(b"<WIGOSMetadataRecord/>")
            response.headers["Content-Length"] = "999"
            return response
        c = collector(opener)
        with self.assertRaisesRegex(ValueError, "TRUNCATED"): c.get(URL)
        self.assertEqual(c.receipts[URL]["status"], "SOURCE_BLOCKED")
        self.assertTrue(c.bodies)

    def test_observation_product_cannot_hide_inside_metadata_ZIP(self):
        body = io.BytesIO()
        with zipfile.ZipFile(body, "w") as archive: archive.writestr("produkt_zehn_min_tu_00071.txt", "values")
        url = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/meta_data/Meta_Daten_zehn_min_tu_00071.zip"
        with self.assertRaisesRegex(ValueError, "ONLY_DWD_METADATA"): validate_body(url, body.getvalue())


class IdentityAndCohortTests(unittest.TestCase):
    def test_published_JSON_arrays_equal_dataclass_tuples_but_changed_physics_fails(self):
        live = {"time": {"offsets": (-50, -40, -30, -20, -10, 0), "weights": (5/12, 7/12)}}
        saved = json.loads(json.dumps(live))
        self.assertNotEqual(live, saved)
        self.assertTrue(records_equal(live, saved))
        saved["time"]["weights"][0] += 1e-12
        self.assertFalse(records_equal(live, saved))

    def test_umlaut_and_geographic_stops_do_not_require_a_weather_lookup(self):
        self.assertEqual(normalized_name("Güssing"), ["GUESSING"])
        rows = [{"text": "ST.VEIT/GLAN (0-20000-0-11111)"}, {"text": "VEITBERG (0-20000-0-22222)"}]
        result = lookup_candidates("St. Veit an der Glan", json.dumps(rows).encode())
        self.assertEqual(result[0]["WSI"], "0-20000-0-11111")

    def test_lookup_has_fixed_WSI_cap_and_deterministic_ties(self):
        rows = [{"text": "TEST (0-20000-0-" + str(i) + ")"} for i in range(10)]
        a = lookup_candidates("TEST", json.dumps(rows).encode())
        b = lookup_candidates("TEST", json.dumps(rows[::-1]).encode())
        self.assertEqual(a, b); self.assertEqual(len(a), 3)

    def test_no_name_overlap_does_not_select_a_default_WSI(self):
        self.assertEqual(lookup_candidates("Güssing", b'[{"text":"INNSBRUCK (0-20000-0-11120)"}]'), [])

    def test_QC10_contract_does_not_rewrite_old_V1_QC22_operator(self):
        old = operator("AT", "klima-v2-1h", "tl", pd.Timestamp("2019-01-10", tz="UTC"), pd.Timestamp("2019-10-16", tz="UTC"))
        self.assertIn("22_PRIMARY", old.source_QC_stratum)
        registration = json.loads((R / "v1_registration_20261026.json").read_text())
        self.assertEqual(registration["QC"]["AT"]["primary"], [22])

    def test_selection_is_independent_of_input_order(self):
        frame = [ref(c, str(i), height=float(i)) for c in COUNTRIES for i in range(9)]
        records = {s.key: {"temperature_source_eligible": True} for s in frame}
        a = choose_targets(frame, records); b = choose_targets(frame[::-1], records)
        self.assertEqual([s.key for s in a[0]], [s.key for s in b[0]])
        self.assertEqual(len(a[0]), 18); self.assertEqual(a[2], [])

    def test_insufficient_dated_metadata_is_retained_not_replenished(self):
        frame = [ref(c, str(i), height=float(i)) for c in COUNTRIES for i in range(9)]
        records = {s.key: {"temperature_source_eligible": not (s.country == "AT" and int(s.station_id) > 3)} for s in frame}
        selected, strata, blocks = choose_targets(frame, records)
        self.assertEqual(sum(s.country == "AT" for s in selected), 4)
        self.assertTrue(any(b.startswith("AT:") for b in blocks))

    def test_two_alias_targets_cannot_be_counted_as_two_stations(self):
        frame = [ref("AT", "a", identity="same"), ref("AT", "b", identity="same")]
        with self.assertRaisesRegex(ValueError, "IDENTITY_ALIAS"): choose_targets(frame, {})

    def test_all_target_aliases_are_excluded_from_donors(self):
        target = ref("AT", "target", identity="target_group")
        another = ref("AT", "second", lat=47.2, identity="second_group")
        pool = [ref("AT", "target_alias", lat=47.1, identity="target_group"), ref("AT", "second_alias", lat=47.3, identity="second_group"), ref("AT", "ok", lon=14.2)]
        chosen = donor_candidates(target, pool, [target, another])
        self.assertEqual([s.station_id for _, s in chosen], ["ok"])

    def test_candidate_limits_remain_first8_AT_first4_DE_CH(self):
        for country, n in [("AT", 8), ("DE", 4), ("CH", 4)]:
            target = ref(country, "target")
            pool = [ref(country, str(i), lon=14.1 + .03 * i) for i in range(12)]
            self.assertEqual(len(donor_candidates(target, pool, [target])), n)


class FrozenFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("metadata frame used network")):
            cls.frame, cls.exposure = discovery()

    def test_saved_frame_replays_exactly(self):
        self.assertEqual((R / "v2_metadata_frame_20261027.json").read_bytes(), json_bytes(self.frame))

    def test_saved_exposure_registry_replays_exactly(self):
        self.assertEqual((R / "v2_exposure_audit_20261027.json").read_bytes(), json_bytes(self.exposure))

    def test_discovery_cap_and_physical_identity_census(self):
        rows = self.frame["metadata_candidates"]
        self.assertEqual(len(rows), 54)
        self.assertEqual(len({r["identity_group"] for r in rows}), 54)
        self.assertTrue(all(sum(r["country"] == c for r in rows) == 18 for c in COUNTRIES))

    def test_excluded_old_targets_and_containers_are_not_relabelled_new(self):
        chosen = {r["country"] + ":" + r["station_id"] for r in self.frame["metadata_candidates"]}
        self.assertTrue(chosen.isdisjoint({"AT:5609", "AT:20123", "DE:01270", "DE:00232", "CH:STG", "CH:SCU", "CH:BAS", "CH:ALT", "CH:MOA"}))
        self.assertTrue(all(not self.exposure["evidence_by_catalog_station"][k] for k in chosen))

    def test_absence_of_a_match_is_not_global_blindness_proof(self):
        self.assertFalse(self.exposure["global_raw_byte_blindness_certified"])
        self.assertFalse(self.exposure["new_measurements_opened"])
        self.assertEqual(self.frame["new_weather_requests_authorized"], 0)

    def test_metadata_frame_is_not_the_final_target_cohort(self):
        self.assertFalse(self.frame["targets_selected"])
        self.assertTrue(self.frame["relative_height_strata_applied_after_dated_metadata_admission"])


if __name__ == "__main__": unittest.main()
