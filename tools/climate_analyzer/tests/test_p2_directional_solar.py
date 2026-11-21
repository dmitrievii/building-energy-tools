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
                self.assertEqual(sky_figure(t,"Total").data[0].type,"barpolar")
                self.assertEqual(sky_figure(t,"Total","3D dome").data[0].type,"mesh3d")
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
