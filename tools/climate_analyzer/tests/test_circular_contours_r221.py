"""R2.21 B2: explicit seam admission, missing-cell masking and presentation parity."""
import unittest
import numpy as np
import plotly.graph_objects as go
from epw_climate_analyzer.circular_heatmap import eligible, contour_eligible, CALENDAR_ANGLE, CLOCK_ANGLE
from epw_climate_analyzer.circular_contours import prepare_grid, STATUS, has_valid_quad, _polar_path, extend_display_edges
from epw_climate_analyzer.heatmap_presentation import apply_heatmap_presentation, TILES, HYBRID, CONTOURS
from epw_climate_analyzer.figure_interpretation_contract import bind_figure_interpretation, validate_figure_interpretation


class CircularContourTests(unittest.TestCase):
    def fixture(self, *, pooled=False, missing=False):
        z=20+8*np.sin(np.arange(24)[:,None]*2*np.pi/24)+5*np.cos(np.arange(12)[None,:]*2*np.pi/12)
        if missing:z[7,3]=np.nan
        f=go.Figure(go.Heatmap(x=list(range(1,13)),y=list(range(24)),z=z,coloraxis="coloraxis"))
        f.update_layout(title="Monthly temperature",xaxis_title="Month",yaxis_title="Hour of day",
            coloraxis=dict(colorscale="Viridis",cmin=0,cmax=40,colorbar=dict(title="°C")),
            meta={"period_time_basis":"Calendar profile" if pooled else "Chronological"})
        bind_figure_interpretation(f,"Shared temperature interpretation.")
        return f

    def test_calendar_seam_only_closes_explicit_pooled_complete_cycle(self):
        for pooled in (False,True):
            f=self.fixture(pooled=pooled)
            x,y,z,n,m,periodic=prepare_grid(eligible(f),f.layout.meta,CALENDAR_ANGLE)
            self.assertEqual(periodic,pooled)
            self.assertEqual(z.shape,(24,13 if pooled else 12))
            if pooled:np.testing.assert_array_equal(z[:,-1],z[:,0])
        f=self.fixture(pooled=True)
        f.data[0].x=list(range(2,13))
        f.data[0].z=np.asarray(f.data[0].z)[:,1:]
        _,_,z,_,_,periodic=prepare_grid(eligible(f),f.layout.meta,CALENDAR_ANGLE)
        self.assertFalse(periodic)
        self.assertTrue(np.isnan(z[:,0]).all())

    def test_clock_seam_recurring_hours_not_individual_chronological_days(self):
        f=self.fixture()
        x,y,z,n,m,periodic=prepare_grid(eligible(f),f.layout.meta,CLOCK_ANGLE)
        self.assertTrue(periodic)
        np.testing.assert_array_equal(z[:,-1],z[:,0])
        f.update_xaxes(title="Day of year")
        f.data[0].x=[f"2026-01-{i:02d}" for i in range(1,13)]
        _,_,z,_,_,periodic=prepare_grid(eligible(f),f.layout.meta,CLOCK_ANGLE)
        self.assertFalse(periodic)
        self.assertEqual(z.shape,(365,24))

    def test_missing_cells_do_not_supply_neighbour_values(self):
        f=self.fixture(pooled=True,missing=True)
        _,_,z,_,_,_=prepare_grid(eligible(f),f.layout.meta,CALENDAR_ANGLE)
        self.assertTrue(np.isnan(z[7,3]))
        self.assertTrue(has_valid_quad(z))
        sparse=np.full((4,4),np.nan)
        sparse[0,0]=1;sparse[0,1]=2;sparse[1,0]=3
        self.assertFalse(has_valid_quad(sparse))

    def test_chronological_edges_cover_display_without_bridging_midnight(self):
        # Distinct first and last hours must remain distinct at the common
        # physical seam. A genuinely missing edge cell must remain masked.
        grid=np.arange(3*24,dtype=float).reshape(3,24)
        grid[1,0]=np.nan
        x,y,z=extend_display_edges(np.arange(24)+.5,np.arange(3)+.5,grid,24,3,False)
        np.testing.assert_array_equal(x[[0,-1]],[0.,24.])
        np.testing.assert_array_equal(y[[0,-1]],[0.,3.])
        np.testing.assert_array_equal(z[1:-1,0],grid[:,0])
        np.testing.assert_array_equal(z[1:-1,-1],grid[:,-1])
        np.testing.assert_array_equal(z[1:-1,1:-1],grid)
        self.assertTrue(np.isnan(z[2,0]))
        self.assertNotEqual(z[1,0],z[1,-1])

    def test_filled_chronological_calendar_reaches_full_circle_and_radial_edges(self):
        f=self.fixture()
        f.update_xaxes(title="Day of year")
        f.data[0].x=[f"2026-01-{i:02d}" for i in range(1,13)]
        apply_heatmap_presentation(f,CONTOURS,geometry="Circular",arrangement=CLOCK_ANGLE,interval=5.)
        status=f.layout.meta[STATUS]
        self.assertEqual(status["mode"],CONTOURS)
        self.assertFalse(status["periodic"])
        bands=[t for t in f.data if isinstance(t.meta,dict) and t.meta.get("circular_contour_band")]
        angles=[a for t in bands for a in t.theta if a is not None]
        radii=[r for t in bands for r in t.r if r is not None]
        self.assertAlmostEqual(min(angles),0.)
        self.assertAlmostEqual(max(angles),360.)
        self.assertAlmostEqual(min(radii),.16)
        # Days outside the selected 12-day interval remain masked.
        self.assertLess(max(radii),.16+.84*13/365)

    def test_angular_path_is_unwrapped_and_tessellated(self):
        theta,r=_polar_path([[11.5,4.5],[12.5,4.5]],12,24)
        self.assertAlmostEqual(theta[0],345)
        self.assertAlmostEqual(theta[-1],375)
        self.assertLessEqual(max(np.diff(theta)),2.00001)
        np.testing.assert_allclose(r,.16+.84*4.5/24)

    def test_both_modes_arrangements_preserve_source_and_shared_colour_contract(self):
        for arrangement in (CALENDAR_ANGLE,CLOCK_ANGLE):
            f=self.fixture(pooled=True,missing=True)
            z=np.asarray(f.data[0].z).copy()
            for mode in (HYBRID,CONTOURS):
                apply_heatmap_presentation(f,mode,geometry="Circular",arrangement=arrangement,
                    interval=5.,width=.25,labels=True)
                self.assertEqual(f.layout.meta[STATUS]["mode"],mode)
                self.assertTrue(f.layout.meta[STATUS]["periodic"])
                self.assertTrue(f.data[0].visible is False)
                np.testing.assert_array_equal(np.asarray(f.data[0].z),z)
                lines=[t for t in f.data if isinstance(t.meta,dict) and t.meta.get("circular_contour_lines")]
                self.assertEqual(len(lines),1)
                self.assertEqual(lines[0].line.width,.25)
                bands=[t for t in f.data if isinstance(t.meta,dict) and t.meta.get("circular_contour_band")]
                self.assertEqual(bool(bands),mode==CONTOURS)
                self.assertEqual(any(t.type=="barpolar" for t in f.data),mode==HYBRID)
                self.assertTrue(validate_figure_interpretation(f,"Shared temperature interpretation."))
                self.assertEqual(f.layout.coloraxis.cmin,0)
                self.assertEqual(f.layout.coloraxis.cmax,40)
            apply_heatmap_presentation(f,TILES)
            self.assertEqual(len(f.data),1)
            self.assertIsNone(f.data[0].visible)
            self.assertNotIn(STATUS,f.layout.meta)

    def test_categorical_cells_and_excessive_level_request_resolve_to_tiles(self):
        f=self.fixture()
        apply_heatmap_presentation(f,CONTOURS,geometry="Circular",interval=.00001)
        self.assertEqual(f.layout.meta[STATUS]["mode"],TILES)
        self.assertIn("reason",f.layout.meta[STATUS])
        apply_heatmap_presentation(f,TILES)
        f.data[0].meta={"heatmap_semantics":"categorical"}
        self.assertIsNone(contour_eligible(f))
        apply_heatmap_presentation(f,HYBRID,geometry="Circular")
        self.assertEqual(f.layout.meta[STATUS]["mode"],TILES)

    def test_report_clone_retains_filled_bands_and_interpretation(self):
        from epw_climate_analyzer.p6_report_structure import report_figure
        f=self.fixture(pooled=True)
        apply_heatmap_presentation(f,CONTOURS,geometry="Circular")
        self.assertEqual(f.layout.meta[STATUS]["mode"],CONTOURS)
        out=report_figure(f,width_pt=480,height_pt=480)
        self.assertTrue(any(isinstance(t.meta,dict) and t.meta.get("circular_contour_band") for t in out.data))
        self.assertEqual(out.layout.coloraxis.cmax,40)
        self.assertTrue(validate_figure_interpretation(out,"Shared temperature interpretation."))

if __name__=="__main__":
    unittest.main()
