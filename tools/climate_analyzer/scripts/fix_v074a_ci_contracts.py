from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Patch anchor missing in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


app = ROOT / "app.py"
replace_once(
    app,
    'if chart_type in {"Profile with min-mean-max ribbon", "Percentile band P05-P50-P95"}:',
    'if chart_type in {"Profile with min-mean-max ribbon", "Middle 90% range with median"}:',
)

ui_test = ROOT / "tests" / "test_interannual_heatmaps_0_6_4.py"
replace_once(
    ui_test,
    '''        self.assertIn('st.selectbox("Compare across", ["Hour of day", "Year"]', self.source)\n''',
    '''        self.assertIn('compare_options = ["Hour of day"] if time_basis(df) == CHRONOLOGICAL else ["Hour of day", "Year"]', self.source)\n        self.assertIn('st.selectbox("Compare across", compare_options', self.source)\n        self.assertIn("Chronological heat maps keep every real day, week or month in sequence across years", self.source)\n''',
)

temporal_test = ROOT / "tests" / "test_temporal_filtering_0_6_3.py"
replace_once(
    temporal_test,
    '''    def test_chronological_multiyear_hour_heatmap_aligns_calendar_months(self) -> None:\n        idx = pd.to_datetime(["2023-01-01 00:00", "2024-01-01 00:00"])\n        df = with_time_basis(frame(idx, [1.0, 2.0]), CHRONOLOGICAL)\n        matrix = calendar_matrix(df, "dry_bulb_temperature_c", row_group="month")\n        self.assertEqual(list(matrix.index), list(range(1, 13)))\n        self.assertAlmostEqual(float(matrix.loc[1, 0]), 1.5)\n''',
    '''    def test_chronological_multiyear_hour_heatmap_preserves_real_year_months(self) -> None:\n        idx = pd.to_datetime(["2023-01-01 00:00", "2024-01-01 00:00"])\n        df = with_time_basis(frame(idx, [1.0, 2.0]), CHRONOLOGICAL)\n        matrix = calendar_matrix(df, "dry_bulb_temperature_c", row_group="month")\n        self.assertEqual(list(matrix.index), ["2023-01", "2024-01"])\n        self.assertAlmostEqual(float(matrix.loc["2023-01", 0]), 1.0)\n        self.assertAlmostEqual(float(matrix.loc["2024-01", 0]), 2.0)\n''',
)

print("v0.7.4-A CI contract cleanup applied")
