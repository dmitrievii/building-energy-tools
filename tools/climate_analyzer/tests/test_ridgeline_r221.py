"""R2.21 A: common-bin distribution and wind-direction display contracts."""
from __future__ import annotations
import unittest
import numpy as np
import pandas as pd

from epw_climate_analyzer.ridgeline import ridgeline_figure
from epw_climate_analyzer.extended_visualization import compatible_types
from epw_climate_analyzer.chart_theme import WIND_DIRECTION_COLORSCALE, WIND_DIRECTION_HEATMAP_COLORS, metric_colorscale


class RidgelineR221Tests(unittest.TestCase):
    def setUp(self):
        index = pd.date_range("2026-01-01", "2026-03-01", freq="h", inclusive="left")
        self.df = pd.DataFrame({"dry_bulb_temperature_c": np.sin(np.arange(len(index))/10)*5+index.month*3.},index=index)

    def test_monthly_ridges_share_physical_axis_and_unit_probability_area(self):
        f, note = ridgeline_figure(self.df,"dry_bulb_temperature_c","°C","Dry-bulb temperature",bins=40)
        self.assertEqual(list(f.layout.yaxis.ticktext), ["January","February"])
        self.assertIn("Ridgeline plot",compatible_types(self.df,"dry_bulb_temperature_c"))
        self.assertIn("unit probability area",note)
        polygons = [t for t in f.data if t.fill == "toself"]
        densities = [t for t in f.data if t.customdata is not None]
        self.assertEqual(len(polygons),2)
        self.assertEqual(len(densities),2)
        np.testing.assert_array_equal(polygons[0].x,polygons[1].x)
        for t in densities:
            dx = float(t.x[1]-t.x[0])
            self.assertAlmostEqual(float(np.sum(t.customdata))*dx,1.,places=10)
        self.assertEqual(len(f.data),8)

    def test_seasonal_grouping_and_no_quantiles(self):
        f,note = ridgeline_figure(self.df,"dry_bulb_temperature_c","°C","Dry-bulb temperature",grouping="Seasonal",quantiles=False)
        self.assertEqual(list(f.layout.yaxis.ticktext),["DJF"])
        self.assertEqual(len(f.data),2)
        self.assertNotIn("Baseline segments",note)

    def test_constant_groups_are_observed_values_not_smoothed(self):
        df=self.df.assign(dry_bulb_temperature_c=12.)
        f,note=ridgeline_figure(df,"dry_bulb_temperature_c","°C","Dry-bulb temperature",quantiles=False)
        self.assertEqual(len(f.data),2)
        self.assertTrue(all(list(t.x)==[12.] for t in f.data))
        self.assertTrue(all(t.fill is None for t in f.data))

    def test_wet_selection_and_missing_values(self):
        df=pd.DataFrame({"liquid_precipitation_depth_mm":[0.,np.nan,1.,2.,3.]},
                        index=pd.date_range("2026-01-01",periods=5,freq="h"))
        f,note=ridgeline_figure(df,"liquid_precipitation_depth_mm","mm","Liquid precipitation depth",wet_only=True)
        self.assertIn("3 valid source observations",note)
        self.assertIn("Positive precipitation observations only",note)
        self.assertGreaterEqual(min(f.data[0].x),1.)

    def test_atlas_uses_same_figure_and_interpretation_kernel(self):
        from epw_climate_analyzer.p66_catalogue import Diagram,TEMP
        from epw_climate_analyzer.p66_render import make_figure
        d=Diagram("ridge-test",TEMP,"Dry-bulb temperature · monthly ridgeline","ridgeline",
                  "dry_bulb_temperature_c","°C",("Monthly","all"))
        f,note=make_figure(d,self.df,{})
        expected,expected_note=ridgeline_figure(self.df,d.column,d.unit,"Dry-bulb temperature")
        self.assertEqual(note,expected_note)
        self.assertEqual(list(f.layout.yaxis.ticktext),list(expected.layout.yaxis.ticktext))
        self.assertEqual(len(f.data),len(expected.data))

    def test_direction_palette_is_cyclic_with_distinct_sector_anchors(self):
        self.assertEqual(WIND_DIRECTION_HEATMAP_COLORS[0],WIND_DIRECTION_HEATMAP_COLORS[-1])
        self.assertEqual(len(set(WIND_DIRECTION_HEATMAP_COLORS[:-1])),8)
        self.assertEqual(WIND_DIRECTION_COLORSCALE[0][0],0.)
        self.assertEqual(WIND_DIRECTION_COLORSCALE[-1][0],1.)
        self.assertEqual(metric_colorscale("wind_direction_deg"),WIND_DIRECTION_COLORSCALE)
        self.assertEqual(metric_colorscale("wind_gust_direction_deg"),WIND_DIRECTION_COLORSCALE)

if __name__=="__main__":
    unittest.main()
