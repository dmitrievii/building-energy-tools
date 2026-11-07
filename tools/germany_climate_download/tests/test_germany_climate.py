"""Offline contract and regression checks; fixtures are documented DWD subsets."""
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
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import germany_climate as g

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CATALOG = g.load_catalog(g.DEFAULT_CATALOG)
PROVENANCE = json.loads((FIXTURES / "provenance.json").read_bytes())
RAW = {r["group"]: (FIXTURES / r["fixture_file"]).read_bytes() for r in PROVENANCE}


def changed_zip(raw, *, transform=None, remove_prefix=None, extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as original, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as result:
        for name in original.namelist():
            if remove_prefix and name.startswith(remove_prefix):
                continue
            data = original.read(name)
            if transform:
                data = transform(name, data)
            result.writestr(name, data)
        if extra:
            result.writestr(*extra)
    return output.getvalue()


def edit_product(raw, edit):
    def transform(name, body):
        if name.startswith("produkt_"):
            lines = body.decode("cp1252").splitlines()
            return ("\n".join(edit(lines)) + "\n").encode("cp1252")
        return body
    return changed_zip(raw, transform=transform)


def edit_first_value(raw, field, value):
    def change(lines):
        fields = [s.strip() for s in lines[0].split(";")]
        row = lines[1].split(";")
        row[fields.index(field)] = value
        lines[1] = ";".join(row)
        return lines
    return edit_product(raw, change)


def fixture_plan(groups=("pressure",), tiers=None, raws=None):
    tiers = ["recent", "row"] if tiers is None else tiers
    catalog = copy.deepcopy(CATALOG)
    catalog["archives"] = [a for a in catalog["archives"] if a["station_id"] == "01048"
                           and a["group"] in groups and a["tier"] in tiers]
    for a in catalog["archives"]:
        a["listing_bytes"] = len((raws or RAW)[a["group"]])
    catalog["catalog_id"] = g.digest({k: v for k, v in catalog.items() if k != "catalog_id"})
    return g.build_plan(catalog, {"start": "2025-06-01", "end": "2025-06-01",
             "groups": list(groups), "station_ids": ["01048"], "tiers": tiers, "min_interval_seconds": 0})


class FakeClient:
    def __init__(self, values=None):
        self.calls = []
        self.values = RAW if values is None else values

    def get(self, url):
        self.calls.append(url)
        return self.values[url] if url in self.values else self.values[url.removeprefix(g.BASE).split("/")[0]]


class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)

    def save(self, group="pressure", raw=None):
        raw = RAW[group] if raw is None else raw
        plan = fixture_plan([group], raws={group: raw})
        root = g.run_root(self.output, plan)
        root.mkdir(parents=True)
        return plan, root, g.save_job(root, plan, plan["jobs"][0], raw)

    def test_packaged_catalogue_identity(self):
        self.assertEqual(len(CATALOG["groups"]), 10)
        self.assertGreater(len(CATALOG["stations"]), 2000)
        self.assertEqual(len({s["station_id"] for s in CATALOG["stations"]}), len(CATALOG["stations"]))

    def test_all_catalogue_source_hashes(self):
        for source in CATALOG["sources"]:
            with self.subTest(url=source["url"]):
                raw = (ROOT / "catalog" / source["path"]).read_bytes()
                self.assertEqual(g.digest(raw), source["stored_sha256"])
                self.assertEqual(g.digest(gzip.decompress(raw) if source["compression"] == "gzip" else raw), source["sha256"])

    def test_all_catalogue_outputs_match_manifest(self):
        manifest = json.loads((ROOT / "catalog" / "catalog_manifest.json").read_bytes())
        self.assertEqual(manifest["catalog_id"], CATALOG["catalog_id"])
        for name, sha in manifest["files"].items():
            self.assertEqual(g.digest((ROOT / "catalog" / name).read_bytes()), sha, name)

    def test_fixture_provenance(self):
        for source in PROVENANCE:
            self.assertEqual(g.digest(RAW[source["group"]]), source["fixture_sha256"])
            self.assertIn("derived fixture", source["transformation"])

    def test_dwd_id_is_not_wmo_number(self):
        self.assertEqual(g.sid(1048), "01048")
        for bad in (0, "../x", "-1", "12.1", "123456"):
            with self.assertRaises(g.SourceError):
                g.sid(bad)

    def test_archive_filename_and_date_interval(self):
        value = g.parse_archive_name("stundenwerte_P0_01048_19750701_20251231_hist.zip", "pressure", "historical")
        self.assertEqual(value["archive_start"], "1975-07-01")
        with self.assertRaises(g.SourceError):
            g.parse_archive_name("stundenwerte_P0_01048_akt.zip", "pressure", "historical")

    def test_naive_user_datetime_rejected(self):
        with self.assertRaises(g.SourceError):
            g.parse_bound("2025-06-01T00:00")

    def test_date_end_is_exclusive_next_day(self):
        self.assertEqual(g.parse_bound("2025-06-01", end=True) - g.parse_bound("2025-06-01"), dt.timedelta(days=1))

    def test_explicit_offset_converted(self):
        self.assertEqual(g.iso(g.parse_bound("2025-06-01T01:00:00+01:00")), "2025-06-01T00:00Z")

    def test_fractional_user_bounds_rejected(self):
        with self.assertRaises(g.SourceError):
            g.parse_bound("2025-06-01T00:15:00Z")

    def test_leap_year_8784_expected_labels(self):
        result = g.coverage([], [], g.parse_bound("2024-01-01"), g.parse_bound("2024-12-31", end=True))
        self.assertEqual(result["expected_hourly_utc_labels"], 8784)
        self.assertFalse(result["full_utc_hour_label_axis"])

    def test_haversine_coordinate_order(self):
        self.assertEqual(g.distance_km(51, 13, 51, 13), 0)
        self.assertAlmostEqual(g.distance_km(0, 0, 0, 1), 111.195080, places=5)

    def test_nearest_group_date_and_exclusion(self):
        rows = g.nearest(CATALOG, 51.13, 13.77, "2025-06-01", groups=["air_temperature"], limit=3)
        self.assertEqual(rows[0]["station_id"], "01048")
        self.assertIn("not_dated_history", rows[0]["coordinate_role"])
        excluded = g.nearest(CATALOG, 51.13, 13.77, "2025-06-01", groups=["air_temperature"], exclude_ids=[1048])
        self.assertNotIn("01048", {r["station_id"] for r in excluded})

    def test_nearest_height_requires_elevation(self):
        with self.assertRaises(g.SourceError):
            g.nearest(CATALOG, 51, 13, "2025-01-01", height_difference_m=100)

    def test_nearest_invalid_geography(self):
        for lat, lon in ((91, 13), (51, 181), (float("nan"), 13)):
            with self.assertRaises(g.SourceError):
                g.nearest(CATALOG, lat, lon, "2025-01-01")

    def test_nearest_radius_filter(self):
        self.assertEqual(g.nearest(CATALOG, 0, 0, "2025-01-01", groups=["pressure"], radius_km=1), [])

    def test_geojson_longitude_latitude(self):
        geo = json.loads((ROOT / "catalog" / "stations.geojson").read_bytes())
        for feature in geo["features"]:
            p = feature["properties"]
            self.assertEqual(feature["geometry"]["coordinates"], [p["longitude_deg"], p["latitude_deg"]])

    def test_plan_contains_no_automatic_recent_overlap(self):
        plan = g.build_plan(CATALOG, {"start": "2016-01-01", "end": "2025-12-31", "groups": ["pressure"], "station_ids": [1048]})
        self.assertTrue(all(j["tier"] == "historical" for j in plan["jobs"]))

    def test_plan_unknown_config_rejected(self):
        with self.assertRaises(g.SourceError):
            g.build_plan(CATALOG, {"start": "2025-01-01", "end": "2025-12-31", "gap_fill": True})

    def test_plan_unavailable_station_rejected(self):
        with self.assertRaises(g.SourceError):
            g.build_plan(CATALOG, {"start": "2025-01-01", "end": "2025-12-31", "station_ids": [99999]})

    def test_plan_roundtrip_and_tamper_rejected(self):
        plan = fixture_plan()
        path = self.output / "plan.json"
        g.write_json(path, plan)
        self.assertEqual(g.load_plan(path), plan)
        plan["jobs"][0]["listing_bytes"] += 1
        g.write_json(path, plan)
        with self.assertRaises(g.SourceError):
            g.load_plan(path)

    def test_untrusted_source_url_rejected(self):
        for url in ("http://opendata.dwd.de/a", "https://example.org/climate_environment/CDC/x", g.BASE + "../x"):
            with self.assertRaises(g.SourceError):
                g.safe_url(url)

    def test_pressure_semantics_in_actual_metadata(self):
        plan = fixture_plan()
        with zipfile.ZipFile(io.BytesIO(RAW["pressure"])) as archive:
            meta = g.archive_metadata(archive, plan["jobs"][0])
        definitions = {r["Parameter"]: r["Parameterbeschreibung"] for r in meta["parameter_history"]}
        self.assertIn("Stationshoehe", definitions["P0"])
        self.assertIn("NN", definitions["P"])

    def test_historical_geography_is_retained(self):
        plan, root, receipt = self.save()
        meta = json.loads((root / g.artifact_paths(plan["jobs"][0])[2]).read_bytes())
        self.assertGreater(len(meta["geography_history"]), 1)
        self.assertEqual(meta["geography_history"][0]["von_datum"], "19260501")

    def test_solar_minutes_and_secondary_woz_retained(self):
        plan, root, receipt = self.save("solar")
        with gzip.open(root / g.artifact_paths(plan["jobs"][0])[1], "rt") as f:
            first = next(csv.DictReader(f))
        self.assertIn(":02", first["timestamp_source"])
        self.assertTrue(first["timestamp_utc"].endswith(":02Z"))
        self.assertIn("MESS_DATUM_WOZ", first)
        self.assertFalse(receipt["coverage"]["full_utc_hour_label_axis"])
        self.assertEqual(receipt["coverage"]["off_full_hour_rows"], 24)

    def test_sun_absent_night_rows_not_fabricated(self):
        plan, root, receipt = self.save("sun")
        self.assertEqual(receipt["coverage"]["selected_rows"], 18)
        self.assertEqual(receipt["coverage"]["missing_hourly_utc_labels"], 6)
        self.assertFalse(receipt["coverage"]["full_utc_hour_label_axis"])

    def test_mez_metadata_conversion_is_explicit(self):
        plan = fixture_plan(["air_temperature"])
        with zipfile.ZipFile(io.BytesIO(RAW["air_temperature"])) as archive:
            meta = g.archive_metadata(archive, plan["jobs"][0])
        utc, basis, status = g.clock_info(dt.datetime(1990, 1, 1), meta, "air_temperature", ["TT_TU", "RF_TU"])
        self.assertEqual((utc, basis), ("1989-12-31T23:00Z", "MEZ"))
        self.assertIn("converted_from_metadata", status)

    def test_old_sun_woz_not_assigned_utc(self):
        plan = fixture_plan(["sun"])
        with zipfile.ZipFile(io.BytesIO(RAW["sun"])) as archive:
            meta = g.archive_metadata(archive, plan["jobs"][0])
        utc, basis, status = g.clock_info(dt.datetime(1990, 1, 1), meta, "sun", ["SD_SO"])
        self.assertEqual((utc, basis), ("", "WOZ"))
        self.assertIn("unresolved", status)

    def test_unknown_or_conflicting_clock_not_guessed(self):
        empty = {"parameter_history": []}
        self.assertEqual(g.clock_info(dt.datetime(2025, 1, 1), empty, "pressure", ["P"])[0], "")
        records = [{"Von_Datum": "20250101", "Bis_Datum": "20251231", "Parameter": "P", "Zusatz-Info": s}
                   for s in ("in UTC", "in MEZ")]
        result = g.clock_info(dt.datetime(2025, 1, 1), {"parameter_history": records}, "pressure", ["P"])
        self.assertEqual(result[1], "AMBIGUOUS")
        self.assertEqual(result[0], "")

    def test_missing_marker_zero_and_qc_preserved(self):
        raw = edit_first_value(RAW["pressure"], "P0", "-999.0")
        raw = edit_first_value(raw, "P", "0.0")
        raw = edit_first_value(raw, "QN_8", "-999")
        plan, root, receipt = self.save("pressure", raw)
        self.assertEqual(receipt["coverage"]["variables"]["P0"]["missing_rows"], 1)
        self.assertEqual(receipt["coverage"]["variables"]["P"]["present_rows"], 24)
        with gzip.open(root / g.artifact_paths(plan["jobs"][0])[1], "rt") as f:
            row = next(csv.DictReader(f))
        self.assertEqual((row["P0"], row["P"], row["QN_8"]), ("-999.0", "0.0", "-999"))

    def test_all_empty_parameter_not_inferred_complete(self):
        def change(lines):
            fields = [s.strip() for s in lines[0].split(";")]
            for i in range(1, len(lines)):
                row = lines[i].split(";"); row[fields.index("P0")] = "-999"; lines[i] = ";".join(row)
            return lines
        plan, root, receipt = self.save(raw=edit_product(RAW["pressure"], change))
        cov = receipt["coverage"]
        self.assertTrue(cov["full_utc_hour_label_axis"])
        self.assertEqual(cov["variables"]["P0"]["present_rows"], 0)
        self.assertEqual(cov["variables"]["P0"]["missing_full_hour_utc_labels"], 24)
        self.assertFalse(cov["full_meteorological_year_or_epw_admission"])

    def test_nonfinite_native_value_rejected(self):
        with self.assertRaises(g.SourceError):
            self.save(raw=edit_first_value(RAW["pressure"], "P0", "nan"))

    def test_wrong_station_in_product_rejected(self):
        with self.assertRaises(g.SourceError):
            self.save(raw=edit_first_value(RAW["pressure"], "STATIONS_ID", "1420"))

    def test_bad_end_of_record_rejected(self):
        with self.assertRaises(g.SourceError):
            self.save(raw=edit_first_value(RAW["pressure"], "eor", ""))

    def test_duplicate_timestamp_rejected(self):
        with self.assertRaises(g.SourceError):
            self.save(raw=edit_product(RAW["pressure"], lambda lines: lines[:2] + [lines[1]] + lines[2:]))

    def test_truncated_row_rejected(self):
        with self.assertRaises(g.SourceError):
            self.save(raw=edit_product(RAW["pressure"], lambda lines: lines + ["1048;2025060123"]))

    def test_missing_quality_column_rejected(self):
        with self.assertRaises(g.SourceError):
            self.save(raw=edit_product(RAW["pressure"], lambda lines: [lines[0].replace("QN_8", "flag")] + lines[1:]))

    def test_metadata_missing_rejected(self):
        with self.assertRaises(g.SourceError):
            self.save(raw=changed_zip(RAW["pressure"], remove_prefix="Metadaten_Parameter_"))

    def test_unsafe_zip_path_rejected(self):
        with self.assertRaises(g.SourceError):
            self.save(raw=changed_zip(RAW["pressure"], extra=("../escape.txt", b"x")))

    def test_duplicate_zip_member_rejected(self):
        with zipfile.ZipFile(io.BytesIO(RAW["pressure"])) as z:
            name = z.namelist()[0]; body = z.read(name)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            raw = changed_zip(RAW["pressure"], extra=(name, body))
        with self.assertRaises(g.SourceError):
            self.save(raw=raw)

    def test_zip_size_change_requires_new_snapshot(self):
        plan = fixture_plan()
        root = g.run_root(self.output, plan)
        with self.assertRaises(g.SourceError):
            g.save_job(root, plan, plan["jobs"][0], RAW["pressure"] + b"extra")

    def test_download_resume_verifies_all_artifacts(self):
        for artifact_index in range(3):
            with self.subTest(artifact=artifact_index), tempfile.TemporaryDirectory() as out:
                plan = fixture_plan(); client = FakeClient()
                self.assertTrue(g.download(plan, out, client)["all_transfers_complete"])
                self.assertEqual(g.download(plan, out, client)["attempted_this_invocation"], 0)
                self.assertEqual(len(client.calls), 1)
                root = g.run_root(out, plan)
                (root / g.artifact_paths(plan["jobs"][0])[artifact_index]).write_bytes(b"corrupt")
                self.assertEqual(g.download(plan, out, client)["attempted_this_invocation"], 1)
                self.assertEqual(len(client.calls), 2)

    def test_incomplete_receipt_not_skipped(self):
        plan, root, receipt = self.save()
        receipt["artifacts"].pop()
        g.write_json(root / "receipts" / (plan["jobs"][0]["job_id"] + ".json"), receipt)
        self.assertFalse(g.receipt_is_complete(root, plan["jobs"][0]))

    def test_max_jobs_limits_new_attempts(self):
        plan = fixture_plan(["pressure", "wind"])
        result = g.download(plan, self.output, FakeClient(), max_jobs=1)
        self.assertEqual((result["attempted_this_invocation"], result["remaining_jobs"]), (1, 1))

    def test_locked_run_does_not_download(self):
        plan = fixture_plan(); client = FakeClient(); root = g.run_root(self.output, plan)
        root.mkdir(); (root / ".download.lock").write_text("another process")
        with self.assertRaises(g.SourceError):
            g.download(plan, self.output, client)
        self.assertEqual(client.calls, [])

    def test_failure_reported_and_lock_released(self):
        plan = fixture_plan()
        result = g.download(plan, self.output, FakeClient({"pressure": b"bad"}))
        self.assertEqual(len(result["failures_this_invocation"]), 1)
        self.assertFalse(result["all_transfers_complete"])
        self.assertFalse((g.run_root(self.output, plan) / ".download.lock").exists())

    def test_export_blocks_missing_or_corrupt_archive(self):
        plan = fixture_plan()
        with self.assertRaises(g.SourceError):
            g.export_station(plan, self.output, 1048, 2025, "pressure")
        g.download(plan, self.output, FakeClient())
        (g.run_root(self.output, plan) / g.artifact_paths(plan["jobs"][0])[1]).write_bytes(b"bad")
        with self.assertRaises(g.SourceError):
            g.export_station(plan, self.output, 1048, 2025, "pressure")

    def test_export_partial_year_label(self):
        plan, root, receipt = self.save()
        result = g.export_station(plan, self.output, 1048, 2025, "pressure", plain=True)
        self.assertTrue(Path(result["csv"]).exists())
        self.assertFalse(result["coverage"]["full_calendar_selection"])
        self.assertEqual(result["coverage"]["selected_rows"], 24)
        self.assertFalse(result["coverage"]["full_meteorological_year_or_epw_admission"])

    def test_export_wrong_year_rejected(self):
        with self.assertRaises(g.SourceError):
            g.export_station(fixture_plan(), self.output, 1048, 2024, "pressure")

    def test_historical_recent_overlap_prefers_historical(self):
        plan = fixture_plan(["pressure"], tiers=["historical", "recent"])
        changed = edit_first_value(RAW["pressure"], "P0", "777.7")
        for j in plan["jobs"]:
            j["listing_bytes"] = len(changed if j["tier"] == "recent" else RAW["pressure"])
            j["job_id"] = g.digest({k: v for k, v in j.items() if k != "job_id"})[:24]
        plan["plan_id"] = g.digest({k: v for k, v in plan.items() if k != "plan_id"})
        client = FakeClient({j["url"]: changed if j["tier"] == "recent" else RAW["pressure"] for j in plan["jobs"]})
        g.download(plan, self.output, client)
        result = g.export_station(plan, self.output, 1048, 2025, "pressure", plain=True)
        self.assertEqual(result["coverage"]["duplicate_rows_removed"], 24)
        self.assertEqual(result["coverage"]["overlap_conflicts_historical_preferred"], 1)
        with Path(result["csv"]).open() as f:
            first = next(csv.DictReader(f))
        self.assertNotEqual(first["P0"], "777.7")

    def test_successful_transfer_can_have_zero_selected_rows(self):
        plan = fixture_plan()
        plan["start_utc_inclusive"], plan["end_utc_exclusive"] = "2025-07-01T00:00Z", "2025-07-02T00:00Z"
        plan["plan_id"] = g.digest({k: v for k, v in plan.items() if k != "plan_id"})
        result = g.download(plan, self.output, FakeClient())
        self.assertTrue(result["all_transfers_complete"])
        root = g.run_root(self.output, plan)
        meta = json.loads((root / g.artifact_paths(plan["jobs"][0])[2]).read_bytes())
        self.assertEqual(meta["coverage"]["selected_rows"], 0)

    def test_conflicting_archives_in_same_tier_block_export(self):
        plan = fixture_plan(["pressure"], tiers=["historical"])
        changed = edit_first_value(RAW["pressure"], "P0", "777.7")
        second = copy.deepcopy(plan["jobs"][0])
        second["filename"] = second["filename"].replace("19750701", "19750702")
        second["url"] = second["url"].replace("19750701", "19750702")
        second["archive_start"] = "1975-07-02"
        second["listing_bytes"] = len(changed)
        second["job_id"] = g.digest({k: v for k, v in second.items() if k != "job_id"})[:24]
        plan["jobs"].append(second)
        plan["plan_id"] = g.digest({k: v for k, v in plan.items() if k != "plan_id"})
        client = FakeClient({plan["jobs"][0]["url"]: RAW["pressure"], second["url"]: changed})
        result = g.download(plan, self.output, client)
        self.assertTrue(result["all_transfers_complete"])
        with self.assertRaises(g.SourceError):
            g.export_station(plan, self.output, 1048, 2025, "pressure")


def actual_fixture_test(group):
    def test(self):
        plan, root, receipt = self.save(group)
        self.assertEqual(receipt["coverage"]["selected_rows"], 18 if group == "sun" else 24)
        self.assertTrue(g.receipt_is_complete(root, plan["jobs"][0]))
    return test


for _group in g.GROUPS:
    setattr(Contracts, "test_real_dwd_fixture_" + _group, actual_fixture_test(_group))


if __name__ == "__main__":
    unittest.main()
