"""R2.10: scientific HVAC weather-screen regressions and atlas integration."""
from __future__ import annotations
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from epw_climate_analyzer import hvac_findings as h
from epw_climate_analyzer import p3_comfort as p3
from epw_climate_analyzer import p4_extremes as p4
from epw_climate_analyzer.decisions import economizer_condition


class HVACR210Tests(unittest.TestCase):
    @staticmethod
    def fixture(n=96):
        idx=pd.date_range("2026-06-01",periods=n,freq="h")
        t=np.tile([10.,22.,30.,32.],n//4+1)[:n]
        w=np.tile([3.,8.,12.,16.],n//4+1)[:n]
        df=pd.DataFrame({
            p3.T:t,p3.W:w,p4.H:1.006*t+w/1000*(2501+1.86*t),
            p3.SV:.8,p3.RH:60.,p3.V:1.5,
            "hour_of_day":idx.hour,"month_index":idx.month,
        },index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_conditioning_summary_additivity(self):
        df=self.fixture()
        ledger=p3.ventilation_loads(df,airflow=1000,heat=20,cool=26,w_low=4,w_high=9)
        s=h.conditioning_summary(df,ledger)
        self.assertEqual(s["Valid hours"],96.)
        self.assertAlmostEqual(s["Sensible total"],s["Sensible heating"]+s["Sensible cooling"])
        self.assertAlmostEqual(s["Latent total"],s["Latent humidification"]+s["Latent dehumidification"])
        self.assertAlmostEqual(s["Combined conditioning indicator"],s["Sensible total"]+s["Latent total"])
        self.assertAlmostEqual(s["Latent share [%]"],100*s["Latent total"]/s["Combined conditioning indicator"])
        note=h.conditioning_interpretation(df,ledger,airflow=1000,heat=20,cool=26,w_low=4,w_high=9)
        self.assertIn("1000",note.replace(",",""))
        self.assertIn("coincident observed hours",note)
        self.assertIn("kWh",note)

    def test_subhourly_counts_and_missing_source(self):
        df=self.fixture(96).iloc[:6].copy()
        df.index=pd.date_range("2026-06-01",periods=6,freq="30min")
        df.attrs["canonical_native_interval_minutes"]=30.
        df.loc[df.index[0],p3.W]=np.nan
        ledger=p3.ventilation_loads(df,airflow=1000,heat=20,cool=26,w_low=4,w_high=9)
        s=h.conditioning_summary(df,ledger)
        self.assertEqual(s["Valid hours"],2.5)
        self.assertEqual(s["Selected hours"],3.)
        self.assertTrue(ledger.iloc[0].isna().all())

    def test_conditioning_grouped_and_stacked(self):
        df=self.fixture()
        ledger=p3.ventilation_loads(df,airflow=1000,heat=20,cool=26,w_low=4,w_high=9)
        grouped=h.conditioning_monthly_figure(df,ledger,grouped=True)
        stacked=h.conditioning_monthly_figure(df,ledger,grouped=False)
        self.assertEqual(len(grouped.data),4)
        self.assertEqual(grouped.layout.barmode,"group")
        self.assertEqual(stacked.layout.barmode,"stack")
        self.assertEqual(sum(grouped.data[0].y),float(ledger["Sensible heating"].sum()))

    def test_economizer_stage_matches_admitted_mask(self):
        df=self.fixture()
        for limit in (35.,50.,65.):
            steps=h.economizer_stages(df,h_return=limit)
            expected=economizer_condition(df,return_air_enthalpy_kj_kg=limit)
            self.assertEqual(steps.Hours.iloc[-1],float(expected.sum()))
            self.assertTrue(steps.Hours.is_monotonic_decreasing)
            note=h.economizer_interpretation(df,h_return=limit)
            self.assertIn(f"{limit:g} kJ/kg",note)
            fig=h.economizer_stages_figure(steps)
            self.assertEqual(len(fig.data[0].y),3)

    def test_economizer_missing_values_and_physical_cadence(self):
        df=self.fixture(96).iloc[:6].copy()
        df.index=pd.date_range("2026-06-01",periods=6,freq="30min")
        df.attrs["canonical_native_interval_minutes"]=30.
        df.loc[df.index[0],p4.H]=np.nan
        steps=h.economizer_stages(df)
        self.assertEqual(steps.Hours.iloc[0],2.5)
        self.assertLessEqual(steps.Hours.iloc[2],steps.Hours.iloc[1])

    def test_ranked_design_candidates_require_complete_days(self):
        df=self.fixture(96)
        table=h.candidate_day_table(df,quantity=p3.T,ranking="Hottest days")
        self.assertEqual(len(table),4)
        fig=h.candidate_day_figure(table,quantity="Air temperature",unit="°C",ranking="Hottest days")
        self.assertEqual(fig.data[0].type,"bar")
        text=h.candidate_day_interpretation(table,quantity="Air temperature",unit="°C",ranking="Hottest days")
        self.assertIn("complete",text)
        partial=df.drop(df.index[8])
        candidates=h.candidate_day_table(partial,quantity=p3.T,ranking="Hottest days")
        self.assertEqual(len(candidates),3)
        self.assertNotIn(pd.Timestamp("2026-06-01"),candidates.index)
        self.assertEqual(len(h.candidate_day_table(df,quantity=p4.H,ranking="Highest enthalpy days")),4)
        self.assertEqual(len(h.candidate_day_table(df,quantity=p3.W,ranking="Most humid days")),4)

    def test_empirical_design_tail_and_coincidence(self):
        df=self.fixture()
        table=p4.design_conditions(df,p3.T,[.4,1.,2.,5.],upper=True,
                                   coincident=[p3.W,p4.H])
        self.assertEqual(len(table),4)
        fig=h.design_quantile_figure(table,quantity="Air temperature",unit="°C",upper=True)
        self.assertEqual(list(fig.data[0].x),[.4,1.,2.,5.])
        note=h.design_quantile_interpretation(table,quantity="Air temperature",unit="°C",upper=True)
        self.assertIn("1% upper hourly tail",note)
        self.assertIn("inclusive tail",note)
        self.assertTrue((table["Valid hours"]==96).all())
        self.assertTrue((table[p3.W+" · paired hours"]<=96).all())

    def test_critical_windows_explain_selected_observed_mean(self):
        df=self.fixture()
        from epw_climate_analyzer.p4_design_charts import critical_windows_figure
        fig,table,detail=critical_windows_figure(df,p3.T,"°C",hours=72,upper=True)
        self.assertIsNotNone(fig)
        self.assertEqual(len(table),1)
        note=h.critical_window_interpretation(table,quantity="Air temperature",unit="°C",
                                              upper=True,hours=72)
        self.assertIn("72-hour",note)
        self.assertIn("nonoverlapping",note)

    def test_integrates_all_hvac_sources_and_atlas(self):
        base=Path(__file__).resolve().parents[1]
        ui=(base/"app.py").read_text(encoding="utf-8")
        panel=(base/"epw_climate_analyzer"/"p3_ui.py").read_text(encoding="utf-8")
        p4ui=(base/"epw_climate_analyzer"/"p4_ui.py").read_text(encoding="utf-8")
        catalog=(base/"epw_climate_analyzer"/"p66_catalogue.py").read_text(encoding="utf-8")
        renderer=(base/"epw_climate_analyzer"/"p66_render.py").read_text(encoding="utf-8")
        for phrase in ("candidate_day_table","economizer_stages_figure"):
            self.assertIn(phrase,ui)
        for phrase in ("conditioning_interpretation","Monthly grouped energies","value=4.","value=9."):
            self.assertIn(phrase,panel)
        for phrase in ("design_quantile_figure","critical_window_interpretation"):
            self.assertIn(phrase,p4ui)
        self.assertIn('"economizer_stages"',catalog)
        for phrase in ('"economizer_stages"',"conditioning_interpretation","critical_window_interpretation"):
            self.assertIn(phrase,renderer)

    def test_atlas_renders_economizer_and_conditioning(self):
        from epw_climate_analyzer import p66_catalogue as catalog
        from epw_climate_analyzer.p66_render import make_figure
        df=self.fixture()
        available={x.kind:x for x in catalog.catalogue(df,{},catalog.FULL) if x.status=="available"}
        for key in ("economizer_stages","vent_load","critical_windows"):
            self.assertIn(key,available)
            fig,note=make_figure(available[key],df,{})
            self.assertTrue(fig.data)
            self.assertIn("hour" if key=="economizer_stages" else ("kwh" if key=="vent_load" else "hour"),note.lower())


if __name__=="__main__":
    unittest.main()
