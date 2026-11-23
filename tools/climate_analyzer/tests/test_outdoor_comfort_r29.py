"""R2.9 regression suite: UTCI paired comparison and architectural findings."""
from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer import utci_findings as f
from epw_climate_analyzer import p3_comfort as p
from epw_climate_analyzer import p66_catalogue


class UtcIR29Tests(unittest.TestCase):
    @staticmethod
    def fixture():
        index = pd.date_range("2026-06-30 22:00", periods=4, freq="h")
        df = pd.DataFrame(index=index)
        df.attrs["canonical_native_interval_minutes"] = 60.
        states = pd.DataFrame({
            "Open sun": [31., 33., 40., np.nan],
            "Direct-beam shade": [29., 31., 38., 37.],
        }, index=index)
        return df, states

    def test_physical_duration_and_threshold_crossing(self):
        df, states = self.fixture()
        result = f.paired_exposure_statistics(df, states)
        self.assertEqual(result["paired_hours"], 3.)
        self.assertEqual(result["coverage_pct"], 75.)
        self.assertAlmostEqual(result["mean_difference_c"], 2.)
        self.assertEqual(result["sun_above_32_h"], 2.)
        self.assertEqual(result["shade_above_32_h"], 1.)
        self.assertEqual(result["downcross_32_h"], 1.)
        self.assertEqual(result["sun_above_38_h"], 1.)
        self.assertEqual(result["shade_above_38_h"], 0.)
        self.assertEqual(result["downcross_38_h"], 1.)
        self.assertEqual(result["upcross_32_h"], 0.)
        self.assertEqual(len(result["monthly"]), 2)
        self.assertEqual(result["monthly"]["hours"].tolist(), [2., 1.])
        note = f.paired_exposure_interpretation(df, states)
        self.assertIn("3 coincident valid hours", note)
        self.assertIn("2.00 K", note)
        self.assertIn("1 paired hours cross", note)

    def test_subhourly_and_missing_data_denominator(self):
        df, states = self.fixture()
        df.attrs["canonical_native_interval_minutes"] = 30.
        stats = f.exposure_statistics(df, states)
        self.assertEqual(stats["Valid hours"].tolist(), [1.5, 2.0])
        self.assertEqual(stats["Period coverage [%]"].tolist(), [75., 100.])
        self.assertEqual(stats["Hours >32 °C"].tolist(), [1., 1.])
        pair = f.paired_exposure_statistics(df, states)
        self.assertEqual(pair["paired_hours"], 1.5)
        self.assertEqual(pair["sun_above_32_h"], 1.)
        self.assertEqual(pair["shade_above_32_h"], .5)
        self.assertAlmostEqual(pair["coverage_pct"],75.)

    def test_stress_categories_are_upper_inclusive(self):
        from epw_climate_analyzer.utci_presentation import stress_codes
        vals = np.array([-40., -27., 0., 9., 26., 32., 38., 46., 46.001, np.nan])
        codes = stress_codes(vals)
        np.testing.assert_array_equal(codes[:9], [0, 1, 3, 4, 5, 6, 7, 8, 9])
        self.assertTrue(np.isnan(codes[9]))

    def test_no_unmatched_sun_shade_comparison(self):
        df, states = self.fixture()
        states["Direct-beam shade"] = np.nan
        result = f.paired_exposure_statistics(df, states)
        self.assertEqual(result["paired_hours"],0)
        self.assertTrue(np.isnan(result["mean_difference_c"]))
        self.assertIn("no paired UTCI observations",f.paired_exposure_interpretation(df, states))

    def test_neutral_beam_yields_zero_difference_and_crossings(self):
        df, states = self.fixture()
        states["Direct-beam shade"] = states["Open sun"]
        result = f.paired_exposure_statistics(df, states)
        self.assertEqual(result["mean_difference_c"],0.)
        self.assertEqual(result["downcross_32_h"],0.)
        self.assertEqual(result["downcross_38_h"],0.)
        self.assertEqual(result["hours_benefit_ge_2k"],0.)

    def test_figures_are_separate_visualizations(self):
        df, values = self.fixture()
        for figure in (
            f.paired_monthly_figure(df,values),
            f.paired_delta_figure(df,values),
            f.paired_threshold_figure(df,values),
            f.mrt_monthly_figure(values),
        ):
            self.assertGreaterEqual(len(figure.data),1)
            self.assertTrue(figure.layout.title.text)
        thresholds=f.paired_threshold_figure(df,values)
        self.assertEqual(list(thresholds.data[0].y),[3.,2.,1.])
        self.assertEqual(list(thresholds.data[1].y),[3.,1.,0.])

    def test_atlas_registers_paired_benefits_and_mrt(self):
        source = (Path(__file__).resolve().parents[1] /
                  "epw_climate_analyzer" / "p66_catalogue.py").read_text(encoding="utf-8")
        renderer = (Path(__file__).resolve().parents[1] /
                    "epw_climate_analyzer" / "p66_render.py").read_text(encoding="utf-8")
        for kind in ("utci_pair_delta","utci_pair_stress","utci_pair_mrt"):
            self.assertIn('"' + kind + '"', source)
            self.assertIn('"' + kind + '"', renderer)


if __name__=="__main__":
    unittest.main()
