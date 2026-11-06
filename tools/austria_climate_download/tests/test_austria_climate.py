"""Source contracts, negative cases, catalogue geography and restart behavior."""
import copy
import csv
import datetime as dt
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import austria_climate as at

RAW_META = (ROOT / "catalog/metadata.original.json").read_bytes()
META = at.load_metadata(RAW_META)
RAW_OBS = (ROOT / "tests/fixtures/sample_20250101.original.json").read_bytes()
SMOKE = json.loads((ROOT / "config_smoke.json").read_bytes())


def plan(config=None, metadata=None):
    return at.build_plan(RAW_META if metadata is None else at.canonical(metadata), config or SMOKE)


class CatalogueTests(unittest.TestCase):
    def test_record_identity_and_site_classes(self):
        rows = at.station_rows(META, at.digest(RAW_META))
        self.assertEqual(len(rows), 823)
        self.assertEqual(sum(r["station_type"] == "INDIVIDUAL" for r in rows), 616)
        self.assertEqual(len({r["station_id"] for r in rows}), len(rows))

    def test_generated_geojson_has_longitude_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            at.make_catalog(RAW_META, tmp)
            obj = json.loads((Path(tmp) / "stations.geojson").read_bytes())
            feature = next(f for f in obj["features"] if f["id"] == "16413")
            self.assertEqual(feature["geometry"]["coordinates"], [15.41028, 47.04611])
            self.assertEqual((Path(tmp) / "metadata.original.json").read_bytes(), RAW_META)
            self.assertTrue((Path(tmp) / "snapshots" / (at.digest(RAW_META) + ".json")).is_file())

    def test_exact_site_is_zero_distance_and_combined_not_a_donor(self):
        rows = at.nearest_stations(META, 47.04611, 15.41028, when=at.parse_time("2025-01-01"))
        self.assertEqual(rows[0]["station_id"], "16413")
        self.assertEqual(rows[0]["distance_km"], 0)
        self.assertTrue(all(r["station_type"] == "INDIVIDUAL" for r in rows))

    def test_reference_city_distance(self):
        self.assertAlmostEqual(at.haversine_km(48.2082, 16.3738, 47.0707, 15.4395), 144.7, delta=1)

    def test_closed_sites_excluded_by_date_not_just_active_flag(self):
        rows = at.nearest_stations(META, 47.079723, 15.447778, when=at.parse_time("2025-01-01"), limit=1000)
        self.assertNotIn("16402", {r["station_id"] for r in rows})
        old = at.nearest_stations(META, 47.079723, 15.447778, when=at.parse_time("1980-01-01"), limit=1000)
        self.assertIn("16402", {r["station_id"] for r in old})

    def test_group_exclusion_for_future_holdout(self):
        rows = at.nearest_stations(META, 47.08, 15.448, when=at.parse_time("2025-01-01"), exclude_group="30", limit=1000)
        self.assertTrue(all(r["group_id"] != 30 for r in rows))

    def test_radius_and_height_filters(self):
        rows = at.nearest_stations(META, 47.04611, 15.41028, when=at.parse_time("2025-01-01"), radius_km=.001,
                                   elevation_m=356.5, max_height_difference_m=0)
        self.assertEqual([r["station_id"] for r in rows], ["16413"])
        self.assertEqual(rows[0]["station_minus_target_elevation_m"], 0)

    def test_invalid_coordinate_and_missing_height(self):
        for kw in ({"lat": 91, "lon": 15}, {"lat": float("nan"), "lon": 15},
                   {"lat": 47, "lon": 15, "max_height_difference_m": 100}):
            with self.subTest(kw=kw), self.assertRaises(at.SourceError):
                at.nearest_stations(META, when=at.parse_time("2025-01-01"), **kw)

    def test_duplicate_station_or_wrong_cadence_rejected(self):
        meta = copy.deepcopy(META)
        meta["stations"].append(meta["stations"][0])
        with self.assertRaises(at.SourceError):
            at.load_metadata(at.canonical(meta))
        meta = copy.deepcopy(META)
        meta["frequency"] = "PT10M"
        with self.assertRaises(at.SourceError):
            at.load_metadata(at.canonical(meta))


class PlannerTests(unittest.TestCase):
    def test_flags_are_added_automatically(self):
        p = plan({**SMOKE, "parameters": ["tl", "p"]})
        self.assertEqual(p["parameters"], ["p", "p_flag", "tl", "tl_flag"])

    def test_unknown_fields_fail_without_guessing(self):
        for config in ({**SMOKE, "parameters": ["not_real"]}, {**SMOKE, "station_ids": [999999]},
                       {**SMOKE, "staton_ids": [16413]}):
            with self.subTest(config=config), self.assertRaises(at.SourceError):
                plan(config)

    def test_composite_id_needs_explicit_kind(self):
        with self.assertRaises(at.SourceError):
            plan({**SMOKE, "station_ids": [30]})
        self.assertEqual(plan({**SMOKE, "station_ids": [30], "station_kind": "combined"})["station_ids"], ["30"])

    def test_leap_year_and_value_ceiling(self):
        p = plan({**SMOKE, "start": "2024-01-01", "end": "2024-12-31", "chunk_months": 12})
        self.assertEqual(sum(j["expected_hours"] * len(j["station_ids"]) for j in p["jobs"]), 8784 * 2)
        self.assertTrue(all(j["requested_values"] <= 800000 for j in p["jobs"]))

    def test_no_overlap_or_utc_dst_holes_between_blocks(self):
        p = plan({**SMOKE, "start": "2024-01-01", "end": "2024-12-31", "chunk_months": 3})
        jobs = [j for j in p["jobs"] if "16413" in j["station_ids"]]
        self.assertEqual(len(jobs), 4)
        for left, right in zip(jobs, jobs[1:]):
            self.assertEqual(at.parse_time(left["end"]) + at.HOUR, at.parse_time(right["start"]))

    def test_site_validity_clips_hours_and_all_null_not_inferred(self):
        meta = copy.deepcopy(META)
        station = next(s for s in meta["stations"] if s["id"] == 16413)
        station["valid_from"] = "2025-01-01T05:20:00Z"
        station["valid_to"] = "2025-01-01T21:30:00Z"
        p = plan({**SMOKE, "station_ids": [16413]}, meta)
        self.assertEqual(p["jobs"][0]["expected_hours"], 16)
        self.assertEqual(p["jobs"][0]["start"], "2025-01-01T06:00:00Z")

    def test_future_and_ambiguous_time_rejected(self):
        with self.assertRaises(at.SourceError):
            plan({**SMOKE, "end": "2100-12-31"})
        with self.assertRaises(at.SourceError):
            at.parse_time("2025-01-01T00:00")

    def test_plan_id_is_reproducible_and_tampering_rejected(self):
        p = plan()
        self.assertEqual(p["plan_id"], plan()["plan_id"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            at.write_json(path, p)
            self.assertEqual(at.load_plan(path)["plan_id"], p["plan_id"])
            p["parameters"].append("fake")
            at.write_json(path, p)
            with self.assertRaises(at.SourceError):
                at.load_plan(path)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan()
        self.job = self.plan["jobs"][0]

    def test_real_fixture_preserves_missing_station_and_pressure_units(self):
        stamps, stations = at.decode_response(RAW_OBS, self.job, META)
        self.assertEqual(len(stamps), 24)
        self.assertEqual(at.coverage(stations["16412"], 24)["tl"]["non_null_hours"], 0)
        self.assertEqual(at.coverage(stations["16413"], 24)["tl"]["non_null_hours"], 24)
        self.assertEqual(stations["16413"]["p"]["unit"], "hPa")
        self.assertIn("pred", stations["16413"])

    def test_qc_zero_and_null_not_silently_removed(self):
        obj = json.loads(RAW_OBS)
        station = next(f for f in obj["features"] if str(f["properties"]["station"]) == "16413")
        station["properties"]["parameters"]["tl_flag"]["data"][0] = 0
        _, stations = at.decode_response(at.canonical(obj), self.job, META)
        self.assertEqual(stations["16413"]["tl"]["data"][0], -4.4)
        counts = at.coverage(stations["16413"], 24)["tl"]["qc_counts_on_non_null"]
        self.assertEqual(counts, {"0": 1, "10": 23})

    def test_truncated_or_duplicate_axis_rejected(self):
        for transform in (lambda x: x.pop(), lambda x: x.__setitem__(1, x[0])):
            obj = json.loads(RAW_OBS)
            transform(obj["timestamps"])
            with self.assertRaises(at.SourceError):
                at.decode_response(at.canonical(obj), self.job, META)

    def test_changed_units_missing_fields_and_other_station_rejected(self):
        for kind in ("unit", "field", "station", "array"):
            obj = json.loads(RAW_OBS)
            props = obj["features"][0]["properties"]
            if kind == "unit": props["parameters"]["p"]["unit"] = "Pa"
            elif kind == "field": del props["parameters"]["tl_flag"]
            elif kind == "station": props["station"] = "999999"
            else: props["parameters"]["tl"]["data"].pop()
            with self.subTest(kind=kind), self.assertRaises(at.SourceError):
                at.decode_response(at.canonical(obj), self.job, META)

    def test_source_csv_resume_and_partial_year_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = at.run_root(tmp, self.plan)
            at.save_job(root, self.job, RAW_OBS, META)
            self.assertTrue(at.receipt_is_complete(root, self.job))
            target, report = at.export_station(self.plan, tmp, "16413", 2025)
            with gzip.open(target, "rt", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 24)
            self.assertEqual(float(rows[0]["tl"]), -4.4)
            self.assertFalse(report["full_calendar_axis"])
            self.assertFalse(report["epw_admission_assessed"])
            self.assertEqual(report["non_null_by_parameter"]["tl"], 24)
            _, empty_report = at.export_station(self.plan, tmp, "16412", 2025, plain=True)
            self.assertEqual(empty_report["non_null_by_parameter"]["tl"], 0)

    def test_corruption_prevents_resume_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = at.run_root(tmp, self.plan)
            receipt = at.save_job(root, self.job, RAW_OBS, META)
            path = root / receipt["artifacts"][1]["path"]
            path.write_bytes(b"broken")
            self.assertFalse(at.receipt_is_complete(root, self.job))
            with self.assertRaises(at.SourceError):
                at.export_station(self.plan, tmp, "16412", 2025)

    def test_missing_artifact_in_receipt_is_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = at.run_root(tmp, self.plan)
            receipt = at.save_job(root, self.job, RAW_OBS, META)
            receipt["artifacts"].pop()
            at.write_json(root / "receipts" / (self.job["job_id"] + ".json"), receipt)
            self.assertFalse(at.receipt_is_complete(root, self.job))

    def test_restart_skips_valid_requests(self):
        class FakeClient:
            calls = 0
            def get(self, url):
                self.calls += 1
                return RAW_OBS
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(at.download(self.plan, tmp, client)["all_transfers_complete"])
            self.assertEqual(at.download(self.plan, tmp, client)["attempted_this_invocation"], 0)
            self.assertEqual(client.calls, 1)

    def test_failed_download_remains_failed_and_releases_lock(self):
        class BadClient:
            def get(self, url):
                raise TimeoutError("fixture outage")
        with tempfile.TemporaryDirectory() as tmp:
            result = at.download(self.plan, tmp, BadClient())
            self.assertEqual(result["remaining_jobs"], 1)
            self.assertTrue(result["failures_this_invocation"])
            self.assertFalse((at.run_root(tmp, self.plan) / ".download.lock").exists())


class TransportTests(unittest.TestCase):
    def test_rate_limit_and_retry_after_are_observed(self):
        now = [1000.0]
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, n): return b"{}"
        def opener(request, timeout):
            calls.append(now[0])
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 429, "limited", {"Retry-After": "40"}, io.BytesIO())
            return Response()
        def sleep(seconds): now[0] += seconds
        client = at.Client(opener=opener, clock=lambda: now[0], sleep=sleep)
        self.assertEqual(client.get(at.BASE), b"{}")
        self.assertEqual(client.get(at.BASE), b"{}")
        self.assertEqual(calls, [1000, 1040, 1056])

    def test_no_official_host_or_rate_floor_bypass(self):
        with self.assertRaises(at.SourceError): at.Client(interval=0)
        with self.assertRaises(at.SourceError): at.Client().get("https://example.com/weather")


if __name__ == "__main__":
    unittest.main()
