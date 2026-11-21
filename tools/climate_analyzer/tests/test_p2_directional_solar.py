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
        opts=dict(facade=180.,width=2.,height=2.)
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

    def test_temporal_shading_device_closure_and_month_hour_bins(self):
        from epw_climate_analyzer.solar_shading import DEVICES, TOTAL_DEVICE, _shading_components
        from epw_climate_analyzer.shading_temporal import (
            ENERGY, REDUCTION, AREA, temporal_shading_tables,
            shading_monthly_rose, shading_month_hour_heatmap,
        )
        geometry=dict(facade=180.,width=2.,height=2.,overhang=1.,left_fin=.5,right_fin=1.)
        az=np.array([135.,180.,225.,0.,np.nan])
        el=np.array([35.,45.,35.,30.,45.])
        f,c,front=_shading_components(az,el,**geometry)
        np.testing.assert_allclose(c.sum(axis=-1),f,equal_nan=True)
        self.assertGreater(c[0,1],0)
        self.assertEqual(c[0,2],0)
        self.assertGreater(c[2,2],0)
        self.assertEqual(c[2,1],0)
        self.assertFalse(front[3])
        self.assertTrue(np.isnan(c[4]).all())
        df=fixture()
        df.index=pd.to_datetime(["2025-01-01 08:00","2025-06-01 12:00","2025-06-01 17:00",
                                 "2025-06-01 01:00","2025-06-02 12:00","2025-07-01 12:00"])
        ledger=shading_ledger(df,**geometry)
        np.testing.assert_allclose(ledger[[d+" intercepted direct" for d in DEVICES]].sum(axis=1,min_count=3),ledger["Intercepted direct"],equal_nan=True)
        monthly,cells=temporal_shading_tables(df,geometry=geometry,metric=ENERGY)
        self.assertAlmostEqual(monthly[TOTAL_DEVICE].sum(),ledger["Intercepted direct"].sum()/1000)
        self.assertAlmostEqual(cells[TOTAL_DEVICE].sum(),monthly[TOTAL_DEVICE].sum())
        self.assertTrue(np.isnan(cells.loc[(7,12),TOTAL_DEVICE]))
        self.assertTrue(np.isnan(monthly.loc[2,TOTAL_DEVICE]))
        self.assertEqual(cells.loc[(6,1),TOTAL_DEVICE],0.)
        mr,cr=temporal_shading_tables(df,geometry=geometry,metric=REDUCTION)
        expected=100*ledger.loc[ledger.index.month==6,"Intercepted direct"].sum()/ledger.loc[ledger.index.month==6,"Unshaded direct"].sum()
        self.assertAlmostEqual(mr.loc[6,TOTAL_DEVICE],expected)
        self.assertTrue(np.isnan(cr.loc[(6,1),TOTAL_DEVICE]))
        ma,ca=temporal_shading_tables(df,geometry=geometry,metric=AREA)
        self.assertTrue(np.isnan(ca.loc[(6,1),TOTAL_DEVICE]))
        self.assertTrue(np.isfinite(ca.loc[(6,12),TOTAL_DEVICE]))
        rose=shading_monthly_rose(monthly,ENERGY)
        self.assertEqual(rose.layout.barmode,"stack")
        self.assertEqual(tuple(t.name for t in rose.data),DEVICES)
        np.testing.assert_allclose(np.sum([np.asarray(t.r,dtype=float) for t in rose.data],axis=0),monthly[TOTAL_DEVICE],equal_nan=True)
        heat=shading_month_hour_heatmap(cr,REDUCTION,"Left fin")
        self.assertEqual(np.asarray(heat.data[0].z).shape,(12,24))
        self.assertEqual(heat.data[0].zmax,100)
        self.assertTrue(np.isnan(heat.data[0].z[5,1]))
        multi=df.copy()
        multi.index=multi.index.where(multi.index.month!=7,multi.index+pd.DateOffset(years=1))
        with self.assertRaises(ValueError):
            temporal_shading_tables(multi,geometry=geometry,metric=ENERGY)

    def test_monthly_shading_figure_stacks_only_complementary_components(self):
        from epw_climate_analyzer.solar_shading import monthly_shading_figure
        table=pd.DataFrame({"Unshaded total":[100.,80.,np.nan,60.],
                            "Shaded total (direct-only)":[70.,80.,np.nan,0.],
                            "Intercepted direct":[30.,0.,np.nan,60.]})
        labels=["Jan","Feb","Mar","Apr"]
        fig=monthly_shading_figure(table,labels)
        self.assertEqual(fig.layout.barmode,"stack")
        self.assertEqual(tuple(tr.type for tr in fig.data),("bar","bar","scatter"))
        self.assertEqual(tuple(tr.name for tr in fig.data),
                         ("Shaded total (direct-only)","Intercepted direct","Unshaded total"))
        for tr in fig.data:
            self.assertEqual(tuple(tr.x),tuple(labels))
            np.testing.assert_allclose(tr.y,table[tr.name],equal_nan=True)
        np.testing.assert_allclose(np.asarray(fig.data[0].y)+np.asarray(fig.data[1].y),
                                   fig.data[2].y,equal_nan=True)
        self.assertFalse(fig.data[2].connectgaps)

    def test_analytical_shading_closed_forms(self):
        # At azimuth difference 45° and elevation atan(cos(45°)),
        # both projected slopes relative to the façade normal are one.
        elevation=np.rad2deg(np.arctan(np.cos(np.deg2rad(45.))))
        opts=dict(facade=180.,width=2.,height=2.)
        def f(o=0.,l=0.,r=0.,az=225.):
            return float(shaded_fraction(az,elevation,overhang=o,left_fin=l,right_fin=r,**opts))
        # Unit-depth top and sunward fin each cover 1.5 m² of a 4 m²
        # window; total 3 m². Opposite fin contributes nothing.
        self.assertAlmostEqual(f(o=1.),.375,places=14)
        self.assertAlmostEqual(f(r=1.),.375,places=14)
        self.assertAlmostEqual(f(o=1.,r=1.),.75,places=14)
        self.assertAlmostEqual(f(o=.5,r=1.),.59375,places=14)
        self.assertEqual(f(l=2.),0.)
        self.assertAlmostEqual(f(l=1.,az=135.),f(r=1.),places=14)
        self.assertAlmostEqual(f(o=2.),.5,places=14)
        self.assertEqual(f(o=2.,r=2.),1.)
        self.assertEqual(f(o=2.,l=2.,r=2.),1.)
        # Due-normal sun; fractional shade not representable by old grids.
        self.assertAlmostEqual(float(shaded_fraction(180.,45.,overhang=.137,**opts)),.0685,places=14)
        for azm,elev in ((0,45),(270,45),(90,45),(180,0),(180,-10),(180,90)):
            self.assertEqual(float(shaded_fraction(azm,elev,overhang=10.,left_fin=10.,right_fin=10.,**opts)),0.)
        for azm,elev in ((np.nan,45),(180,np.nan),(180,91),(180,-91)):
            self.assertTrue(np.isnan(shaded_fraction(azm,elev,overhang=1.,**opts)))
        grid=shaded_fraction(np.array([[135.,180.,225.]]),np.array([[10.],[45.],[80.]]),overhang=.6,left_fin=.2,right_fin=.8,**opts)
        self.assertEqual(grid.shape,(3,3))
        self.assertTrue(np.all((grid>=0)&(grid<=1)))

    def test_against_independent_projected_polygon_clipping(self):
        # Independently project the four actual vertices of each device
        # onto the glazing plane along the 3D solar direction, then clip
        # and integrate polygons with the shoelace formula. The reference
        # is deliberately not the production ray-exit integral.
        def clip(poly,axis,bound,greater):
            result=[]
            if not len(poly):return result
            def inside(v):return v[axis]>=bound if greater else v[axis]<=bound
            prev=poly[-1]
            for cur in poly:
                a,b=inside(prev),inside(cur)
                if a!=b:
                    t=(bound-prev[axis])/(cur[axis]-prev[axis])
                    result.append(prev+t*(cur-prev))
                if b:result.append(cur)
                prev=cur
            return result
        def area(poly):
            if len(poly)<3:return 0.
            p=np.asarray(poly)
            return abs(np.dot(p[:,0],np.roll(p[:,1],-1))-np.dot(p[:,1],np.roll(p[:,0],-1)))/2
        def ref(a,e,w,h,o,l,r):
            ar,er=np.deg2rad([a,e])
            n=np.cos(er)*np.cos(ar)
            sx=np.cos(er)*np.sin(ar)/n
            sy=np.sin(er)/n
            rectangles=[
                [(-w/2,h,0),(w/2,h,0),(w/2,h,o),(-w/2,h,o)],
                [(-w/2,0,0),(-w/2,h,0),(-w/2,h,l),(-w/2,0,l)],
                [(w/2,0,0),(w/2,h,0),(w/2,h,r),(w/2,0,r)],
            ]
            total=0.
            for vertices in rectangles:
                poly=[np.array([x-sx*d,y-sy*d]) for x,y,d in vertices]
                for axis,bound,greater in ((0,-w/2,True),(0,w/2,False),(1,0,True),(1,h,False)):
                    poly=clip(poly,axis,bound,greater)
                total+=area(poly)
            return min(1.,total/(w*h))
        rng=np.random.default_rng(237)
        for _ in range(600):
            w,h=rng.uniform(.1,20,2)
            o,l,r=rng.uniform(0,10,3)
            a,e=rng.uniform(-89.9,89.9),rng.uniform(.05,89.95)
            expected=ref(a,e,w,h,o,l,r)
            actual=float(shaded_fraction(180+a,e,facade=180.,width=w,height=h,overhang=o,left_fin=l,right_fin=r))
            self.assertAlmostEqual(actual,expected,places=10)
            self.assertLessEqual(actual,float(shaded_fraction(180+a,e,width=w,height=h,overhang=o+1,left_fin=l+1,right_fin=r+1))+1e-13)

    def test_sampling_selector_removed(self):
        import ast
        from pathlib import Path
        source=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=="render_shading_analysis")
        self.assertNotIn("Area sampling per dimension",ast.get_source_segment(source,node))
        self.assertNotIn('geometry["samples"]',ast.get_source_segment(source,node))

    def test_shading_design_navigation_and_shared_geometry(self):
        import ast
        from pathlib import Path
        from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES,navigation_label
        from epw_climate_analyzer.historical_capabilities import available_historical_pages
        root=Path(__file__).resolve().parents[1]
        source=(root/"app.py").read_text(encoding="utf-8")
        parsed=ast.parse(source)
        funcs={n.name:ast.get_source_segment(source,n) for n in parsed.body if isinstance(n,ast.FunctionDef)}
        self.assertEqual(navigation_label("Shading analysis"),"Design — Shading analysis")
        self.assertIn("Shading analysis",NAVIGATION_PAGES)
        self.assertIn("Shading analysis",available_historical_pages(fixture()))
        self.assertNotIn("Shading analysis",available_historical_pages(fixture().drop(columns=list(SOURCE_FIELDS.values()))))
        self.assertNotIn('"Shading analysis"',funcs["render_solar"])
        self.assertNotIn("_shading_geometry(",funcs["render_sun_path"])
        self.assertEqual(funcs["render_shading_design"].count("_shading_geometry("),1)
        self.assertIn("render_sun_path(df,shading_geometry=geometry)",funcs["render_shading_design"])
        self.assertIn("geometry=geometry",funcs["render_shading_design"])
        self.assertIn('"Shading analysis"',funcs["page_derivation_flags"])
        for route in ("main","render_generated_climate_analysis","render_canonical_climate_analysis"):
            self.assertIn("render_shading_design(",funcs[route])
        parity=(root/"epw_climate_analyzer/source_parity_ui.py").read_text(encoding="utf-8")
        self.assertIn("legacy.render_shading_design(filtered_df)",parity)

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
