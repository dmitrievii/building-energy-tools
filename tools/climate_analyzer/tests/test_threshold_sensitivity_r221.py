"""R2.21 C: direct-mask parity, missing observations, cadence and shared atlas."""
import unittest
from unittest.mock import patch
import itertools
import numpy as np
import pandas as pd
from epw_climate_analyzer.threshold_sensitivity import joint_counts,calculate,figure,shading_geometry_figure,SPECS
from epw_climate_analyzer.decisions import natural_ventilation_condition,night_flushing_condition,economizer_condition,shading_condition
from epw_climate_analyzer.p3_comfort import T,W,V

G="global_horizontal_radiation_wh_m2"
H="moist_air_enthalpy_kj_kg"

class ThresholdSensitivityTests(unittest.TestCase):
    def setUp(self):
        idx=pd.date_range("2026-07-01",periods=96,freq="30min")
        n=np.arange(len(idx))
        self.df=pd.DataFrame({T:24+8*np.sin(2*np.pi*(idx.hour-8)/24),
            W:5+n%12,V:0.5+(n%15)*.5,H:30+n%40,G:20+n%40*10,
            "hour_of_day":idx.hour,"vapor_pressure_pa":500+n*20,
            "solar_azimuth_deg":180.,"solar_apparent_zenith_deg":45.},index=idx)
        self.df.attrs["canonical_native_interval_minutes"]=30.

    def test_exact_joint_counts_all_comparator_combinations(self):
        import operator
        ops={"<":operator.lt,"<=":operator.le,">":operator.gt,">=":operator.ge}
        a=np.array([0.,1.,2.,3.,np.nan,2.])
        b=np.array([3.,2.,1.,0.,1.,np.nan])
        x=np.array([0.,1.,2.,3.]);y=np.array([0.,1.,2.,3.])
        for xo,yo in itertools.product(ops,repeat=2):
            expected=np.array([[(ops[xo](a,xx)&ops[yo](b,yy)&np.isfinite(a)&np.isfinite(b)).sum() for xx in x] for yy in y])
            np.testing.assert_array_equal(joint_counts(a,b,x,y,x_op=xo,y_op=yo),expected)

    def test_nv_maps_match_original_screen_with_cross_midnight_schedule(self):
        df=self.df.copy()
        df.iloc[4,df.columns.get_loc(W)]=np.nan
        fixed=dict(t_min_c=16.,t_max_c=26.,d_max_g_kg=10.,
                   wind_min_m_s=.5,wind_max_m_s=6.,occupied_only=True,
                   occupied_start_hour=22,occupied_end_hour=6,weekdays_only=False)
        cases=(("nv_temperature_moisture",[22,26,30],[7,10,14],"t_max_c","d_max_g_kg"),
               ("nv_temperature_range",[12,16,24],[20,26,30],"t_min_c","t_max_c"),
               ("nv_wind_range",[0,.5,2],[1,6,9],"wind_min_m_s","wind_max_m_s"))
        for kind,x,y,kx,ky in cases:
            z,den=calculate(df,kind,x,y,fixed=fixed)
            valid=((df.hour_of_day>=22)|(df.hour_of_day<=6))&df[W].notna()
            self.assertEqual(den,valid.sum()*.5)
            for i,yy in enumerate(y):
                for j,xx in enumerate(x):
                    p={**fixed,kx:xx,ky:yy}
                    if p["t_min_c"]>p["t_max_c"] or p["wind_min_m_s"]>p["wind_max_m_s"]:
                        self.assertTrue(np.isnan(z[i,j]));continue
                    self.assertEqual(z[i,j],natural_ventilation_condition(df,**p).sum()*.5)

    def test_night_reference_requires_complete_day_and_matches_existing_kernel(self):
        for frame in (self.df,self.df.drop(self.df.index[4])):
            x=[20.,26.,30.];y=[16.,20.,24.]
            z,den=calculate(frame,"night",x,y)
            for i,yy in enumerate(y):
                for j,xx in enumerate(x):
                    self.assertEqual(z[i,j],night_flushing_condition(frame,xx,yy).sum()*.5)
            self.assertGreater(den,0)

    def test_night_difference_and_night_count_match_individual_observations(self):
        from epw_climate_analyzer.decisions import night_flushing_reference
        night,hot=night_flushing_reference(self.df)
        t=self.df[T]
        valid=night & hot.notna() & t.notna()
        idx=self.df.index
        anchors=idx.normalize().where(idx.hour>6,idx.normalize()-pd.DateOffset(days=1))
        x=[0.,4.,8.];y=[16.,20.,24.]
        hours,den=calculate(self.df,"night_delta",x,y)
        nights,n_den=calculate(self.df,"night_delta",x,y,basis="nights")
        self.assertEqual(den,valid.sum()*.5)
        self.assertEqual(n_den,len(set(anchors[valid])))
        for i,yy in enumerate(y):
            for j,xx in enumerate(x):
                mask=valid & ((hot-t)>=xx) & (t<=yy)
                self.assertEqual(hours[i,j],mask.sum()*.5)
                self.assertEqual(nights[i,j],len(set(anchors[mask])))

    def test_solar_and_economizer_match_single_threshold_masks(self):
        for kind,x,y in (("solar",[20.,24.,30.],[100.,250.,500.]),
                         ("economizer",[20.,24.,28.],[35.,50.,65.])):
            z,den=calculate(self.df,kind,x,y)
            self.assertEqual(den,48.)
            for i,yy in enumerate(y):
                for j,xx in enumerate(x):
                    expected=shading_condition(self.df,xx,yy*.5) if kind=="solar" else economizer_condition(self.df,yy,t_max_c=xx)
                    self.assertEqual(z[i,j],expected.sum()*.5)

    def test_surface_rh_exact_pressure_threshold(self):
        import psychrolib
        x=[5.,12.,20.];y=[70.,80.,100.]
        z,den=calculate(self.df,"surface",x,y)
        for i,yy in enumerate(y):
            for j,xx in enumerate(x):
                expected=(self.df["vapor_pressure_pa"]>=psychrolib.GetSatVapPres(xx)*yy/100).sum()*.5
                self.assertEqual(z[i,j],expected)
        self.assertEqual(den,48.)
        self.assertTrue(np.all(np.diff(z,axis=1)<=0))

    def test_geometry_reuses_poa_and_matches_direct_fraction(self):
        from epw_climate_analyzer.solar_shading import shaded_fraction
        df=self.df
        direct=np.full(len(df),100.)
        geometry=dict(facade=180.,width=2.,height=1.5,overhang=.6,left_fin=0.,right_fin=0.)
        ledger=pd.DataFrame({"Unshaded direct":direct,"Intercepted direct":direct*shaded_fraction(df.solar_azimuth_deg,90-df.solar_apparent_zenith_deg,**geometry)},index=df.index)
        with patch("epw_climate_analyzer.solar_shading.shading_ledger",return_value=ledger) as mock:
            f,note=shading_geometry_figure(df,[0.,.6,1.],[0.,.5,1.],geometry=geometry)
            self.assertEqual(mock.call_count,1)
        self.assertEqual(f.data[0].z[0][0],0.)
        self.assertAlmostEqual(f.data[0].z[0][1],ledger["Intercepted direct"].sum()/1000.)
        self.assertTrue(np.all(np.diff(f.data[0].z,axis=1)>=-1e-10))

    def test_atlas_uses_shared_interpretation_and_no_monthly_admission(self):
        from epw_climate_analyzer.p66_catalogue import Diagram,NV
        from epw_climate_analyzer.p66_render import make_figure
        from epw_climate_analyzer.figure_interpretation_contract import validate_figure_interpretation
        kind="nv_temperature_moisture";spec=SPECS[kind]
        d=Diagram("test",NV,spec.title,"threshold_sensitivity",args=(kind,))
        f,note=make_figure(d,self.df,{})
        expected,expected_note=figure(self.df,kind,np.linspace(*spec.x_range,21),np.linspace(*spec.y_range,21))
        self.assertEqual(note,expected_note)
        np.testing.assert_array_equal(f.data[0].z,expected.data[0].z)
        self.assertTrue(validate_figure_interpretation(f,note))
        df=self.df.copy();df.attrs["canonical_native_resolution"]="monthly"
        with self.assertRaises(ValueError):calculate(df,kind,[26.],[9.])

if __name__=="__main__":
    unittest.main()
