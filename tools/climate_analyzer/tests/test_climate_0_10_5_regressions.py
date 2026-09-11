import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Climate0105RegressionTests(unittest.TestCase):
    def test_primary_psychrometric_chart_uses_container_width(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_humidity")
        calls = []
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "plotly_chart"):
                continue
            if not any(isinstance(kw.value, ast.Call) and isinstance(kw.value.func, ast.Name) and kw.value.func.id == "next_plot_key" and kw.value.args and isinstance(kw.value.args[0], ast.Constant) and kw.value.args[0].value == "psychrometric" for kw in node.keywords if kw.arg == "key"):
                continue
            calls.append(node)
        self.assertEqual(len(calls), 1)
        width_kw = next((kw for kw in calls[0].keywords if kw.arg == "use_container_width"), None)
        self.assertIsNotNone(width_kw)
        self.assertIsInstance(width_kw.value, ast.Constant)
        self.assertIs(width_kw.value.value, True)

    def test_no_fixed_width_primary_psychrometric_render_remains(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('next_plot_key("psychrometric"))\n        if False', source)
        self.assertNotIn('use_container_width=False, config={"displaylogo": False, "scrollZoom": True}, key=next_plot_key("psychrometric")', source)


if __name__ == "__main__":
    unittest.main()
