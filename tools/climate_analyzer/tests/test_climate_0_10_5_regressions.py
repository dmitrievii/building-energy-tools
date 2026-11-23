import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Climate0105RegressionTests(unittest.TestCase):
    def test_primary_psychrometric_chart_uses_container_width(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_humidity")
        def named_call(node, name):
            return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
        # The primary psychrometric chart now uses the common render_plot path
        # (which owns Report capture and container-width layout).
        builds=[n for n in ast.walk(fn) if named_call(n,"psychrometric_chart")]
        self.assertEqual(len(builds),1)
        calls=[n for n in ast.walk(fn) if named_call(n,"render_plot") and n.args and
               isinstance(n.args[0],ast.Name) and n.args[0].id=="fig" and
               len(n.args)>1 and named_call(n.args[1],"humidity_figure_interpretation")]
        self.assertTrue(any(isinstance(n.args[1].args[0],ast.Name) and
                            n.args[1].args[0].id=="report_df" for n in calls))
        renderer=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="render_plot")
        plots=[n for n in ast.walk(renderer) if isinstance(n,ast.Call) and
               isinstance(n.func,ast.Attribute) and n.func.attr=="plotly_chart"]
        self.assertEqual(len(plots),1)
        width=next((kw.value for kw in plots[0].keywords if kw.arg=="use_container_width"),None)
        self.assertIsInstance(width,ast.Constant)
        self.assertIs(width.value,True)

    def test_no_fixed_width_primary_psychrometric_render_remains(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('next_plot_key("psychrometric"))\n        if False', source)
        self.assertNotIn('use_container_width=False, config={"displaylogo": False, "scrollZoom": True}, key=next_plot_key("psychrometric")', source)


if __name__ == "__main__":
    unittest.main()
