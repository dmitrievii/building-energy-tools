"""P6.2B independent solar unit and climatology source contracts."""
from __future__ import annotations
import calendar,csv,tempfile
from pathlib import Path
import unittest
from p6_2b_solar_bias_triangulation import (
    parse_power,parse_pvgis,pv_request,power_request,statistics,observed_station,
)

def pvgis_fixture():
    return {"inputs":{"meteo_data":{"radiation_db":"PVGIS-ERA5"}},
            "outputs":{"monthly":[{"year":y,"month":m,"H(h)_m":100.0}
                                  for y in range(2005,2015) for m in range(1,13)]}}
def power_fixture(unit="kW-hr/m^2/day"):
    return {"header":{"parameter_information":{"ALLSKY_SFC_SW_DWN":{"units":unit}}},
            "properties":{"parameter":{"ALLSKY_SFC_SW_DWN":{
                f"{y}{m:02d}":3.0 for y in range(2005,2015) for m in range(1,13)}}}}

class ExternalSolarContracts(unittest.TestCase):
    def test_pvgis_is_monthly_total_not_daily_average(self):
        db,v=parse_pvgis(pvgis_fixture())
        self.assertEqual(db,"PVGIS-ERA5")
        self.assertEqual(len(v),120)
        self.assertEqual(statistics(v)["mean_annual_kwh_m2"],1200.)

    def test_power_monthly_daily_average_to_monthly_energy(self):
        p,unit=parse_power(power_fixture())
        self.assertEqual(len(p),120)
        self.assertAlmostEqual(p[2012,2],87.)
        self.assertAlmostEqual(p[2014,2],84.)
        self.assertAlmostEqual(statistics(p)["mean_annual_kwh_m2"],3*365.2)

    def test_power_year13_is_annual_record_not_extra_month(self):
        data=power_fixture()
        values=data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
        for year in range(2005,2015):
            values[f"{year}13"]=3.0
        monthly,unit=parse_power(data)
        self.assertEqual(len(monthly),120)
        self.assertAlmostEqual(monthly[2012,2],87.)

    def test_power_invalid_month14_is_rejected(self):
        data=power_fixture()
        data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]["201414"]=3.0
        with self.assertRaisesRegex(ValueError,"unexpected non-calendar month"):
            parse_power(data)

    def test_power_unit_unknown_fails_without_reinterpretation(self):
        with self.assertRaisesRegex(ValueError,"unit missing/changed"):
            parse_power(power_fixture("MJ/m^2/day"))

    def test_external_coordinate_fixed(self):
        self.assertIn("lat=47.08",pv_request(47.08,15.448056,"PVGIS-ERA5"))
        self.assertIn("latitude=46.875",power_request(46.875,15.375))

    def test_station_csv_unverified_observation_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"station.csv"
            cols=["date_geo_moz_utc_label","year","month","day",
                  "trusted_daily_kwh_m2","q21"]
            with path.open("w",encoding="utf8",newline="") as f:
                w=csv.DictWriter(f,fieldnames=cols)
                w.writeheader()
                import datetime
                date=datetime.date(1995,1,1)
                while date<=datetime.date(2014,12,31):
                    w.writerow(dict(zip(cols,[date.isoformat(),date.year,date.month,
                                              date.day,2.,"20" if date.day!=13 else "0"])))
                    date+=datetime.timedelta(days=1)
            with self.assertRaisesRegex(ValueError,"Unverified station GHI"):
                observed_station(path)

    def test_station_valid_20year_dates(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"station.csv"
            cols=["date_geo_moz_utc_label","year","month","day",
                  "trusted_daily_kwh_m2","q21"]
            with path.open("w",encoding="utf8",newline="") as f:
                w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
                import datetime
                date=datetime.date(1995,1,1)
                while date<=datetime.date(2014,12,31):
                    w.writerow(dict(zip(cols,[date.isoformat(),date.year,date.month,
                                              date.day,2.,20])))
                    date+=datetime.timedelta(days=1)
            months=observed_station(path)
            self.assertEqual(len(months),120)
            self.assertEqual(months[2012,2],58.)

if __name__=="__main__":
    unittest.main()
