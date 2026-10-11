"""P7A: scientific EPW calendar/format, source immutability and fail-closed tests."""
import csv,hashlib,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from p7a_historical_epw_reference import (
 YEAR,OFFSET,EPW_COLUMNS,M_VARS,START_UTC,START_LOCAL,EXPECTED_HOURS,
 LAST_UTC,power_url,as_utc,dewpoint_c,original_power_met,make_rows,
 write_epw,load_solar,finite_range,choose_source
)

class FirstHourlyEPWReference(unittest.TestCase):
    def test_epw_2013_is_exact_cet_no_dst_and_has_cross_year_boundary(self):
        self.assertEqual(EXPECTED_HOURS,8760)
        self.assertEqual(START_UTC.isoformat(),"2012-12-31T23:00:00+00:00")
        self.assertEqual(LAST_UTC.isoformat(),"2013-12-31T22:00:00+00:00")
        self.assertEqual(START_LOCAL.isoformat(),"2013-01-01T00:00:00+01:00")
        self.assertIn("time-standard=UTC",power_url())
        self.assertEqual(as_utc("2013-06-01T02:00:00Z").hour,2)
        with self.assertRaisesRegex(ValueError,"UTC"):
            as_utc("2013-06-01T04:00:00+02:00")

    def test_temperature_relative_humidity_dewpoint_physical_constraint(self):
        for t,rh in ((0,50),(21,44),(-10,90),(35,100)):
            td=dewpoint_c(t,rh)
            self.assertLessEqual(td,t+1e-7)
        self.assertAlmostEqual(dewpoint_c(20,100),20,places=6)
        with self.assertRaises(ValueError):
            dewpoint_c(20,0)
        self.assertFalse(finite_range(None,0,100))

    def test_nasa_missing_hourly_variable_original_units_and_utc_rejected(self):
        keys=[(START_UTC+timedelta(hours=h)).strftime("%Y%m%d%H")
              for h in range(EXPECTED_HOURS)]
        vals={"T2M":10,"T2MDEW":5,"RH2M":60,"PS":97,
              "WS10M":2,"WD10M":180,"ALLSKY_SFC_LW_DWN":310,
              "PRECTOT":0}
        units={"T2M":"C","T2MDEW":"C","RH2M":"%","PS":"kPa",
             "WS10M":"m/s","WD10M":"Degrees",
             "ALLSKY_SFC_LW_DWN":"W/m^2","PRECTOT":"mm/hour"}
        obj={"messages":[],"header":{"fill_value":-999},
             "parameters":{p:{"units":units[p]} for p in M_VARS},
             "properties":{"parameter":{p:{k:vals[p] for k in keys}
                               for p in M_VARS}}}
        met,meta=original_power_met(json.dumps(obj).encode(),"https://power.nasa/test")
        self.assertEqual(len(met),8760)
        self.assertEqual(met[START_UTC]["PS"],97)
        self.assertEqual(meta["raw_utc_hours"],8760)
        obj["parameters"]["PS"]["units"]="hPa"
        with self.assertRaisesRegex(ValueError,"unknown unit"):
            original_power_met(json.dumps(obj).encode(),"x")
        obj["parameters"]["PS"]["units"]="kPa"
        del obj["properties"]["parameter"]["WD10M"][keys[-1]]
        with self.assertRaisesRegex(ValueError,"missing mandatory"):
            original_power_met(json.dumps(obj).encode(),"x")

    def test_full_epw_35_columns_no_synthetic_cloud_fallback_and_correct_hour_24(self):
        station={};sol={};met={}
        for i in range(EXPECTED_HOURS):
            dt=START_UTC+timedelta(hours=i)
            station[dt]={"tl_accepted":"15","rf_accepted":"70",
                         "p_accepted":"974","ff_accepted":"2.5"}
            sol[dt]={"ghi":100.,"dni":200.,"dhi":40.,
                     "closure_review":i==33}
            met[dt]={"T2M":16.,"T2MDEW":10.,"RH2M":65.,"PS":97.3,
                     "WS10M":3.,"WD10M":240.,
                     "ALLSKY_SFC_LW_DWN":320.,"PRECTOT":0.}
        rows,lineage,counts,risk=make_rows(station,sol,met)
        self.assertEqual(len(rows),8760)
        self.assertEqual(len(lineage),8760)
        self.assertEqual(counts["tl_station_qc"],8760)
        self.assertEqual(risk["nasa_solar_component_review_hours"],1)
        self.assertEqual(rows[0][0:5],[2013,1,1,1,60])
        self.assertEqual(rows[23][0:5],[2013,1,1,24,60])
        self.assertEqual(rows[-1][0:5],[2013,12,31,24,60])
        self.assertEqual(rows[0][8],70)
        self.assertEqual(rows[0][9],97400.)
        self.assertEqual(rows[0][13:16],[100.,200.,40.])
        self.assertEqual(rows[0][22:24],[99,99])
        self.assertEqual(rows[0][28],999)
        self.assertEqual(rows[0][29],.999)
        self.assertTrue(all(len(x)==EPW_COLUMNS for x in rows))
        with tempfile.TemporaryDirectory() as p:
            file=Path(p)/"historic.epw"
            digest=write_epw(file,rows)
            self.assertEqual(digest,hashlib.sha256(file.read_bytes()).hexdigest())
            with file.open("r",newline="",encoding="utf8") as inp:
                data=list(csv.reader(inp))
            self.assertEqual(len(data),8768)
            self.assertEqual(data[0][0],"LOCATION")
            self.assertEqual(data[7][0],"DATA PERIODS")
            self.assertEqual(data[8][3],"1")
            self.assertEqual(data[8][4],"60")

    def test_qc_missing_fallback_nasa_is_disclosed_and_unavailable_fails(self):
        tally=__import__("collections").Counter()
        src={"tl_accepted":""}
        value,label=choose_source(src,"tl",12.5,1,(-70,70),tally)
        self.assertEqual(value,12.5)
        self.assertEqual(label,"NASA_POWER_GRID_FALLBACK")
        self.assertEqual(tally["tl_nasa_fallback"],1)
        with self.assertRaisesRegex(ValueError,"fail closed"):
            choose_source(src,"tl",None,1,(-70,70),tally)

if __name__=="__main__":unittest.main()
