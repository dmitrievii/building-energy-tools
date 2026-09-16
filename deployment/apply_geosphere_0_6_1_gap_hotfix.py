from __future__ import annotations

from pathlib import Path

path = Path(__file__).resolve().parents[1] / "tools/climate_analyzer/epw_climate_analyzer/historical_capabilities.py"
text = path.read_text(encoding="utf-8")
old = '''    gap_count = 0
    longest_missing = 0.0
    if observed_records:
        points = pd.DatetimeIndex([start, *observed_in_range.tolist(), end]).drop_duplicates().sort_values()
        if len(points) > 1:
            for delta in points[1:] - points[:-1]:
                steps = float(delta / step)
                missing_between = max(0.0, steps - 1.0)
                if missing_between > 1e-9:
                    gap_count += 1
                    longest_missing = max(longest_missing, missing_between * interval_minutes)
    elif expected_records:
        gap_count = 1
        longest_missing = expected_records * interval_minutes
'''
new = '''    gap_count = 0
    longest_missing = 0.0
    if observed_records:
        first_obs = pd.Timestamp(observed_in_range[0])
        last_obs = pd.Timestamp(observed_in_range[-1])

        leading_missing = max(0, int((first_obs - start) // step))
        if leading_missing:
            gap_count += 1
            longest_missing = max(longest_missing, leading_missing * interval_minutes)

        if observed_records > 1:
            for delta in observed_in_range[1:] - observed_in_range[:-1]:
                missing_between = max(0, int(round(float(delta / step))) - 1)
                if missing_between:
                    gap_count += 1
                    longest_missing = max(longest_missing, missing_between * interval_minutes)

        trailing_missing = max(0, int((end - last_obs) // step))
        if trailing_missing:
            gap_count += 1
            longest_missing = max(longest_missing, trailing_missing * interval_minutes)
    elif expected_records:
        gap_count = 1
        longest_missing = expected_records * interval_minutes
'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"Expected one generated gap block, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("CLIMATE_GEOSPHERE_0_6_1_EDGE_GAP_HOTFIX_APPLIED")
