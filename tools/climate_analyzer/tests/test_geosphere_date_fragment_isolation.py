from __future__ import annotations

import ast
from pathlib import Path
import unittest


class GeoSphereDateFragmentIsolationTests(unittest.TestCase):
    def _source(self) -> str:
        return (
            Path(__file__).resolve().parents[1]
            / "epw_climate_analyzer"
            / "geosphere_request_form.py"
        ).read_text(encoding="utf-8")

    def test_only_request_dates_are_fragment_entrypoints(self) -> None:
        source = self._source()
        tree = ast.parse(source)
        fragmented_functions: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "fragment_factory":
                    fragmented_functions.append(node.name)

        self.assertEqual(
            sorted(fragmented_functions),
            ["render_end_date", "render_start_date"],
        )
        self.assertIn("_START_KEY: render_start_date", source)
        self.assertIn("_END_KEY: render_end_date", source)
        self.assertNotIn("fragment_factory(selector)", source)
        self.assertNotIn("fragment_factory(data_editor)", source)
        self.assertNotIn("fragment_factory(form_submit_button)", source)

    def test_station_selector_and_load_transport_remain_outside_fragment(self) -> None:
        source = self._source()
        self.assertIn("return previous(legacy, original)", source)
        self.assertIn("st.form_submit_button = form_submit_button", source)
        self.assertIn("DeltaGenerator.date_input = date_input", source)
        self.assertNotIn("fetch_station_dataset", source)
        self.assertNotIn("fetch_geosphere_station_dataset", source)

    def test_fragment_fallback_preserves_non_streamlit_test_doubles(self) -> None:
        source = self._source()
        self.assertIn('fragment_factory = getattr(st, "fragment", None)', source)
        self.assertIn("if callable(fragment_factory):", source)
        self.assertIn("render_start_date = _render_date_widget", source)
        self.assertIn("render_end_date = _render_date_widget", source)


if __name__ == "__main__":
    unittest.main()
