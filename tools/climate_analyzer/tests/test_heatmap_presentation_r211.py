"""R2.11 admission, numerical conservation, rendering and reversibility."""
import json
import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from epw_climate_analyzer.heatmap_presentation import (
    apply_heatmap_presentation, TILES, CONTOURS, HYBRID, LAYER, ORIGINAL,
)
from epw_climate_analyzer.chart_presentation import ChartPresentationSettings, apply_chart_presentation
from epw_climate_analyzer.p6_report_structure import report_figure

def grid(*,shared=True,x=None,y=None,z=None):
    if x is None:x=list(range(1,13))
    if y is None:y=list(range(24))
    if z is None:z=np.add.outer(np.arange(len(y)),np.arange(len(x)))*1.
    tr=go.Heatmap(x=x,y=y,z=z,meta={"heatmap_quantity":"dry_bulb_temperature_c","heatmap_semantics":"continuous"},
                  **({"coloraxis":"coloraxis"} if shared else {"colorscale":"Viridis","zmin":-10,"zmax":40,"colorbar":{"title":"°C"}}))
    f=go.Figure(tr)
    f.update_layout(title="Temperature",xaxis_title="Month",yaxis_title="Hour of day")
    if shared:f.update_layout(coloraxis=dict(colorscale="Viridis",cmin=-10,cmax=40,colorbar=dict(title="°C")))
    return f

class HeatmapRenderingR211(unittest.TestCase):
    def test_modes_conserve_original_coordinates_and_values(self):
        for shared in (True,False):
            f=grid(shared=shared);original=pio.to_json(f)
            for mode in (CONTOURS,HYBRID,CONTOURS):
                apply_heatmap_presentation(f,mode,interval=5.)
                self.assertEqual(len(f.data),2)
                t,c=f.data
                self.assertEqual(t.type,"heatmap");self.assertEqual(c.type,"contour")
                self.assertEqual(c.contours.coloring,"heatmap" if mode==CONTOURS else "none")
                self.assertEqual(c.contours.size,5.)
                self.assertFalse(c.connectgaps);self.assertFalse(c.hoverongaps)
                self.assertTrue(c.meta[LAYER]);self.assertTrue(c.meta["presentation_only_trace"])
                self.assertEqual(t.opacity,0. if mode==CONTOURS else None)
                np.testing.assert_array_equal(c.z,t.z)
                np.testing.assert_array_equal(c.x,t.x)
                np.testing.assert_array_equal(c.y,t.y)
                if shared:self.assertEqual(c.coloraxis,"coloraxis")
                else:self.assertEqual((c.zmin,c.zmax),(-10,40))
            apply_heatmap_presentation(f,TILES)
            self.assertEqual(json.loads(pio.to_json(f)),json.loads(original))

    def test_preserve_missing_values_and_masks(self):
        z=np.add.outer(np.arange(24),np.arange(12)).astype(float)
        z[2:4,4:6]=np.nan
        f=grid(z=z)
        f.add_heatmap(x=f.data[0].x,y=f.data[0].y,z=np.where(np.isnan(z),1.,np.nan),showscale=False)
        apply_heatmap_presentation(f,HYBRID)
        self.assertEqual(len(f.data),3)
        np.testing.assert_array_equal(np.isnan(f.data[-1].z),np.isnan(z))
        np.testing.assert_array_equal(f.data[0].z,z)
        self.assertFalse(f.data[-1].connectgaps)

    def test_discrete_circular_category_axis_and_empty_grids_stay_tiles(self):
        for case in ("binary","direction","classes","category","missing","gap","constant","year"):
            f=grid()
            if case=="binary":f.data[0].z=np.resize([0.,1.],(24,12))
            elif case=="direction":f.data[0].meta={"heatmap_semantics":"circular"}
            elif case=="classes":f.update_layout(meta={"utci_stress_palette":"categorical-v1"})
            elif case=="category":f.data[0].x=[f"station {i}" for i in range(12)]
            elif case=="missing":
                z=np.full((24,12),np.nan);z[0,0]=1.;z[0,1]=2.;f.data[0].z=z
            elif case=="gap":f.data[0].x=[1,2,3,4,5,6,8,9,10,11,12,13]
            elif case=="constant":f.data[0].z=np.full((24,12),3.)
            elif case=="year":f.update_yaxes(title="Year")
            apply_heatmap_presentation(f,CONTOURS)
            self.assertEqual(len(f.data),1,case)
            self.assertIsNone(f.data[0].opacity,case)

    def test_report_roundtrip_and_actual_static_rendering(self):
        for mode in (CONTOURS,HYBRID):
            f=grid(x=pd.date_range("2026-01-01",periods=12,freq="D").strftime("%Y-%m-%d"))
            f.update_xaxes(title="Day")
            apply_chart_presentation(f,ChartPresentationSettings(heatmap_mode=mode))
            self.assertEqual(len(f.data),2)
            restored=pio.from_json(pio.to_json(f))
            printed=report_figure(restored,width_pt=500,height_pt=230)
            self.assertEqual(printed.data[-1].type,"contour")
            np.testing.assert_array_equal(printed.data[0].z,f.data[0].z)
            self.assertEqual(printed.data[-1].contours.coloring,f.data[-1].contours.coloring)
            svg=printed.to_image(format="svg").decode("utf-8")
            self.assertIn("contourlayer",svg)
            self.assertIn("°C",svg)

    def test_excessive_manual_levels_keep_tiles(self):
        f=grid()
        apply_heatmap_presentation(f,HYBRID,interval=.00001)
        self.assertEqual(len(f.data),1)

if __name__=="__main__":unittest.main()
