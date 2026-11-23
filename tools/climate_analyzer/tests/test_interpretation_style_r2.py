"""R2 editorial regression: affirmative science commentary and psychrometric control layout."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/"epw_climate_analyzer"


class InterpretationEditorialTests(unittest.TestCase):
    def test_automatic_interpretation_modules_avoid_old_boilerplate(self):
        modules=(
            "temperature_findings.py",
            "humidity_findings.py",
            "wind_findings.py",
            "solar_findings.py",
            "interpretations.py",
            "p66_render.py",
            "p6_report_structure.py",
        )
        banned=(
            "illustrative",
            "these are not building heating or cooling loads",
            "this is a user-selected weather screen, not",
            "not an indoor humidity target",
            "not a building energy demand",
            "not a predicted ventilation flow rate",
        )
        for file in modules:
            text=(ENGINE/file).read_text(encoding="utf-8").lower()
            for old in banned:
                with self.subTest(file=file,phrase=old):
                    self.assertNotIn(old,text)

    def test_psychrometric_metrics_and_mapping_collapsed(self):
        source=(ROOT/"app.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                and n.name=="render_humidity")
        expanders={}
        for n in ast.walk(fn):
            if not isinstance(n,ast.With) or not n.items:
                continue
            call=n.items[0].context_expr
            if (not isinstance(call,ast.Call)
                or not isinstance(call.func,ast.Attribute)
                or call.func.attr!="expander"
                or not call.args
                or not isinstance(call.args[0],ast.Constant)):
                continue
            name=call.args[0].value
            expanders[name]=(n,call)
        self.assertIn("Chart metrics",expanders)
        self.assertIn("Data mapping",expanders)
        self.assertNotIn("Chart metrics and overlays",expanders)
        self.assertNotIn("Loaded data mapping",expanders)
        for name in ("Chart metrics","Data mapping"):
            _,call=expanders[name]
            kw={k.arg:k.value for k in call.keywords}
            self.assertIn("expanded",kw)
            self.assertIsInstance(kw["expanded"],ast.Constant)
            self.assertIs(kw["expanded"].value,False)
        metrics,_=expanders["Chart metrics"]
        strings={x.value for x in ast.walk(metrics)
                 if isinstance(x,ast.Constant) and isinstance(x.value,str)}
        for heading in (
            "Dry-bulb temperature range [°C]",
            "Moisture content range [g/kg]",
            "Enthalpy range [kJ/kg dry air]",
            "Metric lines",
            "Show Givoni-Milne bioclimatic overlay",
            "Show heat-index overlay",
        ):
            self.assertIn(heading,strings)

    def test_temperature_and_humidity_examples_are_affirmative(self):
        import pandas as pd
        import plotly.graph_objects as go
        from epw_climate_analyzer.temperature_findings import temperature_figure_interpretation
        from epw_climate_analyzer.humidity_findings import humidity_figure_interpretation
        index=pd.date_range("2026-06-01",periods=4,freq="h")
        frame=pd.DataFrame({
            "dry_bulb_temperature_c":[16.,21.,28.,30.],
            "relative_humidity_pct":[60.,80.,85.,90.],
            "humidity_ratio_g_kg":[7.,8.,9.,10.],
        },index=index)
        fig=go.Figure()
        fig.add_scatter(x=["Jun","Jul"],y=[17.,28.],name="Mean")
        t=temperature_figure_interpretation(frame,fig,"profile")
        h=humidity_figure_interpretation(frame,fig,"threshold",
                column="humidity_ratio_g_kg",args=(9.,">"))
        self.assertIn("seasonal envelope and passive-control priorities",t)
        self.assertIn("frequency of the selected atmospheric moisture condition",h)
        self.assertNotIn("not building heating",t.lower())
        self.assertNotIn("not an indoor humidity target",h.lower())


if __name__=="__main__":
    unittest.main()
