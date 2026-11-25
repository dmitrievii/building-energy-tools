"""Natural Ventilation Atlas interpretations are quantitative and source-bound."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer import p66_catalogue as cat
from epw_climate_analyzer.p66_render import make_figure,NotApplicable
from epw_climate_analyzer.residual_findings import nv_special_figure
from epw_climate_analyzer.figure_interpretation_contract import validate_figure_interpretation
from epw_climate_analyzer.p66_export import _html_panel

class NaturalVentilationInterpretationTests(unittest.TestCase):
    def fixture(self):
        idx=pd.date_range("2026-01-01",periods=24*10,freq="h")
        df=pd.DataFrame({cat.T:np.where(idx.hour<12,20.,30.),cat.W:6.,cat.V:2.,cat.WD:270.},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_atlas_natural_ventilation_notes(self):
        df=self.fixture()
        diagrams=[d for d in cat.catalogue(df,{},cat.REP) if d.chapter==cat.NV and d.status=="available"]
        self.assertTrue(diagrams)
        checked=0
        for d in diagrams:
            with self.subTest(diagram=d.title):
                try:fig,note=make_figure(d,df,{})
                except NotApplicable:continue
                self.assertTrue(note.strip())
                self.assertTrue(validate_figure_interpretation(fig,note,require_binding=True))
                from html import escape
                self.assertIn(escape(note),_html_panel(d,fig,note,1))
                if d.kind=="nv_special" and d.args==("Persistence",):
                    self.assertIn("10 of 10 observed days",note)
                if d.kind=="nv_special" and d.args==("Temperature–wind suitability",):
                    self.assertIn("120.0 h (50.0%)",note)
                if d.kind=="eligibility_total" and d.args[0]=="nv":
                    self.assertIn("120.0 of 240.0",note)
                    self.assertIn("ranges from",note)
                checked+=1
        self.assertGreaterEqual(checked,6)

    def test_shared_persistence_and_sensitivity(self):
        df=self.fixture()
        for style,expected in (("Persistence","10 of 10 observed days"),
                               ("Temperature–wind suitability","120.0 h (50.0%)")):
            fig,note=nv_special_figure(df,style)
            d=next(d for d in cat.catalogue(df,{},cat.REP) if d.kind=="nv_special" and d.args==(style,))
            atlas,atlas_note=make_figure(d,df,{})
            self.assertIn(expected,note)
            self.assertEqual(note,atlas_note)
