"""Conditioning energy colours follow the shared physical series semantics."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer.hvac_findings import LOAD_COLUMNS, conditioning_monthly_figure
from epw_climate_analyzer.chart_theme import HEATING_COLOR, COOLING_COLOR
from epw_climate_analyzer.p6_report_structure import report_figure

class ConditioningPaletteTests(unittest.TestCase):
    def test_grouped_and_stacked_web_and_report(self):
        idx=pd.date_range("2026-01-01",periods=48,freq="h")
        ledger=pd.DataFrame({name:np.full(len(idx),i+1.) for i,name in enumerate(LOAD_COLUMNS)},index=idx)
        expected=(HEATING_COLOR,COOLING_COLOR,"#0891B2","#7C3AED")
        for grouped in (True,False):
            fig=conditioning_monthly_figure(ledger,ledger,grouped=grouped)
            for plot in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                self.assertEqual(tuple(tr.name for tr in plot.data),LOAD_COLUMNS)
                self.assertEqual(tuple(tr.marker.color for tr in plot.data),expected)
                self.assertEqual(tuple(float(tr.y[0]) for tr in plot.data),(48.,96.,144.,192.))
                self.assertEqual(plot.layout.barmode,"group" if grouped else "stack")
