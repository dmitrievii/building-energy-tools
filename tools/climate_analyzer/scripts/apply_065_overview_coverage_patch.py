from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"
text = APP.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    'def render_historical_overview(dataset, df: pd.DataFrame) -> None:\n'
    '    """Render a provider-neutral overview of one measured historical dataset."""',
    'def render_historical_overview(\n'
    '    dataset,\n'
    '    df: pd.DataFrame,\n'
    '    coverage_df: pd.DataFrame | None = None,\n'
    ') -> None:\n'
    '    """Render hourly climate metrics with unfiltered hourly coverage context."""',
    "overview signature",
)
replace_once(
    '    coverage = historical_coverage_summary(df)\n'
    '    m1, m2, m3, m4 = st.columns(4)',
    '    quality_frame = coverage_df if coverage_df is not None else df\n'
    '    coverage = historical_coverage_summary(quality_frame)\n'
    '    st.caption(\n'
    '        "Coverage indicators describe the complete loaded canonical hourly frame; climate metrics and charts below "\n'
    '        "respect the active global Data filter."\n'
    '    )\n'
    '    m1, m2, m3, m4 = st.columns(4)',
    "overview coverage frame",
)
replace_once(
    '    variable_coverage = historical_variable_coverage(df, requested_columns)',
    '    variable_coverage = historical_variable_coverage(quality_frame, requested_columns)',
    "overview variable coverage frame",
)
replace_once(
    '        render_historical_overview(dataset, filtered_df)',
    '        render_historical_overview(dataset, filtered_df, full_df)',
    "overview route coverage frame",
)

APP.write_text(text, encoding="utf-8")
print("Climate 0.6.5 hourly overview coverage context patch applied successfully")
