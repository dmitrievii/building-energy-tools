"""Website/report/atlas parity when the same weather quantity appears in different chapters."""
import unittest

import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.profile_interpretation import profile_interpretation
from epw_climate_analyzer.p6_report import snapshot, printable_html


class DewPointCrossSurfaceTests(unittest.TestCase):
    def setUp(self):
        dates=pd.DatetimeIndex(["2026-03-07 12:00","2026-07-25 12:00"])
        self.df=pd.DataFrame({
            "dew_point_temperature_c":[-9.7,19.3],
            "wet_bulb_temperature_c":[-5.2,21.0],
            "dry_bulb_temperature_c":[-3.0,25.0],
        },index=dates)
        self.df.attrs["canonical_native_interval_minutes"]=60.
        self.fig=go.Figure()
        x=[66,206]
        self.fig.add_scatter(x=x,y=[-12.,18.],name="Minimum")
        self.fig.add_scatter(x=x,y=[-7.2,21.],name="Maximum")
        self.fig.add_scatter(x=x,y=[-9.7,19.3],name="Mean")
        self.fig.update_layout(title="Temperature: Dew-point temperature · Daily · Min–mean–max")

    def test_dew_point_web_temperature_chapter_matches_humidity_report_word_for_word(self):
        web=profile_interpretation(
            self.df,self.fig,"Time series / Profile",domain="Temperature",
            column="dew_point_temperature_c")
        report=profile_interpretation(
            self.df,self.fig,"profile",domain="Humidity and Psychrometrics",
            column="dew_point_temperature_c",
            title="Dew-point temperature · min–mean–max · Daily")
        atlas=profile_interpretation(
            self.df,self.fig,"profile",domain="Temperature",
            column="dew_point_temperature_c",
            title="Dew-point temperature · min–mean–max · Daily")
        self.assertEqual(web,report)
        self.assertEqual(web,atlas)
        self.assertIn("07.03 (-9.7 °C)",web)
        self.assertIn("25.07 (19.3 °C)",web)
        self.assertIn("dew-point temperature profile",web)
        self.assertIn("Min–max shows observed period extrema.",web)
        self.assertIn("Water vapour can condense",web)
        self.assertNotIn("Use this temperature series",web)
        self.assertNotIn("15 °C",web)
        item=snapshot(self.fig,{"page":"Temperature","source":"test"},web)
        self.assertEqual(item["interpretation"],report)
        html=printable_html([item],"Test","A4","Landscape",use_osm=False).decode("utf-8")
        self.assertIn(web,html)

    def test_wet_bulb_temperature_uses_same_science_in_both_pages(self):
        fig=go.Figure(go.Scatter(x=[66,206],y=[-5.2,21.],name="Mean"))
        fig.update_layout(title="Wet-bulb temperature · Daily · Mean")
        a=profile_interpretation(self.df,fig,"profile",
            domain="Temperature",column="wet_bulb_temperature_c")
        b=profile_interpretation(self.df,fig,"profile",
            domain="Humidity and Psychrometrics",column="wet_bulb_temperature_c")
        self.assertEqual(a,b)
        self.assertIn("wet-bulb temperature",a.lower())

    def test_dry_bulb_still_uses_temperature_science(self):
        fig=go.Figure(go.Scatter(x=[66,206],y=[-3.,25.],name="Mean"))
        fig.update_layout(title="Dry-bulb temperature · Daily · Mean")
        result=profile_interpretation(self.df,fig,"profile",
            domain="Temperature",column="dry_bulb_temperature_c")
        self.assertIn("outdoor",result.lower())
        self.assertNotIn("Dew point is",result)

    def test_live_generic_non_profile_dispatch_is_quantity_first(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        source=(root/"app.py").read_text(encoding="utf-8")
        start=source.index('    if chart_type=="Time series / Profile":\n        from epw_climate_analyzer.profile_interpretation import profile_interpretation',source.index("def render_generic_variable_page("))
        branch=source[start:source.index("    render_plot(fig, text)",start)]
        self.assertLess(branch.index('if column in {'),branch.index('elif title_prefix == "Temperature"'))
        self.assertIn('"dew_point_temperature_c"',branch)
        self.assertIn('"wet_bulb_temperature_c"',branch)


if __name__=="__main__":
    unittest.main()
