"""R2.22 deterministic architectural and sensitivity regression."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from epw_climate_analyzer.architectural_shading import (
    window_geometry_3d, shadow_polygons, comparison_figure, comparison_energy)
from epw_climate_analyzer.solar_shading import shaded_fraction
from epw_climate_analyzer.threshold_sensitivity import shading_geometry_figure, figure
from epw_climate_analyzer.p3_comfort import T

BASE=dict(facade=180.,width=2.,height=1.5,overhang=0.,left_fin=0.,right_fin=0.)

def area(p):
    return abs(np.dot(p[:,0],np.roll(p[:,1],-1))-np.dot(p[:,1],np.roll(p[:,0],-1)))/2

class ArchitecturalShadingTests(unittest.TestCase):
    def test_metric_mesh_and_zero_depth_devices(self):
        f=window_geometry_3d(**BASE)
        self.assertEqual(len([v for v in f.data if v.type=="mesh3d"]),5)
        g=dict(BASE,overhang=.7,left_fin=.2,right_fin=1.1)
        f=window_geometry_3d(**g)
        meshes=[v for v in f.data if v.type=="mesh3d"]
        self.assertEqual(len(meshes),8)
        np.testing.assert_allclose([max(v.y) for v in meshes[-3:]],[.7,.2,1.1])
        self.assertEqual(f.layout.scene.aspectmode,"data")
        self.assertEqual(f.layout.scene.dragmode,"orbit")

    def test_overhang_and_fins_match_analytical_area(self):
        for az in (105.,145.,180.,215.,255.):
            for el in (10.,40.,70.):
                for device in ("overhang","left_fin","right_fin"):
                    g=dict(BASE,**{device:.8})
                    polys=shadow_polygons(az,el,**g)
                    self.assertAlmostEqual(sum(area(p) for p in polys)/(g["width"]*g["height"]),
                        float(shaded_fraction(az,el,**g)),places=12)
        self.assertEqual(shadow_polygons(0.,35.,**dict(BASE,overhang=1.)),[])
        self.assertEqual(shadow_polygons(180.,-5.,**dict(BASE,overhang=1.)),[])

    def test_comparison_figure_serialization(self):
        cases=[("No shading",BASE),("Current",dict(BASE,overhang=.6)),("Candidate",dict(BASE,overhang=1.,left_fin=.5,right_fin=.5))]
        f=comparison_figure(cases,205.,45.,energy=[(0,800),(100,700),(250,550)])
        self.assertIn("250.0 kWh/m² intercepted",f.to_json())
        self.assertEqual(f.layout.xaxis.range,f.layout.xaxis3.range)

    def test_geometry_remaining_energy_and_candidate(self):
        idx=pd.date_range("2020-06-01",periods=3,freq="h")
        df=pd.DataFrame({"solar_azimuth_deg":[180.,220.,180.],"solar_apparent_zenith_deg":[45.,40.,110.]},index=idx)
        direct=np.array([400.,600.,0.]);total=direct+100.
        def ledger(frame,*,albedo=None,**g):
            fraction=shaded_fraction(frame.solar_azimuth_deg,90-frame.solar_apparent_zenith_deg,**g)
            lost=direct*fraction
            return pd.DataFrame({"Unshaded direct":direct,"Unshaded total":total,"Intercepted direct":lost,
                                 "Shaded total (direct-only)":total-lost},index=idx)
        with patch("epw_climate_analyzer.solar_shading.shading_ledger",side_effect=ledger), patch("epw_climate_analyzer.architectural_shading.shading_ledger",side_effect=ledger):
            kwargs=dict(geometry=BASE,candidate=(.5,.5))
            remaining,_=shading_geometry_figure(df,[0.,.5],[0.,.5],quantity="remaining",**kwargs)
            blocked,_=shading_geometry_figure(df,[0.,.5],[0.,.5],quantity="intercepted",**kwargs)
            ratio,_=shading_geometry_figure(df,[0.,.5],[0.,.5],quantity="total_percent",**kwargs)
            np.testing.assert_allclose(np.asarray(remaining.data[0].z)+np.asarray(blocked.data[0].z),1.3)
            np.testing.assert_allclose(ratio.data[0].z,np.asarray(blocked.data[0].z)/1.3*100)
            self.assertEqual(remaining.data[-1].name,"Selected candidate")
            self.assertEqual(float(remaining.data[0].z[0][0]),1.3)
            self.assertTrue(np.all(np.diff(np.asarray(remaining.data[0].z),axis=1)<=1e-12))
            cases=[("Candidate",dict(BASE,overhang=.5,left_fin=.5,right_fin=.5))]
            result=comparison_energy(df,cases,albedo=None)[0]
            self.assertAlmostEqual(result[0],float(blocked.data[0].z[1][1]))
            self.assertAlmostEqual(result[1],float(remaining.data[0].z[1][1]))

    def test_reference_relative_screen(self):
        df=pd.DataFrame({T:[16.,18.,22.,26.,28.]},index=pd.date_range("2020-01-01",periods=5,freq="h"))
        f,_=figure(df,"neutral",[16.,18.,20.],[24.,26.,28.],reference=(18.,26.),relative=True)
        self.assertAlmostEqual(float(f.data[0].z[1][1]),0.)
        self.assertLess(float(f.data[0].z[0][2]),0.)
        self.assertGreater(float(f.data[0].z[2][0]),0.)
        self.assertEqual(f.data[0].zmin,-f.data[0].zmax)

if __name__=="__main__":
    unittest.main()
