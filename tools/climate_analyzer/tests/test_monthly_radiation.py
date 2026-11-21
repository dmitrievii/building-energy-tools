"""Unified monthly radiation: plane semantics, interval energy, and UI."""
from __future__ import annotations
import ast
from pathlib import Path
import unittest

import numpy as np
import pandas as pd
from epw_climate_analyzer.monthly_radiation import (
    available_source_quantities, surface_available, monthly_source_irradiation,
    monthly_surface_irradiation, monthly_radiation_chart, SURFACE_FIELDS,
    monthly_rose_years, monthly_rose_table, MONTH_NAMES,
)
from epw_climate_analyzer.solar import surface_irradiance_components
from epw_climate_analyzer.temporal_filtering import CALENDAR_PROFILE, with_time_basis

GHI = "global_horizontal_radiation_wh_m2"
DHI = "diffuse_horizontal_radiation_wh_m2"
DNI = "direct_normal_radiation_wh_m2"


def fixture():
    return pd.DataFrame({
        GHI:[400.,500.,600.,100.],
        DHI:[100.,200.,100.,50.],
        DNI:[600.,600.,800.,100.],
        "solar_apparent_zenith_deg":[60.,60.,45.,60.],
        "solar_azimuth_deg":[90.,180.,270.,180.],
        "month_index":[1,1,2,2],
    }, index=pd.to_datetime(["2025-01-01 12:00","2025-01-01 13:00","2025-02-01 12:00","2025-02-01 13:00"]))


class MonthlyRadiationTests(unittest.TestCase):
    def test_source_inputs_are_independent_and_missing_months_are_nan(self):
        df = fixture()
        df.loc[df.index[0],DNI] = np.nan
        t = monthly_source_irradiation(df, ["GHI","DHI","DNI"])
        np.testing.assert_allclose(t.iloc[0], [.9,.3,.6])
        self.assertTrue(t.iloc[2:].isna().all().all())
        self.assertEqual(list(t.columns), ["GHI","DHI","DNI"])
        for style in ("Bar chart","Line chart"):
            fig = monthly_radiation_chart(t,style=style)
            self.assertEqual(fig.layout.barmode,"group")
            self.assertEqual(len(fig.data),3)
            for trace, col in zip(fig.data,t):
                np.testing.assert_allclose(trace.y,t[col],equal_nan=True)

    def test_poa_interval_kernel_and_additive_closure(self):
        df = fixture()
        df.loc[df.index[0],DNI] = np.nan
        surfaces=[("North",0.),("South",180.),("Custom 62°",62.)]
        for tilt in (0.,45.,90.):
            for albedo in (.2,.5):
                t = monthly_surface_irradiation(df,surfaces,tilt,list(SURFACE_FIELDS),albedo=albedo)
                for name,azi in surfaces:
                    expected=surface_irradiance_components(df,tilt,azi,albedo=albedo)
                    for q,col in SURFACE_FIELDS.items():
                        np.testing.assert_allclose(t[(name,q)].iloc[:2],expected[col].groupby(df.index.month).sum(min_count=1)/1000.)
                    np.testing.assert_allclose(t[(name,"Total POA")],
                        t[name][["Direct","Sky diffuse","Ground-reflected"]].sum(axis=1,min_count=3),equal_nan=True)
                self.assertTrue(t.iloc[2:].isna().all().all())
                fig=monthly_radiation_chart(t,tilt_deg=tilt)
                self.assertEqual(len(fig.data),len(surfaces)*4)
                self.assertEqual(fig.layout.barmode,"group")
                if tilt == 0:
                    np.testing.assert_allclose(t[("North","Total POA")],t[("South","Total POA")],equal_nan=True)
                    self.assertEqual(t[("North","Ground-reflected")].iloc[0],0.)

    def test_missing_source_disables_surface(self):
        df=fixture().drop(columns=DNI)
        self.assertEqual(available_source_quantities(df),["GHI","DHI"])
        self.assertFalse(surface_available(df))
        self.assertRaises(ValueError,monthly_surface_irradiation,df,[("South",180.)],90.,["Total POA"])

    def test_no_invented_multiyear_accumulation(self):
        df=fixture()
        other=df.copy()
        other.index=other.index+pd.DateOffset(years=1)
        both=pd.concat([df,other])
        actual=monthly_source_irradiation(both,["GHI"])
        self.assertAlmostEqual(actual.loc["2025-01-01","GHI"],.9)
        self.assertAlmostEqual(actual.loc["2026-01-01","GHI"],.9)
        self.assertTrue(np.isnan(actual.loc["2025-03-01","GHI"]))
        fig=monthly_radiation_chart(actual)
        self.assertIn("Jan 2025",fig.data[0].x)
        self.assertIn("Jan 2026",fig.data[0].x)
        typical=monthly_source_irradiation(with_time_basis(both,CALENDAR_PROFILE),["GHI"])
        self.assertAlmostEqual(typical.loc[1,"GHI"],.9)

    def test_monthly_rose_disjoint_angular_groups_identical_values(self):
        df = fixture()
        for table in (monthly_source_irradiation(df, ["GHI","DHI","DNI"]),
                      monthly_surface_irradiation(df, [("North",0.),("South",180.)],
                                                  90., list(SURFACE_FIELDS), albedo=.2)):
            fig = monthly_radiation_chart(table, style="Monthly rose")
            self.assertEqual(fig.layout.polar.barmode, "overlay")
            self.assertEqual(fig.layout.meta["month_sectors"],12)
            self.assertEqual(tuple(fig.layout.polar.angularaxis.ticktext), MONTH_NAMES)
            self.assertEqual(tuple(fig.layout.polar.angularaxis.tickvals), tuple(range(0,360,30)))
            self.assertEqual(len(fig.data),len(table.columns))
            occupied = []
            for trace, col in zip(fig.data,table.columns):
                self.assertEqual(trace.type,"barpolar")
                self.assertEqual(trace.base,0)
                self.assertEqual(tuple(trace.customdata), MONTH_NAMES)
                self.assertEqual(len(trace.r),12)
                np.testing.assert_allclose(trace.r,table[col],equal_nan=True)
                offsets=(np.asarray(trace.theta)-np.arange(12)*30+180)%360-180
                self.assertTrue(np.all(np.abs(offsets)+trace.width/2 < 15))
                occupied.append((offsets[0]-trace.width/2, offsets[0]+trace.width/2))
            occupied.sort()
            self.assertTrue(all(a[1] < b[0] for a,b in zip(occupied,occupied[1:])))

    def test_monthly_rose_chronological_year_and_calendar_profile(self):
        df=fixture()
        other=df.copy()
        other.index=other.index+pd.DateOffset(years=1)
        other[GHI]*=2
        both=pd.concat([df,other])
        t=monthly_source_irradiation(both,["GHI"])
        self.assertEqual(monthly_rose_years(t),[2025,2026])
        with self.assertRaisesRegex(ValueError,"Select one calendar year"):
            monthly_radiation_chart(t,style="Monthly rose")
        rose=monthly_radiation_chart(t,style="Monthly rose",rose_year=2026)
        self.assertAlmostEqual(rose.data[0].r[0],1.8)
        self.assertTrue(np.isnan(rose.data[0].r[2]))
        self.assertIn("2026",rose.layout.title.text)
        typical=monthly_source_irradiation(with_time_basis(both,CALENDAR_PROFILE),["GHI"])
        self.assertAlmostEqual(monthly_radiation_chart(typical,style="Monthly rose").data[0].r[0],1.35)
        self.assertEqual(len(monthly_rose_table(t,year=2025)),12)

    def test_unified_actual_widgets(self):
        from streamlit.testing.v1 import AppTest
        source=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        get=lambda name: next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        solar=ast.get_source_segment(source,get("render_solar"))
        self.assertNotIn('"Monthly façade radiation"',solar)
        self.assertNotIn('"Monthly radiation components"',solar)
        self.assertIn("render_monthly_radiation(df, ground_albedo=ground_albedo)",solar)
        script="""
import streamlit as st
import pandas as pd
from epw_climate_analyzer.monthly_radiation import SOURCE_FIELDS
df=pd.DataFrame({SOURCE_FIELDS["GHI"]:[400.,500.],SOURCE_FIELDS["DHI"]:[100.,200.],
                 SOURCE_FIELDS["DNI"]:[600.,600.],"solar_apparent_zenith_deg":[60.,60.],
                 "solar_azimuth_deg":[90.,180.]},index=pd.date_range("2025-01-01",periods=2,freq="h"))
def render_plot(fig,text):
    st.plotly_chart(fig,key="monthly_test_plot")
"""
        app=AppTest.from_string(script+"\n"+ast.get_source_segment(source,get("render_monthly_radiation"))+
                                "\nrender_monthly_radiation(df)",default_timeout=45).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="monthly_radiation_basis").value,"Source radiation")
        self.assertEqual(app.multiselect(key="monthly_source_quantities").value,["GHI","DHI","DNI"])
        self.assertEqual(app.selectbox(key="monthly_radiation_style").options,["Bar chart","Line chart","Monthly rose"])
        app.selectbox(key="monthly_radiation_style").set_value("Monthly rose").run()
        self.assertFalse(app.exception)
        app.selectbox(key="monthly_radiation_basis").set_value("Surface irradiation (POA)").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.multiselect(key="monthly_poa_orientations").value,["North","East","South","West"])
        app.multiselect(key="monthly_poa_quantities").set_value(list(SURFACE_FIELDS)).run()
        self.assertFalse(app.exception)
        app.multiselect(key="monthly_poa_orientations").set_value(["Custom"]).run()
        self.assertFalse(app.exception)
        app.slider(key="monthly_poa_azimuth").set_value(62.).run()
        self.assertFalse(app.exception)
        app.slider(key="monthly_poa_tilt").set_value(0.).run()
        self.assertFalse(app.exception)
        self.assertNotIn("monthly_poa_orientations",[w.key for w in app.multiselect])


if __name__ == "__main__":
    unittest.main()
