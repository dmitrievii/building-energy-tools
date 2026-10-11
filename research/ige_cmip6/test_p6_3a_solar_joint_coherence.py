"""P6.3A source identity, solar monthly closure, dependence and physics contracts."""
from __future__ import annotations
import unittest,math,copy
from pathlib import Path
from p6_3a_solar_joint_coherence import (
    METHODS,NEW,ALL_METHODS,FUTURES,HIST,PAIRS,SEASONS,
    source_folder,daily_methods,rank,corr_vectors,dependence_change,
    physical_metrics,CANONICAL_CAP,
)

class JointClimateScienceContracts(unittest.TestCase):
    def test_all_source_archive_paths_and_repaired_future_are_exact(self):
        roots=tuple(Path(name) for name in
            ("access_hist","original_hist","repair_hist",
             "access_future","original_future","repair_future"))
        cases=[
            ("ACCESS-CM2",HIST,"access_hist/ige-p6-access-historical-1995-2014"),
            ("ACCESS-CM2","ssp245-2040-2059",
             "access_future/ige-p6-access-ssp245-2040-2059"),
            ("CanESM5","ssp585-2080-2099",
             "original_future/ige-p6-CanESM5-ssp585-2080-2099"),
            ("EC-Earth3",HIST,"repair_hist/ige-p6-EC-Earth3-historical-1995-2014"),
            ("EC-Earth3","ssp245-2040-2059",
             "repair_future/ige-p6-EC-Earth3-ssp245-2040-2059"),
            ("MPI-ESM1-2-HR","ssp585-2040-2059",
             "repair_future/ige-p6-MPI-ESM1-2-HR-ssp585-2040-2059"),
        ]
        for model,window,expected in cases:
            with self.subTest(model=model,window=window):
                self.assertEqual(str(source_folder(model,window,*roots)),expected)

    def test_all_five_original_windows_and_four_methods(self):
        self.assertEqual(len(FUTURES),4)
        self.assertEqual(len(ALL_METHODS),4)
        self.assertEqual(len(PAIRS),5)
        self.assertEqual(len(SEASONS),5)
        self.assertEqual(METHODS[0],"M0_raw_nex")

    def test_M1_M2_daily_scaling_conserves_exact_original_monthly_energy(self):
        solar=[];month={};m3=[]
        for y in range(2005,2007):
            for m in range(1,13):
                for d in range(1,4):
                    solar.append({"year":y,"month":m,"day":d,
                                  "ghi_kwh_m2_day":2+m/12})
                    m3.append((2+m/12)*.70)
                raw=3*(2+m/12)
                month[y,m]={METHODS[0]:raw,METHODS[1]:raw*.70,
                            METHODS[2]:raw*.66}
        src=copy.deepcopy(solar)
        corrected=daily_methods(solar,month,m3)
        self.assertEqual(solar,src)
        self.assertEqual(len(corrected),len(solar))
        for i,row in enumerate(corrected):
            self.assertAlmostEqual(row[METHODS[0]],src[i]["ghi_kwh_m2_day"])
            self.assertAlmostEqual(row[METHODS[1]],src[i]["ghi_kwh_m2_day"]*.70)
            self.assertAlmostEqual(row[METHODS[2]],src[i]["ghi_kwh_m2_day"]*.66)
            self.assertAlmostEqual(row[NEW],m3[i])

    def test_m1_m2_must_not_silently_break_original_monthly_solar_energy(self):
        solar=[{"year":2005,"month":m,"day":1,"ghi_kwh_m2_day":4.0}
               for m in range(1,13)]
        monthly={(2005,m):{METHODS[0]:5,METHODS[1]:3,METHODS[2]:4}
                 for m in range(1,13)}
        with self.assertRaisesRegex(ValueError,"Raw monthly source"):
            daily_methods(solar,monthly,[2]*12)

    def test_corr_vectors_pearson_and_spearman_ranks(self):
        x=[float(i) for i in range(100)]
        y=[100-i for i in range(100)]
        self.assertAlmostEqual(corr_vectors(x,x),1)
        self.assertAlmostEqual(corr_vectors(x,y),-1)
        self.assertAlmostEqual(corr_vectors(rank(x),rank(y)),-1)
        self.assertEqual(rank([1,1,3,7]),[1.5,1.5,3.,4.])
        self.assertIsNone(corr_vectors([3.]*100,x))

    def test_no_false_signal_drift_when_all_methods_preserve_joint_correlation(self):
        historical=[];future=[]
        for season in SEASONS:
            for field,name in PAIRS:
                for method in ALL_METHODS:
                    historical.append({"model":"ACCESS-CM2","window":HIST,
                        "method":method,"season":season,"relationship":name,
                        "pearson":-.4,"spearman":-.3})
                    future.append({"model":"ACCESS-CM2",
                        "window":"ssp245-2040-2059",
                        "method":method,"season":season,"relationship":name,
                        "pearson":-.25,"spearman":-.20})
        scores=dependence_change(historical,future)
        self.assertEqual(len(scores),100)
        self.assertTrue(all(abs(r["pearson_signal_distortion_vs_original"])<1e-12
                            and not r["spearman_screen_gt_0p10"] for r in scores))

    def test_corr_change_alarm_detects_solar_weather_coupling_drift(self):
        hist=[];future=[]
        for season in SEASONS:
            for _,name in PAIRS:
                for method in ALL_METHODS:
                    entry={"model":"ACCESS-CM2","method":method,
                           "season":season,"relationship":name,
                           "pearson":-.1,"spearman":-.1}
                    hist.append({**entry,"window":HIST})
                    changed=.2 if method==NEW else -.1
                    future.append({**entry,"window":FUTURES[0],
                                   "pearson":changed,"spearman":changed})
        rows=dependence_change(hist,future)
        alarm=[r for r in rows if r["method"]==NEW]
        self.assertEqual(len(alarm),25)
        self.assertTrue(all(r["pearson_screen_gt_0p20"] for r in alarm))

    def test_physical_gate_fails_if_m3_exceeds_extraterrestrial_ra(self):
        joint=[{"tas_c":20.,"hurs":50.,"pr_mm_day":0.,"rlds_kwh_m2_day":6.,
                "sfcWind":2.,"huss":None} for i in range(32)]
        geo=[{"ra":5.,"rso":4.} for i in range(32)]
        solar=[{**{m:2. for m in ALL_METHODS},NEW:6.} for i in range(32)]
        with self.assertRaisesRegex(ValueError,"M3 physical closure"):
            physical_metrics(joint,solar,geo,"ACCESS-CM2",HIST)

    def test_raw_relative_humidity_overshoot_is_not_silently_removed(self):
        joint=[{"tas_c":20.,"hurs":100.5,"pr_mm_day":0.,
                "rlds_kwh_m2_day":6.,"sfcWind":2.,"huss":None} for i in range(32)]
        geo=[{"ra":5.,"rso":4.} for i in range(32)]
        solar=[{m:2. for m in ALL_METHODS} for i in range(32)]
        summary=physical_metrics(joint,solar,geo,"ACCESS-CM2",HIST)
        self.assertEqual(summary[0]["source_hurs_above_100_count"],32)
        self.assertTrue(summary[0]["huss_missing_all_days"])
        self.assertTrue(all(item["days_above_TOA"]==0 for item in summary))

if __name__=="__main__":unittest.main()
