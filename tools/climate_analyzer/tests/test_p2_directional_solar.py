"""P2 closed numerical invariants; no claim of independent production validation."""
import unittest
from io import BytesIO
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from PIL import Image
from epw_climate_analyzer.sky_distribution import patches, sun_bins, cumulative_sky, sky_figure
from epw_climate_analyzer.solar_shading import shaded_fraction, shading_ledger, overlay_shading_mask
from epw_climate_analyzer.surface_radiation_views import poa_frame, with_diffuse_fraction, orientation_curves, FRACTION
from epw_climate_analyzer.architectural_underlay import prepare_underlay, apply_underlay
from epw_climate_analyzer.monthly_radiation import SOURCE_FIELDS, SURFACE_FIELDS

def fixture():
    df=pd.DataFrame({"solar_apparent_zenith_deg":[60.,30.,45.,110.,60.,60.],
                     "solar_azimuth_deg":[90.,180.,270.,0.,180.,180.],
                     "solar_elevation_deg":[30.,60.,45.,-20.,30.,30.],
                     SOURCE_FIELDS["GHI"]:[400.,600.,500.,0.,200.,np.nan],
                     SOURCE_FIELDS["DHI"]:[100.,150.,100.,0.,100.,np.nan],
                     SOURCE_FIELDS["DNI"]:[600.,500.,500.,0.,200.,300.],
                     "dry_bulb_temperature_c":[10.,20.,30.,5.,10.,20.]},
                     index=pd.date_range("2025-06-21 08:00",periods=6,freq="h"))
    df.attrs["canonical_native_interval_minutes"]=60.
    return df

class P2Tests(unittest.TestCase):
    def test_sky_geometry_and_horizontal_energy(self):
        df=fixture()
        valid=[0,1,2,4]
        direct=np.sum(df[SOURCE_FIELDS["DNI"]].iloc[valid]*np.cos(np.deg2rad(df.solar_apparent_zenith_deg.iloc[valid])))/1000
        diffuse=df[SOURCE_FIELDS["DHI"]].iloc[valid].sum()/1000
        for mf,n in ((1,145),(2,577)):
            p=patches(mf)
            self.assertEqual(len(p),n)
            self.assertAlmostEqual(p.solid_angle.sum(),2*np.pi)
            self.assertAlmostEqual(p.projected_angle.sum(),np.pi)
            self.assertEqual(sun_bins(np.array([0.]),np.array([90.]),mf)[0],n-1)
            for model in ("Isotropic","Perez 1993 (research)"):
                t=cumulative_sky(df,mf=mf,model=model)
                self.assertEqual(t.attrs["valid_intervals"],4)
                self.assertAlmostEqual(t.direct_kwh_m2.sum(),direct,places=10)
                self.assertAlmostEqual(t.diffuse_kwh_m2.sum(),diffuse,places=10)
                np.testing.assert_allclose(t.total_kwh_m2,t.direct_kwh_m2+t.diffuse_kwh_m2)
                self.assertTrue((t.total_kwh_m2>=0).all())
                two=sky_figure(t,"Total")
                three=sky_figure(t,"Total","3D dome")
                self.assertEqual(two.data[0].type,"barpolar")
                self.assertEqual(three.data[0].type,"mesh3d")
                self.assertEqual(two.data[0].marker.colorscale[0],(0.,"#FFFFFF"))
                self.assertEqual(two.data[0].marker.colorscale,three.data[0].colorscale)
                self.assertEqual(three.data[0].cmin,0)
                labels=next(tr for tr in three.data if tr.name=="Compass labels")
                self.assertEqual(tuple(labels.text),("N","E","S","W"))
                self.assertGreater(labels.y[0],0)
                self.assertGreater(labels.x[1],0)
                self.assertLess(labels.y[2],0)
                self.assertLess(labels.x[3],0)
                self.assertEqual(len(sky_figure(t,"Total","3D dome",show_compass=False).data),1)
            iso=cumulative_sky(df,mf=mf,model="Isotropic")
            ani=cumulative_sky(df,mf=mf,model="Perez 1993 (research)")
            self.assertFalse(np.allclose(iso.diffuse_kwh_m2,ani.diffuse_kwh_m2))
        only=df.drop(columns=[SOURCE_FIELDS["DNI"]])
        self.assertAlmostEqual(cumulative_sky(only,quantity="Diffuse").diffuse_kwh_m2.sum(),diffuse)
        with self.assertRaises(ValueError):
            cumulative_sky(only,quantity="Total")

    def test_shading_aperture_geometry_and_energy(self):
        az=np.array([180.,180.,0.,np.nan])
        el=np.array([45.,45.,45.,45.])
        opts=dict(facade=180.,width=2.,height=2.,samples=40)
        f=shaded_fraction(az,el,overhang=1.,**opts)
        np.testing.assert_allclose(f[:3],[.5,.5,0.],atol=1e-12)
        self.assertTrue(np.isnan(f[-1]))
        self.assertEqual(float(shaded_fraction(180.,45.,overhang=0.,**opts)),0.)
        self.assertEqual(float(shaded_fraction(180.,45.,overhang=2.,**opts)),1.)
        self.assertGreater(float(shaded_fraction(225.,45.,right_fin=2.,**opts)),0.)
        df=fixture()
        ledger=shading_ledger(df,overhang=1.,**opts)
        np.testing.assert_allclose(ledger["Remaining direct"]+ledger["Intercepted direct"],ledger["Unshaded direct"],equal_nan=True)
        np.testing.assert_allclose(ledger["Shaded total (direct-only)"]+ledger["Intercepted direct"],ledger["Unshaded total"],equal_nan=True)
        self.assertTrue((ledger["Intercepted direct"].dropna()>=0).all())
        self.assertTrue(np.isnan(ledger["Unshaded total"].iloc[-1]))
        fig=go.Figure()
        overlay_shading_mask(fig,overhang=1.,**opts)
        self.assertEqual(fig.data[0].type,"scatterpolargl")
        self.assertEqual(len(fig.data),5)
        self.assertIn("unshaded",fig.data[0].name)
        self.assertIn("full shade",fig.data[-1].name)
        for tr in fig.data:
            for azm,elev,shade in tr.customdata:
                if azm is None:continue
                self.assertGreater(np.cos(np.deg2rad(azm-180)),0)
                self.assertAlmostEqual(float(shaded_fraction(azm,elev,overhang=1.,**opts))*100,shade)
        other=go.Figure()
        overlay_shading_mask(other,inverted=True,overhang=1.,**opts)
        self.assertEqual(fig.to_json(),other.to_json())
        cart=go.Figure()
        overlay_shading_mask(cart,technical=True,overhang=1.,**opts)
        self.assertTrue(all(tr.type=="scattergl" for tr in cart.data))

    def test_window_sketch_respects_geometry_and_zero_depth(self):
        from epw_climate_analyzer.shading_sketch import window_shading_sketch
        from epw_climate_analyzer.chart_presentation import apply_chart_presentation,ChartPresentationSettings
        fig=window_shading_sketch(facade=135,width=2.5,height=1.8,overhang=.7,left_fin=.3,right_fin=1.2)
        meta=fig.layout.meta["shading_geometry"]
        self.assertEqual(meta["facade"],135)
        self.assertEqual(meta["width"],2.5)
        self.assertEqual(meta["left_fin"],.3)
        fin=next(tr for tr in fig.data if tr.name=="Right fin")
        self.assertEqual(tuple(fin.y),(0,1.2))
        overhang=next(tr for tr in fig.data if tr.name=="Overhang projection")
        self.assertEqual(max(overhang.y),.7)
        text=[ann.text for ann in fig.layout.annotations]
        for label in ("W = 2.50 m","H = 1.80 m","L = 0.30 m","R = 1.20 m","D = 0.70 m","Façade azimuth 135°"):
            self.assertIn(label,text)
        self.assertEqual(fig.layout.yaxis.scaleanchor,"x")
        self.assertEqual(fig.layout.yaxis2.scaleanchor,"x2")
        apply_chart_presentation(fig,ChartPresentationSettings(background="Transparent"))
        self.assertEqual(fig.layout.paper_bgcolor,"rgba(0,0,0,0)")
        empty=window_shading_sketch()
        self.assertNotIn("Overhang projection",[tr.name for tr in empty.data])
        self.assertNotIn("Left fin",[tr.name for tr in empty.data])
        self.assertNotIn("Right fin",[tr.name for tr in empty.data])

    def test_poa_and_fraction(self):
        df=fixture()
        t=poa_frame(df,90.,180.,.2)
        np.testing.assert_allclose(t[SURFACE_FIELDS["Total POA"]],t[SURFACE_FIELDS["Direct"]]+t[SURFACE_FIELDS["Sky diffuse"]]+t[SURFACE_FIELDS["Ground-reflected"]],equal_nan=True)
        self.assertNotIn(SURFACE_FIELDS["Total POA"],df)
        frac=with_diffuse_fraction(df)
        self.assertEqual(frac[FRACTION].iloc[0],25.)
        self.assertTrue(np.isnan(frac[FRACTION].iloc[3]))
        self.assertTrue(np.isnan(frac[FRACTION].iloc[-1]))
        fig=orientation_curves(pd.DataFrame({0:[1,2],90:[3,4],180:[5,6],270:[7,8]},index=[0,90]))
        self.assertEqual(fig.data[0].x[-1],360)
        self.assertEqual(fig.data[0].y[-1],fig.data[0].y[0])

    def test_image_underlay_is_opt_in_compass_only(self):
        buf=BytesIO();Image.new("RGB",(60,40),"#33aa77").save(buf,format="PNG")
        source=prepare_underlay(buf.getvalue(),90)
        self.assertTrue(source.startswith("data:image/png;base64,"))
        f=go.Figure(go.Barpolar(theta=[0],r=[1]))
        self.assertFalse(apply_underlay(f,source))
        f.update_layout(meta={"compass_polar":True})
        self.assertTrue(apply_underlay(f,source,scale=.5,x=.1,y=-.1))
        self.assertEqual(len(f.layout.images),1)
        self.assertAlmostEqual(f.layout.images[0].x,.6)
        self.assertEqual(f.layout.polar.bgcolor,"rgba(0,0,0,0)")
        self.assertEqual(tuple(f.data[0].r),(1,))

if __name__=="__main__":
    unittest.main()
