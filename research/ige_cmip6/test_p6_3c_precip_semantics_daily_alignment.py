"""IGE P6.3C GeoSphere official precipitation sentinel and time label science contracts."""
from __future__ import annotations
import unittest,math,json
from datetime import date,timedelta
from pathlib import Path
from p6_3c_precip_semantics_daily_alignment import (
    SOURCE_FIELDS,SOURCE_UNITS,DONOR_IDS,LAGS,
    metadata_contract,decode_rain,parse_donor_block,lagged,
    nearest_km,wet_dry
)

def metadata():
    parameters=[]
    rr_description=("Niederschlag, 24-Stundensumme der Einminutenwerte von "
       "06:01 UTC bis 06:00 UTC des Folgetags, -1=kein Niederschlag, "
       "0=weniger als 1/10 mm")
    solar=("Globalstrahlung, kalibrierte 24-Stundensumme aus den Stundenwerten "
           "0-24 Uhr MOZ (23 Vortag - 23 Tag UTC)")
    for key,unit in SOURCE_UNITS.items():
        des=rr_description if key=="rr" else solar if key=="cglo_j" \
            else "Lufttemperatur in 2m Höhe, Mittelwert berechnet aus (tlmax + tlmin)/2" \
            if key=="tl_mittel" else key
        parameters.append({"name":key,"unit":unit,"description":des})
        parameters.append({"name":key+"_flag","unit":"code",
            "description":rr_description if key=="rr" else des})
    stations=[{"id":n,"name":f"station{n}","lat":47.1,"lon":15.44,
               "has_global_radiation":True} for n in (30,*DONOR_IDS)]
    return {"parameters":parameters,"stations":stations}

class GeoSphereRainAndTemporalContract(unittest.TestCase):
    def test_official_minus_one_is_verified_dry_zero_is_trace(self):
        self.assertEqual(decode_rain(-1,20),(0.,"verified_no_precipitation",True))
        self.assertEqual(decode_rain("0",20),(0.,"trace_below_0p1_mm",True))
        self.assertEqual(decode_rain(0.1,20),(.1,"light_0p0_to_1p0_mm",True))
        self.assertEqual(decode_rain(1.0,20),(1.,"wet_ge_1mm",True))

    def test_previously_unchecked_q21_stays_unchecked_and_raw_preserved(self):
        self.assertEqual(decode_rain(-1,0),(None,"missing_or_unchecked",False))
        self.assertEqual(decode_rain(-1,None),(None,"missing_or_unchecked",False))
        self.assertEqual(decode_rain(None,20),(None,"missing_or_unchecked",False))
        for code in (-0.1,-2,-999):
            with self.assertRaisesRegex(ValueError,"Unknown negative"):
                decode_rain(code,20)

    def test_provider_sentinel_unit_or_integration_change_must_fail_closed(self):
        m=metadata()
        fields,stations=metadata_contract(m)
        self.assertEqual(len(DONOR_IDS),3)
        self.assertIn("rr",fields)
        for malformed in ("-1=missing", "-1=trace precipitation", "-1=kein Messwert"):
            q=metadata()
            next(p for p in q["parameters"] if p["name"]=="rr")["description"]=(
                q["parameters"][4]["description"].replace("-1=kein Niederschlag",malformed))
            with self.assertRaisesRegex(ValueError,"changed official rr"):
                metadata_contract(q)
        q=metadata()
        next(p for p in q["parameters"] if p["name"]=="cglo_j")["unit"]="W/m²"
        with self.assertRaisesRegex(ValueError,"unit mismatch"):
            metadata_contract(q)

    def test_official_window_fields_not_treated_identically(self):
        rr=next(p for p in metadata()["parameters"] if p["name"]=="rr")
        solar=next(p for p in metadata()["parameters"] if p["name"]=="cglo_j")
        self.assertIn("06:01 UTC",rr["description"])
        self.assertIn("23 Vortag - 23 Tag UTC",solar["description"])

    def test_native_donor_daily_meteorology_and_solar_reconstruction(self):
        d=date(2005,1,1);dates=[]
        while d.year==2005:dates.append(d);d+=timedelta(days=1)
        fields={}
        for key,unit in SOURCE_UNITS.items():
            vals=([360.]*365 if key=="cglo_j" else
                  [-1.,0.,1.2]+[-1.]*362 if key=="rr" else [10.]*365)
            qc=[20]*365;qc[8]=0
            fields[key]={"unit":unit,"data":vals}
            fields[key+"_flag"]={"data":qc}
        src={"timestamps":[d.isoformat()+"T00:00:00+00:00" for d in dates],
             "features":[{"properties":{"station":53,"parameters":fields}}]}
        rows,counts=parse_donor_block(src,53,2005,2005)
        self.assertEqual(len(rows),365)
        self.assertEqual(rows[0]["precipitation_mm_day_clean"],0.)
        self.assertEqual(rows[0]["precipitation_class"],"verified_no_precipitation")
        self.assertEqual(rows[1]["precipitation_class"],"trace_below_0p1_mm")
        self.assertAlmostEqual(rows[1]["ghi_kwh_m2_day"],1.)
        self.assertIsNone(rows[8]["ghi_kwh_m2_day"])
        self.assertEqual(counts["cglo_j_accepted"],364)

    def test_calendar_alignment_rejects_malformed_donor_dates(self):
        src={"timestamps":[],"features":[]}
        with self.assertRaisesRegex(ValueError,"calendar invalid"):
            parse_donor_block(src,53,2005,2005)

    def test_deterministic_daily_lags_no_station_donor_date_pairing(self):
        rows=[]
        for day in range(1,29):
            rows.append({"station_id":30,"date":f"2010-07-{day:02d}",
                         "year":2010,"month":7,
                         "ghi_kwh_m2_day":float(day),
                         "temperature_air_c":float(day+1),
                         "relative_humidity_pct":float(60-day/10),
                         "precipitation_mm_day_clean":0.,
                         "precipitation_class":"verified_no_precipitation"})
        result=lagged(rows)
        idx={(r["season"],r["relationship"],r["weather_label_day_shift"]):r
             for r in result}
        self.assertEqual(len(LAGS),5)
        self.assertEqual(idx["JJA","temperature_ghi",0]["n_complete"],28)
        self.assertEqual(idx["JJA","temperature_ghi",1]["n_complete"],27)
        self.assertEqual(idx["JJA","precipitation_ghi",0]["n_complete"],28)
        self.assertAlmostEqual(idx["JJA","temperature_ghi",0]["pearson"],1.)
        self.assertEqual(idx["JJA","temperature_ghi",0]["status"],"INSUFFICIENT_QC_SAMPLE")

    def test_censored_rain_excluded_from_numeric_amount_correlation(self):
        rows=[]
        for day in range(1,31):
            cls="trace_below_0p1_mm" if day<6 else "wet_ge_1mm"
            rows.append({"station_id":30,"date":f"2010-06-{day:02d}",
                         "year":2010,"month":6,"ghi_kwh_m2_day":float(day),
                         "temperature_air_c":float(day),
                         "relative_humidity_pct":40.,
                         "precipitation_mm_day_clean":0. if day<6 else float(day),
                         "precipitation_class":cls})
        actual=next(r for r in lagged(rows)
                    if r["season"]=="JJA" and r["relationship"]=="precipitation_ghi"
                    and r["weather_label_day_shift"]==0)
        self.assertEqual(actual["n_complete"],25)
        self.assertEqual(actual["excluded_trace_censored_rain_pairs"],5)
        cats=[x for x in wet_dry(rows) if x["season"]=="JJA"]
        self.assertEqual(sum(c["solar_available_days"] for c in cats),30)

    def test_three_preselected_stations_not_chosen_by_climate_scores(self):
        self.assertEqual(DONOR_IDS,(53,94,200))
        dist=nearest_km({"lat":47.08,"lon":15.448056},
                        {"lat":47.07361,"lon":15.59222})
        self.assertTrue(8<dist<14)

if __name__=="__main__":unittest.main()
