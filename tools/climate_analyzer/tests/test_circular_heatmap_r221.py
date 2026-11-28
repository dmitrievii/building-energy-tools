"""R2.21 B1 calendar geometry regression: exact cells, no cyclic extrapolation."""
import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from epw_climate_analyzer.circular_heatmap import (
    eligible, LAYER, LAYOUT, CALENDAR_ANGLE, CLOCK_ANGLE,
)
from epw_climate_analyzer.heatmap_presentation import apply_heatmap_presentation, HYBRID, TILES
from epw_climate_analyzer.figure_interpretation_contract import bind_figure_interpretation, validate_figure_interpretation


class CircularHeatmapTests(unittest.TestCase):
    def fixture(self):
        f=go.Figure(go.Heatmap(x=["2026-01-04","2026-01-06"],y=[0,7,23],
            z=[[0.,1.],[np.nan,3.],[4.,5.]], coloraxis="coloraxis"))
        f.update_layout(xaxis_title="Day of year", yaxis_title="Hour of day",
            coloraxis=dict(cmin=-10,cmax=20,colorscale="Viridis",colorbar=dict(title="°C")),
            meta={"period_source_years":[2026,2026]},height=420)
        bind_figure_interpretation(f,"One canonical interpretation.")
        return f

    def test_calendar_angle_exact_values_and_gap_geometry(self):
        f=self.fixture()
        self.assertIsNotNone(eligible(f))
        apply_heatmap_presentation(f,geometry="Circular",arrangement=CALENDAR_ANGLE)
        self.assertEqual(len(f.data),2)
        t=f.data[1]
        self.assertEqual(t.type,"barpolar")
        self.assertTrue(t.meta[LAYER])
        self.assertIs(f.data[0].visible,False)
        np.testing.assert_array_equal(t.marker.color,[0.,1.,3.,4.,5.])
        np.testing.assert_allclose(t.theta,(np.array([3,5,5,3,5])+.5)*360/365)
        np.testing.assert_allclose(t.width,360/365)
        self.assertEqual(t.customdata[2][0],"06.01.2026")
        self.assertEqual(t.customdata[2][1],"07:00–08:00")
        self.assertEqual(t.marker.coloraxis,"coloraxis")
        self.assertEqual(f.layout.coloraxis.cmin,-10)
        self.assertTrue(validate_figure_interpretation(f,"One canonical interpretation."))

    def test_clock_angle_reversible_idempotent(self):
        f=self.fixture()
        for _ in range(2):
            apply_heatmap_presentation(f,geometry="Circular",arrangement=CLOCK_ANGLE)
            self.assertEqual(len(f.data),2)
            np.testing.assert_allclose(f.data[1].theta,[7.5,7.5,112.5,352.5,352.5])
            np.testing.assert_allclose(f.data[1].base,.16+.84*np.array([3,5,5,3,5])/365)
        apply_heatmap_presentation(f,TILES)
        self.assertEqual(len(f.data),1)
        self.assertIsNone(f.data[0].visible)
        self.assertEqual(f.layout.height,420)
        self.assertNotIn(LAYOUT,f.layout.meta)
        self.assertTrue(np.isnan(np.asarray(f.data[0].z)[1,0]))
        self.assertTrue(validate_figure_interpretation(f,"One canonical interpretation."))

    def test_pooled_leap_neutral_day_and_binary_tiles(self):
        f=go.Figure(go.Heatmap(x=[59,60,61],y=[7,8],z=[[0.,np.nan,1.],[1.,0.,1.]],
            colorscale=[[0,"white"],[.5,"white"],[.5,"black"],[1,"black"]],zmin=0,zmax=1))
        f.update_layout(xaxis_title="Calendar day · leap-year reference",yaxis_title="Hour of day",
                        meta={"period_source_years":[2024,2026]})
        apply_heatmap_presentation(f,geometry="Circular")
        self.assertEqual(len(f.data[-1].r),5)
        self.assertEqual(f.data[-1].marker.cmin,0)
        self.assertEqual(f.data[-1].marker.cmax,1)
        np.testing.assert_allclose(f.data[-1].width,360/366)

    def test_noncalendar_and_chronological_multiyear_are_not_admitted(self):
        f=self.fixture()
        f.update_xaxes(title="Orientation [°]")
        self.assertIsNone(eligible(f))
        f=self.fixture()
        f.data[0].x=["2025-12-31","2026-01-01"]
        self.assertIsNone(eligible(f))
        apply_heatmap_presentation(f,geometry="Circular")
        self.assertEqual(len(f.data),1)
        self.assertIsNone(f.data[0].visible)

    def test_report_clone_preserves_cells_palette_and_interpretation(self):
        from epw_climate_analyzer.p6_report_structure import report_figure
        f=self.fixture()
        apply_heatmap_presentation(f,geometry="Circular")
        printed=report_figure(f,width_pt=480,height_pt=480)
        self.assertEqual(len(printed.data),2)
        self.assertEqual(printed.data[-1].type,"barpolar")
        self.assertEqual(printed.data[-1].marker.coloraxis,"coloraxis")
        self.assertEqual(printed.layout.coloraxis.cmin,-10)
        np.testing.assert_array_equal(printed.data[-1].marker.color,f.data[-1].marker.color)
        self.assertTrue(validate_figure_interpretation(printed,"One canonical interpretation."))

    def test_full_month_grid_has_exact_cell_count(self):
        f=go.Figure(go.Heatmap(x=list(range(1,13)),y=list(range(24)),z=np.arange(288).reshape(24,12)))
        f.update_layout(xaxis_title="Month",yaxis_title="Hour of day")
        apply_heatmap_presentation(f,geometry="Circular")
        self.assertEqual(len(f.data[-1].r),288)
        np.testing.assert_allclose(f.data[-1].width,30.)
        self.assertEqual(list(f.layout.polar.angularaxis.ticktext)[0],"Jan")

if __name__=="__main__":
    unittest.main()
