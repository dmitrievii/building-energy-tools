"""Preserve the historical period×hour orientation of legacy heatmap matrix wrappers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "epw_climate_analyzer" / "aggregations.py"
text = path.read_text(encoding="utf-8")

old_calendar = '''    return temporal_heatmap_matrix(\n        df,\n        column,\n        row_group=row_group,\n        compare_across=HEATMAP_COMPARE_HOUR,\n        statistic="Mean",\n    )\n\n\ndef monthly_hour_matrix'''
new_calendar = '''    return temporal_heatmap_matrix(\n        df,\n        column,\n        row_group=row_group,\n        compare_across=HEATMAP_COMPARE_HOUR,\n        statistic="Mean",\n    ).T\n\n\ndef monthly_hour_matrix'''
if old_calendar not in text and new_calendar not in text:
    raise RuntimeError("calendar_matrix orientation anchor not found")
text = text.replace(old_calendar, new_calendar, 1)

old_month = '''    return temporal_heatmap_matrix(\n        df,\n        column,\n        row_group="month",\n        compare_across=HEATMAP_COMPARE_HOUR,\n        statistic=statistic,\n    )\n\n\ndef duration_curve'''
new_month = '''    return temporal_heatmap_matrix(\n        df,\n        column,\n        row_group="month",\n        compare_across=HEATMAP_COMPARE_HOUR,\n        statistic=statistic,\n    ).T\n\n\ndef duration_curve'''
if old_month not in text and new_month not in text:
    raise RuntimeError("monthly_hour_matrix orientation anchor not found")
text = text.replace(old_month, new_month, 1)

path.write_text(text, encoding="utf-8")
