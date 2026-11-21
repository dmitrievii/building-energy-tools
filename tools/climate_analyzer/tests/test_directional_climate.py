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
