"""P3 physical invariants; independent official reference campaign pending."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer import p3_comfort as p

class P3Tests(unittest.TestCase):
    def fixture(self):
        df=pd.DataFrame({p.T:20.,p.RH:50.,p.W:7.,p.SV:.8,p.V:1.,p.DEW:10.,
                         p.GHI:400.,p.DHI:100.,p.DNI:600.,p.LW:350.,p.ZEN:45.},
                        index=pd.date_range("2025-06-01",periods=240,freq="h"))
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_utci_reference_and_limits(self):
        z=p.utci_values([25.,25.,55.,25.,25.],[25.,25.,55.,100.,25.],[1.,.1,1.,1.,1.],[50.,50.,50.,50.,101.])
        self.assertAlmostEqual(z[0],24.6,delta=.1)
        self.assertTrue(np.isnan(z[1:]).all())

    def test_radiation_closure(self):
        df=self.fixture();tr=p.radiant_scenarios(df)
        self.assertTrue((tr["Open sun"]>tr["Direct-beam shade"]).all())
        df[p.DNI]=0.;tr=p.radiant_scenarios(df)
        np.testing.assert_allclose(tr["Open sun"],tr["Direct-beam shade"])
        df.loc[df.index[0],p.LW]=np.nan
        self.assertTrue(p.radiant_scenarios(df).iloc[0].isna().all())

    def test_loads(self):
        df=self.fixture().iloc[:2].copy()
        df.attrs["canonical_native_interval_minutes"]=30.
        df[p.T]=[10.,30.];df[p.W]=[2.,12.]
        q=p.ventilation_loads(df,airflow=3600,heat=20,cool=26,w_low=3,w_high=10)
        self.assertAlmostEqual(q.iloc[0,0],1.25*(1.006+1.86*.002)*10*.5)
        self.assertAlmostEqual(q.iloc[1,3],1.25*2501*.002*.5)
        self.assertEqual(q.iloc[1,0],0.)
        self.assertAlmostEqual(p.moisture_loads(df,airflow=3600,target=10).iloc[1,1],3600/.8*.002*.5)
        df.loc[df.index[0],p.SV]=np.nan
        self.assertTrue(p.ventilation_loads(df,airflow=3600,heat=20,cool=26,w_low=3,w_high=10).iloc[0].isna().all())

    def test_adaptive(self):
        df=self.fixture();a=p.adaptive_bands(df)
        self.assertTrue(a.Neutral.iloc[:7].isna().all())
        self.assertAlmostEqual(a.Neutral.iloc[7],25.4)
        self.assertAlmostEqual(a["II lower"].iloc[7],21.4)
        self.assertAlmostEqual(a["II upper"].iloc[7],28.4)
        df.loc[df.index[7*24:],p.T]=50.
        self.assertAlmostEqual(p.adaptive_bands(df).Neutral.iloc[7],25.4)
        self.assertTrue(np.isnan(p.adaptive_bands(df.drop(df.index[24])).Neutral.iloc[7]))

    def test_persistence(self):
        idx=pd.to_datetime(["2025-06-01 22:00","2025-06-01 23:00","2025-06-02 00:00","2025-06-02 02:00","2025-06-02 03:00"])
        df=pd.DataFrame(index=idx);df.attrs["canonical_native_interval_minutes"]=60.
        a=p.persistence(df,pd.Series([1.,1.,1.,1.,np.nan],index=idx),night=True)
        self.assertEqual(len(a),1)
        self.assertEqual(a.iloc[0]["Longest run [h]"],3.)
        self.assertEqual(a.iloc[0]["Suitable hours [h]"],4.)
        self.assertEqual(a.iloc[0]["Valid hours [h]"],4.)

    def test_persistence_monthly_threshold_and_unknown_days(self):
        table=pd.DataFrame({"Longest run [h]":[2.,4.,0.,np.nan,1.]},
            index=pd.to_datetime(["2025-06-01","2025-06-02","2025-06-03","2025-06-04","2025-08-01"]))
        a=p.persistence_monthly(table,2.)
        self.assertEqual(a.iloc[0]["Meets minimum"],2.)
        self.assertEqual(a.iloc[0]["Below minimum"],1.)
        self.assertEqual(a.iloc[0]["Observed days"],3.)
        self.assertTrue(a.iloc[1].isna().all())
        self.assertEqual(a.iloc[2]["Below minimum"],1.)

    def test_wind_suitability_retains_empty_intervening_bins(self):
        df=self.fixture().iloc[:2].copy()
        df[p.T]=[10.,16.]
        df[p.V]=[1.,3.]
        z,h=p.suitability_grid(df,pd.Series([0.,1.],index=df.index),axis=p.V)
        self.assertEqual(z.shape,(5,4))
        self.assertEqual(z.iloc[0,0],0.)
        self.assertEqual(z.iloc[-1,-1],100.)
        self.assertTrue(np.isnan(z.iloc[1,1]))
        self.assertAlmostEqual(h.sum().sum(),2.)

    def test_classes_and_suitability(self):
        df=self.fixture().iloc[:3].copy()
        a=p.utci_class_hours(df,pd.Series([9.,26.,np.nan],index=df.index))
        self.assertAlmostEqual(a.sum().sum(),2.)
        self.assertAlmostEqual(a["Slight cold"].sum(),1.)
        self.assertAlmostEqual(a["No thermal stress"].sum(),1.)
        z,h=p.suitability_grid(df,pd.Series([1.,0.,np.nan],index=df.index),axis=p.W)
        self.assertAlmostEqual(z.stack().iloc[0],50.)
        self.assertAlmostEqual(h.stack().iloc[0],2.)
        self.assertEqual(p.condensation_margin(df,10.).iloc[0],0.)

    def test_p3_route_contract(self):
        import ast
        from pathlib import Path
        from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES,navigation_label
        from epw_climate_analyzer.historical_capabilities import available_historical_pages
        root=Path(__file__).resolve().parents[1]
        source=(root/"app.py").read_text(encoding="utf-8")
        funcs={n.name:ast.get_source_segment(source,n) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
        self.assertIn("Outdoor Thermal Comfort",NAVIGATION_PAGES)
        self.assertEqual(navigation_label("Outdoor Thermal Comfort"),"Design — Outdoor thermal comfort")
        self.assertIn("Outdoor Thermal Comfort",available_historical_pages(self.fixture()))
        self.assertNotIn("Outdoor Thermal Comfort",available_historical_pages(self.fixture().drop(columns=[p.V])))
        for name in ("main","render_canonical_climate_analysis","render_generated_climate_analysis"):
            self.assertIn("render_outdoor_comfort(",funcs[name])
            self.assertIn("attach_adaptive(",funcs[name])
        parity=(root/"epw_climate_analyzer/source_parity_ui.py").read_text(encoding="utf-8")
        self.assertIn("legacy.render_outdoor_comfort(filtered_df)",parity)
        self.assertIn("attach_adaptive(full_df)",parity)
        for name,panel in (("render_natural_ventilation","nv_sensitivity"),
                           ("render_natural_ventilation","persistence_panel"),
                           ("render_hvac_passive","ventilation_load_panel"),
                           ("render_hvac_passive","adaptive_panel"),
                           ("render_humidity","condensation_panel"),
                           ("render_humidity","moisture_panel"),
                           ("render_sky_daylight","illuminance_panel")):
            self.assertIn(panel,funcs[name])
        self.assertNotIn("fillna(1.2)",funcs["render_hvac_passive"])
        self.assertIn('"Temperature–wind suitability"',funcs["render_natural_ventilation"])
        self.assertIn('"Continuous ventilation periods"',funcs["render_natural_ventilation"])
        self.assertNotIn('"Daily consecutive availability"',funcs["render_natural_ventilation"])
        ui=(root/"epw_climate_analyzer/p3_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("Temperature × humidity ratio",ui)
        self.assertIn("NV_SUITABILITY_SCALE",ui)
        self.assertIn("importlib.reload(_navigation_contract)",source)

if __name__=="__main__":unittest.main()
