"""IGE P6.3C original GeoSphere hourly radiation QC and 23–23 UTC solar integration contracts."""
from __future__ import annotations
import tempfile,unittest,json
from datetime import datetime,timedelta,timezone,date
from pathlib import Path
from p6_3c_hourly_original_source_alignment import (
    LABELS,EXPECTED_HOURS,hourly_metadata_qa,reconstruct
)

class HourlyNativeQualityContracts(unittest.TestCase):
    def test_original_hourly_solar_calibrated_hour_mean_not_daily_energy(self):
        self.assertEqual(EXPECTED_HOURS,3652*24)
        self.assertEqual(set(LABELS),
                         {"hour_value_start_stamped","hour_value_end_stamped"})

    def test_hourly_original_sha_and_physical_units_must_be_verified(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"hourly_raw_qc.csv.gz"
            p.write_bytes(b"immutable original hourly compressed source bytes")
            h=hashlib.sha256(p.read_bytes()).hexdigest()
            q={"status":"PASS","station_id":30,"year":2010,"expected_hours":8760,
               "hourly_csv_gzip_sha256":h,
               "parameter_metadata":{
                  "cglo":{"description":"Globalstrahlung, kalibrierter Stunden-Mittelwert",
                          "unit":"W/m²"},"tl":{"unit":"°C"}}}
            self.assertEqual(hourly_metadata_qa(q,2010,p),h)
            q["hourly_csv_gzip_sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"digest drift"):
                hourly_metadata_qa(q,2010,p)

    def test_hourly_cglo_not_assumed_qc_even_when_daily_verified(self):
        start=datetime(2010,6,1,23,tzinfo=timezone.utc)
        rows=[{"datetime_utc":start+timedelta(hours=i),
               "solar_Wm2_raw":100.,"solar_checked":False,
               "solar_q21":0} for i in range(25)]
        measured=[{"date":"2010-06-02","year":2010,"month":6,
                   "ghi_kwh_m2_day":2.4}]
        first=reconstruct(rows,measured,"hour_value_start_stamped")[0]
        second=reconstruct(rows,measured,"hour_value_end_stamped")[0]
        self.assertAlmostEqual(first["raw_hourly_sum_kwh_m2"],2.4)
        self.assertAlmostEqual(second["raw_hourly_sum_kwh_m2"],2.4)
        self.assertFalse(first["all_24_hourly_solar_q21_approved"])
        self.assertFalse(second["all_24_hourly_solar_q21_approved"])
        self.assertIn("UNVERIFIED",first["readiness"])
        self.assertEqual(first["original_official_qc_daily_GHI_kwh_m2"],2.4)

    def test_hourly_timestamp_conventions_change_edge_hour_contribution(self):
        start=datetime(2010,6,1,23,tzinfo=timezone.utc)
        rows=[{"datetime_utc":start+timedelta(hours=i),
               "solar_Wm2_raw":0. if i==0 else 100. if i<24 else 500.,
               "solar_checked":False} for i in range(25)]
        obs=[{"date":"2010-06-02","year":2010,"month":6,
              "ghi_kwh_m2_day":2.3}]
        s=reconstruct(rows,obs,"hour_value_start_stamped")[0]
        e=reconstruct(rows,obs,"hour_value_end_stamped")[0]
        self.assertAlmostEqual(s["raw_hourly_sum_kwh_m2"],2.3)
        self.assertAlmostEqual(e["raw_hourly_sum_kwh_m2"],2.8)
        self.assertNotEqual(s["raw_hourly_sum_kwh_m2"],e["raw_hourly_sum_kwh_m2"])

    def test_source_hourly_boundary_missing_prior_year_cannot_be_infilled(self):
        start=datetime(2005,1,1,0,tzinfo=timezone.utc)
        rows=[{"datetime_utc":start+timedelta(hours=i),
               "solar_Wm2_raw":5.,"solar_checked":False} for i in range(24)]
        obs=[{"date":"2005-01-01","year":2005,"month":1,
              "ghi_kwh_m2_day":.2}]
        first=reconstruct(rows,obs,"hour_value_start_stamped")[0]
        self.assertIsNone(first["raw_hourly_sum_kwh_m2"])
        self.assertFalse(first["original_hourly_complete"])

if __name__=="__main__":unittest.main()
