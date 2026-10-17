"""Only frozen P9.1H regional cohort contracts; no weather requests."""
import unittest
from p9_1h_regional_AT_DE_CH_guard import (
    qualification_scope,read_manifest,validate_manifest)

class RegionalScope(unittest.TestCase):
    def test_countries_exact(self):
        self.assertTrue(validate_manifest(read_manifest()))
        for code in ("AT","DE","CH"):
            self.assertEqual(qualification_scope(code,"2022-01-10T00:00:00Z")[0],code)
        for code in ("FI","NL","US","FR","UK","RU"):
            with self.assertRaisesRegex(ValueError,"COUNTRY"):
                qualification_scope(code,"2022-01-10T00:00:00Z")

    def test_frozen_2022_windows_only(self):
        for date in ("2022-01-10","2022-01-16","2022-07-10","2022-07-16"):
            qualification_scope("CH",date+"T23:00:00Z")
        for date in ("2018-01-10","2019-01-10","2021-07-10","2022-01-17","2022-07-17","2023-01-10"):
            with self.assertRaisesRegex(ValueError,"WINDOW"):
                qualification_scope("AT",date+"T00:00:00Z")

    def test_utc_and_no_silent_timezone(self):
        with self.assertRaisesRegex(ValueError,"UTC"):
            qualification_scope("DE","2022-01-11T02:00:00+01:00")
        with self.assertRaisesRegex(ValueError,"UTC"):
            qualification_scope("DE","2022-01-11T02:00:00")

    def test_no_fake_science_qualification(self):
        x=read_manifest()
        for k,v in x["claims"].items():self.assertIs(v,False)
        self.assertTrue(x["data_sources"]["DE"]["strict_QN10_not_automatically_substituted_for_QN3"])
        self.assertTrue(x["data_sources"]["CH"]["existing_P8_swiss_data_are_monthly_not_hourly_skill"])

if __name__=="__main__":unittest.main()
