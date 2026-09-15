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
app = replace_once(
    app,
    "    global aggregate_liquid_precipitation, occurrence_hours, precipitation_summary\n",
    "    global aggregate_liquid_precipitation, occurrence_hours\n",
    "precipitation globals",
)
app = replace_once(
    app,
    "        from epw_climate_analyzer.precipitation import (\n            aggregate_liquid_precipitation,\n            occurrence_hours,\n            precipitation_summary,\n        )\n",
    "        from epw_climate_analyzer.precipitation import (\n            aggregate_liquid_precipitation,\n            occurrence_hours,\n        )\n",
    "precipitation import",
)
old_block = '''    summary = precipitation_summary(df)\n    liquid_available = bool(summary["liquid_data_available"])\n    snow_available = bool(summary["snow_data_available"])\n\n    metric_cols = st.columns(5)\n    metric_cols[0].metric(\n        "Liquid precipitation",\n        "N/A" if summary["liquid_total_mm"] is None else f"{summary['liquid_total_mm']:.1f} mm",\n        help="Sum of valid EPW liquid-precipitation depth records in the current sidebar-filtered view.",\n    )\n    metric_cols[1].metric(\n        "Precipitation records ≥ 0.1 mm",\n        "N/A" if summary["precipitation_records"] is None else f"{summary['precipitation_records']:,}",\n    )\n    metric_cols[2].metric(\n        "Max precipitation record",\n        "N/A" if summary["max_record_precipitation_mm"] is None else f"{summary['max_record_precipitation_mm']:.1f} mm",\n    )\n    metric_cols[3].metric(\n        "Max snow depth",\n        "N/A" if summary["max_snow_depth_cm"] is None else f"{summary['max_snow_depth_cm']:.1f} cm",\n    )\n    metric_cols[4].metric(\n        "Snow-cover hours",\n        "N/A" if summary["snow_cover_hours"] is None else f"{summary['snow_cover_hours']:,}",\n    )\n\n    st.caption(\n        "Precipitation and snow availability depends on the source EPW. Missing EPW sentinel values are excluded. "\n        "Liquid precipitation is accumulated; snow depth is treated as a state variable and is never summed."\n    )\n'''
new_block = '''    liquid_available = (\n        "liquid_precipitation_depth_mm" in df.columns\n        and pd.to_numeric(df["liquid_precipitation_depth_mm"], errors="coerce").notna().any()\n    )\n    snow_available = (\n        "snow_depth_cm" in df.columns\n        and pd.to_numeric(df["snow_depth_cm"], errors="coerce").notna().any()\n    )\n'''
app = replace_once(app, old_block, new_block, "remove precipitation KPI strip")
APP.write_text(app, encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
test = replace_once(
    test,
    "    occurrence_hours,\n    precipitation_summary,\n",
    "    occurrence_hours,\n",
    "remove summary test import",
)
old_test = '''    def test_summary_keeps_liquid_accumulation_and_snow_state_semantics_separate(self) -> None:\n        summary = precipitation_summary(self._fixture())\n        self.assertTrue(summary["liquid_data_available"])\n        self.assertTrue(summary["snow_data_available"])\n        self.assertAlmostEqual(float(summary["liquid_total_mm"]), 7.0)\n        self.assertEqual(summary["precipitation_records"], 3)\n        self.assertAlmostEqual(float(summary["max_record_precipitation_mm"]), 4.0)\n        self.assertAlmostEqual(float(summary["max_snow_depth_cm"]), 3.0)\n        self.assertEqual(summary["snow_cover_hours"], 2)\n\n'''
new_test = '''    def test_precipitation_page_uses_chart_first_layout_without_kpi_strip(self) -> None:\n        function = next(\n            node for node in self.tree.body\n            if isinstance(node, ast.FunctionDef) and node.name == "render_precipitation"\n        )\n        source = ast.get_source_segment(self.source, function) or ""\n        self.assertNotIn(".metric(", source)\n        self.assertNotIn("metric_cols", source)\n        self.assertNotIn("Max precipitation record", source)\n        self.assertNotIn("Max snow depth", source)\n        self.assertIn('chart_group = st.selectbox("Analysis type", options)', source)\n\n'''
test = replace_once(test, old_test, new_test, "replace KPI summary test")
TEST.write_text(test, encoding="utf-8")

print("CLIMATE-0.10.8 precipitation UI consistency patch applied")
