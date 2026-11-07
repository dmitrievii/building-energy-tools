"""Offline regression checks against documented subsets of real MeteoSwiss CSVs."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import switzerland_climate as c

CAT = c.load_catalog(c.DEFAULT_CATALOG)
FIX = Path(__file__).resolve().parent / "fixtures"
PROVENANCE = json.loads((FIX / "provenance.json").read_bytes())
RAW = {p["fixture"]: gzip.decompress((FIX / p["fixture"]).read_bytes()) for p in PROVENANCE}
BER = "smn_BER_day.csv.gz"
SMA = "smn_SMA_day.csv.gz"
RAIN = "smn-precip_ABE_day.csv.gz"
TRANSITION = "smn_BER_transition.csv.gz"


def modified(raw, field, value):
    text, encoding = c.decode_csv(raw)
    lines = text.splitlines()
    names = lines[0].split(";"); row = lines[1].split(";")
    row[names.index(field)] = value; lines[1] = ";".join(row)
    return ("\r\n".join(lines) + "\r\n").encode(encoding)


def fixture_plan(names=(BER,), overrides=None):
    cat = copy.deepcopy(CAT)
    identities = {p["asset_filename"]: (p, (overrides or {}).get(p["fixture"], RAW[p["fixture"]]))
                  for p in PROVENANCE if p["fixture"] in names}
    cat["assets"] = [a for a in cat["assets"] if a["filename"] in identities]
    for asset in cat["assets"]:
        p, raw = identities[asset["filename"]]
        asset["provider_sha256"], asset["provider_bytes"] = c.digest(raw), len(raw)
    cat["catalog_id"] = c.digest({k: v for k, v in cat.items() if k != "catalog_id"})
    transition = names == (TRANSITION,)
    return c.build_plan(cat, {"start": "2017-12-31" if transition else "2025-06-01",
                  "end": "2018-01-01" if transition else "2025-06-01", "parameters": "all",
                  "station_ids": sorted({p["station_id"] for p, raw in identities.values()}), "min_interval_seconds": 0})


class FakeClient:
    response_headers = {"etag": '"test-fixture-etag"'}

    def __init__(self, overrides=None):
        self.calls = []
        self.values = {p["source_url"]: (overrides or {}).get(p["fixture"], RAW[p["fixture"]]) for p in PROVENANCE}

    def get(self, url, **kwargs):
        self.calls.append(url)
        return self.values[url]


class Contracts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def save(self, name=BER, raw=None):
        raw = RAW[name] if raw is None else raw
        plan = fixture_plan((name,), {name: raw})
        root = c.run_root(self.out, plan)
        root.mkdir(parents=True, exist_ok=True)
        receipt = c.save_job(root, plan, plan["jobs"][0], raw)
        return plan, root, receipt

    def test_catalogue_identity_and_pagination_retained(self):
        self.assertEqual(set(CAT["networks"]), {"smn", "smn-precip"})
        self.assertGreaterEqual(len(CAT["stations"]), 300)
        pages = [s for s in CAT["sources"] if s["role"] == "stac_items_page"]
        self.assertGreaterEqual(len(pages), 4)
        self.assertEqual(len({a["url"] for a in CAT["assets"]}), len(CAT["assets"]))

    def test_all_catalogue_source_hashes(self):
        for s in CAT["sources"]:
            raw = (ROOT / "catalog" / s["path"]).read_bytes()
            self.assertEqual(c.digest(raw), s["stored_sha256"])
            self.assertEqual(c.digest(gzip.decompress(raw)), s["sha256"])

    def test_catalogue_output_hashes(self):
        manifest = json.loads((ROOT / "catalog/catalog_manifest.json").read_bytes())
        self.assertEqual(manifest["catalog_id"], CAT["catalog_id"])
        for name, sha in manifest["files"].items():
            self.assertEqual(c.digest((ROOT / "catalog" / name).read_bytes()), sha, name)

    def test_fixture_provenance_and_subset_label(self):
        for p in PROVENANCE:
            self.assertEqual(c.digest((FIX / p["fixture"]).read_bytes()), p["fixture_stored_sha256"])
            self.assertEqual(c.digest(RAW[p["fixture"]]), p["fixture_uncompressed_sha256"])
            self.assertIn("Derived fixture", p["transformation"])

    def test_station_id_validation(self):
        self.assertEqual(c.station_id("ber"), "BER")
        for bad in ("../BER", "B", "BER/", "Zürich"):
            with self.assertRaises(c.SourceError): c.station_id(bad)

    def test_no_fabricated_height_for_unlisted_stac_point(self):
        warnings = [w for w in CAT["warnings"] if w["code"] == "STAC_ITEM_WITHOUT_STATION_TABLE_METADATA"]
        for w in warnings:
            s = next(s for s in CAT["stations"] if s["network"] == w["network"] and s["station_id"] == w["station_id"])
            self.assertIsNone(s["elevation_m"])
            self.assertIsNone(s["barometer_elevation_m"])
            self.assertIn("metadata_missing", s["coordinate_role"])

    def test_geographic_and_barometer_heights_are_separate(self):
        s = next(s for s in CAT["stations"] if s["network"] == "smn" and s["station_id"] == "ABO")
        self.assertEqual(s["elevation_m"], 1321)
        self.assertEqual(s["barometer_elevation_m"], 1326)

    def test_geojson_coordinate_order(self):
        geo = json.loads((ROOT / "catalog/stations.geojson").read_bytes())
        for f in geo["features"]:
            self.assertEqual(f["geometry"]["coordinates"], [f["properties"]["longitude_deg"], f["properties"]["latitude_deg"]])

    def test_nearest_uses_explicit_wgs84_and_date(self):
        s = next(s for s in CAT["stations"] if s["network"] == "smn" and s["station_id"] == "BER")
        rows = c.nearest(CAT, s["latitude_deg"], s["longitude_deg"], "2025-06-01")
        self.assertEqual(rows[0]["station_id"], "BER")
        self.assertEqual(rows[0]["distance_km"], 0)
        self.assertEqual(rows[0]["donor_admission"], "not_assessed")

    def test_nearest_excludes_control_station(self):
        rows = c.nearest(CAT, 46.99, 7.46, "2025-06-01", exclude_ids=["BER"])
        self.assertNotIn("BER", {r["station_id"] for r in rows})

    def test_nearest_uses_parameter_specific_network(self):
        rows = c.nearest(CAT, 47.05, 7.28, "2025-06-01", networks=["smn-precip"], parameters=["rre150h0"])
        self.assertTrue(rows)
        self.assertTrue(all(r["network"] == "smn-precip" for r in rows))
        with self.assertRaises(c.SourceError): c.nearest(CAT, 47, 8, "2025-06-01", networks=["smn-precip"], parameters=["tre200h0"])

    def test_invalid_search_and_height_filter(self):
        with self.assertRaises(c.SourceError): c.nearest(CAT, 91, 8, "2025-01-01")
        with self.assertRaises(c.SourceError): c.nearest(CAT, 47, 8, "2025-01-01", height_difference_m=50)

    def test_time_bounds_timezone_and_exclusive_end(self):
        with self.assertRaises(c.SourceError): c.parse_bound("2025-06-01T00:00:00")
        self.assertEqual(c.iso(c.parse_bound("2025-06-01T02:00:00+02:00")), "2025-06-01T00:00Z")
        self.assertEqual(c.parse_bound("2025-06-01", end=True)-c.parse_bound("2025-06-01"), dt.timedelta(days=1))

    def test_native_source_time_is_utc_without_dst_adjustment(self):
        self.assertEqual(c.iso(c.source_time("30.03.2025 02:00")), "2025-03-30T02:00Z")

    def test_invalid_native_date_rejected(self):
        for value in ("31.02.2025 00:00", "2025-06-01 00:00", "01.06.2025 24:00"):
            with self.assertRaises(c.SourceError): c.source_time(value)

    def test_checksum_multihash_is_decoded(self):
        sha = c.digest(b"data")
        self.assertEqual(c.checksum_sha256("1220" + sha), sha)
        with self.assertRaises(c.SourceError): c.checksum_sha256("1320" + sha)

    def test_external_and_traversal_urls_rejected(self):
        for url in ("http://data.geo.admin.ch/x", "https://example.com/x", c.BASE+"ch.meteoschweiz.ogd-smn/../x"):
            with self.assertRaises(c.SourceError): c.safe_url(url)

    def test_plan_keeps_partial_period(self):
        p = fixture_plan()
        self.assertFalse(p["full_calendar_year_required"])
        self.assertEqual(p["start_utc_inclusive"], "2025-06-01T00:00Z")
        self.assertEqual(len(p["jobs"]), 1)

    def test_unknown_configuration_rejected(self):
        with self.assertRaises(c.SourceError): c.build_plan(CAT, {"start":"2025-01-01","end":"2025-12-31","complete_years_only":True})

    def test_unknown_station_and_parameter_rejected(self):
        for extra in ({"station_ids":["ZZZ"]},{"parameters":["wrong"]}):
            with self.assertRaises(c.SourceError): c.build_plan(CAT, {"start":"2025-01-01","end":"2025-12-31",**extra})

    def test_plan_roundtrip_and_tamper_detection(self):
        p = fixture_plan(); path = self.out/"plan.json"; c.write_json(path,p)
        self.assertEqual(c.load_plan(path),p)
        p["jobs"][0]["provider_sha256"]="0"*64; c.write_json(path,p)
        with self.assertRaises(c.SourceError): c.load_plan(path)

    def test_native_pressure_definitions_not_merged(self):
        defs = {p["parameter_shortname"]:p for p in CAT["parameters"]["smn"]}
        self.assertIn("barometric altitude", defs["prestah0"]["parameter_description_en"])
        self.assertIn("QFF", defs["pp0qffh0"]["parameter_description_en"])
        self.assertIn("QNH", defs["pp0qnhh0"]["parameter_description_en"])
        self.assertEqual(defs["gre000h0"]["parameter_unit"],"W/m²")
        self.assertEqual(defs["fu3010h0"]["parameter_unit"],"km/h")

    def test_qc_flags_not_fabricated(self):
        p,root,r=self.save()
        self.assertEqual(r["source_information"]["qc_status"],"per_value_flags_not_supplied_in_this_csv")
        with gzip.open(root/c.artifact_paths(p["jobs"][0])[1],"rt") as f: fields=csv.DictReader(f).fieldnames
        self.assertFalse(any("flag" in x or "qc" in x for x in fields))

    def test_native_blank_and_zero_preserved(self):
        raw=modified(RAW[BER],"tre200h0","");raw=modified(raw,"rre150h0","0")
        p,root,r=self.save(raw=raw)
        cov=r["coverage_by_year"]["2025"]
        self.assertEqual(cov["parameters"]["tre200h0"]["null_rows"],1)
        with gzip.open(root/c.artifact_paths(p["jobs"][0])[1],"rt") as f: row=next(csv.DictReader(f))
        self.assertEqual((row["tre200h0"],row["rre150h0"]),("","0"))

    def test_missing_column_is_explicit_not_fabricated_measurement(self):
        lines=RAW[BER].decode('cp1252').splitlines();i=lines[0].split(';').index('tre200h0')
        raw=('\n'.join(';'.join(row.split(';')[:i]+row.split(';')[i+1:]) for row in lines)+'\n').encode('cp1252')
        p,root,r=self.save(raw=raw)
        self.assertIn('tre200h0',r['source_information']['missing_selected_columns'])
        self.assertEqual(r['coverage_by_year']['2025']['parameters']['tre200h0']['non_null_rows'],0)

    def test_provider_checksum_mismatch_rejected(self):
        p=fixture_plan();root=c.run_root(self.out,p)
        with self.assertRaises(c.SourceError): c.save_job(root,p,p['jobs'][0],RAW[BER]+b'changed')
        self.assertTrue(list((root/'rejected').rglob('*.gz')))
        self.assertFalse(c.receipt_is_complete(root,p['jobs'][0]))

    def test_wrong_station_rejected(self):
        with self.assertRaises(c.SourceError): self.save(raw=modified(RAW[BER],'station_abbr','SMA'))

    def test_nonfinite_value_rejected(self):
        with self.assertRaises(c.SourceError): self.save(raw=modified(RAW[BER],'tre200h0','nan'))

    def test_duplicate_and_reversed_times_rejected(self):
        lines=RAW[BER].splitlines(keepends=True)
        for raw in (lines[0]+lines[1]+lines[1]+b''.join(lines[2:]),lines[0]+b''.join(reversed(lines[1:]))):
            with self.assertRaises(c.SourceError): self.save(raw=raw)

    def test_truncated_row_rejected(self):
        with self.assertRaises(c.SourceError): self.save(raw=RAW[BER]+b'BER;01.06.2025 23:00\n')

    def test_duplicate_header_rejected(self):
        raw=RAW[BER].replace(b'tre200hn',b'tre200h0',1)
        with self.assertRaises(c.SourceError): self.save(raw=raw)

    def test_unregistered_native_column_rejected(self):
        raw=RAW[BER].replace(b'tre200hn',b'new_unknown_field',1)
        with self.assertRaises(c.SourceError): self.save(raw=raw)

    def test_transition_retains_both_physical_interval_regimes(self):
        p,root,r=self.save(TRANSITION)
        self.assertEqual(r['source_information']['selected_rows'],48)
        self.assertEqual(r['coverage_by_year']['2017']['hour_interval_regimes'],{'pre2018_synop_rule_for_aggregates':24})
        self.assertEqual(r['coverage_by_year']['2018']['hour_interval_regimes'],{'since2018_hour_rule_for_aggregates':24})

    def test_leap_year_and_maximum_gap_include_missing_rows(self):
        start,end=c.parse_bound('2024-01-01'),c.parse_bound('2024-12-31',end=True)
        report=c.coverage([],['tre200h0'],start,end)
        self.assertEqual(report['expected_hourly_labels'],8784)
        self.assertEqual(report['parameters']['tre200h0']['max_missing_full_hour_run'],8784)
        p=fixture_plan();_,rows,_=c.parse_observations(RAW[BER],p,p['jobs'][0])
        rows=rows[:2]+rows[5:]
        cov=c.coverage(rows,['tre200h0'],c.parse_bound('2025-06-01'),c.parse_bound('2025-06-01',end=True))
        self.assertEqual(cov['absent_full_hour_labels'],3)
        self.assertEqual(cov['parameters']['tre200h0']['max_missing_full_hour_run'],3)

    def test_empty_selected_window_is_successful_transfer(self):
        p=fixture_plan();p['start_utc_inclusive']='2025-06-02T00:00Z';p['end_utc_exclusive']='2025-06-03T00:00Z'
        p['plan_id']=c.digest({k:v for k,v in p.items() if k!='plan_id'})
        r=c.download(p,self.out,FakeClient())
        self.assertTrue(r['all_transfers_complete'])
        receipt=json.loads((c.run_root(self.out,p)/'receipts'/(p['jobs'][0]['job_id']+'.json')).read_bytes())
        self.assertEqual(receipt['source_information']['selected_rows'],0)

    def test_resume_verifies_raw_part_and_metadata(self):
        for i in range(3):
            with self.subTest(artifact=i), tempfile.TemporaryDirectory() as out:
                p=fixture_plan();client=FakeClient()
                self.assertTrue(c.download(p,out,client)['all_transfers_complete'])
                self.assertEqual(c.download(p,out,client)['attempted_this_invocation'],0)
                (c.run_root(out,p)/c.artifact_paths(p['jobs'][0])[i]).write_bytes(b'corrupt')
                self.assertEqual(c.download(p,out,client)['attempted_this_invocation'],1)
                self.assertEqual(len(client.calls),2)

    def test_partial_receipt_does_not_allow_skip(self):
        p,root,r=self.save();r['artifacts'].pop()
        c.write_json(root/'receipts'/(p['jobs'][0]['job_id']+'.json'),r)
        self.assertFalse(c.receipt_is_complete(root,p['jobs'][0]))

    def test_max_jobs_and_lock(self):
        p=fixture_plan((BER,RAIN));client=FakeClient()
        r=c.download(p,self.out,client,max_jobs=1)
        self.assertEqual((r['attempted_this_invocation'],r['remaining_jobs']),(1,1))
        root=c.run_root(self.out,p)
        with c.run_lock(root):
            with self.assertRaises(c.SourceError): c.download(p,self.out,client)

    def test_failed_download_reports_failure_and_releases_lock(self):
        p=fixture_plan();client=FakeClient({BER:b'bad'})
        r=c.download(p,self.out,client)
        self.assertFalse(r['all_transfers_complete'])
        self.assertEqual(len(r['failures_this_invocation']),1)
        self.assertFalse((c.run_root(self.out,p)/'.download.lock').exists())

    def test_export_and_audit_block_incomplete_assets(self):
        p=fixture_plan()
        with self.assertRaises(c.SourceError): c.export_station(p,self.out,'BER',2025)
        with self.assertRaises(c.SourceError): c.audit(p,self.out,self.out/'coverage.csv')

    def test_export_is_partial_year_with_native_pressure_fields(self):
        p,root,r=self.save()
        report=c.export_station(p,self.out,'BER',2025,plain=True)
        self.assertEqual(report['selected_rows'],24)
        self.assertFalse(report['full_calendar_selection'])
        self.assertFalse(report['epw_admission_assessed'])
        with open(report['path']) as f:fields=csv.DictReader(f).fieldnames
        self.assertTrue({'prestah0','pp0qffh0','pp0qnhh0'}.issubset(fields))

    def test_audit_writes_all_stations_including_precipitation_only(self):
        p=fixture_plan((BER,SMA,RAIN));client=FakeClient();c.download(p,self.out,client)
        summary=c.audit(p,self.out,self.out/'coverage.csv')
        self.assertEqual(summary['station_years'],3)
        self.assertEqual(summary['network_requests'],0)
        self.assertTrue(summary['partial_station_years_retained'])
        with (self.out/'coverage.csv').open() as f:rows=list(csv.DictReader(f))
        self.assertEqual({r['station_id'] for r in rows},{'BER','SMA','ABE'})
        self.assertTrue(any(r['network']=='smn-precip' and r['parameter']=='rre150h0' for r in rows))

    def test_new_year_transition_audit_keeps_two_partial_years(self):
        p=fixture_plan((TRANSITION,));c.download(p,self.out,FakeClient())
        summary=c.audit(p,self.out,self.out/'coverage.csv')
        self.assertEqual(summary['station_years'],2)
        with (self.out/'coverage.csv').open() as f:rows=list(csv.DictReader(f))
        self.assertEqual({r['year'] for r in rows},{'2017','2018'})


def real_fixture_test(name):
    def test(self):
        p,root,r=self.save(name)
        self.assertTrue(c.receipt_is_complete(root,p['jobs'][0]))
        self.assertTrue(r['provider_checksum_verified'])
        self.assertEqual(r['source_information']['selected_rows'],48 if name==TRANSITION else 24)
    return test


for _name in RAW:
    setattr(Contracts,'test_real_fixture_'+_name.replace('-','_').replace('.','_'),real_fixture_test(_name))


if __name__=='__main__': unittest.main()
