"""IGE P8.4C frozen scalar wind signal provenance and physical EPW safety gates."""
from __future__ import annotations
import datetime as dt
import math
import tempfile
from pathlib import Path
import unittest

import p8_4c_future_wind_baseline as c
import p7c1_epw_morphing as old
import p7c3_ensemble as ens


def row(speed=2.,direction=90.,month=1,qualified=True):
    return {"speed":speed,"direction":direction,"month":month,
            "qualified":qualified}


def clock_2013():
    origin=dt.datetime(2013,1,1)
    return [origin+dt.timedelta(hours=i) for i in range(8760)]


def sample_8760():
    data=[]
    for stamp in clock_2013():
        speed=(.4 if stamp.hour==0 else (6. if stamp.hour in (2,3,4,5,6,7) else 2.))
        data.append(row(speed,None if speed<.5 else 90.,stamp.month))
    return data


def ratios(factor=1.):
    return {(model,window,m):factor for model in ens.MODELS
            for window in ens.WINDOWS for m in range(1,13)}


class WindBaselineContracts(unittest.TestCase):
    def test_exact_eight_registered_models_four_windows(self):
        self.assertEqual(len(ens.MODELS),8)
        self.assertEqual(len(ens.WINDOWS),4)
        self.assertEqual(c.N_GCM_STATES,32)
        self.assertEqual(len(ratios()),384)

    def test_frozen_original_p7c3_monthly_ratio_file_exhaustive(self):
        r,meta=c.read_registered_wind_ratios(c.SIGNALS)
        self.assertEqual(meta["n_signal_rows"],384)
        self.assertEqual(set(r),set(ratios()))
        self.assertTrue(meta["source_wind_day_is_scalar_not_uv"])
        self.assertEqual(len(meta["immutable_committed_GCM_signal_sha256"]),64)

    def test_no_negative_malformed_or_nonfinite_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/"bad.csv"
            src=Path(c.SIGNALS).read_text()
            a.write_text(src.replace(",0.9995219704363616",",-1.0",1))
            with self.assertRaisesRegex(ValueError,"FROZEN_BOUNDS"):
                c.read_registered_wind_ratios(a)
            a.write_text(src.replace(",0.9995219704363616",",nan",1))
            with self.assertRaisesRegex(ValueError,"FROZEN_BOUNDS"):
                c.read_registered_wind_ratios(a)

    def test_duplicate_or_mislabeled_model_month_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/"bad.csv"
            rows=Path(c.SIGNALS).read_text().splitlines()
            a.write_text("\n".join([rows[0],rows[1],rows[1],*rows[3:]])+"\n")
            with self.assertRaisesRegex(ValueError,"DUPLICATE"):
                c.read_registered_wind_ratios(a)

    def test_missing_registered_source_month_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/"short.csv"
            lines=Path(c.SIGNALS).read_text().splitlines()
            a.write_text("\n".join(lines[:-1])+"\n")
            with self.assertRaisesRegex(ValueError,"384"):
                c.read_registered_wind_ratios(a)

    def test_scalar_multiplier_preserves_azimuth(self):
        result=c.morph_record(row(3.,359.9),.8)
        self.assertAlmostEqual(result["speed"],2.4)
        self.assertEqual(result["direction"],359.9)
        self.assertFalse(result["from_original_missing"])

    def test_calm_remains_calm_on_small_multiplier(self):
        r=c.morph_record(row(.3,None),1.1)
        self.assertEqual(r["speed"],.33)
        self.assertIsNone(r["direction"])

    def test_calm_to_noncalm_is_flagged_not_filled_with_north(self):
        p=c.morph_record(row(.4,None),1.5)
        self.assertEqual(p["speed"],.6)
        self.assertIsNone(p["direction"])
        metrics=c.wind_metrics([p])
        self.assertEqual(metrics["noncalm_no_azimuth_count"],1)
        self.assertEqual(metrics["noncalm_azimuth_resolved_count"],0)

    def test_original_missing_wind_cannot_be_imputed(self):
        x=c.morph_record(row(None,None,qualified=False),1.2)
        self.assertIsNone(x["speed"])
        self.assertIsNone(x["direction"])
        self.assertTrue(x["from_original_missing"])

    def test_source_noncalm_without_direction_is_blocked(self):
        # An invalid source hour must remain missing; cannot silently use
        # unverified wind direction from source.
        x=c.morph_record(row(3.,None,qualified=False),2.)
        self.assertIsNone(x["speed"])
        self.assertIsNone(x["direction"])

    def test_negative_and_infinite_factors_rejected(self):
        for x in (-1.,0.,float("nan"),float("inf")):
            with self.assertRaisesRegex(ValueError,"INVALID_POSITIVE"):
                c.morph_record(row(2.,90.),x)

    def test_negative_baseline_speed_rejected(self):
        with self.assertRaisesRegex(ValueError,"INVALID_ORIGINAL"):
            c.morph_record(row(-1.,30.),1.)

    def test_invalid_azimuth_rejected(self):
        for x in (-10.,361.,float("nan")):
            with self.assertRaisesRegex(ValueError,"INVALID_SOURCE_FROM"):
                c.morph_record(row(2.,x),1.)

    def test_exact_north_and_circular_wrap(self):
        self.assertAlmostEqual(c.circular_distance(359.,1.),2.)
        self.assertEqual(c.circular_distance(0.,360.),0.)

    def test_rose_frequency_not_claimed_identical_when_calm_switches(self):
        initial=[{"speed":.4,"direction":0.},
                 {"speed":2.,"direction":180.}]
        changed=[{"speed":.8,"direction":0.},
                 {"speed":4.,"direction":180.}]
        a=c.rose16(initial)
        b=c.rose16(changed)
        self.assertNotEqual(a["frequency"],b["frequency"])
        self.assertEqual(a["resolved_sector_count"],1)
        self.assertEqual(b["resolved_sector_count"],2)

    def test_contiguous_high_wind_excludes_missing_and_subthreshold(self):
        winds=[5.,5.,5.,5.,None,5.,5.,5.,4.,5.,5.,5.]
        self.assertEqual(c.run_count(winds,3,5.),4)
        self.assertEqual(c.run_count(winds,6,5.),0)

    def test_quantiles_are_finite_and_ordered(self):
        base=c.wind_metrics([{"speed":x,"direction":0.} for x in (0.,1.,2.,4.,10.)])
        self.assertLessEqual(base["wind_speed_p05_mps"],base["wind_speed_p50_mps"])
        self.assertLessEqual(base["wind_speed_p50_mps"],base["wind_speed_p95_mps"])
        self.assertEqual(base["n_usable_speed_hours"],5)

    def test_complete_8760_UTC_clock_and_month_balance(self):
        series=sample_8760()
        r=c.compare_one_state(series,ratios(1.5),"ACCESS-CM2",ens.WINDOWS[0])
        self.assertEqual(r["n_identical_original_valid_hour_pairs"],8760)
        self.assertEqual(len(r["monthly"]),12)
        self.assertEqual(len(r["seasons"]),4)
        self.assertTrue(r["source_hourly_directions_preserved"])
        self.assertLessEqual(r["maximum_monthly_mean_speed_ratio_balance_error_mps"],.001)
        self.assertGreater(r["newly_noncalm_missing_direction_hour_count"],0)

    def test_numeric_source_calm_azimuth_still_unqualified_when_promoted(self):
        series=sample_8760()
        for x in series:
            if x["speed"]<c.CALM_MPS:
                x["direction"]=45.  # numeric but meteorologically calm
        r=c.compare_one_state(series,ratios(1.5),"ACCESS-CM2",ens.WINDOWS[0])
        self.assertEqual(
            r["calm_source_promoted_to_noncalm_hours_even_if_azimuth_numeric"],365)
        self.assertEqual(r["newly_noncalm_missing_direction_hour_count"],0)
        self.assertEqual(r["noncalm_direction_physical_suitability_blocker_hours"],365)

    def test_incomplete_hourly_reference_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,"8760"):
            c.compare_one_state(sample_8760()[:-1],ratios(1.),"ACCESS-CM2",ens.WINDOWS[0])

    def test_reference_missing_hours_preserved_and_counted(self):
        source=sample_8760()
        for i in range(200):
            source[i]["qualified"]=False
            source[i]["speed"]=None
            source[i]["direction"]=None
        r=c.compare_one_state(source,ratios(.9),"CanESM5",ens.WINDOWS[0])
        self.assertEqual(r["n_identical_original_valid_hour_pairs"],8560)
        self.assertTrue(r["source_hourly_directions_preserved"])

    def test_old_p7c1_same_wind_scalar_semantics(self):
        # This audit intentionally verifies P7C1 is still a monthly
        # change-factor engine, rather than claiming our output IS P7C1 EPW.
        self.assertIn(21,old.EDIT_FIELDS)
        self.assertNotIn(20,old.EDIT_FIELDS)
        self.assertEqual(old.SOURCE_THRESHOLDS["wind_ratio"],(.3,2.7))

    def test_ensemble_is_nonprobabilistic_and_all_eight_models(self):
        source=sample_8760()
        result=[c.compare_one_state(source,ratios(1.0),m,w)
                for m in ens.MODELS for w in ens.WINDOWS]
        summary=c.calculate_ensemble_summary(result)
        self.assertEqual(set(summary),set(ens.WINDOWS))
        self.assertTrue(all(v["gcm_count"]==8 for v in summary.values()))
        self.assertTrue(all(v["not_probabilistic_uncertainty_intervals"]
                            for v in summary.values()))


if __name__=="__main__":
    unittest.main()
