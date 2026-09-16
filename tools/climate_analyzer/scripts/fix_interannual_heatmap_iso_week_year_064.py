"""Align Week×Year heatmaps to ISO week-year and add a boundary regression."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
agg = ROOT / "epw_climate_analyzer" / "aggregations.py"
text = agg.read_text(encoding="utf-8")
old = '''    if compare_across == HEATMAP_COMPARE_YEAR:\n        temp["_y"] = index.year.astype(int)\n        temp["_x"] = _heatmap_period_key(index, row_group, include_year=False).to_numpy()\n'''
previous = '''    if compare_across == HEATMAP_COMPARE_YEAR:\n        # Week numbers follow ISO-8601, so their year dimension must use the\n        # corresponding ISO week-year as well. Day/month comparisons retain\n        # ordinary calendar years.\n        temp["_y"] = (\n            index.isocalendar().year.astype(int).to_numpy()\n            if str(row_group).strip().lower() == "week"\n            else index.year.astype(int)\n        )\n        temp["_x"] = _heatmap_period_key(index, row_group, include_year=False).to_numpy()\n'''
new = '''    if compare_across == HEATMAP_COMPARE_YEAR:\n        # A week number and its year are one ISO-8601 coordinate. Build both\n        # from the same timestamp tuple so New-Year boundary dates cannot be\n        # assigned to calendar year Y while carrying ISO week Y-1/W53.\n        if str(row_group).strip().lower() == "week":\n            iso_coordinates = [stamp.isocalendar() for stamp in index.to_pydatetime()]\n            temp["_y"] = [int(item.year) for item in iso_coordinates]\n            temp["_x"] = [f"W{int(item.week):02d}" for item in iso_coordinates]\n        else:\n            temp["_y"] = index.year.astype(int)\n            temp["_x"] = _heatmap_period_key(index, row_group, include_year=False).to_numpy()\n'''
if old in text:
    text = text.replace(old, new, 1)
elif previous in text:
    text = text.replace(previous, new, 1)
elif new not in text:
    raise RuntimeError("Week×Year implementation anchor not found")
agg.write_text(text, encoding="utf-8")

test = ROOT / "tests" / "test_interannual_heatmaps_0_6_4.py"
t = test.read_text(encoding="utf-8")
anchor = '''    def test_one_year_year_compare_is_a_single_stripe(self) -> None:\n'''
method = '''    def test_week_by_year_uses_iso_week_year_at_calendar_boundary(self) -> None:\n        idx = pd.to_datetime([\n            "2020-12-31T12:00:00Z",  # ISO 2020-W53\n            "2021-01-01T12:00:00Z",  # still ISO 2020-W53\n            "2021-01-04T12:00:00Z",  # ISO 2021-W01\n        ])\n        df = pd.DataFrame({"dry_bulb_temperature_c": [1.0, 3.0, 10.0]}, index=idx)\n        df["hour_of_day"] = df.index.hour\n        df = with_time_basis(df, CHRONOLOGICAL)\n        matrix = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "week", HEATMAP_COMPARE_YEAR, "Mean")\n        self.assertEqual(matrix.index.tolist(), [2020, 2021])\n        self.assertAlmostEqual(float(matrix.loc[2020, "W53"]), 2.0)\n        self.assertAlmostEqual(float(matrix.loc[2021, "W01"]), 10.0)\n        self.assertTrue(pd.isna(matrix.loc[2021, "W53"]))\n\n'''
if method not in t:
    if anchor not in t:
        raise RuntimeError("Focused test insertion anchor not found")
    t = t.replace(anchor, method + anchor, 1)
else:
    # Upgrade the already-inserted regression with the explicit no-cross-year assertion.
    old_method = method.replace('        self.assertTrue(pd.isna(matrix.loc[2021, "W53"]))\n', '')
    if old_method in t:
        t = t.replace(old_method, method, 1)
test.write_text(t, encoding="utf-8")
