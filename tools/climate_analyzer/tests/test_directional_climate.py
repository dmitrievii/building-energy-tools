import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer.directional_climate import *

class DirectionalTests(unittest.TestCase):
    def test_directions_units_and_missing(self):
        df=pd.DataFrame({"wind_speed_m_s":[2.,4.,0.,3.,2.],"wind_direction_deg":[360.,90.,180.,270.,np.nan],
            "dry_bulb_temperature_c":[10.,20.,30.,np.nan,15.],
            "humidity_ratio_g_kg":[8.,8.,8.,8.,8.],"specific_volume_m3_kg":[.8]*5,
            "liquid_precipitation_depth_mm":[2.,3.,4.,1.,1.],"moist_air_density_kg_m3":[1.2]*5},
            index=pd.date_range("2025-01-01",periods=5,freq="10min"))
        df.attrs["canonical_native_interval_minutes"]=10
        t=directional_table(df,colour="Temperature")
        self.assertAlmostEqual(t.valid_hours.sum(),2/6)
        self.assertEqual(t.loc[0,"colour"],10)
        self.assertEqual(t.loc[90,"colour"],20)
        self.assertAlmostEqual(directional_table(df,radial="Percentage").radius.sum(),100)
        self.assertEqual(directional_table(df,radial="Wind-driven rain exposure").loc[90,"radius"],12)
        self.assertAlmostEqual(directional_table(df,radial="Dynamic pressure potential").loc[90,"radius"],9.6)
        self.assertEqual(absolute_humidity(df).iloc[0],10)
        self.assertEqual(directional_figure(t,"Hours","Temperature","Test").data[0].type,"barpolar")
        self.assertEqual(len(directional_speed_figure(df,"wind_speed_m_s","wind_direction_deg","Test").data),16)
        nv=nv_valid_mask(df,pd.Series([True,False,True,True,True],index=df.index))
        self.assertTrue(pd.isna(nv.iloc[3]))

    def test_class_distribution_closure_and_boundaries(self):
        idx=pd.date_range("2025-01-01",periods=8,freq="10min")
        df=pd.DataFrame({"wind_speed_m_s":[1.,2.,4.,8.,2.,0.,3.,1.],
                         "wind_direction_deg":[0.,0.,90.,90.,180.,0.,270.,np.nan],
                         "dry_bulb_temperature_c":[-1.,10.,20.,30.,25.,15.,np.nan,10.],
                         "relative_humidity_pct":[10.,20.,40.,60.,80.,100.,90.,25.],
                         "humidity_ratio_g_kg":[2.,5.,9.,12.,7.,5.,8.,5.],
                         "specific_volume_m3_kg":[.8]*8,
                         "moist_air_enthalpy_kj_kg":[-2.,20.,40.,60.,80.,20.,30.,20.],
                         "moist_air_density_kg_m3":[1.2]*8},index=idx)
        df.attrs["canonical_native_interval_minutes"]=10
        options=colour_options(df,nv=True)
        for q in ("Temperature","Relative humidity","Humidity ratio","Absolute humidity","Enthalpy","Dynamic pressure potential","Natural ventilation suitability"):
            self.assertIn(q,options)
        nv=pd.Series([False,True,True,False,True,True,np.nan,True],index=idx)
        for q in options:
            table=directional_class_table(df,quantity=q,nv_mask=nv)
            hours=table.to_numpy().sum()
            self.assertAlmostEqual(hours,table.attrs["valid_hours"])
            self.assertAlmostEqual(hours,(5 if q in ("Temperature","Natural ventilation suitability") else 6)/6)
            percent=directional_class_table(df,quantity=q,radial="Percentage",nv_mask=nv)
            self.assertAlmostEqual(percent.to_numpy().sum(),100.)
            fig=directional_class_figure(table,"Class test")
            self.assertEqual(len(fig.data),len(table.columns))
            self.assertEqual(fig.layout.polar.barmode,"stack")
            self.assertAlmostEqual(sum(np.sum(tr.r) for tr in fig.data),hours)
        table=directional_class_table(df,quantity="Temperature",edges=(0,10,20,25,30))
        self.assertAlmostEqual(table.loc[0.,"10 – < 20"],1/6)
        self.assertAlmostEqual(table.loc[90.,"≥ 30"],1/6)
        table=directional_class_table(df,quantity="Natural ventilation suitability",nv_mask=nv)
        self.assertAlmostEqual(table["Suitable"].sum(),3/6)
        self.assertEqual(class_boundaries("0, 10, 20"),(0.,10.,20.))
        for invalid in ("","2,1","5,5","nan,2"):
            with self.assertRaises(ValueError):
                class_boundaries(invalid)
        empty=directional_class_table(df.iloc[0:0],quantity="Temperature")
        self.assertEqual(empty.attrs["valid_hours"],0.)
        self.assertEqual(empty.shape,(16,6))

    def test_epw_wind_preparation_requires_psychrometrics(self):
        import ast
        from pathlib import Path
        from epw_climate_analyzer.psychrometrics import add_psychrometric_properties
        source=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=="page_derivation_flags")
        namespace={}
        exec(ast.get_source_segment(source,node),namespace)
        self.assertEqual(namespace["page_derivation_flags"]("Wind and Ventilation"),(True,False))
        idx=pd.date_range("2025-01-01",periods=2,freq="h")
        df=pd.DataFrame({"dry_bulb_temperature_c":[15.,22.],"relative_humidity_pct":[50.,50.],
                         "atmospheric_station_pressure_pa":[101325.,101325.],
                         "wind_speed_m_s":[2.,4.],"wind_direction_deg":[0.,90.]},index=idx)
        derived=add_psychrometric_properties(df)
        for q in ("Absolute humidity","Enthalpy","Dynamic pressure potential","Natural ventilation suitability"):
            self.assertIn(q,colour_options(derived,nv=True))
