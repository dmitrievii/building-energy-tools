"""P7B.2: no false source-humidity closure, heldout observed solar QA, new EPW."""
from __future__ import annotations
import csv,math,tempfile,unittest
from collections import defaultdict
from datetime import date,timedelta
from pathlib import Path
from statistics import fmean
from p7b2_hourly_physically_bounded_synthesis import (
    solve_moisture,monthly_factors,holdout_climatology,write_epw,regularize_hourly_humidity_continuity,
    P_PROXY,TRAIN_YEARS,EXCLUDED_SOURCE_CONFLICT_YEARS,HOLDOUT_YEARS,
    RH_MIN,RH_MAX,SOLAR_FACTOR_BOUNDS,NONLEAP_HOURS)
from p7b_daily_to_hourly_cmip6_pilot import synthesize_day,q_from_t_rh

class P7B2SourcePhysicalContractTests(unittest.TestCase):
    def temps(self):
        return [15+7*math.cos(2*math.pi*(h-15)/24) for h in range(24)]

    def test_joint_daily_hurs_and_huss_both_exact_when_physically_reachable(self):
        t=self.temps()
        target=fmean(q_from_t_rh(v,60,P_PROXY) for v in t)
        rh,dew,check=solve_moisture(t,60,target)
        self.assertEqual(check["status"],"JOINT_HURS_HUSS_CLOSED_BOUNDED_HOURLY_RH")
        self.assertTrue(check["daily_hurs_conserved"] and check["daily_huss_conserved"])
        self.assertAlmostEqual(fmean(rh),60,places=8)
        self.assertTrue(all(v<=t0+1e-6 for v,t0 in zip(dew,t)))
        self.assertAlmostEqual(check["reconstructed_minus_source_huss_kg_kg"],0,places=8)

    def test_feasible_nonflat_hourly_rh_closes_mean_hurs_and_huss(self):
        t=self.temps()
        # Source q between flat RH and warm-biased original source distribution.
        desired=fmean(q_from_t_rh(x,60+10*(x-fmean(t))/7,P_PROXY)
                      for x in t)
        rh,dew,check=solve_moisture(t,60,desired)
        self.assertEqual(check["status"],"JOINT_HURS_HUSS_CLOSED_BOUNDED_HOURLY_RH")
        self.assertLess(abs(check["reconstructed_minus_source_huss_kg_kg"]),1e-9)
        self.assertLess(abs(check["reconstructed_minus_source_hurs_pp"]),1e-8)
        self.assertTrue(all(RH_MIN<=v<=RH_MAX for v in rh))

    def test_relax_hurs_with_explicit_flags_when_q_outside_joint_family(self):
        t=self.temps()
        q=fmean(q_from_t_rh(x,95,P_PROXY) for x in t)
        rh,dew,check=solve_moisture(t,30,q)
        self.assertEqual(check["status"],"HUSS_PRIORITIZED_HURS_RELAXED_CONSTANT_RH_PROXY")
        self.assertTrue(check["daily_huss_conserved"])
        self.assertFalse(check["daily_hurs_conserved"])
        self.assertAlmostEqual(fmean(rh),95,places=6)
        self.assertTrue(all(x<=t0+1e-8 for x,t0 in zip(dew,t)))

    def test_saturation_does_not_fake_source_huss_or_supersaturation(self):
        t=self.temps()
        high=fmean(q_from_t_rh(v,100,P_PROXY) for v in t)*1.13
        rh,dew,check=solve_moisture(t,60,high)
        self.assertEqual(check["status"],"SOURCE_HUSS_UNACHIEVABLE_AT_PRESSURE_WITH_SATURATION_BOUND")
        self.assertFalse(check["daily_huss_conserved"])
        self.assertTrue(all(v==100 for v in rh))
        self.assertTrue(all(abs(a-b)<1e-7 for a,b in zip(t,dew)))
        self.assertGreater(abs(check["reconstructed_minus_source_huss_kg_kg"]),0)

    def test_all_year_temporal_smoothing_removes_99pp_jump_and_recomputes_native_source_residuals(self):
        records=[];audit=[]
        base=date(2013,1,1)
        for i in range(365):
            d=(base+timedelta(days=i)).isoformat()
            raw_rh=[1. if h<12 else 100. for h in range(24)]
            qtarget=fmean(q_from_t_rh(15,v,P_PROXY) for v in raw_rh)
            audit.append({
                "date":d,"status":"JOINT_HURS_HUSS_CLOSED_BOUNDED_HOURLY_RH",
                "source_hurs_pct":fmean(raw_rh),
                "source_huss_kg_kg":qtarget,
                "reconstructed_minus_source_huss_kg_kg":0.,
                "reconstructed_minus_source_hurs_pp":0.})
            for v in raw_rh:
                records.append({"RH_pct":v,"T_C":15.,"pressure_pa":P_PROXY,
                                "date":d})
        report=regularize_hourly_humidity_continuity(records,audit)
        self.assertGreater(report["source_RH_before_continuity_max_jump_pp"],98.)
        self.assertLess(report["maximum_observed_adjacent_hour_RH_change_pp"],20.)
        self.assertEqual(report["number_adjacent_hours_RH_jump_above_20pp"],0)
        self.assertEqual(sum(report["final_native_daily_hurs_huss_conservation_classes"].values()),365)
        self.assertTrue(all(1<=r["RH_pct"]<=100 for r in records))
        self.assertTrue(all(r["dewpoint_C"]<=15+1e-8 for r in records))
        self.assertEqual(audit[50]["pre_continuity_humidity_stage"],
                         "JOINT_HURS_HUSS_CLOSED_BOUNDED_HOURLY_RH")
        self.assertNotEqual(audit[50]["status"],audit[50]["pre_continuity_humidity_stage"])
        self.assertTrue(all("reconstructed_minus_source_huss_kg_kg" in d for d in audit))
        self.assertEqual(report["prefilter_global_RH_smoothing_window_hours"],7)
        self.assertIn("post_smoothing_bounded_source_restoration_stage_counts",report)
        # Arbitrarily sharp original daily RH cannot always preserve native
        # q and hurs under a 20 pp/hour rate constraint. Report the residual.
        self.assertEqual(sum(report["final_native_daily_hurs_huss_conservation_classes"].values()),365)
        self.assertTrue(any(abs(d["reconstructed_minus_source_huss_kg_kg"])>1e-9
                            for d in audit))

    def test_flat_compatible_source_remains_365_days_jointly_conserved(self):
        original=[];audit=[]
        first=date(2013,1,1)
        qt=q_from_t_rh(20,65,P_PROXY)
        for i in range(365):
            d=(first+timedelta(days=i)).isoformat()
            audit.append({"date":d,"status":"JOINT_HURS_HUSS_CLOSED_BOUNDED_HOURLY_RH",
                "source_hurs_pct":65.,"source_huss_kg_kg":qt,
                "reconstructed_minus_source_huss_kg_kg":0.,
                "reconstructed_minus_source_hurs_pp":0.})
            original.extend({"date":d,"RH_pct":65.,"T_C":20.,
                             "pressure_pa":P_PROXY} for _ in range(24))
        r=regularize_hourly_humidity_continuity(original,audit)
        self.assertEqual(r["final_native_daily_hurs_huss_conservation_classes"]["both_conserved"],365)
        self.assertEqual(r["number_adjacent_hours_RH_jump_above_20pp"],0)
        self.assertAlmostEqual(r["maximum_observed_adjacent_hour_RH_change_pp"],0)

    def test_model_station_calibration_train_only_and_quarantine(self):
        rows=[];station={}
        for year in range(2005,2015):
            start=date(year,1,1)
            station[year]=[]
            n=366 if year in (2008,2012) else 365
            for i in range(365):
                d=start+timedelta(days=i)
                rows.append({"year":str(year),"month":str(d.month),
                    "rsds_kwh_m2_day": "4"})
            for i in range(n):
                day=start+timedelta(days=i)
                station[year].append((day.month,2.5 if year in TRAIN_YEARS else 2.6))
        factors,series,model,ground=monthly_factors(rows,station)
        self.assertEqual(len(series),12)
        self.assertTrue(all(abs(x-.625)<.001 for x in factors.values()))
        self.assertTrue(all(x["holdout_2012_2014_excluded_from_fit"] for x in series))
        self.assertTrue(all(x["2010_2011_excluded_source_daily_10min_mismatch"] for x in series))
        months,summary=holdout_climatology(factors,model,ground)
        self.assertEqual(len(months),12)
        self.assertAlmostEqual(summary["holdout_annual_pct_before"],100*(4/2.6-1),places=2)
        self.assertAlmostEqual(summary["holdout_annual_pct_after"],100*(2.5/2.6-1),places=2)

    def test_full_8760_epw_35_columns_no_fabricated_wind_direction(self):
        from p7b_daily_to_hourly_cmip6_pilot import epw_rows
        r={"model":"CanESM5","scenario":"historical","hurs":"66",
           "huss":"0.008","tas_c":"14","tasmin_c":"9","tasmax_c":"19",
           "sfcWind":"2","pr_mm_day":"1","rsds_kwh_m2_day":"3",
           "rlds_kwh_m2_day":"7"}
        out=[]
        start=date(2013,1,1)
        for i in range(365):
            d=start+timedelta(days=i);r["date"]=d.isoformat()
            h,_=synthesize_day(r,7313);out.extend(h)
        self.assertEqual(len(out),8760)
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/"research.epw"
            sha=write_epw(f,out)
            self.assertEqual(len(sha),64)
            with f.open("r",newline="",encoding="utf8") as inp:
                rr=list(csv.reader(inp))
            self.assertEqual(len(rr),8768)
            self.assertEqual(rr[8][:5],["2013","1","1","1","60"])
            self.assertEqual(rr[-1][:5],["2013","12","31","24","60"])
            self.assertTrue(all(len(x)==35 for x in rr[8:]))
            self.assertEqual(rr[8][20],"999")

if __name__=="__main__":
    unittest.main()
