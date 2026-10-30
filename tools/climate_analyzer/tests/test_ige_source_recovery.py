"""Timeout recovery must preserve original data and exact scientific admission."""
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
import io
import zipfile
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

from epw_climate_analyzer.engine.source_cache import OriginalSourceCache
from epw_climate_analyzer.engine.f1_sources import (SignalRequest, acquire_nex,
    admit_nex_packet, matching_saved_nex_packet, download)
from epw_climate_analyzer.engine.model_sources import bounded_zip
from epw_climate_analyzer.future_selected import base_from_engine, run_selected_future, background_reference
from epw_climate_analyzer.engine_application import run_historical_product, pilot_historical_request

ROOT = Path(__file__).resolve().parents[3]


class SourceCacheTests(unittest.TestCase):
    def test_exact_key_hash_expiry_and_size_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = OriginalSourceCache(folder, entry_limit=100)
            cache.put("point A", b"original", {"retrieved_at": "original time"})
            self.assertEqual(cache.get("point A"), (b"original", {"retrieved_at": "original time"}))
            self.assertIsNone(cache.get("point B"))
            cache.put("large", b"a"*101)
            self.assertIsNone(cache.get("large"))
            path = cache._path("point A")
            path.write_bytes(path.read_bytes()[:-1]+b"X")
            self.assertIsNone(cache.get("point A"))
            cache.put("point A", b"original")
            with patch("epw_climate_analyzer.engine.source_cache.time.time", return_value=0):
                self.assertIsNone(cache.get("point A"))
            expired = OriginalSourceCache(folder, max_age=-1)
            self.assertIsNone(expired.get("point A"))

    def test_disk_budget_removes_old_checkpoints_without_affecting_current_body(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = OriginalSourceCache(folder, entry_limit=6000, max_disk_bytes=12000)
            for i in range(4): cache.put(str(i), b"x"*5000)
            self.assertLessEqual(sum(p.stat().st_size for p in Path(folder).glob("*.cache")), 12000)
            self.assertEqual(cache.get("3")[0], b"x"*5000)

    def test_unwritable_cache_is_a_miss_and_does_not_block_live_work(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/"file"; file.write_bytes(b"not a directory")
            cache = OriginalSourceCache(file)
            cache.put("key", b"original")
            self.assertIsNone(cache.get("key"))


class NASARecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = SignalRequest(47.0707, 15.4395)
        cls.packet = matching_saved_nex_packet(cls.request)
        cls.files = bounded_zip(cls.packet, member_limit=640)
        cls.receipts = json.loads(cls.files["manifest.json"])["receipts"]
        cls.original = {r["url"]: cls.files[r["file"]] for r in cls.receipts}

    def test_exact_retained_request_reuses_only_identical_point_scenario_and_periods(self):
        self.assertIsNotNone(self.packet)
        for change in ({"latitude":48.}, {"scenario":"ssp585"}, {"future_window":(2050,2069)},
                       {"reference_window":(2003,2014)}):
            self.assertIsNone(matching_saved_nex_packet(replace(self.request, **change)))

    def test_partial_timeout_resumes_without_reacquiring_successful_catalogues_or_points(self):
        calls = Counter(); succeeded = set()
        failing = next(r["url"] for r in self.receipts if r.get("file") == "historical_2002_huss.nc")
        interrupted = True
        def fetch(url):
            calls[url] += 1
            if interrupted and url == failing:
                raise RuntimeError("F1_SOURCE_UNAVAILABLE simulated read timeout")
            succeeded.add(url)
            return self.original[url]
        with tempfile.TemporaryDirectory() as folder:
            cache = OriginalSourceCache(folder)
            with self.assertRaisesRegex(RuntimeError,"F1_SOURCE_UNAVAILABLE"):
                acquire_nex(self.request, fetch=fetch, cache=cache)
            kept = set(succeeded)
            self.assertGreater(len(kept), 18)
            self.assertLess(len(kept), len(self.original))
            interrupted = False
            packet = acquire_nex(self.request, fetch=fetch, cache=cache)
            actual, evidence = admit_nex_packet(packet, sha256(packet).hexdigest(), self.request)
            expected, _ = admit_nex_packet(self.packet, sha256(self.packet).hexdigest(), self.request)
            self.assertEqual(actual, expected)
            self.assertEqual(evidence["original_responses"], 315)
            for url in kept: self.assertEqual(calls[url], 1, url)
            self.assertEqual(calls[failing], 2)
            saved_files = bounded_zip(packet, member_limit=640)
            for name, body in self.files.items():
                if name != "manifest.json": self.assertEqual(saved_files[name], body)

    def test_cached_source_for_another_location_cannot_pass_point_admission(self):
        request = replace(self.request, latitude=48.)
        # Even a checksum-valid response under a wrong URL is still decoded
        # and rejected by the scientific nearest-cell guard.
        with tempfile.TemporaryDirectory() as folder:
            cache = OriginalSourceCache(folder)
            def wrong_fetch(url):
                canonical = url.replace("latitude=48.000000", "latitude=47.070700")
                return self.original[canonical]
            with self.assertRaisesRegex(ValueError,"NOT_NEAREST_NEX_GRID_CENTER"):
                acquire_nex(request, fetch=wrong_fetch, cache=cache)

    def test_timeout_before_nasa_admission_does_not_acquire_multiyear_background(self):
        base = base_from_engine(run_historical_product(pilot_historical_request()))
        with patch("epw_climate_analyzer.future_selected.matching_saved_nex_packet", return_value=None), \
             patch("epw_climate_analyzer.future_selected.acquire_nex", side_effect=RuntimeError("F1_SOURCE_UNAVAILABLE test")), \
             patch("epw_climate_analyzer.future_selected.background_reference") as reference:
            with self.assertRaisesRegex(RuntimeError, "F1_SOURCE_UNAVAILABLE"):
                run_selected_future(base, self.request, reference_mode="BACKGROUND_REFERENCE")
            reference.assert_not_called()

    def test_connection_retries_but_permanent_or_invalid_responses_do_not_retry(self):
        good = MagicMock(); good.__enter__.return_value = good
        good.status = 200; good.read.return_value = b"original"
        with patch("epw_climate_analyzer.engine.f1_sources.urlopen", side_effect=[URLError("timeout"), good]) as fetch, \
             patch("epw_climate_analyzer.engine.f1_sources.time.sleep"):
            self.assertEqual(download("https://example.invalid/source"), b"original")
            self.assertEqual(fetch.call_count, 2)
        with patch("epw_climate_analyzer.engine.f1_sources.urlopen", side_effect=HTTPError("url",404,"missing",{},None)) as fetch:
            with self.assertRaises(HTTPError): download("https://example.invalid/source")
            fetch.assert_called_once()
        good.read.return_value = b""
        with patch("epw_climate_analyzer.engine.f1_sources.urlopen", return_value=good) as fetch:
            with self.assertRaisesRegex(ValueError,"SIZE_OR_STATUS"): download("https://example.invalid/source")
            fetch.assert_called_once()


class BackgroundRecoveryTests(unittest.TestCase):
    def test_completed_annual_reference_sources_survive_a_later_year_timeout(self):
        base = base_from_engine(run_historical_product(pilot_historical_request()))
        source = ROOT/"research/ige_cmip6/bm1_reference_sources_2002_2014_20261025.zip"
        originals = {}
        with zipfile.ZipFile(source) as archive:
            for year in (2002, 2003):
                with zipfile.ZipFile(io.BytesIO(archive.read(f"Graz_{year}_original_sources.zip"))) as inner:
                    manifest = json.loads(inner.read("manifest.json"))
                    for receipt in manifest["sources"]:
                        originals[receipt["url"]] = (inner.read(receipt["id"]+".json"), receipt)
        calls = Counter(); stopped = True
        def fetch(key, spec):
            calls[spec["url"]] += 1
            if stopped and "2003" in spec["url"]:
                raise TimeoutError("later reference year unavailable")
            return originals[spec["url"]]
        with tempfile.TemporaryDirectory() as folder, \
             patch("epw_climate_analyzer.future_selected.OriginalSourceCache", return_value=OriginalSourceCache(folder)), \
             patch("epw_climate_analyzer.future_selected.fetch_original", side_effect=fetch):
            with self.assertRaises(TimeoutError): background_reference(base, (2002, 2003))
            completed = [url for url in calls if "2002" in url and "2003" not in url]
            self.assertEqual(len(completed), 2)
            stopped = False
            _, evidence, packet = background_reference(base, (2002, 2003))
            self.assertEqual(len(evidence["years"]), 2)
            for url in completed: self.assertEqual(calls[url], 1)
            replayed, proof, _ = background_reference(base, (2002, 2003), packet=packet,
                                                      expected_sha256=sha256(packet).hexdigest())
            self.assertEqual(proof["reference_source_packet_sha256"], sha256(packet).hexdigest())
            self.assertEqual(len(replayed), 12)


if __name__ == "__main__": unittest.main()
