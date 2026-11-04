"""Original-source gap replay and conservative recovery gates."""
from dataclasses import replace
import csv
import gzip
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from epw_climate_analyzer.engine.point_interpolation import E, T, RH, P, PointRequest
from epw_climate_analyzer.point_interpolation import run_point_product, _replay_donors
from epw_climate_analyzer.station_gap_recovery import recover_station_gaps

ROOT = Path(__file__).resolve().parents[3] / "research/ige_cmip6/f1_gap_recovery_20261104"


def inputs(year):
    data = json.loads((ROOT/"sources.json").read_bytes())[str(year)]
    return PointRequest(**data["request"]), (ROOT/f"stations_{year}.zip").read_bytes(), data["sha256"]


class GapRecoveryTests(unittest.TestCase):
    def setUp(self):
        guard = patch("socket.socket.connect", side_effect=AssertionError("OFFLINE GAP REPLAY"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_real_2015_and_2016_are_recovered_only_in_explicit_mode(self):
        for year, fields in ((2015, {T,RH,P}), (2016, {T})):
            with self.subTest(year=year):
                req, body, digest = inputs(year)
                strict = run_point_product(req,input_packet=body,expected_sha256=digest)
                entry = json.loads((ROOT/"sources.json").read_bytes())[str(year)]
                result = run_point_product(req,input_packet=body,expected_sha256=digest,recover_reference_gaps=True,
                    include_background=True,background_packet=(ROOT/f"background_{year}.zip").read_bytes(),
                    background_sha256=entry["background_sha256"])
                self.assertEqual(result.report["EPW_status"],"ADMITTED_MIXED_SOURCE_RESEARCH")
                epw = result.files["climate.epw"]
                self.assertIn(b"Contains reconstructed station inputs",epw)
                self.assertEqual(len(list(csv.reader(io.StringIO(epw.decode()))))-8,8784 if year==2016 else 8760)
                self.assertEqual(strict.report["status"],"POINT_YEAR_BLOCKED")
                self.assertEqual(result.report["status"],"POINT_YEAR_COMPLETE_RESEARCH")
                self.assertTrue(result.report["engine_gap_fill"])
                self.assertEqual(result.files["inputs.zip"], body)
                station, = result.report["gap_reconstruction"]["stations"]
                episode, = station["episodes"]
                self.assertEqual(station["status"], "RECONSTRUCTED_NOT_OBSERVED")
                self.assertEqual(episode["hours"],2)
                self.assertEqual(set(episode["estimated_values"]),fields)
                self.assertEqual(len(episode["validation_windows_utc"]),12)
                for values in episode["estimated_values"].values():
                    self.assertEqual(len(values),2)

    def test_real_2014_long_gap_is_blocked_before_estimation(self):
        req, body, digest = inputs(2014)
        with patch("epw_climate_analyzer.station_gap_recovery._episode",
                   side_effect=AssertionError("LONG_GAP_MUST_NOT_BE_ESTIMATED")):
            p = run_point_product(req,input_packet=body,expected_sha256=digest,recover_reference_gaps=True)
        self.assertEqual(p.report["status"],"POINT_YEAR_BLOCKED")
        self.assertNotIn("climate.epw",p.files)
        self.assertFalse(p.report["engine_gap_fill"])
        station, = p.report["gap_reconstruction"]["stations"]
        self.assertEqual(station["station_id"], "16411")
        self.assertIn("GAP_DURATION_LIMIT: 61 consecutive missing hours; maximum 2 h",station["reason"])

    def test_recovery_never_changes_observed_fields_and_keeps_original_donors(self):
        req, body, digest = inputs(2016)
        donors,_ = _replay_donors(req,body,digest)
        updated,_ = recover_station_gaps(donors)
        for old,new in zip(donors,updated):
            for field in (T,RH,P,E):
                valid = old.data[field].notna()
                self.assertTrue(old.data.loc[valid,field].equals(new.data.loc[valid,field]))
        self.assertEqual(sum(d.data[T].isna().sum() for d in donors),2)
        self.assertEqual(sum(d.data[T].isna().sum() for d in updated),0)

    def test_quality_rejection_is_never_treated_as_missing_value(self):
        req, body, digest = inputs(2015)
        donors,_ = _replay_donors(req,body,digest)
        i = next(i for i,d in enumerate(donors) if d.blockers)
        donor = donors[i]
        ledger = gzip.decompress(donor.source_gaps_csv_gz).replace(b"MISSING_VALUE",b"QC_NOT_REVIEWED")
        donors[i] = replace(donor,source_gaps_csv_gz=gzip.compress(ledger))
        updated,audit = recover_station_gaps(donors)
        self.assertIs(updated[i],donors[i])
        self.assertEqual(audit["stations"][0]["reason"],"NON_MISSING_SOURCE_REJECTION")
