"""R2: scientific definition and exact profile-interpretation parity in all outputs."""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from epw_climate_analyzer import p66_catalogue as cat
from epw_climate_analyzer import p6_report_structure as report
from epw_climate_analyzer.p66_render import make_figure
from epw_climate_analyzer.charts import time_series_profile_chart
from epw_climate_analyzer.profile_interpretation import profile_interpretation
from epw_climate_analyzer.period_display import canonical_profile_kind
from epw_climate_analyzer.humidity_findings import humidity_figure_interpretation, DP


def climate():
    index=pd.date_range("2026-01-20 00:00",periods=24*14,freq="h")
    i=np.arange(len(index))
    values=np.where(index.day==21,-12.4,20.6)+.3*np.sin(i/4.)
    out=pd.DataFrame({
        DP:values,
        "relative_humidity_pct":50.+30.*np.sin(i/72.),
        "dry_bulb_temperature_c":values+4.,
        "humidity_ratio_g_kg":np.maximum(.1,5.+3.*np.cos(i/5.)),
        "wind_speed_m_s":2.+np.cos(i/10.),
        "global_horizontal_radiation_wh_m2":np.maximum(0.,300.*np.sin(i/24.)),
        "total_sky_cover_tenths":5.+np.sin(i/12.),
        "liquid_precipitation_depth_mm":np.where(i%48==0,1.,0.),
        "hour_of_day":index.hour,
        "month_index":index.month,
    },index=index)
    out.attrs["canonical_native_interval_minutes"]=60.
    return out


class ProfileInterpretationParityTests(unittest.TestCase):
    def test_canonical_representation_across_all_routes(self):
        name="Dew-point temperature · Daily · P05–median–P95"
        self.assertEqual(canonical_profile_kind("Time series / Profile",name),"percentile")
        self.assertEqual(canonical_profile_kind("time_series",name,("Daily","P05–median–P95")),"percentile")
        self.assertEqual(canonical_profile_kind("percentile",name),"percentile")
        self.assertEqual(canonical_profile_kind("Time series / Profile","Hourly · Observed values"),"time_series")
        self.assertEqual(canonical_profile_kind("time_series","Daily · Mean",("Daily","Mean")),"profile")

    def test_hourly_dew_point_is_qualified_with_actual_timestamps(self):
        df=climate()
        fig=time_series_profile_chart(df,DP,"Hourly",
                     "Humidity: Dew-point temperature · Hourly · Observed values",
                     "°C","Observed values")
        note=profile_interpretation(df,fig,"Time series / Profile",
                                    domain="Humidity",column=DP)
        self.assertIn("valid hourly observations",note)
        self.assertRegex(note,r"on \\d{2}\\.\\d{2} at \\d{2}:\\d{2}")
        self.assertIn("P05",note)
        self.assertIn("median",note)
        self.assertIn("P95",note)
        self.assertIn("reaches saturation",note)
        self.assertIn("condense",note)
        self.assertNotIn("15 °C",note)
        self.assertNotIn("moisture accumulation",note)

    def test_atlas_hourly_note_matches_live_exactly(self):
        df=climate()
        figures=cat.catalogue(df,{},cat.FULL)
        selected=next(d for d in figures if d.kind=="time_series" and
                     d.column==DP and d.args==("Hourly","Observed values"))
        fig,actual=make_figure(selected,df,{})
        expected=profile_interpretation(
            df,fig,"Time series / Profile",domain="Humidity",column=DP,
            title=selected.title,args=selected.args)
        self.assertEqual(actual,expected)
        self.assertIn("Lowest:",actual)
        self.assertNotIn("15 °C surface",actual)

    def test_atlas_percentile_has_one_distribution_explanation(self):
        df=climate()
        selected=next(d for d in cat.catalogue(df,{},cat.FULL)
                      if d.kind=="percentile" and d.column==DP and d.args==("Daily",))
        fig,note=make_figure(selected,df,{})
        expected=profile_interpretation(
            df,fig,"Time series / Profile",domain="Humidity",column=DP,
            title=selected.title,args=selected.args)
        self.assertEqual(note,expected)
        self.assertEqual(note.count("central 90%"),1)
        self.assertIn("21.01",note)
        self.assertNotIn("15 °C",note)
        self.assertNotIn("surface moisture accumulation",note)

    def test_standard_monthly_report_matches_adapter_exactly(self):
        df=climate()
        entry=next(e for e in report.CATALOG if e[0]=="humidity_profile")
        fig,note=report.standard_figure(entry,df,{})
        expected=profile_interpretation(
            df,fig,"profile",domain="Humidity and Psychrometrics",
            column="relative_humidity_pct",title=entry[2])
        self.assertEqual(note,expected)
        self.assertNotIn("Monthly values summarize",note)

    def test_captured_report_is_same_interpretation_as_live(self):
        from epw_climate_analyzer.p6_report import snapshot,printable_html
        df=climate()
        fig=time_series_profile_chart(df,DP,"Hourly",
                     "Humidity: Dew-point temperature · Hourly · Observed values",
                     "°C","Observed values")
        live=profile_interpretation(
            df,fig,"Time series / Profile",domain="Humidity",column=DP)
        item=snapshot(fig,{"page":"Humidity and Psychrometrics",
                           "source":"synthetic-2026","selected records":len(df)},live)
        self.assertEqual(item["interpretation"],live)
        html=printable_html([item],"Climate","A4","Landscape",use_osm=False).decode("utf-8")
        self.assertIn(live.split(".")[0],html)
        self.assertNotIn("surface moisture accumulation",html)

    def test_all_six_profile_families_use_one_adapter(self):
        df=climate()
        cases=[("Temperature","dry_bulb_temperature_c"),
               ("Humidity and Psychrometrics",DP),
               ("Wind and Ventilation","wind_speed_m_s"),
               ("Solar and Radiation","global_horizontal_radiation_wh_m2"),
               ("Sky and Daylight","total_sky_cover_tenths"),
               ("Precipitation and Snow","liquid_precipitation_depth_mm")]
        for domain,column in cases:
            with self.subTest(domain=domain):
                fig=time_series_profile_chart(df,column,"Hourly",
                       f"Selected · Hourly · Observed values","°C","Observed values")
                result=profile_interpretation(
                    df,fig,"Time series / Profile",domain=domain,column=column)
                self.assertTrue(result)
                self.assertIsInstance(result,str)

    def test_site_and_atlas_point_to_same_contract(self):
        base=Path(__file__).resolve().parents[1]
        app=(base/"app.py").read_text(encoding="utf-8")
        atlas=(base/"epw_climate_analyzer"/"p66_render.py").read_text(encoding="utf-8")
        standard=(base/"epw_climate_analyzer"/"p6_report_structure.py").read_text(encoding="utf-8")
        self.assertIn("from epw_climate_analyzer.profile_interpretation import profile_interpretation",app)
        self.assertIn("from .profile_interpretation import profile_interpretation",atlas)
        self.assertIn("from .profile_interpretation import profile_interpretation",standard)


if __name__=="__main__":
    unittest.main()
