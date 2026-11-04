"""F1 station-point reference: synthetic integration, real source refusal."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from epw_climate_analyzer.engine.f1_base import admit_base, climatology
from epw_climate_analyzer.engine.f1_sources import SignalRequest
from epw_climate_analyzer.engine.model_sources import bounded_zip
from epw_climate_analyzer.engine.point_interpolation import PointRequest
from epw_climate_analyzer.future_point_reference import (POINT_MODE, POINT_GAP_MODE, STATION_KIND, _admit_year, point_reference,
                                                        point_reference_spec)
from epw_climate_analyzer.future_selected import base_from_point, replay_selected_future, run_selected_future
from epw_climate_analyzer.geosphere_station_year import _zip
from epw_climate_analyzer.point_interpolation import _acquire_stations, run_point_product
from test_ige_f1_selected_future import signals, synthetic_base

ROOT = Path(__file__).resolve().parents[3] / "research/ige_cmip6"
MODULE = "epw_climate_analyzer.future_point_reference"
WINDOW = (2005, 2014)


def retained_point():
    c = json.loads((ROOT / "at_station_usability_20261102.json").read_bytes())
    return run_point_product(PointRequest(**c["request"]), input_packet=(ROOT/c["inputs"]["file"]).read_bytes(),
        expected_sha256=c["inputs"]["sha256"], include_background=True,
        background_packet=(ROOT/c["background"]["file"]).read_bytes(), background_sha256=c["background"]["sha256"])


class PointReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real = retained_point()
        cls.real = base_from_point(real)
        cls.template = base_from_point(real).identity["source_provenance"]
        # Explicit synthetic control with a genuine provenance shape, not real reference data.
        cls.template = {**cls.template, "point_request": {**cls.template["point_request"], "elevation_m": 400.}}
        cls.base = admit_base(synthetic_base(2021).epw, calendar_kind="ACTUAL_YEAR",
            pressure_contract=cls.real.pressure_contract, water_curve=cls.real.water_curve,
            source_kind=cls.real.identity["source_kind"], provenance=cls.template)
        cls.products = {}
        cls.annual = []
        original, _ = point_reference_spec(cls.base, WINDOW)
        for y in range(WINDOW[0], WINDOW[1]+1):
            req = replace(original, year=y)
            b = synthetic_base(y, humidity=60.+(y-WINDOW[0]))
            report = {"status": "POINT_YEAR_COMPLETE_RESEARCH", "EPW_status": "ADMITTED_MIXED_SOURCE_RESEARCH",
                "donor_admission": cls.template["donor_admission"], "field_sources": cls.template["field_sources"],
                "background_source_geometry": cls.template["background_geometry"]}
            product = SimpleNamespace(request=req, report=report,
                files={"climate.epw": b.epw, "report.json": b"synthetic",
                       "inputs.zip": f"station {y}".encode(), "background.sources.zip": f"grid {y}".encode()})
            cls.products[y] = product
            cls.annual.append(base_from_point(product))

    def setUp(self):
        p = patch("socket.socket.connect", side_effect=AssertionError("OFFLINE TEST"))
        p.start()
        self.addCleanup(p.stop)

    def annual_product(self, req, **kwargs):
        product = self.products[req.year]
        if "input_packet" in kwargs:
            self.assertEqual(kwargs["input_packet"], product.files["inputs.zip"])
            self.assertEqual(kwargs["background_packet"], product.files["background.sources.zip"])
        else:
            self.assertEqual(set(kwargs["required_station_ids"]), {"16412","16413","16511","16411"})
        return product

    def test_complete_reference_uses_every_year_and_replays_f1(self):
        r = SignalRequest(*self.base.identity["signal_site"], WINDOW, (2040, 2059))
        mock_signals = (signals(), {"grid": [47.125, 15.375], "source_packet_sha256": "0"*64})
        with patch(MODULE+".OriginalSourceCache") as cache, patch(MODULE+".run_point_product",
                side_effect=self.annual_product) as annual, patch(
                "epw_climate_analyzer.future_selected.admit_nex_packet", return_value=mock_signals):
            cache.return_value.get.return_value = None
            result = run_selected_future(self.base, r, reference_mode=POINT_MODE,
                nex_packet=b"synthetic model", allow_liquid_precipitation_proxy=True)
            self.assertEqual(annual.call_count, 10)
            self.assertEqual(cache.return_value.put.call_count, 10)
            ref = json.loads(result.files["local_reference_climatology.json"])
            for month, fields in climatology(self.annual).items():
                for key, value in fields.items():
                    self.assertAlmostEqual(ref[str(month)][key], value, places=11)
            self.assertEqual(len(result.dataset.data), 8760)
            replayed = replay_selected_future(result.archive, sha256(result.archive).hexdigest())
            self.assertEqual(result.files["climate.epw"], replayed.files["climate.epw"])
            self.assertEqual(annual.call_count, 20)
            self.assertTrue(all("input_packet" in c.kwargs for c in annual.call_args_list[10:]))
            self.assertEqual(cache.call_count, 1)
            files = dict(result.files)
            name = "source_packets/local_reference.sources.zip"
            del files[name]
            manifest = json.loads(files["manifest.json"])
            del manifest["files"][name]
            files["manifest.json"] = json.dumps(manifest).encode()
            archive = _zip(files)
            with self.assertRaisesRegex(ValueError, "OFFLINE_PACKET_REQUIRED"):
                replay_selected_future(archive, sha256(archive).hexdigest())
            self.assertEqual(annual.call_count, 20)

    def test_recovery_mode_is_bound_to_packet_and_replayed(self):
        from epw_climate_analyzer.station_gap_recovery import GAP_POLICY
        r = SignalRequest(*self.base.identity["signal_site"], WINDOW, (2040, 2059))
        def annual_product(req, **kwargs):
            self.assertTrue(kwargs.pop("recover_reference_gaps"))
            p = self.annual_product(req, **kwargs)
            return SimpleNamespace(request=p.request, files=p.files,
                report={**p.report, "gap_reconstruction": {"policy": GAP_POLICY, "stations": []}})
        with patch(MODULE+".OriginalSourceCache") as cache, patch(MODULE+".run_point_product",
                side_effect=annual_product) as annual, patch(
                "epw_climate_analyzer.future_selected.admit_nex_packet",
                return_value=(signals(), {"grid": [47.125,15.375], "source_packet_sha256": "0"*64})):
            cache.return_value.get.return_value = None
            future = run_selected_future(self.base,r,reference_mode=POINT_GAP_MODE,
                nex_packet=b"synthetic model",allow_liquid_precipitation_proxy=True)
            self.assertIn(b"station gap recovery up to 2 h",future.files["climate.epw"])
            packet = future.files["source_packets/local_reference.sources.zip"]
            digest = sha256(packet).hexdigest()
            members = bounded_zip(packet, byte_limit=128*1024**2, member_limit=61)
            manifest = json.loads(members["manifest.json"])
            self.assertEqual(manifest["gap_max_hours"], 2)
            for old_policy, maximum in (("PEER_ANOMALY_MASKED_WINDOWS_V1", 72), (GAP_POLICY, 72)):
                altered = {**manifest, "gap_policy": old_policy, "gap_max_hours": maximum}
                incompatible = _zip({**members, "manifest.json": json.dumps(altered).encode()})
                with self.assertRaisesRegex(ValueError, "IDENTITY_OR_CENSUS"):
                    point_reference(self.base,WINDOW,packet=incompatible,
                        expected_sha256=sha256(incompatible).hexdigest(),recover_gaps=True)
            with self.assertRaisesRegex(ValueError,"IDENTITY_OR_CENSUS"):
                point_reference(self.base,WINDOW,packet=packet,expected_sha256=digest)
            replay = replay_selected_future(future.archive,sha256(future.archive).hexdigest())
            self.assertEqual(future.files["climate.epw"],replay.files["climate.epw"])
            self.assertEqual(annual.call_count,20)

    def test_partial_window_fails_with_year_and_does_not_cache_blocked_year(self):
        blocked = SimpleNamespace(report={"status": "POINT_YEAR_BLOCKED", "global_blockers": ["missing station"]})
        with patch(MODULE+".OriginalSourceCache") as cache, patch(MODULE+".run_point_product",
                side_effect=[self.products[2005], blocked]) as annual:
            cache.return_value.get.return_value = None
            with self.assertRaisesRegex(ValueError, "YEAR_BLOCKED 2006"):
                point_reference(self.base, WINDOW)
            self.assertEqual(annual.call_count, 2)
            self.assertEqual(cache.return_value.put.call_count, 1)

    def test_blocked_point_reference_does_not_download_nasa(self):
        r = SignalRequest(*self.base.identity["signal_site"], WINDOW, (2040, 2059))
        with patch("epw_climate_analyzer.future_selected.point_reference",
                   side_effect=ValueError("F1_POINT_REFERENCE_YEAR_BLOCKED 2005")), patch(
                   "epw_climate_analyzer.future_selected.acquire_nex") as nasa:
            with self.assertRaisesRegex(ValueError, "YEAR_BLOCKED 2005"):
                run_selected_future(self.base, r, reference_mode=POINT_MODE, allow_liquid_precipitation_proxy=True)
            nasa.assert_not_called()

    def test_donor_height_or_background_cell_changes_block_annual_admission(self):
        product = self.products[2005]
        _, spec = point_reference_spec(self.base, WINDOW)
        changed = {**product.report, "background_source_geometry": {"background_cell": [1,2]}}
        with self.assertRaisesRegex(ValueError, "GEOMETRY_OR_METHOD_CHANGED"):
            _admit_year(SimpleNamespace(request=product.request, report=changed), product.request, spec)
        compatible = {**product.report, "background_source_geometry": {
            **product.report["background_source_geometry"], "requested_to_background_distance_km": 9.2}}
        _admit_year(SimpleNamespace(request=product.request, report=compatible), product.request, spec)
        rows = [dict(d) for d in product.report["donor_admission"]]
        next(d for d in rows if d["selected"])["pressure_elevation_m"] += 1
        with self.assertRaisesRegex(ValueError, "GEOMETRY_OR_METHOD_CHANGED"):
            _admit_year(SimpleNamespace(request=product.request, report={**product.report,"donor_admission": rows}),
                        product.request, spec)

    def test_incomplete_or_wrong_source_archive_never_downloads(self):
        p = _zip({"manifest.json": b'{"schema":"wrong"}'})
        with patch(MODULE+".run_point_product") as annual:
            with self.assertRaisesRegex(ValueError, "PACKET_IDENTITY_OR_CENSUS"):
                point_reference(self.base, WINDOW, packet=p, expected_sha256=sha256(p).hexdigest())
            with self.assertRaisesRegex(ValueError, "PACKET_HASH_OR_SIZE"):
                point_reference(self.base, WINDOW, packet=p, expected_sha256="0"*64)
            annual.assert_not_called()

    def test_retained_2025_source_failure_cannot_pass_the_new_gate(self):
        c = json.loads((ROOT / "at_station_usability_20261102.json").read_bytes())["negative_2025"]
        req = PointRequest(**c["request"])
        product = run_point_product(req, input_packet=(ROOT/c["file"]).read_bytes(), expected_sha256=c["sha256"])
        _, spec = point_reference_spec(self.real, (2016, 2025))
        with self.assertRaisesRegex(ValueError, "YEAR_BLOCKED 2025"):
            _admit_year(product, req, spec)

    def test_incomplete_fixed_catalogue_never_downloads_station_years(self):
        req, _ = point_reference_spec(self.real, WINDOW)
        module = "epw_climate_analyzer.point_interpolation"
        def metadata(**kw):
            kw["response_capture"]("", {}, b"original catalogue")
            return {}
        with patch(module+".geo.fetch_metadata", side_effect=metadata), patch(
                module+".geo.parse_stations", return_value=[]), patch(module+".run_station_year") as fetch:
            donors, _, evidence = _acquire_stations(req, lambda _: None, ("16412", "16413", "16511", "16411"))
            self.assertEqual(donors, [])
            self.assertEqual(len(evidence["candidate_metadata_exclusions"]), 4)
            fetch.assert_not_called()

    def test_point_mode_refuses_uploaded_epw_and_short_windows(self):
        with self.assertRaisesRegex(ValueError, "REQUIRES_ADMITTED_STATION_POINT_BASE"):
            point_reference_spec(synthetic_base(), WINDOW)
        with self.assertRaisesRegex(ValueError, "10_TO_30"):
            point_reference_spec(self.real, (2021, 2025))
