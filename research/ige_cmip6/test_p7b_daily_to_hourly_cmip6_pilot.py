"""P7B research-only source/calendar/daily-conservation/solar/EPW contracts."""
from __future__ import annotations
import csv,tempfile,unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from statistics import fmean
from p7b_daily_to_hourly_cmip6_pilot import (
 temperature_curve,wind_curve,rain_curve,solar_curve,dewpoint,
 synthesize_day,write_epw,epw_rows,point_weather,
 NONLEAP_HOURS,QC_SCIENCE_STATUS,P_PROXY,STATION_LAT,STATION_LON)

class DailyToHourlyCMIP6PilotTests(unittest.TestCase):
    def make_day(self,day="2013-06-21",rain=12.,solar=7.):
        d=date.fromisoformat(day)
        return {"year":str(d.year),"month":str(d.month),"day":str(d.day),
                "date":d.isoformat(),"scenario":"historical","model":"CanESM5",
                "tas_c":20.,"tasmin_c":14.,"tasmax_c":26.,
                "hurs":65.,"huss":.009,
                "pr_mm_day":rain,"rsds_kwh_m2_day":solar,
                "rlds_kwh_m2_day":8.,"sfcWind":2.8}

    def test_native_temp_extrema_mean_exactly_and_thermodynamic_dewpoint(self):
        x=temperature_curve(20,14,26)
        self.assertEqual(len(x),24)
        self.assertAlmostEqual(min(x),14)
        self.assertAlmostEqual(max(x),26)
        self.assertAlmostEqual(fmean(x),20)
        self.assertEqual(x.index(min(x)),3)
        self.assertEqual(x.index(max(x)),15)
        self.assertLessEqual(dewpoint(21,65),21)
        # Actual original CanESM5 NEX 2013 daily native tas and tasmax/min
        # use distinct float32 rounding and can differ by 1.5e-5 K.
        rounded=temperature_curve(20.0000152587890625,14,26)
        self.assertAlmostEqual(fmean(rounded),20.0000152587890625,places=9)
        self.assertAlmostEqual(min(rounded),14,places=9)
        self.assertAlmostEqual(max(rounded),26,places=9)
        with self.assertRaisesRegex(ValueError,"midpoint"):
            temperature_curve(24,14,26)

    def test_rain_and_wind_daily_conservation_seed_reproducible(self):
        d=date(2013,9,9)
        self.assertEqual(rain_curve(0,73,d),[0.]*24)
        self.assertEqual(rain_curve(12,73,d),rain_curve(12,73,d))
        self.assertAlmostEqual(sum(rain_curve(12,73,d)),12)
        self.assertTrue(all(v>=0 for v in rain_curve(12,73,d)))
        self.assertEqual(wind_curve(2.8,73,d),wind_curve(2.8,73,d))
        self.assertAlmostEqual(fmean(wind_curve(2.8,73,d)),2.8)

    def test_radiation_ghi_daily_energy_and_dni_dhi_closure(self):
        d=date(2013,6,21)
        solar=solar_curve(7.,d)
        self.assertAlmostEqual(sum(x[0] for x in solar)/1000,7.)
        self.assertEqual(len(solar),24)
        for ghi,dni,dhi,review,geometry in solar:
            cz,toa=geometry
            self.assertGreaterEqual(ghi,0)
            self.assertGreaterEqual(dni,0)
            self.assertLessEqual(dni,1350.001)
            self.assertGreaterEqual(dhi,0)
            self.assertLessEqual(dhi,ghi+1e-8)
            self.assertAlmostEqual(ghi,dhi+dni*cz,places=5)
        self.assertTrue(any(ghi>0 for ghi,*_ in solar))
        self.assertTrue(any(ghi==0 for ghi,*_ in solar))

    def test_synthetic_day_preserves_all_eight_native_daily_quantities(self):
        src=self.make_day()
        h,check=synthesize_day(src,7313)
        self.assertEqual(len(h),24)
        self.assertAlmostEqual(fmean(x["T_C"] for x in h),20.)
        self.assertAlmostEqual(max(x["T_C"] for x in h),26.)
        self.assertAlmostEqual(min(x["T_C"] for x in h),14.)
        self.assertAlmostEqual(sum(x["rain_mm"] for x in h),12.)
        self.assertAlmostEqual(sum(x["ghi_Wh"] for x in h),7000.)
        self.assertAlmostEqual(sum(x["sky_lw_Wh"] for x in h),8000.)
        self.assertAlmostEqual(fmean(x["RH_pct"] for x in h),65.)
        self.assertAlmostEqual(fmean(x["wind_ms"] for x in h),2.8)
        self.assertTrue(check["huss_independent_constraint_closed"] is False)
        self.assertTrue(all(x["dewpoint_C"]<=x["T_C"]+1e-6 for x in h))
        self.assertLess(check["solar_partition_review_hours"],25)

    def test_winter_polar_solar_zero_and_epw_sentinels_not_fake_wind(self):
        h,_=synthesize_day(self.make_day(day="2013-01-07",rain=0,solar=.5),73)
        self.assertTrue(any(x["ghi_Wh"]==0 for x in h))
        self.assertTrue(all(x["hourly_wind_direction_source"]=="UNAVAILABLE" for x in h))
        self.assertTrue(all(x["hourly_pressure_source"].startswith("STANDARD") for x in h))
        epw=epw_rows(h)
        self.assertEqual(len(epw),24)
        self.assertTrue(all(len(x)==35 for x in epw))
        self.assertTrue(all(x[20]==999 for x in epw))
        self.assertTrue(all(x[29]==.999 for x in epw))
        self.assertEqual(epw[0][:5],[2013,1,7,1,60])
        self.assertEqual(epw[-1][:5],[2013,1,7,24,60])

    def test_historical_full_calendar_epw_no_dst_and_month_edges(self):
        allhours=[]
        start=date(2013,1,1)
        for i in range(365):
            d=start+timedelta(days=i)
            src=self.make_day(d.isoformat(),rain=(i%9)/2,solar=1.5)
            h,_=synthesize_day(src,7313)
            allhours.extend(h)
        self.assertEqual(len(allhours),NONLEAP_HOURS)
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"synthetic.epw"
            sha=write_epw(p,allhours)
            self.assertEqual(len(sha),64)
            with p.open("r",encoding="utf8",newline="") as f:
                rows=list(csv.reader(f))
            self.assertEqual(len(rows),8768)
            self.assertEqual(rows[8][:5],["2013","1","1","1","60"])
            self.assertEqual(rows[-1][:5],["2013","12","31","24","60"])
            self.assertTrue(all(len(x)==35 for x in rows[8:]))

    def test_explicit_research_status_and_missing_daily_extreme_error(self):
        self.assertIn("NOT_OBSERVED",QC_SCIENCE_STATUS)
        self.assertGreater(P_PROXY,90000)
        self.assertLess(P_PROXY,101325)
        bad=self.make_day()
        bad["tas_c"]=28.
        with self.assertRaises(ValueError):
            synthesize_day(bad,7313)

if __name__=="__main__":
    unittest.main()
