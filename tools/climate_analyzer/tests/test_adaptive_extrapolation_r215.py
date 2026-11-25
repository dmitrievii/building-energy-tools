"""R2.15: optional research extrapolation; strict admission is preserved."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer.p3_comfort import adaptive_bands, adaptive_bands_from_running_mean
from epw_climate_analyzer.p3_adaptive_chart import adaptive_figure, adaptive_interpretation
from epw_climate_analyzer.p6_report_structure import report_figure
from epw_climate_analyzer import p66_catalogue as cat
from epw_climate_analyzer.p66_render import make_figure

class AdaptiveExtrapolationTests(unittest.TestCase):
    def test_exact_equations_and_missing_data(self):
        rm=pd.Series([5.,10.,30.,31.,39.,np.nan,35.,29.],index=pd.date_range("2026-01-01",periods=8))
        strict=adaptive_bands_from_running_mean(rm)
        all_bands=adaptive_bands_from_running_mean(rm,extrapolate=True)
        np.testing.assert_allclose(all_bands.Neutral,.33*rm+18.8,equal_nan=True)
        valid=rm.between(10.,30.)
        pd.testing.assert_frame_equal(strict.loc[valid],all_bands.loc[valid])
        self.assertEqual(int(strict.Neutral.notna().sum()),3)
        self.assertEqual(int(all_bands.Neutral.notna().sum()),7)
        for category,lower,upper in (("I",3.,2.),("II",4.,3.),("III",5.,4.)):
            np.testing.assert_allclose(all_bands[category+" lower"],all_bands.Neutral-lower,equal_nan=True)
            np.testing.assert_allclose(all_bands[category+" upper"],all_bands.Neutral+upper,equal_nan=True)
        strict_fig=adaptive_figure(strict)
        fig=adaptive_figure(strict,extrapolate=True)
        self.assertEqual(len(strict_fig.data),5)
        self.assertEqual(len(fig.data),9)
        for view in (fig,report_figure(fig,width_pt=500,height_pt=230)):
            extra=next(t for t in view.data if t.name=="Neutral temperature · research extrapolation")
            np.testing.assert_allclose(np.asarray(extra.y,float),all_bands.Neutral.where(~valid),equal_nan=True)
            self.assertEqual(extra.line.dash,"dash")
            cat3=next(t for t in view.data if t.name=="Category III · research extrapolation")
            self.assertEqual(cat3.line.dash,"dash")
            self.assertEqual(list(cat3.x).count(None),3)
            self.assertEqual(view.layout.meta["adaptive_standard_days"],3)
            self.assertEqual(view.layout.meta["adaptive_extrapolated_days"],4)
        self.assertIn("3/8 selected days",adaptive_interpretation(strict,extrapolate=True))
        self.assertIn("Research extrapolation: 4/8",adaptive_interpretation(strict,extrapolate=True))
        self.assertNotIn("Research extrapolation:",adaptive_interpretation(strict))

    def test_full_atlas_explicit_research_variant(self):
        idx=pd.date_range("2026-07-01",periods=24*15,freq="h")
        df=pd.DataFrame({cat.T:35.},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        table=adaptive_bands(df)
        self.assertEqual(int(table.Neutral.notna().sum()),0)
        self.assertEqual(int(table["Running mean"].notna().sum()),8)
        variants=[d for d in cat.catalogue(df,{},cat.FULL) if d.kind=="adaptive"]
        self.assertEqual(len(variants),2)
        strict=next(d for d in variants if not d.args)
        research=next(d for d in variants if d.args)
        cache={}
        f1,n1=make_figure(strict,df,{},cache=cache)
        f2,n2=make_figure(research,df,{},cache=cache)
        self.assertIn("0/15 selected days",n1)
        self.assertIn("Research extrapolation: 8/15",n2)
        self.assertIn("Research extrapolation",f2.layout.title.text)
        self.assertEqual(f1.layout.meta["adaptive_extrapolated_days"],0)
        self.assertEqual(f2.layout.meta["adaptive_extrapolated_days"],8)
