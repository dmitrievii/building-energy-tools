"""P6.3F: strict custodial original ARAD-Graz quality, UTC, minute and no-fabrication tests."""
from __future__ import annotations
import csv,hashlib,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from p6_3f_arad_ground_qc_validation import (
 ARAD_COLS,QC,START,iso_utc,validate_manifest,load_original_arad,
 compare,metrics,pearson,PERIOD_HOURS,SITES
)

def manifest_for(source_hash):
    return {"station_id":"ARAD_GRAZ",
      "custodian":"GeoSphere Austria, original radiometry department",
      "original_source_sha256":source_hash,
      "source_approval":"AUTHENTIC_ORIGINAL_RESEARCH_ACCESS_APPROVED",
      "quality_flag_mapping":{str(k):v for k,v in QC.items()},
      "time_standard":"UTC",
      "timestamp_represents":"start_of_1_minute_average",
      "sampling_seconds":60,
      "variables":{k:{"column":v,"unit":"W/m2","quality_flag_column":v+"_qc"}
                   for k,v in ARAD_COLS.items()},
      "archived_raw_unmodified":True,
      "permission_to_analyse":True,
      "station_latitude":47.078,
      "station_longitude":15.448,
      "source_data_version":"custodian-original-historical-v1",
      "redistribution_permitted":False}

class ARADOriginalGroundScienceContracts(unittest.TestCase):
    def test_local_time_and_dst_cannot_be_paired_to_nasa_utc(self):
        self.assertEqual(iso_utc("2012-07-01T10:15:00Z"),
                         datetime(2012,7,1,10,15,tzinfo=timezone.utc))
        for bad in ("2012-07-01 10:15:00","2012-07-01T10:15:00+02:00",
                    "2012-07-01T10:15:40+00:00"):
            with self.subTest(value=bad),self.assertRaises(ValueError):
                iso_utc(bad)

    def test_manifest_requires_provider_authentication_original_sha_and_quality_codes(self):
        good=manifest_for("a"*64)
        self.assertFalse(validate_manifest(good,"a"*64)["redistribution_permitted"])
        for key,value in (("source_approval","UNVERIFIED"),
                          ("original_source_sha256","b"*64),
                          ("time_standard","Europe/Vienna"),
                          ("timestamp_represents","end_of_1_minute_average"),
                          ("sampling_seconds",600),
                          ("permission_to_analyse",False)):
            m=manifest_for("a"*64);m[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_manifest(m,"a"*64)
        m=manifest_for("a"*64);m["quality_flag_mapping"]["0"]="good"
        with self.assertRaisesRegex(ValueError,"quality"):
            validate_manifest(m,"a"*64)

    def _source(self,root,values):
        path=root/"original.csv";meta=root/"original.json"
        fields=["timestamp_utc"]
        for name in ARAD_COLS.values():fields.extend((name,name+"_qc"))
        with path.open("w",newline="",encoding="utf8") as out:
            writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
            for stamp,vals,flags in values:
                row={"timestamp_utc":stamp}
                for channel,col in ARAD_COLS.items():
                    row[col]=vals.get(channel,100.)
                    row[col+"_qc"]=flags.get(channel,1)
                writer.writerow(row)
        meta.write_text(json.dumps(manifest_for(hashlib.sha256(
                 path.read_bytes()).hexdigest())),encoding="utf8")
        return path,meta

    def test_full_minutes_only_per_component_independently(self):
        with tempfile.TemporaryDirectory() as loc:
            root=Path(loc)
            first=START+timedelta(hours=10)
            original=[]
            for i in range(60):
                t=first+timedelta(minutes=i)
                q={"DHI":3} if i==33 else {}
                original.append((t.isoformat(),
                     {"GHI":300.,"DNI":700.,"DHI":100.,"LW":310.},q))
            source,meta=self._source(root,original)
            hours,provenance=load_original_arad(source,meta)
            row=hours[first]
            self.assertAlmostEqual(row["GHI_kwh_m2_hour"],.3)
            self.assertAlmostEqual(row["DNI_kwh_m2_hour"],.7)
            self.assertIsNone(row["DHI_kwh_m2_hour"])
            self.assertAlmostEqual(row["LW_kwh_m2_hour"],.31)
            self.assertEqual(row["DHI_good_minutes"],59)
            self.assertFalse(row["all_four_complete_q1"])
            self.assertEqual(provenance["quality_counts"]["DHI_q3"],1)
            self.assertFalse(provenance["ground_archive_redistribution_permitted"])

    def test_partial_source_hours_must_not_be_imputed_or_rescaled(self):
        with tempfile.TemporaryDirectory() as loc:
            root=Path(loc);dt=START+timedelta(hours=12)
            data=[((dt+timedelta(minutes=i)).isoformat(),{}, {})
                  for i in range(59)]
            source,meta=self._source(root,data)
            hourly,_=load_original_arad(source,meta)
            for ch in ARAD_COLS:
                self.assertIsNone(hourly[dt][ch+"_kwh_m2_hour"])
            self.assertEqual(hourly[dt]["source_minute_count"],59)

    def test_duplicate_minute_and_wrong_source_hash_rejected(self):
        with tempfile.TemporaryDirectory() as loc:
            root=Path(loc);dt=START
            source,meta=self._source(root,[(dt.isoformat(),{},{}),
                                           (dt.isoformat(),{},{})])
            with self.assertRaisesRegex(ValueError,"duplicate|not chronological"):
                load_original_arad(source,meta)
            orig=json.loads(meta.read_text());orig["original_source_sha256"]="b"*64
            meta.write_text(json.dumps(orig))
            with self.assertRaisesRegex(ValueError,"bytes"):
                load_original_arad(source,meta)

    def test_fixed_hourly_pairs_no_ground_gives_null_metrics_not_fake_zero(self):
        initial=START+timedelta(hours=11)
        nasa={("graz_station30",initial):{
            "GHI":.4,"DNI":.6,"DHI":.13,
            "solar_coszen_noaa_midpoint":.6}}
        for key in nasa.copy():
            nasa[("nasa_gcm_cell",key[1])]=dict(nasa[key])
        # Add one UTC source hour in every season; ground remains absent.
        for month in (4,7,10):
            h=datetime(2012,month,15,11,tzinfo=timezone.utc)
            for site in SITES:
                nasa[(site,h)]={"GHI":.2,"DNI":.3,"DHI":.1,
                    "solar_coszen_noaa_midpoint":.8}
        rows,results=compare({},nasa)
        self.assertEqual(len(rows),24)
        for result in results:
            self.assertEqual(result["independent_ground_q1_paired_hours"],0)
            self.assertIsNone(result["mae_kwh_m2_hour"])
            self.assertIsNone(result["pearson_r"])
            self.assertFalse(result["satellite_is_independent_ground_observation"])

    def test_validated_hourly_comparison_is_not_model_as_truth(self):
        idx={}
        ground={}
        for i in range(40):
            dt=START+timedelta(hours=i)
            idx[("graz_station30",dt)]={"GHI":.2+.01*i,"DNI":.4+.02*i,
                "DHI":.1+.005*i,"solar_coszen_noaa_midpoint":.8}
            idx[("nasa_gcm_cell",dt)]=dict(idx[("graz_station30",dt)])
            ground[dt]={ch+"_kwh_m2_hour":
                 idx[("graz_station30",dt)][ch]-.05 for ch in ("GHI","DNI","DHI")}
        # Seasonal metric function expects source windows represented in
        # all seasons, as in the real 2012–14 immutable NASA archive.
        for month in (4,7,10):
            h=datetime(2012,month,15,11,tzinfo=timezone.utc)
            for site in SITES:
                idx[(site,h)]={"GHI":.2,"DNI":.3,"DHI":.1,
                              "solar_coszen_noaa_midpoint":.8}
        rows,summary=compare(ground,idx)
        annual=next(z for z in summary if z["site"]=="graz_station30"
                   and z["channel"]=="GHI" and z["season"]=="ANNUAL")
        self.assertEqual(annual["independent_ground_q1_paired_hours"],40)
        self.assertAlmostEqual(annual["mean_bias_nasa_minus_ground_kwh_m2_hour"],.05)
        self.assertAlmostEqual(annual["pearson_r"],1.)
        self.assertFalse(annual["satellite_is_independent_ground_observation"])

if __name__=="__main__":
    unittest.main()
