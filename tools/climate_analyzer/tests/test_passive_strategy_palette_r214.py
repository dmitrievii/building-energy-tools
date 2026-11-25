"""Monthly passive strategy matrix: a common zero-anchored duration palette."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer.passive_design_findings import (
    monthly_strategy_matrix, PASSIVE_STRATEGY_HOURS_COLORSCALE,
)
from epw_climate_analyzer.p6_report_structure import report_figure

class PassiveStrategyPaletteTests(unittest.TestCase):
    def test_shared_zero_anchored_palette(self):
        table=pd.DataFrame({"Comfort":[0.,80.,np.nan],"Heating":[400.,0.,50.]},
                           index=["Jan","Feb","Mar"])
        fig=monthly_strategy_matrix(table,"Monthly passive strategy hours")
        for plot in (fig,report_figure(fig,width_pt=500,height_pt=230)):
            trace=plot.data[0]
            self.assertEqual(trace.colorscale,PASSIVE_STRATEGY_HOURS_COLORSCALE)
            self.assertEqual((trace.zmin,trace.zmax),(0.,400.))
            np.testing.assert_allclose(np.asarray(trace.z,float),table.to_numpy().T,equal_nan=True)
            self.assertEqual(tuple(trace.y),tuple(table.columns))
    def test_zero_only_scale_remains_valid(self):
        fig=monthly_strategy_matrix(pd.DataFrame({"Comfort":[0.]},index=["Jan"]),"Zero")
        self.assertEqual((fig.data[0].zmin,fig.data[0].zmax),(0.,1.))
        self.assertEqual(fig.data[0].colorscale[0],(0.,"#FFFFFF"))
