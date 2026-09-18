from pathlib import Path

patch = Path(__file__).with_name("apply_v074a_temporal_patch.py")
source = patch.read_text(encoding="utf-8")
old = """replace_once(\n    app,\n    '''            CALENDAR_PROFILE,\\n            CHRONOLOGICAL,\\n            display_period_labels,\\n            time_basis,\\n''',\n    '''            CALENDAR_PROFILE,\\n            CHRONOLOGICAL,\\n            display_period_labels,\\n            is_multiyear,\\n            time_basis,\\n''',\n)"""
new = """replace_once(\n    app,\n    '''            available_years,\\n            display_period_labels,\\n            filter_datetime_range,\\n''',\n    '''            available_years,\\n            display_period_labels,\\n            is_multiyear,\\n            filter_datetime_range,\\n''',\n)"""
if old not in source:
    raise RuntimeError("v0.7.4-A import-anchor correction target is missing")
source = source.replace(old, new, 1)
exec(compile(source, str(patch), "exec"), {"__name__": "__main__", "__file__": str(patch)})
