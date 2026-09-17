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
    '    active_pressure = fallback_pressure if pressure_mode != "Measured station pressure with fallback median" else measured_median\n'
    '    filtered_df = sidebar_filters(full_df)\n'
    '    if filtered_df.empty:',
    '    active_pressure = fallback_pressure if pressure_mode != "Measured station pressure with fallback median" else measured_median\n'
    '    if page == "Data Quality":\n'
    '        # Source-quality diagnostics must not interpret intentionally excluded\n'
    '        # months/hours as missing provider observations. Audit the complete\n'
    '        # loaded native interval; the global Data filter belongs to analysis.\n'
    '        filtered_df = full_df\n'
    '        st.session_state["_active_filtered_export_df"] = full_df\n'
    '    else:\n'
    '        filtered_df = sidebar_filters(full_df)\n'
    '    if filtered_df.empty:',
    "isolate native Data Quality from analysis filter",
)
replace_once(
    '                    "Timezone", "First source timestamp", "Last source timestamp", "Source records in current view",',
    '                    "Timezone", "First source timestamp", "Last source timestamp", "Source records in loaded interval",',
    "data-quality record label",
)
replace_once(
    '        "This page is calculated from provider-native source observations. Ordinary Climate Analyzer pages use the "\n'
    '        "canonical hourly analysis series; hourly normalization is not used to calculate the diagnostics below."',
    '        "This page is calculated from the complete loaded provider-native source interval. Ordinary Climate Analyzer "\n'
    '        "pages use the canonical hourly analysis series. The global analysis Data filter is intentionally not applied "\n'
    '        "here, so user-excluded months or hours cannot be misclassified as missing source observations."',
    "data-quality filter isolation caption",
)
replace_once(
    '        st.success("No missing values occur in the native measured variables in the current Data filter.")',
    '        st.success("No missing values occur in the native measured variables in the loaded source interval.")',
    "data-quality missing success",
)
replace_once(
    '        st.sidebar.write(f"Source rows in current view: {len(filtered_df):,}")',
    '        st.sidebar.write(f"Source rows loaded: {len(filtered_df):,}")',
    "native sidebar row label",
)

APP.write_text(text, encoding="utf-8")
print("Climate 0.6.5 native Data Quality filter isolation applied successfully")
