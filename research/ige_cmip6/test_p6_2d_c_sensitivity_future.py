"""P6.2D-C sensitivity and future-change science contracts; no source mutation."""
from __future__ import annotations
import tempfile,unittest,calendar
from unittest.mock import patch
from pathlib import Path
from p6_2d_c_sensitivity_future_signals import (
    ALTITUDES,CAPS,BLOCKS,FUTURES,REPAIRED_FUTURES,
    normalized,fit,correct,year_months,monthly_methods,
    future_signal_scores,write_union_csv,model_original_future,
)
from p6_2d_solar_methods_benchmark import METHODS
from p6_2d_b_daily_clearsky_benchmark import NEW,solar_geometry

def synthetic():
    station=[];gcm=[]
    # 20 Gregorian years; only 1 sample for each month in the synthetic
    # correction fixture so use a manually passed CDF for rank calibration.
    for year in range(1995,2015):
        for month in range(1,13):
            ra,rso=solar_geometry(month,15,year,46.875,366.)
            for day in range(1,calendar.monthrange(year,month)[1]+1):
                geom=solar_geometry(month,day,year,46.875,366.)
                raw=.64*geom[1]
                record={"year":year,"month":month,"day":day,
                        "date":f"{year}-{month:02d}-{day:02d}",
                        "ra":geom[0],"rso":geom[1],
                        "ghi_kwh_m2_day":raw}
                station.append({**record,"ghi_kwh_m2_day":.4*geom[1]})
                gcm.append(record)
    return station,gcm

def example_rule():
    return {month:([.3,.4,.5],[.5,.6,.7]) for month in range(1,13)}

class FutureSignalContracts(unittest.TestCase):
    def test_original_future_source_archive_slugs_are_deterministic(self):
        # These are the literal, immutable original GitHub artifact names.
        checks=(
            ("ACCESS-CM2","ssp245-2040-2059",
             "access/ige-p6-access-ssp245-2040-2059"),
            ("CanESM5","ssp585-2080-2099",
             "original/ige-p6-CanESM5-ssp585-2080-2099"),
            ("MPI-ESM1-2-HR","ssp585-2040-2059",
             "repaired/ige-p6-MPI-ESM1-2-HR-ssp585-2040-2059"),
            ("EC-Earth3","ssp245-2040-2059",
             "repaired/ige-p6-EC-Earth3-ssp245-2040-2059"),
        )
        for model,window,expected in checks:
            with self.subTest(model=model,window=window):
                paths=[]
                def fake_source(folder,seen_model,seen_window):
                    paths.append((str(folder),seen_model,seen_window))
                    raise RuntimeError("Sentinel: path capture before reading source")
                with patch("p6_2d_c_sensitivity_future_signals.original_quality",
                           side_effect=fake_source):
                    with self.assertRaisesRegex(RuntimeError,"Sentinel"):
                        model_original_future(model,window,Path("access"),
                                              Path("original"),Path("repaired"))
                self.assertEqual(paths,[(expected,model,window)])

    def test_all_four_future_gcm_periods(self):
        self.assertEqual(set(FUTURES),{"ssp245-2040-2059",
            "ssp585-2040-2059","ssp245-2080-2099","ssp585-2080-2099"})
        self.assertEqual(len(REPAIRED_FUTURES),4)

    def test_sensitivity_is_explicit_proxy_not_verified_elevation(self):
        self.assertEqual(ALTITUDES,(200.,366.,600.))
        self.assertEqual(CAPS,(1.05,1.10,1.15))
        self.assertFalse(set(BLOCKS["train_1995_2004"]) & set(range(2005,2015)))

    def test_no_mutation_when_changing_source_altitude_and_cap(self):
        _,gcm=synthetic()
        original=[dict(x) for x in gcm]
        lo=normalized(gcm,200.,1.05,True)
        hi=normalized(gcm,600.,1.15,True)
        self.assertEqual(gcm,original)
        self.assertGreater(lo[0]["rso"],0)
        self.assertGreater(hi[0]["rso"],lo[0]["rso"])
        self.assertLessEqual(lo[0]["index"],1.05)
        self.assertLessEqual(hi[0]["index"],1.15)

    def test_future_year_cannot_train_m3(self):
        station,gcm=synthetic()
        a=normalized(station,366.,1.10,False)
        b=normalized(gcm,366.,1.10,True)
        with self.assertRaisesRegex(ValueError,"training-leakage"):
            fit(a,b,[2005],1.10)

    def test_holdout_station_does_not_affect_rules(self):
        obs,gcm=synthetic()
        a=normalized(obs,366.,1.10,False)
        b=normalized(gcm,366.,1.10,True)
        rules=fit(a,b,BLOCKS["train_1995_2004"],1.10)
        altered=[dict(x,index=1.03) if x["year"]>=2005 else x for x in a]
        self.assertEqual(rules,fit(altered,b,BLOCKS["train_1995_2004"],1.10))

    def test_daily_future_adjustment_keeps_physical_envelope(self):
        _,gcm=synthetic()
        arr=normalized(gcm,366.,1.05,True)
        target=[x for x in arr if x["year"]>=2005]
        predicted=correct(target,example_rule(),1.05,
                          range(2005,2015),write_daily=True)
        self.assertEqual(len(predicted),3652)
        for r in predicted:
            self.assertGreaterEqual(r["corrected_kwh_m2_day"],0)
            self.assertLessEqual(r["corrected_kwh_m2_day"],
                                 r["physical_cap_kwh_m2_day"]+1e-9)
        monthly=year_months(target,predicted)
        self.assertEqual(len(monthly),120)

    def test_future_target_rejects_unexpected_year(self):
        _,gcm=synthetic()
        arr=normalized(gcm,366.,1.1,True)
        with self.assertRaisesRegex(ValueError,"Wrong target"):
            correct(arr,example_rule(),1.1,range(2040,2060))

    def test_additive_index_shift_preserved_when_no_cap_activated(self):
        _,gcm=synthetic()
        arr=normalized([r for r in gcm if r["year"]>=2005],366.,1.1,True)
        new=[dict(r,index=r["index"]+.04) for r in arr]
        rules={m:([.2,.3,.4],[.4,.5,.6]) for m in range(1,13)}
        old=correct(arr,rules,1.1,range(2005,2015))
        raised=correct(new,rules,1.1,range(2005,2015))
        for a,b,r in zip(old,raised,arr):
            self.assertAlmostEqual(b-a,.04*r["rso"],places=9)

    def test_future_ratio_scoring_does_not_use_station_future(self):
        hist={};future={}
        for year in range(1995,2015):
            for month in range(1,13):
                hist[year,month]={key:80+month for key in (*METHODS,NEW)}
        for year in range(2040,2060):
            for month in range(1,13):
                future[year,month]={key:1.12*(80+month) for key in (*METHODS,NEW)}
        comparisons=future_signal_scores("ACCESS-CM2","ssp245-2040-2059",hist,future)
        self.assertEqual(len(comparisons),20)
        self.assertTrue(all(abs(r["future_change_percent"]-12)<1e-10
                            for r in comparisons))
        self.assertTrue(all(not r["exceeds_5pp_signal_screen"]
                            for r in comparisons))

    def test_heterogeneous_source_manifest_columns_preserved(self):
        rows=[{"model":"A","historical_sha":"sha-A"},
              {"model":"B","future_sha":"sha-B","native_calendar":"noleap"}]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"manifest.csv"
            digest=write_union_csv(path,rows)
            raw=path.read_text()
        self.assertEqual(len(digest),64)
        self.assertIn("historical_sha",raw)
        self.assertIn("future_sha",raw)
        self.assertIn("noleap",raw)

if __name__=="__main__":unittest.main()
