"""P6.2B GMFD attribution fail-closed and original NASA native NetCDF contracts."""
from __future__ import annotations
import csv,tempfile
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
import unittest
from p6_2b_gmfd_direct_source_forensics import (
    COORD,NCAR_PRODUCT,verify_original_nasa,sha,
)

class DirectSourceContracts(unittest.TestCase):
    def test_archival_gmfd_not_assumed_nasa_processed(self):
        self.assertEqual(COORD,(46.875,15.375))
        self.assertIn("/0.25deg/daily/",NCAR_PRODUCT)
        self.assertTrue(NCAR_PRODUCT.endswith("dswrf_0p25_daily_2005-2005.nc"))

    def create_p6_csv(self,root,bad_date=None):
        folder=Path(root)
        with (folder/"joint_daily_raw.csv").open("w",encoding="utf8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=["year","month","day","rsds"])
            w.writeheader()
            d=date(2005,1,1)
            while d.year==2005:
                energy=202 if bad_date is not None and d==bad_date else 200
                w.writerow({"year":d.year,"month":d.month,"day":d.day,"rsds":energy})
                d+=timedelta(days=1)
        return folder

    def fake_payload(self):
        days=[];d=date(2005,1,1)
        while d.year==2005:
            days.append((d.year,d.month,d.day))
            d+=timedelta(days=1)
        return {"days":days,"values":[200.0]*len(days),
                "lat":46.875,"lon":15.375,"unit":"W m-2","calendar":"gregorian"}

    @patch("p6_daily_multivariable.fetch_one")
    @patch("p6_daily_multivariable.catalog")
    def test_native_source_matches_accepted_p6_artifact(self,cat,fetch):
        cat.return_value={2005:"approved_original_nasa_subset.nc"}
        fetch.return_value=(self.fake_payload(),{"sha256":"original_provider_sha",
                      "url":"https://ds.nccs.nasa.gov/original_nc"})
        with tempfile.TemporaryDirectory() as root:
            target=self.create_p6_csv(root)
            r=verify_original_nasa(target,target)
        self.assertEqual(r["status"],"PASS_RAW_NATIVE_NASA_CONFIRMATION")
        self.assertAlmostEqual(r["annual_kwh_m2"],365*200*.024)
        self.assertEqual(r["grid"],[46.875,15.375])

    @patch("p6_daily_multivariable.fetch_one")
    @patch("p6_daily_multivariable.catalog")
    def test_native_discrepancy_must_fail(self,cat,fetch):
        cat.return_value={2005:"original.nc"}
        fetch.return_value=(self.fake_payload(),{"sha256":"a","url":"https://example.org/src"})
        with tempfile.TemporaryDirectory() as root:
            folder=self.create_p6_csv(root,bad_date=date(2005,6,1))
            with self.assertRaisesRegex(ValueError,"disagrees"):
                verify_original_nasa(folder,folder)

if __name__=="__main__":unittest.main()
