from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "tools" / "climate_analyzer" / "app.py"
TEST = ROOT / "tools" / "climate_analyzer" / "tests" / "test_pressure_precipitation_contract.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


app = APP.read_text(encoding="utf-8")
old_chart_selector = '''    chart_type = st.selectbox(\n        "Chart type",\n        [\n            "Profile with min-mean-max ribbon",\n            "Percentile band P05-P50-P95",\n            "Heat map",\n            "Duration curve",\n            "Histogram",\n            "Monthly boxplot",\n            "Monthly violin plot",\n        ],\n    )\n'''
new_chart_selector = '''    chart_types = [\n        "Profile with min-mean-max ribbon",\n        "Percentile band P05-P50-P95",\n        "Heat map",\n        "Duration curve",\n        "Histogram",\n        "Monthly boxplot",\n        "Monthly violin plot",\n    ]\n    if column == "liquid_precipitation_depth_mm":\n        # Accumulated precipitation belongs to the dedicated totals analysis.\n        # A min/mean/max ribbon cannot use a period sum as its centre line while\n        # its bounds remain per-record extrema, so that chart is deliberately\n        # unavailable for this extensive variable.\n        chart_types.remove("Profile with min-mean-max ribbon")\n    chart_type = st.selectbox("Chart type", chart_types)\n'''
app = replace_once(app, old_chart_selector, new_chart_selector, "chart selector")
app = replace_once(
    app,
    '''        # Radiation and illuminance are visualized as mean intensities in the generic explorer.\n        # Monthly/annual energy sums are available in the dedicated solar component charts.\n        extensive = column == "liquid_precipitation_depth_mm"\n        if chart_type == "Profile with min-mean-max ribbon":\n            fig = profile_ribbon_chart(df, column, aggregation or "Monthly", f"{title_prefix}: {variable_label}", unit, extensive=extensive)\n''',
    '''        # Radiation and illuminance are visualized as mean intensities in the generic explorer.\n        # Monthly/annual energy sums are available in the dedicated solar component charts.\n        if chart_type == "Profile with min-mean-max ribbon":\n            fig = profile_ribbon_chart(df, column, aggregation or "Monthly", f"{title_prefix}: {variable_label}", unit)\n''',
    "remove mixed extensive ribbon semantics",
)
APP.write_text(app, encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
test = replace_once(
    test,
    '''    def test_liquid_precipitation_is_explicitly_extensive_but_snow_is_not(self) -> None:\n        self.assertIn('extensive = column == "liquid_precipitation_depth_mm"', self.source)\n        self.assertNotIn('extensive = column.endswith("_mm")', self.source)\n        self.assertIn('["Snow depth"]', self.source)\n\n''',
    '''    def test_liquid_precipitation_accumulation_stays_in_dedicated_totals_route(self) -> None:\n        function = next(\n            node for node in self.tree.body\n            if isinstance(node, ast.FunctionDef) and node.name == "render_precipitation"\n        )\n        source = ast.get_source_segment(self.source, function) or ""\n        self.assertIn("aggregate_liquid_precipitation(df, aggregation)", source)\n        self.assertIn('"Precipitation totals"', source)\n        self.assertIn('["Snow depth"]', source)\n        self.assertNotIn('column.endswith("_mm")', self.source)\n\n''',
    "replace obsolete extensive UI contract",
)
needle = '''    def test_precipitation_page_uses_chart_first_layout_without_kpi_strip(self) -> None:\n'''
if needle not in test:
    raise RuntimeError("expected precipitation UI test anchor")
insert = '''    def test_liquid_precipitation_explorer_never_mixes_period_sum_with_record_min_max(self) -> None:\n        function = next(\n            node for node in self.tree.body\n            if isinstance(node, ast.FunctionDef) and node.name == "render_generic_variable_page"\n        )\n        source = ast.get_source_segment(self.source, function) or ""\n        self.assertIn('if column == "liquid_precipitation_depth_mm":', source)\n        self.assertIn('chart_types.remove("Profile with min-mean-max ribbon")', source)\n        self.assertNotIn('extensive = column == "liquid_precipitation_depth_mm"', source)\n        self.assertNotIn('extensive=extensive', source)\n\n'''
test = test.replace(needle, insert + needle, 1)
TEST.write_text(test, encoding="utf-8")

print("CLIMATE-0.10.9 precipitation chart semantics patch applied")
